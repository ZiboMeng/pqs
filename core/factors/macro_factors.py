"""Macro factor family (Bucket Macro, PRD 2026-05-12).

PRD-E TAA framework reactivation path. Pulls FRED-sourced macro
series via FredProvider, then broadcasts time-series macro factors
across the universe (each stock sees the same macro value at date t).

Factors (6):
  - yield_curve_10y_2y      : DGS10 - DGS2 (term spread)
  - fed_funds_yoy_change    : FEDFUNDS - FEDFUNDS.shift(252)
  - dxy_zscore_60d          : DTWEXBGS 60d z-score
  - wti_yoy_pct             : DCOILWTICO 252d pct change
  - vix_zscore_60d          : VIXCLS 60d z-score
  - cpi_yoy_pct             : CPIAUCNS 12-month pct change

Each factor is a DataFrame of (date × ticker) where every cell in a
given date row has the same value (the macro reading at that date).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.data.fred_provider import FredProvider

logger = logging.getLogger(__name__)


MACRO_FACTOR_NAMES = [
    "yield_curve_10y_2y",
    "fed_funds_yoy_change",
    "dxy_zscore_60d",
    "wti_yoy_pct",
    "vix_zscore_60d",
    "cpi_yoy_pct",
]


def _broadcast(series: pd.Series, daily_idx: pd.DatetimeIndex, tickers: List[str]) -> pd.DataFrame:
    """Broadcast a time-series to (daily_idx × tickers) panel."""
    s = series.reindex(daily_idx.union(series.index)).sort_index().ffill().reindex(daily_idx)
    panel = pd.DataFrame(
        np.tile(s.values[:, None], (1, len(tickers))),
        index=daily_idx, columns=tickers,
    )
    return panel


def compute_macro_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    provider: Optional[FredProvider] = None,
) -> Dict[str, pd.DataFrame]:
    """Compute 6 macro factors, broadcast across tickers."""
    provider = provider or FredProvider()
    factors: Dict[str, pd.DataFrame] = {}

    try:
        dgs10 = provider.load_series("DGS10", as_business_daily=True)
        dgs2 = provider.load_series("DGS2", as_business_daily=True)
        yc = (dgs10 - dgs2).dropna()
        factors["yield_curve_10y_2y"] = _broadcast(yc, daily_idx, tickers)
    except FileNotFoundError:
        factors["yield_curve_10y_2y"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    try:
        ffr = provider.load_series("FEDFUNDS", as_business_daily=True)
        ffr_yoy = ffr - ffr.shift(252)
        factors["fed_funds_yoy_change"] = _broadcast(ffr_yoy.dropna(), daily_idx, tickers)
    except FileNotFoundError:
        factors["fed_funds_yoy_change"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    try:
        dxy = provider.load_series("DTWEXBGS", as_business_daily=True)
        dxy_z = (dxy - dxy.rolling(60).mean()) / dxy.rolling(60).std()
        factors["dxy_zscore_60d"] = _broadcast(dxy_z.dropna(), daily_idx, tickers)
    except FileNotFoundError:
        factors["dxy_zscore_60d"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    try:
        wti = provider.load_series("DCOILWTICO", as_business_daily=True)
        wti_yoy = wti.pct_change(252)
        factors["wti_yoy_pct"] = _broadcast(wti_yoy.dropna(), daily_idx, tickers)
    except FileNotFoundError:
        factors["wti_yoy_pct"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    try:
        vix = provider.load_series("VIXCLS", as_business_daily=True)
        vix_z = (vix - vix.rolling(60).mean()) / vix.rolling(60).std()
        factors["vix_zscore_60d"] = _broadcast(vix_z.dropna(), daily_idx, tickers)
    except FileNotFoundError:
        factors["vix_zscore_60d"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    try:
        cpi = provider.load_series("CPIAUCNS", as_business_daily=True)
        cpi_yoy = cpi.pct_change(252)
        factors["cpi_yoy_pct"] = _broadcast(cpi_yoy.dropna(), daily_idx, tickers)
    except FileNotFoundError:
        factors["cpi_yoy_pct"] = pd.DataFrame(np.nan, index=daily_idx, columns=tickers)

    return factors
