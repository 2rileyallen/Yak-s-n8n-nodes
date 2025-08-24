@echo off
:: This script synchronizes the models required for the Yak ComfyUI n8n node.

:: --- Set the current directory to the script's location ---
cd /d "%~dp0"

ECHO --- Activating Conda Environment ---
:: Activates the 'yak_comfyui_env' to ensure the correct Python and libraries are used.
call conda activate yak_comfyui_env

ECHO --- Synchronizing Required Models... ---
:: Runs the Python script to download, update, and clean up models.
python manage_models.py

ECHO.
ECHO --- Model synchronization complete. ---
PAUSE
