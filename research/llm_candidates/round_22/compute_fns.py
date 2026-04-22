"""R7 (deep mining) — 3 candidate compute_fns seeded from R5 interaction findings.

Each function takes (price_df, vol_df=None, regime=None, **kwargs) and
returns a date × symbol DataFrame of factor values (will be z-scored
by funnel IC screen).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def spy_trend_gated_rs_vs_qqq_63d(
    price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs,
) -> pd.DataFrame:
    """Regime-gated cross-sectional RS.

    rs_vs_qqq_63d = (close / close.shift(63)) - (QQQ / QQQ.shift(63))
    spy_trend_200d = 1 if SPY > SMA(SPY, 200), else 0 (binary gate)
    factor = rs_vs_qqq_63d * spy_trend_200d

    Hypothesis: RS-vs-QQQ predicts forward returns ONLY in SPY uptrend;
    in downtrend RS leaders underperform (market beta dominates). Gating
    avoids using RS signal when it has no predictive power.

    R5 finding: pair IC +0.0704, incremental +0.0458 vs best parent.
    """
    if "QQQ" not in price_df.columns or "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    qqq_ret_63d = (price_df["QQQ"] / price_df["QQQ"].shift(63)) - 1.0
    stock_ret_63d = (price_df / price_df.shift(63)) - 1.0
    rs = stock_ret_63d.sub(qqq_ret_63d, axis=0)
    spy_sma200 = price_df["SPY"].rolling(200, min_periods=100).mean()
    spy_trend = (price_df["SPY"] > spy_sma200).astype(float)
    factor = rs.mul(spy_trend, axis=0)
    # No lookahead: shift(1) is a research convention; the scripts already
    # apply it during IC compute
    return factor.shift(1)


def spy_trend_gated_mom_63d(
    price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs,
) -> pd.DataFrame:
    """Regime-gated momentum.

    mom_63d = close / close.shift(63) - 1
    gated by spy_trend_200d binary.

    Hypothesis: momentum reward/punishment flips in bear regimes.
    Gating preserves signal in uptrend, zeros in downtrend.

    R5 finding: pair IC +0.0704, incremental +0.0458.
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    mom = (price_df / price_df.shift(63)) - 1.0
    spy_sma200 = price_df["SPY"].rolling(200, min_periods=100).mean()
    spy_trend = (price_df["SPY"] > spy_sma200).astype(float)
    factor = mom.mul(spy_trend, axis=0)
    return factor.shift(1)


def max_dd_drawup_composite(
    price_df: pd.DataFrame, vol_df=None, regime=None, **kwargs,
) -> pd.DataFrame:
    """Path-shape composite: max drawdown × drawup-from-252d-low.

    max_dd_126d = min((close - cummax(close, 126)) / cummax(close, 126))
    drawup_from_252d_low = (close - rolling_min(close, 252)) / rolling_min(close, 252)
    factor = max_dd_126d * drawup_from_252d_low

    Hypothesis: a stock that recovered (high drawup) after a deep
    drawdown (large |max_dd|) is a "survivor" with post-stress quality
    signal. Product of the two path-shape factors captures this regime.

    R5 finding: pair IC +0.0966, incremental +0.0102 (small but positive).
    """
    # max drawdown over trailing 126 days (rolling peak drawdown)
    rolling_peak = price_df.rolling(126, min_periods=40).max()
    drawdown = (price_df - rolling_peak) / rolling_peak
    max_dd = drawdown.rolling(126, min_periods=40).min()

    # drawup from trailing 252d low
    rolling_trough = price_df.rolling(252, min_periods=60).min()
    drawup = (price_df - rolling_trough) / rolling_trough

    factor = max_dd * drawup
    return factor.shift(1)
