#!/usr/bin/env python3
"""Build a resumable Yahoo split-adjusted + total-return daily snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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

from core.data.yahoo_corporate_actions import yahoo_symbol  # noqa: E402
from core.data.yahoo_daily_snapshot import (  # noqa: E402
    corporate_actions_match,
    parse_yahoo_daily_bars,
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
    return _sha256_bytes(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8"))


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True,
    ).strip()


def _epoch(date: str) -> int:
    stamp = pd.Timestamp(date)
    if stamp.tzinfo is not None:
        raise ValueError("Yahoo snapshot boundaries must be timezone-naive dates")
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
    output: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        symbol = str(row["symbol"])
        if symbol in output:
            raise RuntimeError(
                f"duplicate Yahoo daily journal symbol at line {line_number}: {symbol}"
            )
        output[symbol] = row
    return output


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
    for attempt in range(6):
        requested_at = time.monotonic()
        response = session.get(
            YAHOO_CHART_URL.format(symbol=yahoo_symbol(symbol)),
            params={
                "period1": period1,
                "period2": period2,
                "interval": "1d",
                "events": "div,splits",
                "includeAdjustedClose": "true",
            },
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PQS governed research)",
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=90,
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
    raise AssertionError("unreachable Yahoo daily retry state")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--corporate-action-corpus-root", required=True)
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
        raise ValueError("Yahoo snapshot start cannot follow through")

    pool_path = (PROJ / args.pool).resolve()
    pool = json.loads(pool_path.read_text())
    symbols = [row["ticker"] for row in pool["selected"]] + ["SPY"]
    corp_root = Path(args.corporate_action_corpus_root).resolve()
    corp_manifest_path = corp_root / "manifest.json"
    corp_manifest = json.loads(corp_manifest_path.read_text())
    if (
        corp_manifest.get("pool_artifact_sha256") != pool["artifact_sha256"]
        or corp_manifest.get("start") != str(start.date())
        or corp_manifest.get("through") != str(through.date())
        or corp_manifest.get("symbols") != symbols
    ):
        raise RuntimeError("corporate-action corpus identity differs from snapshot intent")
    corp_provenance = pd.read_parquet(corp_root / "response_provenance.parquet")
    if len(corp_provenance) != len(symbols):
        raise RuntimeError("corporate-action provenance symbol count mismatch")
    corp_rows = corp_provenance.set_index("symbol", drop=False).to_dict("index")

    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"Yahoo daily snapshot is immutable: {output_root}")
    partial = output_root.with_name(f".{output_root.name}.partial")
    partial.mkdir(parents=True, exist_ok=True)
    raw_dir = partial / "raw_responses"
    daily_dir = partial / "daily"
    raw_dir.mkdir(exist_ok=True)
    daily_dir.mkdir(exist_ok=True)
    intent = {
        "pool_artifact_sha256": pool["artifact_sha256"],
        "pool_file_sha256": _sha256_file(pool_path),
        "symbols": symbols,
        "start": str(start.date()),
        "through": str(through.date()),
        "requests_per_second_cap": args.requests_per_second,
        "corporate_action_manifest_sha256": _sha256_file(corp_manifest_path),
        "builder_commit": _git_commit(),
        "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
        "parser_module_sha256": _sha256_file(
            PROJ / "core/data/yahoo_daily_snapshot.py"),
    }
    intent_path = partial / "build_intent.json"
    if intent_path.exists():
        if json.loads(intent_path.read_text()) != intent:
            raise RuntimeError(
                f"partial Yahoo daily intent differs; inspect before removal: {partial}"
            )
    else:
        _atomic_json(intent, intent_path)

    journal_path = partial / "fetch_journal.jsonl"
    journal = _read_journal(journal_path)
    period1 = _epoch(str(start.date()))
    period2 = _epoch(str((through + pd.Timedelta(days=1)).date()))
    interval_seconds = 1.0 / args.requests_per_second
    last_request_at = float("-inf")
    session = requests.Session()
    for position, symbol in enumerate(symbols, start=1):
        storage_name = f"{symbol.replace('.', '_')}.json"
        if symbol in journal:
            row = journal[symbol]
            raw_path = raw_dir / row["storage_name"]
            if raw_path.exists() and _sha256_file(raw_path) == row["response_sha256"]:
                continue
            raise RuntimeError(f"Yahoo daily journal/file mismatch for {symbol}")
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
            raise RuntimeError(f"empty Yahoo daily response for {symbol}")
        payload = response.json()
        parsed = parse_yahoo_daily_bars(payload, expected_symbol=symbol)
        corp_row = corp_rows[symbol]
        corp_path = corp_root / "raw" / str(corp_row["storage_name"])
        if _sha256_file(corp_path) != corp_row["response_sha256"]:
            raise RuntimeError(f"corporate-action raw response hash changed for {symbol}")
        corp_payload = json.loads(corp_path.read_bytes())
        cross_query_match = corporate_actions_match(
            payload, corp_payload, expected_symbol=symbol,
        )
        if not cross_query_match:
            print(
                f"  diagnostic: 1d/3mo corporate actions differ for {symbol}",
                flush=True,
            )
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
            "rows": len(parsed.frame),
            "first_date": str(parsed.frame.index.min().date()),
            "last_date": str(parsed.frame.index.max().date()),
            "corporate_actions_match": cross_query_match,
        }
        _append_journal(journal_path, row)
        journal[symbol] = row
        if position % 25 == 0 or position == len(symbols):
            print(
                f"symbols {position}/{len(symbols)} downloaded={len(journal)}",
                flush=True,
            )

    if set(journal) != set(symbols):
        raise RuntimeError("Yahoo daily journal symbol set differs from governed pool")
    spy_raw = json.loads((raw_dir / journal["SPY"]["storage_name"]).read_bytes())
    spy = parse_yahoo_daily_bars(spy_raw, expected_symbol="SPY").frame
    benchmark_sessions = spy.index[(spy.index >= start) & (spy.index <= through)]
    manifest_symbols: list[dict[str, Any]] = []
    for position, symbol in enumerate(symbols, start=1):
        row = journal[symbol]
        raw_path = raw_dir / row["storage_name"]
        if _sha256_file(raw_path) != row["response_sha256"]:
            raise RuntimeError(f"Yahoo daily raw response hash changed for {symbol}")
        parsed = parse_yahoo_daily_bars(
            json.loads(raw_path.read_bytes()), expected_symbol=symbol,
        )
        frame = parsed.frame.loc[
            (parsed.frame.index >= start) & (parsed.frame.index <= through)
        ].copy()
        outside = frame.index.difference(benchmark_sessions)
        if len(outside):
            raise RuntimeError(
                f"{symbol}: Yahoo dates outside SPY sessions; first={outside[0].date()}"
            )
        output_path = daily_dir / f"{symbol.replace('^', '_').replace('-', '_')}.parquet"
        frame.to_parquet(output_path, compression="snappy")
        manifest_symbols.append({
            "symbol": symbol,
            "rows": len(frame),
            "first_date": str(frame.index.min().date()),
            "last_date": str(frame.index.max().date()),
            "output_sha256": _sha256_file(output_path),
            "raw_response_sha256": row["response_sha256"],
        })
        if position % 50 == 0 or position == len(symbols):
            print(f"validated {position}/{len(symbols)}", flush=True)
    shutil.copy2(corp_manifest_path, partial / "corporate_action_manifest.json")
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
        "snapshot_id": output_root.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        **intent,
        "source": "Yahoo Finance chart v8 (unofficial)",
        "immutable": True,
        "price_basis": "YAHOO_CHART_SPLIT_ADJUSTED_PRICE_AND_TOTAL_RETURN_V1",
        "price_columns": ["open", "high", "low", "close", "volume"],
        "total_return_columns": [
            "total_return_open", "total_return_high", "total_return_low",
            "total_return_close",
        ],
        "total_return_contract": "Yahoo OHLC multiplied per session by AdjClose/Close",
        "benchmark": "SPY",
        "responses": len(symbols),
        "response_bytes": sum(journal[symbol]["response_bytes"] for symbol in symbols),
        "raw_response_identity_sha256": _sha256_json(raw_identity),
        "corporate_action_cross_query_mismatch_symbols": [
            symbol for symbol in symbols
            if not journal[symbol]["corporate_actions_match"]
        ],
        "symbols": manifest_symbols,
        "evidence_scope": "DEVELOPMENT_ONLY_CURRENT_COMPANY_POOL",
        "automatic_promotion_eligible": False,
    }
    _atomic_json(manifest, partial / "manifest.json")
    os.replace(partial, output_root)
    print(f"yahoo_daily_snapshot={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
