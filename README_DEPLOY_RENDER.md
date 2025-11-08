# Deploy to Render (Docker) — Scraping Cloud

This repo is ready to deploy on Render **without changing your scraping code**.
We run Chrome via **xvfb-run** so `undetected-chromedriver` can operate headless even if your code
doesn't add `--headless`.

## Files included
- `Dockerfile`: installs Chromium + Chromedriver + Xvfb and starts gunicorn under Xvfb.
- `requirements.txt`: pins Flask/Selenium/UC/Pandas/Openpyxl.
- `render.yaml`: one-click blueprint for Render (Docker web service).
- `.renderignore`: avoids uploading results, local caches, and heavy files.

## Pre‑flight checklist
1. Ensure your repo contains:
   - `app.py` exposing `app` (Flask WSGI) ✅
   - `scraper_core/` package with `__init__.py`, `scraper.py`, `realtor_scrape.py`, `zillow_scrape.py`, `zillow_test_scrape.py`, `zillow_avg_runner.py`
   - `templates/index.html` and any static assets the page needs
   - `parametri.xlsx` at repo root or in `data/parametri.xlsx` (the loader checks both)
2. Commit the deployment files alongside your code:
   - `Dockerfile`, `requirements.txt`, `render.yaml`, `.renderignore`
3. Push to GitHub.
4. On Render → **New +** → **Blueprint** → connect repo → pick `render.yaml` → Deploy.

## Notes specific to your code
- `data_loader.load_parametri()` searches `parametri.xlsx` in the project root, parent, or `data/` folder. Keep one of those paths present in the repo. 
- `app.py` creates `results/` and serves downloads from there. This folder is created at runtime in the Docker image.
- Selenium/Chrome: we use Debian's `chromium` and `chromium-driver`. `undetected-chromedriver` will find them at `/usr/bin/chromium` and `/usr/bin/chromedriver`.
- No code change is required for headless: Xvfb provides a virtual display for your existing non‑headless options.

## Troubleshooting
- **Chrome doesn't start**: Check Render logs. Confirm `chromium` and `chromium-driver` are installed (they are in this image). If Zillow/Realtor change front‑end, retry later.
- **`parametri.xlsx non trovato`**: put it at repo root or `data/parametri.xlsx` (the loader searches both).
- **Downloads show "Nessun file generato"**: look at logs; the orchestrator reports `[ERR]`/`[WARN]` messages which the UI surfaces as flashes.
