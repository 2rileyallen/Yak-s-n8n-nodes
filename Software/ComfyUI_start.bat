@echo off
TITLE ComfyUI_Server

:: This script is now generic and receives the Conda path as an argument (%1).

:: Set the current directory to this script's location
cd /d "%~dp0"

:: Change directory into the ComfyUI subfolder
cd ComfyUI

ECHO Starting ComfyUI Server...
:: Use the provided Conda path to run the command.
"%~1\conda.bat" run -n yak_comfyui_env --no-capture-output python main.py
