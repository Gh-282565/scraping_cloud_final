# -*- coding: utf-8 -*-
"""
Realtor scraper v4.1 — Single session + FAST MODE + fix SOLD
- Una sola istanza di UC/Chrome per più URL (ForSale/Sold)
- page_load_strategy="eager", immagini disabilitate, attese compatte
- Correzione SOLD: attesa leggermente più robusta + almeno 1 scroll prima del parsing
- Log espliciti: [DRIVER] created / quit, [NAV]/[DONE]
"""
import os
import re
import gc
import time
from datetime import datetime

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _log(*a):
    print(*a, flush=True)

# ---- timing "compatti" (puoi ridurre/aumentare se necessario)
PAGE_WAIT_S   = 15   # attesa caricamento body
CARD_WAIT_S   = 10   # attesa prima presenza card
SCROLL_PAUSE  = 0.8  # pausa tra scroll

# -------------------- numerics/parsing --------------------
def _num(txt):
    if txt is None: return None
    s = re.sub(r"[^0-9.\-]", "", str(txt))
    try: return float(s) if s else None
    except: return None

def _parse_acres_from_text(txt):
    if not txt: return None
    m = re.search(r"([\d.,]+)\s*acre", txt.lower())
    if not m: return None
    try: return float(m.group(1).replace(",", "."))
    except: return None

def _sold_on_date(txt):
    if not txt: return None
    m = re.search(r"sold\s+on\s+(\d{1,2}/\d{1,2}/\d{2,4})", txt.lower())
    if not m: return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try: return datetime.strptime(m.group(1), fmt).date()
        except: pass
    return None

# -------------------- UI helpers --------------------
def _try_click_any(driver, xpaths):
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xp)))
            el.click(); time.sleep(0.3)
            return True
        except Exception:
            continue
    return False

def _collect_cards(driver):
    cards = driver.find_elements(By.XPATH, "//li[contains(@class,'component_property-card')]")
    if not cards:
        cards = driver.find_elements(By.XPATH, "//div[contains(@data-testid,'property-card')]")
    if not cards:
        cards = driver.find_elements(By.XPATH, "//li[.//a[contains(@href,'/realestateandhomes-detail/')]]")
    if not cards:
        cards = driver.find_elements(By.XPATH, "//a[contains(@href,'/realestateandhomes-detail/')]//ancestor::li")
    if not cards:
        cards = driver.find_elements(By.XPATH, "//a[contains(@href,'/realestateandhomes-detail/')]")
    return cards

# -------------------- Driver factory (FAST MODE) --------------------
def _make_local_uc_driver():
    opts = uc.ChromeOptions()
    # FAST MODE
    opts.page_load_strategy = "eager"
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,1800")
    opts.add_argument("--password-store=basic")
    # Disabilita immagini / notifiche
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.notifications": 2,
    }
    opts.add_experimental_option("prefs", prefs)
    opts.add_argument("--blink-settings=imagesEnabled=false")

    udd = os.path.join(BASE_DIR, "uc_profile_realtor")
    os.makedirs(udd, exist_ok=True)
    opts.add_argument(f"--user-data-dir={udd}")

    # evita errori allo shutdown su alcune macchine
    try: uc.Chrome.__del__ = lambda self: None
    except Exception: pass

    drv = uc.Chrome(options=opts)
    _log("[DRIVER] created (FAST MODE)")
    return drv

def _get_uc_driver():
    # se hai un uc_bootstrap.get_uc_driver() lo puoi usare qui
    try:
        from uc_bootstrap import get_uc_driver
        drv = get_uc_driver()
        _log("[DRIVER] created via uc_bootstrap")
        return drv
    except Exception:
        return _make_local_uc_driver()

# -------------------- Attese + parsing --------------------
def wait_results_page_ready(driver, scroll_steps=2, scroll_pause=SCROLL_PAUSE, status_label="ForSale"):
    """
    Attende il caricamento minimo della pagina risultati.
    Per SOLD:
      - non facciamo early-exit
      - garantiamo almeno 1 scroll (spesso le card SOLD compaiono dopo il primo scroll)
      - concediamo una breve attesa extra sulle card
    """
    # body
    try:
        WebDriverWait(driver, PAGE_WAIT_S).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        time.sleep(0.5)

    # cookie / privacy (best-effort)
    _try_click_any(driver, [
        "//button[contains(., 'Accept')]", "//button[contains(., 'I agree')]",
        "//button[contains(., 'Accept All')]", "//button[contains(., 'Agree')]",
    ])

    # SOLD: card possono apparire dopo primo scroll → attesa + scroll minimo
    extra_wait = 3 if str(status_label).lower() == "sold" else 0

    # Attendo card (o comunque qualche contenuto) per poco
    try:
        WebDriverWait(driver, CARD_WAIT_S + extra_wait).until(
            lambda d: _collect_cards(d) or d.find_elements(By.XPATH, "//*[contains(text(),'results') or contains(text(),'Results')]")
        )
    except TimeoutException:
        pass

    # Calcolo scroll steps: per SOLD almeno 1
    steps = max(1, scroll_steps) if str(status_label).lower() == "sold" else scroll_steps

    # scroll progressivo per lazy load
    try:
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(steps):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
    except Exception:
        pass

def extract_listings(driver, status_label="ForSale"):
    cards = _collect_cards(driver)
    rows = []
    for c in cards:
        try:
            # link
            link = None
            try:
                a = c.find_element(By.XPATH, ".//a[contains(@href,'/realestateandhomes-detail/')]")
                link = a.get_attribute("href")
            except Exception:
                try:
                    a = c.find_element(By.XPATH, ".//a[@href]")
                    href = a.get_attribute("href") or ""
                    if "/realestateandhomes-detail/" in href:
                        link = href
                except Exception:
                    pass

            # testo card
            t = c.text

            # prezzo
            m_price = re.search(r"\$\s?[\d,\.]+", t)
            price_num = _num(m_price.group(0)) if m_price else None

            # acres
            acres = _parse_acres_from_text(t)

            # location
            location = None
            for line in [x.strip() for x in t.splitlines() if x.strip()]:
                if re.search(r",[ ]*[A-Z]{2}[ ]*\d{5}", line):
                    location = line; break

            # sold date (solo se SOLD)
            sold_dt = _sold_on_date(t) if str(status_label).lower() == "sold" else None

            # price-per-acre
            ppa = (price_num / acres) if (price_num and acres and acres > 0) else None

            # scarta card con nessun prezzo e nessun acres
            if not price_num and not acres:
                continue

            rows.append({
                "Price_num": price_num,
                "Acres": acres,
                "Price_per_Acre": ppa,
                "Location": location,
                "Link": link,
                "SoldDate": sold_dt
            })
        except Exception:
            continue
    return rows

# -------------------- API: single-driver --------------------
def scrape_with_single_driver(urls):
    """
    urls = [("ForSale", url1), ("Sold", url2)]
    return {"ForSale": [...], "Sold": [...]}
    """
    driver = None
    try:
        driver = _get_uc_driver()
        results = {}
        for tag, url in urls:
            _log("[NAV]", tag, url)
            driver.get(url)
            wait_results_page_ready(driver, status_label=tag)
            rows = extract_listings(driver, status_label=tag)
            results[tag] = rows
            _log("[DONE]", tag, "rows:", len(rows))
        return results
    finally:
        try:
            if driver:
                driver.quit()
                _log("[DRIVER] quit")
        except Exception:
            pass
        driver = None
        gc.collect()

# -------------------- Retro-compat: single-URL --------------------
def scrape(url, status_label="ForSale", period_hint=None):
    driver = None
    try:
        driver = _get_uc_driver()
        _log("[DRIVER] created (single-url)")
        driver.get(url)
        wait_results_page_ready(driver, status_label=status_label)
        return extract_listings(driver, status_label=status_label)
    finally:
        try:
            if driver:
                driver.quit()
                _log("[DRIVER] quit")
        except Exception:
            pass
        driver = None
        gc.collect()

# --- ENTRY-POINT per orchestratore (Flask) ---
import pandas as _pd

def _build_realtor_urls(*, state: str, county: str, acres_min: int, acres_max: int,
                        include_forsale: bool, include_sold: bool, period: str | None):
    st = (state or "").strip().lower()
    ct = (county or "").strip().lower().replace(" ", "-")
    urls = []
    if include_forsale:
        urls.append((
            "ForSale",
            f"https://www.realtor.com/realestateandhomes-search/{ct}_county_{st}/type-land/"
            f"?acres_min={(acres_min or '')}&acres_max={(acres_max or '')}"
        ))
    if include_sold:
        urls.append((
            "Sold",
            f"https://www.realtor.com/soldhomeprices/{ct}_county_{st}/type-land/"
            f"?acres_min={(acres_min or '')}&acres_max={(acres_max or '')}"
        ))
    return urls

def run_scrape(*, state: str, county: str, acres_min: int, acres_max: int,
               include_forsale: bool, include_sold: bool,
               headless: bool = True, period: str | None = None):
    # Costruisci le URL richieste dal form
    urls = _build_realtor_urls(
        state=state, county=county, acres_min=acres_min, acres_max=acres_max,
        include_forsale=include_forsale, include_sold=include_sold, period=period
    )
    if not urls:
        return _pd.DataFrame([{
            "Title": f"Realtor {county}, {state}", "Price": 0, "Acres": 0,
            "Link": "", "Status": "N/A", "County": county, "State": state, "Period": period or ""
        }])

    # Esegue con il driver già pronto
    data = scrape_with_single_driver(urls)
    rows = []
    for tag, recs in data.items():
        for r in recs:
            rows.append({
                "Title": f"Realtor {tag} {county}, {state}",
                "Price": r.get("Price_num"),
                "Acres": r.get("Acres"),
                "Link": r.get("Link"),
                "Status": "Sold" if tag.lower() == "sold" else "For Sale",
                "County": county,
                "State": state,
                "Period": period or "",
                "SoldDate": r.get("SoldDate"),
                "Price_per_Acre": r.get("Price_per_Acre"),
                "Location": r.get("Location"),
            })
    return _pd.DataFrame(rows)

# opzionale alias
def run(**kwargs):
    return run_scrape(**kwargs)
