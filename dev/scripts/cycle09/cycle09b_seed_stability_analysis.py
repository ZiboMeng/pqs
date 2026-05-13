"""cycle09b §5.3 — seed=42 vs seed=123 stability + cross-NAV + G3 check.

After seed=123 replication mining completed (2026-05-13), top-1 trial is
`mom_126d + coskew_60d_spy + atr_compression_20d` (IR_IR +0.612) — 0/3
factor overlap with seed=42 top-1 (`rs_vs_spy_63d + cpi_yoy_pct +
rd_intensity_ttm`, IR_IR +0.773).

This script computes:
  1. seed=42 top-1 NAV vs seed=123 top-1 NAV correlation (within-cycle
     stability: are these two equally-strong winners structurally similar?)
  2. seed=123 top-1 NAV vs 3 yaml-anchored references (RCMv1 / Cand-2 /
     Trial9_v2) — does seed=123 winner pass G3 orthogonality_gate where
     seed=42 winner failed?

Output: data/audit/cycle09b_seed_stability_analysis.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    STOCK_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)

from dev.scripts.cycle09.cycle09b_track_a_eval import _load_panel
from dev.scripts.cycle09.cycle09b_trial1_extended_nav_correlation import (
    _pair_corr,
    _classify_raw,
)


def main() -> int:
    print("[seed-stability] Loading panel + factors...")
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape}, factors={len(factors)} ({time.time()-t0:.1f}s)")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    xa_cfg = HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map, asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )

    # ── seed=42 top-1 (Trial 1) ──
    seed42_feats = ["rs_vs_spy_63d", "cpi_yoy_pct", "rd_intensity_ttm"]
    print(f"\n[seed=42 top-1] {seed42_feats}")
    t0 = time.time()
    r42 = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(seed42_feats), weights=(1/3, 1/3, 1/3),
            family_counts={"A": 1, "P": 1, "N": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in seed42_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=xa_cfg, research_mask=mask,
    )
    print(f"  NAV: n={len(r42.nav)}, last={r42.nav.iloc[-1]:.4f} ({time.time()-t0:.1f}s)")

    # ── seed=123 top-1 ──
    seed123_feats = ["mom_126d", "coskew_60d_spy", "atr_compression_20d"]
    print(f"\n[seed=123 top-1] {seed123_feats}")
    missing = [f for f in seed123_feats if f not in factors]
    if missing:
        print(f"  ✗ missing factors: {missing} — abort")
        return 1
    t0 = time.time()
    r123 = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(seed123_feats), weights=(1/3, 1/3, 1/3),
            family_counts={"A": 1, "I": 2}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in seed123_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=xa_cfg, research_mask=mask,
    )
    print(f"  NAV: n={len(r123.nav)}, last={r123.nav.iloc[-1]:.4f} ({time.time()-t0:.1f}s)")

    # ── 3 yaml anchors (per cycle09b G3 gate) ──
    rcm_feats = ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"]
    rcm_w_raw = (0.186, 0.302, 0.395, 0.117)
    rcm_w = tuple(w/sum(rcm_w_raw) for w in rcm_w_raw)
    g_cfg = HarnessConfig(
        construction_mode="global_top_n",
        rebalance_cadence="monthly",
        top_n=10, horizon_days=21,
    )
    print(f"\n[RCMv1] {rcm_feats}")
    t0 = time.time()
    r_rcm = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(rcm_feats), weights=rcm_w,
            family_counts={"A": 1, "B": 1, "C": 1, "F": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in rcm_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=g_cfg, research_mask=mask,
    )
    print(f"  NAV: n={len(r_rcm.nav)}, last={r_rcm.nav.iloc[-1]:.4f} ({time.time()-t0:.1f}s)")

    cand2_feats = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
    print(f"\n[Cand-2] {cand2_feats}")
    t0 = time.time()
    r_c2 = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(cand2_feats), weights=(1/3, 1/3, 1/3),
            family_counts={"D": 1, "E": 1, "F": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in cand2_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=g_cfg, research_mask=mask,
    )
    print(f"  NAV: n={len(r_c2.nav)}, last={r_c2.nav.iloc[-1]:.4f} ({time.time()-t0:.1f}s)")

    t9_feats = ["beta_spy_60d", "max_dd_126d", "ret_1d"]
    print(f"\n[Trial 9 v2] {t9_feats}")
    cap_stocks_cfg = HarnessConfig(
        construction_mode="cap_aware",
        rebalance_cadence="monthly",
        top_n=10, horizon_days=21,
        cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=STOCK_RISK_CLUSTER_MAP,
    )
    t0 = time.time()
    r_t9 = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(t9_feats), weights=(1/3, 1/3, 1/3),
            family_counts={"A": 1, "B": 1, "F": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in t9_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=cap_stocks_cfg, research_mask=mask,
    )
    print(f"  NAV: n={len(r_t9.nav)}, last={r_t9.nav.iloc[-1]:.4f} ({time.time()-t0:.1f}s)")

    # ── Within-cycle stability: seed=42 vs seed=123 ──
    print("\n[Within-cycle stability] seed=42 vs seed=123 top-1 NAV correlation...")
    stability = _pair_corr(r42.nav, r123.nav, spy, qqq, "seed42_vs_seed123")
    print(f"  raw={stability['pooled_pearson_raw']:.3f}  "
          f"res_spy={stability['pooled_pearson_residual_vs_spy']:.3f}  "
          f"res_qqq={stability['pooled_pearson_residual_vs_qqq']:.3f}  "
          f"n={stability['n_overlap_days']}")

    # ── seed=123 top-1 G3 check (raw < 0.70 AND res < 0.50, top_k≥1) ──
    print("\n[G3 check on seed=123 top-1] vs 3 yaml anchors...")
    g3_pairs = []
    for name, anchor_nav in [
        ("rcm_v1", r_rcm.nav),
        ("cand_2", r_c2.nav),
        ("trial_9_v2", r_t9.nav),
    ]:
        pc = _pair_corr(r123.nav, anchor_nav, spy, qqq, name)
        g3_pairs.append(pc)
        if pc.get("pooled_pearson_raw") is not None:
            raw_ok = pc["pooled_pearson_raw"] < 0.70
            res_ok = (pc["pooled_pearson_residual_vs_spy"] < 0.50 and
                      pc["pooled_pearson_residual_vs_qqq"] < 0.50)
            both_ok = raw_ok and res_ok
            tier = _classify_raw(pc["pooled_pearson_raw"])
            print(f"  seed=123 top-1 vs {name:12s}: raw={pc['pooled_pearson_raw']:.3f}  "
                  f"res_spy={pc['pooled_pearson_residual_vs_spy']:.3f}  "
                  f"res_qqq={pc['pooled_pearson_residual_vs_qqq']:.3f}  "
                  f"G3 raw<0.70={raw_ok}  res<0.50={res_ok}  both={both_ok}  tier={tier}")

    # G3 verdict for seed=123
    g3_pass_count = sum(
        1 for p in g3_pairs
        if p.get("pooled_pearson_raw") is not None
        and p["pooled_pearson_raw"] < 0.70
        and p["pooled_pearson_residual_vs_spy"] < 0.50
        and p["pooled_pearson_residual_vs_qqq"] < 0.50
    )
    g3_required_pass = 1
    g3_seed123_verdict = "PASS" if g3_pass_count >= g3_required_pass else "FAIL"
    print(f"\n[G3 verdict on seed=123 top-1] {g3_pass_count}/{len(g3_pairs)} anchors clear both G3 sub-gates")
    print(f"  Required: {g3_required_pass}; result: {g3_seed123_verdict}")

    # ── Result write ──
    out = {
        "cycle": "track-c-cycle-2026-05-12-09b",
        "audit_section": "§5.3 seed stability + cross-seed NAV + G3 on seed=123",
        "seed42_top1": {
            "trial_id": "5a99868072e6",
            "features": seed42_feats,
            "ic_ir": 0.773,
            "objective": 1.1219,
        },
        "seed123_top1": {
            "features": seed123_feats,
            "ic_ir": 0.612,
            "objective": 1.1512,
            "from_mining_log": "data/audit/cycle09b_seed123_mining.log line 'Top-5 trials: #1'",
        },
        "factor_overlap_seed42_vs_seed123": {
            "shared_factors": sorted(set(seed42_feats) & set(seed123_feats)),
            "n_shared": len(set(seed42_feats) & set(seed123_feats)),
            "total_factors_per_seed": 3,
            "overlap_fraction": len(set(seed42_feats) & set(seed123_feats)) / 3,
        },
        "within_cycle_stability_pair_corr": stability,
        "seed123_top1_g3_check": {
            "pairs": g3_pairs,
            "anchors_clearing_both_g3": g3_pass_count,
            "required_top_k_under_threshold": g3_required_pass,
            "verdict": g3_seed123_verdict,
        },
        "strategic_finding": {
            "seed_stability": "UNSTABLE — seed=42 and seed=123 produce different top-1 specs with 0/3 factor overlap",
            "implication": "cycle09b at 162-factor + family_first sampler does not converge on single best spec; multiple equally-strong local optima exist",
            "g3_outcome": f"seed=123 top-1 G3 verdict: {g3_seed123_verdict}",
            "g3_seed42_outcome": "seed=42 top-1 (Trial 1) G3 verdict: FAIL (0/3 anchors clear)",
        },
    }
    OUT_PATH = PROJ / "data" / "audit" / "cycle09b_seed_stability_analysis.json"
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[seed-stability] Output: {OUT_PATH.relative_to(PROJ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
