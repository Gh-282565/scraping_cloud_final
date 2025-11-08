# Scraping in Cloud — Starter (Flask + Playwright-ready)

> **Come usarlo**: è un prototipo pronto per deploy su Render/Railway/Docker. La parte di scraping è un **stub**: sostituisci `scraper_core/scraper.py` con le tue funzioni Zillow/Realtor.

## Requisiti
- Python 3.11+
- (Opzionale) Playwright per headless browser: `pip install playwright` e poi `playwright install --with-deps chromium`
- pandas, openpyxl

## Avvio locale
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# (Opzionale) playwright install --with-deps chromium
export FLASK_APP=app.py  # Windows: set FLASK_APP=app.py
flask run --host=0.0.0.0 --port=8000
```
Apri http://localhost:8000

## Struttura
```
app.py
scraper_core/
  __init__.py
  scraper.py        # QUI inserisci il tuo scraping reale (Zillow/Realtor)
templates/
  index.html        # Form input
  result.html       # Pagina risultati + link download
static/
  style.css
requirements.txt
Procfile
render.yaml         # Esempio per Render.com
Dockerfile
```

## Deploy su Render (Free)
1. Fai push su GitHub.
2. Su Render: New → Web Service → collega repo.
3. Runtime: Python 3.11, Build Command:
   ```bash
   pip install -r requirements.txt
   python -m playwright install --with-deps chromium || true
   ```
   Start Command:
   ```bash
   gunicorn app:app -b 0.0.0.0:$PORT --timeout 600
   ```
4. Imposta variabili d'ambiente se servono (es. `PYTHONUNBUFFERED=1`).

> **Nota**: alcuni host free limitano l'uso di browser headless. Playwright con `--with-deps` spesso funziona; in alternativa, usa `requests+bs4` ove possibile.

## Deploy su Railway (Free tier variabile)
- Simile a Render. Aggiungi i comandi di build/start come sopra nelle impostazioni del servizio.

## Dove collegare i tuoi script
- Sostituisci `scraper_core/scraper.py` (funzione `run_scraping`) richiamando le tue routine Zillow/Realtor già pronte.
- Restituisci un `pandas.DataFrame` con le colonne che ti servono. Il salvataggio Excel e il download sono già gestiti.

## Output
- Salva in `results/risultati_estrazione.xlsx` (Foglio1), sovrascritto ad ogni esecuzione.
- Il link per il download è mostrato a fine scraping.

## Sicurezza
- Questa demo esegue sincronamente e non usa code/worker. Per job lunghi, valuta Celery + Redis (piani free permettono setup base).
