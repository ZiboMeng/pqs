#!/usr/bin/env python3
"""Build a resumable immutable Yahoo corporate-action response corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.data.yahoo_corporate_actions import (  # noqa: E402
    parse_yahoo_corporate_actions,
    yahoo_symbol,
)

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True,
    ).strip()


def _epoch(date: str) -> int:
    stamp = pd.Timestamp(date)
    if stamp.tzinfo is not None:
        raise ValueError("corporate-action boundaries must be timezone-naive dates")
    return int(stamp.tz_localize("UTC").timestamp())


def _atomic_bytes(payload: bytes, path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    _atomic_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        path,
    )


def _append_journal(path: Path, row: dict[str, Any]) -> None:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _read_journal(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            symbol = str(row["symbol"])
            if symbol in rows:
                raise RuntimeError(
                    f"duplicate Yahoo journal symbol at line {line_number}: {symbol}"
                )
            rows[symbol] = row
    return rows


def _fetch(
    session: requests.Session,
    *,
    symbol: str,
    period1: int,
    period2: int,
    interval_seconds: float,
    last_request_at: float,
) -> tuple[requests.Response, float]:
    wait = interval_seconds - (time.monotonic() - last_request_at)
    if wait > 0:
        time.sleep(wait)
    response: requests.Response | None = None
    for attempt in range(6):
        requested_at = time.monotonic()
        response = session.get(
            YAHOO_CHART_URL.format(symbol=yahoo_symbol(symbol)),
            params={
                "period1": period1,
                "period2": period2,
                "interval": "3mo",
                "events": "div,splits",
                "includeAdjustedClose": "false",
            },
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PQS governed research)",
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=60,
        )
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
            return response, requested_at
        if attempt == 5:
            response.raise_for_status()
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after else min(60.0, 2.0 ** attempt)
        time.sleep(delay)
        last_request_at = time.monotonic()
    raise AssertionError("unreachable Yahoo retry state")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--through", default="2024-12-31")
    parser.add_argument("--requests-per-second", type=float, default=2.0)
    args = parser.parse_args()
    if not 0 < args.requests_per_second <= 5:
        raise ValueError("Yahoo requests-per-second must be in (0, 5]")
    start = pd.Timestamp(args.start).normalize()
    through = pd.Timestamp(args.through).normalize()
    if start > through:
        raise ValueError("corporate-action start cannot follow through")

    pool_path = (PROJ / args.pool).resolve()
    pool = json.loads(pool_path.read_text())
    symbols = [row["ticker"] for row in pool["selected"]] + ["SPY"]
    if len(symbols) != len(set(symbols)):
        raise ValueError("corporate-action symbol set contains duplicates")
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"corporate-action corpus is immutable: {output_root}")
    partial = output_root.with_name(f".{output_root.name}.partial")
    partial.mkdir(parents=True, exist_ok=True)
    raw_dir = partial / "raw"
    raw_dir.mkdir(exist_ok=True)
    intent = {
        "pool_artifact_sha256": pool["artifact_sha256"],
        "pool_file_sha256": _sha256_file(pool_path),
        "symbols": symbols,
        "start": str(start.date()),
        "through": str(through.date()),
        "requests_per_second_cap": args.requests_per_second,
        "builder_commit": _git_commit(),
        "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
        "parser_module_sha256": _sha256_file(
            PROJ / "core/data/yahoo_corporate_actions.py"),
    }
    intent_path = partial / "build_intent.json"
    if intent_path.exists():
        if json.loads(intent_path.read_text()) != intent:
            raise RuntimeError(
                f"partial corpus intent differs; inspect before removal: {partial}"
            )
    else:
        _atomic_json(intent, intent_path)

    journal_path = partial / "fetch_journal.jsonl"
    journal = _read_journal(journal_path)
    session = requests.Session()
    last_request_at = float("-inf")
    interval_seconds = 1.0 / args.requests_per_second
    period1 = _epoch(str(start.date()))
    period2 = _epoch(str((through + pd.Timedelta(days=1)).date()))
    for position, symbol in enumerate(symbols, start=1):
        storage_name = f"{symbol.replace('.', '_')}.json"
        if symbol in journal:
            row = journal[symbol]
            raw_path = raw_dir / row["storage_name"]
            if raw_path.exists() and _sha256_file(raw_path) == row["response_sha256"]:
                continue
            raise RuntimeError(f"Yahoo journal/file mismatch for {symbol}")
        response, last_request_at = _fetch(
            session,
            symbol=symbol,
            period1=period1,
            period2=period2,
            interval_seconds=interval_seconds,
            last_request_at=last_request_at,
        )
        content = response.content
        if not content:
            raise RuntimeError(f"empty Yahoo chart response for {symbol}")
        try:
            payload = response.json()
            parsed = parse_yahoo_corporate_actions(
                payload, expected_symbol=symbol)
        except (requests.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"invalid Yahoo response for {symbol}: {exc}") from exc
        raw_path = raw_dir / storage_name
        _atomic_bytes(content, raw_path)
        row = {
            "symbol": symbol,
            "vendor_symbol": parsed.vendor_symbol,
            "storage_name": storage_name,
            "url": response.url,
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "response_bytes": len(content),
            "response_sha256": _sha256_bytes(content),
            "distribution_events": len(parsed.distributions),
            "split_events": len(parsed.splits),
        }
        _append_journal(journal_path, row)
        journal[symbol] = row
        if position % 25 == 0 or position == len(symbols):
            print(
                f"symbols {position}/{len(symbols)} downloaded={len(journal)}",
                flush=True,
            )

    if set(journal) != set(symbols):
        raise RuntimeError("Yahoo journal symbol set differs from governed pool")
    distribution_frames: list[pd.DataFrame] = []
    split_frames: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        row = journal[symbol]
        raw_path = raw_dir / row["storage_name"]
        if _sha256_file(raw_path) != row["response_sha256"]:
            raise RuntimeError(f"Yahoo raw response hash changed for {symbol}")
        payload = json.loads(raw_path.read_bytes())
        parsed = parse_yahoo_corporate_actions(payload, expected_symbol=symbol)
        distributions = parsed.distributions.copy()
        splits = parsed.splits.copy()
        for frame in (distributions, splits):
            frame["source"] = "yahoo_chart_v8"
            frame["raw_response_sha256"] = row["response_sha256"]
        distribution_frames.append(distributions)
        split_frames.append(splits)
        coverage_rows.append({
            "symbol": symbol,
            "vendor_symbol": parsed.vendor_symbol,
            "checked_start": start,
            "checked_end": through,
            "status": "QUERY_OK",
            "distribution_event_count": len(distributions),
            "split_event_count": len(splits),
            "raw_response_sha256": row["response_sha256"],
        })
    distributions = pd.concat(distribution_frames, ignore_index=True)
    splits = pd.concat(split_frames, ignore_index=True)
    coverage = pd.DataFrame(coverage_rows)
    provenance = pd.DataFrame([journal[symbol] for symbol in symbols])
    paths = {
        "vendor_distributions": partial / "vendor_distributions.parquet",
        "vendor_splits": partial / "vendor_splits.parquet",
        "query_coverage": partial / "query_coverage.parquet",
        "response_provenance": partial / "response_provenance.parquet",
    }
    distributions.to_parquet(paths["vendor_distributions"], index=False)
    splits.to_parquet(paths["vendor_splits"], index=False)
    coverage.to_parquet(paths["query_coverage"], index=False)
    provenance.to_parquet(paths["response_provenance"], index=False)
    raw_identity = [
        {
            "symbol": symbol,
            "sha256": journal[symbol]["response_sha256"],
            "bytes": journal[symbol]["response_bytes"],
        }
        for symbol in symbols
    ]
    manifest = {
        "schema_version": 1,
        "corpus_id": output_root.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        **intent,
        "source": "Yahoo Finance chart v8 (unofficial)",
        "immutable": True,
        "responses": len(provenance),
        "response_bytes": int(provenance["response_bytes"].sum()),
        "raw_response_identity_sha256": _sha256_json(raw_identity),
        "distribution_events": len(distributions),
        "split_events": len(splits),
        **{
            f"{name}_sha256": _sha256_file(path)
            for name, path in paths.items()
        },
        "evidence_scope": "CORPORATE_ACTION_QUERY_CORPUS_NOT_YET_CERTIFIED",
        "automatic_promotion_eligible": False,
    }
    _atomic_json(manifest, partial / "manifest.json")
    os.replace(partial, output_root)
    print(f"corporate_action_corpus={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
