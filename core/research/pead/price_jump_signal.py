"""Price-jump-anchored PEAD signal — Path 2.

Definition (Chan-Jegadeesh-Lakonishok 1996):

    On earnings announcement day T:
        ret_stock(T) = (close[T] - close[T-1]) / close[T-1]
        ret_SPY(T)   = (spy[T] - spy[T-1]) / spy[T-1]
        AR(T)        = ret_stock(T) - ret_SPY(T)         # abnormal return

    Signal = AR(T) > +AR_threshold (e.g., +5%)
    Entry  = T+1 open (handled by SignalDrivenBacktest execution_delay_bars=1)
    Hold   = max_hold business days

Use as a proxy for earnings surprise when consensus-estimate data is
unavailable. Captures price-reaction-to-news rather than fundamental
surprise; confounded by (a) macro on same day, (b) sector co-move,
(c) guidance / unrelated news. Trade-off vs SUE: sharper trigger,
noisier signal.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd


def compute_abnormal_returns(
    earnings_panel: pd.DataFrame,
    close_df: pd.DataFrame,
    benchmark_symbol: str = "SPY",
) -> pd.DataFrame:
    """Compute AR(T) for each (ticker, filed_date) row.

    Args:
        earnings_panel: DataFrame from `extract_earnings_dates_panel(tickers)`.
            Required columns: ticker, first_filed_date.
        close_df: price panel (date index × ticker columns); MUST include
            `benchmark_symbol` as one of the columns.
        benchmark_symbol: ticker used for market-return subtraction.

    Returns:
        Same DataFrame + columns:
            event_date  pd.Timestamp  (filed_date rolled forward to next
                                       trading day if not in close_df index)
            ret_stock   float         (T close vs T-1 close)
            ret_bench   float         (benchmark return same day)
            abnormal_return float     (stock - bench)

        Rows where event_date cannot be resolved (no trading day after
        filed_date in price_index) OR ticker not in close_df OR T-1
        unavailable, are dropped silently.
    """
    if earnings_panel.empty:
        empty_cols = ["event_date", "ret_stock", "ret_bench", "abnormal_return"]
        return earnings_panel.assign(**{c: pd.Series(dtype=object) for c in empty_cols})

    if benchmark_symbol not in close_df.columns:
        raise ValueError(
            f"benchmark_symbol={benchmark_symbol!r} not in close_df columns"
        )

    price_index = close_df.index
    rows: List[dict] = []
    for _, row in earnings_panel.iterrows():
        sym = row["ticker"]
        if sym not in close_df.columns:
            continue
        filed = pd.Timestamp(row["first_filed_date"])
        # Roll filed forward to next trading day
        after = price_index[price_index >= filed]
        if len(after) == 0:
            continue
        event_date = after[0]
        # Need T-1 close
        before = price_index[price_index < event_date]
        if len(before) == 0:
            continue
        prev_date = before[-1]

        stock_t = close_df.at[event_date, sym]
        stock_tm1 = close_df.at[prev_date, sym]
        bench_t = close_df.at[event_date, benchmark_symbol]
        bench_tm1 = close_df.at[prev_date, benchmark_symbol]

        if (pd.isna(stock_t) or pd.isna(stock_tm1)
                or pd.isna(bench_t) or pd.isna(bench_tm1)
                or stock_tm1 == 0 or bench_tm1 == 0):
            continue

        ret_stock = (stock_t - stock_tm1) / stock_tm1
        ret_bench = (bench_t - bench_tm1) / bench_tm1
        ar = ret_stock - ret_bench

        rows.append({
            **row.to_dict(),
            "event_date": event_date,
            "ret_stock": float(ret_stock),
            "ret_bench": float(ret_bench),
            "abnormal_return": float(ar),
        })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).reset_index(drop=True)


def build_price_jump_signal_panel(
    abnormal_returns_df: pd.DataFrame,
    ar_threshold: float,
    price_index: pd.DatetimeIndex,
    universe: List[str],
) -> pd.DataFrame:
    """Build entry_signals DataFrame for K1 SignalDrivenBacktest.

    For each row where abnormal_return > ar_threshold, set
    entry_signals[event_date, ticker] = True.

    Args:
        abnormal_returns_df: output of `compute_abnormal_returns`.
        ar_threshold: trigger threshold (e.g., 0.05 for +5%).
        price_index: pd.DatetimeIndex of trading days (columns alignment).
        universe: list of ticker symbols.

    Returns:
        DataFrame indexed by price_index, columns=universe, bool values.
    """
    entry = pd.DataFrame(False, index=price_index, columns=universe)
    if abnormal_returns_df.empty:
        return entry

    triggers = abnormal_returns_df[
        abnormal_returns_df["abnormal_return"] >= ar_threshold
    ]
    for _, row in triggers.iterrows():
        sym = row["ticker"]
        if sym not in universe:
            continue
        event_date = pd.Timestamp(row["event_date"])
        if event_date not in price_index:
            continue
        entry.loc[event_date, sym] = True
    return entry
