"""R8 deep-mining: 3 candidates seeded from R4 SHAP interaction-heavy features.

market_vol_ratio and cross_section_dispersion_21d had high SHAP but low
permutation importance — their alpha is conditional on interactions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def mom_63d_scaled_by_market_calm(
    price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs,
) -> pd.DataFrame:
    """Momentum scaled by inverse market vol.

    market_vol_ratio = SPY vol_21d / vol_63d (from factor_generator, negated)
    calm = 1 when market_vol_ratio high (short-vol < long-vol = calm)
    factor = mom_63d × calm

    Hypothesis: momentum works better when market is calm (low realized vol).
    In volatile markets, mom signals get whipsawed.
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    mom_63d = price_df.pct_change(63)
    spy_ret = price_df["SPY"].pct_change()
    vol_21 = spy_ret.rolling(21, min_periods=10).std()
    vol_63 = spy_ret.rolling(63, min_periods=30).std()
    calm_ratio = vol_63 / vol_21.replace(0, np.nan)  # >1 when recent vol low
    calm = calm_ratio.clip(0.5, 2.0)
    factor = mom_63d.mul(calm, axis=0)
    return factor.shift(1)


def rs_dispersion_amplified_63d(
    price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs,
) -> pd.DataFrame:
    """RS amplified by cross-sectional dispersion.

    rs_vs_spy = (ret_63d - SPY_ret_63d)
    dispersion = std across symbols of 21d return
    When dispersion HIGH (stocks moving differently), RS signal is more
    meaningful. When LOW (everything moves together), RS is just noise.

    factor = rs_vs_spy × dispersion (rescaled)
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    ret_63d = price_df.pct_change(63)
    spy_ret_63d = price_df["SPY"].pct_change(63)
    rs = ret_63d.sub(spy_ret_63d, axis=0)

    # Cross-sectional dispersion of 21d returns
    ret_21d = price_df.pct_change(21)
    disp = ret_21d.std(axis=1)  # daily scalar
    disp_norm = (disp - disp.rolling(252, min_periods=60).mean()) / disp.rolling(252, min_periods=60).std().replace(0, np.nan)
    disp_scaled = disp_norm.clip(-2, 2)  # truncate tails

    factor = rs.mul(disp_scaled, axis=0)
    return factor.shift(1)


def vol_ratio_gated_drawup(
    price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs,
) -> pd.DataFrame:
    """drawup_from_252d_low gated by market vol ratio calm state.

    Stocks that recovered from 252d low during calm market periods
    (low market_vol_ratio) are more legit recoveries. During volatile
    markets, recovery signals are more often false starts.

    factor = drawup × (1 - abs(vol_ratio_z))
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    rolling_trough = price_df.rolling(252, min_periods=60).min()
    drawup = (price_df - rolling_trough) / rolling_trough

    spy_ret = price_df["SPY"].pct_change()
    vol_21 = spy_ret.rolling(21, min_periods=10).std()
    vol_63 = spy_ret.rolling(63, min_periods=30).std()
    vol_ratio = vol_21 / vol_63.replace(0, np.nan)  # >1 when recent vol elevated
    # Gate: 1 when calm (vol_ratio <= 1), 0.5 when volatile (>1.3), linear between
    gate = (2.0 - vol_ratio.clip(1.0, 2.0)).clip(0.5, 1.0)

    factor = drawup.mul(gate, axis=0)
    return factor.shift(1)
