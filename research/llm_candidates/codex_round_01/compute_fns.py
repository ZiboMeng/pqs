"""LLM-Phase Round 19 compute functions: external-LLM handoff pack.

These candidates are designed to be immediately usable by Claude's
existing funnel:
  - close-only inputs so `llm_factor_propose.py` can execute them
  - explicit past-only construction via `.shift(1)`
  - daily / expanded-universe focus to fit current research constraints
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def trend_efficiency_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """63d net return divided by 63d path length.

    Measures how "clean" the trend path is: same endpoint return but
    lower intermediate chop should rank higher. Cross-sectional z-score
    per date, lagged by 1 bar to stay past-only.
    """
    close = price_df.astype(float)
    daily_ret = close.pct_change()
    net_ret = close.pct_change(63)
    path_len = daily_ret.abs().rolling(63, min_periods=40).sum().replace(0, np.nan)
    feat = net_ret.div(path_len)
    return _zscore_cs(feat.shift(1))


def rs_qqq_corr_adjusted_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """63d relative strength vs QQQ down-weighted by 63d correlation to QQQ.

    Idea: prefer stocks that outperform QQQ *without* simply being a
    high-correlation proxy for QQQ itself.
    """
    close = price_df.astype(float)
    if "QQQ" not in close.columns:
        return pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    daily_ret = close.pct_change()
    qqq_ret = daily_ret["QQQ"]
    rs_63 = close.pct_change(63).sub(close["QQQ"].pct_change(63), axis=0)
    corr_63 = daily_ret.rolling(63, min_periods=40).corr(qqq_ret).clip(-1.0, 1.0)
    feat = rs_63 * (1.0 - corr_63)
    return _zscore_cs(feat.shift(1))


def recovery_speed_126d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Recovery speed from the rolling 126d low.

    Stocks equally far above their 126d low can differ in HOW FAST they
    got there. Faster recoveries may indicate stronger leadership.
    """
    close = price_df.astype(float)
    roll_low = close.rolling(126, min_periods=63).min()
    drawup = close.div(roll_low) - 1.0

    is_new_low = close.eq(roll_low)
    # Count days since the most recent rolling-window low per symbol.
    days_since_low = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for col in close.columns:
        marker = is_new_low[col].fillna(False)
        counter = (~marker).astype(float).groupby(marker.cumsum()).cumsum() + 1.0
        days_since_low[col] = counter
    feat = drawup.div(days_since_low.replace(0, np.nan))
    return _zscore_cs(feat.shift(1))


def rank_stability_21d_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Short-term stability of 63d momentum rank.

    A stock whose 63d momentum rank stays persistently strong over the
    last month may be more robust than a one-day rank spike.
    """
    close = price_df.astype(float)
    mom_63 = close.pct_change(63)
    rank_63 = mom_63.rank(axis=1, pct=True)
    rolling_rank_mean = rank_63.rolling(21, min_periods=10).mean()
    rolling_rank_std = rank_63.rolling(21, min_periods=10).std().replace(0, np.nan)
    feat = rolling_rank_mean.div(rolling_rank_std)
    return _zscore_cs(feat.shift(1))
