import os
import pandas as pd
from functools import lru_cache

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

@lru_cache(maxsize=1)
def load_parametri(path_hint: str | None = None) -> pd.DataFrame:
    """Load 'parametri.xlsx' (Foglio1) and normalize headers.
    Accepts either an explicit path or searches in BASE_DIR.
    Returns a DataFrame with columns: County, State (upper), Region Id, West, South, East, North.
    """
    candidates = []
    if path_hint:
        candidates.append(path_hint)
    candidates.append(os.path.join(BASE_DIR, 'parametri.xlsx'))
    candidates.append(os.path.join(BASE_DIR, '..', 'parametri.xlsx'))
    candidates.append(os.path.join(BASE_DIR, 'data', 'parametri.xlsx'))

    for p in candidates:
        if p and os.path.exists(p):
            xls = pd.ExcelFile(p)
            df = xls.parse('Foglio1')
            # normalize columns
            colmap = {c: c.strip() for c in df.columns}
            df = df.rename(columns=colmap)
            # Uppercase state codes in-memory only
            if 'State' in df.columns:
                df['State'] = df['State'].astype(str).str.strip().str.upper()
            # County sanitize
            if 'County' in df.columns:
                df['County'] = df['County'].astype(str).str.strip()
            return df
    raise FileNotFoundError("parametri.xlsx non trovato nelle posizioni attese.")
