# realtor_scrape.py — DIAG build (2025-11-12)
# Basato sulla tua ultima versione Render-lean v2, con diagnostica estesa.
# Novità principali:
# - Flag ENV per controllo runtime: REALTOR_FAST, REALTOR_WAIT, REALTOR_SCROLL, REALTOR_IMAGES,
#   REALTOR_QUICK (uscita dopo consent), REALTOR_DIAG (snap multipli + log extra).
# - URL corretta con lot-sqft-<min>-<max> e /sold opzionale.
# - Consent iframe-aware (una sola versione), snapshot HTML in più fasi, 
#   scroll progressivo e riempimento della virtual list.
# - Parser più tollerante: CSS + XPATH + fallback tramite anchor.
# - Writer Excel opzionale (CLI) e wrapper run_scrape -> DataFrame standard.

import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional

# --------------------------------------------------
# Config / Paths
# --------------------------------------------------
RESULTS_BASE = "/app/results"
SNAP_DIR = os.path.join(RESULTS_BASE, "snapshots")
os.makedirs(RESULTS_BASE, exist_ok=True)
os.makedirs(SNAP_DIR, exist_ok=True)

WAIT_TIMEOUT = int(os.getenv("REALTOR_WAIT", "35"))            # attesa indicatori lista
SCROLL_CYCLES = int(os.getenv("REALTOR_SCROLL", "2"))           # cicli deep fill
USE_FAST_UC = bool(int(os.getenv("REALTOR_FAST", "1")))         # UC driver lean
IMAGES_ON = (os.getenv("REALTOR_IMAGES", "0") == "1")           # immagini ON/OFF
QUICK_EXIT = bool(int(os.getenv("REALTOR_QUICK", "0")))          # esci dopo consent
DIAG_MODE = bool(int(os.getenv("REALTOR_DIAG", "1")))            # diagnostica estesa


def log(msg: str):
    print(msg, flush=True)


# --------------------------------------------------
# Driver
# --------------------------------------------------
def _import_uc():
    import undetected_chromedriver as uc
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    return uc, ChromeOptions


def _import_driver_factory():
    from scraper_core.driver_factory import get_driver
    return get_driver


from selenium.webdriver.common.by import By


def _build_fast_uc_driver():
    uc, ChromeOptions = _import_uc()
    opts = ChromeOptions()
    opts.set_capability("pageLoadStrategy", "eager")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,1100")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    prefs = {
        "profile.managed_default_content_settings.images": (1 if IMAGES_ON else 2),
        "profile.default_content_setting_values": {"images": (1 if IMAGES_ON else 2)},
    }
    opts.add_experimental_option("prefs", prefs)
    if not IMAGES_ON:
        opts.add_argument("--blink-settings=imagesEnabled=false")

    profile_dir = "/tmp/uc_profile_realtor"
    os.makedirs(profile_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile_dir}")

    driver = uc.Chrome(options=opts)
    log(f"[DRIVER] FAST UC attivo | images={'ON' if IMAGES_ON else 'OFF'} | wait={WAIT_TIMEOUT}s")
    return driver


# --------------------------------------------------
# Utils / Snapshot / Waits
# --------------------------------------------------
def _snapshot(driver, tag: str):
    if not DIAG_MODE:
        return
    try:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fn = os.path.join(SNAP_DIR, f"realtor_{tag}_{ts}.html")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log(f"[SNAP] {fn}")
    except Exception as e:
        log(f"[SNAP][ERR] {e}")


def _click_cookie_consent(driver, timeout: int = 10) -> bool:
    """Prova in iframe, poi nel main. Non rilancia eccezioni."""
    try:
        driver.implicitly_wait(2)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for fr in iframes:
            try:
                driver.switch_to.frame(fr)
                btns = driver.find_elements(
                    By.XPATH,
                    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept') "
                    "or contains(., 'I agree') or contains(., 'Consenti')]",
                )
                if btns:
                    btns[0].click()
                    driver.switch_to.default_content()
                    log("[CONSENT] in iframe")
                    return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
        # main
        btns = driver.find_elements(
            By.XPATH,
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept') "
            "or contains(., 'I agree') or contains(., 'Consenti')]",
        )
        if btns:
            btns[0].click()
            log("[CONSENT] main")
            return True
    except Exception as e:
        log(f"[CONSENT][ERR] {e}")
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False


def _wait_for_results(driver, timeout: int) -> bool:
    from selenium.webdriver.support.ui import WebDriverWait
    SELECTORS = [
        "[data-testid='component-property-card']",
        "[data-testid='property-card']",
        "article[data-testid*='property-card']",
        "ul[data-testid='results-list']",
        "div[data-testid='search-result-list']",
        "a[href*='/realestateandhomes-detail/']",
    ]
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: any(d.find_elements(By.CSS_SELECTOR, s) for s in SELECTORS)
        )
        return True
    except Exception:
        return False


def _scroll_results_container(driver, steps: int = 3, pause: float = 0.45):
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


def _progressive_scroll(driver, steps: int = 4, pause: float = 0.55):
    for _ in range(steps):
        try:
            driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight*0.85));")
        except Exception:
            pass
        _scroll_results_container(driver, steps=1, pause=0.0)
        time.sleep(pause)


def _deep_fill_results(driver, cycles: int):
    for _ in range(cycles):
        _progressive_scroll(driver, steps=3, pause=0.50)
        time.sleep(0.6)


# --------------------------------------------------
# URL builder
# --------------------------------------------------
def _slugify_county(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[&]", " and ", s)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def _url_for(state_abbr: str, county_name: str, acres_min, acres_max, sold: bool = False) -> str:
    try:
        mn = int(round(float(acres_min) * 43560))
    except Exception:
        mn = 0
    try:
        mx = int(round(float(acres_max) * 43560))
    except Exception:
        mx = 0
    county_slug = _slugify_county(county_name)
    base = (
        f"https://www.realtor.com/realestateandhomes-search/"
        f"{county_slug}-county_{state_abbr.upper()}/type-land"
    )
    if mn or mx:
        base += f"/lot-sqft-{mn}-{mx}"
    if sold:
        base += "/sold"
    return base


# --------------------------------------------------
# Parsing helpers
# --------------------------------------------------
def _first_price(text: str) -> str:
    m = re.search(r"\$[\d,]+", text or "")
    return m.group(0) if m else ""


def _parse_acres_from_text(text: str) -> str:
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


def _extract_listings(driver) -> List[Dict[str, Any]]:
    listings: List[Dict[str, Any]] = []

    cards = driver.find_elements(
        By.CSS_SELECTOR,
        "[data-testid='component-property-card'], [data-testid='property-card'], article[data-testid*='property-card']",
    )

    if not cards:
        xp_candidates = [
            "//li[contains(@class,'component_property-card')]",
            "//div[contains(@data-testid,'property-card')]",
            "//li[.//a[contains(@href,'/realestateandhomes-detail/')]]",
            "//a[contains(@href,'/realestateandhomes-detail/')]//ancestor::li",
            "//a[contains(@href,'/realestateandhomes-detail/')]",
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
        # Fallback minimale: ancora -> parent text
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/realestateandhomes-detail/']")
        for a in anchors:
            try:
                link = a.get_attribute("href") or ""
                parent = a.find_element(By.XPATH, "./ancestor::*[position()<=3]")
                block = parent.text
                price = _first_price(block)
                acres = _parse_acres_from_text(block)
                listings.append({
                    "title": a.text.strip(),
                    "price": price,
                    "acres": acres,
                    "link": link,
                    "status": "",
                })
            except Exception:
                pass
        return listings

    for el in cards:
        try:
            # title
            title = ""
            for sel in [
                ("css", "[data-testid='card-title']"),
                ("css", "h3"),
                ("css", "h2"),
                ("xpath", ".//h3|.//h2"),
            ]:
                try:
                    cand = (
                        el.find_elements(By.CSS_SELECTOR, sel[1]) if sel[0] == "css" else el.find_elements(By.XPATH, sel[1])
                    )
                    if cand:
                        title = cand[0].text.strip()
                        break
                except Exception:
                    pass

            # price
            price = ""
            for sel in [
                ("css", "[data-testid='card-price']"),
                ("css", "span[data-label='pc-price']"),
                ("css", "span[data-testid*='price']"),
                ("css", "span[class*='price']"),
                ("xpath", ".//*[contains(text(),'$')]")
            ]:
                try:
                    cand = (
                        el.find_elements(By.CSS_SELECTOR, sel[1]) if sel[0] == "css" else el.find_elements(By.XPATH, sel[1])
                    )
                    if cand:
                        price = cand[0].text.strip()
                        break
                except Exception:
                    pass

            # acres (lot info nel blocco)
            acres_text = ""
            try:
                lot_els = el.find_elements(By.XPATH, 
                    ".//*[contains(translate(text(),'ACRES','acres'),'acres') or contains(translate(text(),'LOT','lot'),'lot')]"
                )
                if lot_els:
                    acres_text = lot_els[0].text.strip()
            except Exception:
                pass
            acres = _parse_acres_from_text(acres_text)

            # link
            link = ""
            for sel in [
                ("css", "a[data-testid='card-link']"),
                ("css", "a[data-testid*='property-card']"),
                ("css", "a[href*='/realestateandhomes-detail/']"),
                ("xpath", ".//a[contains(@href,'/realestateandhomes-detail/')]")
            ]:
                try:
                    cand = (
                        el.find_elements(By.CSS_SELECTOR, sel[1]) if sel[0] == "css" else el.find_elements(By.XPATH, sel[1])
                    )
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
                "status": status_text,
            })
        except Exception as e:
            log(f"[PARSE][CARD][ERR] {e}")

    return listings


# --------------------------------------------------
# Scraper core
# --------------------------------------------------
@dataclass
class RealtorParams:
    state: str
    county: str
    acres_min: float
    acres_max: float
    sold: bool = False


def scrape_realtor(params: RealtorParams) -> List[Dict[str, Any]]:
    driver = None
    try:
        if USE_FAST_UC:
            driver = _build_fast_uc_driver()
        else:
            log("[DRIVER] driver_factory")
            driver = _import_driver_factory()()

        url = _url_for(params.state, params.county, params.acres_min, params.acres_max, sold=params.sold)
        log(f"[URL] {url}")

        driver.get(url)
        time.sleep(2)
        _snapshot(driver, "after_get")

        clicked = _click_cookie_consent(driver)
        log(f"[CONSENT] clicked={clicked}")
        _snapshot(driver, "after_consent")

        if QUICK_EXIT:
            log("[QUICK] Uscita dopo consent per test di stabilità.")
            return []

        if not _wait_for_results(driver, timeout=WAIT_TIMEOUT):
            log("[WAIT] nessun indicatore; scroll")
            _progressive_scroll(driver, steps=4, pause=0.55)
            if not _wait_for_results(driver, timeout=WAIT_TIMEOUT):
                _snapshot(driver, "zero_results")
                return []

        # riempimento lieve della virtual list
        _deep_fill_results(driver, cycles=SCROLL_CYCLES)
        _progressive_scroll(driver, steps=3, pause=0.5)

        # diagnostica selettori
        try:
            for s in [
                "article[data-testid='property-card']",
                "div[data-testid='property-card']",
                "ul[data-testid='results-list'] article",
                "div[data-testid='search-result-list'] article",
                "a[href*='/realestateandhomes-detail/']",
            ]:
                n = len(driver.find_elements(By.CSS_SELECTOR, s))
                log(f"[CHECK] {s} -> {n}")
        except Exception as e:
            log(f"[CHECK][ERR] {e}")
        _snapshot(driver, "after_scroll_diag")

        data = _extract_listings(driver)
        log(f"[RESULT] trovate {len(data)} card")

        if len(data) == 0:
            # ultima foto istantanea quando 0 risultati, per confronto
            _snapshot(driver, "after_parse_zero")
        return data

    except Exception as e:
        log(f"[ERROR] {e}")
        try:
            et, ex, tb = sys.exc_info()
            with open(os.path.join(RESULTS_BASE, "logs_realtor_error.txt"), "w", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(et, ex, tb)))
        except Exception:
            pass
        return []
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


# --------------------------------------------------
# Excel writer (opzionale CLI)
# --------------------------------------------------
def save_excel(records: List[Dict[str, Any]], path: str):
    import pandas as pd
    from openpyxl.utils import get_column_letter

    if not records:
        df = pd.DataFrame(columns=["title", "price", "acres", "link", "status"])
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


# --------------------------------------------------
# Wrapper orchestratore
# --------------------------------------------------
import pandas as pd


def _num(x):
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(x)))
    except Exception:
        return None


def _to_df(listings: List[Dict[str, Any]], *, state: str, county: str, status_label: str, period: Optional[str]):
    rows = []
    for r in listings:
        price_txt = r.get("price")
        acres_txt = r.get("acres")
        link = r.get("link")
        loc = r.get("title") or r.get("location") or ""
        price_num = _num(price_txt)
        acres_num = _num(acres_txt)
        ppa = (price_num / acres_num) if (price_num and acres_num and acres_num > 0) else None
        price_fmt = f"${price_num:,.0f}" if price_num is not None else (price_txt or "")
        rows.append(
            {
                "Price": price_fmt,
                "Acres": acres_num,
                "Price_per_Acre": ppa,
                "Location": loc,
                "Link": link,
                "Status": status_label,
                "County": county,
                "State": state,
                "Period": period or "",
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "Price",
            "Acres",
            "Price_per_Acre",
            "Location",
            "Link",
            "Status",
            "County",
            "State",
            "Period",
        ],
    )


def run_scrape(
    *,
    state: str,
    county: str,
    acres_min: int,
    acres_max: int,
    include_forsale: bool,
    include_sold: bool,
    headless: bool = True,
    period: Optional[str] = None,
) -> pd.DataFrame:
    log("[REALTOR][VER] run_scrape wrapper attivo")
    try:
        start_marker = os.path.join(SNAP_DIR, f"realtor_start_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(start_marker, "w", encoding="utf-8") as f:
            f.write("run_scrape avviato\n")
        log(f"[SNAP] {start_marker}")
    except Exception as e:
        log(f"[SNAP][ERR] {e}")

    parts: List[pd.DataFrame] = []

    if include_forsale:
        listings_fs = scrape_realtor(
            RealtorParams(state=state, county=county, acres_min=acres_min, acres_max=acres_max, sold=False)
        )
        parts.append(_to_df(listings_fs, state=state, county=county, status_label="For Sale", period=period))

    if include_sold:
        listings_sd = scrape_realtor(
            RealtorParams(state=state, county=county, acres_min=acres_min, acres_max=acres_max, sold=True)
        )
        parts.append(_to_df(listings_sd, state=state, county=county, status_label="Sold", period=period))

    if not parts:
        return pd.DataFrame(
            columns=["Price", "Acres", "Price_per_Acre", "Location", "Link", "Status", "County", "State", "Period"]
        )

    return pd.concat(parts, ignore_index=True)


# --------------------------------------------------
# CLI (per test manuali nel container)
# --------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) >= 6:
        state = sys.argv[1]
        county = sys.argv[2]
        min_ac = sys.argv[3]
        max_ac = sys.argv[4]
        mode = sys.argv[5].lower()
        sold = mode == "sold"
        recs = scrape_realtor(RealtorParams(state=state, county=county, acres_min=min_ac, acres_max=max_ac, sold=sold))
        out = os.path.join(RESULTS_BASE, "realtor_results.xlsx")
        save_excel(recs, out)
        print(f"[OK] Salvato: {out}")
    else:
        print("Uso: python realtor_scrape.py <STATE> <County Name> <min acres> <max acres> <forsale|sold>")
