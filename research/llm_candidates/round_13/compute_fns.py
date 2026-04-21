"""LLM-Phase Round 13 compute functions: 3 path-shape candidates
(PRD §9 LLM-10, §3 path-shape direction).

All are pattern-recognition factors that look at the SHAPE of recent
price path rather than magnitude alone. Distinct from existing
momentum (magnitude) / drawdown (single extrema) / vol (dispersion)
factors. All use .rolling() / .shift() / .cummax() for past-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def breakout_20d_persistence_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of last 63 trading days where close > prior 20d rolling
    high (§3 path-shape).

    Rationale: captures "broke out and held" pattern. A stock that has
    spent most of the last 3 months above its prior 20d high is in a
    persistent uptrend. Distinct from momentum (which measures return
    magnitude) or max_dd (single extremum). Pattern-based proxy for
    trend persistence.

    formula:
      prior_20d_high = close.shift(1).rolling(20).max()
      above = (close > prior_20d_high).astype(float)
      feat = above.rolling(63).mean()
    """
    prior_high = price_df.shift(1).rolling(20, min_periods=15).max()
    above = (price_df > prior_high).astype(float)
    feat = above.rolling(63, min_periods=45).mean()
    return _zscore_cs(feat)


def vol_compression_21_63(price_df: pd.DataFrame) -> pd.DataFrame:
    """Short-term vol / long-term vol ratio (§3 path-shape volatility
    compression).

    Rationale: when 21d vol drops well below 63d vol, the stock is in
    a "compression" or "consolidation" phase. In technical analysis
    such compression often precedes a breakout. Low compression ratio
    (close to 0.5) hypothesized to predict positive forward returns
    (breakout upside bias) — but the SIGN may flip in different regimes
    (breakdown just as likely). A prior in-sample test would be prudent.

    Distinct from Round 2's `vol_term_ratio_5_63` which uses 5d numerator
    (noisy, short). 21d is more stable and better captures multi-week
    compression.

    formula:
      vol_21 = returns.rolling(21).std()
      vol_63 = returns.rolling(63).std()
      feat = vol_21 / vol_63
      (low value → compression)
    """
    ret = price_df.pct_change()
    vol_21 = ret.rolling(21, min_periods=15).std()
    vol_63 = ret.rolling(63, min_periods=45).std()
    ratio = vol_21 / vol_63.replace(0, np.nan)
    return _zscore_cs(ratio)


def days_since_252d_high(price_df: pd.DataFrame) -> pd.DataFrame:
    """Number of trading days since last 252d rolling max was made
    (§3 path-shape, time-since-peak).

    Rationale: recency of the 52-week high is a momentum proxy. A
    stock that just made a new 52w high (days_since = 0) has recent
    strong momentum. Long time since 52w high suggests faded momentum.
    Distinct from max_dd_126d (measures distance from peak, not time
    since peak). Sign expected: negative IC — small values = recent
    peak = forward positive return.

    formula:
      rolling_argmax_pos = rolling(252).argmax()  # index of max WITHIN window
      days_since_high = (window_length - 1) - rolling_argmax_pos
      feat = days_since_high (or -days_since_high for positive correlation)
    """
    # For each date t, find the index position of the rolling window max
    # within the past 252 days. A position of 251 means the max is AT t
    # (today); a position of 0 means the max was 251 days ago.
    # Use .apply() with numpy argmax for correctness.
    window = 252
    min_p = 126

    def _last_argmax_days_ago(arr: np.ndarray) -> float:
        if len(arr) < min_p:
            return np.nan
        # position of max (0 = oldest, len-1 = newest)
        return float(len(arr) - 1 - int(np.argmax(arr)))

    feat = price_df.apply(
        lambda col: col.rolling(window, min_periods=min_p)
                       .apply(_last_argmax_days_ago, raw=True),
        axis=0,
    )
    # Invert: small days_since → strong (positive forward return);
    # so factor value = -days_since (z-scored)
    return _zscore_cs(-feat)
