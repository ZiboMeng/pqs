#!/usr/bin/env python3
"""Derive a cash-event total-return snapshot and quarantine ambiguous actions."""

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

from core.data.cash_distribution_total_return import (  # noqa: E402
    apply_cash_distributions,
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
    parser.add_argument("--adjclose-return-tolerance", type=float, default=5e-6)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"derived total-return snapshot is immutable: {output_root}")
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
    maximum_crosscheck_error = 0.0
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
        both = actions.distributions.merge(
            actions.splits,
            left_on="ex_date",
            right_on="date",
            how="inner",
        )
        is_ambiguous = not both.empty
        if is_ambiguous:
            ambiguous.append(symbol)
        adjusted = apply_cash_distributions(bars, actions.distributions)
        yahoo_factor = (bars["adj_close"] / bars["close"])
        yahoo_factor = yahoo_factor / yahoo_factor.iloc[-1]
        yahoo_return = (bars["close"] * yahoo_factor).pct_change(fill_method=None)
        governed_return = adjusted.frame["total_return_close"].pct_change(
            fill_method=None)
        crosscheck = (governed_return - yahoo_return).abs().dropna()
        max_error = float(crosscheck.max()) if len(crosscheck) else 0.0
        if max_error > args.adjclose_return_tolerance:
            raise RuntimeError(
                f"{symbol}: cash-event total return differs from normalized "
                f"Adj Close by {max_error}"
            )
        maximum_crosscheck_error = max(maximum_crosscheck_error, max_error)
        destination = daily_dir / f"{_safe_symbol(symbol)}.parquet"
        adjusted.frame.to_parquet(destination, compression="snappy")
        output_rows.append({
            "symbol": symbol,
            "rows": len(adjusted.frame),
            "first_date": str(adjusted.frame.index.min().date()),
            "last_date": str(adjusted.frame.index.max().date()),
            "output_sha256": _sha256_file(destination),
            "source_output_sha256": row["output_sha256"],
            "raw_response_sha256": row["raw_response_sha256"],
            "cash_distribution_events_applied": adjusted.applied_events,
            "cash_distribution_events_skipped_pre_history": (
                adjusted.skipped_pre_history_events
            ),
            "same_day_distribution_and_split": is_ambiguous,
            "adjclose_daily_return_crosscheck_max_abs": max_error,
        })
        total_events += adjusted.applied_events
        total_skipped += adjusted.skipped_pre_history_events
        if position % 50 == 0 or position == len(rows):
            print(f"derived {position}/{len(rows)}", flush=True)
    eligible = [row["symbol"] for row in output_rows if row["symbol"] not in ambiguous]
    if "SPY" not in eligible:
        raise RuntimeError("SPY cannot be ambiguous or excluded")
    manifest = {
        "schema_version": 1,
        "snapshot_id": output_root.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "builder_commit": _git_commit(),
        "builder_script_sha256": _sha256_file(Path(__file__).resolve()),
        "adjustment_module_sha256": _sha256_file(
            PROJ / "core/data/cash_distribution_total_return.py"),
        "source_snapshot_id": source_manifest.get("snapshot_id"),
        "source_snapshot_manifest_sha256": _sha256_file(source_manifest_path),
        "pool_artifact_sha256": source_manifest.get("pool_artifact_sha256"),
        "start": source_manifest.get("start"),
        "through": source_manifest.get("through"),
        "immutable": True,
        "price_basis": (
            "YAHOO_SPLIT_ADJUSTED_OHLC_PLUS_CASH_EVENT_TOTAL_RETURN_V1"
        ),
        "price_columns": ["open", "high", "low", "close", "volume"],
        "total_return_columns": [
            "total_return_open", "total_return_high", "total_return_low",
            "total_return_close",
        ],
        "total_return_contract": (
            "Yahoo split-adjusted OHLC back-adjusted only by positive cash "
            "distribution events present in the same immutable 1d response"
        ),
        "adjclose_daily_return_crosscheck_tolerance": (
            args.adjclose_return_tolerance
        ),
        "adjclose_daily_return_crosscheck_max_abs": maximum_crosscheck_error,
        "cash_distribution_events_applied": total_events,
        "cash_distribution_events_skipped_pre_history": total_skipped,
        "excluded_symbols": sorted(ambiguous),
        "exclusion_reason": (
            "same-day Yahoo distribution and split is ambiguous for total-return "
            "composition; excluded fail-closed"
        ),
        "eligible_symbols": eligible,
        "symbols": output_rows,
        "evidence_scope": "DEVELOPMENT_ONLY_CURRENT_COMPANY_POOL",
        "automatic_promotion_eligible": False,
    }
    _atomic_json(manifest, partial / "manifest.json")
    os.replace(partial, output_root)
    print(f"certified_total_return_snapshot={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
