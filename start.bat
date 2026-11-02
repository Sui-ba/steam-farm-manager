@echo off
cd /d "%~dp0"
if not exist ".env" copy /Y ".env.example" ".env" >nul
where pythonw >nul 2>&1 && start "" pythonw server.py && exit /b
python server.py
