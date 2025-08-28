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
			let tempJsonPath: string | undefined;

			try {
				const operationMode = this.getNodeParameter('operationMode', itemIndex, 'tts') as string;
				const outputAsFilePath = this.getNodeParameter('outputAsFilePath', itemIndex, false) as boolean;
				const exaggeration = this.getNodeParameter('exaggeration', itemIndex, 0.5) as number;
				const cfgWeight = this.getNodeParameter('cfgWeight', itemIndex, 0.5) as number;

				// Prepare temp directories
				const tempInputDir = path.join(process.cwd(), 'temp', 'input');
				const tempOutputDir = path.join(process.cwd(), 'temp', 'output');

				// Ensure temp directories exist
				fs.mkdirSync(tempInputDir, { recursive: true });
				fs.mkdirSync(tempOutputDir, { recursive: true });

				// This payload will be written to a JSON file and its path passed to Python
				const payload: IDataObject = {
					mode: operationMode,
					exaggeration: exaggeration,
					cfg_weight: cfgWeight,
				};

				// --- Conditionally add output extension to payload ---
				// If the user wants a specific file path, we tell the Python script
				// what extension to use for its temporary output file.
				if (outputAsFilePath) {
					const finalOutputFilePath = this.getNodeParameter('outputFilePath', itemIndex, '') as string;
					// Add the desired extension to the payload for the Python script
					payload.output_extension = path.extname(finalOutputFilePath);
				}

				// --- Handle Target Voice Input ---
				// This section ensures that the Python script always receives a file path,
				// creating a temporary file if the input is binary data.
				const targetUseFilePath = this.getNodeParameter('targetUseFilePath', itemIndex, false) as boolean;
				let targetVoicePath: string;

				if (targetUseFilePath) {
					targetVoicePath = this.getNodeParameter('targetFilePath', itemIndex, '') as string;
				} else {
					const propertyName = this.getNodeParameter('targetBinaryPropertyName', itemIndex, 'data') as string;
					if (!items[itemIndex].binary?.[propertyName]) {
						throw new NodeOperationError(this.getNode(), `Target Voice binary data not found in property '${propertyName}'.`);
					}
					// Create a temp file from the binary data for the Python script to use
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
						if (!items[itemIndex].binary?.[propertyName]) {
							throw new NodeOperationError(this.getNode(), `Source Audio binary data not found in property '${propertyName}'.`);
						}
						// Create a temp file from the binary data
						sourceAudioPath = await binaryToTempFile(this, itemIndex, propertyName, tempInputDir);
					}
					payload.source_audio_path = sourceAudioPath;
				}

				// --- Write payload to a temporary JSON file ---
				tempJsonPath = path.join(tempInputDir, `payload_${Date.now()}_${itemIndex}.json`);
				fs.writeFileSync(tempJsonPath, JSON.stringify(payload, null, 2));

				// --- Execute Python Script ---
				const condaPythonPath = 'C:\\Users\\2rile\\miniconda3\\envs\\yak_chatterbox_env\\python.exe';
				const pythonScriptPath = path.join(__dirname, 'ChatterboxTTS.py');

				// Pass the path to the JSON file as a command-line argument
				const pythonProcess = spawn(condaPythonPath, [pythonScriptPath, tempJsonPath]);

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

				// The Python script now returns a single line: the path to the temporary output file
				const tempOutputFilePath = scriptOutput.trim();

				if (!tempOutputFilePath || !fs.existsSync(tempOutputFilePath)) {
					throw new NodeOperationError(this.getNode(), `Python script finished, but the output file was not found. Error: ${scriptError}`);
				}

				// --- Handle Final Output ---
				let newItem: INodeExecutionData;

				if (outputAsFilePath) {
					// The user wants the output as a file at a specific location.
					// We need to MOVE the temporary output file to that location.
					const finalOutputFilePath = this.getNodeParameter('outputFilePath', itemIndex, '') as string;
					const finalOutputDir = path.dirname(finalOutputFilePath);
					fs.mkdirSync(finalOutputDir, { recursive: true });

					// Move the file from the temp directory to the final destination
					fs.renameSync(tempOutputFilePath, finalOutputFilePath);

					newItem = {
						json: {
							...items[itemIndex].json,
							message: 'Chatterbox operation successful.',
							outputFilePath: finalOutputFilePath
						},
					};
				} else {
					// The user wants the output as binary data.
					// We read the temporary file into a buffer and then delete it.
					const outputBinaryPropertyName = this.getNodeParameter('outputBinaryPropertyName', itemIndex, 'data') as string;
					const binaryData = await fileToBinary(tempOutputFilePath, outputBinaryPropertyName, this.helpers);

					newItem = {
						json: { ...items[itemIndex].json, message: 'Chatterbox operation successful.' },
						binary: { [outputBinaryPropertyName]: binaryData },
					};

					// Clean up the temporary output file, as it's no longer needed
					fs.unlinkSync(tempOutputFilePath);
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
			} finally {
				// --- Cleanup ---
				// Ensure the temporary JSON payload file is always deleted
				if (tempJsonPath && fs.existsSync(tempJsonPath)) {
					fs.unlinkSync(tempJsonPath);
				}
				// Note: Cleanup of temporary *input* audio files created by `binaryToTempFile`
				// should be handled by that shared function or another process if necessary.
			}
		}
		return [returnData];
	}
}
