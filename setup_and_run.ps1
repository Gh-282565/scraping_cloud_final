# setup_and_run.ps1
# Usage: Right-click > Run with PowerShell (or: powershell -ExecutionPolicy Bypass -File .\setup_and_run.ps1)
# This script sets up a Python venv, installs requirements, and launches the Flask app.

$ErrorActionPreference = "Stop"

Write-Host "== Scraping Cloud — Setup & Run ==" -ForegroundColor Cyan

# 1) Ensure we're in the project root (the folder that contains app.py and requirements.txt)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
Write-Host "[DBG] Working dir:" (Get-Location)

# 2) Check Python
try {
  $pyVer = python --version
  Write-Host "[OK] Python:" $pyVer
} catch {
  Write-Host "[ERR] Python non trovato. Installa Python 3.11+ e riprova." -ForegroundColor Red
  exit 1
}

# 3) Create venv if missing
if (!(Test-Path ".venv")) {
  Write-Host "[ACT] Creo ambiente virtuale .venv ..."
  python -m venv .venv
}

# 4) Activate venv
Write-Host "[ACT] Attivo venv ..."
$venvActivate = ".\.venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
  & $venvActivate
} else {
  Write-Host "[ERR] venv non trovato in .venv\Scripts. Interrompo." -ForegroundColor Red
  exit 1
}

# 5) Upgrade pip & install requirements
Write-Host "[ACT] Aggiorno pip ..."
python -m pip install --upgrade pip wheel

if (Test-Path ".\requirements.txt") {
  Write-Host "[ACT] Installo requirements ..."
  pip install -r requirements.txt
} else {
  Write-Host "[WARN] requirements.txt non trovato; provo comunque ad avviare."
}

# 6) Ensure results dir
if (!(Test-Path ".\results")) {
  New-Item -ItemType Directory -Path ".\results" | Out-Null
}

# 7) Optional env vars
$env:FLASK_SECRET_KEY = "dev-key"

# 8) Run app
Write-Host "[RUN] Avvio Flask app su http://127.0.0.1:8000 ..."
python app.py
