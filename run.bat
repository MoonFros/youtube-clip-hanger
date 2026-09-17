@echo off
REM ============================================================
REM  FairClip - start the whole app (backend :8000 + web :3000)
REM  Double-click this file, or run it from the repo root.
REM      run.bat            -> backend + frontend
REM      run.bat backend    -> backend only
REM      run.bat web        -> frontend only
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set WHAT=%1
if "%WHAT%"=="" set WHAT=all

echo === FairClip ===
echo repo: %CD%
echo.

REM ---------- find a python ----------
set PY=python
where python >nul 2>nul || set PY=py
set PYBITS=?
set PYVER=?
for /f "delims=" %%v in ('%PY% -c "import sys;print(%%d.%%d.%%d%%sys.version_info[:3])" 2^>nul') do set PYVER=%%v
for /f "delims=" %%a in ('%PY% -c "import struct;print(struct.calcsize('P')*8)" 2^>nul') do set PYBITS=%%a
echo [info] Python %PYVER% ^(%PYBITS%-bit^)
%PY% -c "import sys;print('       ', sys.executable)" 2>nul

if "%PYVER%"=="?" (
  echo [error] No working Python found. Install Python 3.12 ^(64-bit^) from
  echo         https://www.python.org/downloads/  and tick "Add python.exe to PATH".
  echo         During setup, the "py launcher" option makes this script use it.
  pause
  exit /b 1
)
if not "%PYBITS%"=="64" (
  echo.
  echo [error] You are running 32-bit Python. The video engine ^(PyAV^) has NO
  echo         32-bit Windows wheels, so pip would have to compile FFmpeg from
  echo         source ^(the "Microsoft Visual C++ 14.0 or greater is required" error^).
  echo.
  echo         Fix: install the 64-bit Python 3.12 from python.org, then delete
  echo         backend\.venv and run this script again. Or start it explicitly:
  echo              py -3.12 run.bat
  pause
  exit /b 1
)

if "%WHAT%"=="all" goto setup
if "%WHAT%"=="backend" goto setup
goto web_setup

:setup
if not exist "backend\.venv" (
  echo [setup] creating backend\.venv ...
  %PY% -m venv backend\.venv
  if errorlevel 1 (
    echo [error] could not create the virtualenv. Is the "venv" module available?
    pause
    exit /b 1
  )
)
if not exist "backend\.venv\.deps-ok" (
  echo [setup] installing python deps ^(one time, ~2 min^)...
  backend\.venv\Scripts\python.exe -m pip install --upgrade pip
  REM --only-binary for the compiled packages: every one of them ships wheels, so
  REM a source build here means this Python has no matching wheel. Failing fast
  REM gives a clear message instead of a 10-minute MSVC error dump.
  backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt ^
      --only-binary=av,numpy,pillow,yt-dlp
  if errorlevel 1 (
    echo.
    echo ============================================================
    echo  pip could not install the backend dependencies.
    echo.
    echo  If the message above mentions "Microsoft Visual C++" or
    echo  "Failed building wheel", it means no prebuilt wheel exists for
    echo  Python %PYVER% ^(%PYBITS%-bit^).
    echo.
    echo  Try, in this order:
    echo    1. a newer pip:   backend\.venv\Scripts\python.exe -m pip install -U pip
    echo    2. Python 3.12 ^(64-bit^): py -3.12 -m venv backend\.venv
    echo       then run this script again
    echo    3. delete backend\.venv and rerun - it will rebuild cleanly
    echo ============================================================
    pause
    exit /b 1
  )
  echo ok> "backend\.venv\.deps-ok"
)

:web_setup
if "%WHAT%"=="backend" goto start_backend
if "%WHAT%"=="web" goto start_web

:start_all
if not exist "frontend\node_modules" (
  echo [setup] installing frontend deps ^(one time^)...
  call npm --prefix frontend install
  if errorlevel 1 (
    echo [error] npm install failed - is Node 20+ installed? https://nodejs.org
    pause
    exit /b 1
  )
)
echo [1/2] backend  -^> http://localhost:8000/api/health
start "FairClip API" /D "%CD%" cmd /k "backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75"
echo [2/2] frontend -^> http://localhost:3000
start "FairClip Web" /D "%CD%" cmd /k "npm --prefix frontend run dev"
echo.
echo Both windows are opening. Open http://localhost:3000 in your browser.
echo If something fails: give the API window a second, then click "Retry now"
echo in the red banner at the top of the page.
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
