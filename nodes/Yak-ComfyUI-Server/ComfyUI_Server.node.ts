import {
    IExecuteFunctions,
    ILoadOptionsFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    INodePropertyOptions,
    NodeConnectionType,
    NodeOperationError,
    IDataObject,
} from 'n8n-workflow';
import WebSocket from 'ws';
import * as path from 'path';
import { promises as fs } from 'fs';
const axios = require('axios');
const FormData = require('form-data');

// --- Interfaces ---
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

interface ICustomNodeProperty extends IDataObject {
    name: string;
    mapsTo?: string;
    default?: any;
}

export class ComfyUI_Server implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Yak ComfyUI Server',
        name: 'yakComfyUiServer',
        group: ['transform'],
        version: 1,
        description: 'Triggers a workflow on a remote ComfyUI instance via a Gatekeeper service.',
        defaults: {
            name: 'Yak ComfyUI Server',
        },
        inputs: [NodeConnectionType.Main],
        outputs: [NodeConnectionType.Main],
        properties: [
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
            },
            {
                displayName: 'Webhook URL',
                name: 'webhookUrl',
                type: 'string',
                default: '',
                displayOptions: { show: { useWebhook: [true] } },
                placeholder: 'https://your-n8n-instance/webhook/comfyui-results',
                required: true,
            },
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
                required: true,
            },
        ],
    };

    constructor() {
        void this.loadAndAppendDynamicProperties();
    }

    // --- Static Path and File Helpers ---
    private static getNodeDir(): string {
        return path.join(__dirname);
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

    private static async getUniqueFinalPath(
        targetPath: string,
        originalFileName: string,
    ): Promise<string> {
        let finalPath: string;
        let isDirectory = false;

        try {
            const stats = await fs.stat(targetPath);
            isDirectory = stats.isDirectory();
        } catch (error) {
            if (path.extname(targetPath) === '') {
                isDirectory = true;
            }
        }

        if (isDirectory) {
            finalPath = path.join(targetPath, originalFileName);
        } else {
            finalPath = targetPath;
        }

        const dir = path.dirname(finalPath);
        await fs.mkdir(dir, { recursive: true });

        if (!(await ComfyUI_Server.pathExists(finalPath))) {
            return finalPath;
        }

        const parsedPath = path.parse(finalPath);
        const baseName = parsedPath.name;
        const ext = parsedPath.ext;
        let counter = 1;
        let uniquePath: string;

        do {
            const newName = `${baseName} (${counter})${ext}`;
            uniquePath = path.join(dir, newName);
            counter++;
        } while (await ComfyUI_Server.pathExists(uniquePath));

        return uniquePath;
    }

    // --- Dynamic Property Loading Methods ---
    methods = {
        loadOptions: {
            async getWorkflows(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                const manifestPath = path.join(ComfyUI_Server.getNodeDir(), 'manifest.json');
                try {
                    const manifest = await ComfyUI_Server.readJson<IManifest>(manifestPath);
                    return manifest.workflows.map((workflow) => ({
                        name: workflow.name,
                        value: workflow.value,
                    }));
                } catch (error) {
                    throw new NodeOperationError(
                        this.getNode(),
                        `Failed to load workflows from manifest: ${(error as Error).message}`,
                    );
                }
            },
        },
    };

    private async loadAndAppendDynamicProperties() {
        try {
            const nodeDir = ComfyUI_Server.getNodeDir();
            const manifestPath = path.join(nodeDir, 'manifest.json');
            const manifest = await ComfyUI_Server.readJson<IManifest>(manifestPath);

            for (const workflow of manifest.workflows) {
                const uiInputsPath = path.join(nodeDir, workflow.uiFile);
                const uiConfig = await ComfyUI_Server.readJson<{ properties?: any[] }>(uiInputsPath);
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
            }
        } catch (error) {
            console.error('Failed to load dynamic properties from manifest:', (error as Error).message);
        }
    }

    // --- WebSocket Connection ---
    // **MODIFIED**: This function now handles the full handshake protocol.
    private static async waitForWebSocketResult(
        wsUrl: string,
        jobId: string,
        headers: IDataObject,
        executeFunctions: IExecuteFunctions,
    ): Promise<any> {
        return new Promise<any>((resolve, reject) => {
            const ws = new WebSocket(`${wsUrl}/ws/${jobId}`, undefined, { headers: headers as any });
            let timeout: NodeJS.Timeout;

            // Resets the timeout. This is called when the connection opens and on every ping.
            const resetTimeout = () => {
                clearTimeout(timeout);
                timeout = setTimeout(() => {
                    ws.close();
                    reject(new NodeOperationError(executeFunctions.getNode(), 'Job timed out. No message or ping received from server.'));
                }, 10800000); // 3-hour timeout
            };

            ws.on('open', () => {
                resetTimeout();
            });

            ws.on('message', (data) => {
                try {
                    const message = JSON.parse(data.toString());

                    // If it's a heartbeat ping from the server, reset our timeout and continue listening.
                    if (message.type === 'ping') {
                        resetTimeout();
                        return;
                    }

                    // It's the final result. Send acknowledgment back to the Gatekeeper.
                    ws.send(JSON.stringify({ status: 'received' }), (err) => {
                        if (err) {
                            // Log if ack fails, but don't stop the workflow, as we have the data.
                            console.error(`Failed to send acknowledgment for job ${jobId}:`, err);
                        }
                    });
                    
                    clearTimeout(timeout);
                    ws.close();
                    resolve(message);

                } catch (e) {
                    clearTimeout(timeout);
                    ws.close();
                    reject(new NodeOperationError(executeFunctions.getNode(), 'Failed to parse WebSocket message.'));
                }
            });

            ws.on('error', (err) => {
                clearTimeout(timeout);
                reject(new NodeOperationError(executeFunctions.getNode(), `WebSocket error: ${err.message}`));
            });

            ws.on('close', () => {
                clearTimeout(timeout);
            });
        });
    }

    // --- Main Execution ---
    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];

        // --- HARDCODED CREDENTIALS ---
        const serverUrl = 'https://gatekeepercomfyuiserver.thetunecanvas.com';
        const headers: IDataObject = {
            'CF-Access-Client-Id': '72df5856f07b7bfc85f0cdb01f933bbe.access',
            'CF-Access-Client-Secret': '6a4ae5dd83bbc93bffab59039efb7ae9a5e002f1c516b8df03a5882850692315',
        };
        // -----------------------------

        const nodeDir = ComfyUI_Server.getNodeDir();
        const manifestPath = path.join(nodeDir, 'manifest.json');
        const manifest = await ComfyUI_Server.readJson<IManifest>(manifestPath);

        for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
            try {
                const selectedWorkflowValue = this.getNodeParameter('selectedWorkflow', itemIndex) as string;
                const workflowInfo = manifest.workflows.find((w) => w.value === selectedWorkflowValue);
                if (!workflowInfo) throw new NodeOperationError(this.getNode(), 'Workflow not found.');

                const [workflowFile, uiFile] = await Promise.all([
                    ComfyUI_Server.readJson(path.join(nodeDir, workflowInfo.workflowFile)),
                    ComfyUI_Server.readJson(path.join(nodeDir, workflowInfo.uiFile)),
                ]);

                const workflowTemplate = workflowFile.workflow || workflowFile;
                const rawUserInputs: IDataObject = {};
                const mappedInputs: IDataObject = {};
                const filesToUpload: { key: string; buffer: Buffer; filename: string }[] = [];
                const dynamicProperties = (uiFile.properties || []) as ICustomNodeProperty[];

                for (const prop of dynamicProperties) {
                    try {
                        rawUserInputs[prop.name] = this.getNodeParameter(prop.name, itemIndex, prop.default ?? '');
                    } catch (e) { /* Ignore conditional property not present */ }
                }

                for (const prop of dynamicProperties) {
                    if (prop.mapsTo) {
                        const mapsToKey = prop.mapsTo;
                        let valueToMap: any;

                        if (prop.name.endsWith('UseFilePath')) continue;
                        
                        if (prop.name.endsWith('FilePath')) {
                            const prefix = prop.name.replace('FilePath', '');
                            if (rawUserInputs[`${prefix}UseFilePath`] === true) {
                                const filePath = rawUserInputs[prop.name] as string;
                                if (!filePath || filePath.trim() === '') {
                                    continue;
                                }
                                const buffer = await fs.readFile(filePath);
                                const filename = path.basename(filePath);
                                filesToUpload.push({ key: mapsToKey, buffer, filename });
                                valueToMap = filename;
                            }
                        } else if (prop.name.endsWith('BinaryPropertyName')) {
                            const prefix = prop.name.replace('BinaryPropertyName', '');
                            if (rawUserInputs[`${prefix}UseFilePath`] === false) {
                                
                                // --- THIS IS THE FIX ---
                                // The check for 'prop.name.startsWith('input')' was too restrictive.
                                // We just need to check if the property is for binary data.
                                const binaryPropName = rawUserInputs[prop.name] as string;
                                const binaryData = this.helpers.assertBinaryData(itemIndex, binaryPropName);
                                const buffer = await this.helpers.getBinaryDataBuffer(itemIndex, binaryPropName);
                                filesToUpload.push({ key: mapsToKey, buffer, filename: binaryData.fileName || 'file' });
                                valueToMap = binaryData.fileName;
                                // --- END OF FIX ---
                            }
                        } else {
                            valueToMap = rawUserInputs[prop.name];
                        }

                        if (valueToMap !== undefined) mappedInputs[mapsToKey] = valueToMap;
                    }
                }

                if (filesToUpload.length > 0) {
                    const form = new FormData();
                    for (const file of filesToUpload) {
                        form.append('files', file.buffer, file.filename);
                    }
                    const uploadResponse = await axios.post(`${serverUrl}/upload`, form, {
                        headers: { ...headers, ...form.getHeaders() },
                    });
                    const filenameMap = uploadResponse.data.filename_map;
                    for (const originalName in filenameMap) {
                        const newName = filenameMap[originalName];
                        for (const mapKey in mappedInputs) {
                            if (mappedInputs[mapKey] === originalName) {
                                mappedInputs[mapKey] = newName;
                            }
                        }
                    }
                }

                const useWebhook = this.getNodeParameter('useWebhook', itemIndex, false) as boolean;
                const executePayload: IDataObject = {
                    n8n_execution_id: this.getExecutionId(),
                    callback_type: useWebhook ? 'webhook' : 'websocket',
                    workflow_template: workflowTemplate,
                    user_inputs: mappedInputs,
                    mappings: uiFile.mappings,
                    output_node_id: uiFile.output_node_id,
                    output_file_filter: uiFile.output_file_filter,
                };

                if (useWebhook) {
                    executePayload.callback_url = this.getNodeParameter('webhookUrl', itemIndex) as string;
                }

                const executeOptions = {
                    method: 'POST',
                    url: `${serverUrl}/execute`,
                    headers,
                    data: executePayload,
                };

                const executeResponse = await axios(executeOptions);
                const { job_id: jobId } = executeResponse.data;

                if (useWebhook) {
                    returnData.push({ json: { status: 'submitted', job_id: jobId }, pairedItem: { item: itemIndex } });
                    continue;
                }

                const wsUrl = serverUrl.replace(/^http/, 'ws');
                const finalResult = await ComfyUI_Server.waitForWebSocketResult(wsUrl, jobId, headers, this);

                // #############################################################
                // #                  --- MODIFIED SECTION ---                   #
                // # The 'processResult' function is updated to handle         #
                // # both file outputs and text/JSON outputs.                  #
                // #############################################################

                const processResult = async (result: any) => {
                    // --- NEW CHECK ---
                    // Check if the result looks like a file (it has 'data' and 'fileName')
                    if (result.data && result.fileName) {
                        // --- EXISTING FILE-HANDLING LOGIC ---
                        const outputAsFilePath = rawUserInputs.outputAsFilePath as boolean;
                        const outputFilePath = rawUserInputs.outputFilePath as string;
                        const outputBinaryPropertyName = rawUserInputs.outputBinaryPropertyName as string;

                        const binaryData = Buffer.from(result.data, 'base64');

                        if (outputAsFilePath) {
                            if (!outputFilePath) {
                                throw new NodeOperationError(this.getNode(), 'An output directory/path must be provided.', { itemIndex });
                            }
                            const finalPath = await ComfyUI_Server.getUniqueFinalPath(outputFilePath, result.fileName);
                            await fs.writeFile(finalPath, binaryData);
                            return { json: { filePath: finalPath }, pairedItem: { item: itemIndex } };
                        } else {
                            const preparedData = await this.helpers.prepareBinaryData(binaryData, result.fileName, result.mimeType);
                            return { json: {}, binary: { [outputBinaryPropertyName]: preparedData }, pairedItem: { item: itemIndex } };
                        }
                    } else {
                        // --- NEW TEXT/JSON-HANDLING LOGIC ---
                        // It's not a file, so just return the entire result object as JSON.
                        // This will contain the text output (e.g., { "text_output": "park" })
                        return { json: result, pairedItem: { item: itemIndex } };
                    }
                };

                // #############################################################
                // #                --- END OF MODIFIED SECTION ---              #
                // #############################################################

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
