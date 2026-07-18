#!/usr/bin/env python3
"""Build uniform as-traded daily OHLCV from yfinance history.

Yahoo's ``auto_adjust=False`` OHLC is split-adjusted to today's share basis
but not dividend-adjusted.  The local BarStore expects as-traded bars and
applies the canonical split table at read time.  This builder reverses the
future split cascade before publishing, proves that reapplying it reconstructs
the downloaded series, writes atomically, and records explicit canonical
source semantics.  Total-return dividends remain a separate BarStore sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config  # noqa: E402
from core.data.canonical_daily import reconstruct_as_traded_ohlcv  # noqa: E402
from core.data.source_boundaries import record_canonical_replacement  # noqa: E402
from core.data.yfinance_provider import YFinanceProvider  # noqa: E402

PHASE2_SYMBOLS = (
    "SPY",
    "QQQ",
    "TQQQ",
    "IEF",
    "GLD",
    "BIL",
    "SHY",
    "SHV",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLY",
    "XLP",
    "XLU",
    "XLB",
)


def executable_symbols() -> list[str]:
    cfg = load_config(ROOT / "config")
    universe = cfg.universe
    symbols = list(
        dict.fromkeys(
            list(universe.seed_pool)
            + list(universe.sector_etfs)
            + list(universe.factor_etfs)
            + list(universe.cross_asset)
        )
    )
    return [symbol for symbol in symbols if symbol not in set(universe.blacklist)]


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    try:
        frame.to_parquet(temporary, compression="snappy")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build(
    symbols: list[str],
    *,
    start: str,
    end: str,
    data_root: Path,
    backup_root: Path,
) -> dict:
    split_table = pd.read_parquet(data_root / "ref/splits.parquet")
    provider = YFinanceProvider(auto_adjust=False, progress=False)
    manifest: dict = {
        "schema_version": 1,
        "source": "yfinance_auto_adjust_false",
        "published_semantics": "as_traded_ohlcv_reconstructed_from_split_adjusted_close",
        "start_requested": start,
        "end_exclusive": end,
        "splits_sha256": hashlib.sha256((data_root / "ref/splits.parquet").read_bytes()).hexdigest(),
        "built_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbols": {},
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        result = provider.fetch_daily([symbol], start=start, end=end)
        if symbol not in result:
            raise RuntimeError(f"no yfinance history for {symbol}")
        downloaded = result[symbol].df.loc[:, ["open", "high", "low", "close", "volume"]]
        relevant_splits = split_table[split_table["symbol"] == symbol]
        raw = reconstruct_as_traded_ohlcv(downloaded, relevant_splits)
        target = data_root / "daily" / f"{symbol.replace('-', '_')}.parquet"
        if target.exists() and not (backup_root / target.name).exists():
            shutil.copy2(target, backup_root / target.name)
        _atomic_parquet(target, raw)
        record_canonical_replacement(
            symbol,
            start_date=raw.index.min().date(),
            end_date=raw.index.max().date(),
            path=data_root / "ref/daily_source_boundaries.parquet",
        )
        manifest["symbols"][symbol] = {
            "first_date": str(raw.index.min().date()),
            "last_date": str(raw.index.max().date()),
            "rows": len(raw),
            "raw_parquet_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "splits": len(relevant_splits),
        }
        print(f"{symbol}: {len(raw)} rows {raw.index.min().date()}..{raw.index.max().date()}")
    return manifest


def finalize_manifest(path: Path, data_root: Path) -> dict:
    """Stamp post-distribution reference hashes onto an existing manifest."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    references = {}
    for name in (
        "splits.parquet",
        "distributions.parquet",
        "distribution_coverage.parquet",
        "daily_source_boundaries.parquet",
    ):
        ref_path = data_root / "ref" / name
        references[name] = {
            "sha256": hashlib.sha256(ref_path.read_bytes()).hexdigest(),
            "rows": len(pd.read_parquet(ref_path)),
        }
    manifest["reference_artifacts"] = references
    manifest["finalized_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _atomic_json(path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="*", default=list(PHASE2_SYMBOLS))
    parser.add_argument(
        "--all-executable",
        action="store_true",
        help="rebuild the complete configured executable universe",
    )
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", default="2026-07-18", help="exclusive")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=ROOT / "data/backups/pre_phase2_canonical_daily_20260717",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "research/registry/phase2_data_manifest.json",
    )
    parser.add_argument(
        "--finalize-only",
        action="store_true",
        help="stamp current split/distribution/coverage/source hashes without rebuilding bars",
    )
    args = parser.parse_args()
    if args.finalize_only:
        finalize_manifest(args.manifest, args.data_root)
        print(f"finalized manifest: {args.manifest}")
        return
    symbols = executable_symbols() if args.all_executable else args.symbols
    manifest = build(
        symbols,
        start=args.start,
        end=args.end,
        data_root=args.data_root,
        backup_root=args.backup_root,
    )
    _atomic_json(args.manifest, manifest)
    print(f"manifest: {args.manifest}")


if __name__ == "__main__":
    main()
