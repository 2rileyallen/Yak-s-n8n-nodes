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

// --- Text Processing Functions ---
// These functions are now integrated directly into the node to pre-process the script.

function normalizeApostrophes(text: string): string {
	return text.replace(/’/g, "'"); // convert curly apostrophe to straight
}

function expandContractions(text: string): string {
	const contractions: { [key: string]: string } = {
		"here's": "here is", "it's": "it is", "that's": "that is", "what's": "what is",
		"where's": "where is", "when's": "when is", "who's": "who is", "how's": "how is",
		"there's": "there is", "he's": "he is", "she's": "she is", "let's": "let us",
		"can't": "cannot", "won't": "will not", "don't": "do not", "doesn't": "does not",
		"didn't": "did not", "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
		"wouldn't": "would not", "shouldn't": "should not", "couldn't": "could not",
		"isn't": "is not", "aren't": "are not", "wasn't": "was not", "weren't": "were not",
		"I'm": "I am", "you're": "you are", "we're": "we are", "they're": "they are",
		"I've": "I have", "you've": "you have", "we've": "we have", "they've": "they have",
		"I'll": "I will", "you'll": "you will", "he'll": "he will", "she'll": "she will",
		"we'll": "we will", "they'll": "they will", "I'd": "I would", "you'd": "you would",
		"he'd": "he would", "she'd": "she would", "we'd": "we would", "they'd": "they would"
	};
	let expandedText = text;
	for (const [contraction, expansion] of Object.entries(contractions)) {
		const regex = new RegExp(`\\b${contraction}\\b`, "gi");
		expandedText = expandedText.replace(regex, (match) => {
			if (match[0] === match[0].toUpperCase()) {
				return expansion.charAt(0).toUpperCase() + expansion.slice(1);
			}
			return expansion;
		});
	}
	return expandedText;
}

function cleanText(text: string): string {
	return text
		.replace(/['"]/g, " ")    // replace leftover apostrophes/quotes with spaces
		.replace(/\\/g, "")       // remove backslashes
		.replace(/\s+/g, " ")     // normalize spaces
		.trim();
}

function processAndChunkScript(text: string, sentencesPerChunk = 3): string[] {
	const normalized = normalizeApostrophes(text);
	const expanded = expandContractions(normalized);
	const sanitized = cleanText(expanded);
	const sentences = sanitized
		.split(/(?<=[.!?])\s+/)
		.map(s => s.trim())
		.filter(s => s.length > 0);

	const chunks: string[] = [];
	for (let i = 0; i < sentences.length; i += sentencesPerChunk) {
		const chunk = sentences.slice(i, i + sentencesPerChunk);
		chunks.push(chunk.join(" "));
	}
	return chunks;
}


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
						name: 'Text-to-Speech (from Script)',
						value: 'tts',
					},
					{
						name: 'Voice Conversion',
						value: 'vc',
					},
				],
				default: 'tts',
				description: 'Choose whether to generate speech from a script or convert an existing audio file.',
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
				displayName: 'Script',
				name: 'text',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						operationMode: ['tts'],
					},
				},
				typeOptions: {
					multiline: true,
				},
				placeholder: 'Enter your full script here...',
				description: 'The full text script to convert to speech. The node will automatically clean and chunk the text.',
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
		const temporaryChunkPaths: string[] = [];
		const filesToCleanup: string[] = [];

		// We assume a single item defines the entire job (e.g., one script, one voice).
		// All parameters are read from the first item.
		const itemIndex = 0;

		try {
			// --- 1. Get all shared parameters for the job ---
			const operationMode = this.getNodeParameter('operationMode', itemIndex, 'tts') as string;
			const exaggeration = this.getNodeParameter('exaggeration', itemIndex, 0.5) as number;
			const cfgWeight = this.getNodeParameter('cfgWeight', itemIndex, 0.5) as number;

			const tempInputDir = path.join(process.cwd(), 'temp', 'input');
			const tempOutputDir = path.join(process.cwd(), 'temp', 'output');
			fs.mkdirSync(tempInputDir, { recursive: true });
			fs.mkdirSync(tempOutputDir, { recursive: true });

			// --- 2. Prepare the base payload and voice file ---
			const basePayload: IDataObject = {
				mode: operationMode,
				exaggeration: exaggeration,
				cfg_weight: cfgWeight,
			};

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
			basePayload.target_voice_path = targetVoicePath;

			// --- 3. Determine the list of tasks to execute ---
			const tasks: IDataObject[] = [];

			if (operationMode === 'tts') {
				const fullScript = this.getNodeParameter('text', itemIndex, '') as string;
				const textChunks = processAndChunkScript(fullScript);
				for (const chunk of textChunks) {
					tasks.push({ ...basePayload, text: chunk });
				}
			} else if (operationMode === 'vc') {
				// For VC, each input item is a separate task
				for (let i = 0; i < items.length; i++) {
					const sourceUseFilePath = this.getNodeParameter('sourceUseFilePath', i, false) as boolean;
					let sourceAudioPath: string;
					if (sourceUseFilePath) {
						sourceAudioPath = this.getNodeParameter('sourceFilePath', i, '') as string;
					} else {
						const propertyName = this.getNodeParameter('sourceBinaryPropertyName', i, 'data') as string;
						if (!items[i].binary?.[propertyName]) {
							throw new NodeOperationError(this.getNode(), `Source Audio binary data not found on item ${i}.`);
						}
						sourceAudioPath = await binaryToTempFile(this, i, propertyName, tempInputDir);
					}
					tasks.push({ ...basePayload, source_audio_path: sourceAudioPath });
				}
			}

			// --- 4. Execute all tasks (Python calls) ---
			for (let i = 0; i < tasks.length; i++) {
				const payload = tasks[i];
				let tempJsonPath: string | undefined;

				try {
					tempJsonPath = path.join(tempInputDir, `payload_${Date.now()}_${i}.json`);
					fs.writeFileSync(tempJsonPath, JSON.stringify(payload, null, 2));
					filesToCleanup.push(tempJsonPath);

					const condaPythonPath = 'C:\\Users\\2rile\\miniconda3\\envs\\yak_chatterbox_env\\python.exe';
					const pythonScriptPath = path.join(__dirname, 'ChatterboxTTS.py');
					const pythonProcess = spawn(condaPythonPath, [pythonScriptPath, tempJsonPath]);

					let scriptOutput = '';
					let scriptError = '';
					for await (const chunk of pythonProcess.stdout) { scriptOutput += chunk; }
					for await (const chunk of pythonProcess.stderr) { scriptError += chunk; }
					const exitCode = await new Promise(resolve => pythonProcess.on('close', resolve));

					if (exitCode !== 0) {
						throw new NodeOperationError(this.getNode(), `Python script failed on chunk ${i}: ${scriptError}`);
					}

					const tempOutputFilePath = scriptOutput.trim();
					if (!tempOutputFilePath || !fs.existsSync(tempOutputFilePath)) {
						throw new NodeOperationError(this.getNode(), `Python script finished for chunk ${i}, but the output file was not found.`);
					}
					temporaryChunkPaths.push(tempOutputFilePath);

				} catch (error) {
					// Re-throw to be caught by the main try/catch block
					throw error;
				}
			} // --- End of task loop ---


			// --- 5. Combine chunks and finalize output ---
			if (temporaryChunkPaths.length === 0) {
				return [[]]; // No output was generated
			}

			let finalCombinedPath: string;
			filesToCleanup.push(...temporaryChunkPaths);

			if (temporaryChunkPaths.length === 1) {
				finalCombinedPath = temporaryChunkPaths[0];
			} else {
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
					throw new NodeOperationError(this.getNode(), `ffmpeg failed to combine chunks: ${ffmpegError}`);
				}
				finalCombinedPath = combinedOutputPath;
			}

			// --- 6. Prepare the final return data ---
			const outputAsFilePath = this.getNodeParameter('outputAsFilePath', 0, true) as boolean;
			let finalItem: INodeExecutionData;

			if (outputAsFilePath) {
				const finalUserPath = this.getNodeParameter('outputFilePath', 0, '') as string;
				fs.mkdirSync(path.dirname(finalUserPath), { recursive: true });
				fs.renameSync(finalCombinedPath, finalUserPath);
				finalItem = {
					json: { ...items[0].json, message: 'Chatterbox operation successful.', outputFilePath: finalUserPath },
				};
			} else {
				const propertyName = this.getNodeParameter('outputBinaryPropertyName', 0, 'data') as string;
				const binaryData = await fileToBinary(finalCombinedPath, propertyName, this.helpers);
				filesToCleanup.push(finalCombinedPath);
				finalItem = {
					json: { ...items[0].json, message: 'Chatterbox operation successful.' },
					binary: { [propertyName]: binaryData },
				};
			}
			return [this.helpers.returnJsonArray([finalItem])];

		} catch (error) {
			if (this.continueOnFail()) {
				return [this.helpers.returnJsonArray([{
					json: items[0].json,
					error: new NodeOperationError(this.getNode(), String(error)),
					pairedItem: { item: 0 }
				}])];
			}
			throw error;
		} finally {
			// --- 7. Final Cleanup ---
			filesToCleanup.forEach(filePath => {
				if (fs.existsSync(filePath)) {
					try { fs.unlinkSync(filePath); }
					catch (e) { console.error(`Failed to cleanup temp file: ${filePath}`, e); }
				}
			});
		}
	}
}

