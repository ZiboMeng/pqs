"""Shared relative / position helpers (PRD 20260423 Step 1, Round 3).

Canonical primitives for the Relative / Position factor family:
  - dist_from_rolling_max(price_df, window)  # 52w-high-style
  - relative_return(price_df, benchmark_col, lookback)

Design rule (inherited): pure function of inputs, no side effects.
Windows and sign conventions are raw and documented per-function.
"""

from __future__ import annotations

import pandas as pd

from core.factors.base_returns import simple_return


def dist_from_rolling_max(
    price_df: pd.DataFrame,
    window: int = 252,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Distance from rolling max: `close / max(close, window) - 1`.

    Sign convention: ≤ 0 everywhere (current close can't exceed its
    own rolling max). Value of 0 means currently at the rolling high.

    Window defaults to 252 trading days (52 weeks × 5 days) per PRD
    §D4. `min_periods` defaults to ceil(window/2) so warmup is
    forgiving — mid-warmup values are valid but compare against a
    shorter effective history (explicit in caller responsibility).

    Parameters
    ----------
    price_df : close prices, index=date, columns=symbols
    window   : rolling window in trading days (default 252)
    min_periods : min observations for a valid value; defaults to
                  max(1, window // 2)
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    mp = min_periods if min_periods is not None else max(1, window // 2)
    rolling_max = price_df.rolling(window, min_periods=mp).max()
    return price_df / rolling_max - 1.0


def relative_return(
    price_df: pd.DataFrame,
    benchmark_col: str,
    lookback: int,
) -> pd.DataFrame:
    """Per-symbol return minus benchmark's return over the same window.

    `(price[t] / price[t-N] - 1) - (benchmark[t] / benchmark[t-N] - 1)`

    Sign convention: raw difference. Positive = stock beat benchmark.
    Benchmark column is looked up inside `price_df`; callers must
    ensure benchmark is in the panel.

    Parameters
    ----------
    price_df      : close prices, index=date, columns=symbols
    benchmark_col : column name in price_df (typically 'SPY')
    lookback      : return horizon in trading days; must be >= 1

    Returns
    -------
    DataFrame aligned to price_df. Benchmark's own column will equal
    exactly 0 after subtraction (tested by caller).
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    if benchmark_col not in price_df.columns:
        raise KeyError(
            f"benchmark_col '{benchmark_col}' not in price_df columns"
        )
    stock_ret = simple_return(price_df, lookback)
    bench_ret = stock_ret[benchmark_col]
    return stock_ret.sub(bench_ret, axis=0)
