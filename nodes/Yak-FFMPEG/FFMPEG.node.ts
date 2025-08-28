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
import { spawn } from 'child_process';
import * as path from 'path';
import { promises as fs } from 'fs';
import { binaryToTempFile } from '../../SharedFunctions/binaryToTempFile';
import { fileToBinary } from '../../SharedFunctions/fileToBinary';

// --- HELPER FUNCTION ---
async function readJson<T = any>(filePath: string): Promise<T> {
    try {
        const raw = await fs.readFile(filePath, 'utf-8');
        return JSON.parse(raw) as T;
    } catch (error) {
        console.error(`Error reading JSON file at ${filePath}:`, error);
        throw new Error(`Failed to read or parse JSON file: ${filePath}`);
    }
}

// --- INTERFACES ---
interface IFFmpegFunction {
    name: string;
    value: string;
    uiFile: string;
    scriptFile: string;
}

interface IManifest {
    functions: IFFmpegFunction[];
}

// --- NODE IMPLEMENTATION ---
export class FFMPEG implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Yak - FFMPEG',
        name: 'yakFfmpeg',
        group: ['transform'],
        version: 1,
        description: 'Executes various FFmpeg functions via Python scripts.',
        defaults: {
            name: 'Yak - FFMPEG',
        },
        inputs: [NodeConnectionType.Main],
        outputs: [NodeConnectionType.Main],
        properties: [
            {
                displayName: 'Function',
                name: 'selectedFunction',
                type: 'options',
                typeOptions: {
                    loadOptionsMethod: 'getFunctions',
                },
                default: '',
                description: 'Select the FFmpeg function to execute.',
                required: true,
            },
        ],
    };

    constructor() {
        this.loadAndAppendDynamicProperties().catch((error) => {
            console.error('Failed to load dynamic properties:', error);
        });
    }

    // Node-local directory (compiled file sits in dist/nodes/Yak-FFMPEG)
    private getNodeDir(): string {
        return __dirname;
    }

    methods = {
        loadOptions: {
            async getFunctions(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                try {
                    const nodeDir = __dirname;
                    const manifestPath = path.join(nodeDir, 'manifest.json');

                    try {
                        await fs.access(manifestPath);
                    } catch {
                        console.warn(`Manifest file not found: ${manifestPath}`);
                        return [];
                    }

                    const manifest = await readJson<IManifest>(manifestPath);

                    if (!manifest.functions || manifest.functions.length === 0) {
                        throw new NodeOperationError(this.getNode(), 'No functions found in manifest.');
                    }

                    return manifest.functions.map((func: IFFmpegFunction) => ({
                        name: func.name,
                        value: func.value,
                        description: `Execute the ${func.name} function`,
                    }));
                } catch (error) {
                    throw new NodeOperationError(
                        this.getNode(),
                        `Failed to load functions from manifest: ${(error as Error).message}`,
                    );
                }
            },
        },
    };

    private async loadAndAppendDynamicProperties(): Promise<void> {
        try {
            const nodeDir = this.getNodeDir();
            const manifestPath = path.join(nodeDir, 'manifest.json');

            try {
                await fs.access(manifestPath);
            } catch {
                console.warn(`Manifest file not found: ${manifestPath}`);
                return;
            }

            const manifest = await readJson<IManifest>(manifestPath);

            if (!manifest.functions || !Array.isArray(manifest.functions)) {
                console.warn('No functions found in manifest');
                return;
            }

            for (const func of manifest.functions) {
                if (!func.uiFile || !func.value) {
                    console.warn(`Invalid function config: ${JSON.stringify(func)}`);
                    continue;
                }

                const uiStructurePath = path.join(nodeDir, func.uiFile);

                try {
                    await fs.access(uiStructurePath);
                    const uiConfig = await readJson<{ properties?: any[] }>(uiStructurePath);
                    const props = uiConfig?.properties || [];

                    for (const prop of props) {
                        if (!prop.name || !prop.type) {
                            console.warn(`Invalid property in ${func.uiFile}:`, prop);
                            continue;
                        }

                        const dynamicProperty = {
                            ...prop,
                            displayOptions: {
                                ...(prop.displayOptions || {}),
                                show: {
                                    ...(prop.displayOptions?.show || {}),
                                    selectedFunction: [func.value],
                                },
                            },
                        };
                        this.description.properties.push(dynamicProperty);
                    }
                } catch (error) {
                    console.error(`Failed to read UI for function '${func.name}':`, (error as Error).message);
                }
            }
        } catch (error) {
            console.error('Failed to load dynamic properties:', error as Error);
        }
    }

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];
        const nodeDir = __dirname;
        let tempFiles: string[] = [];

        // Prepare temp directories
        const tempInputDir = path.join(process.cwd(), 'temp', 'input');
        const tempOutputDir = path.join(process.cwd(), 'temp', 'output');

        // Ensure temp directories exist
        try {
            await fs.mkdir(tempInputDir, { recursive: true });
            await fs.mkdir(tempOutputDir, { recursive: true });
        } catch (error) {
            // Directories might already exist, ignore error
        }

        for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
            try {
                const selectedFunctionValue = this.getNodeParameter('selectedFunction', itemIndex, '') as string;
                if (!selectedFunctionValue) throw new NodeOperationError(this.getNode(), 'No function selected.');

                const manifestPath = path.join(nodeDir, 'manifest.json');
                const manifest = await readJson<IManifest>(manifestPath);
                const selectedFunction = manifest.functions.find((f: IFFmpegFunction) => f.value === selectedFunctionValue);
                if (!selectedFunction) throw new NodeOperationError(this.getNode(), `Function '${selectedFunctionValue}' not found.`);

                const scriptPath = path.join(nodeDir, selectedFunction.scriptFile);
                const uiStructurePath = path.join(nodeDir, selectedFunction.uiFile);
                await fs.access(scriptPath);

                const parameters: IDataObject = {};
                const uiConfig = await readJson<{ properties?: { name: string; type: string }[] }>(uiStructurePath);

                if (uiConfig.properties && Array.isArray(uiConfig.properties)) {
                    for (const prop of uiConfig.properties) {
                        if (!prop.name) continue;
                        try {
                            parameters[prop.name] = this.getNodeParameter(prop.name, itemIndex);
                        } catch {
                            // Ignore missing params that may be conditional
                            continue;
                        }
                    }
                }

                // BINARY INPUT HANDLING - Using SharedFunctions
                const processedParameters = { ...parameters };

                // Handle input binary/file path toggles
                const inputUseFilePathKeys = Object.keys(processedParameters).filter((k) => k.endsWith('UseFilePath'));

                for (const toggleKey of inputUseFilePathKeys) {
                    const useFilePath = processedParameters[toggleKey] as boolean;
                    const prefix = toggleKey.replace('UseFilePath', '');
                    
                    if (useFilePath) {
                        const filePathKey = `${prefix}FilePath`;
                        if (processedParameters[filePathKey]) {
                            continue;
                        }
                    } else {
                        const binaryPropNameKey = `${prefix}BinaryPropertyName`;
                        
                        if (processedParameters[binaryPropNameKey]) {
                            const binaryPropertyName = processedParameters[binaryPropNameKey] as string;
                            
                            const inputData = items[itemIndex];
                            const binaryInfo = inputData.binary?.[binaryPropertyName];

                            if (!binaryInfo) {
                                throw new NodeOperationError(
                                    this.getNode(),
                                    `Binary property '${binaryPropertyName}' not found in input data.`,
                                );
                            }

                            const tempFilePath = await binaryToTempFile(this, itemIndex, binaryPropertyName, tempInputDir);
                            tempFiles.push(tempFilePath);

                            const filePathKey = `${prefix}FilePath`;
                            processedParameters[filePathKey] = tempFilePath;
                        }
                    }
                }

                // Handle output settings. The node provides a directory and a base name.
                // The Python script is responsible for adding the correct extension.
                const outputAsFilePath = processedParameters.outputAsFilePath as boolean;
                let finalUserOutputPath: string | undefined = undefined;

                if (outputAsFilePath && processedParameters.outputFilePath) {
                    // User specified a final destination path.
                    // We still process in a temp directory, and will move the file later.
                    finalUserOutputPath = processedParameters.outputFilePath as string;
                }
                
                // Always give the Python script a temp directory and a unique base name to work with.
                processedParameters.outputDirectory = tempOutputDir;
                processedParameters.outputBaseName = `output_${Date.now()}_${itemIndex}`;

                const paramsPath = path.join(tempInputDir, `n8n-ffmpeg-params-${Date.now()}-${itemIndex}.json`);
                await fs.writeFile(paramsPath, JSON.stringify(processedParameters, null, 2));
                tempFiles.push(paramsPath);

                const scriptResult = await new Promise<string>((resolve, reject) => {
                    const pythonProcess = spawn('python', [scriptPath, paramsPath]);
                    let stdout = '';
                    let stderr = '';

                    pythonProcess.stdout.on('data', (data) => (stdout += data.toString()));
                    pythonProcess.stderr.on('data', (data) => (stderr += data.toString()));
                    pythonProcess.on('close', (code) => {
                        if (code !== 0) {
                            // --- IMPROVED ERROR HANDLING ---
                            // The script failed. First, try to parse stdout for a detailed JSON error from Python.
                            try {
                                const potentialJsonError = JSON.parse(stdout.trim());
                                if (potentialJsonError && potentialJsonError.error) {
                                    // We got a detailed error message from the script!
                                    const command = potentialJsonError.command ? `\nCommand: ${potentialJsonError.command}` : '';
                                    const errorMessage = `Python script error: ${potentialJsonError.error}${command}`;
                                    return reject(new NodeOperationError(this.getNode(), errorMessage));
                                }
                            } catch (e) {
                                // stdout was not a valid JSON error message, so we will fall back to stderr.
                            }
                            
                            // Fallback to using stderr or the exit code if stdout didn't provide a clear error.
                            return reject(
                                new NodeOperationError(
                                    this.getNode(),
                                    `Script failed: ${stderr.trim() || `Exited with code ${code}`}`,
                                ),
                            );
                        }
                        // If code is 0, the script succeeded.
                        resolve(stdout.trim());
                    });
                    pythonProcess.on('error', (err) =>
                        reject(new NodeOperationError(this.getNode(), `Failed to start script: ${err.message}`)),
                    );
                });

                let jsonResult: IDataObject;
                try {
                    jsonResult = JSON.parse(scriptResult);
                } catch {
                    jsonResult = { output: scriptResult, parseError: true };
                }

                // Get the actual file path returned by the Python script
                const generatedFilePath = jsonResult.output_file_path as string;
                if (!generatedFilePath) {
                    throw new NodeOperationError(this.getNode(), 'Python script did not return an output_file_path.');
                }
                
                // Ensure the generated file exists before proceeding
                try {
                    await fs.access(generatedFilePath);
                } catch (error) {
                     throw new NodeOperationError(
                        this.getNode(),
                        `Output file not found at path: ${generatedFilePath}. Script may have failed to generate output.`,
                    );
                }

                let executionData: INodeExecutionData;

                if (finalUserOutputPath) {
                    // User wants a specific file path. Move the temp file to its final destination.
                    await fs.rename(generatedFilePath, finalUserOutputPath);
                    executionData = {
                        json: { ...jsonResult, outputFilePath: finalUserOutputPath },
                        pairedItem: { item: itemIndex },
                    };
                } else {
                    // User wants binary output. Convert the generated file.
                    const outputBinaryPropertyName = (processedParameters.outputBinaryPropertyName as string) || 'data';
                    const binaryData = await fileToBinary(generatedFilePath, outputBinaryPropertyName, this.helpers);
                    
                    executionData = {
                        json: { ...jsonResult },
                        binary: { [outputBinaryPropertyName]: binaryData },
                        pairedItem: { item: itemIndex },
                    };
                    
                    // The generated file is temporary and should be cleaned up
                    tempFiles.push(generatedFilePath);
                }

                returnData.push(executionData);

            } catch (error) {
                if (this.continueOnFail()) {
                    returnData.push({ json: { error: (error as Error).message }, pairedItem: { item: itemIndex } });
                    continue;
                }
                throw error;
            } finally {
                // Clean up temp files
                for (const filePath of tempFiles) {
                    try {
                        await fs.unlink(filePath);
                    } catch (e) {
                        console.error(`Could not clean up temp file ${filePath}:`, e);
                    }
                }
                tempFiles = [];
            }
        }

        return this.prepareOutputData(returnData);
    }
}
