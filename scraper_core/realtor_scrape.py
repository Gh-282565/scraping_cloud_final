# scraper_core/realtor_scrape.py

import os
import re
import time
import math
import traceback
from datetime import datetime
from urllib.parse import quote

from .driver_factory import make_driver  # <-- stesso factory usato per Zillow
from .excel_utils import save_realtor_results  # <-- se già usi un writer centralizzato; vedi nota in fondo

ACRE_TO_SQFT = 43560

def acres_to_sqft_range(min_acres: float, max_acres: float):
    def _safe(x):
        try:
            return max(0, float(x))
        except:
            return 0.0
    a_min = _safe(min_acres)
    a_max = _safe(max_acres)
    # Realtor accetta interi
    s_min = int(round(a_min * ACRE_TO_SQFT))
    s_max = int(round(a_max * ACRE_TO_SQFT)) if a_max > 0 else 0
    return s_min, s_max

def normalize_county(county: str):
    """
    'Appling' -> 'Appling-County'
    Evita doppio 'County' se già presente.
    """
    c = (county or "").strip()
    if not c:
        return c
    if re.search(r'county$', c, flags=re.I):
        return re.sub(r'\s+', '-', c.strip().title())
    return re.sub(r'\s+', '-', f"{c.strip().title()}-County")

def state_upper(state_abbr: str):
    return (state_abbr or "").strip().upper()

def build_realtor_urls(state_abbr: str, county: str, min_acres: float, max_acres: float,
                       include_for_sale: bool = True, include_sold: bool = False,
                       property_type: str = "type-land"):
    """
    Ritorna una lista di URL da interrogare.
    Pattern robusto (valido al momento):
      For Sale: /realestateandhomes-search/{County-County}_{STATE}/{property_type}/lot-sqft-{min}-{max}
      Sold:     stesso ma con suffisso '/sold'
    Nota: se hai bisogno di filtri aggiuntivi, appendi querystring.
    """
    s = state_upper(state_abbr)
    c = normalize_county(county)
    sqft_min, sqft_max = acres_to_sqft_range(min_acres, max_acres)
    acres_part = f"lot-sqft-{sqft_min}-{sqft_max}" if sqft_max > 0 else f"lot-sqft-{sqft_min}-"
    base = f"https://www.realtor.com/realestateandhomes-search/{quote(c)}_{quote(s)}"
    urls = []
    if property_type and property_type.strip():
        base = f"{base}/{property_type.strip()}"
    base = f"{base}/{acres_part}"

    if include_for_sale:
        urls.append((base, "for_sale"))
    if include_sold:
        # Sold come path di coda
        urls.append((base.rstrip('/') + "/sold", "sold"))
    return urls

def _click_cookie_consent(driver, log):
    # Prova più selettori/label perché Realtor cambia spesso
    candidates = [
        "button#onetrust-accept-btn-handler",
        "button[aria-label='Accept']",
        "button[aria-label='Accept All']",
        "button[aria-label='Accept all']",
        "button[aria-label='Agree']",
        "button:contains('Accept')",  # pseudo, ma alcune librerie lo gestiscono; UC no -> skip silenzioso
        "button[data-testid='trust-accept']",
    ]
    for css in candidates:
        try:
            btns = driver.find_elements("css selector", css)
            if btns:
                btns[0].click()
                log(f"[CONSENT] Click su {css}")
                time.sleep(0.5)
                return True
        except Exception:
            pass
    # Alcuni overlay hanno un “X”
    try:
        xs = driver.find_elements("css selector", "button[aria-label='Close'], button[aria-label='Dismiss']")
        if xs:
            xs[0].click()
            log("[CONSENT] Chiuso overlay con Close/Dismiss")
            time.sleep(0.3)
            return True
    except Exception:
        pass
    return False

def _progressive_scroll(driver, steps=6, pause=0.8):
    # scroll a scatti per popolare listing lazy
    for i in range(steps):
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight * 0.6);")
        time.sleep(pause)

def _wait_for_results(driver, timeout=15):
    """
    Attende che compaiano card risultati o un contatore.
    """
    start = time.time()
    while time.time() - start < timeout:
        # card possibili
        cards = driver.find_elements("css selector", 
            "[data-testid='component-property-card'], [data-testid='property-card'], article[data-testid*='card']")
        if cards and len(cards) > 0:
            return True
        # contatore risultati (a volte in header)
        counts = driver.find_elements("css selector", "[data-testid='search-result-count'], span[class*='results']")
        if counts:
            return True
        time.sleep(0.5)
    return False

def _extract_listings(driver, log):
    listings = []

    # Primo tentativo: card strutturate
    cards = driver.find_elements("css selector", 
        "[data-testid='component-property-card'], [data-testid='property-card'], article[data-testid*='card']")
    if not cards:
        log("[PARSE] Nessuna card standard trovata, provo fallback su anchor")
    else:
        for el in cards:
            try:
                title_el = None
                # titolo / headline
                for sel in ["[data-testid='card-title']", "h3", "h2"]:
                    cand = el.find_elements("css selector", sel)
                    if cand:
                        title_el = cand[0]
                        break

                price_el = None
                for sel in ["[data-testid='card-price']", "span[data-label='pc-price']",
                            "span[data-testid*='price']", "span[class*='price']"]:
                    cand = el.find_elements("css selector", sel)
                    if cand:
                        price_el = cand[0]
                        break

                acres_text = ""
                # spesso è “Lot size” o “XX acres”
                lot_els = el.find_elements("xpath", ".//*[contains(translate(text(),'ACRES','acres'),'acres') or contains(translate(text(),'LOT','lot'),'lot')]")
                if lot_els:
                    acres_text = lot_els[0].text.strip()

                link_el = None
                for sel in ["a[data-testid='card-link']", "a[data-testid*='property-card']", "a[href*='/realestateandhomes-detail/']"]:
                    cand = el.find_elements("css selector", sel)
                    if cand:
                        link_el = cand[0]
                        break

                status_text = ""
                st_els = el.find_elements("css selector", "[data-testid*='status'], span[class*='status'], div[class*='status']")
                if st_els:
                    status_text = st_els[0].text.strip()

                title = title_el.text.strip() if title_el else ""
                price = price_el.text.strip() if price_el else ""
                link = link_el.get_attribute("href") if link_el else ""

                # acres parse grezzo (es. "2.3 acres" o "Lot size: 1.1 acres")
                acres = _parse_acres_from_text(acres_text)

                if link:
                    listings.append({
                        "title": title,
                        "price": price,
                        "acres": acres,
                        "link": link,
                        "status": status_text
                    })
            except Exception as e:
                log(f"[PARSE][CARD][ERR] {e}")

    # Fallback: anchor generici
    if not listings:
        anchors = driver.find_elements("css selector", "a[href*='/realestateandhomes-detail/']")
        for a in anchors:
            try:
                link = a.get_attribute("href") or ""
                txt = a.text.strip()
                # Heuristic: prendi vicino prezzo/lot info
                price = ""
                acres = None
                # prova a salire di un parent per leggere testo aggregato
                parent = a.find_element("xpath", "./ancestor::*[position()<=3]")
                block = parent.text
                price = _first_price(block)
                acres = _parse_acres_from_text(block)
                listings.append({
                    "title": txt,
                    "price": price,
                    "acres": acres,
                    "link": link,
                    "status": ""
                })
            except Exception:
                pass

    return listings

def _first_price(text: str):
    # Estrazione semplice: $123,456 o 123,456 USD
    if not text:
        return ""
    m = re.search(r'(\$\s?\d[\d,\.]*)', text)
    return m.group(1) if m else ""

def _parse_acres_from_text(text: str):
    if not text:
        return None
    # cattura "1.23 acres" o "0.5 ac"
    m = re.search(r'([\d\.,]+)\s*ac(res)?\b', text, flags=re.I)
    if m:
        try:
            return float(m.group(1).replace(',', '.'))
        except:
            return None
    return None

def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def _snapshot(driver, tag="realtor"):
    try:
        base = "/app/results/snapshots"
        _ensure_dir(base)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(base, f"{tag}_{ts}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        return path
    except Exception:
        return None

def scrape_realtor(county: str, state_abbr: str,
                   min_acres: float, max_acres: float,
                   include_for_sale: bool = True, include_sold: bool = False,
                   property_type: str = "type-land",
                   logger=print):
    """
    Ritorna dict: { 'for_sale': [..], 'sold': [..] } con listing estratti.
    """
    def log(*args):
        logger(*args)

    urls = build_realtor_urls(state_abbr, county, min_acres, max_acres,
                              include_for_sale, include_sold, property_type)
    log(f"[REALTOR] URL generate: {urls}")

    results = {"for_sale": [], "sold": []}
    driver = None
    try:
        driver = make_driver()  # UC headless
        for url, bucket in urls:
            log(f"[REALTOR] GET {bucket}: {url}")
            driver.get(url)
            time.sleep(2)

            _click_cookie_consent(driver, log)
            if not _wait_for_results(driver, timeout=18):
                log("[WAIT] Nessun indicatore risultati ancora visibile, provo scroll")
            _progressive_scroll(driver, steps=8, pause=0.7)

            listings = _extract_listings(driver, log)
            log(f"[REALTOR] {bucket}: trovate {len(listings)} card")

            if len(listings) == 0:
                snap = _snapshot(driver, tag=f"{bucket}_0results")
                log(f"[SNAPSHOT] Zero risultati salvato in: {snap}")
            results[bucket] = listings

        return results
    except Exception as e:
        log(f"[REALTOR][ERR] {e}")
        log(traceback.format_exc())
        if driver:
            snap = _snapshot(driver, tag="exception")
            log(f"[SNAPSHOT] Eccezione: snapshot in {snap}")
        return results
    finally:
        try:
            if driver:
                driver.quit()
        except:
            pass
# ---- ADAPTER per compatibilità con scraper_core/scraper.py ----
# Mantiene la vecchia firma: run_scrape(...) -> list[dict] / DataFrame-friendly

import re

def _price_to_float(raw):
    if raw is None:
        return None
    s = str(raw)
    # rimuove $ , spazi ecc. mantenendo solo cifre e punto
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s) if s else None
    except:
        return None

def run_scrape(
    *,
    state: str,
    county: str,
    acres_min: float = 0,
    acres_max: float = 0,
    include_forsale: bool = True,
    include_sold: bool = False,
    headless: bool = True,
    period: str | None = None,
    logger=print,
    **kwargs
):
    """
    Adapter per lo scraper orchestrator.
    Ritorna una lista di record (ForSale+Sold) con colonne compatibili:
    State, County, Status, Price, Acres, Price_per_Acre, Link
    """
    res = scrape_realtor(
        county=county,
        state_abbr=state,
        min_acres=acres_min,
        max_acres=acres_max,
        include_for_sale=include_forsale,
        include_sold=include_sold,
        logger=logger
    )

    rows = []
    for bucket, items in (res or {}).items():
        status = "for sale" if bucket == "for_sale" else "sold"
        for it in items or []:
            price_num = _price_to_float(it.get("price"))
            acres = it.get("acres")
            ppa = (price_num / acres) if (price_num is not None and acres not in (None, 0, 0.0)) else None
            rows.append({
                "State": state,
                "County": county,
                "Status": status,
                "Price": price_num,          # numerico per i tuoi calcoli
                "Acres": acres,
                "Price_per_Acre": ppa,
                "Link": it.get("link", "")
            })
    return rows
