"""LLM-Phase Round 18 compute functions: 3 calendar / event-proxy
candidates (PRD §9 LLM-9, §3 event direction).

Without access to real earnings / Fed / index-rebalance date data, we
proxy event effects via calendar patterns: day-of-week biases and
intra-month position effects. Research expectation: large-cap ETF/Mag7
universe is highly efficient, so calendar anomalies likely weak or
absent. The exercise completes menu coverage and provides another
data point for R30 blocker report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _calendar_filtered_rolling_mean(
    price_df: pd.DataFrame,
    mask: pd.Series,
    window: int = 63,
) -> pd.DataFrame:
    """Compute per-symbol rolling window mean of returns, but only over
    dates where `mask==True`. Returns DataFrame same shape as price_df.

    This is the core primitive for calendar-effect factors: return value
    at date t is the rolling mean of past returns at dates matching the
    mask condition.
    """
    ret = price_df.pct_change()
    # Only keep returns on masked dates; zero out others but preserve index
    masked_ret = ret.multiply(mask, axis=0)
    # Rolling sum of returns / rolling sum of mask (count of matching dates)
    roll_sum = masked_ret.rolling(window, min_periods=10).sum()
    roll_count = mask.rolling(window, min_periods=10).sum()
    return roll_sum.div(roll_count.replace(0, np.nan), axis=0)


def monday_effect_mean_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Rolling 63-day mean return on Mondays (§3 event/calendar).

    Hypothesis: "Monday effect" — Monday returns have historical
    directional bias (often negative post-weekend info). Tests whether
    per-symbol Monday drift predicts future returns. Very unlikely to
    have strong IC in a Mag7-heavy ETF universe (too efficient).

    formula:
      mask = (index.dayofweek == 0)
      ret = close.pct_change()
      feat = rolling_mean(ret where mask, window=63)
    """
    mask = pd.Series(
        (price_df.index.dayofweek == 0).astype(float),
        index=price_df.index,
    )
    feat = _calendar_filtered_rolling_mean(price_df, mask, window=63)
    return _zscore_cs(feat)


def _last_n_of_month_mask(index: pd.DatetimeIndex, n: int = 5) -> pd.Series:
    """Mark the last N trading days of each calendar month as 1.0.

    Groups by (year, month); sorts dates within group; marks the last
    n positions. Past-only — mask at date t depends only on t's month
    and its position within that month (requires seeing ALL days of the
    month, which is fine since we only use this to compute rolling means
    of PAST returns).
    """
    mask = pd.Series(0.0, index=index)
    for _, group in index.to_series().groupby([index.year, index.month]):
        sorted_dates = sorted(group.index)
        for d in sorted_dates[-n:]:
            mask.loc[d] = 1.0
    return mask


def monthend_last5d_mean_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Rolling 63-day mean return on the last 5 trading days of each
    month (§3 event/calendar).

    Hypothesis: month-end institutional flows (rebalancing, window
    dressing) create directional drift in the last week. Rolling 63d
    mean captures per-symbol sensitivity to month-end pattern.

    formula:
      mask = (date in last 5 trading days of its month)
      ret = close.pct_change()
      feat = rolling_mean(ret where mask, window=63)
    """
    mask = _last_n_of_month_mask(price_df.index, n=5)
    feat = _calendar_filtered_rolling_mean(price_df, mask, window=63)
    return _zscore_cs(feat)


def _first_n_of_month_mask(index: pd.DatetimeIndex, n: int = 5) -> pd.Series:
    """Mark the first N trading days of each calendar month as 1.0."""
    mask = pd.Series(0.0, index=index)
    for _, group in index.to_series().groupby([index.year, index.month]):
        sorted_dates = sorted(group.index)
        for d in sorted_dates[:n]:
            mask.loc[d] = 1.0
    return mask


def monthstart_first5d_mean_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Rolling 63-day mean return on the first 5 trading days of each
    month (§3 event/calendar).

    Hypothesis: "turn-of-month effect" — positive inflows concentrated
    in first week (401k contributions, fund inflows). Counterpart to
    monthend_last5d: this captures the START-of-month pattern. Sign
    may differ from month-end.

    formula:
      mask = (date in first 5 trading days of its month)
      ret = close.pct_change()
      feat = rolling_mean(ret where mask, window=63)
    """
    mask = _first_n_of_month_mask(price_df.index, n=5)
    feat = _calendar_filtered_rolling_mean(price_df, mask, window=63)
    return _zscore_cs(feat)
