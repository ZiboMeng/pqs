"""Fail-closed access to exact cash distributions for portfolio backtests."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from core.data.price_basis import PriceBasisError, validate_total_return_coverage


def load_cash_distribution_panel(
    root: str | Path,
    symbols: Sequence[str],
    index: pd.DatetimeIndex,
    *,
    validate_coverage: bool = True,
) -> pd.DataFrame:
    """Return an exact per-share cash matrix aligned to execution prices."""

    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("cash distribution panel requires DatetimeIndex")
    normalized = index.tz_localize(None).normalize() if index.tz is not None else index.normalize()
    if normalized.has_duplicates or not normalized.is_monotonic_increasing:
        raise PriceBasisError("cash distribution index must be sorted and unique")
    wanted = tuple(dict.fromkeys(str(symbol).upper() for symbol in symbols))
    if not wanted:
        raise PriceBasisError("cash distribution panel requires symbols")
    if len(normalized) < 2:
        raise PriceBasisError("cash distribution panel requires at least two sessions")
    if validate_coverage:
        validate_total_return_coverage(
            root,
            wanted,
            from_date=normalized.min(),
            through=normalized.max(),
        )
    path = Path(root) / "ref/distributions.parquet"
    if not path.is_file():
        raise PriceBasisError(f"distribution sidecar is missing: {path}")
    events = pd.read_parquet(path)
    required = {"symbol", "ex_date", "cash_amount"}
    if not required.issubset(events.columns):
        raise PriceBasisError(
            f"distribution sidecar schema missing columns: {sorted(required - set(events.columns))}"
        )
    events = events[events["symbol"].astype(str).str.upper().isin(wanted)].copy()
    events["symbol"] = events["symbol"].astype(str).str.upper()
    events["ex_date"] = pd.to_datetime(events["ex_date"], errors="raise").dt.tz_localize(None).dt.normalize()
    events["cash_amount"] = pd.to_numeric(events["cash_amount"], errors="coerce")
    if (
        events["cash_amount"].isna().any()
        or not np.isfinite(events["cash_amount"].to_numpy()).all()
        or bool((events["cash_amount"] <= 0).any())
    ):
        raise PriceBasisError("distribution sidecar contains invalid cash amounts")
    if events.duplicated(["symbol", "ex_date"]).any():
        raise PriceBasisError("distribution sidecar contains duplicate symbol/ex-date rows")
    in_range = events[
        (events["ex_date"] >= normalized.min())
        & (events["ex_date"] <= normalized.max())
    ]
    absent_dates = sorted(set(in_range["ex_date"]) - set(normalized))
    if absent_dates:
        raise PriceBasisError(
            "distribution ex-dates are absent from the execution calendar: "
            f"{[str(value.date()) for value in absent_dates[:5]]}"
        )
    panel = pd.DataFrame(0.0, index=normalized, columns=list(wanted))
    for event in in_range.itertuples(index=False):
        panel.loc[event.ex_date, event.symbol] = float(event.cash_amount)
    return panel


def build_total_return_close_panel(
    split_adjusted_close: pd.DataFrame,
    cash_distributions: pd.DataFrame,
) -> pd.DataFrame:
    """Build exact close-to-close wealth indices for signal/label inputs."""

    if not split_adjusted_close.index.equals(cash_distributions.index):
        raise ValueError("close and cash-distribution indices do not align")
    if list(split_adjusted_close.columns) != list(cash_distributions.columns):
        raise ValueError("close and cash-distribution symbols do not align")
    out: dict[str, pd.Series] = {}
    for symbol in split_adjusted_close.columns:
        close = pd.to_numeric(split_adjusted_close[symbol], errors="coerce").dropna()
        if close.empty:
            continue
        if bool((close <= 0).any()) or not np.isfinite(close.to_numpy()).all():
            raise ValueError(f"{symbol}: split-adjusted close is invalid")
        cash = cash_distributions[symbol].reindex(close.index)
        gross = close.add(cash).div(close.shift(1))
        gross.iloc[0] = 1.0
        if bool((gross <= 0).any()) or not np.isfinite(gross.to_numpy()).all():
            raise ValueError(f"{symbol}: total-return recurrence is invalid")
        out[symbol] = float(close.iloc[0]) * gross.cumprod()
    return pd.DataFrame(out, index=split_adjusted_close.index)


__all__ = ["build_total_return_close_panel", "load_cash_distribution_panel"]
