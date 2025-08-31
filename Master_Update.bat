@echo off
ECHO --- Starting Master ComfyUI Environment Update ---

:: Set the current directory to this script's location
cd /d "%~dp0"

:: Activate the conda environment once for all subsequent scripts
ECHO.
ECHO --- Activating Conda Environment: yak_comfyui_env ---
call conda activate yak_comfyui_env

:: --- NEW STEP: Install/Update Python Requirements ---
ECHO.
ECHO ======================================================
ECHO  INSTALLING/UPDATING PYTHON REQUIREMENTS
ECHO ======================================================
pip install -r requirements.txt

:: --- Step 1: Update the ComfyUI Application ---
ECHO.
ECHO ======================================================
ECHO  STEP 1: UPDATING CORE COMFYUI APP
ECHO ======================================================
call ..\..\Software\update_comfyui_app.bat

:: --- Step 2: Synchronize Custom Nodes ---
ECHO.
ECHO ======================================================
ECHO  STEP 2: SYNCHRONIZING CUSTOM NODES
ECHO ======================================================
call manage_custom_nodes.bat

:: --- Step 3: Synchronize Models ---
ECHO.
ECHO ======================================================
ECHO  STEP 3: SYNCHRONIZING MODELS
ECHO ======================================================
call manage_models.bat

ECHO.
ECHO --- Master ComfyUI Environment Update Complete ---
PAUSE
