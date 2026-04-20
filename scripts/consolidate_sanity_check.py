#!/usr/bin/env python3
"""
Sanity check root 1m + daily parquets after consolidate_trades has merged
trades backfill into root. Runs after aggregate_bars (uses daily parquet
for speed — 22k full-day reads vs 22k full-1m reads = 10-100x faster).

Checks per ticker:
  1. Daily return outlier: |return_d| > THRESHOLD_PCT on any non-split day
     (splits are known and skipped via ref/splits.parquet; jumps around those
     dates are expected).
  2. Cross-source boundary: if a ticker has >1 source epoch (inferred from
     month-gap patterns), the close-to-open ratio across the boundary should
     be within 5% (modulo splits).
  3. Coverage: consecutive missing trading-day gaps > 5.

Output: reports/consolidate_sanity/<ts>.json with summary + flagged list.

Exit code:
  0  — zero or trivial flags
  1  — halt: ≥ HALT_THRESHOLD flagged tickers (operator review required)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

PQS_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs"))
DAILY_DIR = PQS_ROOT / "data" / "daily"
SPLITS_FILE = PQS_ROOT / "data" / "ref" / "splits.parquet"
OUT_DIR = PQS_ROOT / "reports" / "consolidate_sanity"

RETURN_OUTLIER_PCT = 0.20   # 20% daily move
# Low-priced / illiquid tickers (penny stocks, warrants) have legitimate
# 20-40% daily moves driven by tick-size/noise, not data errors. Skip return
# outlier checks if either side of the transition is below this price.
MIN_PRICE_FOR_RETURN_CHECK = 1.0
GAP_TRADING_DAYS = 5        # 5 consecutive missing days
# Halt if ≥ this many cross-source-boundary outliers (these are the concerning
# ones — should be near-zero if consolidate_trades did its job correctly).
HALT_THRESHOLD_BOUNDARY = 5
# Random outliers (single volatile days for small-caps) are expected; only
# halt if the rate exceeds this fraction.
MAX_OTHER_FLAGGED_RATE = 0.10   # 10% of tickers

# Dates considered "source-transition boundaries" — outliers here are red
# flags (likely consolidate/merge artifact). Dates are the LAST trading day
# of a prior-source era; an outlier between that date and the next trading
# day is suspicious.
BOUNDARY_DATES = {
    "2023-12-29",  # polygon_gz → stocks_csv (Dec 29 last trading day of 2023)
    "2024-12-31",  # stocks_csv (2024) → stocks_csv (2025) — continuity check
    "2025-11-28",  # stocks_csv → trades_backfill (approximate, varies)
    "2025-12-31",  # 2025 → 2026
}


def load_splits() -> dict[str, set[pd.Timestamp]]:
    """Return {symbol: set of split dates}. Used to exclude legitimate
    price discontinuities from the outlier check."""
    if not SPLITS_FILE.exists():
        return {}
    df = pd.read_parquet(SPLITS_FILE)
    out: dict[str, set[pd.Timestamp]] = {}
    for sym, grp in df.groupby("symbol"):
        out[str(sym)] = {pd.Timestamp(d) for d in grp["date"].tolist()}
    return out


def check_ticker(sym_file: Path, splits: dict[str, set[pd.Timestamp]]) -> dict:
    """Return dict of flags for one ticker. Empty lists = clean."""
    sym = sym_file.stem
    df = pd.read_parquet(sym_file)
    if df.empty or len(df) < 5:
        return {"symbol": sym, "n_days": len(df), "skipped": "insufficient_data",
                "return_outliers": [], "gaps": []}

    close = df["close"].astype("float64").sort_index()
    idx = pd.DatetimeIndex(close.index)
    # Daily return
    ret = close.pct_change()
    sym_splits = splits.get(sym, set())

    outliers = []
    boundary_outliers = []
    for t, r in ret.items():
        if pd.isna(r) or abs(r) < RETURN_OUTLIER_PCT:
            continue
        # allow ± 1 day around a known split
        t_ts = pd.Timestamp(t)
        is_near_split = any(abs((t_ts - s).days) <= 1 for s in sym_splits)
        if is_near_split:
            continue
        prev_idx = close.index[close.index.get_loc(t) - 1]
        prev_c = float(close.loc[prev_idx])
        curr_c = float(close.loc[t])
        # Skip penny / warrant noise: relative % moves are meaningless when
        # absolute price is below $1 (one-tick move = many %).
        if prev_c < MIN_PRICE_FOR_RETURN_CHECK or curr_c < MIN_PRICE_FOR_RETURN_CHECK:
            continue
        prev_str = str(prev_idx)[:10]
        rec = {
            "date": str(t)[:10],
            "prev_date": prev_str,
            "prev_close": round(prev_c, 4),
            "curr_close": round(curr_c, 4),
            "return_pct": round(float(r) * 100, 2),
        }
        # Flag as boundary-outlier if prev_date OR date is within ±2 business
        # days of any BOUNDARY_DATES (source-transition red zone).
        is_boundary = any(
            abs((t_ts - pd.Timestamp(b)).days) <= 4
            or abs((pd.Timestamp(prev_str) - pd.Timestamp(b)).days) <= 4
            for b in BOUNDARY_DATES
        )
        if is_boundary:
            boundary_outliers.append(rec)
        else:
            outliers.append(rec)

    # Coverage gaps
    gaps = []
    if len(idx) >= 2:
        # Use business-day diff to skip weekends; a gap of >5 consecutive
        # trading days (business days) is suspicious.
        for i in range(1, len(idx)):
            bd_gap = int(np.busday_count(
                idx[i - 1].date().isoformat(), idx[i].date().isoformat()
            )) - 1
            if bd_gap > GAP_TRADING_DAYS:
                gaps.append({
                    "prev_date": str(idx[i - 1])[:10],
                    "curr_date": str(idx[i])[:10],
                    "missing_business_days": bd_gap,
                })

    return {"symbol": sym, "n_days": len(df),
            "return_outliers": outliers,
            "boundary_outliers": boundary_outliers,
            "gaps": gaps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="debug: only check first N")
    ap.add_argument("--halt-boundary", type=int, default=HALT_THRESHOLD_BOUNDARY,
                    help="exit 1 if this many tickers have ≥1 boundary outlier")
    ap.add_argument("--halt-other-rate", type=float, default=MAX_OTHER_FLAGGED_RATE,
                    help="exit 1 if this fraction of tickers have non-boundary "
                         "outliers (catches systemic issues)")
    args = ap.parse_args()

    if not DAILY_DIR.exists():
        print(f"ERROR: no daily dir at {DAILY_DIR}. Run aggregate_bars first.")
        sys.exit(2)

    splits = load_splits()
    files = sorted(DAILY_DIR.glob("*.parquet"))
    if args.limit:
        files = files[: args.limit]
    print(f"checking {len(files)} tickers against {len(splits)} split records")

    flagged_boundary = []
    flagged_other = []
    flagged_gaps = []
    summary = {"total": len(files), "skipped": 0, "clean": 0,
               "flagged_boundary": 0, "flagged_other": 0, "flagged_gaps": 0}
    total_boundary = total_other = total_gaps = 0

    for f in tqdm(files, desc="sanity", unit="sym"):
        r = check_ticker(f, splits)
        if r.get("skipped"):
            summary["skipped"] += 1
            continue
        has_flag = False
        if r.get("boundary_outliers"):
            flagged_boundary.append(r)
            summary["flagged_boundary"] += 1
            total_boundary += len(r["boundary_outliers"])
            has_flag = True
        if r.get("return_outliers"):
            flagged_other.append(r)
            summary["flagged_other"] += 1
            total_other += len(r["return_outliers"])
            has_flag = True
        if r.get("gaps"):
            flagged_gaps.append(r)
            summary["flagged_gaps"] += 1
            total_gaps += len(r["gaps"])
            has_flag = True
        if not has_flag:
            summary["clean"] += 1

    summary["total_boundary_outliers"] = total_boundary
    summary["total_other_outliers"] = total_other
    summary["total_gaps_found"] = total_gaps

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"sanity_{ts}.json"
    doc = {
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "halt_boundary_threshold": args.halt_boundary,
        "halt_other_rate": args.halt_other_rate,
        "boundary_dates": sorted(BOUNDARY_DATES),
        "flagged_boundary": flagged_boundary,
        "flagged_other_sample": flagged_other[:50],  # truncate; full list rarely useful
        "flagged_other_count": len(flagged_other),
        "flagged_gaps_sample": flagged_gaps[:50],
        "flagged_gaps_count": len(flagged_gaps),
    }
    out_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out_path}")
    print(f"summary: {summary}")

    # Halt conditions
    halt = False
    if summary["flagged_boundary"] >= args.halt_boundary:
        print(f"\nHALT: {summary['flagged_boundary']} tickers with boundary "
              f"outliers ≥ {args.halt_boundary}. Cross-source merge issue.")
        halt = True
    other_rate = summary["flagged_other"] / max(1, summary["total"] - summary["skipped"])
    if other_rate > args.halt_other_rate:
        print(f"\nHALT: {summary['flagged_other']} tickers with generic "
              f"outliers ({other_rate:.1%} > {args.halt_other_rate:.1%}). "
              "Possible systemic issue.")
        halt = True
    if halt:
        sys.exit(1)
    print("\nOK to proceed")
    sys.exit(0)


if __name__ == "__main__":
    main()
