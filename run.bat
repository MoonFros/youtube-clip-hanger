@echo off
REM ============================================================
REM  FairClip - start the whole app (backend :8000 + web :3000)
REM  Double-click this file, or run it from the repo root.
REM      run.bat            -> backend + frontend
REM      run.bat backend    -> backend only
REM      run.bat web        -> frontend only
REM ============================================================
setlocal
cd /d "%~dp0"
set WHAT=%1
if "%WHAT%"=="" set WHAT=all

echo === FairClip ===
echo repo: %CD%
echo.

REM ---------- python ----------
set PY=python
where python >nul 2>nul || set PY=py

if "%WHAT%"=="all" goto setup
if "%WHAT%"=="backend" goto setup
goto web_setup

:setup
if not exist "backend\.venv" (
  echo [setup] creating backend\.venv ...
  %PY% -m venv backend\.venv
)
if not exist "backend\.venv\.deps-ok" (
  echo [setup] installing python deps ^(one time, ~2 min^)...
  backend\.venv\Scripts\python.exe -m pip install --upgrade pip
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo.
    echo [error] pip install failed. Try the minimal set:
    echo     backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-windows.txt
    pause
    exit /b 1
  )
  echo ok> "backend\.venv\.deps-ok"
)

:web_setup
if "%WHAT%"=="all" goto start
if "%WHAT%"=="web" goto start
goto start

:start
if "%WHAT%"=="all" goto start_all
if "%WHAT%"=="backend" goto start_backend
if "%WHAT%"=="web" goto start_web

:start_all
if not exist "frontend\node_modules" (
  echo [setup] installing frontend deps ^(one time^)...
  call npm --prefix frontend install
)
echo [1/2] backend  -^> http://localhost:8000/api/health
start "FairClip API" /D "%CD%" cmd /k "backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75"
echo [2/2] frontend -^> http://localhost:3000
start "FairClip Web" /D "%CD%" cmd /k "npm --prefix frontend run dev"
echo.
echo Both windows are opening. Open http://localhost:3000 in your browser.
timeout /t 6 >nul
goto :eof

:start_backend
echo [1/1] backend -^> http://localhost:8000/api/health
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75
goto :eof

:start_web
if not exist "frontend\node_modules" (
  echo [setup] installing frontend deps ^(one time^)...
  call npm --prefix frontend install
)
echo [1/1] frontend -^> http://localhost:3000
call npm --prefix frontend run dev
goto :eof
