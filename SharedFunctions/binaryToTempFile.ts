import type { IExecuteFunctions } from 'n8n-workflow';
import * as path from 'path';
import * as fs from 'fs';
import { randomUUID } from 'crypto';

/**
 * Converts binary data from n8n to a temporary file on disk.
 * 
 * @param executeFunctions - The n8n execution context
 * @param itemIndex - The current item index being processed
 * @param propertyName - The name of the binary property to read
 * @param tempDir - The directory to write the temporary file (e.g., 'temp/input')
 * @returns Promise<string> - The absolute path to the created temporary file
 */
export async function binaryToTempFile(
	executeFunctions: IExecuteFunctions,
	itemIndex: number,
	propertyName: string,
	tempDir: string
): Promise<string> {
	// Get the binary data buffer from n8n
	const binaryBuffer = await executeFunctions.helpers.getBinaryDataBuffer(itemIndex, propertyName);
	
	// Get the binary metadata to try to determine file extension
	const items = executeFunctions.getInputData();
	const binaryData = items[itemIndex].binary?.[propertyName];
	
	// Try to extract file extension from mimeType or fileName
	let extension = '';
	if (binaryData?.mimeType) {
		const mimeMap: { [key: string]: string } = {
			'audio/wav': '.wav',
			'audio/mpeg': '.mp3',
			'audio/mp4': '.m4a',
			'audio/ogg': '.ogg',
			'video/mp4': '.mp4',
			'video/avi': '.avi',
			'video/mov': '.mov',
			'image/jpeg': '.jpg',
			'image/png': '.png',
		};
		extension = mimeMap[binaryData.mimeType] || '';
	}
	
	// If no extension from mime type, try to get it from fileName
	if (!extension && binaryData?.fileName) {
		const parsedPath = path.parse(binaryData.fileName);
		extension = parsedPath.ext;
	}
	
	// Generate a unique filename
	const uniqueId = randomUUID();
	const fileName = `${uniqueId}${extension}`;
	const filePath = path.join(tempDir, fileName);
	
	// Ensure the temp directory exists
	if (!fs.existsSync(tempDir)) {
		fs.mkdirSync(tempDir, { recursive: true });
	}
	
	// Write the binary data to the temporary file
	fs.writeFileSync(filePath, binaryBuffer);
	
	return path.resolve(filePath);
}