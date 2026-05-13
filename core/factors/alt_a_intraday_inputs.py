"""Compute alt-A intraday inputs from 60m bars.

Per PRD `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md` §11
LOCKED:
  - intraday_volume_60m_zscore: 1st-regular-session 60m bar volume
    of T+1 z-scored over last 20 days
  - early_session_return_pct: 1st-regular-session 60m bar return on T+1
    (close - open) / open

Used by `core.backtest.intraday_reversal_bridge.build_intraday_reversal_signals`.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# NYSE regular session: 09:30 ET open → 16:00 ET close. 60m bars stored
# at ET local time (per BarStore convention). The "first regular session
# 60m bar" is the bar timestamped at or after 09:30 ET — practically the
# 09:00 ET bar (covers 09:30-10:00 due to 60m granularity overlap) OR
# the 10:00 ET bar depending on how BarStore aggregates. We pick by
# explicit timestamp filter.
NYSE_FIRST_REGULAR_BAR_HOUR = 9  # ET local; 9:00-10:00 bar covers opening hour


def _select_first_regular_bar(
    bars_60m: pd.DataFrame,
    target_date: pd.Timestamp,
) -> Optional[pd.Series]:
    """Find the first regular-session 60m bar for a given trading date.

    Returns the row (Series with open/high/low/close/volume) or None.
    """
    if bars_60m is None or bars_60m.empty:
        return None
    # Filter to target date (ignore time-of-day; subset by date)
    same_day = bars_60m[bars_60m.index.date == target_date.date()]
    if same_day.empty:
        return None
    # Find bars at or after 09:00 ET (regular session)
    regular = same_day[same_day.index.hour >= NYSE_FIRST_REGULAR_BAR_HOUR]
    if regular.empty:
        return None
    # First regular-session bar
    return regular.iloc[0]


def compute_alt_a_intraday_inputs(
    bars_60m_by_symbol: Dict[str, pd.DataFrame],
    daily_dates: pd.DatetimeIndex,
    rolling_window_days: int = 20,
) -> Dict[str, pd.DataFrame]:
    """Compute alt-A intraday inputs across symbol × daily-date grid.

    Parameters
    ----------
    bars_60m_by_symbol : dict[str, DataFrame]
        Per-symbol 60m bars (from BarStore.load(sym, freq="60m")).
        Each DataFrame index = pd.DatetimeIndex (ET local time).
    daily_dates : DatetimeIndex
        Daily trading-date grid (typically a subset of price_df.index).
    rolling_window_days : int
        Lookback for volume z-score (default 20 trading days).

    Returns
    -------
    {
      "intraday_volume_60m_zscore": DataFrame (dates × symbols),
      "early_session_return_pct":    DataFrame (dates × symbols),
    }

    For each (T, sym):
      - Look up the first regular-session 60m bar of T (NB: same-day
        not T+1; the bridge calls this at T expecting "T's morning",
        which IS the first-60m bar on T's date)
      - intraday_volume_60m_zscore[T, sym] = z-score of that bar's
        volume over last `rolling_window_days` first-60m volumes
      - early_session_return_pct[T, sym] = (close - open) / open of
        that bar
    """
    syms = sorted(bars_60m_by_symbol.keys())
    iv_zscore = pd.DataFrame(np.nan, index=daily_dates, columns=syms)
    er_pct = pd.DataFrame(np.nan, index=daily_dates, columns=syms)

    for sym in syms:
        bars = bars_60m_by_symbol[sym]
        if bars is None or bars.empty:
            logger.debug("%s: no 60m bars; skipping", sym)
            continue

        # Build per-date series of first-bar volume + return
        first_bar_vol: List[float] = []
        first_bar_ret: List[float] = []
        valid_dates: List[pd.Timestamp] = []

        for d in daily_dates:
            row = _select_first_regular_bar(bars, d)
            if row is None:
                continue
            try:
                open_v = float(row["open"])
                close_v = float(row["close"])
                vol_v = float(row["volume"])
            except (KeyError, TypeError, ValueError):
                continue
            if not np.isfinite(open_v) or open_v <= 0:
                continue
            first_bar_vol.append(vol_v)
            first_bar_ret.append((close_v - open_v) / open_v)
            valid_dates.append(d)

        if not valid_dates:
            continue

        vol_series = pd.Series(first_bar_vol, index=valid_dates)
        ret_series = pd.Series(first_bar_ret, index=valid_dates)

        # Rolling 20d z-score of volume
        avg = vol_series.rolling(rolling_window_days).mean()
        std = vol_series.rolling(rolling_window_days).std().replace(0, np.nan)
        z = (vol_series - avg) / std

        # Reindex to full daily_dates (missing values stay NaN)
        iv_zscore[sym] = z.reindex(daily_dates)
        er_pct[sym] = ret_series.reindex(daily_dates)

    return {
        "intraday_volume_60m_zscore": iv_zscore,
        "early_session_return_pct": er_pct,
    }


def report_coverage(
    bars_60m_by_symbol: Dict[str, pd.DataFrame],
    daily_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Per-symbol coverage report: % of daily_dates with a valid
    first-regular-session 60m bar.

    Useful pre-Track-A walking sanity check (PRD §4.1 requires ≥95%).
    """
    syms = sorted(bars_60m_by_symbol.keys())
    rows = []
    for sym in syms:
        bars = bars_60m_by_symbol[sym]
        n_total = len(daily_dates)
        n_valid = 0
        if bars is not None and not bars.empty:
            for d in daily_dates:
                if _select_first_regular_bar(bars, d) is not None:
                    n_valid += 1
        coverage_pct = (n_valid / n_total * 100) if n_total else 0
        rows.append({
            "symbol": sym,
            "n_valid": n_valid,
            "n_total": n_total,
            "coverage_pct": coverage_pct,
            "meets_95_threshold": coverage_pct >= 95.0,
        })
    return pd.DataFrame(rows).set_index("symbol")
