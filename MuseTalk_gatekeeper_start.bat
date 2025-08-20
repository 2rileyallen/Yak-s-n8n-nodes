@echo off
setlocal EnableDelayedExpansion

rem ######################################################################
rem ### Yak-s-N8N-nodes Gatekeeper Startup Script for Windows          ###
rem ### This script activates the correct Conda environment and        ###
rem ### launches the MuseTalk Gatekeeper server.                       ###
rem ######################################################################

echo Activating Conda environment: yak_musetalk_env
rem Use 'call' to ensure the script continues after this command
call conda activate yak_musetalk_env

echo.
echo Starting Gatekeeper server...
echo (To stop the server, press CTRL+C in this window)
echo.

rem Run the Gatekeeper Python script using its relative path from the root
python nodes/Yak-MuseTalk/gatekeeper.py

rem Keep the window open after the server is stopped
echo.
echo Gatekeeper server has been stopped. Press any key to close this window.
pause > nul
