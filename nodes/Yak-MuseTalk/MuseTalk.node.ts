import {
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    NodeConnectionType,
    NodeOperationError,
    IHttpRequestOptions,
    IDataObject,
} from 'n8n-workflow';
import WebSocket from 'ws';
import * as path from 'path';
import { promises as fs } from 'fs';

// Import shared helper functions
import { binaryToTempFile } from '../../SharedFunctions/binaryToTempFile';
import { fileToBinary } from '../../SharedFunctions/fileToBinary';

export class MuseTalk implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Yak - MuseTalk',
        name: 'yakMusetalk',
        icon: 'file:museTalkNode.svg',
        group: ['transform'],
        version: 1,
        description: 'Generate lip-synced videos using MuseTalk via a local Gatekeeper service.',
        defaults: {
            name: 'Yak - MuseTalk',
        },
        inputs: [NodeConnectionType.Main],
        outputs: [NodeConnectionType.Main],
        properties: [
            // ----------------------------------
            //       Callback Settings
            // ----------------------------------
            {
                displayName: '--- Callback Settings ---',
                name: 'callbackSettingsNotice',
                type: 'notice',
                default: 'Choose how to receive the result. Use WebSocket to wait for the result in this workflow, or use a Webhook to trigger a new workflow when the job is done.',
            },
            {
                displayName: 'Use Webhook (Fire and Forget)',
                name: 'useWebhook',
                type: 'boolean',
                default: false,
                description: 'Whether to send the result to a webhook URL instead of waiting for it. This allows the current workflow to continue immediately.',
            },
            {
                displayName: 'Webhook URL',
                name: 'webhookUrl',
                type: 'string',
                default: '',
                displayOptions: { show: { useWebhook: [true] } },
                placeholder: 'https://your-n8n-instance/webhook/musetalk-results',
                description: 'The URL to which the Gatekeeper will POST the final result.',
                required: true,
            },
            // ** NEW **: Webhook-specific output options
            {
                displayName: 'Webhook Output as File Path',
                name: 'webhookAsFilePath',
                type: 'boolean',
                default: true,
                displayOptions: { show: { useWebhook: [true] } },
                description: 'Whether the webhook should receive a file path. Uncheck to receive binary data.',
            },
            {
                displayName: 'Webhook Output File Path',
                name: 'webhookOutputFilePath',
                type: 'string',
                default: '',
                displayOptions: {
                    show: {
                        useWebhook: [true],
                        webhookAsFilePath: [true],
                    },
                },
                placeholder: '/path/to/webhook_output.mp4',
                description: 'The final, absolute path where the Gatekeeper should save the video before sending the webhook.',
                required: true,
            },
            {
                displayName: 'Webhook Sends Binary Data',
                name: 'webhookBinaryOutput',
                type: 'boolean',
                default: false,
                displayOptions: {
                    show: {
                        useWebhook: [true],
                        webhookAsFilePath: [false],
                    },
                },
                description: 'Enable to have the webhook POST the raw video file. If disabled, it will POST JSON with a file path.',
            },


            // ----------------------------------
            //       Output Settings (WebSocket ONLY)
            // ----------------------------------
            {
                displayName: '--- Output Settings (WebSocket only) ---',
                name: 'outputSettingsNotice',
                type: 'notice',
                default: 'These settings apply ONLY if not using a webhook.',
                displayOptions: { show: { useWebhook: [false] } },
            },
            {
                displayName: 'Output as File Path',
                name: 'outputAsFilePath',
                type: 'boolean',
                default: true,
                displayOptions: { show: { useWebhook: [false] } },
                description: 'Whether to save the output to a specified file path. Uncheck to output as binary data.',
            },
            {
                displayName: 'Output File Path',
                name: 'outputFilePath',
                type: 'string',
                default: '',
                displayOptions: {
                    show: {
                        outputAsFilePath: [true],
                        useWebhook: [false],
                    },
                },
                placeholder: '/path/to/output.mp4',
                description: 'The full file path where the generated video will be saved.',
                required: true,
            },
            {
                displayName: 'Output Binary Property Name',
                name: 'outputBinaryPropertyName',
                type: 'string',
                default: 'data',
                displayOptions: {
                    show: {
                        outputAsFilePath: [false],
                        useWebhook: [false],
                    },
                },
                description: 'The name to give the output binary property for the generated video.',
            },

            // ... (rest of the properties are unchanged) ...
            {
                displayName: '--- Input Audio ---',
                name: 'inputAudioNotice',
                type: 'notice',
                default: '',
            },
            {
                displayName: 'Use File Path',
                name: 'audioUseFilePath',
                type: 'boolean',
                default: true,
                description: 'Use a file path for the input audio. Uncheck to use binary data from a previous node.',
            },
            {
                displayName: 'File Path',
                name: 'audioFilePath',
                type: 'string',
                default: '',
                displayOptions: { show: { audioUseFilePath: [true] } },
                placeholder: '/path/to/audio.wav',
                description: 'Absolute path to the input audio file.',
                required: true,
            },
            {
                displayName: 'Binary Property Name',
                name: 'audioBinaryPropertyName',
                type: 'string',
                default: 'data',
                displayOptions: { show: { audioUseFilePath: [false] } },
                description: 'Name of the binary property containing the input audio data.',
                required: true,
            },
            {
                displayName: '--- Input Video ---',
                name: 'inputVideoNotice',
                type: 'notice',
                default: '',
            },
            {
                displayName: 'Use File Path',
                name: 'videoUseFilePath',
                type: 'boolean',
                default: true,
                description: 'Use a file path for the input video. Uncheck to use binary data from a previous node.',
            },
            {
                displayName: 'File Path',
                name: 'videoFilePath',
                type: 'string',
                default: '',
                displayOptions: { show: { videoUseFilePath: [true] } },
                placeholder: '/path/to/video.mp4',
                description: 'Absolute path to the input video file.',
                required: true,
            },
            {
                displayName: 'Binary Property Name',
                name: 'videoBinaryPropertyName',
                type: 'string',
                default: 'data',
                displayOptions: { show: { videoUseFilePath: [false] } },
                description: 'Name of the binary property containing the input video data.',
                required: true,
            },
            {
                displayName: '--- Inference Parameters ---',
                name: 'inferenceParamsNotice',
                type: 'notice',
                default: 'Adjust parameters for MuseTalk generation.',
            },
            {
                displayName: 'BBox Shift (px)',
                name: 'bbox_shift',
                type: 'number',
                default: 0,
            },
            {
                displayName: 'Extra Margin',
                name: 'extra_margin',
                type: 'number',
                typeOptions: { minValue: 0, maxValue: 40 },
                default: 10,
            },
            {
                displayName: 'Parsing Mode',
                name: 'parsing_mode',
                type: 'options',
                options: [
                    { name: 'Jaw', value: 'jaw' },
                    { name: 'Raw', value: 'raw' },
                ],
                default: 'jaw',
            },
            {
                displayName: 'Left Cheek Width',
                name: 'left_cheek_width',
                type: 'number',
                typeOptions: { minValue: 20, maxValue: 160 },
                default: 90,
            },
            {
                displayName: 'Right Cheek Width',
                name: 'right_cheek_width',
                type: 'number',
                typeOptions: { minValue: 20, maxValue: 160 },
                default: 90,
            },
        ],
    };

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];

        const repoRoot = path.join(__dirname, '..', '..');
        const tempInputDir = path.join(repoRoot, 'temp', 'input');
        const tempOutputDir = path.join(repoRoot, 'temp', 'output');

        await fs.mkdir(tempInputDir, { recursive: true });
        await fs.mkdir(tempOutputDir, { recursive: true });

        for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
            try {
                const useWebhook = this.getNodeParameter('useWebhook', itemIndex, false) as boolean;

                // --- Handle Inputs ---
                const audioUseFilePath = this.getNodeParameter('audioUseFilePath', itemIndex, true) as boolean;
                let audioPathAbs: string;
                let tempAudioCreated: string | undefined;
                if (audioUseFilePath) {
                    audioPathAbs = path.resolve(this.getNodeParameter('audioFilePath', itemIndex, '') as string);
                } else {
                    const propName = this.getNodeParameter('audioBinaryPropertyName', itemIndex, 'data') as string;
                    audioPathAbs = await binaryToTempFile(this, itemIndex, propName, tempInputDir);
                    tempAudioCreated = audioPathAbs;
                }

                const videoUseFilePath = this.getNodeParameter('videoUseFilePath', itemIndex, true) as boolean;
                let videoPathAbs: string;
                let tempVideoCreated: string | undefined;
                if (videoUseFilePath) {
                    videoPathAbs = path.resolve(this.getNodeParameter('videoFilePath', itemIndex, '') as string);
                } else {
                    const propName = this.getNodeParameter('videoBinaryPropertyName', itemIndex, 'data') as string;
                    videoPathAbs = await binaryToTempFile(this, itemIndex, propName, tempInputDir);
                    tempVideoCreated = videoPathAbs;
                }

                // --- Construct Gatekeeper Payload ---
                const gatekeeperPayload: IDataObject = {
                    audio_path: audioPathAbs,
                    video_path: videoPathAbs,
                    gatekeeper_output_path: path.join(tempOutputDir, `musetalk-${this.getExecutionId()}-${itemIndex}.mp4`),
                    bbox_shift: this.getNodeParameter('bbox_shift', itemIndex, 0),
                    extra_margin: this.getNodeParameter('extra_margin', itemIndex, 10),
                    parsing_mode: this.getNodeParameter('parsing_mode', itemIndex, 'jaw'),
                    left_cheek_width: this.getNodeParameter('left_cheek_width', itemIndex, 90),
                    right_cheek_width: this.getNodeParameter('right_cheek_width', itemIndex, 90),
                };

                if (useWebhook) {
                    gatekeeperPayload.callback_type = 'webhook';
                    gatekeeperPayload.callback_url = this.getNodeParameter('webhookUrl', itemIndex, '') as string;
                    
                    const webhookAsFilePath = this.getNodeParameter('webhookAsFilePath', itemIndex, true) as boolean;
                    if (webhookAsFilePath) {
                        // ** NEW **: Pass the final desired path to the Gatekeeper
                        gatekeeperPayload.user_final_output_path = path.resolve(this.getNodeParameter('webhookOutputFilePath', itemIndex, '') as string);
                        gatekeeperPayload.webhook_binary_output = false;
                    } else {
                        gatekeeperPayload.webhook_binary_output = this.getNodeParameter('webhookBinaryOutput', itemIndex, false) as boolean;
                    }

                } else {
                    gatekeeperPayload.callback_type = 'websocket';
                }

                // --- Submit Job to Gatekeeper ---
                const requestOptions: IHttpRequestOptions = {
                    method: 'POST',
                    url: 'http://127.0.0.1:7861/execute',
                    body: gatekeeperPayload,
                    json: true,
                };
                const initialResponse = (await this.helpers.httpRequest(requestOptions)) as { status: string; job_id: string };
                const jobId = initialResponse.job_id;

                if (!jobId) {
                    throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a job_id', { itemIndex });
                }

                // --- Handle Response Based on Callback Type ---
                if (useWebhook) {
                    returnData.push({ json: { status: 'webhook_sent', jobId: jobId }, pairedItem: { item: itemIndex } });
                } else {
                    const finalResult = await new Promise<any>((resolve, reject) => {
                        const ws = new WebSocket(`ws://127.0.0.1:7861/ws/${jobId}`);
                        const timeout = setTimeout(() => {
                            try { ws.close(); } catch {}
                            reject(new NodeOperationError(this.getNode(), 'Job timed out after 20 minutes.', { itemIndex }));
                        }, 20 * 60 * 1000);

                        ws.on('message', (data: WebSocket.Data) => {
                            clearTimeout(timeout);
                            try {
                                const payload = JSON.parse(data.toString());
                                ws.close();
                                resolve(payload);
                            } catch {
                                reject(new NodeOperationError(this.getNode(), 'Invalid JSON from Gatekeeper WebSocket.', { itemIndex }));
                            }
                        });

                        ws.on('error', (err: Error) => {
                            clearTimeout(timeout);
                            reject(new NodeOperationError(this.getNode(), `WebSocket error: ${err.message}`, { itemIndex }));
                        });
                    });

                    if (finalResult?.error) {
                        throw new NodeOperationError(this.getNode(), `Gatekeeper error: ${finalResult.error}`, { itemIndex });
                    }

                    const tempResultPath = path.resolve(finalResult?.filePath);
                    if (!tempResultPath || !(await fs.stat(tempResultPath).catch(() => false))) {
                        throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a valid result file path.', { itemIndex });
                    }

                    const output: INodeExecutionData = { json: {}, pairedItem: { item: itemIndex } };
                    const outputAsFilePath = this.getNodeParameter('outputAsFilePath', itemIndex, true) as boolean;

                    if (outputAsFilePath) {
                        const userFinalOutputPath = path.resolve(this.getNodeParameter('outputFilePath', itemIndex, '') as string);
                        await fs.mkdir(path.dirname(userFinalOutputPath), { recursive: true });
                        await fs.rename(tempResultPath, userFinalOutputPath);
                        output.json.filePath = userFinalOutputPath;
                    } else {
                        const outputBinaryPropertyName = this.getNodeParameter('outputBinaryPropertyName', itemIndex, 'data') as string;
                        const binary = await fileToBinary(tempResultPath, outputBinaryPropertyName, this.helpers);
                        output.binary = { [outputBinaryPropertyName]: binary };
                        try { await fs.unlink(tempResultPath); } catch {}
                    }
                    returnData.push(output);
                }

                if (tempAudioCreated) { try { await fs.unlink(tempAudioCreated); } catch {} }
                if (tempVideoCreated) { try { await fs.unlink(tempVideoCreated); } catch {} }

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
