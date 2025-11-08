@echo off
REM === Avvio automatico ambiente Flask (Scraping Cloud) ===
cd /d "%~dp0"
echo [INFO] Attivo ambiente virtuale...
call .\venv\Scripts\activate

echo [INFO] Avvio server Flask su http://127.0.0.1:5000 ...
set FLASK_APP=app.py
set FLASK_DEBUG=1

start "" "http://127.0.0.1:5000"
python -m flask run --host=127.0.0.1 --port=5000

pause
