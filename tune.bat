@echo off
rem Runs tools\tune.py inside the project venv, so you do not have to type paths.
rem Usage:  tune.bat --list
rem         tune.bat --tone --device 23 --freq 20 --amp 1.0
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.venv\Scripts\python.exe" (
    echo The project venv is missing. Create it with:
    echo     py -m venv "%HERE%.venv"
    echo     "%HERE%.venv\Scripts\python.exe" -m pip install sounddevice numpy
    exit /b 1
)
"%HERE%.venv\Scripts\python.exe" "%HERE%tools\tune.py" %*
