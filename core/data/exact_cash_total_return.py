"""Exact cash-distribution accounting for split-adjusted daily prices."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ExactCashTotalReturn:
    frame: pd.DataFrame
    applied_events: int
    skipped_pre_history_events: int


def build_exact_cash_total_return(
    split_adjusted_bars: pd.DataFrame,
    distributions: pd.DataFrame,
) -> ExactCashTotalReturn:
    """Add exact per-share cash and a close-to-close reinvested wealth index.

    For an ex-date ``t`` with cash amount ``D_t``, the exact holder return is
    ``(close_t + D_t) / close_(t-1) - 1``.  This deliberately does not use a
    vendor back-adjustment approximation such as ``1 - D_t / close_(t-1)``.
    Portfolio execution must still credit ``D_t`` to shares held before the
    ex-date open; the wealth index is for return features and close labels.
    """

    required_bars = {"open", "high", "low", "close", "volume"}
    missing_bars = required_bars - set(split_adjusted_bars)
    if missing_bars:
        raise ValueError(f"split-adjusted bars lack columns: {sorted(missing_bars)}")
    required_events = {"ex_date", "cash_amount"}
    missing_events = required_events - set(distributions)
    if missing_events:
        raise ValueError(f"distribution events lack columns: {sorted(missing_events)}")
    if not isinstance(split_adjusted_bars.index, pd.DatetimeIndex):
        raise TypeError("split-adjusted bars require DatetimeIndex")
    if (
        split_adjusted_bars.empty
        or not split_adjusted_bars.index.is_monotonic_increasing
        or split_adjusted_bars.index.has_duplicates
    ):
        raise ValueError("split-adjusted bars must be non-empty, sorted, and unique")
    prices = split_adjusted_bars[list(required_bars)].apply(
        pd.to_numeric, errors="coerce")
    if prices.isna().any().any() or not np.isfinite(prices.to_numpy()).all():
        raise ValueError("split-adjusted bars contain missing or non-finite values")
    if bool((prices[["open", "high", "low", "close"]] <= 0).any().any()):
        raise ValueError("split-adjusted prices must be positive")
    if bool((prices["volume"] < 0).any()):
        raise ValueError("volume must be non-negative")

    events = distributions.copy()
    events["ex_date"] = (
        pd.to_datetime(events["ex_date"], errors="raise")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    events["cash_amount"] = pd.to_numeric(
        events["cash_amount"], errors="coerce")
    if events["cash_amount"].isna().any() or not np.isfinite(
        events["cash_amount"].to_numpy()).all():
        raise ValueError("cash distributions must be finite")
    if bool((events["cash_amount"] <= 0).any()):
        raise ValueError("cash distributions must be positive")
    if events.duplicated("ex_date").any():
        raise ValueError("cash distributions contain duplicate ex-dates")

    cash = pd.Series(
        0.0, index=split_adjusted_bars.index, name="cash_distribution")
    skipped = 0
    applied = 0
    first = split_adjusted_bars.index[0]
    for event in events.sort_values("ex_date").itertuples(index=False):
        ex_date = pd.Timestamp(event.ex_date)
        if ex_date <= first:
            skipped += 1
            continue
        if ex_date not in cash.index:
            raise ValueError(
                f"cash distribution ex-date is absent from price bars: {ex_date.date()}"
            )
        cash.loc[ex_date] = float(event.cash_amount)
        applied += 1

    close = split_adjusted_bars["close"].astype(float)
    gross = close.add(cash).div(close.shift(1))
    gross.iloc[0] = 1.0
    if bool((gross <= 0).any()) or not np.isfinite(gross.to_numpy()).all():
        raise ValueError("exact cash total-return gross factors are invalid")
    total_return_close = float(close.iloc[0]) * gross.cumprod()
    total_return_close.name = "total_return_close"
    output = split_adjusted_bars[
        ["open", "high", "low", "close", "volume"]
    ].copy()
    output["cash_distribution"] = cash
    output["total_return_close"] = total_return_close
    return ExactCashTotalReturn(
        frame=output,
        applied_events=applied,
        skipped_pre_history_events=skipped,
    )


__all__ = ["ExactCashTotalReturn", "build_exact_cash_total_return"]
