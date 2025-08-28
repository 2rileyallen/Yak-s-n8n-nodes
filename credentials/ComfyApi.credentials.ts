import {
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class ComfyApi implements ICredentialType {
	name = 'comfyApi';
	displayName = 'ComfyUI Server API';
	documentationUrl = 'https://github.com/2rileyallen/Yak-s-n8n-nodes';
	properties: INodeProperties[] = [
		{
			displayName: 'Server URL',
			name: 'serverUrl',
			type: 'string',
			default: '',
			placeholder: 'https://gatekeeper.yourdomain.com',
			description: 'The public URL of the ComfyUI Gatekeeper on your server',
			required: true,
		},
		{
			displayName: 'Client ID Header Name',
			name: 'clientIdHeaderName',
			type: 'string',
			default: 'CF-Access-Client-Id',
			description: 'The header name for your Cloudflare Access Client ID',
		},
		{
			displayName: 'Client ID Header Value',
			name: 'clientIdHeaderValue',
			type: 'string',
			typeOptions: {
				password: true,
			},
			default: '',
			description: 'The secret value for your Cloudflare Access Client ID',
		},
		{
			displayName: 'Client Secret Header Name',
			name: 'clientSecretHeaderName',
			type: 'string',
			default: 'CF-Access-Client-Secret',
			description: 'The header name for your Cloudflare Access Client Secret',
		},
		{
			displayName: 'Client Secret Header Value',
			name: 'clientSecretHeaderValue',
			type: 'string',
			typeOptions: {
				password: true,
			},
			default: '',
			description: 'The secret value for your Cloudflare Access Client Secret',
		},
	];
}
