@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  echo [1/2] Tao moi truong ao .venv ...
  %PY% -m venv .venv || (echo Khong tim thay Python. Cai Python 3.11/3.12 tu python.org, tick "Add to PATH". & pause & exit /b 1)
)
echo [2/2] Cai thu vien ...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
echo.
echo Xong! Chay app bang file run_windows.bat
pause
