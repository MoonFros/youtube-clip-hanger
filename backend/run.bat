@echo off
REM Run from backend folder OR root
cd /d "%~dp0.."
echo === YouTube Clip Hanger Backend ===
echo Current dir: %CD%

echo.
echo [1/2] Installing Python deps (Windows fix for av build error)...
python -m pip install -r backend\requirements.txt
if %errorlevel% neq 0 (
  echo Trying Windows minimal...
  python -m pip install -r backend\requirements-windows.txt
)
if %errorlevel% neq 0 (
  python -m pip install --only-binary=:all: -r backend\requirements.txt
)
if %errorlevel% neq 0 (
  pip3 install -r backend\requirements.txt
)

echo.
echo [2/2] Starting backend on http://0.0.0.0:8000 ...
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
if %errorlevel% neq 0 (
  py -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
)
