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
				displayName: 'Use Webhook (Fire and Forget)',
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
			{
				displayName: 'Webhook Output Format',
				name: 'webhookOutputFormat',
				type: 'options',
				displayOptions: { show: { useWebhook: [true] } },
				options: [
					{
						name: 'File Path',
						value: 'filePath',
						description: 'The webhook payload will contain the absolute path to the output file.',
					},
					{
						name: 'Binary Data',
						value: 'binary',
						description: 'The webhook will receive the raw output file as binary data.',
					},
				],
				default: 'filePath',
				description: 'Choose the format for the data sent to the webhook.',
			},
			{
				displayName: 'Webhook Output File Path',
				name: 'webhookOutputFilePath',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						useWebhook: [true],
						webhookOutputFormat: ['filePath'],
					},
				},
				placeholder: '/data/final_images/output.png',
				description:
					'The final, absolute path where the Gatekeeper should save the file before sending the webhook.',
				required: true,
			},

			// ----------------------------------
			//      Output Settings (WebSocket ONLY)
			// ----------------------------------
			{
				displayName: '--- Output Settings (WebSocket only) ---',
				name: 'outputSettingsNotice',
				type: 'notice',
				default: 'These settings apply ONLY if not using a webhook.',
				displayOptions: { show: { useWebhook: [false] } },
			},
			{
				displayName: 'Output Format',
				name: 'nodeOutputFormat',
				type: 'options',
				displayOptions: { show: { useWebhook: [false] } },
				options: [
					{
						name: 'File Path',
						value: 'filePath',
						description: 'Output the absolute path to the generated file.',
					},
					{
						name: 'Binary Data',
						value: 'binary',
						description: 'Output the generated file as n8n binary data.',
					},
				],
				default: 'binary',
				description: 'The desired format for the output from this node.',
			},
			{
				displayName: 'Output File Path',
				name: 'outputFilePath',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						useWebhook: [false],
						nodeOutputFormat: ['filePath'],
					},
				},
				placeholder: '/data/my_images/output.png',
				description:
					'The full file path where the generated file will be moved after completion.',
				required: true,
			},
			{
				displayName: 'Output Binary Property Name',
				name: 'outputBinaryPropertyName',
				type: 'string',
				default: 'data',
				displayOptions: {
					show: {
						useWebhook: [false],
						nodeOutputFormat: ['binary'],
					},
				},
				description: 'The name to give the output binary property.',
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
			{
				displayName: 'Batch Size',
				name: 'batchSize',
				type: 'number',
				typeOptions: { minValue: 1 },
				default: 1,
				description: 'How many images to generate for each input item.',
			},
			// Dynamic workflow-specific properties are appended here by the constructor
		],
	};

	constructor() {
		// Preload and append dynamic properties from the manifest at node load time
		void this.loadAndAppendDynamicProperties();
	}

	// --- Static Path and File Helpers ---

	private static getNodeDir(): string {
		// Resolves the path to the directory containing this node file
		return path.join(__dirname);
	}

	private static getRepoRoot(): string {
		// Assumes the node is in /nodes/Yak-ComfyUI/
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
			/**
			 * Dynamically populates the Workflow dropdown by reading the manifest.json file.
			 */
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

	/**
	 * Reads the manifest, finds all UI definition files, and appends their properties
	 * to the node's description, making them dynamically visible based on workflow selection.
	 */
	private async loadAndAppendDynamicProperties() {
		try {
			const nodeDir = ComfyUI.getNodeDir();
			const manifestPath = path.join(nodeDir, 'manifest.json');
			const manifest = await ComfyUI.readJson<IManifest>(manifestPath);

			for (const workflow of manifest.workflows) {
				const uiInputsPath = path.join(nodeDir, workflow.uiFile);

				if (!(await ComfyUI.pathExists(uiInputsPath))) {
					// eslint-disable-next-line no-console
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
								show: {
									selectedWorkflow: [workflow.value],
								},
							},
						};
						this.description.properties.push(dynamicProperty);
					}
				} catch (e) {
					// eslint-disable-next-line no-console
					console.error(
						`Failed to read or parse ui_inputs.json for workflow '${workflow.name}':`,
						(e as Error).message,
					);
				}
			}
		} catch (error) {
			// eslint-disable-next-line no-console
			console.error('Failed to load dynamic properties from manifest:', (error as Error).message);
		}
	}

	// --- Workflow Execution Logic ---

	// Utility to set a deep property in an object using a dot-notation path
	private static setByPath(obj: any, pathStr: string, value: any) {
		const parts = pathStr.split('.');
		let ref = obj;
		for (let i = 0; i < parts.length - 1; i++) {
			const key = parts[i];
			if (ref[key] === undefined || ref[key] === null) ref[key] = {};
			ref = ref[key];
		}
		ref[parts[parts.length - 1]] = value;
	}

	/**
	 * Applies user inputs from the n8n UI to the raw ComfyUI workflow JSON.
	 */
	private static applyUserInputsToWorkflow(
		workflow: any,
		userInputs: IDataObject,
		mappings: Record<string, { nodeId: string; path: string }>,
		batchSize: number,
	): any {
		const modified = JSON.parse(JSON.stringify(workflow));

		for (const [inputName, mapping] of Object.entries(mappings || {})) {
			const { nodeId, path: pathStr } = mapping as { nodeId: string; path: string };
			if (!modified[nodeId]) continue;

			// Special handling for batchSize
			if (inputName === 'batchSize' && pathStr === 'inputs.batch_size') {
				ComfyUI.setByPath(modified[nodeId], pathStr, batchSize);
				continue;
			}

			// Apply other user inputs
			if (userInputs[inputName] !== undefined) {
				ComfyUI.setByPath(modified[nodeId], pathStr, userInputs[inputName]);
			}
		}

		return modified;
	}

	/**
	 * Connects to the Gatekeeper WebSocket and waits for the final result for a given job ID.
	 * This is a static method to avoid issues with 'this' context inside execute.
	 */
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

		// Ensure temp directories exist
		const tempInputPath = ComfyUI.getSharedVolumePath('input');
		const tempOutputPath = ComfyUI.getSharedVolumePath('output');
		await fs.mkdir(tempInputPath, { recursive: true });
		await fs.mkdir(tempOutputPath, { recursive: true });

		// Load manifest once
		const nodeDir = ComfyUI.getNodeDir();
		const manifestPath = path.join(nodeDir, 'manifest.json');
		const manifest = await ComfyUI.readJson<IManifest>(manifestPath);

		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			try {
				// --- Get Parameters ---
				const selectedWorkflowValue = this.getNodeParameter('selectedWorkflow', itemIndex) as string;
				const batchSize = this.getNodeParameter('batchSize', itemIndex, 1) as number;
				const useWebhook = this.getNodeParameter('useWebhook', itemIndex, false) as boolean;

				if (!selectedWorkflowValue) {
					throw new NodeOperationError(
						this.getNode(),
						'No workflow selected. Please select a workflow from the dropdown.',
						{ itemIndex },
					);
				}

				// --- Load Workflow Config from Manifest ---
				const workflowInfo = manifest.workflows.find((w) => w.value === selectedWorkflowValue);
				if (!workflowInfo) {
					throw new NodeOperationError(
						this.getNode(),
						`Selected workflow '${selectedWorkflowValue}' not found in manifest.`,
						{ itemIndex },
					);
				}

				const workflowJsonPath = path.join(nodeDir, workflowInfo.workflowFile);
				const uiInputsPath = path.join(nodeDir, workflowInfo.uiFile);

				const [workflowFile, uiFile] = await Promise.all([
					ComfyUI.readJson(workflowJsonPath),
					ComfyUI.readJson(uiInputsPath),
				]);

				const workflowTemplate = workflowFile.workflow;
				const mappings = uiFile.mappings as Record<string, { nodeId: string; path: string }>;

				// --- Gather Dynamic Inputs ---
				const userInputs: IDataObject = {};
				const dynamicProperties = (uiFile.properties || []) as Array<{ name: string; default?: any }>;
				for (const prop of dynamicProperties) {
					userInputs[prop.name] = this.getNodeParameter(prop.name, itemIndex, prop.default ?? '');
				}

				// --- Prepare Workflow and Gatekeeper Payload ---
				const finalWorkflow = ComfyUI.applyUserInputsToWorkflow(
					workflowTemplate,
					userInputs,
					mappings,
					batchSize,
				);

				const gatekeeperPayload: IDataObject = {
					n8n_execution_id: this.getExecutionId(),
					callback_type: useWebhook ? 'webhook' : 'websocket',
					workflow_json: finalWorkflow,
				};

				if (useWebhook) {
					gatekeeperPayload.callback_url = this.getNodeParameter('webhookUrl', itemIndex) as string;
					gatekeeperPayload.output_format = this.getNodeParameter(
						'webhookOutputFormat',
						itemIndex,
						'filePath',
					) as string;
					if (gatekeeperPayload.output_format === 'filePath') {
						gatekeeperPayload.output_path = this.getNodeParameter(
							'webhookOutputFilePath',
							itemIndex,
						) as string;
					}
				}

				// --- Submit Job to Gatekeeper ---
				const initialOptions: IHttpRequestOptions = {
					method: 'POST',
					url: 'http://127.0.0.1:8189/execute',
					body: gatekeeperPayload,
					json: true,
					timeout: 120000, // 2 minutes for initial submission
				};

				const initialResponse = (await this.helpers.httpRequest(initialOptions)) as {
					job_id: string;
				};
				const jobId = initialResponse.job_id;

				// --- Handle Response ---
				if (useWebhook) {
					// Fire-and-forget mode
					returnData.push({
						json: { status: 'submitted', job_id: jobId, workflow: selectedWorkflowValue },
						pairedItem: { item: itemIndex },
					});
					continue; // Move to the next item
				}

				// WebSocket mode: Wait for completion
				const finalResult = await ComfyUI.waitForWebSocketResult(this, jobId);

				// --- Process WebSocket Result ---
				const nodeOutputFormat = this.getNodeParameter(
					'nodeOutputFormat',
					itemIndex,
					'binary',
				) as string;

				const processResult = async (result: any) => {
					const tempFilePath = result.data; // Gatekeeper ALWAYS returns a temp file path
					if (!tempFilePath) {
						throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a valid file path.', {
							itemIndex,
						});
					}

					if (nodeOutputFormat === 'filePath') {
						const finalPath = this.getNodeParameter('outputFilePath', itemIndex) as string;
						await fs.mkdir(path.dirname(finalPath), { recursive: true });
						await fs.rename(tempFilePath, finalPath);
						return { json: { filePath: finalPath }, pairedItem: { item: itemIndex } };
					} else {
						// 'binary' format
						const propertyName = this.getNodeParameter(
							'outputBinaryPropertyName',
							itemIndex,
							'data',
						) as string;
						const binaryData = await fileToBinary(tempFilePath, propertyName, this.helpers);
						// Clean up the temp file after converting to binary
						await fs.unlink(tempFilePath);
						return {
							json: {},
							binary: { [propertyName]: binaryData },
							pairedItem: { item: itemIndex },
						};
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
			}
		}

		return [returnData];
	}
}
