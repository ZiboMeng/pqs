#!/usr/bin/env python3
"""Validate local split/total-return daily data against Yahoo references."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.data.bar_store import BarStore  # noqa: E402
from core.data.price_access import load_adjusted  # noqa: E402


def max_return_difference(left: pd.Series, right: pd.Series) -> float:
    common = left.dropna().index.intersection(right.dropna().index)
    if len(common) < 2:
        raise ValueError("fewer than two common observations")
    difference = left.loc[common].pct_change() - right.loc[common].pct_change()
    return float(difference.abs().dropna().max())


def validate(
    manifest_path: Path,
    *,
    data_root: Path,
    start: str,
    end: str,
    split_tolerance: float,
    total_return_tolerance: float,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    symbols = sorted(manifest["symbols"])
    yahoo = yf.download(
        symbols,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    store = BarStore(root=data_root)
    rows: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for symbol in symbols:
        split_only = load_adjusted(
            symbol,
            data_root,
            "1d",
            adjusted_total_return=False,
            fallback="local",
            _store=store,
        )
        total_return = load_adjusted(
            symbol,
            data_root,
            "1d",
            adjusted_total_return=True,
            fallback="local",
            _store=store,
        )
        if split_only is None or total_return is None:
            failures.append(f"{symbol}:LOCAL_LOAD_FAILED")
            continue
        yahoo_close = yahoo["Close"][symbol].dropna()
        yahoo_adjusted = yahoo["Adj Close"][symbol].dropna()
        split_diff = max_return_difference(split_only["close"], yahoo_close)
        total_diff = max_return_difference(total_return["close"], yahoo_adjusted)
        passed = split_diff <= split_tolerance and total_diff <= total_return_tolerance
        if not passed:
            failures.append(f"{symbol}:PARITY")
        rows[symbol] = {
            "first_date": str(total_return.index.min().date()),
            "last_date": str(total_return.index.max().date()),
            "rows": len(total_return),
            "split_return_max_abs_diff": split_diff,
            "total_return_max_abs_diff": total_diff,
            "passed": passed,
        }
    return {
        "schema_version": 1,
        "validated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifest": (
            str(manifest_path.resolve().relative_to(ROOT))
            if manifest_path.resolve().is_relative_to(ROOT)
            else str(manifest_path)
        ),
        "symbols_requested": len(symbols),
        "symbols_passed": sum(bool(row["passed"]) for row in rows.values()),
        "split_return_tolerance": split_tolerance,
        "total_return_tolerance": total_return_tolerance,
        "max_split_return_abs_diff": max(row["split_return_max_abs_diff"] for row in rows.values()),
        "max_total_return_abs_diff": max(row["total_return_max_abs_diff"] for row in rows.values()),
        "failures": failures,
        "symbols": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "research/registry/phase2_data_manifest.json",
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", default="2026-07-18")
    parser.add_argument("--split-tolerance", type=float, default=2e-5)
    parser.add_argument("--total-return-tolerance", type=float, default=2e-4)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research/results/phase2/data_parity.json",
    )
    args = parser.parse_args()
    report = validate(
        args.manifest,
        data_root=args.data_root,
        start=args.start,
        end=args.end,
        split_tolerance=args.split_tolerance,
        total_return_tolerance=args.total_return_tolerance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"canonical parity: {report['symbols_passed']}/{report['symbols_requested']} "
        f"max_split={report['max_split_return_abs_diff']:.3e} "
        f"max_total_return={report['max_total_return_abs_diff']:.3e}"
    )
    if report["failures"]:
        raise SystemExit(f"canonical parity failures: {report['failures']}")


if __name__ == "__main__":
    main()
