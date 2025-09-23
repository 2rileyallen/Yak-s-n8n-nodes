import type {
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    IDataObject,
    IHttpRequestOptions,
} from 'n8n-workflow';
import { NodeConnectionType, NodeOperationError } from 'n8n-workflow';
import * as path from 'path';
import * as fs from 'fs';
import WebSocket from 'ws';
import { binaryToTempFile } from '../../SharedFunctions/binaryToTempFile';
import { fileToBinary } from '../../SharedFunctions/fileToBinary';

/**
 * Parses a .bat config file to extract environment variables.
 * @param filePath The absolute path to the .bat config file.
 * @returns An object containing the key-value pairs of the variables.
 */
function parseConfigBat(filePath: string): { [key: string]: string } {
    const config: { [key: string]: string } = {};
    if (!fs.existsSync(filePath)) {
        throw new Error(`Configuration file not found at: ${filePath}. Please run the setup script.`);
    }
    const fileContent = fs.readFileSync(filePath, 'utf-8');
    const lines = fileContent.split(/\r?\n/);
    const regex = /^SET "([^"]+)=([^"]+)"/;

    for (const line of lines) {
        const match = line.match(regex);
        if (match) {
            config[match[1]] = match[2];
        }
    }
    return config;
}


export class IndexTTS2 implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Yak - IndexTTS2',
        name: 'indexTts2',
        group: ['transform'],
        version: 1,
        description: 'Generates expressive speech with advanced voice cloning and emotion control using IndexTTS2.',
        defaults: {
            name: 'Yak - IndexTTS2',
        },
        inputs: [NodeConnectionType.Main],
        outputs: [NodeConnectionType.Main],
        properties: [
            // --- Section 1: Core Inputs ---
            {
                displayName: 'Text to Synthesize',
                name: 'text',
                type: 'string',
                default: '',
                typeOptions: {
                    multiline: true,
                },
                placeholder: 'Enter your script here. Use tags like <emotion> and <break> for performance control.',
                description: 'The script to convert to speech. Use tags like `<emotion>`, `<break>`, `<prosody>`, and `<emphasis>` for fine-grained control.',
                required: true,
            },

            // --- Section 2: Voice & Global Emotion ---
            {
                displayName: '--- Target Voice ---',
                name: 'targetVoiceNotice',
                type: 'notice',
                default: '',
            },
            {
                displayName: 'Use Voice Reference File Path',
                name: 'voiceUseFilePath',
                type: 'boolean',
                default: true,
                description: 'Toggle to use a direct file path for the voice reference audio. Uncheck to use binary data from a previous node.',
            },
            {
                displayName: 'Voice Reference File Path',
                name: 'voiceFilePath',
                type: 'string',
                default: '',
                displayOptions: { show: { voiceUseFilePath: [true] } },
                placeholder: '/path/to/voice_sample.wav',
                required: true,
            },
            {
                displayName: 'Voice Reference Binary Property',
                name: 'voiceBinaryPropertyName',
                type: 'string',
                default: 'data',
                displayOptions: { show: { voiceUseFilePath: [false] } },
                description: 'The name of the binary property containing the voice reference audio.',
            },
            {
                displayName: 'Set Global Emotion By',
                name: 'globalEmotionType',
                type: 'options',
                options: [
                    { name: 'None (Default Behavior)', value: 'none' },
                    { name: 'Emotion Text Prompt', value: 'text' },
                    { name: 'Manual Emotion Vector', value: 'vector' },
                ],
                default: 'none',
                description: 'Optionally set a baseline emotion for the entire script. This is overridden by any `<emotion>` tags in the text.',
            },
            {
                displayName: 'Emotion Text Prompt',
                name: 'globalEmotionText',
                type: 'string',
                default: '',
                displayOptions: { show: { globalEmotionType: ['text'] } },
                typeOptions: { multiline: true },
                placeholder: 'He spoke with a sense of quiet urgency.',
                description: 'A descriptive phrase to guide the overall emotion.',
            },
            {
                displayName: 'Global Emotion Vector',
                name: 'globalEmotionVector',
                type: 'collection',
                placeholder: 'Add Emotion',
                default: {},
                displayOptions: { show: { globalEmotionType: ['vector'] } },
                description: 'Sets the baseline emotion intensity.',
                options: [
                    { displayName: 'Happy', name: 'happy', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Angry', name: 'angry', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Sad', name: 'sad', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Afraid', name: 'afraid', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Disgusted', name: 'disgusted', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Melancholic', name: 'melancholic', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Surprised', name: 'surprised', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                    { displayName: 'Calm', name: 'calm', type: 'number', typeOptions: { minValue: 0.0, maxValue: 1.0 }, default: 0.0 },
                ],
            },

            // --- Section 3: Output Settings ---
            {
                displayName: '--- Output Settings ---',
                name: 'outputSettingsNotice',
                type: 'notice',
                default: '',
            },
            {
                displayName: 'Output as File Path',
                name: 'outputAsFilePath',
                type: 'boolean',
                default: true,
                description: 'Whether to save the final audio to a specified file path. Uncheck to output as binary data.',
            },
            {
                displayName: 'Output File Path',
                name: 'outputFilePath',
                type: 'string',
                default: '',
                displayOptions: { show: { outputAsFilePath: [true] } },
                placeholder: '/path/to/final_audio.wav',
                required: true,
            },
            {
                displayName: 'Output Binary Property Name',
                name: 'outputBinaryPropertyName',
                type: 'string',
                default: 'data',
                displayOptions: { show: { outputAsFilePath: [false] } },
                description: 'The name to give the output binary property.',
            },

            // --- Section 4: Advanced ---
             {
                displayName: '--- Advanced ---',
                name: 'advancedNotice',
                type: 'notice',
                default: '',
            },
            {
                displayName: 'Enable Randomness',
                name: 'enableRandomness',
                type: 'boolean',
                default: false,
                description: 'Whether to introduce natural-sounding variations to the performance. Warning: May slightly reduce the accuracy of the voice cloning.',
            },
        ],
    };

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];

        // --- Get User-Specific Paths ---
        const repoRoot = path.join(__dirname, '..', '..', '..');
        const config = parseConfigBat(path.join(repoRoot, 'local_config.bat'));
        if (!config.PROJECT_PATH) {
            throw new NodeOperationError(this.getNode(), 'Could not parse PROJECT_PATH from local_config.bat.');
        }
        const tempInputDir = path.join(config.PROJECT_PATH, 'temp', 'input');
        fs.mkdirSync(tempInputDir, { recursive: true });

        for (let i = 0; i < items.length; i++) {
            const filesToCleanup: string[] = [];
            try {
                // --- 1. Gather Parameters & Prepare Payload ---
                const payload: IDataObject = {
                    text: this.getNodeParameter('text', i, '') as string,
                    use_random: this.getNodeParameter('enableRandomness', i, false) as boolean,
                };

                const voiceUseFilePath = this.getNodeParameter('voiceUseFilePath', i, true) as boolean;
                if (voiceUseFilePath) {
                    payload.voice_ref_path = path.resolve(this.getNodeParameter('voiceFilePath', i, '') as string);
                } else {
                    const propertyName = this.getNodeParameter('voiceBinaryPropertyName', i, 'data') as string;
                    if (!items[i].binary?.[propertyName]) {
                        throw new NodeOperationError(this.getNode(), `Voice reference binary data not found in property '${propertyName}' on item ${i}.`);
                    }
                    payload.voice_ref_path = await binaryToTempFile(this, i, propertyName, tempInputDir);
                    filesToCleanup.push(payload.voice_ref_path as string);
                }

                const globalEmotionType = this.getNodeParameter('globalEmotionType', i, 'none') as string;
                if (globalEmotionType === 'vector') {
                    const vectorValues = this.getNodeParameter('globalEmotionVector.globalEmotionVectorValues', i, {}) as IDataObject;
                    payload.global_emotion_type = 'vector';
                    payload.global_emotion_value = [
                        vectorValues.happy ?? 0.0, vectorValues.angry ?? 0.0, vectorValues.sad ?? 0.0, vectorValues.afraid ?? 0.0,
                        vectorValues.disgusted ?? 0.0, vectorValues.melancholic ?? 0.0, vectorValues.surprised ?? 0.0, vectorValues.calm ?? 0.0
                    ];
                } else if (globalEmotionType === 'text') {
                    payload.global_emotion_type = 'text';
                    payload.global_emotion_value = this.getNodeParameter('globalEmotionText', i, '') as string;
                }

                // --- 2. Submit Job to Gatekeeper ---
                const requestOptions: IHttpRequestOptions = {
                    method: 'POST',
                    url: 'http://127.0.0.1:7863/execute', // Port for IndexTTS2 Gatekeeper
                    body: payload,
                    json: true,
                };
                const initialResponse = (await this.helpers.httpRequest(requestOptions)) as { status: string; job_id: string };
                const jobId = initialResponse.job_id;
                if (!jobId) {
                    throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a job_id', { itemIndex: i });
                }

                // --- 3. Wait for Result via WebSocket ---
                const finalResult = await new Promise<any>((resolve, reject) => {
                    const ws = new WebSocket(`ws://127.0.0.1:7863/ws/${jobId}`);
                    const timeout = setTimeout(() => {
                        try { ws.close(); } catch {}
                        reject(new NodeOperationError(this.getNode(), 'Job timed out after 20 minutes.', { itemIndex: i }));
                    }, 20 * 60 * 1000);

                    ws.on('message', (data: WebSocket.Data) => {
                        clearTimeout(timeout);
                        try {
                            const wsPayload = JSON.parse(data.toString());
                            ws.close();
                            resolve(wsPayload);
                        } catch {
                            reject(new NodeOperationError(this.getNode(), 'Invalid JSON from Gatekeeper WebSocket.', { itemIndex: i }));
                        }
                    });
                    ws.on('error', (err: Error) => {
                        clearTimeout(timeout);
                        reject(new NodeOperationError(this.getNode(), `WebSocket error: ${err.message}`, { itemIndex: i }));
                    });
                });

                if (finalResult?.error) {
                    throw new NodeOperationError(this.getNode(), `Gatekeeper error: ${finalResult.error}`, { itemIndex: i });
                }

                const tempResultPath = path.resolve(finalResult?.filePath);
                if (!tempResultPath || !fs.existsSync(tempResultPath)) {
                    throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a valid result file path.', { itemIndex: i });
                }

                // --- 4. Finalize Output ---
                const output: INodeExecutionData = { json: items[i].json, pairedItem: { item: i } };
                const outputAsFilePath = this.getNodeParameter('outputAsFilePath', i, true) as boolean;
                if (outputAsFilePath) {
                    const userFinalOutputPath = path.resolve(this.getNodeParameter('outputFilePath', i, '') as string);
                    fs.mkdirSync(path.dirname(userFinalOutputPath), { recursive: true });
                    fs.renameSync(tempResultPath, userFinalOutputPath);
                    output.json.filePath = userFinalOutputPath;
                } else {
                    const outputBinaryPropertyName = this.getNodeParameter('outputBinaryPropertyName', i, 'data') as string;
                    const binary = await fileToBinary(tempResultPath, outputBinaryPropertyName, this.helpers);
                    output.binary = { [outputBinaryPropertyName]: binary };
                    filesToCleanup.push(tempResultPath);
                }
                returnData.push(output);

            } catch (error) {
                 if (this.continueOnFail()) {
                    returnData.push({ json: { ...items[i].json, error: (error as Error).message }, pairedItem: { item: i } });
                    continue;
                }
                throw error;
            } finally {
                 filesToCleanup.forEach(filePath => {
                    if (fs.existsSync(filePath)) {
                        try { fs.unlinkSync(filePath); }
                        catch (e) { console.error(`Failed to cleanup temp file: ${filePath}`, e); }
                    }
                });
            }
        } // --- End of item loop ---

        return [returnData];
    }
}

