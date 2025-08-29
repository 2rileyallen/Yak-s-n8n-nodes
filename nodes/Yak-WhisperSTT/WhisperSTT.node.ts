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

export class WhisperSTT implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Yak - WhisperSTT',
		name: 'yakWhisperSTT',
		icon: 'file:Whisper.svg', // Assuming you will create an icon named Whisper.svg
		group: ['transform'],
		version: 1,
		description: 'Transcribes or translates audio/video files to text using OpenAI\'s Whisper model.',
		defaults: {
			name: 'Yak - WhisperSTT',
		},
		inputs: [NodeConnectionType.Main],
		outputs: [NodeConnectionType.Main],
		properties: [
			// --- Input File ---
			{
				displayName: '--- Input File ---',
				name: 'inputFileNotice',
				type: 'notice',
				default: '',
			},
			{
				displayName: 'Use Input File Path',
				name: 'useInputFilePath',
				type: 'boolean',
				default: true,
				description: 'Whether to use a file path for the input. Uncheck to use binary data from a previous node.',
			},
			{
				displayName: 'Input File Path',
				name: 'inputFilePath',
				type: 'string',
				default: '',
				displayOptions: { show: { useInputFilePath: [true] } },
				placeholder: 'C:\\path\\to\\audio.mp3',
				description: 'The full file path to the audio or video file to transcribe.',
				required: true,
			},
			{
				displayName: 'Input Binary Property',
				name: 'inputBinaryPropertyName',
				type: 'string',
				default: 'data',
				displayOptions: { show: { useInputFilePath: [false] } },
				description: 'The name of the binary property containing the input audio or video.',
				required: true,
			},

			// --- Core Options ---
			{
				displayName: '--- Core Options ---',
				name: 'coreOptionsNotice',
				type: 'notice',
				default: '',
			},
			{
				displayName: 'Model Size',
				name: 'model',
				type: 'options',
				options: [
					{ name: 'Tiny', value: 'tiny' },
					{ name: 'Base', value: 'base' },
					{ name: 'Small', value: 'small' },
					{ name: 'Medium', value: 'medium' },
					{ name: 'Large', value: 'large' },
				],
				default: 'base',
				description: 'Select the model size. Larger models are more accurate but slower and require more VRAM.',
			},
			{
				displayName: 'Task',
				name: 'task',
				type: 'options',
				options: [
					{ name: 'Transcribe', value: 'transcribe' },
					{ name: 'Translate to English', value: 'translate' },
				],
				default: 'transcribe',
				description: 'Choose whether to transcribe in the original language or translate to English.',
			},
			{
				displayName: 'Language',
				name: 'language',
				type: 'string',
				default: 'English',
				placeholder: 'English',
				description: 'Optional. Specify the source language to improve accuracy. Leave blank to auto-detect.',
			},
			{
				displayName: 'Output Detail Level',
				name: 'outputDetail',
				type: 'options',
				options: [
					{
						name: 'Text Only',
						value: 'text_only',
						description: 'Returns only the final transcribed text as a single string.',
					},
					{
						name: 'Segment Timestamps',
						value: 'segment_timestamps',
						description: 'Returns text, language, and segments with start/end times for phrases.',
					},
					{
						name: 'Word-Level Timestamps',
						value: 'word_timestamps',
						description: 'Returns detailed segments including start/end times for every word. Ideal for captions.',
					},
				],
				default: 'segment_timestamps',
				description: 'Select the level of detail for the output.',
			},

			// --- Additional Options ---
			{
				displayName: 'Additional Options',
				name: 'additionalOptions',
				type: 'collection',
				placeholder: 'Add Option',
				default: {},
				options: [
					{
						displayName: 'Initial Prompt',
						name: 'initial_prompt',
						type: 'string',
						typeOptions: { multiLine: true },
						default: '',
						description: 'A prompt to provide context, vocabulary, or spelling, such as names or technical terms. For songs, providing the full lyrics here can greatly improve timestamp accuracy.',
					},
					{
						displayName: 'Temperature',
						name: 'temperature',
						type: 'number',
						default: 0.0,
						description: 'Controls randomness. 0.0 is deterministic. Higher values may be more creative but less factual.',
					},
					{
						displayName: 'Beam Size',
						name: 'beam_size',
						type: 'number',
						typeOptions: {
							minValue: 0,
						},
						default: 5,
						description: 'Number of alternative transcriptions to explore. Higher values can improve accuracy on poor audio at the cost of speed.',
					},
					{
						displayName: 'Aggressive VAD',
						name: 'aggressiveVAD',
						type: 'boolean',
						default: false,
						description: 'Whether to use a more aggressive Voice Activity Detection to filter out non-speech segments.',
					},
				],
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			let tempInputPayloadPath: string | undefined;
			let tempOutputResultPath: string | undefined;

			try {
				// --- Prepare Directories ---
				const tempInputDir = path.join(process.cwd(), 'temp', 'input');
				fs.mkdirSync(tempInputDir, { recursive: true });

				// --- Prepare Payload ---
				const payload: IDataObject = {
					model: this.getNodeParameter('model', itemIndex, 'base') as string,
					task: this.getNodeParameter('task', itemIndex, 'transcribe') as string,
					language: this.getNodeParameter('language', itemIndex, '') as string,
					output_detail: this.getNodeParameter('outputDetail', itemIndex, 'segment_timestamps') as string,
				};

				// Handle Additional Options
				const additionalOptions = this.getNodeParameter('additionalOptions', itemIndex, {}) as IDataObject;
				payload.initial_prompt = additionalOptions.initial_prompt;
				payload.temperature = additionalOptions.temperature;
				payload.beam_size = additionalOptions.beam_size;
				payload.aggressive_vad = additionalOptions.aggressiveVAD;


				// --- Handle Input File ---
				const useInputFilePath = this.getNodeParameter('useInputFilePath', itemIndex, true) as boolean;
				if (useInputFilePath) {
					payload.input_file_path = this.getNodeParameter('inputFilePath', itemIndex, '') as string;
				} else {
					const propertyName = this.getNodeParameter('inputBinaryPropertyName', itemIndex, 'data') as string;
					if (!items[itemIndex].binary?.[propertyName]) {
						throw new NodeOperationError(this.getNode(), `Input binary data not found in property '${propertyName}'.`);
					}
					// Create a temp file from binary data for the Python script
					payload.input_file_path = await binaryToTempFile(this, itemIndex, propertyName, tempInputDir);
				}

				// --- Write payload to temporary JSON file ---
				tempInputPayloadPath = path.join(tempInputDir, `payload_whisper_${Date.now()}_${itemIndex}.json`);
				fs.writeFileSync(tempInputPayloadPath, JSON.stringify(payload, null, 2));

				// --- Execute Python Script ---
				const condaPythonPath = 'C:\\Users\\2rile\\miniconda3\\envs\\yak_whisper_env\\python.exe'; // This path should be configured
				const pythonScriptPath = path.join(__dirname, 'WhisperSTT.py'); // Assumes python script is in the same directory

				const pythonProcess = spawn(condaPythonPath, [pythonScriptPath, tempInputPayloadPath]);

				let scriptOutput = '';
				let scriptError = '';

				for await (const chunk of pythonProcess.stdout) { scriptOutput += chunk; }
				for await (const chunk of pythonProcess.stderr) { scriptError += chunk; }

				const exitCode = await new Promise(resolve => pythonProcess.on('close', resolve));

				if (exitCode !== 0) {
					throw new NodeOperationError(this.getNode(), `Python script exited with code ${exitCode}: ${scriptError}`);
				}

				// The python script returns the path to the temporary output JSON file
				tempOutputResultPath = scriptOutput.trim();

				if (!tempOutputResultPath || !fs.existsSync(tempOutputResultPath)) {
					throw new NodeOperationError(this.getNode(), `Python script finished, but the output file was not found. Stderr: ${scriptError}`);
				}

				// --- Process and Return Results ---
				const resultJsonString = fs.readFileSync(tempOutputResultPath, 'utf8');
				const resultData = JSON.parse(resultJsonString);

				if (resultData.status === 'error') {
					throw new NodeOperationError(this.getNode(), `Error from Python script: ${resultData.message}`);
				}

				const newItem: INodeExecutionData = {
					json: { ...items[itemIndex].json, ...resultData.data },
					binary: {},
				};
				returnData.push(newItem);

			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({
						json: this.getInputData(itemIndex)[0].json,
						error: new NodeOperationError(this.getNode(), String(error)),
						pairedItem: itemIndex,
					});
					continue;
				}
				throw error;
			} finally {
				// --- Cleanup ---
				if (tempInputPayloadPath && fs.existsSync(tempInputPayloadPath)) {
					fs.unlinkSync(tempInputPayloadPath);
				}
				if (tempOutputResultPath && fs.existsSync(tempOutputResultPath)) {
					fs.unlinkSync(tempOutputResultPath);
				}
				// Note: Cleanup of temporary *input* media files created by `binaryToTempFile`
				// should be handled by that shared function or another process if necessary.
			}
		}
		return [returnData];
	}
}
