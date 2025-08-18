import type { IExecuteFunctions, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { NodeConnectionType } from 'n8n-workflow';

export class VocalRemover implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Yak – VocalRemover',
    name: 'yakVocalremover',
    group: ['transform'],
    version: 1,
    description: 'Placeholder node',
    defaults: { name: 'Yak – VocalRemover' },
    inputs: [NodeConnectionType.Main],
    outputs: [NodeConnectionType.Main],
    properties: [
      {
        displayName: 'Note',
        name: 'note',
        type: 'notice',
        default: '',
        description: 'This is a placeholder node.',
      },
    ],
  };

  async execute(this: IExecuteFunctions) {
    // Pass input through unchanged
    return [this.getInputData()];
  }
}