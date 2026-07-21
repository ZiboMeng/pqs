#!/usr/bin/env python3
"""Build an isolated, homogeneous raw-OHLCV snapshot for mining v4."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

from core.research.mining_v4_daily_snapshot import (  # noqa: E402
    repair_known_plus_one_day_shift,
    resolve_raw_daily_source,
    safe_symbol,
    validate_raw_daily,
)
from core.data.daily_aggregator import aggregate_1m_to_daily  # noqa: E402

P4_RULE = "p4_expanded_v1_2026-05-16"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _phase4_symbols(data_root: Path) -> set[str]:
    path = data_root / "ref" / "bar_provenance.parquet"
    provenance = pd.read_parquet(
        path, filters=[("rule_version", "==", P4_RULE)],
        columns=["symbol", "freq", "rule_version"],
    )
    return set(provenance.loc[provenance["freq"] == "1d", "symbol"])


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True).strip()


def _benchmark_sessions(data_root: Path, end: pd.Timestamp) -> pd.DatetimeIndex:
    spy = pd.read_parquet(data_root / "daily" / "SPY.parquet")
    spy = spy.loc[spy.index <= end]
    validate_raw_daily(
        spy,
        symbol="SPY",
        benchmark_sessions=pd.DatetimeIndex(spy.index),
    )
    return pd.DatetimeIndex(spy.index)


def _rebuild_from_one_minute(
    data_root: Path,
    symbol: str,
    *,
    sessions: pd.DatetimeIndex,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, Path, int]:
    path = data_root / "intraday" / "1m" / f"{safe_symbol(symbol)}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{symbol}: mixed daily corruption and no 1m rebuild source")
    minute = pd.read_parquet(path)
    if not isinstance(minute.index, pd.DatetimeIndex):
        raise TypeError(f"{symbol}: 1m rebuild source requires DatetimeIndex")
    if minute.index.tz is not None:
        minute = minute.copy()
        minute.index = minute.index.tz_convert(
            "America/New_York").tz_localize(None)
    minute = minute.loc[
        (minute.index.normalize() >= sessions.min())
        & (minute.index.normalize() <= end)
    ]
    daily, audit = aggregate_1m_to_daily(minute)
    if daily.empty:
        raise ValueError(f"{symbol}: 1m rebuild produced no accepted daily rows")
    daily = daily.copy()
    daily["amount"] = float("nan")
    # amount is deliberately not part of the governed OHLCV validation.
    validate_raw_daily(
        daily,
        symbol=symbol,
        benchmark_sessions=sessions,
    )
    return daily, path, len(audit)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument(
        "--pool", default="research/universes/semantic_ml_company_pool_v1.json")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--end", default="2024-12-31")
    args = parser.parse_args()

    data_root = Path(args.data_root).resolve()
    output_root = Path(args.output_root).resolve()
    if output_root.exists():
        raise FileExistsError(
            f"snapshot output already exists and is immutable: {output_root}")
    pool_path = (PROJ / args.pool).resolve()
    pool = json.loads(pool_path.read_text())
    symbols = [row["ticker"] for row in pool["selected"]] + ["SPY"]
    end = pd.Timestamp(args.end)
    sessions = _benchmark_sessions(data_root, end)
    phase4 = _phase4_symbols(data_root)

    output_root.parent.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(
        prefix=f".{output_root.name}.building.", dir=output_root.parent))
    (building / "daily").mkdir()
    (building / "ref").mkdir()
    rows: list[dict[str, Any]] = []
    try:
        for position, symbol in enumerate(symbols, start=1):
            source = resolve_raw_daily_source(
                data_root / "daily",
                symbol,
                phase4_preadjusted=symbol in phase4,
            )
            frame = pd.read_parquet(source.path)
            # The governed research horizon starts with the benchmark store.
            # Older company history is neither required nor representable in
            # the benchmark-session containment check.
            frame = frame.loc[
                (frame.index >= sessions.min()) & (frame.index <= end)
            ].copy()
            weekend_rows_before = int((frame.index.dayofweek >= 5).sum())
            audit_rows = 0
            source_path = source.path
            if source.transform.startswith("KNOWN_PLUS_ONE") or weekend_rows_before:
                try:
                    frame = repair_known_plus_one_day_shift(
                        frame,
                        symbol=symbol,
                        benchmark_sessions=sessions,
                    )
                    transform = "SHIFT_ALL_INDEX_LABELS_MINUS_ONE_CALENDAR_DAY"
                except ValueError:
                    frame, source_path, audit_rows = _rebuild_from_one_minute(
                        data_root,
                        symbol,
                        sessions=sessions,
                        end=end,
                    )
                    transform = "STRICT_REGULAR_SESSION_AGGREGATION_FROM_1M"
            else:
                validate_raw_daily(
                    frame,
                    symbol=symbol,
                    benchmark_sessions=sessions,
                )
                transform = "IDENTITY"
            destination = building / "daily" / f"{safe_symbol(symbol)}.parquet"
            frame.to_parquet(destination, compression="snappy")
            rows.append({
                "symbol": symbol,
                "source_path": str(source_path),
                "source_sha256": _sha256(source_path),
                "source_phase4_preadjusted_replacement": symbol in phase4,
                "transform": transform,
                "weekend_rows_before": weekend_rows_before,
                "quarantined_1m_days": audit_rows,
                "rows": len(frame),
                "first_date": str(frame.index.min().date()),
                "last_date": str(frame.index.max().date()),
                "output_sha256": _sha256(destination),
            })
            if position % 25 == 0 or position == len(symbols):
                print(f"built {position}/{len(symbols)}", flush=True)

        splits_source = data_root / "ref" / "splits.parquet"
        shutil.copy2(splits_source, building / "ref" / "splits.parquet")
        manifest = {
            "schema_version": 1,
            "snapshot_id": output_root.name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "builder_commit": _git_commit(),
            "builder_script_sha256": _sha256(Path(__file__).resolve()),
            "repair_module_sha256": _sha256(
                PROJ / "core" / "research" / "mining_v4_daily_snapshot.py"),
            "evidence_scope": "DEVELOPMENT_ONLY",
            "immutable": True,
            "pool_path": str(pool_path),
            "pool_artifact_sha256": pool["artifact_sha256"],
            "through": str(end.date()),
            "benchmark": "SPY",
            "price_basis": "RAW_OHLCV_WITH_SPLITS_APPLIED_AT_READ_TIME",
            "repair_contract": (
                "Only sources with the known +1-calendar-day weekend signature "
                "are shifted -1 day; Phase-4 auto-adjust replacements are not "
                "used, and their retained raw sidecars receive the same repair."),
            "splits_sha256": _sha256(splits_source),
            "symbols": rows,
        }
        _atomic_json(manifest, building / "manifest.json")
        os.replace(building, output_root)
    except Exception:
        shutil.rmtree(building, ignore_errors=True)
        raise
    print(f"snapshot={output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
