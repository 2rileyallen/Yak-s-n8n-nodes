@echo off
ECHO --- Stopping All Services ---

ECHO.
ECHO --- Shutting down Python-based Gatekeepers and Servers... ---
powershell -command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*gatekeeper.py*' -or $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

ECHO.
ECHO --- Shutting down n8n Server... ---
powershell -command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*n8n*' -and $_.Name -eq 'node.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

ECHO.
ECHO --- All services have been shut down. Window will close in 5 seconds... ---
timeout /t 5 >nul
