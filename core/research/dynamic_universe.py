"""Causal, trailing-only eligibility for governed strategy research.

The frozen symbol pool and the per-date eligible universe are deliberately
different concepts.  A pool may be selected once for a future research
program; this module decides which pool members were actually tradeable at a
historical decision close without consulting any later row.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Iterable, Sequence

import pandas as pd


@dataclass(frozen=True, slots=True)
class DynamicEligibilityConfig:
    min_history_sessions: int = 252
    lookback_sessions: int = 63
    min_observation_density: float = 0.95
    min_price: float = 5.0
    min_median_dollar_volume: float = 20_000_000.0
    excluded_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_history_sessions < 1:
            raise ValueError("min_history_sessions must be >= 1")
        if self.lookback_sessions < 1:
            raise ValueError("lookback_sessions must be >= 1")
        if not 0 < self.min_observation_density <= 1:
            raise ValueError("min_observation_density must be in (0, 1]")
        if self.min_price < 0:
            raise ValueError("min_price must be non-negative")
        if self.min_median_dollar_volume < 0:
            raise ValueError("min_median_dollar_volume must be non-negative")


def _validate_panels(close: pd.DataFrame, volume: pd.DataFrame) -> None:
    if not isinstance(close.index, pd.DatetimeIndex):
        raise TypeError("close must use a DatetimeIndex")
    if not isinstance(volume.index, pd.DatetimeIndex):
        raise TypeError("volume must use a DatetimeIndex")
    if not close.index.equals(volume.index):
        raise ValueError("close and volume indexes must match exactly")
    if not close.columns.equals(volume.columns):
        raise ValueError("close and volume columns must match exactly")
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        raise ValueError("price panels require sorted, unique decision dates")


def build_dynamic_eligibility_mask(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    config: DynamicEligibilityConfig | None = None,
    *,
    decision_dates: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Return a causal boolean eligibility panel.

    A cell at close ``T`` is true only when all required history, current-bar
    price/volume, observation density and trailing liquidity were known at T.
    Rolling calculations are backward-looking and include T because the
    governed strategy decision occurs after that close; execution is T+1 open.

    ``decision_dates`` is applied *after* all rolling state is calculated so a
    monthly decision schedule does not accidentally reinterpret 63 sessions as
    63 months.
    """

    cfg = config or DynamicEligibilityConfig()
    _validate_panels(close, volume)

    finite = close.notna() & volume.notna() & (close > 0) & (volume >= 0)
    history = finite.cumsum()
    min_obs = ceil(cfg.lookback_sessions * cfg.min_observation_density)
    observations = finite.rolling(
        cfg.lookback_sessions, min_periods=1).sum()
    density = observations / float(cfg.lookback_sessions)
    dollar_volume = (close * volume).where(finite)
    median_dollar_volume = dollar_volume.rolling(
        cfg.lookback_sessions,
        min_periods=min_obs,
    ).median()

    eligible = (
        finite
        & (history >= cfg.min_history_sessions)
        & (density >= cfg.min_observation_density)
        & (close >= cfg.min_price)
        & (median_dollar_volume >= cfg.min_median_dollar_volume)
    )
    excluded = set(cfg.excluded_symbols)
    for symbol in eligible.columns.intersection(sorted(excluded)):
        eligible.loc[:, symbol] = False

    eligible = eligible.fillna(False).astype(bool)
    if decision_dates is not None:
        requested = pd.DatetimeIndex(decision_dates)
        missing = requested.difference(eligible.index)
        if len(missing):
            raise KeyError(
                "decision_dates are absent from the price panel: "
                f"{[str(v) for v in missing[:5]]}"
            )
        eligible = eligible.loc[requested]
    return eligible


def eligible_symbols(
    mask: pd.DataFrame,
    decision_date: str | pd.Timestamp,
    *,
    ordered_pool: Iterable[str] | None = None,
) -> list[str]:
    """Resolve one decision date to a deterministic ordered symbol list."""

    date = pd.Timestamp(decision_date)
    if date not in mask.index:
        raise KeyError(f"decision date {date} is absent from eligibility mask")
    row = mask.loc[date]
    order = list(ordered_pool) if ordered_pool is not None else list(mask.columns)
    return [symbol for symbol in order if symbol in row.index and bool(row[symbol])]
