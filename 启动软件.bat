@echo off
setlocal
cd /d "%~dp0"
set "PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
set "PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%~dp0main.py" (
    echo Cannot find application entry point: %~dp0main.py
    pause
    exit /b 1
)

if exist "%PYTHONW%" (
    start "" "%PYTHONW%" "%~dp0main.py"
    exit /b 0
)

if exist "%PYTHON%" (
    echo pythonw.exe is missing; starting with a console window.
    start "" "%PYTHON%" "%~dp0main.py"
    exit /b 0
)

echo Cannot find Python in the project's .venv\Scripts directory.
echo Please install the dependencies or recreate the virtual environment.
pause
exit /b 1
