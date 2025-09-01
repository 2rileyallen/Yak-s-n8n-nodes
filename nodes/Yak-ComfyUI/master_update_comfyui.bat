@echo off
ECHO --- Starting Yak-ComfyUI Node Environment Update ---

:: This script is now called from its own directory, so relative paths are reliable.

:: ------------------------------------------------------------------
:: Activate the Conda environment
:: ------------------------------------------------------------------
ECHO.
ECHO --- Activating Conda Environment: yak_comfyui_env ---
call conda activate yak_comfyui_env

:: The Python requirements are now handled by the main update script.

:: ------------------------------------------------------------------
:: Synchronize the required custom nodes for the workflows
:: ------------------------------------------------------------------
ECHO.
ECHO ======================================================
ECHO  SYNCHRONIZING CUSTOM NODES
ECHO ======================================================
call "manage_custom_nodes.bat"

:: ------------------------------------------------------------------
:: Synchronize the required models for the workflows
:: ------------------------------------------------------------------
ECHO.
ECHO ======================================================
ECHO  SYNCHRONIZING MODELS
ECHO ======================================================
call "manage_models.bat"

ECHO.
ECHO --- Yak-ComfyUI Node Environment Update Complete ---
:: The PAUSE command is removed from this sub-script so the main script can finish.
