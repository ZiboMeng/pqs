"""Compute functions for feat_v1_round_01 candidates (ralph-loop R24).

Per PRD §2.2, LLM funnel requires compute_fn to advance past shape /
leakage-only checks into IC screening. R24 implements the compute_fn
for the R18-R22 autonomous finding so it becomes funnel-reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def overnight_reversal_quality_gated_1d(
    price_df: pd.DataFrame,
    vol_df=None,
    regime=None,
    **kwargs,
) -> pd.DataFrame:
    """Quality-gated overnight reversal (R18-R22 loop-generated lead).

    factor[t, symbol] = overnight_gap[t] * rolling_sharpe_126d[t]

    where:
      overnight_gap[t]      = open[t] / close[t-1] - 1
      rolling_sharpe_126d[t] = (126d mean daily return) / (126d std daily return) * sqrt(252)

    Sign convention: negative IC at h=1 forward return (reversal). Raw
    output returned; caller multiplies by -1 for signal-ready direction.

    Required kwargs:
        open_df: pd.DataFrame aligned to price_df — open prices

    Returns
    -------
    DataFrame aligned to price_df. NaN for (a) first bar (no prior close),
    (b) first ~63 bars (min_periods warmup for rolling_sharpe).
    """
    open_df = kwargs.get("open_df")
    if open_df is None:
        # Graceful NaN panel — matches other compute_fns that require
        # inputs not supplied by funnel CLI
        return pd.DataFrame(
            np.nan, index=price_df.index, columns=price_df.columns,
        )

    # 1. Overnight gap
    prev_close = price_df.shift(1)
    overnight_gap = open_df.reindex_like(price_df) / prev_close - 1.0

    # 2. Rolling 126d annualized Sharpe on daily close-to-close returns
    daily_ret = price_df.pct_change()
    roll_mean = daily_ret.rolling(126, min_periods=63).mean() * 252
    roll_std = daily_ret.rolling(126, min_periods=63).std() * np.sqrt(252)
    roll_sharpe = roll_mean / roll_std.replace(0, np.nan)

    # 3. Product
    return overnight_gap * roll_sharpe
