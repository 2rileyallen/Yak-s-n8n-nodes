@echo off
ECHO --- Starting All Services ---

:: ##################################################################
:: ##                      USER CONFIGURATION                      ##
:: ##  You ONLY need to change these two lines to match your system. ##
:: ##################################################################

SET "PROJECT_PATH=C:\Users\2rile\.n8n\custom\Yak-s-n8n-nodes"
SET "CONDA_PATH=C:\Users\2rile\miniconda3"

:: ##################################################################
:: ##                  (No changes needed below)                   ##
:: ##################################################################

:: Set the current directory to the project path to ensure npm commands work
cd /d "%PROJECT_PATH%"

ECHO.
ECHO --- Building n8n Nodes... ---
call npm run build

ECHO.
ECHO --- Launching Services Silently in the Background... ---

:: We use PowerShell's Start-Process command, which is the most reliable way
:: to launch processes silently in the background on modern Windows.

ECHO Starting ComfyUI Server...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '-n', 'yak_comfyui_env', '--no-capture-output', 'python', 'main.py' -WorkingDirectory '%PROJECT_PATH%\Software\ComfyUI' -WindowStyle Hidden"

ECHO Starting ComfyUI Gatekeeper...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '-n', 'yak_comfyui_env', '--no-capture-output', 'uvicorn', 'gatekeeper:app', '--reload' -WorkingDirectory '%PROJECT_PATH%\nodes\Yak-ComfyUI' -WindowStyle Hidden"

ECHO Starting MuseTalk Gatekeeper...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '-n', 'yak_musetalk_env', '--no-capture-output', 'uvicorn', 'gatekeeper:app', '--reload' -WorkingDirectory '%PROJECT_PATH%\nodes\Yak-MuseTalk' -WindowStyle Hidden"

ECHO Starting n8n Server...
wscript.exe "%PROJECT_PATH%\run_silent.vbs" "cmd /c n8n"


ECHO.
ECHO --- All services have been started in the background. ---
ECHO Please allow 15-30 seconds for all services to initialize.
timeout /t 5 >nul
