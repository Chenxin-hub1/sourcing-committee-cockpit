@echo off
rem Sourcing Committee Cockpit - background start for Task Scheduler (no console window).
rem Same as start.bat, but all output goes to backend\data\server.log so problems can be inspected later.
cd /d "%~dp0backend"
if not exist data mkdir data
if not exist "%~dp0.env" exit /b 1
set "PORT=8031"
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%~dp0.env") do (
  if /i "%%a"=="SC_PORT" if not "%%b"=="" set "PORT=%%b"
)
echo [%date% %time%] starting on port %PORT% >> data\server.log
"%~dp0windows-portable\python\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% --workers 1 >> data\server.log 2>&1
