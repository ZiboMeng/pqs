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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

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


def _split_factor(index: pd.DatetimeIndex, splits: pd.DataFrame) -> np.ndarray:
    if splits.empty:
        return np.ones(len(index), dtype="float64")
    ordered = splits.sort_values("date").reset_index(drop=True)
    ratios = (ordered["from"].astype(float) / ordered["to"].astype(float)).to_numpy()
    suffix = np.ones(len(ratios) + 1, dtype="float64")
    for position in range(len(ratios) - 1, -1, -1):
        suffix[position] = suffix[position + 1] * ratios[position]
    dates = pd.to_datetime(ordered["date"]).to_numpy(dtype="datetime64[ns]")
    observed = index.normalize().to_numpy(dtype="datetime64[ns]")
    return suffix[np.searchsorted(dates, observed, side="right")]


def reconstruct_as_traded_ohlcv(
    split_adjusted: pd.DataFrame,
    splits: pd.DataFrame,
) -> pd.DataFrame:
    """Reverse future split adjustment into the BarStore raw-bar basis."""
    if split_adjusted.empty:
        raise ValueError("cannot reconstruct an empty frame")
    factor = _split_factor(split_adjusted.index, splits)
    if not np.isfinite(factor).all() or (factor <= 0.0).any():
        raise ValueError("invalid split factor")
    raw = split_adjusted.copy()
    for column in ("open", "high", "low", "close"):
        raw[column] = split_adjusted[column].astype("float64") / factor
    raw["volume"] = (split_adjusted["volume"].astype("float64") * factor).round()
    raw["amount"] = raw["close"] * raw["volume"]
    raw["partial_day"] = False
    raw["thin_data"] = False

    # Publish is forbidden unless the exact BarStore forward transform is
    # reversible to the vendor series.
    for column in ("open", "high", "low", "close"):
        restored = raw[column].to_numpy(dtype="float64") * factor
        if not np.allclose(
            restored,
            split_adjusted[column].to_numpy(dtype="float64"),
            rtol=1e-9,
            atol=1e-6,
            equal_nan=False,
        ):
            raise ValueError(f"split reconstruction invariant failed for {column}")
    restored_volume = raw["volume"].to_numpy(dtype="float64") / factor
    if not np.allclose(
        restored_volume,
        split_adjusted["volume"].to_numpy(dtype="float64"),
        rtol=0.0,
        atol=1.0,
    ):
        raise ValueError("split reconstruction invariant failed for volume")
    return raw


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
        if target.exists():
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="*", default=list(PHASE2_SYMBOLS))
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
    args = parser.parse_args()
    manifest = build(
        args.symbols,
        start=args.start,
        end=args.end,
        data_root=args.data_root,
        backup_root=args.backup_root,
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"manifest: {args.manifest}")


if __name__ == "__main__":
    main()
