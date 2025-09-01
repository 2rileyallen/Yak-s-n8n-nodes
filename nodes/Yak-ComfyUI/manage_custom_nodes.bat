@echo off
:: This script synchronizes the custom nodes required for the Yak ComfyUI n8n node.

:: --- Set the current directory to the script's location ---
cd /d "%~dp0"

ECHO --- Activating Conda Environment ---
:: Activates the 'yak_comfyui_env' to ensure the correct Python and libraries are used.
call conda activate yak_comfyui_env

ECHO --- Synchronizing Required Custom Nodes... ---
:: Runs the Python script to clone, update, and install dependencies for custom nodes.
python manage_custom_nodes.py

ECHO.
ECHO --- Custom Node synchronization complete. ---
:: The PAUSE command has been removed to allow the master update script to continue uninterrupted.
