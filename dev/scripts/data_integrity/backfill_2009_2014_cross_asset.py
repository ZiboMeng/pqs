"""Backfill 2009-2014 daily bars for cross-asset ETFs (cycle #04 P0b).

Existing daily/<sym>.parquet for cross-asset ETFs covers 2015-01 onwards.
Cycle #04 panel needs 2009-2014 to cover the GFC/Eurozone-debt/taper
regimes where bond + commodity diversifiers prove their value.

This script fetches yfinance long-history (auto_adjust=False) for the
6 cycle #04 cross-asset ETFs and merges 2009-2014 into existing files,
respecting basis consistency:

Critical basis-consistency rule:
  yfinance auto_adjust=False applies splits to the Close column (only
  Adj Close is split+div-adjusted). Our canonical daily/*.parquet stores
  TRUE RAW close (un-split-adjusted) — splits are applied at READ time
  via BarStore + splits.parquet.

  → For symbols with splits in our splits.parquet (e.g. BIL has a
    2017-11-30 phantom 1-for-2 reverse split), backfilled yfinance Close
    is in yfinance's post-split basis. To match our existing 2015+
    raw basis, we DIVIDE yfinance Close by the cumulative split factor
    that yfinance applied for splits AFTER the backfill date.

  → For symbols without splits (TLT, IEF, SHY, GLD, SHV — none have
    splits per our splits.parquet), yfinance Close = raw, direct merge.

Schema reconciliation:
  Existing daily files have two schema variants per Task #49:
    (a) round-3 step3b: float64 + partial_day + thin_data
    (b) older: float32 + no flags
  Backfilled rows fill (a)-style columns with conservative defaults
  (partial_day=False, thin_data=False since yfinance daily is full-day).

Usage:
  python dev/scripts/data_integrity/backfill_2009_2014_cross_asset.py \\
    --start 2009-01-01 --end 2014-12-31 \\
    --symbols TLT IEF SHY GLD BIL SHV

  # dry-run preview (no writes):
  python dev/scripts/data_integrity/backfill_2009_2014_cross_asset.py \\
    --start 2009-01-01 --end 2014-12-31 --dry-run

After this runs successfully, distributions.parquet should also be
re-built so its sidecar covers 2009-2014 ex-dates that previously
got dropped (no daily ref close before 2015):
  python dev/scripts/data_integrity/build_distributions_parquet.py \\
    --symbols TLT IEF SHY GLD BIL SHV
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")


def _yfinance_factor_array_for_index(
    sym: str,
    bar_index: pd.DatetimeIndex,
) -> np.ndarray:
    """Vectorized: for each bar in bar_index, compute the cumulative
    yfinance split factor applied (= product over splits with
    ex_date > bar_date). Returns array same length as bar_index.

    yfinance ratio convention: ratio < 1 means reverse split (e.g.,
    0.5 = 1-for-2 reverse, price doubles). The factor applied to
    pre-split bars by yfinance Close is 1/ratio.

    Single yfinance API call per symbol; no per-bar call.
    """
    import yfinance as yf
    splits = yf.Ticker(sym).splits
    if splits is None or len(splits) == 0:
        return np.ones(len(bar_index), dtype="float64")
    if hasattr(splits.index, "tz") and splits.index.tz is not None:
        splits.index = splits.index.tz_convert("America/New_York").tz_localize(None)
    splits.index = splits.index.normalize()
    splits = splits.sort_index()
    # For each bar at t, factor = product of (1/ratio) for splits at ex > t.
    split_dates = splits.index.to_numpy(dtype="datetime64[ns]")
    inv_ratios = (1.0 / splits.values.astype("float64"))
    # cumulative product from the right: suffix_prod[i] = product of
    # inv_ratios[i:] (i.e., factor for a bar at any time strictly
    # before split_dates[i]).
    suffix_prod = np.ones(len(inv_ratios) + 1, dtype="float64")
    for i in range(len(inv_ratios) - 1, -1, -1):
        suffix_prod[i] = suffix_prod[i + 1] * inv_ratios[i]
    # For each bar t, find index i = number of splits with ex_date <= t.
    # Then factor = suffix_prod[i].
    bar_dates = bar_index.normalize().to_numpy(dtype="datetime64[ns]")
    i_arr = np.searchsorted(split_dates, bar_dates, side="right")
    return suffix_prod[i_arr]


def _backfill_one(
    sym: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Fetch yfinance daily for sym between [start, end], undo yfinance
    split adjustment to return true raw daily bars matching the canonical
    daily/<sym>.parquet schema."""
    import yfinance as yf

    print(f"  fetching {sym} {start} → {end}...")
    hist = yf.Ticker(sym).history(start=start, end=end, auto_adjust=False)
    if hist.empty:
        print(f"    EMPTY — yfinance returned 0 rows")
        return pd.DataFrame()

    if hasattr(hist.index, "tz") and hist.index.tz is not None:
        hist.index = hist.index.tz_convert("America/New_York").tz_localize(None)
    hist.index = hist.index.normalize()
    hist.index.name = "date"

    # Determine if any splits are in our splits.parquet for this sym
    splits_df = pd.read_parquet(PROJ / "data" / "ref" / "splits.parquet")
    sym_splits = splits_df[splits_df["symbol"] == sym]
    n_splits = len(sym_splits)

    # Apply UNDO of yfinance split scaling so output matches canonical raw.
    # For each bar at t, yfinance Close = raw_close × yfinance_factor(t)
    # where yfinance_factor(t) = product over yfinance splits with ex_date > t.
    # We want raw_close = yf_Close / yfinance_factor(t).
    if n_splits > 0:
        factors = _yfinance_factor_array_for_index(sym, hist.index)
        for col in ("Open", "High", "Low", "Close"):
            hist[col] = hist[col] / factors
        # Volume scales inversely (yfinance volume divides by factor; undo
        # → multiply by factor)
        hist["Volume"] = hist["Volume"] * factors
        print(f"    applied yfinance-split-undo: {n_splits} splits in our table; "
              f"factor range [{factors.min():.4f}, {factors.max():.4f}]")
    else:
        print(f"    no splits in our table for {sym}; yfinance Close = raw")

    # Remap columns to canonical schema
    out = pd.DataFrame({
        "open": hist["Open"].astype("float64"),
        "high": hist["High"].astype("float64"),
        "low": hist["Low"].astype("float64"),
        "close": hist["Close"].astype("float64"),
        "volume": hist["Volume"].astype("float64"),
        "amount": np.nan,  # yfinance daily doesn't include amount
        "partial_day": False,
        "thin_data": False,
    }, index=hist.index)

    return out


def _merge_with_existing(
    sym: str,
    backfill: pd.DataFrame,
    dry_run: bool = False,
) -> int:
    """Merge backfill with existing daily/<sym>.parquet. Existing rows
    win on date overlaps. Returns number of new rows added (0 if dry_run)."""
    p = PROJ / "data" / "daily" / f"{sym}.parquet"
    if not p.exists():
        print(f"  NO EXISTING file at {p}; aborting")
        return 0
    existing = pd.read_parquet(p)
    existing_min = existing.index.min()

    # Drop backfill rows that overlap existing (existing wins)
    pre_existing = backfill[backfill.index < existing_min]
    if pre_existing.empty:
        print(f"  no new rows (backfill overlaps existing entirely)")
        return 0

    # Schema reconciliation: align columns + dtypes to existing
    aligned = pre_existing.copy()
    for col in existing.columns:
        if col not in aligned.columns:
            # existing has a col we don't (e.g., partial_day, thin_data)
            if existing[col].dtype == bool or existing[col].dtype == "object":
                aligned[col] = False
            else:
                aligned[col] = np.nan
        # cast to existing dtype
        if existing[col].dtype != aligned[col].dtype:
            try:
                aligned[col] = aligned[col].astype(existing[col].dtype)
            except (ValueError, TypeError):
                pass  # leave as-is; pandas will broadcast on concat
    aligned = aligned[existing.columns]  # column order

    merged = pd.concat([aligned, existing]).sort_index()
    n_new = len(aligned)

    print(f"  backfill: {len(aligned)} new rows ({aligned.index.min().date()} → "
          f"{aligned.index.max().date()})")
    print(f"  merged total: {len(merged)} rows ({merged.index.min().date()} → "
          f"{merged.index.max().date()})")

    if not dry_run:
        merged.to_parquet(p, compression="snappy")
        print(f"  WROTE {p}")

    # Provenance
    if not dry_run:
        prov_path = PROJ / "data" / "ref" / "bar_provenance.parquet"
        if prov_path.exists():
            prov = pd.read_parquet(prov_path)
            new_row = pd.DataFrame([{
                "symbol": sym, "freq": "1d",
                "source_type": "yfinance_daily_backfill_2009_2014",
                "rule_version": "yf_auto_adjust_false_split_undone",
                "first_bar_ts": aligned.index.min(),
                "last_bar_ts": aligned.index.max(),
                "n_bars_added": len(aligned),
                "updated_at": pd.Timestamp.now(),
            }])
            prov = pd.concat([prov, new_row], ignore_index=True)
            prov.to_parquet(prov_path, index=False)
            print(f"  provenance updated")

    return n_new


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--start", default="2009-01-01")
    ap.add_argument("--end", default="2014-12-31")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"[backfill] symbols: {args.symbols}")
    print(f"[backfill] range: {args.start} → {args.end}")
    print(f"[backfill] dry_run: {args.dry_run}")

    total_new = 0
    for sym in args.symbols:
        print(f"\n[backfill] {sym}")
        bf = _backfill_one(sym, args.start, args.end)
        if bf.empty:
            continue
        n_new = _merge_with_existing(sym, bf, dry_run=args.dry_run)
        total_new += n_new

    print(f"\n[backfill] TOTAL new rows: {total_new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
