"""FRED macroeconomic data provider (CSV endpoint, no API key).

PRD 2026-05-12 (Bucket Macro / PRD-E TAA reactivation path).

Uses https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series_id>
which is free, no auth, deep history (CPIAUCNS goes back to 1913).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
DEFAULT_CACHE_DIR = Path("data/fundamentals/macro")

# Standard PQS macro series codes (FRED ID, frequency, units)
MACRO_SERIES = {
    "CPIAUCNS": {"label": "CPI All Items (NSA)", "frequency": "monthly", "units": "index_1982_84_100"},
    "FEDFUNDS": {"label": "Federal Funds Effective Rate", "frequency": "monthly", "units": "pct_per_annum"},
    "DGS10":    {"label": "10-Year Treasury Constant Maturity Rate", "frequency": "daily", "units": "pct_per_annum"},
    "DGS2":     {"label": "2-Year Treasury Constant Maturity Rate", "frequency": "daily", "units": "pct_per_annum"},
    "DTWEXBGS": {"label": "Trade-Weighted USD (Broad)", "frequency": "daily", "units": "index_2006_100"},
    "DCOILWTICO": {"label": "WTI Crude Oil (Cushing OK)", "frequency": "daily", "units": "usd_per_barrel"},
    "VIXCLS":   {"label": "CBOE VIX (Close)", "frequency": "daily", "units": "index"},
    "UNRATE":   {"label": "Unemployment Rate (SA)", "frequency": "monthly", "units": "pct"},
}


class FredProvider:
    """Fetch + cache FRED time series via fredgraph.csv endpoint."""

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def download_series(self, series_id: str) -> Path:
        """Download CSV; cache to <cache_dir>/<series_id>.csv. Returns path."""
        import requests
        url = f"{FRED_CSV_BASE}?id={series_id}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        if not r.text.startswith("observation_date"):
            raise ValueError(f"Unexpected FRED response for {series_id}: {r.text[:100]}")
        path = self.cache_dir / f"{series_id}.csv"
        with open(path, "wb") as f:
            f.write(r.content)
        return path

    def load_series(
        self,
        series_id: str,
        as_business_daily: bool = False,
    ) -> pd.Series:
        """Load cached series; if not cached raises FileNotFoundError.

        Returns pd.Series indexed by date. If as_business_daily=True,
        forward-fills to business calendar (preserves PIT semantics:
        a monthly observation released on the 15th propagates from
        that date forward).
        """
        path = self.cache_dir / f"{series_id}.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"FRED series {series_id} not cached at {path}. "
                f"Run dev/scripts/fundamentals/build_macro_cache.py."
            )
        df = pd.read_csv(path, parse_dates=["observation_date"])
        df = df.set_index("observation_date").sort_index()
        # FRED sometimes uses '.' for missing values
        series = pd.to_numeric(df[series_id], errors="coerce").dropna()
        series.name = series_id
        if as_business_daily:
            bday_idx = pd.bdate_range(series.index.min(), series.index.max())
            series = series.reindex(bday_idx.union(series.index)).sort_index().ffill().reindex(bday_idx)
        return series

    def load_panel(
        self,
        series_ids: List[str],
        as_business_daily: bool = True,
    ) -> pd.DataFrame:
        """Multi-series DataFrame, columns = series IDs, business-day index."""
        cols = {}
        for sid in series_ids:
            try:
                cols[sid] = self.load_series(sid, as_business_daily=as_business_daily)
            except FileNotFoundError:
                logger.warning("Series %s not cached; skipping", sid)
        if not cols:
            return pd.DataFrame()
        # Outer-join via Union of indices
        combined = pd.concat(cols, axis=1, join="outer")
        return combined.ffill()
