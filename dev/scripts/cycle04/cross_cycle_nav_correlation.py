"""Cycle #04 cross-cycle NAV correlation post-eval (CRITICAL Tier-1 gate).

The cycle04 evaluator left nav_correlation_vs_existing_pair empty because
cross-cycle reference NAV building was deferred. This script:

1. Takes top-K cycle04 archived trials
2. Builds their NAVs via cap_aware_cross_asset harness (extended panel)
3. Builds RCMv1 + Cand-2 + cycle03-top1 reference NAVs via global_top_n
   harness on the SAME extended panel (stocks-only ones still produce
   stock-only NAVs because their cluster maps exclude ETFs)
4. Computes pooled raw + residual Pearson
5. RE-classifies R41 with the now-populated NAV-correlation data
6. Writes augmented JSON

Output overlays evaluation_summary.json (NOT replaces) — adds
'nav_correlation_vs_existing_pair' + re-derived 'r41_classification'.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
LINEAGE_TAG = "track-c-cycle-2026-05-01-04"

sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "cycle04"))


def main():
    from evaluate_cycle04_top_n import (
        _build_inputs, _load_criteria_yaml,
        _classify_r41, _residual_pair_corr,
        _compute_cross_cycle_correlations,
        _evaluate_one,
    )
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec

    print("[cross_cycle] Loading inputs...")
    cycle_yaml = _load_criteria_yaml()
    panel, all_factors, mask, split_cfg = _build_inputs(cycle_yaml)
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    # Reference NAVs via global_top_n on SAME extended panel
    refs: Dict[str, pd.Series] = {}

    # RCMv1 (4 factors weighted)
    rcm_feats = ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"]
    rcm_w = (0.186, 0.302, 0.395, 0.117)
    s = sum(rcm_w); rcm_w = tuple(w / s for w in rcm_w)
    rcm_panel = {f: all_factors[f] for f in rcm_feats if f in all_factors}
    if len(rcm_panel) == len(rcm_feats):
        cfg_g = HarnessConfig(construction_mode="global_top_n",
                              rebalance_cadence="monthly", top_n=10, horizon_days=21)
        try:
            r = evaluate_composite_spec(
                spec=ResearchCompositeSpec(features=tuple(rcm_feats), weights=rcm_w,
                                            family_counts={"A": 1, "B": 2, "C": 1}),
                factor_panel_map=rcm_panel, price_df=panel["close"],
                open_df=panel["open"], spy_series=spy, qqq_series=qqq,
                config=cfg_g, research_mask=mask)
            refs["rcm_v1"] = r.nav
            print(f"  ✓ RCMv1 NAV built (n={len(r.nav)})")
        except Exception as exc:
            print(f"  ✗ RCMv1 NAV failed: {exc}")

    # Cand-2 (3 factors equal-weight)
    c2_feats = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
    c2_w = (1/3, 1/3, 1/3)
    s = sum(c2_w); c2_w = tuple(w / s for w in c2_w)
    c2_panel = {f: all_factors[f] for f in c2_feats if f in all_factors}
    if len(c2_panel) == len(c2_feats):
        cfg_g = HarnessConfig(construction_mode="global_top_n",
                              rebalance_cadence="monthly", top_n=10, horizon_days=21)
        try:
            r = evaluate_composite_spec(
                spec=ResearchCompositeSpec(features=tuple(c2_feats), weights=c2_w,
                                            family_counts={"E": 1, "F": 1, "D": 1}),
                factor_panel_map=c2_panel, price_df=panel["close"],
                open_df=panel["open"], spy_series=spy, qqq_series=qqq,
                config=cfg_g, research_mask=mask)
            refs["cand_2"] = r.nav
            print(f"  ✓ Cand-2 NAV built (n={len(r.nav)})")
        except Exception as exc:
            print(f"  ✗ Cand-2 NAV failed: {exc}")

    # Cycle03 top-1
    c3_feats = ["rs_vs_spy_126d", "drawup_from_252d_low", "market_vol_ratio"]
    c3_w = (1/3, 1/3, 1/3)
    s = sum(c3_w); c3_w = tuple(w / s for w in c3_w)
    c3_panel = {f: all_factors[f] for f in c3_feats if f in all_factors}
    if len(c3_panel) == len(c3_feats):
        cfg_g = HarnessConfig(construction_mode="global_top_n",
                              rebalance_cadence="monthly", top_n=10, horizon_days=21)
        try:
            r = evaluate_composite_spec(
                spec=ResearchCompositeSpec(features=tuple(c3_feats), weights=c3_w,
                                            family_counts={"E": 1, "B": 1, "C": 1}),
                factor_panel_map=c3_panel, price_df=panel["close"],
                open_df=panel["open"], spy_series=spy, qqq_series=qqq,
                config=cfg_g, research_mask=mask)
            refs["cycle_03_top"] = r.nav
            print(f"  ✓ Cycle03-top NAV built (n={len(r.nav)})")
        except Exception as exc:
            print(f"  ✗ Cycle03-top NAV failed: {exc}")

    # Build cycle04 candidate NAVs and compute correlations
    summary_path = PROJ / "data" / "ml" / "cycle04_evaluation" / LINEAGE_TAG / "evaluation_summary.json"
    summary = json.loads(summary_path.read_text())

    print(f"\n[cross_cycle] Building cycle04 candidate NAVs + correlations...")
    import sqlite3
    con = sqlite3.connect(str(PROJ / "data" / "mining" / "rcm_archive.db"))
    archive_df = pd.read_sql(
        "SELECT trial_id, ic_ir, features_csv, weights_csv, family_counts_json "
        "FROM rcm_trials WHERE lineage_tag = ? "
        "ORDER BY ic_ir DESC LIMIT 10",
        con, params=(LINEAGE_TAG,))
    con.close()

    anchor_features = {
        "cycle_01_top": ["beta_spy_60d", "mom_12_1", "volume_ratio_20d"],
        "cycle_02_top": ["beta_spy_60d", "mom_12_1", "volume_ratio_20d"],
        "cycle_03_top": ["rs_vs_spy_126d", "drawup_from_252d_low", "market_vol_ratio"],
        "rcm_v1": ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"],
        "cand_2": ["ret_5d", "rs_vs_spy_126d", "hl_range"],
    }

    for i, (_, trial_row) in enumerate(archive_df.iterrows(), start=1):
        print(f"  [{i}] {trial_row['trial_id']}")
        ev = _evaluate_one(trial_row, panel, all_factors, mask, cycle_yaml, split_cfg)
        if "error" in ev:
            continue
        cand_nav = ev.pop("_nav_series")
        nc = _compute_cross_cycle_correlations(cand_nav, refs, spy, qqq)
        summary["evaluations"][i-1]["nav_correlation_vs_existing_pair"] = nc
        # Re-classify R41 with populated NAV correlations
        new_r41 = _classify_r41(
            summary["evaluations"][i-1],
            nc,
            anchor_features,
        )
        summary["evaluations"][i-1]["r41_classification_v2_with_nav"] = new_r41

    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[cross_cycle] Updated: {summary_path}")

    # Summary print
    print("\n=== R41 v2 (with NAV correlation) ===")
    tier_v2 = {}
    for ev in summary["evaluations"]:
        r41 = ev.get("r41_classification_v2_with_nav", {})
        tier = r41.get("tier", "?")
        tier_v2[tier] = tier_v2.get(tier, 0) + 1
        nc = ev.get("nav_correlation_vs_existing_pair", {})
        rcm_raw = nc.get("rcm_v1_pooled_pearson_raw")
        cand_raw = nc.get("cand_2_pooled_pearson_raw")
        c3_raw = nc.get("cycle_03_top_pooled_pearson_raw")
        feats = ev.get("features", [])
        print(f"  {ev['trial_id']} {feats}")
        print(f"    raw vs RCMv1={rcm_raw:.3f if rcm_raw else float('nan')}  vs Cand2={cand_raw:.3f if cand_raw else float('nan')}  vs C3={c3_raw:.3f if c3_raw else float('nan')}")
        print(f"    R41 v2 Tier {r41.get('tier')}: {r41.get('reason')}")
    print(f"\nTier distribution v2: {sorted(tier_v2.items())}")


if __name__ == "__main__":
    raise SystemExit(main())
