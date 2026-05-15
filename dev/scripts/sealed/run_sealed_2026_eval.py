"""Sealed 2026 single-shot evaluation — cycle06 + cycle08 survivors.

IRREVERSIBLE. Running this script reads the sealed 2026 holdout
(2026-01-01 → panel max date). Per CLAUDE.md + sealed_ledger M5
fail_closed_on_repeat, the 2026 holdout for split `alternating_regime_
holdout_v1` is single-shot. Once this runs, that split's 2026 holdout
is consumed; re-testing improved candidates requires bumping split_name.

Candidates (both passed Track A acceptance post-MaxDD-fix 2026-05-15):
  - cycle08_3f40e3f4ed1a: max_dd_126d + xsection_rank_63d + ret_5d, monthly
  - cycle06_31af04cf2ff9: drawup_from_252d_low + trend_tstat_20d + ret_2d, weekly

Both mined 2026-05-06/08 — BEFORE the 2026-05-13 WebSearch leak, so the
sealed test on them is clean (designs do not depend on leaked 2026 info).

Sealed-pass criteria (pre-committed, mirror Track A intent on 2026):
  - 2026 return vs SPY > 0 (HARD — CLAUDE.md primary outperformance)
  - 2026 MaxDD <= 25% (HARD — Black Swan ceiling; 2026 is a partial year)
  - 2026 Sharpe > 0 (HARD — basic risk-adjusted)

Run (consumes holdout):
    python dev/scripts/sealed/run_sealed_2026_eval.py --record
Run (compute only, still epistemically consumes — avoid):
    python dev/scripts/sealed/run_sealed_2026_eval.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "cycle06"))

import pandas as pd

CANDIDATES = [
    {"id": "cycle08_3f40e3f4ed1a", "cadence": "monthly",
     "features": ["max_dd_126d", "xsection_rank_63d", "ret_5d"],
     "source_trial": "3f40e3f4ed1a", "lineage": "track-c-cycle-2026-05-08-01"},
    {"id": "cycle06_31af04cf2ff9", "cadence": "weekly",
     "features": ["drawup_from_252d_low", "trend_tstat_20d", "ret_2d"],
     "source_trial": "31af04cf2ff9", "lineage": "track-c-cycle-2026-05-06-01"},
]


def _spec_sha256(cand: dict) -> str:
    """Deterministic hash of the canonical composite spec."""
    canon = json.dumps({
        "features": sorted(cand["features"]),
        "weights": "equal_third",
        "cadence": cand["cadence"],
        "construction": "cap_aware_cross_asset",
        "source_trial": cand["source_trial"],
    }, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJ, text=True).strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true",
                    help="record to sealed ledger (consumes holdout)")
    args = ap.parse_args()

    from core.config.loader import load_config
    from core.data.bar_store import BarStore
    from core.factors.base_masks import research_mask_default
    from core.factors.factor_generator import generate_all_factors
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER, CROSS_ASSET_RISK_CLUSTER_MAP,
        make_unified_cluster_map,
    )
    from core.research.sealed_ledger import run_sealed_eval_record
    from core.research.temporal_split import load_temporal_split

    print("=== SEALED 2026 single-shot evaluation ===")
    print(f"Mode: {'RECORD (consumes holdout)' if args.record else 'compute-only'}")

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)

    # Build panel INCLUDING 2026 (sealed). No partition cap.
    cross_asset_set = set(CROSS_ASSET_RISK_CLUSTER_MAP.keys())
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        atr = sym in cross_asset_set
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=atr, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    for col in ("open", "high", "low", "volume"):
        panel[col] = pd.DataFrame(frames[col]).reindex_like(panel["close"])

    panel_max = panel["close"].index.max().date()
    print(f"Panel: {panel['close'].shape}, max date {panel_max}")
    if panel_max.year < 2026:
        print("FATAL: panel has no 2026 data — nothing sealed to test")
        return 1

    bench = {b: panel["close"][b] for b in ("SPY", "QQQ")
             if b in panel["close"].columns}
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    mask = research_mask_default(panel["close"], panel["volume"])
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        s: ASSET_CLASS_BY_CLUSTER[cluster_map[s]]
        for s in panel["close"].columns if s in cluster_map
    }
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    git_sha = _git_sha()

    results = []
    for cand in CANDIDATES:
        feats = cand["features"]
        pm = {f: factors[f] for f in feats if f in factors}
        if len(pm) != len(feats):
            print(f"  ✗ {cand['id']}: missing {set(feats)-set(pm)}")
            continue
        spec = ResearchCompositeSpec(
            features=tuple(feats), weights=(1/3, 1/3, 1/3),
            family_counts={"X": 3}, holding_freq=cand["cadence"],
        )
        hc = HarnessConfig(
            rebalance_cadence=cand["cadence"],
            construction_mode="cap_aware_cross_asset",
            top_n=10, cluster_cap=0.20, max_single_weight=0.10,
            cluster_map=cluster_map, asset_class_map=asset_class_map,
            asset_class_caps={"equities": 0.70, "bonds": 0.40,
                              "commodities": 0.20, "cash_anchor": 0.30},
        )
        # Evaluate with 2026 as the target window.
        r = evaluate_composite_spec(
            spec=spec, factor_panel_map=pm,
            price_df=panel["close"], open_df=panel["open"],
            spy_series=spy, qqq_series=qqq, config=hc,
            validation_years=[2026], stress_slices={},
            research_mask=mask,
        )
        m2026 = r.metrics_per_validation_year.get(2026, {})
        sealed_metrics = {
            "window": f"2026-01-01..{panel_max}",
            "cum_ret": float(m2026.get("cum_ret", 0.0)),
            "vs_spy": float(m2026.get("vs_spy", 0.0)),
            "vs_qqq": float(m2026.get("vs_qqq", 0.0)),
            "sharpe": float(m2026.get("sharpe", 0.0)),
            "max_dd": float(m2026.get("max_dd", 0.0)),
            "spy_cum_ret": float(m2026.get("spy_cum_ret", 0.0)),
        }
        # Sealed-pass criteria
        passed = (
            sealed_metrics["vs_spy"] > 0.0
            and abs(sealed_metrics["max_dd"]) <= 0.25
            and sealed_metrics["sharpe"] > 0.0
        )
        sealed_metrics["sealed_pass"] = passed
        results.append({"candidate": cand, "metrics": sealed_metrics,
                        "spec_sha256": _spec_sha256(cand)})

        print(f"\n--- {cand['id']} ({cand['cadence']}) ---")
        print(f"  features: {feats}")
        for k in ("window", "cum_ret", "vs_spy", "vs_qqq", "sharpe", "max_dd"):
            v = sealed_metrics[k]
            print(f"  {k}: {v if isinstance(v,str) else f'{v:+.4f}'}")
        print(f"  SEALED VERDICT: {'PASS' if passed else 'FAIL'}")

    if args.record:
        # A sealed eval is ONE event per split_name (sealed_ledger B1
        # fail_closed_on_split_failure). A multi-candidate batch must be
        # recorded as a SINGLE ledger entry whose result_metrics holds
        # every candidate — NOT one entry per candidate.
        #
        # NOTE (2026-05-15): the first run of this script looped
        # record_eval per candidate; cycle08 recorded, then B1 correctly
        # blocked cycle06. The split is already locked. This corrected
        # single-batch-entry form is retained for reference only — it
        # cannot successfully re-run (B1 locks alternating_regime_holdout_v1).
        print("\n=== Recording to sealed ledger (CONSUMES HOLDOUT) ===")
        batch_metrics = {
            "sealed_event": "cycle06_cycle08_survivors_2026-05-15",
            "candidates": {
                res["candidate"]["id"]: res["metrics"] for res in results
            },
        }
        batch_sha = hashlib.sha256(
            json.dumps(sorted(r["spec_sha256"] for r in results),
                       sort_keys=True).encode()
        ).hexdigest()
        entry = run_sealed_eval_record(
            spec_sha256=batch_sha,
            role="core",
            git_sha=git_sha,
            panel_max_date=str(panel_max),
            result_metrics=batch_metrics,
            split_yaml_path=PROJ / "config" / "temporal_split.yaml",
            extra={"candidate_ids": [r["candidate"]["id"] for r in results],
                   "batch": True},
        )
        print(f"  recorded sealed batch: ledger entry "
              f"{entry.result_metrics_sha256[:12]}")
    else:
        print("\n[compute-only] NOT recorded to ledger. "
              "Re-run with --record to persist (holdout already epistemically seen).")

    out = {
        "evaluation": "sealed_2026_single_shot",
        "panel_max_date": str(panel_max),
        "git_sha": git_sha,
        "recorded": args.record,
        "results": [{"id": r["candidate"]["id"], **r["metrics"]} for r in results],
    }
    out_path = PROJ / "data/audit/sealed_2026_eval.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")
    n_pass = sum(1 for r in results if r["metrics"]["sealed_pass"])
    print(f"VERDICT: {n_pass}/{len(results)} passed sealed 2026 test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
