#!/usr/bin/env python3
"""Verify canonical split events against Yahoo and publish query coverage."""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.data.corporate_action_coverage import (  # noqa: E402
    compare_split_events,
    normalize_canonical_splits,
    normalize_vendor_splits,
)
from dev.scripts.data_integrity.build_distributions_parquet import (  # noqa: E402
    _atomic_to_parquet,
)


def _fetch_vendor_splits(symbol: str, *, retries: int = 3) -> pd.Series:
    import yfinance as yf

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return yf.Ticker(symbol.replace(".", "-")).get_splits(period="max")
        except Exception as exc:  # provider exception types vary by release
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"split query failed after {retries} attempts: {last_error}")


def _merge_by_symbol(
    existing: pd.DataFrame,
    new: pd.DataFrame,
    symbols: set[str],
) -> pd.DataFrame:
    if not existing.empty:
        existing = existing[
            ~existing["symbol"].astype(str).str.upper().isin(symbols)
        ]
    combined = pd.concat([existing, new], ignore_index=True)
    if combined.empty:
        return combined
    order = [name for name in ("symbol", "date", "checked_at") if name in combined]
    return combined.sort_values(order).reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", required=True, help="Inclusive coverage end")
    parser.add_argument("--data-root", default=str(PROJ / "data"))
    parser.add_argument("--coverage-output", default=None)
    parser.add_argument("--events-output", default=None)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    split_path = data_root / "ref" / "splits.parquet"
    if not split_path.exists():
        raise FileNotFoundError(split_path)
    split_sha = hashlib.sha256(split_path.read_bytes()).hexdigest()[:16]
    canonical_table = pd.read_parquet(split_path)
    coverage_path = (
        Path(args.coverage_output).resolve()
        if args.coverage_output else data_root / "ref" / "split_coverage.parquet"
    )
    events_path = (
        Path(args.events_output).resolve()
        if args.events_output
        else data_root / "ref" / "split_verification_events.parquet"
    )
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    coverage_rows: list[dict[str, object]] = []
    event_frames: list[pd.DataFrame] = []
    query_errors: list[dict[str, str]] = []

    symbols = list(dict.fromkeys(str(symbol).upper() for symbol in args.symbols))
    for position, symbol in enumerate(symbols, start=1):
        print(f"[{position}/{len(symbols)}] verifying {symbol}", flush=True)
        try:
            vendor_raw = _fetch_vendor_splits(symbol)
        except RuntimeError as exc:
            query_errors.append({"symbol": symbol, "error": str(exc)})
            continue
        canonical = normalize_canonical_splits(
            canonical_table, symbol, start=args.start, end=args.end)
        vendor = normalize_vendor_splits(
            vendor_raw, start=args.start, end=args.end)
        comparison = compare_split_events(canonical, vendor)
        coverage_rows.append({
            "symbol": symbol,
            "checked_start": pd.Timestamp(args.start),
            "checked_end": pd.Timestamp(args.end),
            "checked_at": checked_at,
            "source": "yfinance_splits",
            "status": comparison.status,
            "error": "",
            "canonical_event_count": comparison.canonical_event_count,
            "vendor_event_count": comparison.vendor_event_count,
            "matched_event_count": comparison.matched_event_count,
            "canonical_only_count": comparison.canonical_only_count,
            "vendor_only_count": comparison.vendor_only_count,
            "ratio_mismatch_count": comparison.ratio_mismatch_count,
            "splits_table_sha": split_sha,
        })
        if not comparison.details.empty:
            details = comparison.details.copy()
            details.insert(0, "symbol", symbol)
            details["checked_at"] = checked_at
            details["splits_table_sha"] = split_sha
            event_frames.append(details)
        if position < len(symbols) and args.pause_seconds:
            time.sleep(args.pause_seconds)

    coverage = pd.DataFrame(coverage_rows)
    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame(
        columns=[
            "symbol", "date", "canonical_ratio", "vendor_ratio",
            "comparison", "checked_at", "splits_table_sha",
        ]
    )
    successful_symbols = set(coverage["symbol"]) if not coverage.empty else set()
    new_mismatches = (
        int((coverage["status"] != "OK").sum()) if not coverage.empty else 0
    )
    error_path: Path | None = None
    if query_errors:
        error_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        error_path = data_root / "audit" / f"split_coverage_errors_{error_stamp}.parquet"
        _atomic_to_parquet(pd.DataFrame(query_errors), error_path)
        if not args.append:
            print(f"query errors={len(query_errors)} -> {error_path}")
            print("canonical split coverage NOT modified")
            return 2
    if args.append:
        old_coverage = (
            pd.read_parquet(coverage_path) if coverage_path.exists() else pd.DataFrame()
        )
        old_events = pd.read_parquet(events_path) if events_path.exists() else pd.DataFrame()
        coverage = _merge_by_symbol(old_coverage, coverage, successful_symbols)
        events = _merge_by_symbol(old_events, events, successful_symbols)
    _atomic_to_parquet(coverage, coverage_path)
    _atomic_to_parquet(events, events_path)

    if error_path is not None:
        print(f"query errors={len(query_errors)} -> {error_path}")
    print(
        f"split coverage: published={len(successful_symbols)} "
        f"mismatches={new_mismatches} query_errors={len(query_errors)}"
    )
    return 2 if query_errors or new_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
