import type {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	IDataObject,
} from 'n8n-workflow';
import { NodeConnectionType, NodeOperationError } from 'n8n-workflow';
import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { binaryToTempFile } from '../../SharedFunctions/binaryToTempFile';
import { fileToBinary } from '../../SharedFunctions/fileToBinary';

export class ChatterboxTTS implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Yak - ChatterboxTTS',
		name: 'yakChatterboxtts',
		group: ['transform'],
		version: 1,
		description: 'Performs Text-to-Speech or Voice Conversion using Chatterbox AI.',
		defaults: {
			name: 'Yak - ChatterboxTTS',
		},
		inputs: [NodeConnectionType.Main],
		outputs: [NodeConnectionType.Main],
		properties: [
			{
				displayName: 'Operation Mode',
				name: 'operationMode',
				type: 'options',
				options: [
					{
						name: 'Text-to-Speech',
						value: 'tts',
					},
					{
						name: 'Voice Conversion',
						value: 'vc',
					},
				],
				default: 'tts',
				description: 'Choose whether to generate speech from text or convert the voice in an audio file.',
			},

			// --- Output Settings ---
			{
				displayName: 'Output as File Path',
				name: 'outputAsFilePath',
				type: 'boolean',
				default: true,
				description: 'Whether to save the output to a specified file path. Uncheck to output as binary data.',
			},
			{
				displayName: 'Output File Path',
				name: 'outputFilePath',
				type: 'string',
				default: '',
				displayOptions: { show: { outputAsFilePath: [true] } },
				placeholder: '/path/to/output.wav',
				description: 'The full file path to save the generated audio.',
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

			// --- Text Input (TTS mode) ---
			{
				displayName: '--- Text Input ---',
				name: 'textInputNotice',
				type: 'notice',
				default: '',
				displayOptions: {
					show: {
						operationMode: ['tts'],
					},
				},
			},
			{
				displayName: 'Text to Speak',
				name: 'text',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						operationMode: ['tts'],
					},
				},
				placeholder: 'Enter text here',
				description: 'The text to convert to speech.',
				required: true,
			},

			// --- Source Audio Input (VC mode) ---
			{
				displayName: '--- Source Audio ---',
				name: 'sourceAudioNotice',
				type: 'notice',
				default: '',
				displayOptions: {
					show: {
						operationMode: ['vc'],
					},
				},
			},
			{
				displayName: 'Use File Path',
				name: 'sourceUseFilePath',
				type: 'boolean',
				default: true,
				displayOptions: {
					show: {
						operationMode: ['vc'],
					},
				},
			},
			{
				displayName: 'File Path',
				name: 'sourceFilePath',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						operationMode: ['vc'],
						sourceUseFilePath: [true],
					},
				},
				placeholder: 'C:\\path\\to\\audio.mp3',
				description: 'The full file path to the source audio.',
				required: true,
			},
			{
				displayName: 'Binary Property Name',
				name: 'sourceBinaryPropertyName',
				type: 'string',
				default: 'data',
				displayOptions: {
					show: {
						operationMode: ['vc'],
						sourceUseFilePath: [false],
					},
				},
				description: 'The name of the binary property containing the source audio.',
			},

			// --- Target Voice Input (both modes) ---
			{
				displayName: '--- Target Voice ---',
				name: 'targetVoiceNotice',
				type: 'notice',
				default: '',
			},
			{
				displayName: 'Use File Path',
				name: 'targetUseFilePath',
				type: 'boolean',
				default: true,
			},
			{
				displayName: 'File Path',
				name: 'targetFilePath',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						targetUseFilePath: [true],
					},
				},
				placeholder: 'C:\\path\\to\\voice.wav',
				description: 'The full file path to the target voice audio.',
				required: true,
			},
			{
				displayName: 'Binary Property Name',
				name: 'targetBinaryPropertyName',
				type: 'string',
				default: 'data',
				displayOptions: {
					show: {
						targetUseFilePath: [false],
					},
				},
				description: 'The name of the binary property containing the target voice audio.',
			},

			// --- Parameters ---
			{
				displayName: '--- Parameters ---',
				name: 'parametersNotice',
				type: 'notice',
				default: '',
			},
			{
				displayName: 'Speech Intensity',
				name: 'exaggeration',
				type: 'number',
				typeOptions: {
					minValue: 0.0,
					maxValue: 1.0,
				},
				default: 0.5,
				description: 'Controls the emotional exaggeration of the speech. Default: 0.5',
			},
			{
				displayName: 'Pacing Control',
				name: 'cfgWeight',
				type: 'number',
				typeOptions: {
					minValue: 0.0,
					maxValue: 1.0,
				},
				default: 0.5,
				description: 'Controls the pacing and stability of the speech. Default: 0.5',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			try {
				const operationMode = this.getNodeParameter('operationMode', itemIndex, 'tts') as string;
				const outputAsFilePath = this.getNodeParameter('outputAsFilePath', itemIndex, false) as boolean;
				const exaggeration = this.getNodeParameter('exaggeration', itemIndex, 0.5) as number;
				const cfgWeight = this.getNodeParameter('cfgWeight', itemIndex, 0.5) as number;

				// Prepare temp directories
				const tempInputDir = path.join(process.cwd(), 'temp', 'input');
				const tempOutputDir = path.join(process.cwd(), 'temp', 'output');

				// Ensure temp directories exist
				if (!fs.existsSync(tempInputDir)) {
					fs.mkdirSync(tempInputDir, { recursive: true });
				}
				if (!fs.existsSync(tempOutputDir)) {
					fs.mkdirSync(tempOutputDir, { recursive: true });
				}

				const payload: IDataObject = {
					mode: operationMode,
					exaggeration: exaggeration,
					cfg_weight: cfgWeight,
				};

				// --- Handle Target Voice Input ---
				const targetUseFilePath = this.getNodeParameter('targetUseFilePath', itemIndex, false) as boolean;
				let targetVoicePath: string;

				if (targetUseFilePath) {
					targetVoicePath = this.getNodeParameter('targetFilePath', itemIndex, '') as string;
				} else {
					const propertyName = this.getNodeParameter('targetBinaryPropertyName', itemIndex, 'data') as string;
					const binaryData = items[itemIndex].binary?.[propertyName];
					if (!binaryData) {
						throw new NodeOperationError(this.getNode(), `Target Voice binary data not found in property '${propertyName}'.`);
					}
					targetVoicePath = await binaryToTempFile(this, itemIndex, propertyName, tempInputDir);
				}
				payload.target_voice_path = targetVoicePath;

				// --- Handle Mode-Specific Inputs ---
				if (operationMode === 'tts') {
					payload.text = this.getNodeParameter('text', itemIndex, '') as string;
				} else if (operationMode === 'vc') {
					const sourceUseFilePath = this.getNodeParameter('sourceUseFilePath', itemIndex, false) as boolean;
					let sourceAudioPath: string;

					if (sourceUseFilePath) {
						sourceAudioPath = this.getNodeParameter('sourceFilePath', itemIndex, '') as string;
					} else {
						const propertyName = this.getNodeParameter('sourceBinaryPropertyName', itemIndex, 'data') as string;
						const binaryData = items[itemIndex].binary?.[propertyName];
						if (!binaryData) {
							throw new NodeOperationError(this.getNode(), `Source Audio binary data not found in property '${propertyName}'.`);
						}
						sourceAudioPath = await binaryToTempFile(this, itemIndex, propertyName, tempInputDir);
					}
					payload.source_audio_path = sourceAudioPath;
				}

				// --- Handle Output Path ---
				if (outputAsFilePath) {
					payload.output_file_path = this.getNodeParameter('outputFilePath', itemIndex, '') as string;
				} else {
					// Generate temp output path for binary return
					payload.output_file_path = path.join(tempOutputDir, `output_${Date.now()}.wav`);
				}

				// --- Execute Python Script ---
				const condaPythonPath = 'C:\\Users\\2rile\\miniconda3\\envs\\yak_chatterbox_env\\python.exe';
				const pythonScriptPath = path.join(__dirname, 'ChatterboxTTS.py');

				const pythonProcess = spawn(condaPythonPath, [pythonScriptPath]);

				pythonProcess.stdin.write(JSON.stringify(payload));
				pythonProcess.stdin.end();

				let scriptOutput = '';
				let scriptError = '';

				for await (const chunk of pythonProcess.stdout) {
					scriptOutput += chunk;
				}
				for await (const chunk of pythonProcess.stderr) {
					scriptError += chunk;
				}

				const exitCode = await new Promise(resolve => pythonProcess.on('close', resolve));

				if (exitCode !== 0) {
					throw new NodeOperationError(this.getNode(), `Python script exited with code ${exitCode}: ${scriptError}`);
				}

				const result = JSON.parse(scriptOutput);

				if (result.status === 'error') {
					throw new NodeOperationError(this.getNode(), `Python script error: ${result.message}`);
				}

				// --- Handle Output ---
				let newItem: INodeExecutionData;

				if (outputAsFilePath) {
					// Return file path in JSON
					newItem = {
						json: { 
							...items[itemIndex].json, 
							message: result.message,
							outputFilePath: result.output_file_path 
						},
					};
				} else {
					// Convert output file to binary
					const outputBinaryPropertyName = this.getNodeParameter('outputBinaryPropertyName', itemIndex, 'data') as string;
					const binaryData = await fileToBinary(result.output_file_path, outputBinaryPropertyName, this.helpers);
					
					newItem = {
						json: { ...items[itemIndex].json, message: result.message },
						binary: { [outputBinaryPropertyName]: binaryData },
					};

					// Clean up temp output file
					if (fs.existsSync(result.output_file_path)) {
						fs.unlinkSync(result.output_file_path);
					}
				}

				returnData.push(newItem);

			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({ 
						json: this.getInputData(itemIndex)[0].json, 
						error: new NodeOperationError(this.getNode(), String(error)), 
						pairedItem: itemIndex 
					});
					continue;
				}
				throw error;
			}
		}
		return [returnData];
	}
}