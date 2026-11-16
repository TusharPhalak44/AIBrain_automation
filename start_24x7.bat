@echo off
TITLE XM Global MT5 V2 Trading Portal - 24/7 Production Launcher
COLOR 0B

echo ===============================================================================
echo     XM GLOBAL MT5 V2 MULTI-ASSET AUTOMATED TRADING PORTAL
echo     Forex Majors, Gold, BTC, ETH, and SOL Institutional Algorithmic Engine
echo ===============================================================================
echo.

cd /d "%~dp0"

:: 1. Verify and Start XAMPP MySQL
echo [*] Checking XAMPP MySQL service on port 3306...
netstat -ano | findstr :3306 >nul
if %errorlevel% equ 0 (
    echo [OK] MySQL is active on port 3306.
) else (
    echo [!] MySQL not detected. Starting mysqld from C:\xampp\mysql\bin...
    start "XAMPP MySQL Daemon" /min "C:\xampp\mysql\bin\mysqld.exe" --defaults-file="C:\xampp\mysql\bin\my.ini" --console
    timeout /t 3 /nobreak >nul
)

:: 2. Check Python Virtual Environment
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe!
    pause
    exit /b 1
)

:: 3. Check MT5 Terminal
set "MT5_PATH=C:\Program Files\XM Global MT5\terminal64.exe"
if exist "%MT5_PATH%" (
    tasklist /fi "imagename eq terminal64.exe" 2>nul | findstr /i "terminal64.exe" >nul
    if %errorlevel% neq 0 (
        echo [*] Launching XM Global MT5 Terminal...
        start "" "%MT5_PATH%"
    ) else (
        echo [OK] XM Global MT5 terminal64.exe is already running.
    )
) else (
    echo [i] Note: XM MT5 terminal path not found at default location. You can configure it in Settings.
)

:: 4. Start FastAPI Backend (:8000)
echo [*] Starting FastAPI Backend on http://127.0.0.1:8000...
start "XM Trading Portal - Backend (:8000)" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.api.server:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 2 /nobreak >nul

:: 5. Start Vite Frontend (:3000)
echo [*] Starting Vite React Terminal on http://127.0.0.1:3000...
start "XM Trading Portal - Frontend (:3000)" cmd /k "npm --prefix frontend run dev -- --host 127.0.0.1 --port 3000"

timeout /t 3 /nobreak >nul

:: 6. Launch Browser
echo [*] Opening Institutional Terminal in browser...
start http://localhost:3000

echo.
echo ===============================================================================
echo [SUCCESS] XM Global MT5 V2 Portal is now running 24/7!
echo   - Web Terminal:   http://localhost:3000
echo   - Backend API:    http://localhost:8000
echo   - API Docs:       http://localhost:8000/docs
echo   - WebSocket:      ws://localhost:8000/ws/live
echo ===============================================================================
echo.
echo Keep this console open or minimize it. Press any key to stop all services...
pause >nul

echo.
echo [*] Stopping services...
taskkill /f /im node.exe 2>nul
taskkill /f /im uvicorn.exe 2>nul
echo [OK] Shutdown complete.

