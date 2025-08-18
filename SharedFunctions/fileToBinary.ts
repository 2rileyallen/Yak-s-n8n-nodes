import type { IExecuteFunctions, IBinaryData } from 'n8n-workflow';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Converts a file on disk to n8n binary data format.
 */
export async function fileToBinary(
	filePath: string,
	propertyName: string,
	helpers: IExecuteFunctions['helpers']
): Promise<IBinaryData> {
	// Read the file from disk
	const fileBuffer = fs.readFileSync(filePath);

	const fileName = path.basename(filePath);

	const extension = path.extname(filePath).toLowerCase();
	const mimeTypeMap: { [key: string]: string } = {
		'.wav': 'audio/wav',
		'.mp3': 'audio/mpeg',
		'.m4a': 'audio/mp4',
		'.ogg': 'audio/ogg',
		'.mp4': 'video/mp4',
		'.avi': 'video/avi',
		'.mov': 'video/quicktime',
		'.jpg': 'image/jpeg',
		'.jpeg': 'image/jpeg',
		'.png': 'image/png',
	};

	const mimeType = mimeTypeMap[extension] || 'application/octet-stream';

	// Use n8n's helper to prepare the binary data
	const binaryData = await helpers.prepareBinaryData(fileBuffer, fileName, mimeType);
	return binaryData;
}