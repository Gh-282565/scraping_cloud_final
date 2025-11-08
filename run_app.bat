@echo off
REM run_app.bat - Activates venv and starts the Flask app (Windows)
setlocal ENABLEEXTENSIONS ENABLEDELAYEDEXPANSION

REM Ensure we are in the script dir
cd /d "%~dp0"

IF NOT EXIST ".venv\Scripts\activate.bat" (
  echo [ERR] venv non trovato. Esegui prima: powershell -ExecutionPolicy Bypass -File setup_and_run.ps1
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
set FLASK_SECRET_KEY=dev-key

echo [RUN] Avvio Flask app su http://127.0.0.1:8000 ...
python app.py
pause
