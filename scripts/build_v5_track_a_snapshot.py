#!/usr/bin/env python3
"""Freeze Yahoo split-adjusted bars plus exact cash ledgers for V5 Track A."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.data.exact_cash_total_return import build_exact_cash_total_return  # noqa: E402
from core.research.qualification_v2 import canonical_sha256, sha256_file  # noqa: E402

SYMBOLS = ("SPY", "BIL", "QUAL", "MTUM", "USMV", "IEF", "GLD")


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
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


def _records_hash(frame: pd.DataFrame) -> str:
    payload = frame.reset_index().to_json(
        orient="records", date_format="iso", double_precision=15
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="data/research/mining_v5/track_a_yahoo_exact_cash_v1",
    )
    parser.add_argument("--start", default="2006-12-01")
    parser.add_argument("--end-exclusive", default="2025-01-02")
    parser.add_argument(
        "--canonical-spy-source",
        default=None,
        help="Existing frozen exact-cash SPY parquet bound by the V5 benchmark.",
    )
    args = parser.parse_args()
    output = Path(args.output_dir)
    output = output if output.is_absolute() else ROOT / output
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        print(f"ERROR: snapshot is immutable: {manifest_path}", file=sys.stderr)
        return 2
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required") from exc

    rows: dict[str, dict] = {}
    for symbol in SYMBOLS:
        if symbol == "SPY" and args.canonical_spy_source:
            canonical_source = Path(args.canonical_spy_source).resolve()
            exact_frame = pd.read_parquet(canonical_source)
            required = {
                "open", "high", "low", "close", "volume",
                "cash_distribution", "total_return_close",
            }
            if required - set(exact_frame):
                raise RuntimeError("canonical SPY source lacks exact-cash fields")
            daily_path = output / "daily" / "SPY.parquet"
            daily_path.parent.mkdir(parents=True, exist_ok=True)
            exact_frame.to_parquet(daily_path)
            rows[symbol] = {
                "source": "preexisting_canonical_exact_cash_snapshot",
                "upstream_path_at_build": str(canonical_source),
                "upstream_sha256": sha256_file(canonical_source),
                "daily_path": str(daily_path.relative_to(ROOT)),
                "daily_sha256": sha256_file(daily_path),
                "first_session": exact_frame.index[0].date().isoformat(),
                "last_session": exact_frame.index[-1].date().isoformat(),
                "sessions": len(exact_frame),
                "distribution_events": int(
                    (exact_frame["cash_distribution"] > 0.0).sum()
                ),
                "total_return_close_sha256": canonical_sha256(
                    exact_frame["total_return_close"].tolist()
                ),
            }
            print(f"SPY: {len(exact_frame)} sessions (canonical source)")
            continue
        raw = yf.Ticker(symbol).history(
            start=args.start,
            end=args.end_exclusive,
            auto_adjust=False,
            actions=True,
            repair=True,
        )
        if raw.empty:
            raise RuntimeError(f"Yahoo returned no history for {symbol}")
        index = pd.DatetimeIndex(raw.index)
        if index.tz is not None:
            index = index.tz_convert("America/New_York").tz_localize(None)
        raw.index = index.normalize()
        bars = raw.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })[["open", "high", "low", "close", "volume"]]
        dividends = pd.to_numeric(raw.get("Dividends", 0.0), errors="raise")
        events = pd.DataFrame({
            "ex_date": raw.index[dividends > 0.0],
            "cash_amount": dividends.loc[dividends > 0.0].to_numpy(),
        })
        exact = build_exact_cash_total_return(bars, events)
        daily_path = output / "daily" / f"{symbol}.parquet"
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        exact.frame.to_parquet(daily_path)
        rows[symbol] = {
            "source": "Yahoo Finance via pinned local yfinance environment",
            "request": {
                "start": args.start,
                "end_exclusive": args.end_exclusive,
                "auto_adjust": False,
                "actions": True,
                "repair": True,
            },
            "raw_normalized_records_sha256": _records_hash(raw),
            "daily_path": str(daily_path.relative_to(ROOT)),
            "daily_sha256": sha256_file(daily_path),
            "first_session": exact.frame.index[0].date().isoformat(),
            "last_session": exact.frame.index[-1].date().isoformat(),
            "sessions": len(exact.frame),
            "distribution_events": exact.applied_events,
            "total_return_close_sha256": canonical_sha256(
                exact.frame["total_return_close"].tolist()
            ),
        }
        print(f"{symbol}: {len(exact.frame)} sessions")
    manifest = {
        "schema_version": 1,
        "snapshot_id": "track_a_yahoo_exact_cash_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "immutable": True,
        "symbols": rows,
        "limitations": [
            "Yahoo is a frozen development-data source, not exchange ground truth.",
            "Current download time is recorded; reruns must create a new snapshot ID.",
        ],
    }
    manifest["content_sha256"] = canonical_sha256(manifest)
    _atomic_json(manifest_path, manifest)
    print(f"wrote {manifest_path}")
    print(f"manifest_sha256={sha256_file(manifest_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
