@echo off
TITLE One-Time Project Setup

ECHO.
ECHO ##################################################################
ECHO ##                                                              ##
ECHO ##           Welcome to the Yak's n8n Nodes Project Setup       ##
ECHO ##                                                              ##
ECHO ##  This script will configure the project for your machine.    ##
ECHO ##  You only need to run this once.                             ##
ECHO ##                                                              ##
ECHO ##################################################################
ECHO.

:: --- Step 1: Get the Project Path ---
:: The script is located in the project root, so we can get its path automatically.
SET "PROJECT_PATH=%~dp0"
:: Remove the trailing backslash for a clean path
SET "PROJECT_PATH=%PROJECT_PATH:~0,-1%"
ECHO The project path has been automatically detected as:
ECHO %PROJECT_PATH%
ECHO.

:: --- Step 2: Get the Conda Path ---
set /p CONDA_PATH="Please enter the full path to your miniconda3 or anaconda3 folder and press Enter: "
ECHO.

:: Validate that the path looks reasonable
if not exist "%CONDA_PATH%\condabin\conda.bat" (
    ECHO [ERROR] The path you entered does not seem to be a valid Conda installation.
    ECHO         Could not find 'condabin\conda.bat' inside the provided folder.
    ECHO         Please run this script again and provide the correct path.
    ECHO.
    PAUSE
    exit /b
)

:: --- Step 3: Create the local_config.bat file ---
ECHO Creating your local configuration file (local_config.bat)...
(
    echo @echo off
    echo :: This is an auto-generated file. Do not edit it directly.
    echo :: To change these paths, run the setup.bat script again.
    echo.
    echo SET "PROJECT_PATH=%PROJECT_PATH%"
    echo SET "CONDA_PATH=%CONDA_PATH%"
) > local_config.bat

ECHO.
ECHO --- Setup Complete! ---
ECHO Your local paths have been saved. You can now use the master scripts.
ECHO Window will close in 10 seconds...
timeout /t 10 >nul
