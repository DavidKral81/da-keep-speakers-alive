@echo off
rem Starts Da Keep Speakers Alive in the background (no console window).
rem   start.bat            just the tray icon
rem   start.bat --show     opens the settings window straight away
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "windows\keep_alive.py" %*
