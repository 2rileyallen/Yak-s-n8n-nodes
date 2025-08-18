import type { IExecuteFunctions, INodeType, INodeTypeDescription } from 'n8n-workflow';
import { NodeConnectionType } from 'n8n-workflow';

export class YakFFMPEG implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Yak – FFMPEG',
    name: 'yakFfmpeg',
    group: ['transform'],
    version: 1,
    description: 'Placeholder node',
    defaults: { name: 'Yak – FFMPEG' },
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