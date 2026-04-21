"""LLM-Phase Round 01 compute functions for 5 candidate factors.

Each function takes `price_df` (columns=symbols, index=dates, values=close)
and returns a DataFrame of the same shape with factor values. All lags use
explicit `.shift()` / `.rolling()` to satisfy the leakage heuristic and
guarantee past-only data access.

Authored by LLM acting as candidate generator (PRD §2.1). Final
keep/reject decision is NOT made here — goes through the standard
funnel in `core/factors/llm_candidate.py::run_funnel`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score per row (date). Used to normalize factor
    values across symbols for consistent sign/scale."""
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def rs_vs_qqq_63d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Relative strength vs QQQ over 63 days (§3 benchmark-relative).

    Rationale: existing `rs_vs_spy_*` factors benchmark against SPY.
    Since QQQ is our second benchmark (per QQQ outperformance rule),
    RS vs QQQ may expose different alpha — especially for stocks
    outperforming even the tech-concentrated benchmark.

    formula: pct_change(63) - qqq_pct_change(63)
    fallback: if QQQ not in columns, use cross-sectional mean return.
    """
    ret = price_df.pct_change(63)
    if "QQQ" in price_df.columns:
        bench_ret = ret["QQQ"]
    else:
        bench_ret = ret.mean(axis=1)
    excess = ret.sub(bench_ret, axis=0)
    return _zscore_cs(excess)


def vol_term_ratio_5_63(price_df: pd.DataFrame) -> pd.DataFrame:
    """Short-term vol (5d) / long-term vol (63d) ratio (§3 non-classical
    variant).

    Rationale: vol_regime measures vol vs historical long-run; this
    measures SHORT vs LONG within a name. When short >> long, regime
    is changing — potential directional signal via mean reversion or
    trend acceleration.

    formula: returns.rolling(5).std() / returns.rolling(63).std()
    higher values → more short-term vol → potential overreaction
    """
    ret = price_df.pct_change()
    vol_s = ret.rolling(5, min_periods=5).std()
    vol_l = ret.rolling(63, min_periods=30).std()
    ratio = vol_s / vol_l.replace(0, np.nan)
    return _zscore_cs(ratio)


def drawup_from_252d_low(price_df: pd.DataFrame) -> pd.DataFrame:
    """Distance from 252-day rolling low (§3 path-shape).

    Rationale: existing `max_dd_126d` measures drawdown from rolling
    HIGH; this measures gain from rolling LOW. Different info content:
    stocks recovering strongly from annual lows have recency momentum
    that may persist.

    formula: (close - close.rolling(252).min()) / close.rolling(252).min()
    """
    rolling_min = price_df.rolling(252, min_periods=126).min()
    drawup = (price_df - rolling_min) / rolling_min.replace(0, np.nan)
    return _zscore_cs(drawup)


def momentum_quality_interaction(price_df: pd.DataFrame) -> pd.DataFrame:
    """63-day momentum × inverse-vol-rank (§3 factor interaction).

    Rationale: captures "high-quality" momentum — high return with low
    realized vol. Existing factors are additive in the composite; this
    is a multiplicative interaction term.

    formula: mom_63d * (1 - rank_pct(vol_63d))
    higher value → strong momentum AND low vol
    """
    ret = price_df.pct_change()
    mom = price_df.pct_change(63)
    vol = ret.rolling(63, min_periods=30).std()
    vol_rank = vol.rank(axis=1, pct=True)
    interaction = mom.multiply(1.0 - vol_rank)
    return _zscore_cs(interaction)


def path_accel_21d(price_df: pd.DataFrame) -> pd.DataFrame:
    """Return acceleration: short-window mean return vs long-window mean
    return (§3 path-shape / multi-horizon).

    Rationale: momentum factors measure return magnitude; this measures
    whether recent return rate has SPED UP vs longer baseline. Captures
    new-catalyst-driven acceleration.

    formula: pct_change(5).rolling(21).mean() - pct_change(21).rolling(63).mean()
    positive → recent 21d of 5d returns outpacing prior 63d of 21d returns
    """
    short_ret = price_df.pct_change(5).rolling(21, min_periods=15).mean()
    long_ret = price_df.pct_change(21).rolling(63, min_periods=30).mean()
    accel = short_ret - long_ret
    return _zscore_cs(accel)
