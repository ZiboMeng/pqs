"""Append-only official-listing snapshots for the free prospective PIT lane."""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from core.data.pit_contract import PitDataContract
from core.data.pit_security_master import FREE_PROSPECTIVE_PIT


class ProspectivePitError(RuntimeError):
    """Prospective snapshot or hash-chain integrity failure."""


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_bytes(payload: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def parse_sec_company_tickers_exchange(content: bytes) -> list[dict[str, Any]]:
    payload = json.loads(content.decode("utf-8"))
    if payload.get("fields") != ["cik", "name", "ticker", "exchange"]:
        raise ProspectivePitError("unexpected SEC ticker-exchange schema")
    rows = []
    for raw in payload.get("data", []):
        if not isinstance(raw, list) or len(raw) != 4:
            raise ProspectivePitError("malformed SEC ticker-exchange row")
        cik, name, ticker, exchange = raw
        symbol = str(ticker).upper().strip()
        if not symbol:
            continue
        rows.append(
            {
                "record_key": f"sec:{int(cik)}:{symbol}:{str(exchange).strip()}",
                "source_id": "sec_company_tickers_exchange",
                "ticker": symbol,
                "security_name": str(name).strip(),
                "exchange": str(exchange).strip(),
                "cik": int(cik),
                "evidence_scope": FREE_PROSPECTIVE_PIT,
            }
        )
    return sorted(rows, key=lambda row: row["record_key"])


def _parse_pipe_rows(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    rows: list[dict[str, str]] = []
    for row in reader:
        if not row or None in row:
            continue
        normalized = {str(key): str(value or "").strip() for key, value in row.items()}
        if any(value.startswith("File Creation Time") for value in normalized.values()):
            continue
        rows.append(normalized)
    return rows


def parse_nasdaq_listed(content: bytes) -> list[dict[str, Any]]:
    output = []
    for row in _parse_pipe_rows(content):
        ticker = row.get("Symbol", "").upper()
        if not ticker or row.get("Test Issue") != "N":
            continue
        output.append(
            {
                "record_key": f"nasdaq:NASDAQ:{ticker}",
                "source_id": "nasdaq_listed",
                "ticker": ticker,
                "security_name": row.get("Security Name", ""),
                "exchange": "NASDAQ",
                "is_etf": row.get("ETF") == "Y",
                "is_test_issue": False,
                "financial_status": row.get("Financial Status", ""),
                "evidence_scope": FREE_PROSPECTIVE_PIT,
            }
        )
    return sorted(output, key=lambda record: record["record_key"])


def parse_other_listed(content: bytes) -> list[dict[str, Any]]:
    exchange_names = {"A": "NYSE_AMERICAN", "N": "NYSE", "P": "NYSE_ARCA", "Z": "CBOE"}
    output = []
    for row in _parse_pipe_rows(content):
        ticker = row.get("ACT Symbol", "").upper()
        if not ticker or row.get("Test Issue") != "N":
            continue
        exchange_code = row.get("Exchange", "")
        exchange = exchange_names.get(exchange_code, exchange_code)
        output.append(
            {
                "record_key": f"other:{exchange}:{ticker}",
                "source_id": "other_listed",
                "ticker": ticker,
                "security_name": row.get("Security Name", ""),
                "exchange": exchange,
                "is_etf": row.get("ETF") == "Y",
                "is_test_issue": False,
                "evidence_scope": FREE_PROSPECTIVE_PIT,
            }
        )
    return sorted(output, key=lambda record: record["record_key"])


PARSERS = {
    "sec_company_tickers_exchange": parse_sec_company_tickers_exchange,
    "nasdaq_listed": parse_nasdaq_listed,
    "other_listed": parse_other_listed,
}


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ProspectivePitError(
                    f"invalid ledger JSON at line {line_number}"
                ) from exc
    return rows


def verify_prospective_ledger(output_root: str | Path) -> dict[str, Any]:
    root = Path(output_root)
    rows = _read_ledger(root / "ledger.jsonl")
    previous = None
    for index, row in enumerate(rows):
        stored_hash = row.get("event_sha256")
        body = {key: value for key, value in row.items() if key != "event_sha256"}
        expected = _sha256_bytes(_canonical_json(body))
        if stored_hash != expected:
            raise ProspectivePitError(f"ledger event hash mismatch at index {index}")
        if body.get("previous_event_sha256") != previous:
            raise ProspectivePitError(f"ledger previous hash mismatch at index {index}")
        batch = root / "snapshots" / body["batch_id"]
        manifest = batch / "manifest.json"
        if not manifest.exists() or _sha256_bytes(manifest.read_bytes()) != body.get(
            "manifest_sha256"
        ):
            raise ProspectivePitError(f"ledger manifest mismatch at index {index}")
        previous = stored_hash
    return {
        "events": len(rows),
        "head_event_sha256": previous,
        "integrity_pass": True,
    }


def collect_prospective_snapshot(
    source_payloads: Mapping[str, Mapping[str, Any]],
    *,
    output_root: str | Path,
    captured_at: str | datetime,
    contract: PitDataContract,
) -> dict[str, Any]:
    """Store one immutable listing snapshot and append a hash-chain event."""

    contract.assert_operation_allowed("prospective_collection")
    timestamp = pd_timestamp_utc(captured_at)
    batch_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    root = Path(output_root)
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    final_batch = snapshots / batch_id
    if final_batch.exists():
        raise ProspectivePitError(f"snapshot batch already exists: {batch_id}")
    building = snapshots / f".{batch_id}.building"
    if building.exists():
        raise ProspectivePitError(f"incomplete building directory exists: {building}")
    building.mkdir()

    raw_manifest: dict[str, Any] = {}
    normalized: list[dict[str, Any]] = []
    try:
        raw_dir = building / "raw"
        raw_dir.mkdir()
        for source_id in sorted(source_payloads):
            if source_id not in PARSERS:
                raise ProspectivePitError(f"unsupported prospective source {source_id}")
            source = source_payloads[source_id]
            content = source.get("content")
            if not isinstance(content, bytes) or not content:
                raise ProspectivePitError(f"{source_id} content must be non-empty bytes")
            suffix = "json" if source_id.startswith("sec_") else "txt"
            raw_path = raw_dir / f"{source_id}.{suffix}"
            _atomic_bytes(content, raw_path)
            parsed = PARSERS[source_id](content)
            normalized.extend(parsed)
            raw_manifest[source_id] = {
                "url": str(source.get("url", "")),
                "content_type": str(source.get("content_type", "")),
                "etag": str(source.get("etag", "")),
                "last_modified": str(source.get("last_modified", "")),
                "bytes": len(content),
                "sha256": _sha256_bytes(content),
                "records": len(parsed),
                "raw_relative_path": str(raw_path.relative_to(building)),
            }

        normalized.sort(key=lambda record: record["record_key"])
        keys = [record["record_key"] for record in normalized]
        if len(keys) != len(set(keys)):
            raise ProspectivePitError("duplicate normalized prospective record keys")
        normalized_path = building / "normalized_records.json"
        _atomic_bytes(
            json.dumps(normalized, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            normalized_path,
        )

        ledger_path = root / "ledger.jsonl"
        prior_events = _read_ledger(ledger_path)
        prior_records: list[dict[str, Any]] = []
        if prior_events:
            previous_batch = snapshots / prior_events[-1]["batch_id"]
            prior_records = json.loads(
                (previous_batch / "normalized_records.json").read_text(encoding="utf-8")
            )
        prior_by_key = {record["record_key"]: record for record in prior_records}
        current_by_key = {record["record_key"]: record for record in normalized}
        added = sorted(set(current_by_key) - set(prior_by_key))
        removed = sorted(set(prior_by_key) - set(current_by_key))
        changed = sorted(
            key
            for key in set(current_by_key) & set(prior_by_key)
            if current_by_key[key] != prior_by_key[key]
        )
        diff = {
            "baseline_snapshot": not bool(prior_events),
            "added_keys": added,
            "removed_keys": removed,
            "changed_keys": changed,
        }
        _atomic_bytes(
            json.dumps(diff, indent=2, sort_keys=True).encode("utf-8") + b"\n",
            building / "diff.json",
        )
        manifest = {
            "schema_version": 1,
            "batch_id": batch_id,
            "captured_at_utc": timestamp.isoformat(),
            "contract_id": contract.contract_id,
            "evidence_scope": FREE_PROSPECTIVE_PIT,
            "raw_sources": raw_manifest,
            "normalized_records": len(normalized),
            "normalized_sha256": _sha256_bytes(normalized_path.read_bytes()),
            "diff_counts": {
                "added": len(added),
                "removed": len(removed),
                "changed": len(changed),
            },
            "directional_compute_performed": False,
        }
        contract.assert_artifact_non_directional(manifest)
        manifest_bytes = (
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        )
        _atomic_bytes(manifest_bytes, building / "manifest.json")
        os.replace(building, final_batch)

        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / "ledger.lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            existing = _read_ledger(ledger_path)
            expected_previous = existing[-1]["event_sha256"] if existing else None
            if len(existing) != len(prior_events):
                raise ProspectivePitError("prospective ledger changed during collection")
            event_body = {
                "schema_version": 1,
                "batch_id": batch_id,
                "captured_at_utc": timestamp.isoformat(),
                "manifest_sha256": _sha256_bytes(
                    (final_batch / "manifest.json").read_bytes()
                ),
                "previous_event_sha256": expected_previous,
            }
            event = {
                **event_body,
                "event_sha256": _sha256_bytes(_canonical_json(event_body)),
            }
            with ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        verification = verify_prospective_ledger(root)
        return {**manifest, "ledger": verification}
    except Exception:
        if building.exists():
            for child in sorted(building.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            building.rmdir()
        raise


def pd_timestamp_utc(value: str | datetime):
    # Local import keeps the parser-only surface dependency-light.
    import pandas as pd

    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


__all__ = [
    "PARSERS",
    "ProspectivePitError",
    "collect_prospective_snapshot",
    "parse_nasdaq_listed",
    "parse_other_listed",
    "parse_sec_company_tickers_exchange",
    "verify_prospective_ledger",
]
