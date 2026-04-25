#!/usr/bin/env python
"""
Round-3 step 3b — full universe daily-parquet rebuild via the
1m → daily aggregator (`core.data.daily_aggregator`).

Per round-3 implementation note + step-3a-rev user pinning:
  * canonical source = polygon 1m parquet (`data/intraday/1m/<sym>.parquet`)
  * label = real ET trading day; close = 15:59 ET 1m bar close
  * two-tier N_min: complete >= 350, thin_data 300-349, quarantine < 300
  * NYSE half-session whitelist (dynamic) → partial_day=True
  * NO fallback. Single canonical source. BRK-B and any zero-1m symbol
    are dropped (manifest reason='no_1m_data').

Sidecars produced (round-3 step 3b deliverables):
  data/ref/incomplete_days.parquet      — per (symbol, date) quarantine
                                          rows: reason / n_bars / first/last bar ts
  data/ref/data_quality_watch.parquet   — per-symbol watch flags for
                                          BKNG/CMG/TKO/TT/SOXL/BRK-B + any
                                          symbol with thin_data_pct > 5% or
                                          quarantine_pct > 10%
  data/ref/daily_rebuild_manifest.parquet
                                        — per-symbol: old_rows / new_rows /
                                          thin_data / quarantined / written /
                                          drop_reason

Default mode is `--dry-run` (no parquet writes). Use `--apply` to write
fresh `data/daily/<sym>.parquet` (overwrite). Always writes the three
sidecars + a console summary.

Usage:
    python dev/scripts/data_integrity/rebuild_daily.py --apply
    python dev/scripts/data_integrity/rebuild_daily.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.data.daily_aggregator import aggregate_1m_to_daily

DEFAULT_UNIVERSE_YAML = ROOT / "config" / "universe.yaml"
DAILY_DIR = ROOT / "data" / "daily"
ONEMIN_DIR = ROOT / "data" / "intraday" / "1m"
REF_DIR = ROOT / "data" / "ref"

INCOMPLETE_DAYS_PATH = REF_DIR / "incomplete_days.parquet"
WATCH_SIDECAR_PATH   = REF_DIR / "data_quality_watch.parquet"
MANIFEST_PATH        = REF_DIR / "daily_rebuild_manifest.parquet"

# Watch list per round-3 step-3a-rev:
WATCH_LIST_HARDCODED = ["BKNG", "CMG", "TKO", "TT", "SOXL", "BRK-B"]
THIN_PCT_FLAG = 5.0       # symbols with thin_data_pct > 5% get watch flag
QUAR_PCT_FLAG = 10.0      # symbols with quarantine_pct > 10% get watch flag


def _load_universe() -> list[str]:
    cfg = yaml.safe_load(DEFAULT_UNIVERSE_YAML.read_text())
    return list(cfg.get("seed_pool", []))


def _load_existing_daily_row_count(symbol: str) -> int:
    p = DAILY_DIR / f"{symbol}.parquet"
    if not p.exists():
        return 0
    try:
        df = pd.read_parquet(p)
        return len(df)
    except Exception:
        return -1  # unreadable


def _process_symbol(
    symbol: str,
) -> tuple[Optional[pd.DataFrame], pd.DataFrame, dict]:
    """
    Return (daily_df_or_None, audit_df, manifest_row).
    daily_df is None when the symbol has no 1m data (drop case).
    """
    onemin_path = ONEMIN_DIR / f"{symbol}.parquet"
    if not onemin_path.exists():
        return None, _empty_audit_df(), {
            "symbol": symbol,
            "old_rows": _load_existing_daily_row_count(symbol),
            "new_rows": 0,
            "thin_data_count": 0,
            "quarantine_count": 0,
            "partial_count": 0,
            "written": False,
            "drop_reason": "no_1m_parquet",
        }
    try:
        bars_1m = pd.read_parquet(onemin_path)
    except Exception as exc:
        return None, _empty_audit_df(), {
            "symbol": symbol,
            "old_rows": _load_existing_daily_row_count(symbol),
            "new_rows": 0,
            "thin_data_count": 0,
            "quarantine_count": 0,
            "partial_count": 0,
            "written": False,
            "drop_reason": f"parquet_load_error: {str(exc)[:60]}",
        }
    if bars_1m.empty:
        return None, _empty_audit_df(), {
            "symbol": symbol,
            "old_rows": _load_existing_daily_row_count(symbol),
            "new_rows": 0,
            "thin_data_count": 0,
            "quarantine_count": 0,
            "partial_count": 0,
            "written": False,
            "drop_reason": "empty_1m",
        }
    if bars_1m.index.tz is not None:
        bars_1m = bars_1m.copy()
        bars_1m.index = bars_1m.index.tz_localize(None)

    daily_df, audit_df = aggregate_1m_to_daily(bars_1m)
    if daily_df.empty:
        return None, audit_df, {
            "symbol": symbol,
            "old_rows": _load_existing_daily_row_count(symbol),
            "new_rows": 0,
            "thin_data_count": 0,
            "quarantine_count": int(len(audit_df)),
            "partial_count": 0,
            "written": False,
            "drop_reason": "all_days_quarantined",
        }

    # Add `amount` column for back-compat with existing daily schema
    # (1m source has no dollar volume; downstream code does not use
    # this column — we keep it as NaN to match yfinance fallback).
    daily_df = daily_df.copy()
    daily_df["amount"] = np.nan

    return daily_df, audit_df, {
        "symbol": symbol,
        "old_rows": _load_existing_daily_row_count(symbol),
        "new_rows": int(len(daily_df)),
        "thin_data_count": int(daily_df["thin_data"].sum()),
        "quarantine_count": int(len(audit_df)),
        "partial_count": int(daily_df["partial_day"].sum()),
        "written": False,        # set True downstream if --apply
        "drop_reason": "",
    }


def _empty_audit_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["reason", "n_bars", "first_bar_ts", "last_bar_ts",
                 "partial_day_whitelisted"],
        index=pd.DatetimeIndex([], name="date"),
    )


def _emit_daily_parquet(symbol: str, daily_df: pd.DataFrame) -> None:
    """Write daily parquet at data/daily/<sym>.parquet (overwrite)."""
    out_path = DAILY_DIR / f"{symbol}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Match existing daily schema: ['open','high','low','close','volume','amount']
    # plus the new 'partial_day' and 'thin_data' sidecar flags.
    cols = ["open", "high", "low", "close", "volume", "amount",
            "partial_day", "thin_data"]
    out = daily_df[cols].copy()
    out.index.name = "date"
    out.to_parquet(out_path, index=True)


def _build_watch_sidecar(manifest: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol data-quality watch sidecar."""
    rows = []
    for _, r in manifest.iterrows():
        sym = r["symbol"]
        is_hard = sym in WATCH_LIST_HARDCODED
        if r["new_rows"] > 0:
            thin_pct = r["thin_data_count"] / r["new_rows"] * 100
        else:
            thin_pct = 0.0
        total_emitted_or_q = r["new_rows"] + r["quarantine_count"]
        if total_emitted_or_q > 0:
            quar_pct = r["quarantine_count"] / total_emitted_or_q * 100
        else:
            quar_pct = 0.0

        is_dropped = bool(r["drop_reason"])
        flagged = (
            is_hard
            or thin_pct > THIN_PCT_FLAG
            or quar_pct > QUAR_PCT_FLAG
            or is_dropped
        )
        if not flagged:
            continue

        # Reasons (csv-friendly)
        reasons = []
        if is_dropped:
            reasons.append(f"dropped:{r['drop_reason']}")
        if is_hard:
            reasons.append("hardcoded_watch")
        if thin_pct > THIN_PCT_FLAG:
            reasons.append(f"thin_pct={thin_pct:.1f}%")
        if quar_pct > QUAR_PCT_FLAG:
            reasons.append(f"quar_pct={quar_pct:.1f}%")
        rows.append({
            "symbol": sym,
            "thin_data_pct": round(thin_pct, 2),
            "quarantine_pct": round(quar_pct, 2),
            "complete_count": int(r["new_rows"] - r["thin_data_count"] - r["partial_count"]),
            "thin_data_count": int(r["thin_data_count"]),
            "partial_count": int(r["partial_count"]),
            "quarantine_count": int(r["quarantine_count"]),
            "written": bool(r["written"]),
            "drop_reason": str(r["drop_reason"]),
            "watch_reasons": " | ".join(reasons),
        })
    return pd.DataFrame(rows).sort_values(
        ["written", "quarantine_pct"], ascending=[True, False]
    ) if rows else pd.DataFrame(
        columns=["symbol","thin_data_pct","quarantine_pct","complete_count",
                 "thin_data_count","partial_count","quarantine_count",
                 "written","drop_reason","watch_reasons"],
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write daily parquet (default: dry-run).")
    ap.add_argument("--universe-symbols", nargs="*",
                    help="Optional: subset of symbols (default: full seed_pool).")
    args = ap.parse_args()

    REF_DIR.mkdir(parents=True, exist_ok=True)

    universe = args.universe_symbols or _load_universe()
    print(f"[rebuild_daily] {len(universe)} symbols, mode = "
          f"{'APPLY (writes parquet)' if args.apply else 'DRY-RUN'}")

    t0 = time.time()
    manifest_rows: list[dict] = []
    audit_frames: list[pd.DataFrame] = []

    for i, sym in enumerate(universe):
        daily_df, audit_df, m_row = _process_symbol(sym)

        if not audit_df.empty:
            ad = audit_df.copy()
            ad["symbol"] = sym
            ad = ad.reset_index().set_index(["symbol", "date"])
            audit_frames.append(ad)

        if daily_df is not None:
            if args.apply:
                _emit_daily_parquet(sym, daily_df)
                m_row["written"] = True

        manifest_rows.append(m_row)

        if (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(universe)} done in {elapsed:.1f}s "
                  f"(latest: {sym}: new={m_row['new_rows']} "
                  f"thin={m_row['thin_data_count']} q={m_row['quarantine_count']} "
                  f"written={m_row['written']})",
                  flush=True)

    manifest = pd.DataFrame(manifest_rows)
    print(f"\n[rebuild_daily] all {len(universe)} processed in {time.time()-t0:.1f}s")

    # Sidecars
    incomplete_all = (
        pd.concat(audit_frames) if audit_frames else
        pd.DataFrame(columns=["reason","n_bars","first_bar_ts","last_bar_ts",
                              "partial_day_whitelisted"])
    )
    watch = _build_watch_sidecar(manifest)

    if args.apply:
        manifest.to_parquet(MANIFEST_PATH, index=False)
        incomplete_all.to_parquet(INCOMPLETE_DAYS_PATH)
        watch.to_parquet(WATCH_SIDECAR_PATH, index=False)
        print(f"\nSidecars written:")
        print(f"  - {MANIFEST_PATH}")
        print(f"  - {INCOMPLETE_DAYS_PATH}")
        print(f"  - {WATCH_SIDECAR_PATH}")
    else:
        print(f"\n[DRY-RUN] would write sidecars:")
        print(f"  - {MANIFEST_PATH}: {len(manifest)} rows")
        print(f"  - {INCOMPLETE_DAYS_PATH}: {len(incomplete_all)} rows")
        print(f"  - {WATCH_SIDECAR_PATH}: {len(watch)} rows")

    # Console summary
    print(f"\n[SUMMARY]")
    true_drops = manifest[manifest["drop_reason"] != ""]
    actually_written = manifest[manifest["written"] == True]
    would_write = manifest[(manifest["drop_reason"] == "") & (manifest["written"] == False)]
    total_new = int(manifest["new_rows"].sum())
    total_old = int(manifest["old_rows"].sum())
    total_thin = int(manifest["thin_data_count"].sum())
    total_q = int(manifest["quarantine_count"].sum())
    total_partial = int(manifest["partial_count"].sum())
    print(f"  Symbols processed:    {len(manifest)}")
    print(f"  Symbols actually written: {len(actually_written)}  (apply mode)")
    print(f"  Symbols would-write (dry-run): {len(would_write)}")
    print(f"  Symbols dropped:      {len(true_drops)} {true_drops['drop_reason'].tolist() if len(true_drops) else ''}")
    print(f"  Total new rows:       {total_new:,}")
    print(f"    of which thin_data:    {total_thin:,} ({total_thin/max(total_new,1)*100:.2f}%)")
    print(f"    of which partial:      {total_partial:,} ({total_partial/max(total_new,1)*100:.2f}%)")
    print(f"  Quarantined rows:     {total_q:,}")
    print(f"  Old rows (cur store): {total_old:,}")
    print(f"  Net delta:            {total_new - total_old:+,}")
    print(f"\n  Watch sidecar:    {len(watch)} symbols flagged")
    if len(watch):
        print(watch[["symbol","quarantine_pct","thin_data_pct","written","watch_reasons"]].to_string(index=False))


if __name__ == "__main__":
    main()
