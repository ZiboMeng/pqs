"""LLM-Phase Round 20 compute functions: lower-collinearity candidates.

These factors deliberately emphasize conditional behavior rather than
plain endpoint momentum, to reduce overlap with the current momentum /
relative-strength family.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _masked_rolling_mean(ret_df: pd.DataFrame, mask: pd.Series, window: int, min_periods: int) -> pd.DataFrame:
    masked_ret = ret_df.mul(mask.astype(float), axis=0)
    roll_sum = masked_ret.rolling(window, min_periods=min_periods).sum()
    roll_cnt = mask.astype(float).rolling(window, min_periods=min_periods).sum()
    return roll_sum.div(roll_cnt.replace(0, np.nan), axis=0)


def downside_resilience_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Average stock return on SPY-down days over the last 63 sessions."""
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    ret = price_df.pct_change()
    spy_down = ret["SPY"].lt(0)
    feat = _masked_rolling_mean(ret, spy_down, window=63, min_periods=15)
    return _zscore_cs(feat.shift(1))


def weak_breadth_resilience_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Average stock return on weak-breadth days over the last 63 sessions."""
    ret = price_df.pct_change()
    breadth = ret.gt(0).mean(axis=1)
    weak_breadth = breadth.lt(0.4)
    feat = _masked_rolling_mean(ret, weak_breadth, window=63, min_periods=15)
    return _zscore_cs(feat.shift(1))


def down_up_beta_spread_126d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Difference between down-market beta and up-market beta to SPY."""
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    ret = price_df.pct_change()
    spy = ret["SPY"]
    down_mask = spy.lt(0)
    up_mask = spy.gt(0)
    down_std = spy.where(down_mask).rolling(126, min_periods=25).std()
    up_std = spy.where(up_mask).rolling(126, min_periods=25).std()

    down_beta = pd.DataFrame(index=ret.index, columns=ret.columns, dtype=float)
    up_beta = pd.DataFrame(index=ret.index, columns=ret.columns, dtype=float)
    for col in ret.columns:
        cov_down = ret[col].where(down_mask).rolling(126, min_periods=25).cov(spy.where(down_mask))
        cov_up = ret[col].where(up_mask).rolling(126, min_periods=25).cov(spy.where(up_mask))
        down_beta[col] = cov_down.div(down_std.pow(2).replace(0, np.nan))
        up_beta[col] = cov_up.div(up_std.pow(2).replace(0, np.nan))
    feat = down_beta - up_beta
    return _zscore_cs(feat.shift(1))


def weak_market_relative_strength_63d(price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs) -> pd.DataFrame:
    """Stock return on SPY-weak days minus its return on SPY-strong days."""
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    ret = price_df.pct_change()
    spy_ret = ret["SPY"]
    weak_mask = spy_ret.lt(spy_ret.rolling(63, min_periods=20).median())
    strong_mask = spy_ret.gt(spy_ret.rolling(63, min_periods=20).median())
    weak_mean = _masked_rolling_mean(ret, weak_mask, window=63, min_periods=15)
    strong_mean = _masked_rolling_mean(ret, strong_mask, window=63, min_periods=15)
    feat = weak_mean - strong_mean
    return _zscore_cs(feat.shift(1))
