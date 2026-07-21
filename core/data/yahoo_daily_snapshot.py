"""Strict Yahoo chart parser for homogeneous research daily price bases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from core.data.yahoo_corporate_actions import (
    parse_yahoo_corporate_actions,
    yahoo_symbol,
)


@dataclass(frozen=True, slots=True)
class YahooDailyBars:
    vendor_symbol: str
    frame: pd.DataFrame
    ohlc_bound_repairs: int


def _single_result(
    payload: Mapping[str, Any], expected_symbol: str,
) -> Mapping[str, Any]:
    chart = payload.get("chart")
    if not isinstance(chart, Mapping):
        raise ValueError("Yahoo response lacks chart object")
    if chart.get("error") is not None:
        raise ValueError(f"Yahoo chart error: {chart['error']!r}")
    result = chart.get("result")
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("Yahoo response must contain exactly one chart result")
    record = result[0]
    if not isinstance(record, Mapping):
        raise ValueError("Yahoo chart result must be an object")
    meta = record.get("meta")
    if not isinstance(meta, Mapping):
        raise ValueError("Yahoo chart result lacks meta object")
    observed = str(meta.get("symbol", "")).upper()
    expected = yahoo_symbol(expected_symbol)
    if observed != expected:
        raise ValueError(f"Yahoo response symbol mismatch: {observed!r} != {expected!r}")
    return record


def parse_yahoo_daily_bars(
    payload: Mapping[str, Any],
    *,
    expected_symbol: str,
) -> YahooDailyBars:
    """Return split-adjusted price OHLC and dividend-adjusted total-return OHLC."""

    result = _single_result(payload, expected_symbol)
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not timestamps:
        raise ValueError("Yahoo chart result has no timestamps")
    if not isinstance(indicators, Mapping):
        raise ValueError("Yahoo chart result lacks indicators")
    quotes = indicators.get("quote")
    adjusted = indicators.get("adjclose")
    if not isinstance(quotes, list) or len(quotes) != 1:
        raise ValueError("Yahoo chart result must have one quote array")
    if not isinstance(adjusted, list) or len(adjusted) != 1:
        raise ValueError("Yahoo chart result must have one adjclose array")
    quote = quotes[0]
    adjclose = adjusted[0]
    if not isinstance(quote, Mapping) or not isinstance(adjclose, Mapping):
        raise ValueError("Yahoo quote and adjclose records must be objects")
    columns = {
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "volume": quote.get("volume"),
        "adj_close": adjclose.get("adjclose"),
    }
    length = len(timestamps)
    for name, values in columns.items():
        if not isinstance(values, list) or len(values) != length:
            raise ValueError(
                f"Yahoo {name} length differs from timestamps: "
                f"{len(values) if isinstance(values, list) else None} != {length}"
            )
    index = (
        pd.to_datetime(timestamps, unit="s", utc=True, errors="raise")
        .tz_convert("America/New_York")
        .tz_localize(None)
        .normalize()
    )
    frame = pd.DataFrame(columns, index=pd.DatetimeIndex(index, name="date"))
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Yahoo daily dates must be sorted and unique")
    frame = frame.apply(pd.to_numeric, errors="coerce")
    if frame.isna().any().any() or not np.isfinite(frame.to_numpy()).all():
        missing = frame.columns[frame.isna().any()].tolist()
        raise ValueError(f"Yahoo daily bars contain missing/non-finite values: {missing}")
    if bool((frame[["open", "high", "low", "close", "adj_close"]] <= 0).any().any()):
        raise ValueError("Yahoo daily price values must be positive")
    if bool((frame["volume"] < 0).any()):
        raise ValueError("Yahoo daily volume must be non-negative")
    if bool((frame.index.dayofweek >= 5).any()):
        raise ValueError("Yahoo daily bars contain weekend dates")
    upper = frame[["open", "close"]].max(axis=1)
    lower = frame[["open", "close"]].min(axis=1)
    high_bad = frame["high"] < upper
    low_bad = frame["low"] > lower
    relative_high_error = (upper - frame["high"]).clip(lower=0).div(frame["close"])
    relative_low_error = (frame["low"] - lower).clip(lower=0).div(frame["close"])
    material = (relative_high_error > 0.02) | (relative_low_error > 0.02)
    if bool(material.any()):
        first = frame.index[material][0]
        raise ValueError(
            f"Yahoo daily OHLC bound error exceeds 2% at {first.date()}"
        )
    repair_count = int((high_bad | low_bad).sum())
    frame.loc[high_bad, "high"] = upper.loc[high_bad]
    frame.loc[low_bad, "low"] = lower.loc[low_bad]
    factor = frame["adj_close"] / frame["close"]
    if bool((factor <= 0).any()) or not np.isfinite(factor.to_numpy()).all():
        raise ValueError("Yahoo adjustment factor must be finite and positive")
    for name in ("open", "high", "low", "close"):
        frame[f"total_return_{name}"] = frame[name] * factor
    if not np.allclose(
        frame["total_return_close"], frame["adj_close"],
        rtol=1e-10, atol=1e-10,
    ):
        raise ValueError("Yahoo total-return close differs from Adj Close")
    return YahooDailyBars(
        vendor_symbol=yahoo_symbol(expected_symbol),
        frame=frame,
        ohlc_bound_repairs=repair_count,
    )


def corporate_actions_match(
    left_payload: Mapping[str, Any],
    right_payload: Mapping[str, Any],
    *,
    expected_symbol: str,
) -> bool:
    """Compare normalized event tables across two independently saved responses."""

    left = parse_yahoo_corporate_actions(
        left_payload, expected_symbol=expected_symbol)
    right = parse_yahoo_corporate_actions(
        right_payload, expected_symbol=expected_symbol)
    return (
        left.distributions.equals(right.distributions)
        and left.splits.equals(right.splits)
    )


__all__ = [
    "YahooDailyBars",
    "corporate_actions_match",
    "parse_yahoo_daily_bars",
]
