@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (call setup_windows.bat)
.venv\Scripts\python run.py
if errorlevel 1 pause
