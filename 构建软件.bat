@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Project virtual environment not found. Create .venv and install requirements first.
    pause
    exit /b 1
)

"%PYTHON%" -m PyInstaller --clean --noconfirm "%~dp0AI智阅小助手.spec"
if errorlevel 1 (
    echo Build failed. Check the messages above.
    pause
    exit /b 1
)

echo Build succeeded: %~dp0dist\AI智阅小助手.exe
pause
