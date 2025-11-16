import os
import json
import importlib
import time
from datetime import datetime
from flask import (
    Flask, render_template, request, send_from_directory,
    url_for, redirect, flash, jsonify, session
)
# ⚠️ importiamo il modulo, non la funzione (così possiamo fare reload)
import scraper_core.scraper as scraper_mod
from data_loader import load_parametri
import pandas as pd  # ok anche se non usato; puoi rimuoverlo se vuoi

app = Flask(__name__)
import os
from flask import jsonify, send_from_directory, abort

RESULTS_DIR = "/app/results"
SNAP_DIR = os.path.join(RESULTS_DIR, "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

@app.get("/results")
def list_results():
    # Elenco JSON dei file in /app/results e sottocartelle
    out = []
    for root, _, files in os.walk(RESULTS_DIR):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), RESULTS_DIR).replace("\\", "/")
            out.append(rel)
    out.sort()
    return jsonify(out)

@app.get("/results/<path:fname>")
def download_result(fname: str):
    # Permetti solo percorsi dentro /app/results
    safe_root = os.path.realpath(RESULTS_DIR)
    safe_path = os.path.realpath(os.path.join(safe_root, fname))
    if not safe_path.startswith(safe_root):
        return abort(403)
    return send_from_directory(safe_root, fname, as_attachment=True)

# --- Diagnostica Chrome UC in container ---
from scraper_core.driver_factory import make_uc_driver

@app.get("/diag/uc")
def diag_uc():
    try:
        d = make_uc_driver()
        d.get("https://example.com/")
        title = d.title
        d.quit()
        return {"ok": True, "title": title}, 200
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "error": str(e),
            "trace": traceback.format_exc().splitlines()[-5:]
        }, 500

# --- PWA: route per il service worker ---
@app.route("/service-worker.js")
def service_worker():
    # Il file deve trovarsi in static/service-worker.js
    return send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript"
    )

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key")

# --- Opzionale: scadenza versione beta PWA ---
# Imposta una data (UTC) per far scadere la versione di prova,
# oppure lascia None per disattivare il controllo.
BETA_EXPIRATION = None  # es. datetime(2025, 1, 31)

@app.before_request
def check_beta_expiration():
    # Se non vuoi scadenza, lascia BETA_EXPIRATION = None
    if BETA_EXPIRATION is None:
        return
    if datetime.utcnow() > BETA_EXPIRATION:
        return "Versione di prova scaduta. Contatta l'amministratore.", 403

# ----------------------------
# No-cache per tutte le risposte
# ----------------------------
@app.after_request
def add_no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# -------------------------------------------------
# NOMI COMPLETI DEGLI STATI (sigla -> nome intero)
# -------------------------------------------------
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"
}

# -------------------------------------------------
# FUNZIONI PER CARICARE LE CONTEE
# -------------------------------------------------
def _build_counties_mapping(df):
    """Genera dict { 'FL': ['Alachua', ...], ... } da DataFrame con colonne State/County."""
    cols = {c.lower().strip(): c for c in df.columns}
    state_col = cols.get("state") or cols.get("stato")
    county_col = cols.get("county") or cols.get("contea")
    if not state_col or not county_col:
        raise ValueError("Colonne State/County non trovate in Foglio1.")

    tmp = df[[state_col, county_col]].dropna().copy()
    tmp[state_col] = tmp[state_col].astype(str).str.upper().str.strip()
    tmp[county_col] = tmp[county_col].astype(str).str.strip()

    mapping = (
        tmp.groupby(state_col)[county_col]
        .apply(lambda s: sorted(set(x for x in s if x)))
        .to_dict()
    )
    return {k: v for k, v in mapping.items() if v}

def _fallback_counties_mapping():
    """Fallback in caso di assenza file Excel."""
    return {
        "FL": ["Alachua", "Baker", "Bay", "Brevard", "Broward", "Duval", "Miami-Dade", "St. Johns"],
        "GA": ["Appling", "Bacon", "Baldwin", "Banks", "Barrow", "Bartow", "Berrien", "Bryan", "Bulloch"],
        "TX": ["Harris", "Dallas", "Travis", "Bexar", "Tarrant", "Collin"],
        "AR": ["Arkansas", "Benton", "Boone", "Bradley", "Calhoun", "Carroll", "Clark", "Clay", "Columbia"]
    }

# Precaricamento iniziale
try:
    df = load_parametri()
    COUNTIES_BY_STATE = _build_counties_mapping(df)
except Exception as e:
    print(f"[WARN] Impossibile caricare parametri.xlsx ({e}); uso fallback.")
    COUNTIES_BY_STATE = _fallback_counties_mapping()

STATES = sorted(COUNTIES_BY_STATE.keys())
STATES_FULL = [(code, STATE_NAMES.get(code, code)) for code in STATES]

# Helper: ricarica l’orchestratore e restituisce la funzione aggiornata
def _get_run_scraping():
    global scraper_mod
    scraper_mod = importlib.reload(scraper_mod)
    print("[USING SCRAPER]", scraper_mod.__file__)  # log: quale scraper.py sta usando
    return scraper_mod.run_scraping

# -------------------------------------------------
# API opzionale per test dinamico
# -------------------------------------------------
@app.route("/api/counties")
def api_counties():
    state = (request.args.get("state") or "").strip().upper()
    if not state:
        return jsonify({"ok": False, "error": "Missing state"}), 400
    try:
        df = load_parametri()
        mapping = _build_counties_mapping(df)
        return jsonify({"ok": True, "state": state, "counties": mapping.get(state, [])})
    except Exception as e:
        return jsonify({
            "ok": True,
            "state": state,
            "counties": _fallback_counties_mapping().get(state, []),
            "fallback": True
        })

# -------------------------------------------------
# PAGINA PRINCIPALE
# -------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        states_full=STATES_FULL,
        counties_json=json.dumps(COUNTIES_BY_STATE, ensure_ascii=False),
        message=None,
        download_links=None,   # compatibilità (lista)
        download_link=None,    # compatibilità (singolo)
        # nuovi flag per messaggi inline con link
        realtor_ready=False,
        realtor_url=None,
        zillow_ready=False,
        zillow_url=None,
        done=False
    )

# -------------------------------------------------
# RESET STATO / NUOVA RICERCA
# -------------------------------------------------
@app.route("/reset", methods=["GET"])
def reset():
    # Pulisci solo eventuale stato temporaneo usato per mostrare esiti
    for k in ("log_messages", "last_download", "success"):
        session.pop(k, None)
    # cache-buster per evitare riproposizione dell'HTML precedente
    return redirect(url_for("index", _=int(time.time())))

# -------------------------------------------------
# ESECUZIONE SCRAPING
# -------------------------------------------------
@app.route("/run", methods=["POST"])
@app.route("/run_scraper", methods=["POST"])
def run():
    try:
        state = (request.form.get("state") or "").strip().upper()
        county = (request.form.get("county") or "").strip()
        acres_min = int(request.form.get("min_acres", "0") or 0)
        acres_max = int(request.form.get("max_acres", "0") or 0)
        period = (request.form.get("period") or "").strip()

        include_forsale = bool(request.form.get("include_forsale"))
        include_sold    = bool(request.form.get("include_sold"))
        use_realtor     = bool(request.form.get("use_realtor"))
        use_zillow      = bool(request.form.get("use_zillow"))
        headless        = bool(request.form.get("headless"))

        print("[DEBUG FORM]", dict(request.form))

        if not state or not county:
            flash("Inserisci Stato e Contea.", "error")
            return redirect(url_for("index"))

        sources = []
        if use_realtor:
            sources.append("realtor")
        if use_zillow:
            sources.append("zillow")
        if not sources:
            flash("Seleziona almeno una fonte (Realtor o Zillow).", "error")
            return redirect(url_for("index"))

        # 🔁 usa sempre la versione aggiornata dell’orchestratore
        try:
            run_scraping = _get_run_scraping()
        except Exception as e:
            flash(f"[ERR] impossibile caricare l'orchestratore: {e}", "error")
            return redirect(url_for("index"))

        # Avvia scraping reale (robusto allo spacchettamento)
        outpaths, messages = [], []
        try:
            out = run_scraping(
                state=state,
                county=county,
                acres_min=acres_min,
                acres_max=acres_max,
                include_forsale=include_forsale,
                include_sold=include_sold,
                use_sources=sources,
                headless=headless,
                period=period
                # results_dir=RESULTS_DIR  # abilita se il tuo orchestratore lo supporta
            )

            if isinstance(out, tuple) and len(out) == 2:
                outpaths, messages = out
            elif isinstance(out, dict):
                outpaths, messages = out, []
            elif isinstance(out, (list, tuple)):
                outpaths, messages = list(out), []
            elif out is None:
                messages = ["[ERR] run_scraping ha restituito None"]
            else:
                messages = [f"[ERR] run_scraping tipo inatteso: {type(out).__name__}"]

        except Exception as e:
            messages = [f"[ERR] {e}"]
   
        
            # Messaggi utente: mostra solo eventuali errori
        for msg in messages:
            if "ERR" in msg or "Errore" in msg:
                flash(msg, "error")

        # -------- Normalizzazione output & costruzione link --------
        def _file_url(path):
            if not path:
                return None
            fname = os.path.basename(path)
            full = os.path.join(RESULTS_DIR, fname)
            if os.path.isfile(path):
                return url_for("download_file", filename=os.path.basename(path))
            if os.path.isfile(full):
                return url_for("download_file", filename=fname)
            return None

        download_links = []
        realtor_ready = False
        realtor_url = None
        zillow_ready = False
        zillow_url = None

        # Caso 1: dict {"realtor": "...", "zillow": "..."}
        if isinstance(outpaths, dict):
            for k, v in outpaths.items():
                url = _file_url(v)
                if url:
                    download_links.append(url)
                    key = (k or "").lower()
                    if "realtor" in key:
                        realtor_ready, realtor_url = True, url
                    if "zillow" in key:
                        zillow_ready, zillow_url = True, url

        # Caso 2: lista/tupla di path
        elif isinstance(outpaths, (list, tuple)):
            for v in outpaths:
                url = _file_url(v)
                if url:
                    download_links.append(url)
                    low = os.path.basename(str(v)).lower()
                    if "realtor" in low and not realtor_ready:
                        realtor_ready, realtor_url = True, url
                    if "zillow" in low and not zillow_ready:
                        zillow_ready, zillow_url = True, url

        # Caso 3: singolo string path
        elif isinstance(outpaths, str):
            url = _file_url(outpaths)
            if url:
                download_links.append(url)
                low = os.path.basename(outpaths).lower()
                if "realtor" in low:
                    realtor_ready, realtor_url = True, url
                elif "zillow" in low:
                    zillow_ready, zillow_url = True, url

        if not download_links:
            flash("Nessun file generato. Controlla i log.", "error")

        return render_template(
            "index.html",
            states_full=STATES_FULL,
            counties_json=json.dumps(COUNTIES_BY_STATE, ensure_ascii=False),
            message="Scraping completato.",
            download_links=download_links,  # lista multipla (compatibilità)
            download_link=None,
            # nuovi flag/URL per mostrare i link sulla stessa riga dei messaggi per-fonte
            realtor_ready=realtor_ready,
            realtor_url=realtor_url,
            zillow_ready=zillow_ready,
            zillow_url=zillow_url,
            done=True
        )

    except Exception as e:
        flash(f"Errore durante lo scraping: {e}", "error")
        return redirect(url_for("index"))

# -------------------------------------------------
# DOWNLOAD FILE
# -------------------------------------------------
@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(RESULTS_DIR, filename, as_attachment=True)

# -------------------------------------------------
# MAIN
# -------------------------------------------------
if __name__ == "__main__":
    # 0.0.0.0 + PORT per compatibilità con hosting/Render; in locale va bene uguale
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
