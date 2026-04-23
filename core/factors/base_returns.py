"""Shared return-family helpers (PRD 20260423 Step 1).

Adds canonical primitives for the Returns family that both
factor_generator and future strategy code can share:
  - simple_return(price_df, lookback)
  - overnight_return_raw(open_df, close_df)
  - intraday_return_raw(open_df, close_df)

Design rule (inherited from base_factors.py): every function is a
pure function of its inputs. Lookahead safety is enforced at the
caller level — these helpers operate on the panel as-given.

Sign convention: all helpers return RAW, unsigned values. A positive
value = positive return. Sign-flipping for mean-reversion-style
signals is the caller's responsibility (e.g. _mean_reversion_factors
negates the 5d return to get `reversal_5d`).
"""

from __future__ import annotations

import pandas as pd


def simple_return(price_df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Close-to-close return over `lookback` trading days.

    Equivalent to `price_df.pct_change(lookback)` but centralized here
    so future changes (e.g. alternative compounding) land in one place.

    Parameters
    ----------
    price_df : close prices, index=date, columns=symbols
    lookback : number of trading days; must be >= 1

    Returns
    -------
    DataFrame aligned to price_df. First `lookback` rows are NaN.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    return price_df.pct_change(lookback)


def overnight_return_raw(
    open_df: pd.DataFrame, close_df: pd.DataFrame,
) -> pd.DataFrame:
    """Raw 1-bar overnight gap: open[t] / close[t-1] - 1.

    Distinct from `overnight_gap_5d` / `overnight_gap_21d` in
    factor_generator which are rolling means over this same primitive.
    Exposing the raw 1-bar form is required by PRD §3.1.B (raw sibling
    of rolling-mean overnight family).

    Parameters
    ----------
    open_df  : open prices, index=date, columns=symbols
    close_df : close prices, same shape as open_df (alignment enforced
               via reindex; mismatched indices become NaN)

    Returns
    -------
    DataFrame aligned to open_df.index. First row is NaN (no prior close).
    """
    # Align on open_df's index/columns; shift close for the prior-day reference
    prev_close = close_df.reindex_like(open_df).shift(1)
    return open_df / prev_close - 1.0


def intraday_return_raw(
    open_df: pd.DataFrame, close_df: pd.DataFrame,
) -> pd.DataFrame:
    """Raw 1-bar intraday return: close[t] / open[t] - 1.

    Sign convention: positive = close > open = up day. Complementary
    pair to `overnight_return_raw`; their rolling aggregates are
    already exposed as `overnight_vs_intraday` but the raw 1-bar
    intraday form was not exposed as a registered factor before this
    PRD.

    Parameters
    ----------
    open_df  : open prices, index=date, columns=symbols
    close_df : close prices, same shape as open_df

    Returns
    -------
    DataFrame aligned to open_df.index. NaN where open is 0 or NaN.
    """
    aligned_close = close_df.reindex_like(open_df)
    return aligned_close / open_df - 1.0
