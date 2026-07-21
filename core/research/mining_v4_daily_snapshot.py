"""Build a homogeneous raw-daily source for governed mining.

The canonical daily store contains two historically documented research-only
ingest classes that must not be mixed silently:

* legacy raw OHLCV whose date labels were shifted by +1 calendar day; and
* Phase-4 yfinance ``auto_adjust=True`` replacements, while the original raw
  file was retained as ``.preP4Expand_*``.

This module performs the only permitted repair for that known signature.  It
does not mutate the canonical store.  A source is accepted only when its
original index contains weekend rows and shifting *every* label back one
calendar day produces a unique, weekday-only index contained in the governed
benchmark calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class RawDailySource:
    symbol: str
    path: Path
    transform: str


def safe_symbol(symbol: str) -> str:
    return symbol.replace("^", "_").replace("-", "_")


def validate_raw_daily(
    frame: pd.DataFrame,
    *,
    symbol: str,
    benchmark_sessions: pd.DatetimeIndex,
) -> None:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"{symbol}: raw daily source lacks {sorted(missing)}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError(f"{symbol}: raw daily source requires DatetimeIndex")
    if frame.index.tz is not None:
        raise ValueError(f"{symbol}: raw daily index must be timezone-naive")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError(f"{symbol}: raw daily index must be sorted and unique")
    if bool((frame.index.dayofweek >= 5).any()):
        raise ValueError(f"{symbol}: raw daily source retains weekend rows")
    outside = frame.index.difference(benchmark_sessions)
    if len(outside):
        raise ValueError(
            f"{symbol}: {len(outside)} dates fall outside benchmark sessions; "
            f"first={outside[0].date()}"
        )
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError(f"{symbol}: raw daily OHLCV contains NaN/inf")
    if bool((numeric[["open", "high", "low", "close"]] <= 0).any().any()):
        raise ValueError(f"{symbol}: raw daily price must be positive")
    if bool((numeric["volume"] < 0).any()):
        raise ValueError(f"{symbol}: raw daily volume must be non-negative")
    # Historical Polygon/trades aggregation can differ from the stored close
    # by sub-cent rounding.  The existing expanded-universe audit uses 0.5%
    # as the material OHLC-bound threshold; match that governed tolerance.
    tolerance = numeric["close"].abs().clip(lower=1.0) * 5e-3
    if bool((numeric["high"] + tolerance < numeric[["open", "close"]].max(axis=1)).any()):
        raise ValueError(f"{symbol}: high violates OHLC bounds")
    if bool((numeric["low"] - tolerance > numeric[["open", "close"]].min(axis=1)).any()):
        raise ValueError(f"{symbol}: low violates OHLC bounds")


def repair_known_plus_one_day_shift(
    frame: pd.DataFrame,
    *,
    symbol: str,
    benchmark_sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Repair only the proven all-row +1-calendar-day corruption pattern."""

    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError(f"{symbol}: shifted raw daily source requires DatetimeIndex")
    weekend_count = int((frame.index.dayofweek >= 5).sum())
    if weekend_count == 0:
        raise ValueError(
            f"{symbol}: refuse -1d repair because source has no weekend signature")
    repaired = frame.copy()
    repaired.index = repaired.index - pd.Timedelta(days=1)
    repaired.index.name = "date"
    validate_raw_daily(
        repaired,
        symbol=symbol,
        benchmark_sessions=benchmark_sessions,
    )
    return repaired


def resolve_raw_daily_source(
    daily_dir: Path,
    symbol: str,
    *,
    phase4_preadjusted: bool,
) -> RawDailySource:
    """Resolve the raw file without guessing its price basis."""

    stem = safe_symbol(symbol)
    canonical = daily_dir / f"{stem}.parquet"
    if phase4_preadjusted:
        backups = sorted(daily_dir.glob(f"{stem}.parquet.preP4Expand_*"))
        if not backups:
            raise FileNotFoundError(
                f"{symbol}: Phase-4 pre-adjusted file has no retained raw sidecar")
        return RawDailySource(
            symbol=symbol,
            path=backups[-1],
            transform="KNOWN_PLUS_ONE_DAY_SHIFT_TO_RAW_SIDECAR",
        )
    if not canonical.exists():
        raise FileNotFoundError(f"{symbol}: canonical daily parquet is absent")
    return RawDailySource(
        symbol=symbol,
        path=canonical,
        transform="AUTO_DETECT_KNOWN_PLUS_ONE_DAY_OR_IDENTITY",
    )


__all__ = [
    "RawDailySource",
    "repair_known_plus_one_day_shift",
    "resolve_raw_daily_source",
    "safe_symbol",
    "validate_raw_daily",
]
