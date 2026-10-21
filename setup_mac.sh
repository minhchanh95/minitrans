#!/bin/bash
cd "$(dirname "$0")"
PY=$(command -v python3.12 || command -v python3.11 || command -v python3)
[ -z "$PY" ] && { echo "Chưa có Python: brew install python@3.12"; exit 1; }
[ -d .venv ] || { echo "[1/2] Tạo .venv bằng $PY"; "$PY" -m venv .venv || exit 1; }
echo "[2/2] Cài thư viện..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt || exit 1
echo "Xong! Chạy app: ./run_mac.command"
