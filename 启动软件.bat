@echo off
cd /d "%~dp0"
set "LOG=%~dp0startup_error.log"
set "PYTHONW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=pythonw.exe"
start "" "%PYTHONW%" "%~dp0main.py"
timeout /t 2 /nobreak >nul
if not exist "%LOG%" exit /b 0
findstr /c:"--- startup failure ---" "%LOG%" >nul
if errorlevel 1 exit /b 0
start "" notepad.exe "%LOG%"
