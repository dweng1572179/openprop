@echo off
taskkill /f /im uvicorn.exe >nul 2>nul
echo OpenProp stopped. You can close this window.
pause
