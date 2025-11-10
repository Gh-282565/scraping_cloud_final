# today_realtor_scrape_PATCH_FAST.py
# Drop-in per testare Realtor con lo STESSO approccio driver dell'ambiente test (UC FAST MODE)
# Toggle via env: REALTOR_FAST=1 (default) => usa driver locale UC ottimizzato
#                   REALTOR_FAST=0         => delega a driver_factory.get_driver() (condiviso con Zillow)
#
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

def _click_cookie_consent(driver):
    # Tenta varianti comuni "Accept/Consent/Agree"
    texts = ["Accept", "I agree", "Consent", "Agree", "Accetta", "OK"]
    for t in texts:
        try:
            btns = driver.find_elements(By.XPATH, f"//button[normalize-space()='{t}']")
            if btns:
                btns[0].click()
                time.sleep(0.5)
                return True
        except Exception:
            pass
    # data-testid comuni
    for sel in [
        "[data-testid='accept-consent']",
        "button[aria-label*='accept']",
        "button[aria-label*='consent']",
    ]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                els[0].click()
                time.sleep(0.5)
                return True
        except Exception:
            pass
    return False

def _wait_for_results(driver, timeout=20):
    start = time.time()
    while time.time() - start < timeout:
        # CSS moderni
        cards = driver.find_elements(By.CSS_SELECTOR,
            "[data-testid='component-property-card'], [data-testid='property-card'], article[data-testid*='card']")
        if cards:
            return True

        # Contatori/indicatori
        counts = driver.find_elements(By.CSS_SELECTOR, "[data-testid='search-result-count'], span[class*='results']")
        if counts:
            return True

        # XPATH legacy (robusti)
        xp_any = [
            "//li[contains(@class,'component_property-card')]",
            "//div[contains(@data-testid,'property-card')]",
            "//li[.//a[contains(@href,'/realestateandhomes-detail/')]]",
            "//a[contains(@href,'/realestateandhomes-detail/')]//ancestor::li",
            "//a[contains(@href,'/realestateandhomes-detail/')]"
        ]
        for xp in xp_any:
            try:
                if driver.find_elements(By.XPATH, xp):
                    return True
            except Exception:
                pass

        time.sleep(0.5)
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
        time.sleep(2)
        _click_cookie_consent(driver)

        # Scroll corto, attesa, scroll profondo
        _progressive_scroll(driver, steps=2, pause=0.7)
        if not _wait_for_results(driver, timeout=20):
            log("[WAIT] Nessun indicatore risultati; continuo con scroll profondo.")
        _progressive_scroll(driver, steps=8, pause=0.7)

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
