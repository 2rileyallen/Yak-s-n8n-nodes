@echo off
ECHO --- Updating ComfyUI Application ---

:: Set the current directory to this script's location (the /Software/ folder)
cd /d "%~dp0"

:: Navigate into the ComfyUI repository
cd ComfyUI

ECHO.
ECHO --- Pulling latest changes for ComfyUI... ---
git pull

ECHO.
ECHO --- Installing/Updating Python dependencies for ComfyUI... ---
:: Activate the environment to ensure pip installs packages in the right place
call conda activate yak_comfyui_env
pip install -r requirements.txt

ECHO.
ECHO --- ComfyUI application update complete. ---
PAUSE
