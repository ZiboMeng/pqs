"""Freeze a current SEC-company pool for future strategy observation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

SEC_COMPANY_TICKERS_EXCHANGE_URL = (
    "https://www.sec.gov/files/company_tickers_exchange.json"
)


@dataclass(frozen=True, slots=True)
class CompanyPoolConfig:
    max_symbols: int = 300
    exchanges: tuple[str, ...] = ("Nasdaq", "NYSE")
    min_history_sessions_at_snapshot: int = 756
    freshness_calendar_days: int = 5
    min_price: float = 5.0
    trailing_liquidity_sessions: int = 63
    min_median_dollar_volume: float = 20_000_000.0
    excluded_name_patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_symbols < 1:
            raise ValueError("max_symbols must be >= 1")
        if not self.exchanges:
            raise ValueError("at least one exchange is required")
        if self.min_history_sessions_at_snapshot < 1:
            raise ValueError("min_history_sessions_at_snapshot must be >= 1")
        if self.freshness_calendar_days < 0:
            raise ValueError("freshness_calendar_days must be non-negative")
        if self.trailing_liquidity_sessions < 1:
            raise ValueError("trailing_liquidity_sessions must be >= 1")


@dataclass(frozen=True, slots=True)
class CompanyPoolSelection:
    selected: tuple[dict[str, Any], ...]
    rejection_counts: dict[str, int]
    n_records: int
    n_unique_tickers: int


def parse_sec_company_tickers(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Parse the SEC fields/data representation into named records."""

    fields = payload.get("fields")
    data = payload.get("data")
    expected = ["cik", "name", "ticker", "exchange"]
    if fields != expected or not isinstance(data, list):
        raise ValueError("unexpected SEC company_tickers_exchange schema")
    records: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("malformed SEC company ticker row")
        record = dict(zip(fields, row))
        record["ticker"] = str(record["ticker"]).upper().strip()
        record["name"] = str(record["name"]).strip()
        record["exchange"] = str(record["exchange"]).strip()
        record["cik"] = int(record["cik"])
        records.append(record)
    return records


def sec_payload_sha256(payload_bytes: bytes) -> str:
    return hashlib.sha256(payload_bytes).hexdigest()


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy()
    if not isinstance(bars.index, pd.DatetimeIndex):
        date_column = next(
            (name for name in ("date", "Date") if name in bars.columns), None)
        if date_column is None:
            raise ValueError("daily bars lack a DatetimeIndex/date column")
        bars.index = pd.to_datetime(bars.pop(date_column))
    bars.index = pd.DatetimeIndex(bars.index).tz_localize(None).normalize()
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    required = {"close", "volume"}
    if not required.issubset(bars.columns):
        raise ValueError(f"daily bars missing columns {sorted(required - set(bars))}")
    return bars[["close", "volume"]]


def select_company_pool(
    records: Iterable[Mapping[str, Any]],
    load_bars: Callable[[str], pd.DataFrame | None],
    *,
    price_as_of: str | pd.Timestamp,
    config: CompanyPoolConfig,
    excluded_symbols: Sequence[str] = (),
) -> CompanyPoolSelection:
    """Select a liquid current-company pool using snapshot-known inputs."""

    cutoff = pd.Timestamp(price_as_of).tz_localize(None).normalize()
    excluded = {str(symbol).upper() for symbol in excluded_symbols}
    patterns = [re.compile(pattern) for pattern in config.excluded_name_patterns]
    allowed_exchanges = set(config.exchanges)
    rejection: Counter[str] = Counter()
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    record_list = list(records)

    for raw in sorted(record_list, key=lambda row: str(row.get("ticker", ""))):
        ticker = str(raw.get("ticker", "")).upper().strip()
        name = str(raw.get("name", "")).strip()
        exchange = str(raw.get("exchange", "")).strip()
        if not ticker or ticker in seen:
            rejection["missing_or_duplicate_ticker"] += 1
            continue
        seen.add(ticker)
        if exchange not in allowed_exchanges:
            rejection["exchange"] += 1
            continue
        if ticker in excluded:
            rejection["project_exclusion"] += 1
            continue
        if any(pattern.search(name) for pattern in patterns):
            rejection["fund_or_etp_name"] += 1
            continue
        try:
            frame = load_bars(ticker)
            if frame is None or frame.empty:
                rejection["missing_bars"] += 1
                continue
            bars = _normalize_bars(frame)
        except (OSError, ValueError, TypeError):
            rejection["invalid_bars"] += 1
            continue
        bars = bars.loc[bars.index <= cutoff].dropna(subset=["close", "volume"])
        bars = bars[(bars["close"] > 0) & (bars["volume"] >= 0)]
        if len(bars) < config.min_history_sessions_at_snapshot:
            rejection["history"] += 1
            continue
        last_date = bars.index[-1]
        if (cutoff - last_date).days > config.freshness_calendar_days:
            rejection["stale"] += 1
            continue
        last_price = float(bars["close"].iloc[-1])
        if last_price < config.min_price:
            rejection["price"] += 1
            continue
        recent = bars.tail(config.trailing_liquidity_sessions)
        if len(recent) < config.trailing_liquidity_sessions:
            rejection["liquidity_history"] += 1
            continue
        median_dollar_volume = float((recent["close"] * recent["volume"]).median())
        if median_dollar_volume < config.min_median_dollar_volume:
            rejection["liquidity"] += 1
            continue
        candidates.append({
            "ticker": ticker,
            "cik": int(raw["cik"]),
            "name": name,
            "exchange": exchange,
            "first_bar_date": str(bars.index[0].date()),
            "last_bar_date": str(last_date.date()),
            "history_sessions": int(len(bars)),
            "last_price": last_price,
            "median_dollar_volume_63": median_dollar_volume,
        })

    candidates.sort(
        key=lambda row: (-row["median_dollar_volume_63"], row["ticker"]))
    selected = tuple(candidates[:config.max_symbols])
    rejection["liquidity_rank_below_max_symbols"] += max(
        0, len(candidates) - len(selected))
    return CompanyPoolSelection(
        selected=selected,
        rejection_counts=dict(sorted(rejection.items())),
        n_records=len(record_list),
        n_unique_tickers=len(seen),
    )


def canonical_artifact_hash(artifact_without_hash: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        artifact_without_hash,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
