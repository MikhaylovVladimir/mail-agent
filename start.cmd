@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run: python -m venv .venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
