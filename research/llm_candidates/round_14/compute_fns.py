"""LLM-Phase Round 14 compute functions: 3 cross-sectional candidates
(PRD §9 LLM-11, §3 universe-aware / cross-sectional direction).

Cross-sectional factors look at a stock's POSITION relative to the
universe panel on each date, not its absolute price/return history.
Existing research factors in this family: `xsection_rank_21d/63d`,
`cross_section_dispersion_21d`, `advance_ratio_10d`. These 3 new
candidates extend the family with PATH-based cross-sectional features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def rank_change_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Change in cross-sectional 63-day momentum rank over 21 days.

    Rationale: `xsection_rank_63d` captures CURRENT rank; this captures
    RANK MOMENTUM — how much a stock has moved up/down in the
    cross-sectional ranking over the past 21 days. Stocks rising in
    rank may continue to rise (rank momentum); stocks falling may
    continue to fall. Distinct from `rank_momentum_change` in research
    registry (which uses a different construction — delta of absolute
    rank not normalized by time).

    formula:
      mom_63 = close.pct_change(63)
      rank_today = mom_63.rank(axis=1, pct=True)    # CS rank 0-1
      rank_21d_ago = rank_today.shift(21)
      feat = rank_today - rank_21d_ago   # ∈ [-1, +1]
      cross-sectional z-score per date (past-only via .shift)
    """
    mom = price_df.pct_change(63)
    rank_today = mom.rank(axis=1, pct=True)
    rank_21d_ago = rank_today.shift(21)
    feat = rank_today - rank_21d_ago
    return _zscore_cs(feat)


def above_median_persistence_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Fraction of last 63 trading days where stock's 21-day return
    exceeded the cross-sectional median 21-day return.

    Rationale: captures "persistent above-median performer" pattern.
    Distinct from momentum (magnitude) and xsection_rank (single snapshot
    of relative position). This is TIME-WEIGHTED cross-sectional
    persistence — a stock consistently in the top half is a durable
    outperformer.

    formula:
      ret_21 = close.pct_change(21)
      median = ret_21.median(axis=1)
      above = (ret_21.sub(median, axis=0) > 0).astype(float)
      feat = above.rolling(63).mean()
      cross-sectional z-score per date
    """
    ret_21 = price_df.pct_change(21)
    median = ret_21.median(axis=1)
    above = ret_21.sub(median, axis=0).gt(0).astype(float)
    feat = above.rolling(63, min_periods=45).mean()
    return _zscore_cs(feat)


def dispersion_adjusted_mom_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """63-day momentum divided by cross-sectional dispersion (standard
    deviation of returns across symbols, 21d rolling).

    Rationale: normalize a stock's momentum by the panel's overall
    dispersion. In high-dispersion regimes (e.g., post-crash), individual
    momentum signals are noisier; normalization dampens them. In
    low-dispersion regimes, momentum signals have higher signal-to-noise.
    Distinct from `risk_adj_mom_63d` (which uses single-stock time-series
    vol, not panel dispersion).

    formula:
      mom_63 = close.pct_change(63)
      daily_ret = close.pct_change()
      panel_disp = daily_ret.rolling(21).std().std(axis=1)  # CS std of vols
      feat = mom_63.div(panel_disp, axis=0)
      cross-sectional z-score per date
    """
    mom = price_df.pct_change(63)
    ret = price_df.pct_change()
    panel_vol_series = ret.rolling(21, min_periods=15).std()
    # Panel dispersion = std of per-symbol vols across symbols per date
    panel_disp = panel_vol_series.std(axis=1).replace(0, np.nan)
    feat = mom.div(panel_disp, axis=0)
    return _zscore_cs(feat)
