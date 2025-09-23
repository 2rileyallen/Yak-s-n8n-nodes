@echo off
TITLE Master Service Starter

:: ##################################################################
:: ##  This script now loads paths from your local configuration.  ##
:: ##  Run setup.bat once if you haven't already.                  ##
:: ##################################################################

:: --- Load local configuration ---
if not exist "local_config.bat" (
    ECHO [ERROR] Configuration file 'local_config.bat' not found.
    ECHO Please run the setup.bat script once before using this script.
    PAUSE
    exit /b
)
call local_config.bat

:: Set the current directory to the project path to ensure commands work
cd /d "%PROJECT_PATH%"

ECHO.
ECHO --- Launching Services Silently in the Background... ---
ECHO Using Project Path: %PROJECT_PATH%
ECHO Using Conda Path:   %CONDA_PATH%
ECHO.

:: We use PowerShell's Start-Process command, which is the most reliable way
:: to launch processes silently in the background on modern Windows.

ECHO Starting ComfyUI Server...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '-n', 'yak_comfyui_env', '--no-capture-output', 'python', 'main.py' -WorkingDirectory '%PROJECT_PATH%\Software\ComfyUI' -WindowStyle Hidden"

ECHO Starting ComfyUI Gatekeeper...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '-n', 'yak_comfyui_env', '--no-capture-output', 'uvicorn', 'gatekeeper:app', '--reload', '--port', '8189' -WorkingDirectory '%PROJECT_PATH%\nodes\Yak-ComfyUI' -WindowStyle Hidden"

ECHO Starting MuseTalk Gatekeeper...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '-n', 'yak_musetalk_env', '--no-capture-output', 'uvicorn', 'gatekeeper:app', '--reload' -WorkingDirectory '%PROJECT_PATH%\nodes\Yak-MuseTalk' -WindowStyle Hidden"

ECHO Starting IndexTTS2 Gatekeeper...
powershell -command "Start-Process -FilePath '%CONDA_PATH%\condabin\conda.bat' -ArgumentList 'run', '--cwd', '%PROJECT_PATH%\Software\IndexTTS2', '-n', 'yak_indextts2_env', '--no-capture-output', 'uv', 'run', 'python', '%PROJECT_PATH%\nodes\Yak-IndexTTS2\gatekeeper.py' -WindowStyle Hidden"

ECHO Starting n8n Server...
wscript.exe "%PROJECT_PATH%\run_silent.vbs" "cmd /c n8n"


ECHO.
ECHO --- All services have been started in the background. ---
ECHO Please allow 15-30 seconds for all services to initialize.
timeout /t 5 >nul

