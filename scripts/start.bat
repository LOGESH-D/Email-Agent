@echo off
REM Resolve project root from the script's own location (scripts\ is one level down)
set PROJECT_ROOT=%~dp0..

echo Starting Mail Analyzer Agent...
echo Project root: %PROJECT_ROOT%
echo.

REM Kill any process already using port 8000
echo Freeing port 8000...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8000 "') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak > nul

REM Terminal 1 — ngrok tunnel
start "ngrok tunnel" cmd /k "cd /d %PROJECT_ROOT% && venv\Scripts\activate && python scripts\tunnel.py"

REM Wait for ngrok to start
timeout /t 3 /nobreak > nul

REM Terminal 2 — webhook server
start "webhook server" cmd /k "cd /d %PROJECT_ROOT% && venv\Scripts\activate && python -m src.server.webhook"

echo.
echo Both processes started.
echo Open your browser at the URL shown in the webhook server window.
echo.
pause
