@echo off
ECHO --- Starting Full Repository and Environment Update ---

:: ------------------------------------------------------------------
:: Set the current directory to the script's location (the project root)
:: ------------------------------------------------------------------
cd /d "%~dp0"

:: ------------------------------------------------------------------
:: STEP 1: Update the main repository from Git
:: ------------------------------------------------------------------
ECHO.
ECHO --- [1/5] Pulling latest changes from the Git repository... ---
git pull

:: ------------------------------------------------------------------
:: STEP 2: Update Node.js dependencies and build the n8n nodes
:: ------------------------------------------------------------------
ECHO.
ECHO --- [2/5] Updating Node.js requirements and building nodes... ---
npm install
npm run build

:: ------------------------------------------------------------------
:: STEP 3: Update Python dependencies from the root requirements file
:: ------------------------------------------------------------------
ECHO.
ECHO --- [3/5] Updating Python requirements... ---
call conda activate yak_comfyui_env
pip install -r requirements.txt

:: ------------------------------------------------------------------
:: STEP 4: Update the core ComfyUI application
:: ------------------------------------------------------------------
ECHO.
ECHO --- [4/5] Updating the core ComfyUI application... ---
:: Change directory into the Software folder before calling the app updater
cd "Software"
call "update_comfyui_app.bat"
:: Return to the project root
cd "%~dp0"

:: ------------------------------------------------------------------
:: STEP 5: Update the Yak-ComfyUI node dependencies (models & custom nodes)
:: ------------------------------------------------------------------
ECHO.
ECHO --- [5/5] Updating Yak-ComfyUI models and custom nodes... ---
:: Change directory into the node's folder before calling its specific updater
cd "nodes\Yak-ComfyUI"
call "master_update_comfyui.bat"
:: Return to the project root
cd "%~dp0"

ECHO.
ECHO --- Full Repository and Environment Update Complete ---
PAUSE

