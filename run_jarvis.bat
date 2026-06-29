@echo off
cd /d "%~dp0"
echo [JARVIS] Activating virtual environment and launching system...
venv\Scripts\python.exe main.py
if %errorlevel% neq 0 (
    echo.
    echo [JARVIS] Error: System exited with code %errorlevel%.
    echo [JARVIS] Please check if venv contains all requirements.
    pause
)
