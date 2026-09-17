@echo off
REM Run from backend folder OR root
cd /d "%~dp0.."
echo === YouTube Clip Hanger Backend ===
echo Current dir: %CD%

echo.
echo [1/2] Installing Python deps...
python -m pip install -r backend\requirements.txt
if %errorlevel% neq 0 (
  pip3 install -r backend\requirements.txt
)

echo.
echo [2/2] Starting backend on http://0.0.0.0:8000 ...
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
if %errorlevel% neq 0 (
  py -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
)
