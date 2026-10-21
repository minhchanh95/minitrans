#!/bin/bash
cd "$(dirname "$0")"
.venv/bin/python -m pip install pyinstaller
.venv/bin/pyinstaller --noconfirm --windowed --name MiniTrans \
  --collect-all faster_whisper --collect-all ctranslate2 \
  $( .venv/bin/python -c "import mlx_whisper" 2>/dev/null && echo "--collect-all mlx_whisper --collect-all mlx" ) \
  run.py
# Khai báo quyền micro, nếu thiếu macOS sẽ chặn thu âm trong bản .app
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 'MiniTrans cần micro để dịch giọng nói.'" dist/MiniTrans.app/Contents/Info.plist 2>/dev/null
echo "App: dist/MiniTrans.app"
