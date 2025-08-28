const axios = require('axios');
const fs = require('fs');
const FormData = require('form-data');

// --- Configuration ---
// IMPORTANT: Replace this with the actual, full path to a small test image on your computer.
const FILE_PATH = 'C:\\Users\\2rile\\Downloads\\qwen_edit_00002_.png'; 
const SERVER_URL = 'https://gatekeepercomfyuiserver.thetunecanvas.com/upload';
const HEADERS = {
    'CF-Access-Client-Id': '72df5856f07b7bfc85f0cdb01f933bbe.access',
    'CF-Access-Client-Secret': '6a4ae5dd83bbc93bffab59039efb7ae9a5e002f1c516b8df03a5882850692315',
};
// --------------------


async function uploadTest() {
    console.log(`Attempting to upload file: ${FILE_PATH}`);

    if (!fs.existsSync(FILE_PATH)) {
        console.error('ERROR: The test file does not exist at the specified path. Please update FILE_PATH in the script.');
        return;
    }

    try {
        const form = new FormData();
        form.append('files', fs.createReadStream(FILE_PATH));

        const response = await axios.post(SERVER_URL, form, {
            headers: {
                ...HEADERS,
                ...form.getHeaders(),
            },
        });

        console.log('--- SUCCESS ---');
        console.log('Server Response:', response.data);

    } catch (error) {
        console.error('--- ERROR ---');
        if (error.response) {
            console.error('Status:', error.response.status);
            console.error('Data:', error.response.data);
        } else {
            console.error('Error Message:', error.message);
        }
    }
}

uploadTest();
