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
				displayName: 'Combine Outputs',
				name: 'combineOutputs',
				type: 'boolean',
				default: false,
				description: 'Whether to combine the audio generated from all input items into a single file.',
			},
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
		const combineOutputs = this.getNodeParameter('combineOutputs', 0, false) as boolean;
		const temporaryChunkPaths: string[] = [];

		// --- Loop to generate all individual chunks ---
		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			let tempJsonPath: string | undefined;

			try {
				const operationMode = this.getNodeParameter('operationMode', itemIndex, 'tts') as string;
				const outputAsFilePath = this.getNodeParameter('outputAsFilePath', itemIndex, false) as boolean;
				const exaggeration = this.getNodeParameter('exaggeration', itemIndex, 0.5) as number;
				const cfgWeight = this.getNodeParameter('cfgWeight', itemIndex, 0.5) as number;

				const tempInputDir = path.join(process.cwd(), 'temp', 'input');
				const tempOutputDir = path.join(process.cwd(), 'temp', 'output');
				fs.mkdirSync(tempInputDir, { recursive: true });
				fs.mkdirSync(tempOutputDir, { recursive: true });

				const payload: IDataObject = {
					mode: operationMode,
					exaggeration: exaggeration,
					cfg_weight: cfgWeight,
				};

				if (outputAsFilePath) {
					const finalOutputFilePath = this.getNodeParameter('outputFilePath', itemIndex, '') as string;
					payload.output_extension = path.extname(finalOutputFilePath);
				}

				const targetUseFilePath = this.getNodeParameter('targetUseFilePath', itemIndex, false) as boolean;
				let targetVoicePath: string;
				if (targetUseFilePath) {
					targetVoicePath = this.getNodeParameter('targetFilePath', itemIndex, '') as string;
				} else {
					const propertyName = this.getNodeParameter('targetBinaryPropertyName', itemIndex, 'data') as string;
					if (!items[itemIndex].binary?.[propertyName]) {
						throw new NodeOperationError(this.getNode(), `Target Voice binary data not found in property '${propertyName}'.`);
					}
					targetVoicePath = await binaryToTempFile(this, itemIndex, propertyName, tempInputDir);
				}
				payload.target_voice_path = targetVoicePath;

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
						sourceAudioPath = await binaryToTempFile(this, itemIndex, propertyName, tempInputDir);
					}
					payload.source_audio_path = sourceAudioPath;
				}

				tempJsonPath = path.join(tempInputDir, `payload_${Date.now()}_${itemIndex}.json`);
				fs.writeFileSync(tempJsonPath, JSON.stringify(payload, null, 2));

				const condaPythonPath = 'C:\\Users\\2rile\\miniconda3\\envs\\yak_chatterbox_env\\python.exe';
				const pythonScriptPath = path.join(__dirname, 'ChatterboxTTS.py');
				const pythonProcess = spawn(condaPythonPath, [pythonScriptPath, tempJsonPath]);

				let scriptOutput = '';
				let scriptError = '';
				for await (const chunk of pythonProcess.stdout) { scriptOutput += chunk; }
				for await (const chunk of pythonProcess.stderr) { scriptError += chunk; }
				const exitCode = await new Promise(resolve => pythonProcess.on('close', resolve));

				if (exitCode !== 0) {
					throw new NodeOperationError(this.getNode(), `Python script exited with code ${exitCode}: ${scriptError}`);
				}

				const tempOutputFilePath = scriptOutput.trim();
				if (!tempOutputFilePath || !fs.existsSync(tempOutputFilePath)) {
					throw new NodeOperationError(this.getNode(), `Python script finished, but the output file was not found. Error: ${scriptError}`);
				}

				// --- Handle individual chunk based on combine setting ---
				if (combineOutputs) {
					temporaryChunkPaths.push(tempOutputFilePath);
				} else {
					// Not combining, so process and return each file immediately
					let newItem: INodeExecutionData;
					if (outputAsFilePath) {
						const finalOutputFilePath = this.getNodeParameter('outputFilePath', itemIndex, '') as string;
						fs.mkdirSync(path.dirname(finalOutputFilePath), { recursive: true });
						fs.renameSync(tempOutputFilePath, finalOutputFilePath);
						newItem = {
							json: { ...items[itemIndex].json, message: 'Chatterbox operation successful.', outputFilePath: finalOutputFilePath },
						};
					} else {
						const propertyName = this.getNodeParameter('outputBinaryPropertyName', itemIndex, 'data') as string;
						const binaryData = await fileToBinary(tempOutputFilePath, propertyName, this.helpers);
						fs.unlinkSync(tempOutputFilePath); // Clean up the temp file
						newItem = {
							json: { ...items[itemIndex].json, message: 'Chatterbox operation successful.' },
							binary: { [propertyName]: binaryData },
						};
					}
					returnData.push(newItem);
				}

			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({
						json: this.getInputData(itemIndex)[0].json,
						error: new NodeOperationError(this.getNode(), String(error)),
						pairedItem: itemIndex
					});
					continue;
				}
				// Cleanup any chunks created so far if we're in combine mode and an error occurs
				if (combineOutputs) { temporaryChunkPaths.forEach(p => fs.existsSync(p) && fs.unlinkSync(p)); }
				throw error;
			} finally {
				if (tempJsonPath && fs.existsSync(tempJsonPath)) { fs.unlinkSync(tempJsonPath); }
			}
		} // --- End of item loop ---


		// --- Post-Loop Combination Logic ---
		if (combineOutputs && temporaryChunkPaths.length > 0) {
			let finalFilePath: string;
			const filesToCleanup: string[] = [...temporaryChunkPaths];

			try {
				if (temporaryChunkPaths.length === 1) {
					finalFilePath = temporaryChunkPaths[0];
				} else {
					// Combine multiple chunks using ffmpeg
					const tempInputDir = path.join(process.cwd(), 'temp', 'input');
					const tempOutputDir = path.join(process.cwd(), 'temp', 'output');
					const fileListPath = path.join(tempInputDir, `filelist_${Date.now()}.txt`);
					filesToCleanup.push(fileListPath);

					const fileListContent = temporaryChunkPaths
						.map(p => `file '${path.resolve(p).replace(/\\/g, '/')}'`)
						.join('\n');
					fs.writeFileSync(fileListPath, fileListContent);

					const outputExtension = path.extname(temporaryChunkPaths[0]) || '.mp3';
					const combinedOutputPath = path.join(tempOutputDir, `combined_${Date.now()}${outputExtension}`);

					const ffmpegProcess = spawn('ffmpeg', ['-f', 'concat', '-safe', '0', '-i', fileListPath, '-c', 'copy', combinedOutputPath]);

					let ffmpegError = '';
					for await (const chunk of ffmpegProcess.stderr) { ffmpegError += chunk; }
					const exitCode = await new Promise(resolve => ffmpegProcess.on('close', resolve));

					if (exitCode !== 0) {
						throw new NodeOperationError(this.getNode(), `ffmpeg failed with code ${exitCode}: ${ffmpegError}`);
					}
					finalFilePath = combinedOutputPath;
				}

				// Process the final combined file
				const outputAsFilePath = this.getNodeParameter('outputAsFilePath', 0, false) as boolean;
				let newItem: INodeExecutionData;

				if (outputAsFilePath) {
					const finalUserPath = this.getNodeParameter('outputFilePath', 0, '') as string;
					fs.mkdirSync(path.dirname(finalUserPath), { recursive: true });
					fs.renameSync(finalFilePath, finalUserPath);
					newItem = {
						json: { ...items[0].json, message: 'Chatterbox combination successful.', outputFilePath: finalUserPath },
					};
				} else {
					const propertyName = this.getNodeParameter('outputBinaryPropertyName', 0, 'data') as string;
					const binaryData = await fileToBinary(finalFilePath, propertyName, this.helpers);
					filesToCleanup.push(finalFilePath); // Add final combined file to cleanup
					newItem = {
						json: { ...items[0].json, message: 'Chatterbox combination successful.' },
						binary: { [propertyName]: binaryData },
					};
				}
				returnData.push(newItem);

			} finally {
				// Final cleanup of all temporary files
				filesToCleanup.forEach(filePath => {
					if (fs.existsSync(filePath)) {
						try { fs.unlinkSync(filePath); }
						catch (e) { console.error(`Failed to cleanup temp file: ${filePath}`, e); }
					}
				});
			}
		}

		return [returnData];
	}
}
