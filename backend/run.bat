@echo off
REM FairClip backend only (port 8000).
REM Prefer the root run.bat which starts backend + frontend together.
setlocal
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py

if not exist ".venv" (
  echo [setup] creating backend\.venv ...
  %PY% -m venv .venv
)
if not exist ".venv\.deps-ok" (
  echo [setup] installing python deps ^(one time, ~2 min^)...
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [error] pip install failed - see the troubleshooting section of README.md
    pause
    exit /b 1
  )
  echo ok> ".venv\.deps-ok"
)

echo FairClip API -^> http://localhost:8000/api/health
REM set FAIRCLIP_RELOAD=1 before running to auto-restart on code changes
set RELOAD=
if "%FAIRCLIP_RELOAD%"=="1" set RELOAD=--reload
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75 %RELOAD%
