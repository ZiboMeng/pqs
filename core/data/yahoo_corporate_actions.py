"""Strict parser for Yahoo chart corporate-action responses.

The chart endpoint is an external, unofficial data source.  This module only
normalizes a saved response; fetching, provenance, and certification belong to
the governed corpus builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class YahooCorporateActions:
    vendor_symbol: str
    distributions: pd.DataFrame
    splits: pd.DataFrame


def yahoo_symbol(symbol: str) -> str:
    """Translate the repository's class-share notation for Yahoo requests."""

    normalized = str(symbol).strip().upper()
    if not normalized:
        raise ValueError("Yahoo symbol must be non-empty")
    return normalized.replace(".", "-")


def _event_date(epoch_seconds: Any) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(int(epoch_seconds), unit="s", tz="UTC")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid Yahoo event timestamp: {epoch_seconds!r}") from exc
    return timestamp.tz_convert("America/New_York").tz_localize(None).normalize()


def _chart_result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    chart = payload.get("chart")
    if not isinstance(chart, Mapping):
        raise ValueError("Yahoo response lacks chart object")
    if chart.get("error") is not None:
        raise ValueError(f"Yahoo chart error: {chart['error']!r}")
    result = chart.get("result")
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("Yahoo response must contain exactly one chart result")
    if not isinstance(result[0], Mapping):
        raise ValueError("Yahoo chart result must be an object")
    return result[0]


def parse_yahoo_corporate_actions(
    payload: Mapping[str, Any],
    *,
    expected_symbol: str,
) -> YahooCorporateActions:
    """Parse positive cash distributions and economically effective splits."""

    result = _chart_result(payload)
    meta = result.get("meta")
    if not isinstance(meta, Mapping):
        raise ValueError("Yahoo chart result lacks meta object")
    observed_symbol = str(meta.get("symbol", "")).upper()
    expected_vendor_symbol = yahoo_symbol(expected_symbol)
    if observed_symbol != expected_vendor_symbol:
        raise ValueError(
            "Yahoo response symbol mismatch: "
            f"{observed_symbol!r} != {expected_vendor_symbol!r}"
        )
    events = result.get("events") or {}
    if not isinstance(events, Mapping):
        raise ValueError("Yahoo chart events must be an object")

    distribution_rows: list[dict[str, Any]] = []
    dividends = events.get("dividends") or {}
    if not isinstance(dividends, Mapping):
        raise ValueError("Yahoo dividend events must be an object")
    for event in dividends.values():
        if not isinstance(event, Mapping):
            raise ValueError("Yahoo dividend event must be an object")
        amount = pd.to_numeric(event.get("amount"), errors="coerce")
        if not np.isfinite(amount) or float(amount) <= 0:
            raise ValueError(f"invalid Yahoo dividend amount: {event.get('amount')!r}")
        distribution_rows.append({
            "symbol": str(expected_symbol).upper(),
            "ex_date": _event_date(event.get("date")),
            "cash_amount": float(amount),
        })
    distributions = pd.DataFrame(
        distribution_rows, columns=["symbol", "ex_date", "cash_amount"])
    if not distributions.empty:
        duplicate = distributions.duplicated(["symbol", "ex_date"])
        if duplicate.any():
            raise ValueError("Yahoo response has duplicate dividend event dates")
        distributions = distributions.sort_values("ex_date").reset_index(drop=True)

    split_rows: list[dict[str, Any]] = []
    splits = events.get("splits") or {}
    if not isinstance(splits, Mapping):
        raise ValueError("Yahoo split events must be an object")
    for event in splits.values():
        if not isinstance(event, Mapping):
            raise ValueError("Yahoo split event must be an object")
        numerator = pd.to_numeric(event.get("numerator"), errors="coerce")
        denominator = pd.to_numeric(event.get("denominator"), errors="coerce")
        if (
            not np.isfinite(numerator)
            or not np.isfinite(denominator)
            or float(numerator) <= 0
            or float(denominator) <= 0
        ):
            raise ValueError(f"invalid Yahoo split ratio: {event!r}")
        ratio = float(numerator) / float(denominator)
        if np.isclose(ratio, 1.0, rtol=1e-8, atol=1e-10):
            continue
        split_rows.append({
            "symbol": str(expected_symbol).upper(),
            "date": _event_date(event.get("date")),
            "vendor_ratio": ratio,
        })
    split_frame = pd.DataFrame(
        split_rows, columns=["symbol", "date", "vendor_ratio"])
    if not split_frame.empty:
        split_frame = (
            split_frame.groupby(["symbol", "date"], as_index=False)["vendor_ratio"]
            .prod()
            .sort_values("date")
            .reset_index(drop=True)
        )
    return YahooCorporateActions(
        vendor_symbol=observed_symbol,
        distributions=distributions,
        splits=split_frame,
    )


__all__ = [
    "YahooCorporateActions",
    "parse_yahoo_corporate_actions",
    "yahoo_symbol",
]
