"""R12 deep-mining: multi-horizon composite factors.

Blending different lookback horizons to capture persistence at multiple
time scales.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def mom_blend_5_21_63_252(price_df, vol_df=None, regime=None, **kwargs):
    """Equal-weighted z-scored momentum across 4 horizons.

    Combines 5d, 21d, 63d, 252d momentum after cross-sectional z-score
    of each; average. Rewards persistent outperformers across time scales.
    Uses rolling pct_change with shift(1) for no lookahead.
    """
    horizons = [5, 21, 63, 252]
    z_sum = None
    n = 0
    for h in horizons:
        mom_h = price_df.pct_change(h)
        z = _zscore_cs(mom_h)
        z_sum = z if z_sum is None else z_sum + z
        n += 1
    blended = z_sum / n
    return blended.shift(1)


def sharpe_blend_21_63_126(price_df, vol_df=None, regime=None, **kwargs):
    """Rolling-Sharpe blend across 3 horizons (21/63/126).

    Each horizon's rolling Sharpe → cross-sectional z-score → average.
    Captures quality across time scales.
    """
    horizons = [21, 63, 126]
    daily_ret = price_df.pct_change()
    z_sum = None
    n = 0
    for h in horizons:
        mean_h = daily_ret.rolling(h, min_periods=max(10, h // 3)).mean()
        std_h = daily_ret.rolling(h, min_periods=max(10, h // 3)).std().replace(0, np.nan)
        sharpe = mean_h / std_h
        z = _zscore_cs(sharpe)
        z_sum = z if z_sum is None else z_sum + z
        n += 1
    blended = z_sum / n
    return blended.shift(1)


def mom_accel_5_21_63(price_df, vol_df=None, regime=None, **kwargs):
    """Momentum acceleration: recent > medium > long.

    Positive when short-horizon momentum > medium > long (accelerating uptrend).
    factor_raw = z(mom_5) - z(mom_21) + z(mom_21) - z(mom_63) = z(mom_5) - z(mom_63)
    Simplifies to: short momentum rank MINUS long momentum rank.
    """
    mom_5 = price_df.pct_change(5)
    mom_21 = price_df.pct_change(21)
    mom_63 = price_df.pct_change(63)
    z5 = _zscore_cs(mom_5)
    z21 = _zscore_cs(mom_21)
    z63 = _zscore_cs(mom_63)
    # Accel = (z5 - z21) + (z21 - z63) = z5 - z63 (but weight intermediate)
    # Use weighted: recent positive, long negative
    factor = 2 * z5 + z21 - 3 * z63
    return factor.shift(1)
