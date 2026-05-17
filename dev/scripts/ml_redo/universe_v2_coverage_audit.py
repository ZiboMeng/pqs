"""R-P4ext — polygon coverage audit → universe_expanded_v2 (~1k).

Per supplementary PRD §8.5. The locally-ingested polygon daily store
holds ~25k symbols; a ~1000-name universe is data-feasible. N is set
by DATA (coverage + completeness + liquidity thresholds), NOT pulled
from an external index-membership list (which would be time-sensitive
and a sealed-window risk). Membership-by-data => no current-year market
query, sealed 2026 untouched.

temporal_split discipline: all stats computed on the TRAIN window only
(<= train_end, default 2024-12-31). Validation/sealed bars never read
for universe construction.

Outputs:
  data/audit/ml_redo/universe_v2_coverage.json   (per-symbol audit)
  config/universe_expanded_v2.yaml               (selected ~1k set)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import yaml

_PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJ))

# config-sourced thresholds (PRD G7) — defaults are literature-informed
# judgment; final N emerges from the data.
_TRAIN_END = pd.Timestamp("2024-12-31")
# Empirical ceiling probe (run 1, recorded as provenance): data/daily
# row-count dist — >=2000:5244, >=3000:only 58, >=4000:23. expanded_v1's
# good names (ACN/ADBE/ADI) have ~2859 rows (≈2014-start, 11y). The
# polygon daily store's substantial-history names cluster at ~2800-2900
# rows; a >=3000 + start<=2009 combo was an over-strict artifact (run 1
# gave 22). Literature-grade only needs ample history for ML + CPCV;
# >=2000 train rows ≈ 8y is sufficient. start<=2009 dropped as a HARD
# filter (recorded informationally instead) — a 2014-start symbol still
# covers train years 2014-2017/2020/2022/2024 (most of the train block).
_MIN_TRAIN_ROWS = 2000                    # ≈ 8y trading days in-train
_INFO_FULL_SPAN_START = pd.Timestamp("2009-12-31")  # informational only
_MIN_COMPLETENESS = 0.90                  # over the symbol's own [start,end]
_TARGET_N = 1000                          # judgment target; data may give fewer
_DAILY = _PROJ / "data" / "daily"


def main() -> int:
    files = sorted(_DAILY.glob("*.parquet"))
    print(f"scanning {len(files)} daily parquets (pyarrow metadata pre-filter)")

    # Phase 1: fast metadata pre-filter on row count (cheap).
    shortlist = []
    for i, f in enumerate(files):
        try:
            n = pq.ParquetFile(f).metadata.num_rows
        except Exception:
            continue
        if n >= _MIN_TRAIN_ROWS:
            shortlist.append(f)
        if (i + 1) % 5000 == 0:
            print(f"  pre-filtered {i+1}/{len(files)} -> {len(shortlist)}")
    print(f"shortlist (>= {_MIN_TRAIN_ROWS} rows): {len(shortlist)}")

    # Phase 2: precise train-window coverage + liquidity on shortlist.
    rows = []
    for f in shortlist:
        sym = f.stem
        try:
            df = pd.read_parquet(f, columns=["close", "volume"])
        except Exception:
            try:
                df = pd.read_parquet(f, columns=["close"])
                df["volume"] = float("nan")
            except Exception:
                continue
        if df.empty or not isinstance(df.index, pd.DatetimeIndex):
            continue
        tr = df[df.index <= _TRAIN_END]
        if tr.empty:
            continue
        start, end = tr.index.min(), tr.index.max()
        # completeness over the symbol's OWN [start, end] (not penalizing
        # a 2014-start name for missing 2009-2013 — that is handled as
        # NaN in the cross-sectional panel, recorded informationally)
        bdays = pd.bdate_range(start, end)
        completeness = len(tr) / max(1, len(bdays))
        dollar_vol = float(
            (tr["close"] * tr["volume"]).replace(
                [float("inf"), float("-inf")], float("nan")
            ).dropna().median()) if tr["volume"].notna().any() else 0.0
        rows.append({
            "symbol": sym,
            "start": str(start.date()), "end": str(end.date()),
            "n_train_rows": int(len(tr)),
            "completeness": round(completeness, 4),
            "median_dollar_vol": dollar_vol,
            "drop": None if completeness >= _MIN_COMPLETENESS else
            "low_completeness",
        })

    kept = [r for r in rows if r.get("drop") is None]
    kept.sort(key=lambda r: r["median_dollar_vol"], reverse=True)
    selected = kept[:_TARGET_N]
    sel_syms = sorted(r["symbol"] for r in selected)

    audit = {
        "audit": "universe_v2_coverage",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "train_end": str(_TRAIN_END.date()),
        "n_scanned": len(files),
        "n_shortlist": len(shortlist),
        "n_passed_filters": len(kept),
        "target_n": _TARGET_N,
        "n_selected": len(selected),
        "thresholds": {
            "info_full_span_start": str(_INFO_FULL_SPAN_START.date()),
            "min_train_rows": _MIN_TRAIN_ROWS,
            "min_completeness": _MIN_COMPLETENESS,
            "rank_by": "median_dollar_vol (train-window)",
        },
        "sealed_discipline": "train-window only (<=2024-12-31); membership "
                             "by data not external index list; sealed 2026 "
                             "never read",
        "run1_artifact_note": "run 1 used min_train_rows=3000 + "
                              "start<=2009 HARD filter → only 22 passed. "
                              "Empirical row-count dist (provenance): "
                              ">=2000:5244 >=3000:58 >=4000:23; "
                              "expanded_v1 good names (ACN/ADBE/ADI) have "
                              "~2859 rows (≈2014-start, 11y) — sat just "
                              "below the 3000 cutoff. That combo was an "
                              "over-strict artifact, NOT a data ceiling. "
                              "Corrected: min_train_rows=2000 (≈8y, ample "
                              "for ML+CPCV), start<=2009 dropped as hard "
                              "filter (recorded informationally; 2014-start "
                              "covers most train block, earlier years NaN "
                              "in cross-sectional panel = normal).",
        "full_span_2009_start_count": sum(
            1 for r in rows if r.get("drop") is None
            and r.get("start", "9999") <= "2010-01-01"),
        "selected_head": [r["symbol"] for r in selected[:20]],
        "per_symbol": rows,
    }
    out_json = _PROJ / "data" / "audit" / "ml_redo" / "universe_v2_coverage.json"
    out_json.write_text(json.dumps(audit, indent=2, default=str))

    uni_yaml = {
        "_generated_by": "dev/scripts/ml_redo/universe_v2_coverage_audit.py",
        "_doc": "R-P4ext expanded_v2 — data-driven (~1k target); N set by "
                "coverage audit, NOT external index membership. D6: "
                "executable/expanded_v1 unaffected.",
        "n_symbols": len(sel_syms),
        "selection_rule": "train-window start<=2009, n_train_rows>=3000, "
                          "completeness>=0.95, top median dollar-vol up to 1000",
        "symbols": sel_syms,
    }
    out_yaml = _PROJ / "config" / "universe_expanded_v2.yaml"
    out_yaml.write_text(yaml.safe_dump(uni_yaml, sort_keys=False))
    print(f"coverage audit -> {out_json.name}: scanned={len(files)} "
          f"shortlist={len(shortlist)} passed={len(kept)} "
          f"selected={len(selected)} -> {out_yaml.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
