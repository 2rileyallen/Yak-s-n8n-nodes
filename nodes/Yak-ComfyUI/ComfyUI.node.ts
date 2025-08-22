import {
	IExecuteFunctions,
	ILoadOptionsFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	INodePropertyOptions,
	IHttpRequestOptions,
	NodeConnectionType,
	NodeOperationError,
	IDataObject,
} from 'n8n-workflow';
import WebSocket from 'ws';
import * as path from 'path';
import { promises as fs } from 'fs';
import { fileToBinary } from '../../SharedFunctions/fileToBinary';
import { binaryToTempFile } from '../../SharedFunctions/binaryToTempFile';


// Manifest structure interfaces for type safety
interface IWorkflowInManifest {
	name: string;
	value: string;
	uiFile: string;
	workflowFile: string;
	dependenciesFile: string;
}

interface IManifest {
	workflows: IWorkflowInManifest[];
}

// Interface for a UI property that includes our custom 'mapsTo' key
interface ICustomNodeProperty extends IDataObject {
	name: string;
	mapsTo?: string;
	default?: any;
}


export class ComfyUI implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Yak ComfyUI',
		name: 'yakComfyUi',
		group: ['transform'],
		version: 1,
		description: 'Triggers a workflow in a local ComfyUI instance via the Gatekeeper service.',
		defaults: {
			name: 'Yak ComfyUI',
		},
		inputs: [NodeConnectionType.Main],
		outputs: [NodeConnectionType.Main],
		properties: [
			// ----------------------------------
			//      Callback Settings
			// ----------------------------------
			{
				displayName: '--- Callback Settings ---',
				name: 'callbackSettingsNotice',
				type: 'notice',
				default:
					'Choose how to receive the result. Use WebSocket to wait for the result in this workflow, or use a Webhook to trigger a new workflow when the job is done.',
			},
			{
				displayName: 'Use Webhook',
				name: 'useWebhook',
				type: 'boolean',
				default: false,
				description:
					'Whether to send the result to a webhook URL instead of waiting for it. This allows the current workflow to continue immediately.',
			},
			{
				displayName: 'Webhook URL',
				name: 'webhookUrl',
				type: 'string',
				default: '',
				displayOptions: { show: { useWebhook: [true] } },
				placeholder: 'https://your-n8n-instance/webhook/comfyui-results',
				description: 'The URL to which the Gatekeeper will POST the final result.',
				required: true,
			},

			// ----------------------------------
			//      Workflow Settings
			// ----------------------------------
			{
				displayName: '--- Workflow Settings ---',
				name: 'workflowSettingsNotice',
				type: 'notice',
				default: 'Select a workflow and provide the required inputs.',
			},
			{
				displayName: 'Workflow',
				name: 'selectedWorkflow',
				type: 'options',
				typeOptions: {
					loadOptionsMethod: 'getWorkflows',
				},
				default: '',
				description: 'Select the ComfyUI workflow to execute.',
				required: true,
			},
			// All other properties are now loaded dynamically from the workflow's ui_inputs.json
		],
	};

	constructor() {
		void this.loadAndAppendDynamicProperties();
	}

	// --- Static Path and File Helpers ---

	private static getNodeDir(): string {
		return path.join(__dirname);
	}

	private static getRepoRoot(): string {
		return path.join(__dirname, '..', '..');
	}

	private static getSharedVolumePath(subfolder: 'input' | 'output'): string {
		return path.join(ComfyUI.getRepoRoot(), 'temp', subfolder);
	}

	private static async pathExists(p: string): Promise<boolean> {
		try {
			await fs.access(p);
			return true;
		} catch {
			return false;
		}
	}

	private static async readJson<T = any>(filePath: string): Promise<T> {
		const raw = await fs.readFile(filePath, 'utf-8');
		return JSON.parse(raw) as T;
	}

	// --- Dynamic Property Loading Methods ---

	methods = {
		loadOptions: {
			async getWorkflows(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
				const manifestPath = path.join(ComfyUI.getNodeDir(), 'manifest.json');
				try {
					const manifest = await ComfyUI.readJson<IManifest>(manifestPath);
					if (!manifest.workflows || manifest.workflows.length === 0) {
						throw new Error('No workflows found in manifest.json.');
					}
					return manifest.workflows.map((workflow) => ({
						name: workflow.name,
						value: workflow.value,
						description: `Execute the ${workflow.name} workflow`,
					}));
				} catch (error) {
					throw new NodeOperationError(
						this.getNode(),
						`Failed to load workflows from manifest: ${(error as Error).message}`,
						{ itemIndex: 0 },
					);
				}
			},
		},
	};

	private async loadAndAppendDynamicProperties() {
		try {
			const nodeDir = ComfyUI.getNodeDir();
			const manifestPath = path.join(nodeDir, 'manifest.json');
			const manifest = await ComfyUI.readJson<IManifest>(manifestPath);

			for (const workflow of manifest.workflows) {
				const uiInputsPath = path.join(nodeDir, workflow.uiFile);
				if (!(await ComfyUI.pathExists(uiInputsPath))) {
					console.warn(`UI file not found for workflow '${workflow.name}': ${uiInputsPath}`);
					continue;
				}

				try {
					const uiConfig = await ComfyUI.readJson<{ properties?: any[] }>(uiInputsPath);
					const props = uiConfig?.properties ?? [];

					for (const prop of props) {
						const dynamicProperty = {
							...prop,
							displayOptions: {
								...(prop.displayOptions || {}),
								show: {
									...(prop.displayOptions?.show || {}),
									selectedWorkflow: [workflow.value],
								},
							},
						};
						this.description.properties.push(dynamicProperty);
					}
				} catch (e) {
					console.error(
						`Failed to read or parse ui_inputs.json for workflow '${workflow.name}':`,
						(e as Error).message,
					);
				}
			}
		} catch (error) {
			console.error('Failed to load dynamic properties from manifest:', (error as Error).message);
		}
	}

	// --- Workflow Execution Logic ---

	private static async waitForWebSocketResult(
		executeFunctions: IExecuteFunctions,
		jobId: string,
	): Promise<any> {
		return new Promise<any>((resolve, reject) => {
			const ws = new WebSocket(`ws://127.0.0.1:8189/ws/${jobId}`);
			const timeout = setTimeout(() => {
				ws.close();
				reject(
					new NodeOperationError(
						executeFunctions.getNode(),
						'Job timed out. No response from Gatekeeper WebSocket after 10 minutes.',
					),
				);
			}, 600000); // 10 minutes

			ws.on('message', (data) => {
				clearTimeout(timeout);
				ws.close();
				try {
					resolve(JSON.parse(data.toString()));
				} catch (e) {
					reject(
						new NodeOperationError(
							executeFunctions.getNode(),
							'Failed to parse WebSocket message from Gatekeeper.',
						),
					);
				}
			});

			ws.on('error', (err) => {
				clearTimeout(timeout);
				reject(
					new NodeOperationError(
						executeFunctions.getNode(),
						`WebSocket connection error: ${err.message}`,
					),
				);
			});

			ws.on('close', () => {
				clearTimeout(timeout);
			});
		});
	}

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		let tempFiles: string[] = [];

		const tempInputPath = ComfyUI.getSharedVolumePath('input');
		await fs.mkdir(tempInputPath, { recursive: true });

		const nodeDir = ComfyUI.getNodeDir();
		const manifestPath = path.join(nodeDir, 'manifest.json');
		const manifest = await ComfyUI.readJson<IManifest>(manifestPath);

		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			try {
				const selectedWorkflowValue = this.getNodeParameter('selectedWorkflow', itemIndex) as string;
				if (!selectedWorkflowValue) {
					throw new NodeOperationError(this.getNode(), 'No workflow selected.', { itemIndex });
				}

				const workflowInfo = manifest.workflows.find((w) => w.value === selectedWorkflowValue);
				if (!workflowInfo) {
					throw new NodeOperationError(
						this.getNode(),
						`Selected workflow '${selectedWorkflowValue}' not found in manifest.`,
						{ itemIndex },
					);
				}

				const [workflowFile, uiFile] = await Promise.all([
					ComfyUI.readJson(path.join(nodeDir, workflowInfo.workflowFile)),
					ComfyUI.readJson(path.join(nodeDir, workflowInfo.uiFile)),
				]);

				const workflowTemplate = workflowFile.workflow || workflowFile;
				const rawUserInputs: IDataObject = {};
				const mappedInputs: IDataObject = {};
				const dynamicProperties = (uiFile.properties || []) as ICustomNodeProperty[];

				// Step 1: Gather all raw values from the UI controls
				for (const prop of dynamicProperties) {
					try {
						rawUserInputs[prop.name] = this.getNodeParameter(prop.name, itemIndex, prop.default ?? '');
					} catch (e) {
						// Ignore if a conditional property is not present
					}
				}

				// Step 2: Process raw inputs and map them to their final keys using 'mapsTo'
				for (const prop of dynamicProperties) {
					if (prop.mapsTo) {
						const mapsToKey = prop.mapsTo;
						let valueToMap: any;

						// This logic is now generic and robust, handling all cases correctly.
						if (prop.name.endsWith('UseFilePath')) {
							// This is a boolean toggle; its value is used by other properties but not mapped itself.
							continue;
						} else if (prop.name.endsWith('FilePath')) {
							const prefix = prop.name.replace('FilePath', '');
							const useFilePathToggle = rawUserInputs[`${prefix}UseFilePath`] as boolean;
							if (useFilePathToggle === true) {
								valueToMap = rawUserInputs[prop.name];
							}
						} else if (prop.name.endsWith('BinaryPropertyName')) {
							const prefix = prop.name.replace('BinaryPropertyName', '');
							const useFilePathToggle = rawUserInputs[`${prefix}UseFilePath`] as boolean;

							if (useFilePathToggle === false) {
								// This logic is for INPUT media files that need conversion
								if (prop.name.startsWith('input')) {
									const binaryPropName = rawUserInputs[prop.name] as string;
									const tempFilePath = await binaryToTempFile(this, itemIndex, binaryPropName, tempInputPath);
									tempFiles.push(tempFilePath);
									valueToMap = tempFilePath;
								}
							}
						} else {
							// For all other properties (prompts, numbers, etc.), map their value directly.
							valueToMap = rawUserInputs[prop.name];
						}

						if (valueToMap !== undefined) {
							mappedInputs[mapsToKey] = valueToMap;
						}
					}
				}
				// **FIXED**: Separately and reliably map the output binary property name if needed.
				if (rawUserInputs.outputAsFilePath === false) {
					mappedInputs.outputBinaryPropertyName = rawUserInputs.outputBinaryPropertyName;
				}


				const useWebhook = this.getNodeParameter('useWebhook', itemIndex, false) as boolean;
				const gatekeeperPayload: IDataObject = {
					n8n_execution_id: this.getExecutionId(),
					callback_type: useWebhook ? 'webhook' : 'websocket',
					workflow_template: workflowTemplate,
					user_inputs: mappedInputs, // Send the clean, mapped inputs
					mappings: uiFile.mappings,
				};

				if (useWebhook) {
					gatekeeperPayload.callback_url = this.getNodeParameter('webhookUrl', itemIndex) as string;
				}

				const initialOptions: IHttpRequestOptions = {
					method: 'POST',
					url: 'http://127.0.0.1:8189/execute',
					body: gatekeeperPayload,
					json: true,
					timeout: 120000,
				};

				const { job_id: jobId } = (await this.helpers.httpRequest(initialOptions)) as { job_id: string };

				if (useWebhook) {
					returnData.push({
						json: { status: 'submitted', job_id: jobId, workflow: selectedWorkflowValue },
						pairedItem: { item: itemIndex },
					});
					continue;
				}

				const finalResult = await ComfyUI.waitForWebSocketResult(this, jobId);

				const processResult = async (result: any) => {
					const tempFilePath = result.data;
					if (!tempFilePath) {
						throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a valid file path.', { itemIndex });
					}

					const outputAsFilePath = mappedInputs.outputAsFilePath as boolean;

					if (outputAsFilePath) {
						const finalPath = mappedInputs.outputFilePath as string;
						await fs.mkdir(path.dirname(finalPath), { recursive: true });
						await fs.rename(tempFilePath, finalPath);
						return { json: { filePath: finalPath }, pairedItem: { item: itemIndex } };
					} else {
						const propertyName = mappedInputs.outputBinaryPropertyName as string;
						const binaryData = await fileToBinary(tempFilePath, propertyName, this.helpers);
						await fs.unlink(tempFilePath);
						return { json: {}, binary: { [propertyName]: binaryData }, pairedItem: { item: itemIndex } };
					}
				};

				if (finalResult.format === 'multiple' && Array.isArray(finalResult.results)) {
					for (const result of finalResult.results) {
						returnData.push(await processResult(result));
					}
				} else {
					returnData.push(await processResult(finalResult));
				}
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({ json: { error: (error as Error).message }, pairedItem: { item: itemIndex } });
					continue;
				}
				throw error;
			} finally {
				for (const file of tempFiles) {
					await fs.unlink(file).catch(e => console.error(`Failed to delete temp file: ${file}`, e));
				}
				tempFiles = [];
			}
		}

		return [returnData];
	}
}
