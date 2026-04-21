"""LLM-Phase Round 02 compute functions for 3 intraday candidate factors.

Each function takes `price_df` (daily close, columns=symbols, index=dates)
and loads 60m RTH bars internally from `data/intraday/60m/<SYMBOL>.parquet`.
Per-day intraday features are aggregated, then a 21-day rolling mean is
returned, aligned to `price_df.index` (daily dates).

RTH bars are 10:00-16:00 inclusive (7 hourly bars covering 9:30-16:00 ET
trading session; pre/post-market bars excluded). See Round 5 for the
existing intraday family (`realized_vol_60m_21d`, `intraday_vol_ratio_21d`,
`intraday_autocorr_21d`) — these Round 02 candidates target WITHIN-DAY
PATH SHAPE and time-of-day drift, which the existing family does not
capture.

Authored by LLM acting as candidate generator (PRD §2.1). Final verdict
goes through the standard funnel; LLM is never final judge (§2.2).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# RTH 60m bars on 10:00, 11:00, ..., 16:00 ET (7 bars per day)
_RTH_START_HOUR = 10
_RTH_END_HOUR = 16
_INTRADAY_ROOT = Path("data/intraday/60m")


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score per row (date)."""
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


@lru_cache(maxsize=64)
def _load_rth_60m(symbol: str) -> pd.DataFrame:
    """Load a symbol's 60m bars, filter to RTH (10:00-16:00 inclusive).
    Cached to avoid re-reading the same parquet across candidates."""
    p = _INTRADAY_ROOT / f"{symbol}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    hour = df.index.hour
    return df[(hour >= _RTH_START_HOUR) & (hour <= _RTH_END_HOUR)]


def _per_symbol_daily_feature(price_df: pd.DataFrame, feature_fn) -> pd.DataFrame:
    """Apply feature_fn(rth_df) -> Series(indexed by date) for each symbol
    in price_df; assemble into a DataFrame aligned to price_df.index."""
    out = {}
    for sym in price_df.columns:
        rth = _load_rth_60m(sym)
        if rth.empty:
            continue
        # Group by date, apply feature_fn per day → returns one scalar per day
        daily_feat = feature_fn(rth)
        if daily_feat is None or daily_feat.empty:
            continue
        # Align index to price_df's date index
        daily_feat.index = pd.DatetimeIndex([pd.Timestamp(d) for d in daily_feat.index])
        out[sym] = daily_feat
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).sort_index()
    df = df.reindex(price_df.index)
    return df


def first_last_bar_diff_21d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Afternoon-vs-morning drift: (last RTH 60m bar return) − (first RTH
    60m bar return), rolling 21d mean per symbol (§3 path-shape / intraday).

    Rationale: morning reflects overnight information absorption; last
    hour reflects institutional re-balancing / MOC flow. A positive diff
    means "afternoon stronger than morning" — a proxy for late-day
    accumulation. Sign and magnitude differ from close-to-close mom.

    feature: bar_close / bar_open - 1 for first and last RTH bars;
             diff = last_bar_ret - first_bar_ret; rolling(21).mean()
    """
    def feat(rth_df: pd.DataFrame) -> pd.Series:
        grouped = rth_df.groupby(rth_df.index.date)
        per_day = []
        dates = []
        for day, sub in grouped:
            if len(sub) < 2:
                continue
            first_ret = sub["close"].iloc[0] / sub["open"].iloc[0] - 1
            last_ret = sub["close"].iloc[-1] / sub["open"].iloc[-1] - 1
            per_day.append(last_ret - first_ret)
            dates.append(day)
        s = pd.Series(per_day, index=pd.DatetimeIndex(dates))
        return s.rolling(21, min_periods=15).mean()

    raw = _per_symbol_daily_feature(price_df, feat)
    return _zscore_cs(raw)


def intraday_cumret_skew_21d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Within-day cumulative return path skewness, rolling 21d mean
    (§3 path-shape / intraday).

    Rationale: captures asymmetric intraday drift. Positive skew → day's
    cumulative return path has bursts upward late; negative → drifts
    lower then recovers. Distinct from realized_vol (magnitude only)
    and intraday_autocorr (serial correlation).

    feature: intra-day bar-to-bar cumret; scipy-style skewness of the
             7-point RTH path; rolling(21).mean()
    """
    def feat(rth_df: pd.DataFrame) -> pd.Series:
        grouped = rth_df.groupby(rth_df.index.date)
        per_day = []
        dates = []
        for day, sub in grouped:
            if len(sub) < 4:
                continue
            # Bar-to-bar returns within day
            rets = sub["close"].pct_change().dropna().values
            if len(rets) < 3:
                continue
            # Cumulative return path within the day
            cum = np.cumsum(rets)
            mu = np.mean(cum)
            sd = np.std(cum, ddof=0)
            if sd < 1e-10:
                continue
            # Skewness of the cum-return path (not of returns themselves)
            skew = np.mean(((cum - mu) / sd) ** 3)
            per_day.append(skew)
            dates.append(day)
        s = pd.Series(per_day, index=pd.DatetimeIndex(dates))
        return s.rolling(21, min_periods=15).mean()

    raw = _per_symbol_daily_feature(price_df, feat)
    return _zscore_cs(raw)


def late_day_vol_share_21d(price_df: pd.DataFrame) -> pd.DataFrame:
    """End-of-day volatility share: last 2 RTH 60m bars' return stdev
    divided by full-day RTH stdev, rolling 21d mean (§3 intraday).

    Rationale: high late-day vol share suggests news clustering into
    the close (information-driven); low share suggests bleed-in,
    morning-centric price discovery. Complementary to
    realized_vol_60m_21d (full-day magnitude).

    feature: late = std(bars[-2:] returns); full = std(all RTH bar
             returns); share = late / full; rolling(21).mean()
    """
    def feat(rth_df: pd.DataFrame) -> pd.Series:
        grouped = rth_df.groupby(rth_df.index.date)
        per_day = []
        dates = []
        for day, sub in grouped:
            if len(sub) < 5:
                continue
            rets = sub["close"].pct_change().dropna().values
            if len(rets) < 4:
                continue
            full = np.std(rets, ddof=0)
            late = np.std(rets[-2:], ddof=0)
            if full < 1e-10:
                continue
            per_day.append(late / full)
            dates.append(day)
        s = pd.Series(per_day, index=pd.DatetimeIndex(dates))
        return s.rolling(21, min_periods=15).mean()

    raw = _per_symbol_daily_feature(price_df, feat)
    return _zscore_cs(raw)
