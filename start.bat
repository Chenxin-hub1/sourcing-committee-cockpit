@echo off
rem Sourcing Committee Cockpit - portable start for Windows (no admin rights, no Docker, no install).
rem Runtime lives in windows-portable\python ; data is written to backend\data ; settings come from .env next to this file.
cd /d "%~dp0backend"
if not exist data mkdir data
if not exist "%~dp0.env" (
  echo [!] .env not found. Copy .env.example to .env and fill it in first.
  pause
  exit /b 1
)
echo Sourcing Committee Cockpit is starting on http://localhost:8031/
echo Keep this window open. Close it (or press Ctrl+C) to stop the service.
"%~dp0windows-portable\python\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8031 --workers 1
pause
