# realtor_scrape.py - versione STUB per Render (Realtor disabilitato)
# -------------------------------------------------------------------
# Questa versione NON fa più scraping, NON apre browser e NON usa Selenium.
# Serve solo a:
#  - permettere a scraper.py di importare "realtor_scrape" senza errori
#  - restituire immediatamente un DataFrame vuoto se qualcuno lo chiama.
#
# Nella versione cloud "solo Zillow" la casella Realtor è nascosta dalla maschera,
# quindi run_scrape NON dovrebbe essere mai invocata in pratica.

import pandas as pd

print("[REALTOR][LOAD] Modulo STUB caricato (Render: Realtor disabilitato).", flush=True)


def run_scrape(
    state: str,
    county: str,
    acres_min: float,
    acres_max: float,
    include_forsale: bool = True,
    include_sold: bool = False,
    period: str = "12M",
    headless: bool = True,
    **kwargs,
) -> pd.DataFrame:
    """
    Stub: viene chiamato solo se qualcosa nel codice forza ancora Realtor.
    In ambiente Render la maschera non mostra più la casella Realtor,
    quindi NON dovrebbe essere usato. In ogni caso:
      - nessun driver viene creato
      - nessuna chiamata HTTP viene fatta
      - restituisce un DataFrame vuoto con le colonne attese.
    """
    print(
        "[REALTOR][STUB] run_scrape chiamato ma Realtor è disattivato in cloud. "
        "Restituisco DataFrame vuoto.",
        flush=True,
    )

    cols = [
        "Price",
        "Acres",
        "Price_per_Acre",
        "Location",
        "Link",
        "Status",
        "County",
        "State",
        "Period",
    ]
    return pd.DataFrame(columns=cols)
