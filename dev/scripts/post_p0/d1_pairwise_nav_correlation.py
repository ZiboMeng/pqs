"""D1 post-P0.b.4: pairwise NAV correlation for 5 NEW Track A PASS candidates.

After R1 retroactive re-eval (post-P0.a QQQ demote + P0.b.4 data repair),
5 trials newly PASS Track A 18-gate. Before any fleet-init, must
quantify pairwise sibling-by-NAV across these 5.

5 candidates (all from track-c-cycle-2026-05-{06,07,08}-01 cap_aware_cross_asset):
  - cycle06 31af04cf2ff9 weekly: drawup+trend_tstat+ret_2d
  - cycle07a f133a18d1495 monthly: drawup+rank_mom_chg+ret_1d
  - cycle07a 1e771580f486 monthly: drawup+mom_63d+ret_1d (CLAUDE.md NAV Red vs RCMv1)
  - cycle08 8ac6bccbeed1 weekly: maxdd_126d+mom_252d+reversal_21d
  - cycle08 3f40e3f4ed1a monthly: maxdd_126d+xsection_rank_63d+ret_5d

Output: 5x5 raw Pearson + residual_vs_spy + residual_vs_qqq matrix.
Verdict: any pair raw >= 0.85 → sibling-by-NAV.
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
    ("cycle06_31af04cf2ff9", "weekly",
     ["drawup_from_252d_low", "trend_tstat_20d", "ret_2d"]),
    ("cycle07a_f133a18d1495", "monthly",
     ["drawup_from_252d_low", "rank_momentum_change", "ret_1d"]),
    ("cycle07a_1e771580f486", "monthly",
     ["drawup_from_252d_low", "mom_63d", "ret_1d"]),
    ("cycle08_8ac6bccbeed1", "weekly",
     ["max_dd_126d", "mom_252d", "reversal_21d"]),
    ("cycle08_3f40e3f4ed1a", "monthly",
     ["max_dd_126d", "xsection_rank_63d", "ret_5d"]),
]


def _residual_corr(a_ret: pd.Series, b_ret: pd.Series, bench_ret: pd.Series):
    """Pearson of residuals after regressing each return on bench return."""
    aligned = pd.concat([a_ret, b_ret, bench_ret], axis=1).dropna()
    if len(aligned) < 60:
        return None
    a, b, bench = aligned.iloc[:, 0], aligned.iloc[:, 1], aligned.iloc[:, 2]
    var_bench = bench.var()
    if var_bench <= 0:
        return None
    beta_a = (a * bench).mean() / (bench ** 2).mean() if (bench ** 2).mean() > 0 else 0.0
    beta_b = (b * bench).mean() / (bench ** 2).mean() if (bench ** 2).mean() > 0 else 0.0
    res_a = a - beta_a * bench
    res_b = b - beta_b * bench
    return float(res_a.corr(res_b))


def main():
    from cycle06_track_a_eval import _load_panel
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import (
        ASSET_CLASS_BY_CLUSTER, make_unified_cluster_map,
    )

    print("Loading panel + factors (selector role)...")
    panel, factors, mask, _ = _load_panel()
    print(f"  panel: {panel['close'].shape}")

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
    for cand_id, cadence, feats in CANDIDATES:
        panel_map = {f: factors[f] for f in feats if f in factors}
        if len(panel_map) != len(feats):
            missing = set(feats) - set(panel_map.keys())
            print(f"  ✗ {cand_id}: missing {missing}")
            continue
        spec = ResearchCompositeSpec(
            features=tuple(feats), weights=(1/3, 1/3, 1/3),
            family_counts={"X": 3}, holding_freq=cadence,
        )
        hc = HarnessConfig(
            rebalance_cadence=cadence,
            construction_mode="cap_aware_cross_asset",
            top_n=10, cluster_cap=0.20, max_single_weight=0.10,
            cluster_map=cluster_map, asset_class_map=asset_class_map,
            asset_class_caps={
                "equities": 0.70, "bonds": 0.40,
                "commodities": 0.20, "cash_anchor": 0.30,
            },
        )
        r = evaluate_composite_spec(
            spec=spec, factor_panel_map=panel_map,
            price_df=panel["close"], open_df=panel["open"],
            spy_series=spy, qqq_series=qqq, config=hc,
            research_mask=mask,
        )
        navs[cand_id] = r.nav.pct_change()
        print(f"  ✓ {cand_id} NAV built (n={len(r.nav)})")

    ids = list(navs.keys())
    n = len(ids)

    # Pairwise raw Pearson
    raw_mat = np.zeros((n, n))
    res_spy_mat = np.zeros((n, n))
    res_qqq_mat = np.zeros((n, n))
    for i, a_id in enumerate(ids):
        for j, b_id in enumerate(ids):
            if i == j:
                raw_mat[i, j] = 1.0
                res_spy_mat[i, j] = 1.0
                res_qqq_mat[i, j] = 1.0
                continue
            a_ret = navs[a_id]
            b_ret = navs[b_id]
            aligned = pd.concat([a_ret, b_ret], axis=1).dropna()
            if len(aligned) >= 60:
                raw_mat[i, j] = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
                rs = _residual_corr(a_ret, b_ret, spy_ret)
                rq = _residual_corr(a_ret, b_ret, qqq_ret)
                res_spy_mat[i, j] = rs if rs is not None else np.nan
                res_qqq_mat[i, j] = rq if rq is not None else np.nan

    print("\n=== RAW DAILY-RETURN PEARSON ===")
    print(f"{'':<25}" + "  ".join(f"{x[7:15]:>8}" for x in ids))
    for i, a in enumerate(ids):
        row = f"{a:<25}" + "  ".join(f"{raw_mat[i, j]:>8.3f}" for j in range(n))
        print(row)

    print("\n=== RESIDUAL vs SPY ===")
    print(f"{'':<25}" + "  ".join(f"{x[7:15]:>8}" for x in ids))
    for i, a in enumerate(ids):
        row = f"{a:<25}" + "  ".join(f"{res_spy_mat[i, j]:>8.3f}" for j in range(n))
        print(row)

    print("\n=== RESIDUAL vs QQQ ===")
    print(f"{'':<25}" + "  ".join(f"{x[7:15]:>8}" for x in ids))
    for i, a in enumerate(ids):
        row = f"{a:<25}" + "  ".join(f"{res_qqq_mat[i, j]:>8.3f}" for j in range(n))
        print(row)

    # Verdict
    print("\n=== VERDICT ===")
    sibling_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            raw = raw_mat[i, j]
            if raw >= 0.85:
                sibling_pairs.append((ids[i], ids[j], raw, res_spy_mat[i, j]))
    if sibling_pairs:
        print(f"  {len(sibling_pairs)} sibling pairs (raw >= 0.85):")
        for a, b, r, rs in sibling_pairs:
            print(f"    {a} <-> {b}: raw={r:.3f}  res_spy={rs:.3f}")
    else:
        print("  No sibling pairs found (all raw < 0.85)")

    # Maximum pairwise raw per candidate (for fleet selection)
    print("\n=== MAX PAIRWISE RAW per CANDIDATE ===")
    for i, a in enumerate(ids):
        others = [raw_mat[i, j] for j in range(n) if j != i]
        max_raw = max(others) if others else 0
        print(f"  {a}: max_raw_pair = {max_raw:.3f}")

    # Save
    out = {
        "candidates": [{"id": x, "cadence": c, "features": f} for x, c, f in CANDIDATES],
        "raw_matrix": raw_mat.tolist(),
        "residual_vs_spy_matrix": res_spy_mat.tolist(),
        "residual_vs_qqq_matrix": res_qqq_mat.tolist(),
        "sibling_pairs_raw_0_85": [
            {"a": a, "b": b, "raw": r, "res_spy": rs}
            for a, b, r, rs in sibling_pairs
        ],
    }
    out_path = PROJ / "data/audit/d1_pairwise_nav_correlation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
