"""Scope the data/daily/<sym>.parquet heterogeneous split-adjustment issue.

Step 0 (RCMv1 retro β verification, 2026-04-30) and Step 3a (cycle #02
harness eval, 2026-04-30) both surfaced the same bug: data/daily/<sym>.parquet
contains bars from multiple sources merged without normalization, so
adjacent rows can have prices in different "scales" (e.g. LRCX 2015-04-22
$6.72 vs 2015-04-23 $77.07). BarStore.load(adjusted=True) cannot repair
this because splits.parquet handles forward-split cascades only.

This diagnostic enumerates which symbols are affected and roughly how
many days, so we can decide whether to fix (re-aggregate from canonical
1m → daily) or quarantine.

Output: data/audit/heterogeneous_split_audit_<date>.json with per-symbol
counts and worst offenders.

Decision authority: tactical (P3 follow-up after cycle #02 closeout).
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
DATA_DAILY = PROJ / "data" / "daily"


def scan_one_symbol(sym: str, ratio_tol: tuple[float, float] = (0.2, 5.0),
                     ret_abs_tol: float = 0.5) -> dict:
    """Scan one symbol's daily parquet for adjacent-day ratio anomalies.

    Anomaly = day-over-day close ratio outside (0.2x, 5.0x) i.e. price
    fell to <20% or rose to >500% in one day. A real stock split shows
    up as ONE such day matching the splits.parquet ratio. Heterogeneous
    adjustment shows up as MANY such days, alternating up and down.
    """
    p = DATA_DAILY / f"{sym}.parquet"
    if not p.exists():
        return {"symbol": sym, "exists": False}
    try:
        df = pd.read_parquet(p)
    except Exception as e:
        return {"symbol": sym, "exists": True, "error": str(e)}
    if "close" not in df.columns or len(df) < 10:
        return {"symbol": sym, "exists": True, "n_rows": len(df), "error": "insufficient data"}

    close = df["close"].dropna()
    if len(close) < 10:
        return {"symbol": sym, "exists": True, "n_rows": len(close), "error": "insufficient close"}

    ratio = close / close.shift(1)
    # Anomaly: abnormal ratio
    anom_low = ratio < ratio_tol[0]
    anom_high = ratio > ratio_tol[1]
    n_low = int(anom_low.sum())
    n_high = int(anom_high.sum())

    # Heterogeneous fingerprint: many adjacent flips (up-then-down rapidly)
    anom_any = anom_low | anom_high
    n_anom = int(anom_any.sum())

    # Stricter test: is there a "rapid alternation" pattern? Count number
    # of times a day is anomalous and the very next day is also anomalous.
    # A true split has 1 anomaly day. Heterogeneous has many anomaly days
    # close together.
    rapid_alt = (anom_any & anom_any.shift(-1).fillna(False)) | \
                (anom_any & anom_any.shift(-2).fillna(False))
    n_rapid_alt = int(rapid_alt.sum())

    # Worst offender dates: top-3 most extreme up + down
    worst_up = ratio.nlargest(3)
    worst_down = ratio.nsmallest(3)

    # Heuristic flag: heterogeneous if n_anom > 5 AND n_rapid_alt > 2
    is_heterogeneous = (n_anom > 5) and (n_rapid_alt > 2)

    return {
        "symbol": sym,
        "exists": True,
        "n_rows": int(len(close)),
        "first_date": str(close.index[0].date()) if len(close) else None,
        "last_date": str(close.index[-1].date()) if len(close) else None,
        "n_anomalous_ratio_lt_0.2": n_low,
        "n_anomalous_ratio_gt_5.0": n_high,
        "n_anomalous_total": n_anom,
        "n_rapid_alternation_pairs": n_rapid_alt,
        "is_heterogeneous_likely": is_heterogeneous,
        "worst_up_ratios": [
            {"date": str(d.date()), "ratio": float(r)}
            for d, r in worst_up.items() if r > 1.5
        ],
        "worst_down_ratios": [
            {"date": str(d.date()), "ratio": float(r)}
            for d, r in worst_down.items() if r < 0.7
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else (
        PROJ / "data" / "audit" / f"heterogeneous_split_audit_{date.today().isoformat()}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    syms = sorted([p.stem for p in DATA_DAILY.glob("*.parquet")])
    print(f"Scanning {len(syms)} parquet files in {DATA_DAILY}")

    results = []
    affected = []
    for sym in syms:
        r = scan_one_symbol(sym)
        results.append(r)
        if r.get("is_heterogeneous_likely"):
            affected.append(r)
            print(f"  AFFECTED  {sym}: n_anom={r['n_anomalous_total']} "
                  f"n_rapid={r['n_rapid_alternation_pairs']} "
                  f"first={r['first_date']} last={r['last_date']}")

    summary = {
        "scan_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "data_dir": str(DATA_DAILY),
        "n_symbols_scanned": len(results),
        "n_symbols_likely_heterogeneous": len(affected),
        "affected_symbols": [r["symbol"] for r in affected],
        "thresholds": {
            "ratio_anomaly_low": 0.2,
            "ratio_anomaly_high": 5.0,
            "n_anom_min": 5,
            "n_rapid_alt_pairs_min": 2,
        },
        "per_symbol_details": results,
    }
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}")
    print(f"\nSummary:")
    print(f"  scanned: {len(results)} symbols")
    print(f"  likely heterogeneous: {len(affected)}")
    print(f"  affected list: {[r['symbol'] for r in affected]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
