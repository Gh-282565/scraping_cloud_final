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
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        return uc, ChromeOptions
    except Exception as e:
        print("[IMPORT][UC][ERR]", e, flush=True)
        raise    

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
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Toggle immagini: default OFF come nel cloud-test. Metti REALTOR_IMAGES=1 su Render per abilitarle.
    imgs_on = (os.getenv("REALTOR_IMAGES", "0") == "1")
    prefs = {
        "profile.managed_default_content_settings.images": (1 if imgs_on else 2),
        "profile.default_content_setting_values": {"images": (1 if imgs_on else 2)},
    }
    opts.add_experimental_option("prefs", prefs)
    if not imgs_on:
        opts.add_argument("--blink-settings=imagesEnabled=false")

    # User data dir dedicata (persistenza anti-bot soft)
    profile_dir = os.path.join(os.getcwd(), "uc_profile_realtor")
    os.makedirs(profile_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile_dir}")

    driver = uc.Chrome(options=opts)
    return driver


def _progressive_scroll(driver, steps=8, pause=0.7):
    """
    Scrolla sia la finestra principale sia, se presente,
    il contenitore dei risultati (virtual list).
    """
    for _ in range(steps):
        try:
            driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight*0.85));")
        except Exception:
            pass
        # Scroll anche del container interno (virtual-list)
        _scroll_results_container(driver, steps=1, pause=0.0)
        time.sleep(pause)


def _scroll_results_container(driver, steps=6, pause=0.6):
    """
    Scrolla anche il contenitore risultati (virtual list) se presente,
    altrimenti lo scroll di window non materializza le card.
    """
    js = """
    (function(){
      const sels = [
        "div[data-testid='search-result-list']",
        "ul[data-testid='results-list']",
        "div[data-testid='results']",
        "main ul[data-testid='results-list']"
      ];
      let hit = 0;
      for (const s of sels) {
        const el = document.querySelector(s);
        if (el && el.scrollHeight > el.clientHeight) {
          el.scrollTop = el.scrollTop + Math.floor(el.clientHeight*0.9);
          el.dispatchEvent(new Event('scroll'));
          hit++;
        }
      }
      window.dispatchEvent(new Event('scroll'));
      window.dispatchEvent(new Event('resize'));
      return hit;
    })();
    """
    for _ in range(steps):
        try:
            driver.execute_script(js)
        except Exception:
            pass
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

def _wait_for_results(driver, timeout=40):
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
        "ul[data-testid='results-list']",
        "div[data-testid='search-result-list']",
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
    return m.group(0) if m else ""

def _parse_acres_from_text(text):
    # Prova a leggere "x.xx acres" oppure calcola da sqft
    import re
    if not text:
        return ""
    t = text.lower()
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*acres?", t)
    if m:
        return m.group(1)
    m2 = re.search(r"([0-9,]+)\s*(sq\.?\s*ft|sqft|square\s*feet)", t)
    if m2:
        sqft = int(m2.group(1).replace(",", ""))
        acres = sqft / 43560.0
        return f"{acres:.2f}"
    return ""

def _extract_listings(driver):
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

    cards = []
    for s in SELECTORS:
        els = driver.find_elements(By.CSS_SELECTOR, s)
        if els:
            cards.extend(els)

    # deduplica
    cards = list(dict.fromkeys(cards))
    log(f"[PARSE] Card trovate (unione selettori): {len(cards)}")

    # ⬇️ qui continua normalmente il tuo codice di parsing
    # ad esempio:
    # results = []
    # for card in cards:
    #     ... estrai titolo, prezzo, link ecc. ...
    # return results

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
        # Ultimo fallback: ancora anchor grezzi
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/realestateandhomes-detail/']")
        for a in anchors:
            try:
                link = a.get_attribute("href") or ""
                parent = a.find_element(By.XPATH, "./ancestor::*[position()<=3]")
                block = parent.text
                price = _first_price(block)
                acres = _parse_acres_from_text(block)
                listings.append({"title": a.text.strip(), "price": price, "acres": acres, "link": link, "status": ""})
            except Exception:
                pass
        return listings

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
                        price = cand[0].text.strip()
                        break
                except Exception:
                    pass

            # acres
            acres_text = ""
            try:
                lot_els = el.find_elements(By.XPATH, ".//*[contains(translate(text(),'ACRES','acres'),'acres') or contains(translate(text(),'LOT','lot'),'lot')]")
                if lot_els:
                    acres_text = lot_els[0].text.strip()
            except Exception:
                pass
            acres = _parse_acres_from_text(acres_text)

            # link
            link = ""
            for sel in [("css","a[data-testid='card-link']"), ("css","a[data-testid*='property-card']"),
                        ("css","a[href*='/realestateandhomes-detail/']"), ("xpath",".//a[contains(@href,'/realestateandhomes-detail/')]")]:
                try:
                    if sel[0] == "css":
                        cand = el.find_elements(By.CSS_SELECTOR, sel[1])
                    else:
                        cand = el.find_elements(By.XPATH, sel[1])
                    if cand:
                        link = cand[0].get_attribute("href") or ""
                        break
                except Exception:
                    pass

            status_text = ""
            try:
                st_els = el.find_elements(By.CSS_SELECTOR, "[data-testid*='status'], span[class*='status'], div[class*='status']")
                if st_els:
                    status_text = st_els[0].text.strip()
            except Exception:
                pass

            if not (price or acres or link):
                continue

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
        acres_min, acres_max = 0, 0
    sqft_min = int(round(acres_min * 43560))
    sqft_max = int(round(acres_max * 43560))
    county_slug = county_name.strip().lower().replace(" ", "-")
    base = f"https://www.realtor.com/realestateandhomes-search/{county_slug}-county_{state_abbr}/type-land/lot-sqft-{sqft_min}-{sqft_max}"
    if sold:
        base += "/sold"
    return base

def save_excel(records: List[Dict[str,Any]], path: str):
    import pandas as pd
    from openpyxl.utils import get_column_letter

    if not records:
        # crea xlsx vuoto con intestazioni
        df = pd.DataFrame(columns=["title","price","acres","link","status"])
    else:
        df = pd.DataFrame(records)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="ForSale")
        ws = writer.sheets["ForSale"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for idx, _ in enumerate(df.columns, start=1):
            ws.column_dimensions[get_column_letter(idx)].width = 19

@dataclass
class RealtorParams:
    state: str
    county: str
    acres_min: float
    acres_max: float
    sold: bool = False

def scrape_realtor(params: RealtorParams) -> List[Dict[str,Any]]:
    driver = None
    try:
        if USE_FAST_UC:
            log("[DRIVER] FAST UC attivo (ambiente test).")
            driver = _build_fast_uc_driver()
        else:
            log("[DRIVER] Driver condiviso (driver_factory).")
            get_driver = _import_driver_factory()
            driver = get_driver()

        url = _url_for(params.state, params.county, params.acres_min, params.acres_max, sold=params.sold)
        log("[URL]", url)

        driver.get(url)
        import time
        time.sleep(2)  # piccolo buffer post-navigazione

        # diagnosi post-navigazione
        try:
            _snapshot(driver, "after_get")
        except Exception:
            pass

        # cookie consent (USARE la funzione rimasta in alto, iframe-aware)
        clicked = _click_cookie_consent(driver)
        log(f"[CONSENT] clicked={clicked}")
        try:
            _snapshot(driver, "after_consent")
        except Exception:
            pass

        # attendi comparsa risultati; se nulla, scroll profondo e riattendi
        if not _wait_for_results(driver, timeout=40):
            _progressive_scroll(driver, steps=10, pause=0.6)
            if not _wait_for_results(driver, timeout=40):
                _snapshot(driver, "zero_results")
                return []
                
        # ⚠️ satura la virtual-list PRIMA del parsing
        _deep_fill_results(driver, cycles=6)
        
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
            _snapshot(driver, "after_scroll_diag")
        except Exception:
            pass

        data = _extract_listings(driver)
        log(f"[RESULT] Trovate {len(data)} card.")
        return data
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    # CLI: python today_realtor_scrape_PATCH_FAST.py GA Appling 0 5 forsale
    if len(sys.argv) >= 6:
        state = sys.argv[1]
        county = sys.argv[2]
        min_ac = sys.argv[3]
        max_ac = sys.argv[4]
        mode = sys.argv[5].lower()
        sold = (mode == "sold")
        recs = scrape_realtor(RealtorParams(state=state, county=county, acres_min=min_ac, acres_max=max_ac, sold=sold))
        out = os.path.join(RESULTS_DIR, "realtor_results.xlsx")
        save_excel(recs, out)
        print(f"[OK] Salvato: {out}")
    else:
        print("Uso: python today_realtor_scrape_PATCH_FAST.py <STATE> <County Name> <min acres> <max acres> <forsale|sold>")
# --- WRAPPER per orchestratore GUI: espone run_scrape() come da contratto ---

import re
import pandas as pd

def _num(x):
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(x)))
    except Exception:
        return None

def _to_df(listings, *, state, county, status_label, period):
    """
    listings: lista di dict come {"title","price","acres","link","status"}
    Ritorna DF con colonne standard attese dalla GUI:
    Price, Acres, Price_per_Acre, Location, Link, Status, County, State, Period
    """
    rows = []
    for r in listings:
        price_txt = r.get("price")
        acres_txt = r.get("acres")
        link = r.get("link")
        loc = r.get("title") or r.get("location") or ""
        price_num = _num(price_txt)
        acres_num = _num(acres_txt)
        ppa = (price_num / acres_num) if (price_num and acres_num and acres_num > 0) else None
        # format prezzo in USD se numerico
        price_fmt = f"${price_num:,.0f}" if price_num is not None else (price_txt or "")
        rows.append({
            "Price": price_fmt,
            "Acres": acres_num,
            "Price_per_Acre": ppa,
            "Location": loc,
            "Link": link,
            "Status": status_label,
            "County": county,
            "State": state,
            "Period": period or ""
        })
    return pd.DataFrame(rows, columns=[
        "Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"
    ])

def run_scrape(
    *,
    state: str,
    county: str,
    acres_min: int,
    acres_max: int,
    include_forsale: bool,
    include_sold: bool,
    headless: bool = True,   # ignorato: il driver interno è già headless/new
    period: str | None = None,
) -> pd.DataFrame:
    """
    Entry-point richiesto dalla GUI.
    Chiama lo scraper interno 'scrape_realtor' una o due volte e unisce i risultati in un unico DataFrame.
    """
    print("[REALTOR][VER] run_scrape wrapper attivo", flush=True)
    # Snapshot iniziale per confermare l'avvio del wrapper (diagnostica)
    try:
        from datetime import datetime
        snap_test = f"/app/results/snapshots/realtor_start_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        os.makedirs("/app/results/snapshots", exist_ok=True)
        with open(snap_test, "w", encoding="utf-8") as f:
            f.write("run_scrape avviato\n")
        print(f"[SNAP] Created {snap_test}", flush=True)
    except Exception as e:
        print("[SNAP][ERR] Impossibile creare snapshot iniziale:", e, flush=True)

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
