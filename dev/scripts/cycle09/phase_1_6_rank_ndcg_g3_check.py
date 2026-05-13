"""Phase 1.6 rank:ndcg config G3 orthogonality check vs cycle09b yaml anchors.

After Phase 1.6 sweep found rank:ndcg achieves +14.45% per-yr vs SPY
(94% of cycle09b linear baseline +15.31%), the next gate is the same
yaml-ratified G3 orthogonality test that cycle09b Trial 1 failed:
  raw < 0.70 AND residual < 0.50 vs 3 yaml anchors
  required_top_k_under_threshold: 1

If rank:ndcg PASSES G3 where Trial 1 failed → ML produces a structurally
distinct candidate. Worth forward-init consideration.

Output: data/audit/phase_1_6_rank_ndcg_g3_check.json
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
    # Load rank:ndcg NAV (from Phase 1.6 sweep output)
    ndcg_nav_path = PROJ / "data/ml/xgb_alpha_phase_1_6/rank_ndcg/nav.csv"
    ndcg_nav = pd.read_csv(ndcg_nav_path, parse_dates=["date"]).set_index("date")["nav"]
    print(f"[Phase 1.6 G3 check] rank:ndcg NAV: n={len(ndcg_nav)}, "
          f"last={ndcg_nav.iloc[-1]:.4f}")

    # Build the 3 yaml-anchored references (same as cycle09b §5.1)
    print("\n[Loading panel + factors...]")
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape}, factors={len(factors)} ({time.time()-t0:.1f}s)")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    g_cfg = HarnessConfig(
        construction_mode="global_top_n",
        rebalance_cadence="monthly",
        top_n=10, horizon_days=21,
    )
    cap_stocks_cfg = HarnessConfig(
        construction_mode="cap_aware",
        rebalance_cadence="monthly",
        top_n=10, horizon_days=21,
        cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=STOCK_RISK_CLUSTER_MAP,
    )

    # RCMv1
    rcm_feats = ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"]
    rcm_w_raw = (0.186, 0.302, 0.395, 0.117)
    rcm_w = tuple(w/sum(rcm_w_raw) for w in rcm_w_raw)
    print("[Build RCMv1 NAV...]")
    r_rcm = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(rcm_feats), weights=rcm_w,
            family_counts={"A": 1, "B": 1, "C": 1, "F": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in rcm_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=g_cfg, research_mask=mask,
    )
    rcm_nav = r_rcm.nav

    # Cand-2
    cand2_feats = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
    print("[Build Cand-2 NAV...]")
    r_c2 = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(cand2_feats), weights=(1/3, 1/3, 1/3),
            family_counts={"D": 1, "E": 1, "F": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in cand2_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=g_cfg, research_mask=mask,
    )
    c2_nav = r_c2.nav

    # Trial 9 v2
    t9_feats = ["beta_spy_60d", "max_dd_126d", "ret_1d"]
    print("[Build Trial 9 v2 NAV...]")
    r_t9 = evaluate_composite_spec(
        spec=ResearchCompositeSpec(
            features=tuple(t9_feats), weights=(1/3, 1/3, 1/3),
            family_counts={"A": 1, "B": 1, "F": 1}, holding_freq="monthly",
        ),
        factor_panel_map={f: factors[f] for f in t9_feats},
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=cap_stocks_cfg, research_mask=mask,
    )
    t9_nav = r_t9.nav

    # G3 check on rank:ndcg vs 3 yaml anchors
    print("\n[G3 orthogonality check on rank:ndcg config]")
    print("  Per cycle09b yaml line 262-271:")
    print("    raw < 0.70 AND residual < 0.50, required_top_k_under_threshold: 1")
    print()

    pair_results: List[Dict[str, Any]] = []
    for name, anchor_nav in [("rcm_v1", rcm_nav), ("cand_2", c2_nav), ("trial_9_v2", t9_nav)]:
        pc = _pair_corr(ndcg_nav, anchor_nav, spy, qqq, name)
        pair_results.append(pc)
        if pc.get("pooled_pearson_raw") is not None:
            raw_ok = pc["pooled_pearson_raw"] < 0.70
            res_ok = (pc["pooled_pearson_residual_vs_spy"] < 0.50 and
                      pc["pooled_pearson_residual_vs_qqq"] < 0.50)
            both = raw_ok and res_ok
            tier = _classify_raw(pc["pooled_pearson_raw"])
            print(f"  rank:ndcg vs {name:12s}: raw={pc['pooled_pearson_raw']:.3f}  "
                  f"res_spy={pc['pooled_pearson_residual_vs_spy']:.3f}  "
                  f"res_qqq={pc['pooled_pearson_residual_vs_qqq']:.3f}  "
                  f"G3 raw<0.70={raw_ok}  res<0.50={res_ok}  both={both}  tier={tier}")

    g3_pass_count = sum(
        1 for p in pair_results
        if p.get("pooled_pearson_raw") is not None
        and p["pooled_pearson_raw"] < 0.70
        and p["pooled_pearson_residual_vs_spy"] < 0.50
        and p["pooled_pearson_residual_vs_qqq"] < 0.50
    )
    g3_verdict = "PASS" if g3_pass_count >= 1 else "FAIL"
    print(f"\n[G3 verdict] {g3_pass_count}/3 anchors clear both gates → {g3_verdict}")

    # Compare with cycle09b Trial 1 (which failed G3 0/3)
    print("\nComparison vs cycle09b Trial 1 (linear baseline candidate):")
    print(f"  Trial 1: 0/3 anchors clear G3 → REJECTED")
    print(f"  rank:ndcg: {g3_pass_count}/3 → {g3_verdict}")

    out = {
        "candidate": "ML Phase 1.6 rank:ndcg config",
        "ndcg_avg_per_yr_vs_spy": 0.1445,
        "cycle09b_linear_baseline": 0.1531,
        "pct_of_baseline": round(0.1445 / 0.1531, 3),
        "pair_correlations": pair_results,
        "g3_anchors_passing": g3_pass_count,
        "g3_required": 1,
        "g3_verdict": g3_verdict,
        "comparison_to_trial1": {
            "trial1_g3_anchors_passing": 0,
            "trial1_g3_verdict": "FAIL",
        },
    }
    out_path = PROJ / "data/audit/phase_1_6_rank_ndcg_g3_check.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[Saved] {out_path.relative_to(PROJ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
