@echo off
setlocal

:: 1. Go to the root of the project to find the config file
cd ..\..

:: 2. Load the shared configuration from the root directory
call local_config.bat

:: 3. Go back to the gatekeeper's directory
cd nodes\Yak-Wan2GP

:: 4. Activate the correct conda environment using the loaded path
call "%CONDA_PATH%\Scripts\activate.bat" wan2gp

:: 5. Run the gatekeeper
echo Starting Yak-Wan2GP Gatekeeper...
python gatekeeper.py

endlocal