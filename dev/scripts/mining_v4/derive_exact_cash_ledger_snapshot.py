#!/usr/bin/env python3
"""Derive split-adjusted OHLC plus an exact per-share cash ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.data.exact_cash_total_return import (  # noqa: E402
    build_exact_cash_total_return,
)
from core.data.yahoo_corporate_actions import (  # noqa: E402
    parse_yahoo_corporate_actions,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True,
    ).strip()


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_symbol(symbol: str) -> str:
    return symbol.replace("^", "_").replace("-", "_")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"exact cash-ledger snapshot is immutable: {output_root}")
    source_manifest_path = source_root / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text())
    if source_manifest.get("price_basis") != (
        "YAHOO_CHART_SPLIT_ADJUSTED_PRICE_AND_TOTAL_RETURN_V1"
    ):
        raise RuntimeError("source is not the governed Yahoo daily snapshot")
    rows = source_manifest.get("symbols")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("source snapshot lacks per-symbol evidence")

    partial = output_root.with_name(f".{output_root.name}.partial")
    partial.mkdir(parents=True, exist_ok=False)
    daily_dir = partial / "daily"
    daily_dir.mkdir()
    output_rows: list[dict[str, Any]] = []
    ambiguous: list[str] = []
    total_events = 0
    total_skipped = 0
    max_exact_recurrence_error = 0.0
    max_vendor_adjclose_diagnostic_error = 0.0
    max_distribution_to_previous_close = 0.0
    max_distribution_event: dict[str, Any] | None = None
    for position, row in enumerate(rows, start=1):
        symbol = str(row["symbol"])
        source_daily = source_root / "daily" / f"{_safe_symbol(symbol)}.parquet"
        if _sha256_file(source_daily) != row.get("output_sha256"):
            raise RuntimeError(f"source daily hash mismatch for {symbol}")
        raw_path = source_root / "raw_responses" / f"{symbol.replace('.', '_')}.json"
        if _sha256_file(raw_path) != row.get("raw_response_sha256"):
            raise RuntimeError(f"source raw response hash mismatch for {symbol}")
        bars = pd.read_parquet(source_daily)
        actions = parse_yahoo_corporate_actions(
            json.loads(raw_path.read_bytes()), expected_symbol=symbol,
        )
        same_day_actions = actions.distributions.merge(
            actions.splits,
            left_on="ex_date",
            right_on="date",
            how="inner",
        )
        is_ambiguous = not same_day_actions.empty
        if is_ambiguous:
            ambiguous.append(symbol)
        exact = build_exact_cash_total_return(bars, actions.distributions)
        expected_return = exact.frame["close"].add(
            exact.frame["cash_distribution"]
        ).div(exact.frame["close"].shift(1)) - 1.0
        actual_return = exact.frame["total_return_close"].pct_change(
            fill_method=None)
        recurrence_error = (actual_return - expected_return).abs().dropna()
        recurrence_max = (
            float(recurrence_error.max()) if len(recurrence_error) else 0.0)
        if recurrence_max > 1e-12:
            raise RuntimeError(
                f"{symbol}: exact cash recurrence error {recurrence_max}")
        max_exact_recurrence_error = max(
            max_exact_recurrence_error, recurrence_max)

        yahoo_return = bars["adj_close"].pct_change(fill_method=None)
        vendor_diagnostic = (actual_return - yahoo_return).abs().dropna()
        vendor_max = (
            float(vendor_diagnostic.max()) if len(vendor_diagnostic) else 0.0)
        max_vendor_adjclose_diagnostic_error = max(
            max_vendor_adjclose_diagnostic_error, vendor_max)
        distribution_ratio = exact.frame["cash_distribution"].div(
            exact.frame["close"].shift(1)).where(
                exact.frame["cash_distribution"] > 0).dropna()
        distribution_ratio_max = (
            float(distribution_ratio.max()) if len(distribution_ratio) else 0.0)
        if distribution_ratio_max > max_distribution_to_previous_close:
            event_date = distribution_ratio.idxmax()
            max_distribution_to_previous_close = distribution_ratio_max
            max_distribution_event = {
                "symbol": symbol,
                "ex_date": str(event_date.date()),
                "cash_amount": float(
                    exact.frame.loc[event_date, "cash_distribution"]),
                "previous_close": float(
                    exact.frame["close"].shift(1).loc[event_date]),
                "ratio": distribution_ratio_max,
            }
        destination = daily_dir / f"{_safe_symbol(symbol)}.parquet"
        exact.frame.to_parquet(destination, compression="snappy")
        output_rows.append({
            "symbol": symbol,
            "rows": len(exact.frame),
            "first_date": str(exact.frame.index.min().date()),
            "last_date": str(exact.frame.index.max().date()),
            "output_sha256": _sha256_file(destination),
            "source_output_sha256": row["output_sha256"],
            "raw_response_sha256": row["raw_response_sha256"],
            "cash_distribution_events_applied": exact.applied_events,
            "cash_distribution_events_skipped_pre_history": (
                exact.skipped_pre_history_events),
            "same_day_distribution_and_split": is_ambiguous,
            "exact_recurrence_max_abs_error": recurrence_max,
            "vendor_adjclose_daily_return_diagnostic_max_abs": vendor_max,
            "distribution_to_previous_close_max": distribution_ratio_max,
        })
        total_events += exact.applied_events
        total_skipped += exact.skipped_pre_history_events
        if position % 50 == 0 or position == len(rows):
            print(f"derived {position}/{len(rows)}", flush=True)

    eligible = [
        row["symbol"] for row in output_rows
        if row["symbol"] not in ambiguous
    ]
    if "SPY" not in eligible:
        raise RuntimeError("SPY cannot be ambiguous or excluded")
    manifest = {
        "schema_version": 1,
        "snapshot_id": output_root.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "builder_commit": _git_commit(),
        "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
        "adjustment_module_sha256": _sha256_file(
            PROJ / "core/data/exact_cash_total_return.py"),
        "source_snapshot_id": source_manifest.get("snapshot_id"),
        "source_snapshot_manifest_sha256": _sha256_file(source_manifest_path),
        "pool_artifact_sha256": source_manifest.get("pool_artifact_sha256"),
        "start": source_manifest.get("start"),
        "through": source_manifest.get("through"),
        "immutable": True,
        "price_basis": "YAHOO_SPLIT_ADJUSTED_OHLC_PLUS_EXACT_CASH_LEDGER_V2",
        "price_columns": ["open", "high", "low", "close", "volume"],
        "cash_distribution_column": "cash_distribution",
        "total_return_columns": ["total_return_close"],
        "total_return_contract": (
            "close-to-close return equals (close_t + cash_distribution_t) / "
            "close_(t-1) - 1; portfolio cash is credited only to shares held "
            "before the ex-date open"),
        "cash_distribution_interpretation": (
            "Yahoo chart dividend events are treated as per-share cash or "
            "cash-equivalent value; source remains unofficial"),
        "exact_recurrence_tolerance": 1e-12,
        "exact_recurrence_max_abs_error": max_exact_recurrence_error,
        "vendor_adjclose_daily_return_diagnostic_max_abs": (
            max_vendor_adjclose_diagnostic_error),
        "max_distribution_to_previous_close": (
            max_distribution_to_previous_close),
        "max_distribution_event": max_distribution_event,
        "cash_distribution_events_applied": total_events,
        "cash_distribution_events_skipped_pre_history": total_skipped,
        "excluded_symbols": sorted(ambiguous),
        "exclusion_reason": (
            "same-day Yahoo distribution and split is ambiguous for per-share "
            "cash composition; excluded fail-closed"),
        "eligible_symbols": eligible,
        "upstream_corporate_action_cross_query_mismatch_symbols": (
            source_manifest.get(
                "corporate_action_cross_query_mismatch_symbols", [])),
        "upstream_cross_query_interpretation": (
            "retained diagnostic: the coarser corporate-action side query "
            "omitted some events present in the hashed daily response; the "
            "daily response is the primary event source for this artifact"),
        "symbols": output_rows,
        "evidence_scope": "DEVELOPMENT_ONLY_CURRENT_COMPANY_POOL",
        "automatic_promotion_eligible": False,
    }
    _atomic_json(manifest, partial / "manifest.json")
    os.replace(partial, output_root)
    print(f"exact_cash_ledger_snapshot={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
