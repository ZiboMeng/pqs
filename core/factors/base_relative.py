"""Shared relative / position helpers.

Canonical primitives for the Relative / Position factor family:
  - dist_from_rolling_max(price_df, window)  # 52w-high-style
  - relative_return(price_df, benchmark_col, lookback)
  - rolling_beta(stock_returns, bench_returns, lookback)  # PRD 20260424 P2
  - residualize_returns(stock_returns, bench_returns, lookback)  # PRD 20260424 P2

Design rule (inherited): pure function of inputs, no side effects.
Windows and sign conventions are raw and documented per-function.
"""

from __future__ import annotations

import numpy as np
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


# ── PRD 20260424 §6 P2: Residualization helpers ──────────────────────────────
#
# Used by `residual_mom_spy_20d` and future sector-neutral residual factors.
# Both helpers operate on DAILY RETURNS (not prices) so they compose cleanly:
# a 20d residual-momentum factor is just `rolling(20).sum()` applied to the
# daily-residual-returns output of `residualize_returns`.


def rolling_beta(
    stock_returns: pd.DataFrame,
    bench_returns: pd.Series,
    lookback: int = 60,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Rolling OLS beta of each stock's daily returns vs benchmark's.

    beta[t, sym] = Cov(stock_ret[t-L:t, sym], bench_ret[t-L:t]) /
                   Var(bench_ret[t-L:t])

    Parameters
    ----------
    stock_returns : DataFrame of daily returns, index=date, columns=symbols
    bench_returns : Series of daily returns for the benchmark, indexed by date
    lookback      : rolling window in trading days (default 60)
    min_periods   : min observations for a valid beta; defaults to
                    max(20, lookback // 2) — require enough data for
                    a stable estimate

    Returns
    -------
    DataFrame aligned to stock_returns. NaN during warmup (< min_periods).
    """
    if lookback < 2:
        raise ValueError(f"lookback must be >= 2, got {lookback}")
    mp = min_periods if min_periods is not None else max(20, lookback // 2)
    # Align benchmark to stock panel's index
    bench = bench_returns.reindex(stock_returns.index)
    # Var of benchmark (scalar per date, as Series). Use ddof=0 (population
    # variance, N divisor) so it matches the N-divisor used by .mean() below
    # when computing E[XY] - E[X]E[Y]. Otherwise beta_self (bench vs itself)
    # comes out to (N-1)/N instead of 1.0 — a systematic bias.
    bench_var = bench.rolling(lookback, min_periods=mp).var(ddof=0)
    # Cov of each stock with benchmark — broadcast via DataFrame arithmetic
    # Cov(X, Y) = E[XY] - E[X]E[Y]; use the identity via rolling means.
    stock_mean = stock_returns.rolling(lookback, min_periods=mp).mean()
    bench_mean = bench.rolling(lookback, min_periods=mp).mean()
    # E[X * Y]:  elementwise product then rolling mean per column
    xy = stock_returns.mul(bench, axis=0)
    cross_mean = xy.rolling(lookback, min_periods=mp).mean()
    cov = cross_mean.sub(stock_mean.mul(bench_mean, axis=0), axis=0)
    # beta = cov / var (broadcast var across columns)
    beta = cov.div(bench_var.replace(0, np.nan), axis=0)
    return beta


def residualize_returns(
    stock_returns: pd.DataFrame,
    bench_returns: pd.Series,
    lookback: int = 60,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Daily residual returns after removing rolling-beta exposure to benchmark.

    residual[t, sym] = stock_ret[t, sym] - beta[t, sym] * bench_ret[t]

    where `beta[t, sym]` is the rolling `lookback`-day OLS beta as computed by
    `rolling_beta`. This is the standard Fama-MacBeth-style daily residual
    return that composes into:
      - residual momentum: `rolling(N).sum()` of the output
      - idiosyncratic volatility: `rolling(N).std()` of the output
      - residual correlation / dispersion / etc.

    Parameters
    ----------
    stock_returns : DataFrame of daily returns
    bench_returns : Series of benchmark daily returns
    lookback      : rolling window for beta estimation (default 60)
    min_periods   : see rolling_beta; same default

    Returns
    -------
    DataFrame aligned to stock_returns. NaN during warmup.
    """
    beta = rolling_beta(stock_returns, bench_returns, lookback, min_periods)
    bench = bench_returns.reindex(stock_returns.index)
    # element-wise: stock_ret - beta * bench_ret (broadcast bench per date)
    expected = beta.mul(bench, axis=0)
    return stock_returns - expected
