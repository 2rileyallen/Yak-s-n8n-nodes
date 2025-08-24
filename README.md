![Banner image](https://user-images.githubusercontent.com/10284570/173569848-c624317f-42b1-45a6-ab09-f0ea3c247648.png)

# Yak's n8n Nodes

This repo contains custom community nodes for [n8n](https://n8n.io). The Yak collection includes multiple independent nodes for audio, video, and AI integrations.

Each node is self‑contained, so you can pick and choose the ones relevant to your workflows.

## Prerequisites

You need the following installed on your development machine:

* [git](https://git-scm.com/downloads)
* Node.js and npm. Minimum version Node 20. You can find instructions on how to install both using nvm (Node Version Manager) for Linux, Mac, and WSL [here](https://github.com/nvm-sh/nvm). For Windows users, refer to Microsoft's guide to [Install NodeJS on Windows](https://docs.microsoft.com/en-us/windows/dev-environment/javascript/nodejs-on-windows).
* Install n8n with:
    ```bash
    npm install n8n -g
    ```
* [FFmpeg](https://ffmpeg.org/download.html) installed and available in your system PATH
    * **Windows**: download binaries and add ffmpeg to PATH
    * **macOS**: `brew install ffmpeg`
    * **Linux (Debian/Ubuntu)**: `sudo apt update && sudo apt install ffmpeg`
* Python environment with required packages installed:
    ```bash
    pip install librosa audioread numpy
    ```
* Recommended: follow n8n's guide to [set up your development environment](https://docs.n8n.io/integrations/creating-nodes/build/node-development-environment/).

### Additional Setup for Chatterbox TTS (Windows only)

Chatterbox TTS requires its own Conda environment with PyTorch, torchaudio, and ffmpeg support. Complete these steps before using the **Yak‑ChatterboxTTS** node:

1.  Install [Miniconda](https://docs.conda.io/en/main/miniconda.html) for Windows if you haven’t already.
2.  Open **Anaconda Prompt** (or PowerShell with Conda initialized).
3.  Create and activate a dedicated environment:
    ```bash
    conda create --name yak_chatterbox_env python=3.11 -y
    conda activate yak_chatterbox_env
    ```
4.  Install required Python packages:
    ```bash
    pip install chatterbox-tts torchaudio ffmpeg-python
    ```
5.  Ensure FFmpeg is installed system‑wide and available in PATH (see Prerequisites above).
6.  Verify installation:
    ```bash
    python -c "from chatterbox.tts import ChatterboxTTS; print('ChatterboxTTS ready')"
    ```

This ensures the Yak‑ChatterboxTTS node can call the Python backend correctly.

### Additional Setup for MuseTalk (Windows with NVIDIA GPU)

The Yak-MuseTalk node requires a specific Conda environment and a separate download for its models. Complete these steps before using the node:

1.  **System Prerequisites:**
    * **NVIDIA CUDA Toolkit:** Version **12.1** must be installed.
    * **Visual Studio Build Tools:** Install with the "Desktop development with C++" workload.

2.  **Download Models:**
    * The MuseTalk models are required for the node to function. Download the `models` folder from the following link and place it inside the `Software/MuseTalk/` directory.
    * **Google Drive Link:** `[Link to be added here]`

3.  **Create Conda Environment:**
    * Open **Anaconda Prompt** (or PowerShell with Conda initialized).
    * Create and activate the dedicated environment:
        ```bash
        conda create --name yak_musetalk_env python=3.10 -y
        conda activate yak_musetalk_env
        ```

4.  **Install Python Dependencies:**
    * Install the specific PyTorch version for CUDA 12.1:
        ```bash
        pip install torch==2.1.0 torchvision==0.16.0+cu121 --extra-index-url [https://download.pytorch.org/whl/cu121](https://download.pytorch.org/whl/cu121)
        ```
        ```bash
        pip install torchaudio==2.1.0 --extra-index-url [https://download.pytorch.org/whl/cu121](https://download.pytorch.org/whl/cu121)
        ```
    * Install the dependencies for the Gatekeeper server:
        ```bash
        pip install sqlalchemy fastapi "uvicorn[standard]" httpx
        ```
    * Navigate to the MuseTalk software directory and install its requirements:
        ```bash
        cd path/to/Yak-s-n8n-nodes/Software/MuseTalk
        pip install -r requirements.txt
        ```
    * Install the required MMLab packages:
        ```bash
        pip install openmim
        pip install mmengine
        pip install mmcv==2.1.0 -f [https://download.openmmlab.com/mmcv/dist/cu121/torch2.1.0/index.html](https://download.openmmlab.com/mmcv/dist/cu121/torch2.1.0/index.html)
        pip install mmdet==3.2.0
        pip install mmpose==1.3.1
        ```

### Additional Setup for ComfyUI (Windows with NVIDIA GPU)

The Yak-ComfyUI node requires a local ComfyUI installation, a dedicated Conda environment, and a managed set of models and custom nodes.

1.  **Install ComfyUI:**
    * Navigate to the `Software/` directory inside this repository.
    * Clone the official ComfyUI repository:
        ```bash
        git clone [https://github.com/comfyanonymous/ComfyUI.git](https://github.com/comfyanonymous/ComfyUI.git)
        ```

2.  **Create Conda Environment:**
    * Open **Anaconda Prompt**.
    * Create and activate the dedicated environment:
        ```bash
        conda create --name yak_comfyui_env python=3.11 -y
        conda activate yak_comfyui_env
        ```

3.  **Install Python Dependencies:**
    * Install dependencies for the Gatekeeper and management scripts:
        ```bash
        pip install "fastapi[all]" sqlalchemy httpx websockets requests tqdm gdown
        ```
    * Install ComfyUI's dependencies into the same environment:
        ```bash
        pip install -r Software/ComfyUI/requirements.txt
        ```

4.  **Configure Model Paths:**
    * Find the `extra_model_paths.yaml.example` file inside `nodes/Yak-ComfyUI/`.
    * Copy this file into your `Software/ComfyUI/` directory and rename it to `extra_model_paths.yaml`.
    * Open the new file and edit the placeholder paths to match your system's configuration.

5.  **Synchronize Environment:**
    * Run the management scripts to download all required models and custom nodes for the included workflows.
    * Navigate to the `nodes/Yak-ComfyUI/` directory and run the following batch files:
        ```bash
        manage_models.bat
        manage_custom_nodes.bat
        ```

6.  **Launch Services:**
    * The `master_start.bat` file in the root directory is used to launch all services (ComfyUI, Gatekeeper, n8n).
    * Before running it for the first time, open `master_start.bat` and edit the `PROJECT_PATH` and `CONDA_PATH` variables at the top to match your system.
    * Run the script to start all services in the background:
        ```bash
        master_start.bat
        ```

## Using these nodes

These are the basic steps for working with Yak's node package. For detailed guidance on creating and publishing nodes, refer to the [documentation](https://docs.n8n.io/integrations/creating-nodes/).

1.  Clone this repository:
    ```bash
    git clone [https://github.com/2rileyallen/Yak-s-n8n-nodes.git](https://github.com/2rileyallen/Yak-s-n8n-nodes.git)
    ```
2.  Navigate into the project:
    ```bash
    cd Yak-s-n8n-nodes
    ```
3.  Run `npm install` to install dependencies.
4.  Build the nodes:
    ```bash
    npm run build
    ```
5.  Copy the built nodes to your n8n custom directory or link them to your installation.
6.  Start n8n and search for "Yak" in the node palette.

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
