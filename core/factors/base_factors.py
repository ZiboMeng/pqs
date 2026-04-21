"""Shared factor computation helpers (Round 6 Topic E, 2026-04-20).

Before this module, MultiFactorStrategy and factor_generator each
had their own inline implementation of essentially-the-same factor
(e.g. MultiFactor's inline `low_vol` vs factor_generator's `vol_63d`).
The two were documented in `RESEARCH_TO_PRODUCTION_MAP` as "shadowed"
— economic intent aligned but implementations could drift silently.

This module exposes the canonical implementation used by BOTH sides.
After migration, there is ONE source of truth per factor; the
shadow map entry can be removed.

Design rule: every function here is a pure function of its inputs
(no config, no side effects). Keeps it callable from both research
and execution contexts without leaking behavior.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def low_vol_factor(
    price_df: pd.DataFrame,
    lookback:    int = 63,
    min_periods: int = 20,
) -> pd.DataFrame:
    """Negative rolling std of daily returns — "low-vol" factor.

    Higher output = lower volatility (sort descending for low-vol picks).
    Note: NOT annualized. Annualization is a monotonic scalar that
    cancels after cross-sectional z-scoring, so including it has no
    downstream effect on strategies that z-score before ranking.

    Parameters
    ----------
    price_df    : close prices, index=date, columns=symbols
    lookback    : rolling window in business days (default 63, ~3 months)
    min_periods : min observations for a valid value (default 20).
                  Smaller warmup than `lookback` lets the factor fill in
                  earlier in the series.
    """
    daily_ret = price_df.pct_change()
    vol = daily_ret.rolling(lookback, min_periods=min_periods).std()
    return -vol


def rel_strength_factor(
    price_df:      pd.DataFrame,
    benchmark_col: str = "SPY",
    lookback:      int = 63,
) -> pd.DataFrame:
    """Symbol return minus benchmark return over `lookback` days.

    Positive output = outperformer; negative = underperformer. Used
    by MultiFactorStrategy's `rel_strength` and factor_generator's
    `rs_vs_spy_<N>d` family.

    Parameters
    ----------
    price_df      : close prices, index=date, columns=symbols (must
                    include `benchmark_col`)
    benchmark_col : column to use as benchmark (default SPY)
    lookback      : return lookback in business days (default 63)

    Returns
    -------
    DataFrame index=date, columns=symbols. Empty if benchmark_col
    missing from price_df.columns.
    """
    if benchmark_col not in price_df.columns:
        return pd.DataFrame(
            np.nan,
            index=price_df.index,
            columns=price_df.columns,
        )
    bench = price_df[benchmark_col]
    sym_ret = price_df.pct_change(lookback)
    bench_ret = bench.pct_change(lookback)
    return sym_ret.sub(bench_ret, axis=0)
