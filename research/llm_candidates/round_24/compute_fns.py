"""R9 deep-mining: cross-sectional × cross-sectional interactions."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rs_vs_spy_risk_adj_63d(price_df, vol_df=None, regime=None, **kwargs):
    """Risk-adjusted relative strength: rs_vs_spy_63d / vol_63d.

    Pure cross-sectional factor: each symbol's RS divided by its own
    volatility. Penalizes volatile outperformers, rewards steady ones.
    """
    if "SPY" not in price_df.columns:
        return pd.DataFrame(index=price_df.index, columns=price_df.columns, dtype=float)
    ret_63d = price_df.pct_change(63)
    spy_ret_63d = price_df["SPY"].pct_change(63)
    rs = ret_63d.sub(spy_ret_63d, axis=0)
    daily_ret = price_df.pct_change()
    vol_63 = daily_ret.rolling(63, min_periods=30).std()
    vol_63 = vol_63.replace(0, np.nan)
    factor = rs / vol_63
    return factor.shift(1)


def mom_minus_reversal_21d(price_df, vol_df=None, regime=None, **kwargs):
    """Momentum (21d) minus reversal (21d, short-term).

    mom_21d ≈ close / close.shift(21) - 1
    reversal_21d ≈ -mom_21d (often used as mean-reversion in short horizon)
    factor = mom_21d - reversal_21d = 2 * mom_21d (trivial degen)

    Better interpretation: mom_63d (medium trend) - reversal_21d (recent flip):
    identify stocks with sustained 63d uptrend BUT recent 21d pullback
    — classic "buy the dip" signal.

    factor = mom_63d - reversal_21d = mom_63d + mom_21d (post-flip)
    Since reversal convention is "-mom_21d", formula simplifies:
    factor = mom_63d + mom_21d (weighted trend + momentum alignment)
    """
    mom_63 = price_df.pct_change(63)
    mom_21 = price_df.pct_change(21)
    # Stocks with positive 63d trend AND recent 21d dip (negative 21d ret)
    # would have mom_63 - mom_21 = (large positive trend) - (small negative recent)
    # = small positive; but we want the DIVERGENCE signal
    divergence = mom_63 - mom_21  # 63d trend minus recent 21d
    return divergence.shift(1)


def quality_survivor_63d(price_df, vol_df=None, regime=None, **kwargs):
    """Rolling Sharpe × drawup combination.

    Survivor thesis: high rolling-sharpe_126 × high drawup_from_252d_low
    = stock that has been quality (high Sharpe) AND recovered from a
    trough → "post-stress quality survivor".
    """
    daily_ret = price_df.pct_change()
    mean_126 = daily_ret.rolling(126, min_periods=40).mean()
    std_126 = daily_ret.rolling(126, min_periods=40).std().replace(0, np.nan)
    sharpe_126 = mean_126 / std_126

    rolling_low_252 = price_df.rolling(252, min_periods=60).min()
    drawup = (price_df - rolling_low_252) / rolling_low_252

    factor = sharpe_126 * drawup
    return factor.shift(1)
