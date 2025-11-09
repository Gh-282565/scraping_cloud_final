# -*- coding: utf-8 -*-
"""
scraper_core/realtor_scrape.py
Headless Realtor.com scraper per orchestratore cloud.
Ritorna DF con colonne: Price, Acres, Price_per_Acre, Location, Link, Status, County, State, Period
"""

from __future__ import annotations
import re
import unicodedata
import pandas as pd
from typing import List, Optional
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from scraper_core.driver_factory import make_uc_driver

# -------------------------
# Helpers
# -------------------------
def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s, flags=re.I).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s

def _to_float(s) -> Optional[float]:
    try:
        s = re.sub(r"[^0-9.\-]", "", str(s))
        return float(s) if s else None
    except Exception:
        return None

def _fmt_price_usd(v: Optional[float]) -> Optional[str]:
    if v is None: 
        return None
    try:
        return f"${float(v):,.0f}"
    except Exception:
        return None

def _build_realtor_url(state: str, county: str, acres_min: int, acres_max: int, sold: bool) -> str:
    # Path “<county>-county_<state>/type-land”
    path = f"{_slug(county)}-county_{state.upper()}/type-land"
    # Filtro acres. Realtor accetta lot-<min>-<max>acres nel path
    lot = f"lot-{int(acres_min)}-{int(acres_max)}acres" if acres_max else f"lot-{int(acres_min)}-acres"
    base = f"https://www.realtor.com/realestateandhomes-search/{path}/{lot}"
    if sold:
        # Ordina per “recently sold” (fallback tramite query). Non è perfetto ma funziona.
        return base + "?sby=6&status=110001"
    return base

def _collect_cards(driver) -> List[dict]:
    out: List[dict] = []
    # Attendi contenitore risultati (diversi data-testid a seconda del layout)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((
                By.XPATH, "//ul|//div[contains(@data-testid,'result-list') or contains(@data-testid,'srp-list')]"
            ))
        )
    except Exception:
        pass

    cards = driver.find_elements(By.XPATH, "//li//div[contains(@data-testid,'property-card')]|//article")
    for c in cards[:200]:
        txt = c.text or ""
        # price
        m_price = re.search(r"\$\s?[\d,\.]+", txt)
        price = m_price.group(0) if m_price else None
        # acres (lot size)
        acres = None
        m_lot = re.search(r"([\d\.,]+)\s*acres?", txt, re.I)
        if m_lot:
            acres = m_lot.group(1)
        else:
            m_lot2 = re.search(r"lot size[:\s]+([\d\.,]+)\s*acres?", txt, re.I)
            acres = m_lot2.group(1) if m_lot2 else None
        # location / address tail
        loc = None
        lines = [t.strip() for t in txt.splitlines() if t.strip()]
        for line in lines[::-1]:
            if re.search(r",[ ]*[A-Z]{2}[ ]*\d{5}", line):
                loc = re.sub(r"^.*?,\s*", "", line)
                break
        # link
        href = None
        try:
            a = c.find_element(By.XPATH, ".//a[@href]")
            href = a.get_attribute("href")
        except Exception:
            pass

        out.append({"price": price, "acres": acres, "location": loc, "link": href})
    return out

def _rows_to_df(rows: List[dict], *, state: str, county: str, status_label: str, period: Optional[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])
    data = []
    for r in rows:
        price_num = _to_float(r.get("price"))
        acres_num = _to_float((r.get("acres") or "").replace(",", "")) if r.get("acres") else None
        ppa = (price_num / acres_num) if (price_num and acres_num and acres_num > 0) else None
        data.append({
            "Price": _fmt_price_usd(price_num) if price_num is not None else r.get("price"),
            "Acres": acres_num,
            "Price_per_Acre": ppa,
            "Location": r.get("location"),
            "Link": r.get("link"),
            "Status": status_label,
            "County": county,
            "State": state,
            "Period": period or ""
        })
    return pd.DataFrame(data, columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])

# -------------------------
# Entry-point orchestratore
# -------------------------
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

    driver = None
    parts = []

    try:
        driver = make_uc_driver()
        print("[REALTOR] Driver OK (headless)", flush=True)

        modes = []
        if include_forsale:
            modes.append(("For Sale", False))
        if include_sold:
            modes.append(("Sold", True))

        for label, is_sold in modes:
            url = _build_realtor_url(state, county, acres_min, acres_max, sold=is_sold)
            print(f"[REALTOR] URL {label}: {url}", flush=True)

            # Navigazione resiliente
            try:
                driver.get(url)
            except TimeoutException:
                print("[REALTOR][WARN] driver.get timeout; continuo con contenuto parziale", flush=True)

            rows = _collect_cards(driver)
            print(f"[REALTOR] {label}: {len(rows)} risultati (cards)", flush=True)

            df = _rows_to_df(rows, state=state, county=county, status_label=label, period=period)
            parts.append(df)

        if not parts:
            return pd.DataFrame(columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])
        return pd.concat(parts, ignore_index=True)

    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass
