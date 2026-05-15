"""Cycle12 top-2 vs cycle08 D1 anchor pair NAV correlation.

D1+D2 surfaced cycle08 8ac6bccbeed1 + 3f40e3f4ed1a as PQS first
fleet-eligible pair (raw 0.742). Cycle12 top-1 + top-2 PASS Track A —
must NOT be sibling-by-NAV of cycle08 anchors.

Reject if any cycle12 candidate raw >= 0.85 vs either cycle08 anchor.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "cycle06"))

CANDIDATES = [
    ("cycle12_top1_3dfd918b5d86", "monthly",
     ["max_dd_126d", "golden_cross_score", "mom_126d"]),
    ("cycle12_top2_0fa7336cea3a", "monthly",
     ["drawup_from_252d_low", "down_vol_ratio_20d", "cokurt_60d_spy"]),
    ("cycle08_8ac6bccbeed1", "weekly",
     ["max_dd_126d", "mom_252d", "reversal_21d"]),
    ("cycle08_3f40e3f4ed1a", "monthly",
     ["max_dd_126d", "xsection_rank_63d", "ret_5d"]),
]


def _residual_corr(a_ret, b_ret, bench_ret):
    aligned = pd.concat([a_ret, b_ret, bench_ret], axis=1).dropna()
    if len(aligned) < 60:
        return None
    a, b, bench = aligned.iloc[:, 0], aligned.iloc[:, 1], aligned.iloc[:, 2]
    if bench.var() <= 0:
        return None
    beta_a = (a * bench).mean() / (bench ** 2).mean()
    beta_b = (b * bench).mean() / (bench ** 2).mean()
    return float((a - beta_a * bench).corr(b - beta_b * bench))


def main():
    from cycle06_track_a_eval import _load_panel
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER, make_unified_cluster_map,
    )

    panel, factors, mask, _ = _load_panel()
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    spy_ret = spy.pct_change()
    qqq_ret = qqq.pct_change()

    navs = {}
    for cid, cad, feats in CANDIDATES:
        panel_map = {f: factors[f] for f in feats if f in factors}
        if len(panel_map) != len(feats):
            print(f"  ✗ {cid}: missing {set(feats)-set(panel_map.keys())}")
            continue
        spec = ResearchCompositeSpec(
            features=tuple(feats), weights=(1/3, 1/3, 1/3),
            family_counts={"X": 3}, holding_freq=cad,
        )
        hc = HarnessConfig(
            rebalance_cadence=cad, construction_mode="cap_aware_cross_asset",
            top_n=10, cluster_cap=0.20, max_single_weight=0.10,
            cluster_map=cluster_map, asset_class_map=asset_class_map,
            asset_class_caps={"equities":0.70,"bonds":0.40,"commodities":0.20,"cash_anchor":0.30},
        )
        r = evaluate_composite_spec(
            spec=spec, factor_panel_map=panel_map,
            price_df=panel["close"], open_df=panel["open"],
            spy_series=spy, qqq_series=qqq, config=hc, research_mask=mask,
        )
        navs[cid] = r.nav.pct_change()
        print(f"  ✓ {cid} NAV built (n={len(r.nav)})")

    ids = list(navs.keys())
    n = len(ids)

    print(f"\n=== RAW NAV PEARSON (cycle12 top-2 vs cycle08 anchors) ===")
    print(f"{'':<32}" + "  ".join(f"{x[-13:]:>13}" for x in ids))
    raw_mat = np.zeros((n, n))
    res_spy_mat = np.zeros((n, n))
    for i, a in enumerate(ids):
        for j, b in enumerate(ids):
            if i == j:
                raw_mat[i,j] = 1.0
                res_spy_mat[i,j] = 1.0
                continue
            aligned = pd.concat([navs[a], navs[b]], axis=1).dropna()
            if len(aligned) >= 60:
                raw_mat[i,j] = float(aligned.iloc[:,0].corr(aligned.iloc[:,1]))
                rs = _residual_corr(navs[a], navs[b], spy_ret)
                res_spy_mat[i,j] = rs if rs is not None else np.nan
    for i, a in enumerate(ids):
        print(f"{a:<32}" + "  ".join(f"{raw_mat[i,j]:>13.3f}" for j in range(n)))

    print(f"\n=== VERDICT (cycle12 top-2 must be non-sibling vs cycle08 pair) ===")
    cycle12_top1_idx = 0
    cycle12_top2_idx = 1
    cycle08_8ac_idx = 2
    cycle08_3f4_idx = 3
    for c12_idx, c12_name in [(0, "top1_3dfd918"), (1, "top2_0fa7336")]:
        max_vs_c08 = max(raw_mat[c12_idx][cycle08_8ac_idx], raw_mat[c12_idx][cycle08_3f4_idx])
        verdict = "NON-SIBLING ✓" if max_vs_c08 < 0.85 else "SIBLING REJECT"
        print(f"  {c12_name}: max_raw vs cycle08_pair = {max_vs_c08:.3f} → {verdict}")

    # cycle12 internal pair
    if n >= 2:
        c12_pair_raw = raw_mat[0][1]
        c12_pair_res = res_spy_mat[0][1]
        v = "non-sibling" if c12_pair_raw < 0.85 else "sibling"
        print(f"  cycle12_top1 <-> top2 internal: raw={c12_pair_raw:.3f} res_spy={c12_pair_res:.3f} → {v}")

    out = {
        "candidates": [{"id": x, "cadence": c, "features": f} for x, c, f in CANDIDATES],
        "raw_matrix": raw_mat.tolist(),
        "residual_vs_spy_matrix": res_spy_mat.tolist(),
    }
    (PROJ / "data/audit/cycle12_nav_correlation_vs_d1_anchors.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
