"""Trial 3 (cycle07a 1e771580f486) vs RCMv1 / Cand-2 / Trial 9 NAV correlation.

Pre-forward-init gate per x.txt locked spec (2026-05-07).
Trial 3 = drawup_from_252d_low + mom_63d + ret_1d, equal-weight, monthly,
cap_aware (cluster_cap=0.20, max_single=0.10, top_n=10, horizon=21d).

Anchors:
  - RCMv1: beta_spy_60d + drawup_from_252d_low + days_since_52w_high
           + amihud_20d, weights (0.186, 0.302, 0.395, 0.117); global_top_n
  - Cand-2: ret_5d + rs_vs_spy_126d + hl_range, equal-weight 1/3; global_top_n
  - Trial 9: beta_spy_60d + max_dd_126d + ret_1d, equal-weight 1/3;
             cap_aware (cluster_cap=0.20, max_single=0.10)

Each anchor uses its OWN frozen construction protocol (mirrors realized
fleet behavior); Trial 3 uses cycle07a-inherited cap_aware (its eventual
forward construction).

Panel: cycle07a yaml's selector partition (train + validation, 2009-2024).
This matches the panel Trial 3's mining + Track A acceptance ran on; gives
~16y of returns for stable pooled Pearson.

Output: data/audit/cycle07a_trial3_nav_correlation.json + stdout verdict.

Verdict (locked 2026-05-07 in x.txt):
  Green:  all 3 raw < 0.80 AND all residuals < 0.45
  Yellow: at least one raw in [0.80, 0.85) AND all raw < 0.85
          AND all residuals < 0.50
  Red:    any raw >= 0.85 OR any residual >= 0.50
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

PROJ = Path("/home/zibo/Documents/projects/pqs")
LINEAGE_TAG = "track-c-cycle-2026-05-07-01"
TRIAL3_ID = "1e771580f486"

sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "dev" / "scripts" / "cycle04"))


def _residual_pair_corr(a: pd.Series, b: pd.Series, bench: pd.Series) -> float:
    df = pd.DataFrame({"a": a, "b": b, "bench": bench}).dropna()
    if len(df) < 5:
        return float("nan")
    bv = df["bench"].var()
    if not np.isfinite(bv) or bv < 1e-12:
        return float("nan")
    beta_a = df.cov().loc["a", "bench"] / bv
    beta_b = df.cov().loc["b", "bench"] / bv
    res_a = df["a"] - beta_a * df["bench"]
    res_b = df["b"] - beta_b * df["bench"]
    if res_a.std() < 1e-12 or res_b.std() < 1e-12:
        return float("nan")
    return float(res_a.corr(res_b))


def _pair_corr(
    cand_nav: pd.Series,
    ref_nav: pd.Series,
    spy_close: pd.Series,
    qqq_close: pd.Series,
    name: str,
) -> Dict[str, Any]:
    cand_ret = cand_nav.pct_change().dropna()
    ref_ret = ref_nav.pct_change().dropna()
    spy_ret = spy_close.pct_change().dropna()
    qqq_ret = qqq_close.pct_change().dropna()
    common = cand_ret.index.intersection(ref_ret.index).intersection(spy_ret.index).intersection(qqq_ret.index)
    if len(common) < 60:
        return {
            "anchor": name,
            "n_overlap_days": int(len(common)),
            "pooled_pearson_raw": None,
            "pooled_pearson_residual_vs_spy": None,
            "pooled_pearson_residual_vs_qqq": None,
            "note": "n_overlap < 60 → insufficient",
        }
    a = cand_ret.reindex(common)
    b = ref_ret.reindex(common)
    spy_c = spy_ret.reindex(common)
    qqq_c = qqq_ret.reindex(common)
    return {
        "anchor": name,
        "n_overlap_days": int(len(common)),
        "pooled_pearson_raw": float(a.corr(b)),
        "pooled_pearson_residual_vs_spy": _residual_pair_corr(a, b, spy_c),
        "pooled_pearson_residual_vs_qqq": _residual_pair_corr(a, b, qqq_c),
    }


def _verdict(pair_results: list[dict]) -> Dict[str, Any]:
    raws = [p.get("pooled_pearson_raw") for p in pair_results if p.get("pooled_pearson_raw") is not None]
    res_spys = [p.get("pooled_pearson_residual_vs_spy") for p in pair_results if p.get("pooled_pearson_residual_vs_spy") is not None]
    res_qqqs = [p.get("pooled_pearson_residual_vs_qqq") for p in pair_results if p.get("pooled_pearson_residual_vs_qqq") is not None]

    if not raws or not res_spys:
        return {"tier": "INSUFFICIENT", "reason": "missing pair correlations"}

    max_raw = max(raws)
    max_res = max(max(res_spys), max(res_qqqs) if res_qqqs else 0)

    # Red: any raw >= 0.85 OR any residual >= 0.50
    if any(r >= 0.85 for r in raws):
        red_pairs = [p["anchor"] for p in pair_results if (p.get("pooled_pearson_raw") or 0) >= 0.85]
        return {"tier": "RED", "reason": f"raw >= 0.85 violation in pairs: {red_pairs}", "max_raw": max_raw, "max_residual": max_res}
    if any(r >= 0.50 for r in res_spys + res_qqqs):
        red_pairs = [p["anchor"] for p in pair_results if (p.get("pooled_pearson_residual_vs_spy") or 0) >= 0.50 or (p.get("pooled_pearson_residual_vs_qqq") or 0) >= 0.50]
        return {"tier": "RED", "reason": f"residual >= 0.50 violation in pairs: {red_pairs}", "max_raw": max_raw, "max_residual": max_res}

    # Green: all raw < 0.80 AND all residual < 0.45
    if max_raw < 0.80 and max_res < 0.45:
        return {"tier": "GREEN", "reason": "all raw < 0.80 and all residuals < 0.45", "max_raw": max_raw, "max_residual": max_res}

    # Yellow: 0.80 <= max_raw < 0.85 AND max_res < 0.50
    if 0.80 <= max_raw < 0.85 and max_res < 0.50:
        return {"tier": "YELLOW", "reason": "max raw in [0.80, 0.85) and max residual < 0.50", "max_raw": max_raw, "max_residual": max_res}

    # Edge case: residual in [0.45, 0.50) but raw < 0.80
    if max_raw < 0.80 and 0.45 <= max_res < 0.50:
        return {"tier": "YELLOW", "reason": "max residual in [0.45, 0.50) (raw < 0.80)", "max_raw": max_raw, "max_residual": max_res}

    return {"tier": "RED", "reason": f"unexpected combination: max_raw={max_raw:.3f}, max_residual={max_res:.3f}", "max_raw": max_raw, "max_residual": max_res}


def main() -> int:
    from evaluate_cycle04_top_n import _build_inputs, _load_criteria_yaml
    from core.mining.research_miner import ResearchCompositeSpec
    from core.research.harness import HarnessConfig, evaluate_composite_spec
    from core.research.risk_cluster_map import STOCK_RISK_CLUSTER_MAP

    print("[trial3_nav_corr] Loading panel via cycle07a yaml...")
    cycle07a_yaml_path = PROJ / "data" / "research_candidates" / f"{LINEAGE_TAG}_promotion_criteria.yaml"
    if not cycle07a_yaml_path.exists():
        print(f"  ✗ cycle07a yaml not found: {cycle07a_yaml_path}")
        return 1

    import yaml
    cycle_yaml = yaml.safe_load(cycle07a_yaml_path.read_text())
    panel, all_factors, mask, split_cfg = _build_inputs(cycle_yaml)
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    print(f"  panel loaded: {panel['close'].shape}, factors={len(all_factors)}")

    navs: Dict[str, pd.Series] = {}

    # ─── Trial 3 (cycle07a, cap_aware) ───
    t3_feats = ["drawup_from_252d_low", "mom_63d", "ret_1d"]
    t3_w = (1 / 3, 1 / 3, 1 / 3)
    t3_panel = {f: all_factors[f] for f in t3_feats if f in all_factors}
    if len(t3_panel) != len(t3_feats):
        missing = [f for f in t3_feats if f not in all_factors]
        print(f"  ✗ Trial 3 missing factors: {missing}")
        return 1
    cfg_cap = HarnessConfig(
        construction_mode="cap_aware",
        rebalance_cadence="monthly",
        top_n=10,
        horizon_days=21,
        cluster_cap=0.20,
        max_single_weight=0.10,
        cluster_map=STOCK_RISK_CLUSTER_MAP,
    )
    print("[trial3_nav_corr] Building Trial 3 NAV (cap_aware, monthly, top10, h=21)...")
    r = evaluate_composite_spec(
        spec=ResearchCompositeSpec(features=tuple(t3_feats), weights=t3_w,
                                   family_counts={"A": 0, "B": 1, "C": 0, "D": 1, "E": 0, "F": 1}),
        factor_panel_map=t3_panel, price_df=panel["close"],
        open_df=panel["open"], spy_series=spy, qqq_series=qqq,
        config=cfg_cap, research_mask=mask)
    navs["trial_3"] = r.nav
    print(f"  ✓ Trial 3 NAV: n={len(r.nav)}, last={r.nav.iloc[-1]:.4f}")

    # ─── RCMv1 (global_top_n, monthly) ───
    rcm_feats = ["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"]
    rcm_w_raw = (0.186, 0.302, 0.395, 0.117)
    s = sum(rcm_w_raw)
    rcm_w = tuple(w / s for w in rcm_w_raw)
    rcm_panel = {f: all_factors[f] for f in rcm_feats if f in all_factors}
    if len(rcm_panel) != len(rcm_feats):
        print(f"  ✗ RCMv1 missing factors")
        return 1
    cfg_g = HarnessConfig(
        construction_mode="global_top_n",
        rebalance_cadence="monthly",
        top_n=10,
        horizon_days=21,
    )
    print("[trial3_nav_corr] Building RCMv1 NAV (global_top_n, monthly, top10, h=21)...")
    r = evaluate_composite_spec(
        spec=ResearchCompositeSpec(features=tuple(rcm_feats), weights=rcm_w,
                                   family_counts={"A": 1, "B": 1, "C": 1, "D": 0, "E": 0, "F": 1}),
        factor_panel_map=rcm_panel, price_df=panel["close"],
        open_df=panel["open"], spy_series=spy, qqq_series=qqq,
        config=cfg_g, research_mask=mask)
    navs["rcm_v1"] = r.nav
    print(f"  ✓ RCMv1 NAV: n={len(r.nav)}, last={r.nav.iloc[-1]:.4f}")

    # ─── Cand-2 (global_top_n, monthly) ───
    c2_feats = ["ret_5d", "rs_vs_spy_126d", "hl_range"]
    c2_w = (1 / 3, 1 / 3, 1 / 3)
    c2_panel = {f: all_factors[f] for f in c2_feats if f in all_factors}
    if len(c2_panel) != len(c2_feats):
        print(f"  ✗ Cand-2 missing factors")
        return 1
    print("[trial3_nav_corr] Building Cand-2 NAV (global_top_n, monthly, top10, h=21)...")
    r = evaluate_composite_spec(
        spec=ResearchCompositeSpec(features=tuple(c2_feats), weights=c2_w,
                                   family_counts={"A": 0, "B": 0, "C": 0, "D": 1, "E": 1, "F": 1}),
        factor_panel_map=c2_panel, price_df=panel["close"],
        open_df=panel["open"], spy_series=spy, qqq_series=qqq,
        config=cfg_g, research_mask=mask)
    navs["cand_2"] = r.nav
    print(f"  ✓ Cand-2 NAV: n={len(r.nav)}, last={r.nav.iloc[-1]:.4f}")

    # ─── Trial 9 (cap_aware, monthly) ───
    t9_feats = ["beta_spy_60d", "max_dd_126d", "ret_1d"]
    t9_w = (1 / 3, 1 / 3, 1 / 3)
    t9_panel = {f: all_factors[f] for f in t9_feats if f in all_factors}
    if len(t9_panel) != len(t9_feats):
        missing = [f for f in t9_feats if f not in all_factors]
        print(f"  ✗ Trial 9 missing factors: {missing}")
        return 1
    print("[trial3_nav_corr] Building Trial 9 NAV (cap_aware, monthly, top10, h=21)...")
    r = evaluate_composite_spec(
        spec=ResearchCompositeSpec(features=tuple(t9_feats), weights=t9_w,
                                   family_counts={"A": 1, "B": 1, "C": 0, "D": 0, "E": 0, "F": 1}),
        factor_panel_map=t9_panel, price_df=panel["close"],
        open_df=panel["open"], spy_series=spy, qqq_series=qqq,
        config=cfg_cap, research_mask=mask)
    navs["trial_9"] = r.nav
    print(f"  ✓ Trial 9 NAV: n={len(r.nav)}, last={r.nav.iloc[-1]:.4f}")

    # ─── Pair correlations ───
    print("\n[trial3_nav_corr] Computing pair correlations...")
    cand_nav = navs["trial_3"]
    pair_results = []
    for anchor_name, anchor_nav in [("rcm_v1", navs["rcm_v1"]),
                                     ("cand_2", navs["cand_2"]),
                                     ("trial_9", navs["trial_9"])]:
        pc = _pair_corr(cand_nav, anchor_nav, spy, qqq, anchor_name)
        pair_results.append(pc)
        if pc.get("pooled_pearson_raw") is not None:
            print(f"  Trial 3 vs {anchor_name:8s}: raw={pc['pooled_pearson_raw']:.3f} | "
                  f"res_vs_spy={pc['pooled_pearson_residual_vs_spy']:.3f} | "
                  f"res_vs_qqq={pc['pooled_pearson_residual_vs_qqq']:.3f} | n={pc['n_overlap_days']}")
        else:
            print(f"  Trial 3 vs {anchor_name}: {pc.get('note')}")

    # ─── Verdict ───
    verdict = _verdict(pair_results)
    print(f"\n=== VERDICT: {verdict['tier']} ===")
    print(f"reason: {verdict['reason']}")
    if "max_raw" in verdict:
        print(f"max_raw={verdict['max_raw']:.3f}, max_residual={verdict['max_residual']:.3f}")

    out = {
        "candidate_id": f"trial_3_{TRIAL3_ID}",
        "lineage": LINEAGE_TAG,
        "spec": {
            "features": t3_feats,
            "weights": list(t3_w),
            "construction_mode": "cap_aware",
            "rebalance_cadence": "monthly",
            "top_n": 10,
            "horizon_days": 21,
            "cluster_cap": 0.20,
            "max_single_weight": 0.10,
        },
        "anchors": {
            "rcm_v1": {"features": rcm_feats, "weights": list(rcm_w), "mode": "global_top_n"},
            "cand_2": {"features": c2_feats, "weights": list(c2_w), "mode": "global_top_n"},
            "trial_9": {"features": t9_feats, "weights": list(t9_w), "mode": "cap_aware"},
        },
        "pair_correlations": pair_results,
        "verdict": verdict,
        "thresholds_locked_2026_05_07": {
            "green": "all raw < 0.80 AND all residuals < 0.45",
            "yellow": "max raw in [0.80, 0.85) AND max residual < 0.50",
            "red": "any raw >= 0.85 OR any residual >= 0.50",
        },
    }
    out_path = PROJ / "data" / "audit" / "cycle07a_trial3_nav_correlation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[trial3_nav_corr] Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
