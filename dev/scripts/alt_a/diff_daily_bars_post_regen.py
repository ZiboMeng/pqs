"""Diff regenerated daily bars vs snapshot for 53-股 alt-A universe.

Used by Phase 3 Step A: assess blast radius after running aggregate_bars.py
for the alt-A universe. If daily bars differ materially from snapshot,
cycle04-08 reproducibility is at risk and snapshot should be restored.

Tolerance:
  - close: |diff| / close < 0.1% (10 bps)
  - volume: |diff| / volume < 1% (CSV-source rounding tolerance)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd

ALT_A_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "PWR", "WMT", "GILD",
    "JNJ", "VZ", "OXY", "GIS", "WEC", "EA", "ED", "DG", "CLX", "GS", "MS", "C",
    "LRCX", "KLAC", "CAT", "MU", "AVGO", "TER", "TJX", "TKO", "TRGP", "TRV",
    "TSN", "TT", "TXN", "UNP", "VICI", "COST", "AXP", "BKNG", "APD", "ABT",
    "CMG", "COP", "UNH", "LLY", "ISRG", "NEE", "MCK", "CME", "TMO", "A", "ACGL",
]


def diff_one(sym: str, new_dir: Path, snap_dir: Path,
             close_tol_bps: float = 10.0,
             volume_tol_pct: float = 1.0) -> dict:
    """Diff single symbol's daily bars."""
    new_p = new_dir / f"{sym}.parquet"
    snap_p = snap_dir / f"{sym}.parquet"
    if not new_p.exists():
        return {"symbol": sym, "status": "new_missing"}
    if not snap_p.exists():
        return {"symbol": sym, "status": "snap_missing"}

    new_df = pd.read_parquet(new_p).sort_index()
    snap_df = pd.read_parquet(snap_p).sort_index()

    # Align on common index
    common = new_df.index.intersection(snap_df.index)
    if common.empty:
        return {"symbol": sym, "status": "no_overlap",
                "new_n": len(new_df), "snap_n": len(snap_df)}

    n1 = new_df.loc[common]
    s1 = snap_df.loc[common]

    # Close diff (bps)
    if "close" in n1.columns and "close" in s1.columns:
        close_diff_bps = ((n1["close"] - s1["close"]).abs() /
                          s1["close"].replace(0, float("nan"))) * 10000
        close_diff_bps = close_diff_bps.dropna()
        close_max_bps = close_diff_bps.max() if not close_diff_bps.empty else 0
        close_above_tol_n = (close_diff_bps > close_tol_bps).sum()
    else:
        close_max_bps = 0; close_above_tol_n = 0

    # Volume diff (pct)
    if "volume" in n1.columns and "volume" in s1.columns:
        vol_diff_pct = ((n1["volume"] - s1["volume"]).abs() /
                        s1["volume"].replace(0, float("nan"))) * 100
        vol_diff_pct = vol_diff_pct.dropna()
        vol_max_pct = vol_diff_pct.max() if not vol_diff_pct.empty else 0
        vol_above_tol_n = (vol_diff_pct > volume_tol_pct).sum()
    else:
        vol_max_pct = 0; vol_above_tol_n = 0

    # Length diff
    len_new = len(new_df); len_snap = len(snap_df)
    len_delta = len_new - len_snap

    return {
        "symbol": sym,
        "status": ("MATERIAL_DRIFT" if (close_above_tol_n > 0 or vol_above_tol_n > 5)
                   else "OK"),
        "n_common": len(common),
        "len_new": len_new,
        "len_snap": len_snap,
        "len_delta": len_delta,
        "close_max_bps": round(close_max_bps, 2),
        "close_n_above_tol": int(close_above_tol_n),
        "vol_max_pct": round(vol_max_pct, 2),
        "vol_n_above_tol": int(vol_above_tol_n),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-dir", default="data/daily")
    ap.add_argument("--snap-dir", default="data/daily.snapshot.20260512")
    ap.add_argument("--close-tol-bps", type=float, default=10.0)
    ap.add_argument("--volume-tol-pct", type=float, default=1.0)
    ap.add_argument("--restore-from-snap-if-drift", action="store_true",
                    help="If material drift detected, RESTORE daily files "
                         "from snapshot. Use carefully.")
    args = ap.parse_args()

    rows = []
    for sym in ALT_A_UNIVERSE:
        rows.append(diff_one(sym, Path(args.new_dir), Path(args.snap_dir),
                             args.close_tol_bps, args.volume_tol_pct))
    df = pd.DataFrame(rows).set_index("symbol")
    print(df.to_string())

    summary_status = df["status"].value_counts().to_dict()
    print(f"\n=== Summary ===")
    print(f"Per-status counts: {summary_status}")

    drift_syms = df[df["status"] == "MATERIAL_DRIFT"].index.tolist()
    print(f"\nMaterial drift symbols ({len(drift_syms)}): {drift_syms}")

    if drift_syms and args.restore_from_snap_if_drift:
        for sym in drift_syms:
            snap_p = Path(args.snap_dir) / f"{sym}.parquet"
            new_p = Path(args.new_dir) / f"{sym}.parquet"
            if snap_p.exists():
                shutil.copy(snap_p, new_p)
                print(f"Restored {new_p} from snapshot")

    out_path = Path("data/audit/alt_a_phase3_daily_diff.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path)
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
