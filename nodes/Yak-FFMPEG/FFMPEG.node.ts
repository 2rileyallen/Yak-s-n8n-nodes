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
                        // User chose file path - use the file path parameter directly
                        const filePathKey = `${prefix}FilePath`;
                        if (processedParameters[filePathKey]) {
                            // File path is already set, no conversion needed
                            continue;
                        }
                    } else {
                        // User chose binary - convert binary to temp file
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

                            // Use SharedFunction to convert binary to temp file
                            const tempFilePath = await binaryToTempFile(this, itemIndex, binaryPropertyName, tempInputDir);
                            tempFiles.push(tempFilePath);

                            // Replace the binary property name with the actual file path for the Python script
                            const filePathKey = `${prefix}FilePath`;
                            processedParameters[filePathKey] = tempFilePath;
                        }
                    }
                }

                // Handle output settings - determine if user wants file path or binary output
                const outputAsFilePath = processedParameters.outputAsFilePath as boolean;
                let outputFilePath: string;

                if (outputAsFilePath && processedParameters.outputFilePath) {
                    // User specified a file path for output
                    outputFilePath = processedParameters.outputFilePath as string;
                } else {
                    // Generate temp output path for binary return
                    outputFilePath = path.join(tempOutputDir, `output_${Date.now()}_${itemIndex}.mp4`);
                }

                processedParameters.outputFilePath = outputFilePath;

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
                        if (code !== 0)
                            return reject(
                                new NodeOperationError(
                                    this.getNode(),
                                    `Script failed: ${stderr || `Exited with code ${code}`}`,
                                ),
                            );
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

                // BINARY OUTPUT HANDLING - Using SharedFunctions
                let executionData: INodeExecutionData;

                if (outputAsFilePath) {
                    // Return file path in JSON
                    executionData = {
                        json: { 
                            ...jsonResult, 
                            outputFilePath: jsonResult.output_file_path || outputFilePath 
                        },
                        pairedItem: { item: itemIndex },
                    };
                } else {
                    // Convert output file to binary using SharedFunction
                    const outputBinaryPropertyName = (processedParameters.outputBinaryPropertyName as string) || 'data';
                    
                    // Check if the output file exists
                    const finalOutputPath = (jsonResult.output_file_path as string) || outputFilePath;
                    
                    try {
                        await fs.access(finalOutputPath);
                        const binaryData = await fileToBinary(finalOutputPath, outputBinaryPropertyName, this.helpers);
                        
                        executionData = {
                            json: { ...jsonResult },
                            binary: { [outputBinaryPropertyName]: binaryData },
                            pairedItem: { item: itemIndex },
                        };

                        // Clean up temp output file
                        tempFiles.push(finalOutputPath);
                    } catch (error) {
                        throw new NodeOperationError(
                            this.getNode(),
                            `Output file not found: ${finalOutputPath}. Script may have failed to generate output.`,
                        );
                    }
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