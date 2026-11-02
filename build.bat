@echo off
cd /d "%~dp0"
REM Собирает папку dist\SteamFarmManager. База и .env появятся рядом с exe, не внутри сборки.
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --name SteamFarmManager --console --add-data "web;web" --add-data ".env.example;." --collect-all cryptography --collect-submodules selenium server.py
echo.
echo Готово: dist\SteamFarmManager\SteamFarmManager.exe
echo Запускай exe из этой папки. Рядом появятся .env, база и ключи.
