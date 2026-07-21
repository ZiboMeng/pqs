"""Construct a total-return price basis from split-adjusted OHLC and cash events."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class CashDistributionAdjustment:
    frame: pd.DataFrame
    factors: pd.Series
    applied_events: int
    skipped_pre_history_events: int


def apply_cash_distributions(
    split_adjusted_bars: pd.DataFrame,
    distributions: pd.DataFrame,
) -> CashDistributionAdjustment:
    """Back-adjust OHLC for positive cash distributions through the cutoff."""

    required_bars = {"open", "high", "low", "close"}
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
        not split_adjusted_bars.index.is_monotonic_increasing
        or split_adjusted_bars.index.has_duplicates
    ):
        raise ValueError("split-adjusted bars must be sorted and unique")
    factors = pd.Series(1.0, index=split_adjusted_bars.index, name="factor")
    events = distributions.copy()
    events["ex_date"] = pd.to_datetime(events["ex_date"]).dt.tz_localize(None).dt.normalize()
    events["cash_amount"] = pd.to_numeric(events["cash_amount"], errors="coerce")
    if events["cash_amount"].isna().any() or bool((events["cash_amount"] <= 0).any()):
        raise ValueError("cash distributions must be finite and positive")
    if events.duplicated("ex_date").any():
        raise ValueError("cash distributions contain duplicate ex-dates")
    applied = 0
    skipped = 0
    for event in events.sort_values("ex_date").itertuples(index=False):
        prior = split_adjusted_bars.index[
            split_adjusted_bars.index < pd.Timestamp(event.ex_date)]
        if len(prior) == 0:
            skipped += 1
            continue
        reference = float(split_adjusted_bars.loc[prior[-1], "close"])
        factor = 1.0 - float(event.cash_amount) / reference
        if not np.isfinite(factor) or not 0 < factor <= 1.0:
            raise ValueError(
                f"invalid cash adjustment on {event.ex_date}: "
                f"cash={event.cash_amount} reference={reference} factor={factor}"
            )
        factors.loc[factors.index < pd.Timestamp(event.ex_date)] *= factor
        applied += 1
    if bool((factors <= 0).any()) or not np.isfinite(factors.to_numpy()).all():
        raise ValueError("cumulative cash adjustment factor is invalid")
    output = split_adjusted_bars.copy()
    for name in ("open", "high", "low", "close"):
        output[f"total_return_{name}"] = output[name] * factors
    return CashDistributionAdjustment(
        frame=output,
        factors=factors,
        applied_events=applied,
        skipped_pre_history_events=skipped,
    )


__all__ = ["CashDistributionAdjustment", "apply_cash_distributions"]
