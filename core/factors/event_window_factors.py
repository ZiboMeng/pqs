"""Event window factors — pre-FOMC / post-FOMC / pre-CPI / pre-NFP.

PRD 2026-05-12 Bucket A T1 batch 3 deferred items.

Factor definitions:
  pre_fomc_window_flag   : 1 if t in [FOMC - 2 bdays, FOMC] else 0
  post_fomc_window_flag  : 1 if t in [FOMC + 1, FOMC + 3 bdays] else 0
  pre_cpi_window_flag    : 1 if t in [CPI - 1 bday, CPI] else 0
  pre_nfp_window_flag    : 1 if t in [NFP - 1 bday, NFP] else 0

Each factor is broadcast across all tickers (time-only signal).
Sourced from `core.data.macro_event_calendar.load_calendar()`.

Sign convention: factor = 1 marks "anticipation window". Mining
infers IC sign from forward returns (could be positive or negative
depending on regime).
"""

from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from core.data.macro_event_calendar import load_calendar, window_flag_panel

logger = logging.getLogger(__name__)


EVENT_WINDOW_FACTOR_NAMES = [
    "pre_fomc_window_flag",
    "post_fomc_window_flag",
    "pre_cpi_window_flag",
    "pre_nfp_window_flag",
]


def compute_event_window_factors(
    daily_idx: pd.DatetimeIndex,
    tickers: List[str],
    yaml_path: str = "config/macro_event_calendar.yaml",
) -> Dict[str, pd.DataFrame]:
    # Audit Ω2 E1 fix: empty daily_idx → return empty panels gracefully
    if len(daily_idx) == 0:
        empty = pd.DataFrame(index=daily_idx, columns=tickers, dtype=float)
        return {n: empty.copy() for n in EVENT_WINDOW_FACTOR_NAMES}
    calendar = load_calendar(
        yaml_path=yaml_path,
        start_year=int(daily_idx.min().year) - 1,
        end_year=int(daily_idx.max().year) + 1,
    )
    factors: Dict[str, pd.DataFrame] = {}
    factors["pre_fomc_window_flag"] = window_flag_panel(
        calendar["fomc"], daily_idx, tickers,
        bars_before=2, bars_after=0,
    )
    factors["post_fomc_window_flag"] = window_flag_panel(
        calendar["fomc"], daily_idx, tickers,
        bars_before=-1, bars_after=3,
    )
    factors["pre_cpi_window_flag"] = window_flag_panel(
        calendar["cpi"], daily_idx, tickers,
        bars_before=1, bars_after=0,
    )
    factors["pre_nfp_window_flag"] = window_flag_panel(
        calendar["nfp"], daily_idx, tickers,
        bars_before=1, bars_after=0,
    )
    return factors
