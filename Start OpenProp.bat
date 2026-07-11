@echo off
cd /d "%~dp0"
echo Starting OpenProp - the first time takes a few minutes. Please wait...
docker compose up -d || (echo Could not start. Is Docker Desktop open? & pause & exit /b 1)
timeout /t 10 >nul
start "" http://localhost:8787
echo OpenProp is open at http://localhost:8787
pause
