@echo off
TITLE MuseTalk_Gatekeeper

:: This script is now generic and receives the Conda path as an argument (%1).

:: Set the current directory to this script's location
cd /d "%~dp0"

ECHO Starting MuseTalk Gatekeeper...
:: Use the provided Conda path to run the command.
"%~1\conda.bat" run -n yak_musetalk_env --no-capture-output uvicorn gatekeeper:app --reload
