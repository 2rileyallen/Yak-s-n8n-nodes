![Banner image](https://user-images.githubusercontent.com/10284570/173569848-c624317f-42b1-45a6-ab09-f0ea3c247648.png)

# Yak's n8n Nodes

This repo contains custom community nodes for [n8n](https://n8n.io). The Yak collection includes multiple independent nodes for audio, video, and AI integrations.

Each node is self‑contained, so you can pick and choose the ones relevant to your workflows.

## Prerequisites

You need the following installed on your development machine:

* [git](https://git-scm.com/downloads)
* Node.js and npm. Minimum version Node 20. You can find instructions on how to install both using nvm (Node Version Manager) for Linux, Mac, and WSL [here](https://github.com/nvm-sh/nvm). For Windows users, refer to Microsoft's guide to [Install NodeJS on Windows](https://docs.microsoft.com/en-us/windows/dev-environment/javascript/nodejs-on-windows).
* Install n8n with:
npm install n8n -g

* [FFmpeg](https://ffmpeg.org/download.html) installed and available in your system PATH
* **Windows**: download binaries and add ffmpeg to PATH
* **macOS**: `brew install ffmpeg`
* **Linux (Debian/Ubuntu)**: `sudo apt update && sudo apt install ffmpeg`
* Python environment with required packages installed:
pip install librosa audioread numpy

* Recommended: follow n8n's guide to [set up your development environment](https://docs.n8n.io/integrations/creating-nodes/build/node-development-environment/).

### Additional Setup for Chatterbox TTS (Windows only)

Chatterbox TTS requires its own Conda environment with PyTorch, torchaudio, and ffmpeg support. Complete these steps before using the **Yak‑ChatterboxTTS** node:

1. Install [Miniconda](https://docs.conda.io/en/main/miniconda.html) for Windows if you haven’t already.  
2. Open **Anaconda Prompt** (or PowerShell with Conda initialized).  
3. Create and activate a dedicated environment:
    ```bash
    conda create --name yak_chatterbox_env python=3.11 -y
    conda activate yak_chatterbox_env
    ```
4. Install required Python packages:
    ```bash
    pip install chatterbox-tts torchaudio ffmpeg-python
    ```
5. Ensure FFmpeg is installed system‑wide and available in PATH (see Prerequisites above).  
6. Verify installation:
    ```bash
    python -c "from chatterbox.tts import ChatterboxTTS; print('ChatterboxTTS ready')"
    ```

This ensures the Yak‑ChatterboxTTS node can call the Python backend correctly.

## Using these nodes

These are the basic steps for working with Yak's node package. For detailed guidance on creating and publishing nodes, refer to the [documentation](https://docs.n8n.io/integrations/creating-nodes/).

1. Clone this repository:
git clone https://github.com/2rileyallen/Yak-s-n8n-nodes.git

2. Navigate into the project:
cd Yak-s-n8n-nodes

3. Run `npm install` to install dependencies.
4. Build the nodes:
npm run build

5. Copy the built nodes to your n8n custom directory or link them to your installation.
6. Start n8n and search for "Yak" in the node palette.

## Nodes included

* **Yak-FFMPEG** – advanced video/audio processing with multiple functions (requires FFmpeg + Python packages above)
* **Yak-ChatterboxTTS** – text‑to‑speech synthesis
* **Yak-ComfyUI** – ComfyUI integration for AI image generation
* **Yak-MuseTalk** – AI-powered lip sync and talking head generation
* **Yak-VocalRemover** – audio source separation and vocal isolation (requires FFmpeg)
* **Yak-WhisperSTT** – speech‑to‑text transcription

## More information

Refer to our [documentation on creating nodes](https://docs.n8n.io/integrations/creating-nodes/) for detailed information on building and testing your own nodes.

## License

[MIT](LICENSE.md)