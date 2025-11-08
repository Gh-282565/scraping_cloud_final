# -*- coding: utf-8 -*-
"""
scraper_core/zillow_scrape.py
Integrazione Zillow per l'orchestratore:
- Costruisce URL con la tua build_url (zillow_avg_runner)
- Esegue scrape con il tuo zillow_test_scrape.scrape(url)
- Converte le righe nel DF atteso (aggiungendo Status/State/County/Period)
"""

from __future__ import annotations
import re
import pandas as pd

# IMPORT RELATIVI (obbligatori dentro il package scraper_core)
from .zillow_avg_runner import build_url, df_from_rows  # riusiamo il tuo parsing numerico
from . import zillow_test_scrape as zts  # tuo scraper già collaudato


def _to_num(s):
    if s in (None, ""): 
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(s))) if isinstance(s, str) else float(s)
    except Exception:
        return None


def _rows_to_df(rows, *, state: str, county: str, status_label: str, period: str | None):
    """
    Converte le Row in DF allineato all'orchestratore.
    df_from_rows() dei tuoi script già calcola Price_num/Acres_num/Price_per_Acre;
    qui aggiungiamo metadati e rinominiamo le colonne dove serve.
    """
    base = df_from_rows(rows)  # colonne: Price, Price_num, Acres, Acres_num, Price_per_Acre, Location, Link
    if base is None or base.empty:
        return pd.DataFrame(columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])

    # aggiungi metadati fissi
    base["Status"] = status_label
    base["County"] = county
    base["State"] = state
    base["Period"] = period or ""

    # allineamenti minimi (l’orchestratore poi normalizza e ordina)
    # qui Price è testuale; Price_num è numerico. La pipeline usa Price (numerico)
    # → portiamo Price a numerico se Price_num è disponibile
    if "Price_num" in base.columns:
        base["Price"] = base["Price_num"].apply(_to_num)
    if "Acres_num" in base.columns:
        base["Acres"] = base["Acres_num"].apply(_to_num)

    wanted = ["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"]
    for col in wanted:
        if col not in base.columns:
            base[col] = None
    return base[wanted]


def run_scrape(
    *,
    state: str,
    county: str,
    acres_min: int,
    acres_max: int,
    include_forsale: bool,
    include_sold: bool,
    headless: bool = True,   # (opzionale: si può propagare in zts.scrape mettendo --headless)
    period: str | None = None,
) -> pd.DataFrame:
    """
    Entry-point per l’orchestratore (scraper_core.scraper).
    Esegue fino a 2 ricerche: For Sale e/o Sold.
    """
    all_parts = []

    # Zillow URL secondo il tuo runner (usa lot in sqft, doz per periodo, ecc.)
    modes = []
    if include_forsale:
        modes.append(("For Sale", "land"))
    if include_sold:
        modes.append(("Sold", "sold"))

    # NB: regionId/bounds non obbligatori; il runner li accetta anche None.
    region_id = None
    north = south = east = west = None
    min_lot = acres_min
    max_lot = acres_max

    for label, tipo in modes:
        url = build_url(
            county, state, region_id, north, south, east, west,
            period, min_lot, max_lot, tipo_vendita=tipo
        )
        print(f"[ZILLOW] URL {label}: {url}")

        # Esegue il tuo scraper reale
        rows = zts.scrape(url)
        print(f"[ZILLOW] {label}: {len(rows)} risultati")

        df_part = _rows_to_df(rows, state=state, county=county, status_label=label, period=period)
        all_parts.append(df_part)

    if not all_parts:
        return pd.DataFrame(columns=["Price","Acres","Price_per_Acre","Location","Link","Status","County","State","Period"])

    df = pd.concat(all_parts, ignore_index=True)
    return df
