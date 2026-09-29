@echo off
rem Sourcing Committee Cockpit - portable start for Windows (no admin rights, no Docker, no install).
rem Runtime lives in windows-portable\python ; data is written to backend\data ; settings come from .env next to this file.
rem Port: SC_PORT in .env (default 8031). Port 80 needs no admin rights on Windows as long as nothing else uses it.
cd /d "%~dp0backend"
if not exist data mkdir data
if not exist "%~dp0.env" (
  echo [!] .env not found. Copy .env.example to .env and fill it in first.
  pause
  exit /b 1
)
set "PORT=8031"
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0.env") do (
  if /i "%%a"=="SC_PORT" if not "%%b"=="" set "PORT=%%b"
)
echo Sourcing Committee Cockpit is starting on http://localhost:%PORT%/
echo Keep this window open. Close it (or press Ctrl+C) to stop the service.
"%~dp0windows-portable\python\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --workers 1
pause
