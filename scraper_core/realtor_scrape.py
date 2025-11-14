# today_realtor_scrape_PATCH_FAST.py
# Drop-in per testare Realtor con lo STESSO approccio driver dell'ambiente test (UC FAST MODE)
# Toggle via env: REALTOR_FAST=1 (default) => usa driver locale UC ottimizzato
#                   REALTOR_FAST=0         => delega a driver_factory.get_driver() (condiviso con Zillow)
# PATCH 1: robust consent click (iframe-aware)
def _click_cookie_consent(driver):
    try:
        driver.implicitly_wait(2)
        iframes = driver.find_elements("tag name", "iframe")
        for f in iframes:
            try:
                driver.switch_to.frame(f)
                btns = driver.find_elements("xpath", "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]")
                if btns:
                    btns[0].click()
                    driver.switch_to.default_content()
                    print("[CONSENT] Clicked inside iframe")
                    return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
        # fallback on main doc
        btns = driver.find_elements("xpath", "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]")
        if btns:
            btns[0].click()
            print("[CONSENT] Clicked on main doc")
            return True
    except Exception as e:
        print("[CONSENT] No banner or failed:", e)
    driver.switch_to.default_content()
    return False

def _force_unblock(driver):
    """Forza la rimozione/silenziamento di overlay o modal che possono coprire i risultati."""
    try:
        js = """(function(){
            const selectors = [
                'div[aria-modal="true"]',
                'div[role="dialog"]',
                'div[class*="modal"]',
                'div[class*="overlay"]',
                'section[class*="overlay"]'
            ];
            let removed = 0;
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    el.style.display = 'none';
                    el.style.visibility = 'hidden';
                    el.removeAttribute('aria-modal');
                    removed++;
                });
            });
            return removed;
        })();"""
        removed = driver.execute_script(js)
        log(f"[UNBLOCK] overlay rimossi={removed}")
    except Exception as e:
        log(f"[UNBLOCK][ERR] {e}")

# Funzioni chiave:
# - _build_fast_uc_driver(): riprende le ottimizzazioni del vecchio ambiente test (pageLoadStrategy=eager, immagini OFF, headless)
# - _wait_for_results(): attesa tollerante (CSS + XPATH legacy)
# - _extract_listings(): parser robusto con fallback multipli
# - _progressive_scroll(): scroll in 2 fasi (sblocco lazy-load)
#
# Uso rapido (standalone):
#   python today_realtor_scrape_PATCH_FAST.py GA Appling 0 5 forsale
# Genera: results/realtor_results.xlsx
#
# Integrazione con la tua app:
# - Temporaneamente importa e usa scrape_realtor() di questo file.
# - Oppure copia _build_fast_uc_driver / _wait_for_results / _extract_listings nel tuo today_realtor_scrape.py
#   e sostituisci la creazione driver con la logica REALTOR_FAST.

import os, time, math, sys, traceback
from dataclasses import dataclass
from typing import List, Dict, Any

# Toggle FAST vs shared driver
USE_FAST_UC = bool(int(os.getenv("REALTOR_FAST", "1")))

# Safe imports: UC è richiesto solo se USE_FAST_UC=True
def _import_uc():
    import undetected_chromedriver as uc
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    return uc, ChromeOptions

# Fallback al driver condiviso se richiesto
def _import_driver_factory():
    from scraper_core.driver_factory import get_driver  # deve esistere nella tua app
    return get_driver

# Helpers Selenium comuni
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException

RESULTS_DIR = os.path.join(os.getcwd(), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

def log(*a):
    print(*a, flush=True)

def _build_fast_uc_driver():
    uc, ChromeOptions = _import_uc()

    opts = ChromeOptions()
    # EAGER: parte a DOM interactive (non attende rete/immagini)
    opts.set_capability("pageLoadStrategy", "eager")
    # Headless "new"
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1440,1200")

    # Disabilita immagini
    prefs = {
        "profile.default_content_setting_values": {"images": 2},
        "profile.managed_default_content_settings.images": 2
    }
    opts.add_experimental_option("prefs", prefs)

    # User data dir dedicata (persistenza anti-bot soft)
    profile_dir = os.path.join(os.getcwd(), "uc_profile_realtor")
    os.makedirs(profile_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile_dir}")

    driver = uc.Chrome(options=opts)
    return driver

def _progressive_scroll(driver, steps=8, pause=0.7):
    for i in range(steps):
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight * 0.25);")
        time.sleep(pause)

# PATCH 2: extended wait and diagnostic snapshots
import os, time
from datetime import datetime

def _snapshot(driver, tag):
    try:
        os.makedirs("/app/results/snapshots", exist_ok=True)
        fn = f"/app/results/snapshots/realtor_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        with open(fn, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[SNAP] Saved {fn}")
    except Exception as e:
        print("[SNAP] Error saving snapshot:", e)


def _safe_get(driver, url, tries=2, pause=2.0):
    """Navigazione robusta con retry e snapshot after_get_t1/after_get_t2."""
    last_err = None
    for i in range(1, tries + 1):
        try:
            log(f"[GET] try={i} url={url}")
            driver.get(url)
            time.sleep(pause)
            try:
                _snapshot(driver, f"after_get_t{i}")
            except Exception:
                pass
            return True
        except WebDriverException as e:
            last_err = e
            log(f"[GET][ERR] try={i} -> {e}")
        except Exception as e:
            last_err = e
            log(f"[GET][ERR-UNK] try={i} -> {e}")
    log(f"[GET][FAIL] url={url} err={last_err}")
    return False

def _wait_for_results(driver, timeout=25):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    SELECTORS = [
        "article[data-testid='property-card']",
        "section[data-testid='property-card']",
        "div[data-testid='property-card']",
        "li[data-testid='result-card'] article",
        "ul[data-testid='results-list'] article",
        "div[data-testid='search-result-list'] article",
        "div[class^='BasePropertyCard_propertyCardWrap__'] article",
    ]
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: any(d.find_elements(By.CSS_SELECTOR, s) for s in SELECTORS)
        )
        return True
    except Exception:
        return False

def _first_price(text):
    # Estrai token $xxx,xxx
    import re
    m = re.search(r"\$[\d,]+", text or "")
    if not m:
        return ""
    return m.group(0)

def _parse_acres_from_text(text):
    if not text:
        return None
    t = text.lower()
    import re
    m = re.search(r"([\d.,]+)\s*acres?", t)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except Exception:
            return None
    # Try sqft
    m = re.search(r"([\d.,]+)\s*(square feet|sqft|sq\.ft)", t)
    if m:
        try:
            sqft = float(m.group(1).replace(",", ""))
            return sqft / 43560.0
        except Exception:
            return None
    return None

def _extract_listings(driver):
    """
    Parser robusto delle card risultati.
    Ritorna: List[Dict] con chiavi: title, price (str), acres (float), link (str), status (str)
    """
    listings = []

    # Primo tentativo: CSS moderni
    cards = driver.find_elements(By.CSS_SELECTOR,
        "[data-testid='component-property-card'], [data-testid='property-card'], article[data-testid*='card']")

    # Fallback XPATH legacy
    if not cards:
        xp_candidates = [
            "//li[contains(@class,'component_property-card')]",
            "//div[contains(@data-testid,'property-card')]",
            "//li[.//a[contains(@href,'/realestateandhomes-detail/')]]",
            "//a[contains(@href,'/realestateandhomes-detail/')]//ancestor::li",
            "//a[contains(@href,'/realestateandhomes-detail/')]"
        ]
        for xp in xp_candidates:
            try:
                els = driver.find_elements(By.XPATH, xp)
                if els:
                    cards = els
                    break
            except Exception:
                pass

    if not cards:
        log("[RESULT] Nessuna card trovata anche dopo i fallback.")
        return []

    for el in cards:
        try:
            # titolo
            title = ""
            for sel in [("css","[data-testid='card-title']"), ("css","h3"), ("css","h2"), ("xpath",".//h3|.//h2")]:
                try:
                    if sel[0] == "css":
                        cand = el.find_elements(By.CSS_SELECTOR, sel[1])
                    else:
                        cand = el.find_elements(By.XPATH, sel[1])
                    if cand:
                        title = cand[0].text.strip()
                        break
                except Exception:
                    pass

            # prezzo
            price = ""
            for sel in [("css","[data-testid='card-price']"), ("css","span[data-label='pc-price']"),
                        ("css","span[data-testid*='price']"), ("css","span[class*='price']"),
                        ("xpath",".//*[contains(text(),'$')]")]:
                try:
                    if sel[0] == "css":
                        cand = el.find_elements(By.CSS_SELECTOR, sel[1])
                    else:
                        cand = el.find_elements(By.XPATH, sel[1])
                    if cand:
                        price = _first_price(cand[0].text)
                        if price:
                            break
                except Exception:
                    pass

            # acres
            acres = None
            try:
                info_text = el.text
                acres = _parse_acres_from_text(info_text)
            except Exception:
                pass

            # link
            link = ""
            try:
                a = el.find_element(By.CSS_SELECTOR, "a[href*='/realestateandhomes-detail/']")
                link = a.get_attribute("href")
            except Exception:
                try:
                    a = el.find_element(By.XPATH, ".//a[contains(@href,'/realestateandhomes-detail/')]")
                    link = a.get_attribute("href")
                except Exception:
                    pass

            # status (For Sale / Sold) spesso NON è esplicito sulla card => lo gestiamo a livello chiamante
            status_text = ""

            listings.append({
                "title": title,
                "price": price,
                "acres": acres,
                "link": link,
                "status": status_text
            })
        except Exception as e:
            log(f"[PARSE][CARD][ERR] {e}")

    return listings

def _url_for(state_abbr, county_name, acres_min, acres_max, sold=False):
    # Realtor usa sqft nel path: acres -> sqft
    # 1 acro = 43,560 sqft
    try:
        acres_min = float(acres_min)
        acres_max = float(acres_max)
    except Exception:
        acres_min = 0.0
        acres_max = 0.0

    sqft_min = int(acres_min * 43560)
    sqft_max = int(acres_max * 43560) if acres_max > 0 else 0

    county_slug = county_name.strip().lower().replace(" ", "-").replace("county", "").strip()
    state_abbr = state_abbr.strip().upper()

    base = f"https://www.realtor.com/realestateandhomes-search/{county_slug}-county_{state_abbr}/type-land"
    if sqft_max > 0:
        base += f"/lot-sqft-{sqft_min}-{sqft_max}"
    else:
        base += f"/lot-sqft-{sqft_min}-no-max"

    if sold:
        base += "?status=recently_sold"
    else:
        base += "?status=for_sale"

    return base

@dataclass
class RealtorParams:
    state: str
    county: str
    acres_min: float
    acres_max: float
    sold: bool = False

def scrape_realtor(params: RealtorParams) -> List[Dict[str, Any]]:
    """
    Esegue lo scraping Realtor per i parametri dati.
    Ritorna una lista di dict con almeno: title, price(str), acres(float), link(str), status(str)
    """
    log("[REALTOR][VER] run_scrape wrapper attivo")

    # Scegli driver
    if USE_FAST_UC:
        log("[DRIVER] FAST UC attivo (ambiente test).")
        driver = _build_fast_uc_driver()
    else:
        log("[DRIVER] Shared driver_factory.get_driver()")
        get_driver = _import_driver_factory()
        driver = get_driver(headless=True, for_realtor=True)

    try:
        url = _url_for(params.state, params.county, params.acres_min, params.acres_max, sold=params.sold)
        log("[URL]", url)

        if not _safe_get(driver, url, tries=2, pause=2.0):
            return []

        # cookie consent (USARE la funzione rimasta in alto, iframe-aware)
        clicked = _click_cookie_consent(driver)
        log(f"[CONSENT] clicked={clicked}")
        if not clicked:
            try:
                _force_unblock(driver)
                time.sleep(0.5)
            except Exception as e:
                log(f"[UNBLOCK][ERR] {e}")
        try:
            _snapshot(driver, "after_consent")
        except Exception:
            pass

        # attendi comparsa risultati; se nulla, scroll profondo e riattendi
        if not _wait_for_results(driver, timeout=25):
            _progressive_scroll(driver, steps=8, pause=0.7)
            if not _wait_for_results(driver, timeout=25):
                _snapshot(driver, "zero_results")
                return []

        # scroll profondo per far materializzare tutte le card lazy
        _progressive_scroll(driver, steps=8, pause=0.7)
        # --- DIAGNOSTICA SELETTORI CARD (prima del parsing) ---
        from selenium.webdriver.common.by import By
        SELECTORS = [
            "article[data-testid='property-card']",
            "section[data-testid='property-card']",
            "div[data-testid='property-card']",
            "li[data-testid='result-card'] article",
            "ul[data-testid='results-list'] article",
            "div[data-testid='search-result-list'] article",
            "div[class^='BasePropertyCard_propertyCardWrap__'] article",
  
        ]

        for s in SELECTORS:
            try:
                n = len(driver.find_elements(By.CSS_SELECTOR, s))
                log(f"[CHECK] {s} -> {n}")
            except Exception as e:
                log(f"[CHECK][ERR] {s} -> {e}")

        try:
            listings = _extract_listings(driver)
        except Exception as e:
            log("[RESULT] Errore in _extract_listings:", e)
            listings = []

        log(f"[RESULT] Trovate {len(listings)} card.")
        return listings

    finally:
        try:
            driver.quit()
        except Exception:
            pass

# ----------------- WRAPPER PER LA TUA PIPELINE ESISTENTE -----------------

import pandas as pd

def _to_df(records: List[Dict[str, Any]], state: str, county: str, status_label: str, period: str) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])
    rows = []
    for r in records:
        price_str = r.get("price") or ""
        p_clean = "".join(ch for ch in price_str if ch.isdigit() or ch == ".")
        price_val = float(p_clean) if p_clean else None

        acres = r.get("acres")
        if price_val is not None and acres not in (None, 0):
            ppa = price_val / acres
        else:
            ppa = None

        rows.append({
            "Price": price_val,
            "Acres": acres,
            "Price_per_Acre": ppa,
            "Location": r.get("title") or "",
            "Link": r.get("link") or "",
            "Status": status_label,
            "County": county,
            "State": state,
            "Period": period
        })
    return pd.DataFrame(rows)

def run_scrape(state: str, county: str, acres_min: float, acres_max: float,
               include_forsale: bool = True, include_sold: bool = False,
               period: str = "12M") -> pd.DataFrame:
    """
    Wrapper compatibile con il tuo scraper_core/scraper.py:
    - state, county, acres_min, acres_max, include_forsale, include_sold, period
    Ritorna un DataFrame già pronto da scrivere in Excel.
    """
    parts = []

    # For Sale
    if include_forsale:
        listings_fs = scrape_realtor(RealtorParams(
            state=state, county=county, acres_min=acres_min, acres_max=acres_max, sold=False
        ))
        parts.append(_to_df(listings_fs, state=state, county=county, status_label="For Sale", period=period))

    # Sold
    if include_sold:
        listings_sd = scrape_realtor(RealtorParams(
            state=state, county=county, acres_min=acres_min, acres_max=acres_max, sold=True
        ))
        parts.append(_to_df(listings_sd, state=state, county=county, status_label="Sold", period=period))

    if not parts:
        return pd.DataFrame(columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])

    return pd.concat(parts, ignore_index=True)
