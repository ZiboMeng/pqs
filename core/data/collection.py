"""Phase 3 provider-neutral, collect-only market-data ingestion boundary.

Raw inputs are preserved in one immutable hash chain.  A semantic validation
failure is appended under ``quarantine`` and never advances the trusted
provider cursor.  This module deliberately has no strategy-facing read API.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from core.runtime.strategy_artifact import canonical_json, sha256_bytes

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_ZERO_HASH = "0" * 64
_MAX_CURSOR_LENGTH = 512


class CollectionError(RuntimeError):
    """Base class for collection boundary failures."""


class CollectionChainError(CollectionError):
    """The append-only collection chain is corrupt or ambiguous."""


class FeedKind(StrEnum):
    DAILY = "daily"
    INTRADAY = "intraday"
    OPTIONS = "options"


class BatchStatus(StrEnum):
    TRUSTED = "trusted"
    QUARANTINED = "quarantined"


EXPECTED_SCHEMAS = {
    FeedKind.DAILY: "daily_total_return_v1",
    FeedKind.INTRADAY: "intraday_quote_bar_v1",
    FeedKind.OPTIONS: "options_chain_v1",
}

_DAILY_FIELDS = {
    "symbol",
    "session",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "total_return_factor",
    "volume",
    "dividend",
    "split_factor",
    "corporate_action",
    "calendar",
    "event_time",
    "available_time",
    "received_time",
    "source",
    "quality",
}
_INTRADAY_FIELDS = {
    "symbol",
    "interval",
    "bar_start",
    "bar_end",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "bid",
    "ask",
    "session_flag",
    "latency_ms",
    "event_time",
    "available_time",
    "received_time",
    "source",
    "quality",
}
_OPTIONS_FIELDS = {
    "chain_id",
    "contract_id",
    "occ_symbol",
    "underlying",
    "quote_time",
    "expiration",
    "strike",
    "option_type",
    "bid",
    "ask",
    "last",
    "bid_size",
    "ask_size",
    "volume",
    "open_interest",
    "implied_volatility",
    "delta",
    "gamma",
    "theta",
    "vega",
    "rho",
    "multiplier",
    "event_time",
    "available_time",
    "received_time",
    "source",
    "quality",
}
_RECORD_FIELDS = {
    "record_schema",
    "sequence",
    "batch_id",
    "feed",
    "source",
    "data_schema",
    "event_time_utc",
    "available_time_utc",
    "received_time_utc",
    "provider_cursor",
    "next_cursor",
    "quality_flags",
    "revision_of",
    "row_count",
    "content_sha256",
    "rows",
    "status",
    "validation_errors",
    "previous_record_sha256",
    "record_sha256",
}


def _safe_id(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"unsafe {label}: {value!r}")
    return normalized


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    return _aware_utc(parsed, label)


def _parse_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _quality(value: Any) -> None:
    if not isinstance(value, list) or any(
        not isinstance(flag, str) or not _SAFE_ID.fullmatch(flag) for flag in value
    ):
        raise ValueError("quality must be a list of safe string flags")
    if len(set(value)) != len(value):
        raise ValueError("quality flags must be unique")


def _canonical_rows(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Canonicalize rows through the project's mapping-typed helper."""

    return canonical_json({"rows": [dict(row) for row in rows]})


def _symbol(value: Any, label: str = "symbol") -> str:
    normalized = str(value).strip().upper()
    if not _SYMBOL.fullmatch(normalized):
        raise ValueError(f"{label} is invalid")
    return normalized


def _validate_ohlc(row: Mapping[str, Any]) -> None:
    values = {name: _finite(row[name], name) for name in ("open", "high", "low", "close")}
    if any(value <= 0 for value in values.values()):
        raise ValueError("OHLC values must be positive")
    if values["high"] < max(values["open"], values["low"], values["close"]):
        raise ValueError("high is below another OHLC value")
    if values["low"] > min(values["open"], values["high"], values["close"]):
        raise ValueError("low is above another OHLC value")


def _row_times(row: Mapping[str, Any]) -> tuple[datetime, datetime, datetime]:
    event = _parse_time(row["event_time"], "event_time")
    available = _parse_time(row["available_time"], "available_time")
    received = _parse_time(row["received_time"], "received_time")
    if not event <= available <= received:
        raise ValueError("row times must satisfy event <= available <= received")
    return event, available, received


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CollectionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json_strict(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    if path.is_symlink():
        raise CollectionError(f"collection input/record cannot be a symlink: {path}")
    before = path.stat()
    if not path.is_file() or before.st_size > maximum_bytes:
        raise CollectionError(f"collection input/record is irregular or too large: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        raw = os.read(descriptor, maximum_bytes + 1)
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.stat()
    if len(raw) > maximum_bytes:
        raise CollectionError(f"collection input/record exceeds size limit: {path}")
    if (
        before.st_ino != opened.st_ino
        or before.st_ino != after.st_ino
        or before.st_size != opened.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise CollectionError(f"collection input/record changed while being read: {path}")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionError(f"invalid collection JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CollectionError("collection JSON must be an object")
    return payload


def _atomic_create(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise CollectionError("immutable collection path cannot traverse a symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json(dict(payload)) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o400)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise CollectionError(f"immutable collection record exists: {path}") from exc
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    feed: FeedKind
    requested_at: datetime
    cursor: str | None = None
    resource: str | None = None

    def __post_init__(self) -> None:
        _aware_utc(self.requested_at, "requested_at")
        for label, value in (("cursor", self.cursor), ("resource", self.resource)):
            if value is not None and (not value.strip() or len(value) > _MAX_CURSOR_LENGTH):
                raise ValueError(f"{label} is empty or too long")


@dataclass(frozen=True, slots=True)
class IngestionEnvelope:
    batch_id: str
    feed: FeedKind
    source: str
    data_schema: str
    event_time: datetime
    available_time: datetime
    received_time: datetime
    rows: Sequence[Mapping[str, Any]]
    provider_cursor: str | None = None
    next_cursor: str | None = None
    quality_flags: tuple[str, ...] = ()
    revision_of: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.batch_id, "batch id")
        _safe_id(self.data_schema, "data schema")
        _safe_id(self.source, "source")
        _aware_utc(self.event_time, "event_time")
        _aware_utc(self.available_time, "available_time")
        _aware_utc(self.received_time, "received_time")
        if self.revision_of is not None:
            _safe_id(self.revision_of, "revision parent")
            if self.revision_of == self.batch_id:
                raise ValueError("a batch cannot revise itself")
        for label, value in (
            ("provider_cursor", self.provider_cursor),
            ("next_cursor", self.next_cursor),
        ):
            if value is not None and (not value.strip() or len(value) > _MAX_CURSOR_LENGTH):
                raise ValueError(f"{label} is empty or too long")
        if len(set(self.quality_flags)) != len(self.quality_flags) or any(
            not _SAFE_ID.fullmatch(flag) for flag in self.quality_flags
        ):
            raise ValueError("envelope quality flags must be unique safe IDs")
        _canonical_rows(self.rows)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> IngestionEnvelope:
        expected = {
            "batch_id",
            "feed",
            "source",
            "data_schema",
            "event_time",
            "available_time",
            "received_time",
            "rows",
            "provider_cursor",
            "next_cursor",
            "quality_flags",
            "revision_of",
        }
        if set(payload) != expected:
            raise ValueError(
                f"envelope fields differ: missing={sorted(expected - set(payload))}, "
                f"unexpected={sorted(set(payload) - expected)}"
            )
        rows = payload["rows"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("envelope rows must be a list of objects")
        flags = payload["quality_flags"]
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            raise ValueError("quality_flags must be a list of strings")
        return cls(
            batch_id=str(payload["batch_id"]),
            feed=FeedKind(str(payload["feed"])),
            source=str(payload["source"]),
            data_schema=str(payload["data_schema"]),
            event_time=_parse_time(payload["event_time"], "event_time"),
            available_time=_parse_time(payload["available_time"], "available_time"),
            received_time=_parse_time(payload["received_time"], "received_time"),
            rows=rows,
            provider_cursor=payload["provider_cursor"],
            next_cursor=payload["next_cursor"],
            quality_flags=tuple(flags),
            revision_of=payload["revision_of"],
        )


@dataclass(frozen=True, slots=True)
class BatchMetadata:
    sequence: int
    batch_id: str
    feed: FeedKind
    status: BatchStatus
    source: str
    data_schema: str
    row_count: int
    provider_cursor: str | None
    next_cursor: str | None
    revision_of: str | None
    validation_errors: tuple[str, ...]
    content_sha256: str
    previous_record_sha256: str
    record_sha256: str
    reused: bool = False


@runtime_checkable
class CollectionProvider(Protocol):
    """Injected adapter boundary; providers return one immutable envelope."""

    @property
    def provider_name(self) -> str: ...

    def fetch(self, request: CollectionRequest) -> IngestionEnvelope: ...


class FileCollectionProvider:
    """Read one strict envelope JSON from a configured, non-symlink root."""

    def __init__(self, root: str | Path, provider_name: str, *, maximum_bytes: int) -> None:
        configured_root = Path(root)
        if configured_root.is_symlink():
            raise CollectionError("file provider root cannot be a symlink")
        self.root = configured_root.resolve()
        if not self.root.is_dir():
            raise CollectionError("file provider root must be a regular directory")
        self._provider_name = _safe_id(provider_name, "provider name")
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        self.maximum_bytes = int(maximum_bytes)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def fetch(self, request: CollectionRequest) -> IngestionEnvelope:
        if request.resource is None:
            raise CollectionError("file provider requires request.resource")
        relative = Path(request.resource)
        if relative.is_absolute() or ".." in relative.parts:
            raise CollectionError("file provider resource escapes configured root")
        candidate = self.root
        for component in relative.parts:
            candidate = candidate / component
            if candidate.is_symlink():
                raise CollectionError("file provider resource traverses a symlink")
        candidate = candidate.resolve(strict=True)
        if not candidate.is_relative_to(self.root):
            raise CollectionError("file provider resource escapes configured root")
        envelope = IngestionEnvelope.from_mapping(
            _read_json_strict(candidate, maximum_bytes=self.maximum_bytes)
        )
        _validate_provider_response(self.provider_name, request, envelope)
        return envelope


class MockCollectionProvider:
    """Deterministic offline adapter keyed by feed and provider cursor."""

    def __init__(self, provider_name: str, envelopes: Sequence[IngestionEnvelope]) -> None:
        self._provider_name = _safe_id(provider_name, "provider name")
        self._envelopes = tuple(envelopes)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def fetch(self, request: CollectionRequest) -> IngestionEnvelope:
        matches = [
            envelope
            for envelope in self._envelopes
            if envelope.feed == request.feed and envelope.provider_cursor == request.cursor
        ]
        if len(matches) != 1:
            raise CollectionError(
                f"mock provider expected one batch for {request.feed}/{request.cursor!r}; "
                f"found {len(matches)}"
            )
        envelope = matches[0]
        _validate_provider_response(self.provider_name, request, envelope)
        return envelope


def _validate_provider_response(
    provider_name: str,
    request: CollectionRequest,
    envelope: IngestionEnvelope,
) -> None:
    if envelope.source != provider_name:
        raise CollectionError("provider response source does not match injected adapter")
    if envelope.feed != request.feed:
        raise CollectionError("provider returned the wrong feed")
    if envelope.provider_cursor != request.cursor:
        raise CollectionError("provider did not honor the requested cursor")
    if envelope.received_time > request.requested_at:
        raise CollectionError("provider response was received after requested_at")


def _error(errors: list[str], row_number: int, code: str) -> None:
    errors.append(f"ROW_{row_number:06d}:{code}")


def _validate_common(
    row: Mapping[str, Any],
    *,
    expected_fields: set[str],
    source: str,
) -> tuple[datetime, datetime, datetime]:
    if set(row) != expected_fields:
        raise ValueError("FIELD_SET_MISMATCH")
    if row["source"] != source:
        raise ValueError("SOURCE_MISMATCH")
    _quality(row["quality"])
    return _row_times(row)


def _validate_daily(row: Mapping[str, Any], source: str) -> tuple[datetime, datetime, datetime]:
    times = _validate_common(row, expected_fields=_DAILY_FIELDS, source=source)
    _symbol(row["symbol"])
    _parse_date(row["session"], "session")
    if row["calendar"] != "XNYS":
        raise ValueError("UNSUPPORTED_CALENDAR")
    _validate_ohlc(row)
    _nonnegative_integer(row["volume"], "volume")
    if _finite(row["adjusted_close"], "adjusted_close") <= 0:
        raise ValueError("ADJUSTED_CLOSE_NOT_POSITIVE")
    if _finite(row["total_return_factor"], "total_return_factor") <= 0:
        raise ValueError("TOTAL_RETURN_FACTOR_NOT_POSITIVE")
    if _finite(row["dividend"], "dividend") < 0:
        raise ValueError("DIVIDEND_NEGATIVE")
    if _finite(row["split_factor"], "split_factor") <= 0:
        raise ValueError("SPLIT_FACTOR_NOT_POSITIVE")
    action = row["corporate_action"]
    if action is not None and not isinstance(action, str):
        raise ValueError("CORPORATE_ACTION_INVALID")
    return times


def _validate_intraday(row: Mapping[str, Any], source: str) -> tuple[datetime, datetime, datetime]:
    times = _validate_common(row, expected_fields=_INTRADAY_FIELDS, source=source)
    _symbol(row["symbol"])
    interval_seconds = {"1m": 60, "5m": 300}.get(row["interval"])
    if interval_seconds is None:
        raise ValueError("UNSUPPORTED_INTERVAL")
    start = _parse_time(row["bar_start"], "bar_start")
    end = _parse_time(row["bar_end"], "bar_end")
    if (end - start).total_seconds() != interval_seconds:
        raise ValueError("BAR_DURATION_MISMATCH")
    if times[0] != end:
        raise ValueError("EVENT_TIME_NOT_BAR_END")
    _validate_ohlc(row)
    _nonnegative_integer(row["volume"], "volume")
    bid = _finite(row["bid"], "bid")
    ask = _finite(row["ask"], "ask")
    if bid < 0 or ask < 0 or bid > ask:
        raise ValueError("INVALID_MARKET")
    if row["session_flag"] not in {"PRE", "REGULAR", "POST"}:
        raise ValueError("INVALID_SESSION_FLAG")
    latency = _finite(row["latency_ms"], "latency_ms")
    observed_latency = (times[2] - times[0]).total_seconds() * 1000
    if latency < 0 or abs(latency - observed_latency) > 1.0:
        raise ValueError("LATENCY_MISMATCH")
    return times


def _optional_finite(row: Mapping[str, Any], field: str) -> float | None:
    return None if row[field] is None else _finite(row[field], field)


def _validate_options(row: Mapping[str, Any], source: str) -> tuple[datetime, datetime, datetime]:
    times = _validate_common(row, expected_fields=_OPTIONS_FIELDS, source=source)
    _safe_id(str(row["chain_id"]), "chain id")
    _safe_id(str(row["contract_id"]), "contract id")
    if not str(row["occ_symbol"]).strip():
        raise ValueError("OCC_SYMBOL_REQUIRED")
    _symbol(row["underlying"], "underlying")
    quote_time = _parse_time(row["quote_time"], "quote_time")
    if quote_time != times[0]:
        raise ValueError("EVENT_TIME_NOT_QUOTE_TIME")
    if _parse_date(row["expiration"], "expiration") < quote_time.date():
        raise ValueError("EXPIRED_CONTRACT")
    if _finite(row["strike"], "strike") <= 0:
        raise ValueError("STRIKE_NOT_POSITIVE")
    if row["option_type"] not in {"CALL", "PUT"}:
        raise ValueError("INVALID_OPTION_TYPE")
    bid = _finite(row["bid"], "bid")
    ask = _finite(row["ask"], "ask")
    last = _finite(row["last"], "last")
    if min(bid, ask, last) < 0 or bid > ask:
        raise ValueError("INVALID_MARKET")
    for field in ("bid_size", "ask_size", "volume", "open_interest"):
        _nonnegative_integer(row[field], field)
    if not isinstance(row["multiplier"], int) or isinstance(row["multiplier"], bool):
        raise ValueError("MULTIPLIER_NOT_INTEGER")
    if row["multiplier"] <= 0:
        raise ValueError("MULTIPLIER_NOT_POSITIVE")
    implied_volatility = _optional_finite(row, "implied_volatility")
    if implied_volatility is not None and implied_volatility < 0:
        raise ValueError("IMPLIED_VOLATILITY_NEGATIVE")
    delta = _optional_finite(row, "delta")
    gamma = _optional_finite(row, "gamma")
    if delta is not None and not -1 <= delta <= 1:
        raise ValueError("DELTA_OUT_OF_RANGE")
    if gamma is not None and gamma < 0:
        raise ValueError("GAMMA_NEGATIVE")
    for field in ("theta", "vega", "rho"):
        _optional_finite(row, field)
    return times


def validate_envelope(envelope: IngestionEnvelope, *, maximum_rows: int) -> tuple[str, ...]:
    """Return stable error codes; never returns raw values in an error."""

    errors: list[str] = []
    if envelope.data_schema != EXPECTED_SCHEMAS[envelope.feed]:
        errors.append("ENVELOPE:SCHEMA_MISMATCH")
    event = _aware_utc(envelope.event_time, "event_time")
    available = _aware_utc(envelope.available_time, "available_time")
    received = _aware_utc(envelope.received_time, "received_time")
    if not event <= available <= received:
        errors.append("ENVELOPE:TIME_ORDER")
    if not envelope.rows:
        errors.append("ENVELOPE:EMPTY_BATCH")
    if len(envelope.rows) > maximum_rows:
        errors.append("ENVELOPE:ROW_LIMIT")

    validator = {
        FeedKind.DAILY: _validate_daily,
        FeedKind.INTRADAY: _validate_intraday,
        FeedKind.OPTIONS: _validate_options,
    }[envelope.feed]
    row_times: list[tuple[datetime, datetime, datetime]] = []
    identities: set[tuple[Any, ...]] = set()
    intraday_order: dict[tuple[str, str], tuple[datetime, str]] = {}
    chain_identity: tuple[str, str, datetime] | None = None
    for row_number, row in enumerate(envelope.rows, start=1):
        try:
            times = validator(row, envelope.source)
            row_times.append(times)
            if envelope.feed == FeedKind.DAILY:
                identity: tuple[Any, ...] = (row["symbol"], row["session"])
            elif envelope.feed == FeedKind.INTRADAY:
                identity = (row["symbol"], row["interval"], row["bar_start"])
                key = (str(row["symbol"]), str(row["interval"]))
                start = _parse_time(row["bar_start"], "bar_start")
                previous = intraday_order.get(key)
                if previous is not None:
                    previous_start, previous_session = previous
                    interval = {"1m": 60, "5m": 300}[str(row["interval"])]
                    if start <= previous_start:
                        raise ValueError("OUT_OF_ORDER")
                    if (
                        str(row["session_flag"]) == previous_session
                        and start.date() == previous_start.date()
                        and (start - previous_start).total_seconds() > interval
                    ):
                        raise ValueError("MISSING_BAR")
                intraday_order[key] = (start, str(row["session_flag"]))
            else:
                quote_time = _parse_time(row["quote_time"], "quote_time")
                identity = (row["contract_id"], row["quote_time"])
                current_chain = (str(row["chain_id"]), str(row["underlying"]), quote_time)
                if chain_identity is None:
                    chain_identity = current_chain
                elif chain_identity != current_chain:
                    raise ValueError("MIXED_CHAIN_SNAPSHOT")
            if identity in identities:
                raise ValueError("DUPLICATE_ROW")
            identities.add(identity)
        except (KeyError, TypeError, ValueError) as exc:
            code = str(exc) or type(exc).__name__
            _error(errors, row_number, re.sub(r"[^A-Z0-9_]+", "_", code.upper())[:80])
        if len(errors) >= 100:
            errors.append("ENVELOPE:ERROR_LIMIT_REACHED")
            break
    if row_times:
        if min(item[0] for item in row_times) != event:
            errors.append("ENVELOPE:EVENT_TIME_NOT_MINIMUM")
        if max(item[1] for item in row_times) != available:
            errors.append("ENVELOPE:AVAILABLE_TIME_NOT_MAXIMUM")
        if max(item[2] for item in row_times) != received:
            errors.append("ENVELOPE:RECEIVED_TIME_NOT_MAXIMUM")
    return tuple(dict.fromkeys(errors))


def _revision_errors(
    envelope: IngestionEnvelope,
    records: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    errors: list[str] = []
    parent = records.get(envelope.revision_of) if envelope.revision_of else None
    if envelope.revision_of and parent is None:
        errors.append("REVISION:PARENT_ABSENT")
    elif parent is not None:
        if parent["status"] != BatchStatus.TRUSTED.value:
            errors.append("REVISION:PARENT_NOT_TRUSTED")
        if parent["feed"] != envelope.feed.value:
            errors.append("REVISION:FEED_MISMATCH")
        if parent["source"] != envelope.source:
            errors.append("REVISION:SOURCE_MISMATCH")
        if parent["data_schema"] != envelope.data_schema:
            errors.append("REVISION:SCHEMA_MISMATCH")
    return errors


class CollectionStore:
    """Append-only trusted/quarantine records with one global hash chain."""

    def __init__(
        self,
        root: str | Path,
        *,
        maximum_batch_bytes: int = 20_000_000,
        maximum_rows: int = 100_000,
    ) -> None:
        self.root = Path(root)
        if self.root.exists() and self.root.is_symlink():
            raise CollectionError("collection root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if maximum_batch_bytes <= 0 or maximum_rows <= 0:
            raise ValueError("collection limits must be positive")
        self.maximum_batch_bytes = int(maximum_batch_bytes)
        self.maximum_rows = int(maximum_rows)
        for status in BatchStatus:
            for feed in FeedKind:
                path = self.root / status.value / feed.value
                if path.exists() and path.is_symlink():
                    raise CollectionError("collection status/feed path cannot be a symlink")
                path.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".append.lock"

    def _lock(self) -> int:
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor

    def _record_paths(self) -> list[Path]:
        allowed_root = {"trusted", "quarantined", ".append.lock"}
        unexpected_root = [
            path.name for path in self.root.iterdir() if path.name not in allowed_root
        ]
        if unexpected_root:
            raise CollectionChainError(f"unexpected collection root entries: {unexpected_root}")
        paths: list[Path] = []
        for status in BatchStatus:
            status_path = self.root / status.value
            if status_path.is_symlink() or not status_path.is_dir():
                raise CollectionChainError(f"invalid collection status directory: {status_path}")
            allowed_feeds = {feed.value for feed in FeedKind}
            unexpected_feeds = [
                path.name for path in status_path.iterdir() if path.name not in allowed_feeds
            ]
            if unexpected_feeds:
                raise CollectionChainError(
                    f"unexpected collection feed entries: {unexpected_feeds}"
                )
            for feed in FeedKind:
                feed_path = status_path / feed.value
                if feed_path.is_symlink() or not feed_path.is_dir():
                    raise CollectionChainError(f"invalid collection feed directory: {feed_path}")
                for path in feed_path.iterdir():
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or not re.fullmatch(r"\d{12}_[0-9a-f]{64}\.json", path.name)
                    ):
                        raise CollectionChainError(f"unexpected collection record: {path}")
                    paths.append(path)
        return sorted(paths, key=lambda path: path.name)

    @staticmethod
    def _metadata(payload: Mapping[str, Any], *, reused: bool = False) -> BatchMetadata:
        return BatchMetadata(
            sequence=int(payload["sequence"]),
            batch_id=str(payload["batch_id"]),
            feed=FeedKind(str(payload["feed"])),
            status=BatchStatus(str(payload["status"])),
            source=str(payload["source"]),
            data_schema=str(payload["data_schema"]),
            row_count=int(payload["row_count"]),
            provider_cursor=payload["provider_cursor"],
            next_cursor=payload["next_cursor"],
            revision_of=payload["revision_of"],
            validation_errors=tuple(payload["validation_errors"]),
            content_sha256=str(payload["content_sha256"]),
            previous_record_sha256=str(payload["previous_record_sha256"]),
            record_sha256=str(payload["record_sha256"]),
            reused=reused,
        )

    def _verify_locked(self) -> tuple[list[BatchMetadata], dict[str, dict[str, Any]]]:
        metadata: list[BatchMetadata] = []
        records: dict[str, dict[str, Any]] = {}
        previous_hash = _ZERO_HASH
        for expected_sequence, path in enumerate(self._record_paths(), start=1):
            payload = _read_json_strict(path, maximum_bytes=self.maximum_batch_bytes)
            if set(payload) != _RECORD_FIELDS:
                raise CollectionChainError("collection record fields are not exact")
            if payload.get("record_schema") != "phase3_collection_record_v1":
                raise CollectionChainError("collection record schema is invalid")
            record_hash = str(payload.get("record_sha256", ""))
            hashed = dict(payload)
            hashed.pop("record_sha256", None)
            if record_hash != sha256_bytes(canonical_json(hashed)):
                raise CollectionChainError("collection record content hash is invalid")
            expected_name = f"{expected_sequence:012d}_{record_hash}.json"
            if path.name != expected_name or payload.get("sequence") != expected_sequence:
                raise CollectionChainError("collection sequence or filename is invalid")
            if payload.get("previous_record_sha256") != previous_hash:
                raise CollectionChainError("collection previous-record hash is broken")
            try:
                feed = FeedKind(str(payload["feed"]))
                status = BatchStatus(str(payload["status"]))
                batch_id = _safe_id(str(payload["batch_id"]), "batch id")
            except (KeyError, ValueError) as exc:
                raise CollectionChainError("collection record identity is invalid") from exc
            if path.parent != self.root / status.value / feed.value:
                raise CollectionChainError(
                    "collection record is in the wrong status/feed partition"
                )
            rows = payload.get("rows")
            if (
                not isinstance(rows, list)
                or any(not isinstance(row, dict) for row in rows)
                or payload.get("row_count") != len(rows)
            ):
                raise CollectionChainError("collection row count is invalid")
            if payload.get("content_sha256") != sha256_bytes(_canonical_rows(rows)):
                raise CollectionChainError("collection raw content hash is invalid")
            if batch_id in records:
                raise CollectionChainError(f"duplicate collection batch id: {batch_id}")
            revision_of = payload.get("revision_of")
            if revision_of is not None and revision_of == batch_id:
                raise CollectionChainError("collection batch revises itself")
            try:
                envelope = IngestionEnvelope(
                    batch_id=batch_id,
                    feed=feed,
                    source=str(payload["source"]),
                    data_schema=str(payload["data_schema"]),
                    event_time=_parse_time(payload["event_time_utc"], "event_time_utc"),
                    available_time=_parse_time(payload["available_time_utc"], "available_time_utc"),
                    received_time=_parse_time(payload["received_time_utc"], "received_time_utc"),
                    rows=rows,
                    provider_cursor=payload["provider_cursor"],
                    next_cursor=payload["next_cursor"],
                    quality_flags=tuple(payload["quality_flags"]),
                    revision_of=revision_of,
                )
                expected_errors = list(validate_envelope(envelope, maximum_rows=self.maximum_rows))
                expected_errors.extend(_revision_errors(envelope, records))
            except (KeyError, TypeError, ValueError) as exc:
                raise CollectionChainError("collection envelope cannot be reconstructed") from exc
            expected_errors = list(dict.fromkeys(expected_errors))
            if payload["validation_errors"] != expected_errors:
                raise CollectionChainError("collection validation result is inconsistent")
            expected_status = BatchStatus.QUARANTINED if expected_errors else BatchStatus.TRUSTED
            if status != expected_status:
                raise CollectionChainError("collection trusted/quarantine status is inconsistent")
            records[batch_id] = payload
            metadata.append(self._metadata(payload))
            previous_hash = record_hash
        return metadata, records

    def verify_chain(self) -> list[BatchMetadata]:
        descriptor = self._lock()
        try:
            metadata, _ = self._verify_locked()
            return metadata
        finally:
            os.close(descriptor)

    def append(self, envelope: IngestionEnvelope) -> BatchMetadata:
        descriptor = self._lock()
        try:
            metadata, records = self._verify_locked()
            raw_rows = [dict(row) for row in envelope.rows]
            content_hash = sha256_bytes(_canonical_rows(raw_rows))
            identity = {
                "batch_id": envelope.batch_id,
                "feed": envelope.feed.value,
                "source": envelope.source,
                "data_schema": envelope.data_schema,
                "event_time_utc": _aware_utc(envelope.event_time, "event_time").isoformat(),
                "available_time_utc": _aware_utc(
                    envelope.available_time, "available_time"
                ).isoformat(),
                "received_time_utc": _aware_utc(
                    envelope.received_time, "received_time"
                ).isoformat(),
                "provider_cursor": envelope.provider_cursor,
                "next_cursor": envelope.next_cursor,
                "quality_flags": list(envelope.quality_flags),
                "revision_of": envelope.revision_of,
                "row_count": len(raw_rows),
                "content_sha256": content_hash,
                "rows": raw_rows,
            }
            existing = records.get(envelope.batch_id)
            if existing is not None:
                comparable = {key: existing[key] for key in identity}
                if comparable != identity:
                    raise CollectionError(
                        f"batch id {envelope.batch_id!r} conflicts with immutable content"
                    )
                return self._metadata(existing, reused=True)

            errors = list(validate_envelope(envelope, maximum_rows=self.maximum_rows))
            errors.extend(_revision_errors(envelope, records))
            status = BatchStatus.QUARANTINED if errors else BatchStatus.TRUSTED
            payload: dict[str, Any] = {
                "record_schema": "phase3_collection_record_v1",
                "sequence": len(metadata) + 1,
                **identity,
                "status": status.value,
                "validation_errors": list(dict.fromkeys(errors)),
                "previous_record_sha256": metadata[-1].record_sha256 if metadata else _ZERO_HASH,
            }
            encoded = canonical_json(payload)
            if len(encoded) + 100 > self.maximum_batch_bytes:
                raise CollectionError("collection record exceeds maximum_batch_bytes")
            payload["record_sha256"] = sha256_bytes(encoded)
            path = (
                self.root
                / status.value
                / envelope.feed.value
                / f"{payload['sequence']:012d}_{payload['record_sha256']}.json"
            )
            _atomic_create(path, payload)
            return self._metadata(payload)
        finally:
            os.close(descriptor)

    def latest_trusted(self, feed: FeedKind, source: str) -> BatchMetadata | None:
        _safe_id(source, "source")
        matching = [
            item
            for item in self.verify_chain()
            if item.feed == feed and item.source == source and item.status == BatchStatus.TRUSTED
        ]
        return matching[-1] if matching else None

    def resume_cursor(self, feed: FeedKind, source: str) -> str | None:
        latest = self.latest_trusted(feed, source)
        return None if latest is None else latest.next_cursor

    def status_manifest(self) -> dict[str, Any]:
        chain = self.verify_chain()
        feeds: dict[str, dict[str, Any]] = {}
        for feed in FeedKind:
            selected = [item for item in chain if item.feed == feed]
            trusted = [item for item in selected if item.status == BatchStatus.TRUSTED]
            feeds[feed.value] = {
                "batches": len(selected),
                "trusted": len(trusted),
                "quarantined": len(selected) - len(trusted),
                "latest_trusted_batch_id": trusted[-1].batch_id if trusted else None,
                "latest_trusted_record_sha256": trusted[-1].record_sha256 if trusted else None,
            }
        return {
            "schema_version": 1,
            "mode": "COLLECT_ONLY",
            "strategy_consumption_enabled": False,
            "records": len(chain),
            "latest_record_sha256": chain[-1].record_sha256 if chain else None,
            "feeds": feeds,
        }


class CollectionIngestor:
    """Fetch exactly one batch from an injected provider and append it."""

    def __init__(self, store: CollectionStore, provider: CollectionProvider) -> None:
        if not isinstance(provider, CollectionProvider):
            raise TypeError("provider does not satisfy CollectionProvider")
        self.store = store
        self.provider = provider

    def ingest(self, request: CollectionRequest) -> BatchMetadata:
        envelope = self.provider.fetch(request)
        _validate_provider_response(self.provider.provider_name, request, envelope)
        return self.store.append(envelope)


def load_envelope_file(path: str | Path, *, maximum_bytes: int) -> IngestionEnvelope:
    """Strict loader shared by the file and CLI mock paths."""

    return IngestionEnvelope.from_mapping(
        _read_json_strict(Path(path), maximum_bytes=maximum_bytes)
    )
