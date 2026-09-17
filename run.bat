@echo off
REM YouTube Clip Hanger - Windows run script
REM Double-click this or run in PowerShell: .\run.bat

echo === YouTube Clip Hanger Backend ===
echo Installing requirements...
pip install -r backend\requirements.txt

echo.
echo Starting backend on http://0.0.0.0:8000 ...
echo Check health: http://localhost:8000/api/health
echo Docs: http://localhost:8000/docs
echo Press CTRL+C to stop
echo.

python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
