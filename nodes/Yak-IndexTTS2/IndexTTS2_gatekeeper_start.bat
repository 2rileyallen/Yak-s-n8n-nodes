@echo off
TITLE IndexTTS2_Gatekeeper

:: This script is called by master_start.bat. It assumes %PROJECT_PATH% and %CONDA_PATH% are set.

:: 1. Activate the correct Conda environment to make 'uv' available.
call "%CONDA_PATH%\condabin\conda.bat" activate yak_indextts2_env
if %errorlevel% neq 0 (
    echo [ERROR] Failed to activate Conda environment 'yak_indextts2_env'.
    pause
    exit /b
)

:: 2. The CWD must be the Software/IndexTTS2 directory for uv run to work.
cd /d "%PROJECT_PATH%\Software\IndexTTS2"

:: 3. Use 'uv run' to launch the uvicorn server.
echo "Starting IndexTTS2 Gatekeeper server..."
uv run uvicorn gatekeeper:app --port 7863 --app-dir "%PROJECT_PATH%\nodes\Yak-IndexTTS2"

