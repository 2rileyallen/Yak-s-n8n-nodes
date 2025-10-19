import {
    IExecuteFunctions,
    ILoadOptionsFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    INodePropertyOptions,
    IHttpRequestOptions,
    NodeConnectionType,
    NodeOperationError,
    IDataObject,
} from 'n8n-workflow';
import * as path from 'path';
import { promises as fs } from 'fs';
import { fileToBinary } from '../../SharedFunctions/fileToBinary';

// --- Manifest structure interfaces for type safety ---
interface IProfileInManifest {
    name: string;
    value: string;
}

interface IModelFamilyInManifest {
    label: string;
    loraDirectory: string;
    profiles: IProfileInManifest[];
}

interface IWorkflowInManifest {
    value: string;
    label: string;
    family: string;
    uiDefinition: string;
    gatekeeperDefinition: string;
}

interface IManifest {
    modelFamilies: { [key: string]: IModelFamilyInManifest };
    workflows: IWorkflowInManifest[];
}

export class Yak_Wan2GP implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Yak - Wan2GP',
        name: 'yakWan2gp',
        icon: 'file:wan2gp.svg',
        group: ['transform'],
        version: 1,
        description: 'Generate images using Wan2GP via a local Gatekeeper service.',
        defaults: {
            name: 'Yak - Wan2GP',
        },
        inputs: [NodeConnectionType.Main],
        outputs: [NodeConnectionType.Main],
        properties: [
            // Static properties that are always visible
            {
                displayName: '--- Workflow Selection ---',
                name: 'workflowSelectionNotice',
                type: 'notice',
                default: 'Select a workflow to see its available parameters.',
            },
            {
                displayName: 'Workflow',
                name: 'selectedWorkflow',
                type: 'options',
                typeOptions: {
                    loadOptionsMethod: 'getWorkflows',
                },
                default: '',
                description: 'Select the Wan2GP workflow to execute.',
                required: true,
            },
            // Dynamic properties will be appended here by the constructor
        ],
    };

    // --- CONSTRUCTOR ---
    // This runs when n8n starts and loads the node. It kicks off the process
    // of reading the manifest and adding the dynamic UI properties.
    constructor() {
        void this.loadAndAppendDynamicProperties();
    }

    // --- Static Path and File Helpers ---
    private static getNodeDir(): string {
        return path.join(__dirname);
    }

    private static async readJson<T = any>(filePath: string): Promise<T> {
        const raw = await fs.readFile(filePath, 'utf-8');
        return JSON.parse(raw) as T;
    }

    // --- Dynamic Property Loading Methods ---
    methods = {
        loadOptions: {
            async getWorkflows(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                const manifestPath = path.join(Yak_Wan2GP.getNodeDir(), 'manifest.json');
                try {
                    const manifest = await Yak_Wan2GP.readJson<IManifest>(manifestPath);
                    return manifest.workflows.map(workflow => ({
                        name: workflow.label,
                        value: workflow.value,
                    }));
                } catch (error) {
                    throw new NodeOperationError(this.getNode(), `Failed to load workflows from manifest: ${(error as Error).message}`);
                }
            },
            async getProfiles(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                try {
                    const manifestPath = path.join(Yak_Wan2GP.getNodeDir(), 'manifest.json');
                    const manifest = await Yak_Wan2GP.readJson<IManifest>(manifestPath);
                    const selectedWorkflowId = this.getCurrentNodeParameter('selectedWorkflow') as string;

                    if (!selectedWorkflowId) return [{ name: 'Select a workflow first', value: '' }];

                    const workflowInfo = manifest.workflows.find(w => w.value === selectedWorkflowId);
                    if (!workflowInfo) return [{ name: 'Invalid workflow selected', value: '' }];

                    const familyInfo = manifest.modelFamilies[workflowInfo.family];
                    if (!familyInfo || !familyInfo.profiles) return [{ name: 'No profiles for this family', value: '' }];

                    return familyInfo.profiles.map(p => ({ name: p.name, value: p.value }));
                } catch (error) {
                    return [{ name: 'Could not load profiles', value: '' }];
                }
            },
        },
    };

    // --- DYNAMIC UI LOADER (THE MISSING PIECE) ---
    // This function reads the manifest, finds all the UI definition files,
    // and adds their properties to the node's UI, conditioned on the selected workflow.
    private async loadAndAppendDynamicProperties() {
        try {
            const nodeDir = Yak_Wan2GP.getNodeDir();
            const manifestPath = path.join(nodeDir, 'manifest.json');
            const manifest = await Yak_Wan2GP.readJson<IManifest>(manifestPath);

            for (const workflow of manifest.workflows) {
                const uiConfigPath = path.join(nodeDir, workflow.uiDefinition);
                const uiConfig = await Yak_Wan2GP.readJson<{ properties?: any[] }>(uiConfigPath);
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
            console.error(`[Yak-Wan2GP] Failed to load dynamic properties from manifest: ${(error as Error).message}`);
        }
    }

    // --- Workflow Execution Logic ---
    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];

        const nodeDir = Yak_Wan2GP.getNodeDir();
        const manifestPath = path.join(nodeDir, 'manifest.json');
        const manifest = await Yak_Wan2GP.readJson<IManifest>(manifestPath);

        for (let i = 0; i < items.length; i++) {
            try {
                const selectedWorkflow = this.getNodeParameter('selectedWorkflow', i) as string;
                if (!selectedWorkflow) {
                    throw new NodeOperationError(this.getNode(), 'No workflow selected.', { itemIndex: i });
                }

                const workflowInfo = manifest.workflows.find(w => w.value === selectedWorkflow);
                if (!workflowInfo) {
                    throw new NodeOperationError(this.getNode(), `Selected workflow '${selectedWorkflow}' not found in manifest.`);
                }
                
                const uiConfigPath = path.join(nodeDir, workflowInfo.uiDefinition);
                const uiConfig = await Yak_Wan2GP.readJson<{ properties?: any[] }>(uiConfigPath);
                const uiProperties = uiConfig?.properties ?? [];
                
                const userInputs: IDataObject = {};
                let profileName: string = '';

                for (const prop of uiProperties) {
                    if (prop.name && prop.type !== 'notice') {
                        try {
                            if (prop.name === 'profileName') {
                                profileName = this.getNodeParameter(prop.name, i, '') as string;
                            } else {
                                userInputs[prop.name] = this.getNodeParameter(prop.name, i);
                            }
                        } catch (error) {
                            // This can happen if a conditional property is not available. Ignore.
                        }
                    }
                }

                const gatekeeperPayload: IDataObject = {
                    workflow: selectedWorkflow,
                    profileName: profileName,
                    user_inputs: userInputs,
                };

                const requestOptions: IHttpRequestOptions = {
                    method: 'POST',
                    url: 'http://127.0.0.1:7862/generate',
                    body: gatekeeperPayload,
                    json: true,
                    timeout: 600000,
                };
                const response = (await this.helpers.httpRequest(requestOptions)) as { filePath: string };
                
                const tempResultPath = response.filePath;
                if (!tempResultPath) {
                    throw new NodeOperationError(this.getNode(), 'Gatekeeper did not return a valid file path.');
                }

                const outputAsFilePath = userInputs.outputAsFilePath as boolean;
                const output: INodeExecutionData = { json: {}, pairedItem: { item: i } };

                if (outputAsFilePath) {
                    const userFinalOutputPath = userInputs.outputFilePath as string;
                    await fs.mkdir(path.dirname(userFinalOutputPath), { recursive: true });
                    await fs.rename(tempResultPath, userFinalOutputPath);
                    output.json.filePath = userFinalOutputPath;
                } else {
                    const outputBinaryPropertyName = userInputs.outputBinaryPropertyName as string;
                    const binary = await fileToBinary(tempResultPath, outputBinaryPropertyName, this.helpers);
                    output.binary = { [outputBinaryPropertyName]: binary };
                    await fs.unlink(tempResultPath);
                }
                returnData.push(output);

            } catch (error) {
                if (this.continueOnFail()) {
                    returnData.push({ json: { error: (error as Error).message }, pairedItem: { item: i } });
                    continue;
                }
                throw error;
            }
        }
        return [returnData];
    }
}