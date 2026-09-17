@echo off
REM YouTube Clip Hanger - Windows run script
REM Run from ROOT: .\run.bat  or double-click

echo === YouTube Clip Hanger Backend ===
echo Current dir: %CD%

echo.
echo [1/2] Installing Python deps (Windows-friendly, no C++ build tools needed)...
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
if %errorlevel% neq 0 (
  echo.
  echo First install failed, trying Windows minimal requirements...
  python -m pip install -r backend\requirements-windows.txt
)
if %errorlevel% neq 0 (
  echo.
  echo Trying with --only-binary to avoid building av...
  python -m pip install --only-binary=:all: -r backend\requirements.txt
)
if %errorlevel% neq 0 (
  echo.
  echo Trying pip3...
  pip3 install -r backend\requirements.txt
  if %errorlevel% neq 0 pip3 install -r backend\requirements-windows.txt
)

echo.
echo [2/2] Starting backend on http://0.0.0.0:8000 ...
echo Check health: http://localhost:8000/api/health
echo Docs: http://localhost:8000/docs
echo Press CTRL+C to stop
echo.

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
if %errorlevel% neq 0 (
  echo.
  echo Failed with 'python'. Trying 'py' launcher...
  py -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
)
