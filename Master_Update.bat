@echo off
ECHO --- Starting Repository and Environment Update ---

:: Set the current directory to the script's location (the project root)
cd /d "%~dp0"

ECHO.
ECHO --- Pulling latest changes from the Git repository... ---
git pull

ECHO.
ECHO --- Git repository updated. Now starting the ComfyUI environment update... ---
ECHO.

:: Call the master update script for ComfyUI
call "nodes\Yak-ComfyUI\master_update_comfyui.bat"

ECHO.
ECHO --- Full Repository and Environment Update Complete ---
PAUSE
