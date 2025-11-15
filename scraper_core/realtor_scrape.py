# today_realtor_scrape_PATCH_FAST_REGEX_V3.py

# ----------------------------------------------------------------------
# Cookie consent (iframe-aware) + forza sblocco overlay
# ----------------------------------------------------------------------
def _click_cookie_consent(driver):
    try:
        driver.implicitly_wait(2)
        iframes = driver.find_elements("tag name", "iframe")
        for f in iframes:
            try:
                driver.switch_to.frame(f)
                btns = driver.find_elements(
                    "xpath",
                    "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]"
                )
                if btns:
                    btns[0].click()
                    driver.switch_to.default_content()
                    print("[CONSENT] Clicked inside iframe")
                    return True
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()
        # fallback on main doc
        btns = driver.find_elements(
            "xpath",
            "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'accept')]"
        )
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


# ----------------------------------------------------------------------
# Setup driver & helper comuni
# ----------------------------------------------------------------------
import os, time, math, sys, traceback, re
from dataclasses import dataclass
from typing import List, Dict, Any

USE_FAST_UC = bool(int(os.getenv("REALTOR_FAST", "1")))

def _import_uc():
    import undetected_chromedriver as uc
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    return uc, ChromeOptions


def _import_driver_factory():
    from scraper_core.driver_factory import get_driver
    return get_driver


from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException

RESULTS_DIR = os.path.join(os.getcwd(), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def log(*a):
    print(*a, flush=True)
print(f"[REALTOR][LOAD] using file {__file__}", flush=True)


def _build_fast_uc_driver():
    uc, ChromeOptions = _import_uc()

    opts = ChromeOptions()
    opts.set_capability("pageLoadStrategy", "eager")
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1440,1200")

    prefs = {
        "profile.default_content_setting_values": {"images": 2},
        "profile.managed_default_content_settings.images": 2
    }
    opts.add_experimental_option("prefs", prefs)

    profile_dir = os.path.join(os.getcwd(), "uc_profile_realtor")
    os.makedirs(profile_dir, exist_ok=True)
    opts.add_argument(f"--user-data-dir={profile_dir}")

    driver = uc.Chrome(options=opts)
    return driver


def _progressive_scroll(driver, steps=8, pause=0.7):
    for i in range(steps):
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight * 0.25);")
        time.sleep(pause)
        try:
            _force_unblock(driver)
            time.sleep(0.3)
        except Exception:
            pass


# ----------------------------------------------------------------------
# Snapshot & safe_get
# ----------------------------------------------------------------------
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


def _safe_get(driver, url, tries=3, pause=3.5):
    """Navigazione robusta con retry e snapshot."""
    last_err = None
    for i in range(1, tries + 1):
        try:
            log(f"[GET] try={i} url={url}")
            driver.get(url)
            time.sleep(pause)
            _snapshot(driver, f"after_get_t{i}")
            return True
        except Exception as e:
            last_err = e
            log(f"[GET][ERR] try={i} -> {e}")
    log(f"[GET][FAIL] url={url} err={last_err}")
    return False


def _wait_for_results(driver, timeout=25):
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


# ----------------------------------------------------------------------
# Parser DOM + fallback regex
# ----------------------------------------------------------------------
def _first_price(text):
    m = re.search(r"\$[\d,]+", text or "")
    if not m:
        return ""
    return m.group(0)


def _parse_acres_from_text(text):
    if not text:
        return None
    t = text.lower()
    m = re.search(r"([\d.,]+)\s*acres?", t)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except:
            return None
    m = re.search(r"([\d.,]+)\s*(square feet|sqft|sq\.ft)", t)
    if m:
        try:
            sqft = float(m.group(1).replace(",", ""))
            return sqft / 43560.0
        except:
            return None
    return None


def _extract_listings(driver):
    listings = []

    cards = driver.find_elements(
        By.CSS_SELECTOR,
        "[data-testid='component-property-card'], [data-testid='property-card'], article[data-testid*='card']"
    )

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
            except:
                pass

    if not cards:
        log("[RESULT] Nessuna card trovata anche dopo i fallback DOM.")
        return []

    for el in cards:
        try:
            title = ""
            for sel in [
                ("css","[data-testid='card-title']"),
                ("css","h3"), ("css","h2"),
                ("xpath",".//h3|.//h2")
            ]:
                try:
                    cand = el.find_elements(
                        By.CSS_SELECTOR if sel[0]=="css" else By.XPATH,
                        sel[1]
                    )
                    if cand:
                        title = cand[0].text.strip()
                        break
                except:
                    pass

            price = ""
            for sel in [
                ("css","[data-testid='card-price']"),
                ("css","span[data-label='pc-price']"),
                ("css","span[data-testid*='price']"),
                ("css","span[class*='price']"),
                ("xpath",".//*[contains(text(),'$')]")
            ]:
                try:
                    cand = el.find_elements(
                        By.CSS_SELECTOR if sel[0]=="css" else By.XPATH,
                        sel[1]
                    )
                    if cand:
                        price = _first_price(cand[0].text)
                        if price:
                            break
                except:
                    pass

            acres = None
            try:
                acres = _parse_acres_from_text(el.text)
            except:
                pass

            link = ""
            try:
                a = el.find_element(By.CSS_SELECTOR, "a[href*='/realestateandhomes-detail/']")
                link = a.get_attribute("href")
            except:
                try:
                    a = el.find_element(By.XPATH, ".//a[contains(@href,'/realestateandhomes-detail/')]")
                    link = a.get_attribute("href")
                except:
                    pass

            listings.append({
                "title": title,
                "price": price,
                "acres": acres,
                "link": link,
                "status": ""
            })
        except Exception as e:
            log(f"[PARSE][CARD][ERR] {e}")

    return listings


# ----------------------------------------------------------------------
# URL builder
# ----------------------------------------------------------------------
def _url_for(state_abbr, county_name, acres_min, acres_max, sold=False):
    try:
        acres_min = float(acres_min)
        acres_max = float(acres_max)
    except:
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


# ----------------------------------------------------------------------
# Core scrape
# ----------------------------------------------------------------------
@dataclass
class RealtorParams:
    state: str
    county: str
    acres_min: float
    acres_max: float
    sold: bool = False


def scrape_realtor(params: RealtorParams) -> List[Dict[str, Any]]:
    log("[REALTOR][VER] run_scrape wrapper attivo (V3_REGEX)")

    if USE_FAST_UC:
        log("[DRIVER] FAST UC attivo (ambiente test).")
        driver = _build_fast_uc_driver()
    else:
        log("[DRIVER] shared driver_factory.get_driver()")
        get_driver = _import_driver_factory()
        driver = get_driver(headless=True, for_realtor=True)

    try:
        url = _url_for(params.state, params.county, params.acres_min, params.acres_max, sold=params.sold)
        log("[URL]", url)

        if not _safe_get(driver, url, tries=2, pause=2.5):
            return []

        clicked = _click_cookie_consent(driver)
        log(f"[CONSENT] clicked={clicked}")
        if not clicked:
            try:
                _force_unblock(driver)
                time.sleep(0.5)
            except Exception as e:
                log(f"[UNBLOCK][ERR] {e}")

        _snapshot(driver, "after_consent")

        found = _wait_for_results(driver, timeout=25)
        if not found:
            log("[WAIT] nessun indicatore; continuo con scroll e DOM+regex.")

        _progressive_scroll(driver, steps=8, pause=0.7)

        try:
            title = driver.title
        except:
            title = ""
        try:
            html_len = len(driver.page_source or "")
        except:
            html_len = -1
        log(f"[PAGE] title='{title}' len={html_len}")

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

        listings = []
        try:
            listings = _extract_listings(driver)
        except Exception as e:
            log("[RESULT] Errore in _extract_listings:", e)

        # Fallback regex
        if not listings:
            try:
                html = driver.page_source or ""
                urls = re.findall(
                    r"https://www\.realtor\.com/realestateandhomes-detail/[^\\"']+",
                    html
                )
                seen = set()
                uniq_urls = []
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        uniq_urls.append(u)
                log(f"[FALLBACK-LINKS] trovate {len(uniq_urls)} URL annuncio da regex.")
                listings = [
                    {
                        "title": "",
                        "price": "",
                        "acres": None,
                        "link": u,
                        "status": ""
                    }
                    for u in uniq_urls
                ]
            except Exception as e:
                log(f"[FALLBACK-LINKS][ERR] {e}")

        if not listings:
            _snapshot(driver, "zero_results")

        log(f"[RESULT] Trovate {len(listings)} card (DOM+regex).")
        return listings

    finally:
        try:
            driver.quit()
        except:
            pass


# ----------------------------------------------------------------------
# Wrapper: restituisce SOLO un DataFrame (non più file)
# ----------------------------------------------------------------------
import pandas as pd

def _to_df(records: List[Dict[str, Any]], state: str, county: str,
           status_label: str, period: str) -> pd.DataFrame:

    if not records:
        return pd.DataFrame(columns=[
            "Price","Acres","Price_per_Acre","Location","Link",
            "Status","County","State","Period"
        ])
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
               period: str = "12M", headless: bool = True, **kwargs) -> pd.DataFrame:
    """
    Restituisce SEMPRE un DataFrame.
    La creazione del file Excel viene fatta da scraper.py.
    """
    parts = []

    if include_forsale:
        listings_fs = scrape_realtor(RealtorParams(
            state=state, county=county,
            acres_min=acres_min, acres_max=acres_max,
            sold=False
        ))
        parts.append(_to_df(
            listings_fs,
            state=state,
            county=county,
            status_label="For Sale",
            period=period
        ))

    if include_sold:
        listings_sd = scrape_realtor(RealtorParams(
            state=state, county=county,
            acres_min=acres_min, acres_max=acres_max,
            sold=True
        ))
        parts.append(_to_df(
            listings_sd,
            state=state,
            county=county,
            status_label="Sold",
            period=period
        ))

    if not parts:
        df = pd.DataFrame(columns=[
            "Price","Acres","Price_per_Acre","Location","Link",
            "Status","County","State","Period"
        ])
    else:
        df = pd.concat(parts, ignore_index=True)

    log(f"[REALTOR][RUN_SCRAPE] restituisco DF con {len(df)} righe.")
    return df
