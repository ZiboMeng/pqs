"""R13 deep-mining: cross-sectional rank-change factors.

Uses cross-sectional rank (per-date rank across symbols) as the primary
signal, then looks at how ranks change over time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rank_change_21_vs_63(price_df, vol_df=None, regime=None, **kwargs):
    """Cross-sectional rank improvement.

    rank_21 = cross-sectional rank of 21d return
    rank_63 = cross-sectional rank of 63d return
    factor = rank_21 - rank_63 (positive = recently-climbing)
    Uses rolling pct_change and .rank(axis=1) per date; shift(1) applied.
    """
    ret_21 = price_df.pct_change(21)
    ret_63 = price_df.pct_change(63)
    rank_21 = ret_21.rank(axis=1, pct=True)
    rank_63 = ret_63.rank(axis=1, pct=True)
    return (rank_21 - rank_63).shift(1)


def rank_persistence_126d(price_df, vol_df=None, regime=None, **kwargs):
    """How stable is a symbol's rank over 126 days.

    Compute daily cross-sectional rank of trailing 21d return.
    Factor = 1 - rolling_std(rank) over 126d (higher = more stable rank).
    Stable high-rank = persistent outperformer.
    """
    ret_21 = price_df.pct_change(21)
    rank = ret_21.rank(axis=1, pct=True)
    rank_std = rank.rolling(126, min_periods=40).std()
    # Only meaningful if symbol's mean rank is high; combine with mean rank
    rank_mean = rank.rolling(126, min_periods=40).mean()
    persistence = rank_mean * (1.0 - rank_std)
    return persistence.shift(1)


def rank_acceleration_21d(price_df, vol_df=None, regime=None, **kwargs):
    """How quickly a symbol's cross-sectional rank is changing.

    Compute 21d return rank each day.
    factor = rank_today - rank_21d_ago (raw change over window)
    Positive = rank climbing; negative = rank falling.
    """
    ret_21 = price_df.pct_change(21)
    rank = ret_21.rank(axis=1, pct=True)
    rank_21d_ago = rank.shift(21)
    return (rank - rank_21d_ago).shift(1)
