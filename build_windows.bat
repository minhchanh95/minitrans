@echo off
cd /d "%~dp0"
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --windowed --name MiniTrans --collect-all faster_whisper --collect-all ctranslate2 run.py
echo File chay: dist\MiniTrans\MiniTrans.exe
pause
