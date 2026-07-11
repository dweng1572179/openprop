@echo off
rem Double-click to start OpenProp. No Docker needed - just Python.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
where python >nul 2>nul || (
  echo Python is not installed.
  echo Get it from https://www.python.org/downloads/ - tick "Add python.exe to PATH" - then double-click this file again.
  pause & exit /b 1
)
if not exist .venv\Scripts\uvicorn.exe (
  echo First run - installing OpenProp. This takes a couple of minutes...
  python -m venv .venv && .venv\Scripts\pip install -q -r requirements.txt || (echo Install failed. & pause & exit /b 1)
)
if not defined OPENPROP_PORT set OPENPROP_PORT=8787
echo Starting OpenProp at http://localhost:%OPENPROP_PORT%
start "OpenProp - leave this window open" .venv\Scripts\uvicorn.exe app.app:app --host 127.0.0.1 --port %OPENPROP_PORT%
timeout /t 8 >nul
start "" http://localhost:%OPENPROP_PORT%
