@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1 && start "" pythonw server.py && exit /b
python server.py
