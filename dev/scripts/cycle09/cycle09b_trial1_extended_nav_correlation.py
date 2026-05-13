"""cycle09b §5.1 — Trial 1 extended NAV correlation vs 5 anchors.

Builds NAV for cycle09b Trial 1 (`5a99868072e6` =
`rs_vs_spy_63d + cpi_yoy_pct + rd_intensity_ttm`, equal-weight,
cap_aware_cross_asset, monthly, top10) on the cycle09b selector
partition (train + validation, ~16y) and computes pairwise NAV
correlations against five anchors using each anchor's frozen
construction:

  - RCMv1 (`rcm_v1_defensive_composite_01`):
      beta_spy_60d + drawup_from_252d_low + days_since_52w_high +
      amihud_20d, weights (0.186, 0.302, 0.395, 0.117), global_top_n
  - Cand-2 (`candidate_2_orthogonal_01`):
      ret_5d + rs_vs_spy_126d + hl_range, equal 1/3, global_top_n
  - Trial 9 (`trial9_diversifier_002` = same spec as v1):
      beta_spy_60d + max_dd_126d + ret_1d, equal 1/3, cap_aware
  - cycle07a Trial 3 (`1e771580f486`):
      drawup_from_252d_low + mom_63d + ret_1d, equal 1/3, cap_aware
  - cycle08 top-1 (`8ac6bccbeed1`):
      max_dd_126d + mom_252d + reversal_21d, equal 1/3, cap_aware,
      holding_freq=weekly

Tier verdict per cycle09b yaml + cycle07a-locked thresholds
(2026-05-07):
  - raw < 0.50           → true_diversifier
  - 0.50 - 0.70          → partial_diversifier
  - 0.70 - 0.85          → warn_label_void
  - >= 0.85              → reject_step5

Output: data/audit/cycle09b_trial1_extended_nav_correlation.json
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


# ── Pair correlation helpers (lifted from cycle07a trial3_nav_correlation.py) ──


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
    common = (
        cand_ret.index
        .intersection(ref_ret.index)
        .intersection(spy_ret.index)
        .intersection(qqq_ret.index)
    )
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


def _classify_raw(raw) -> str:
    if raw is None or (isinstance(raw, float) and not np.isfinite(raw)):
        return "insufficient_data"
    if raw < 0.50:
        return "true_diversifier"
    if raw < 0.70:
        return "partial_diversifier"
    if raw < 0.85:
        return "warn_label_void"
    return "reject_step5"


def _verdict(pair_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    raws = [p.get("pooled_pearson_raw") for p in pair_results
            if p.get("pooled_pearson_raw") is not None]
    res_spys = [p.get("pooled_pearson_residual_vs_spy") for p in pair_results
                if p.get("pooled_pearson_residual_vs_spy") is not None]
    res_qqqs = [p.get("pooled_pearson_residual_vs_qqq") for p in pair_results
                if p.get("pooled_pearson_residual_vs_qqq") is not None]
    if not raws:
        return {"tier": "INSUFFICIENT", "reason": "missing pair correlations"}
    max_raw = max(raws)
    max_res = max(max(res_spys, default=0), max(res_qqqs, default=0))
    raw_classifications = {
        p["anchor"]: _classify_raw(p["pooled_pearson_raw"]) for p in pair_results
        if p.get("pooled_pearson_raw") is not None
    }
    # locked thresholds per 2026-05-07 x.txt
    if any(r >= 0.85 for r in raws):
        red_pairs = [p["anchor"] for p in pair_results
                     if (p.get("pooled_pearson_raw") or 0) >= 0.85]
        return {
            "tier": "RED",
            "reason": f"raw >= 0.85 violation in pairs: {red_pairs}",
            "max_raw": max_raw, "max_residual": max_res,
            "per_anchor_raw_tier": raw_classifications,
        }
    if any(r >= 0.50 for r in res_spys + res_qqqs):
        red_pairs = [p["anchor"] for p in pair_results
                     if (p.get("pooled_pearson_residual_vs_spy") or 0) >= 0.50
                     or (p.get("pooled_pearson_residual_vs_qqq") or 0) >= 0.50]
        return {
            "tier": "RED",
            "reason": f"residual >= 0.50 violation in pairs: {red_pairs}",
            "max_raw": max_raw, "max_residual": max_res,
            "per_anchor_raw_tier": raw_classifications,
        }
    if max_raw < 0.80 and max_res < 0.45:
        return {
            "tier": "GREEN",
            "reason": "all raw < 0.80 and all residuals < 0.45",
            "max_raw": max_raw, "max_residual": max_res,
            "per_anchor_raw_tier": raw_classifications,
        }
    if 0.80 <= max_raw < 0.85 and max_res < 0.50:
        return {
            "tier": "YELLOW",
            "reason": "max raw in [0.80, 0.85) and max residual < 0.50",
            "max_raw": max_raw, "max_residual": max_res,
            "per_anchor_raw_tier": raw_classifications,
        }
    if max_raw < 0.80 and 0.45 <= max_res < 0.50:
        return {
            "tier": "YELLOW",
            "reason": "max residual in [0.45, 0.50) (raw < 0.80)",
            "max_raw": max_raw, "max_residual": max_res,
            "per_anchor_raw_tier": raw_classifications,
        }
    return {
        "tier": "RED",
        "reason": f"unexpected combination: max_raw={max_raw:.3f}, "
                  f"max_residual={max_res:.3f}",
        "max_raw": max_raw, "max_residual": max_res,
        "per_anchor_raw_tier": raw_classifications,
    }


def _cap_aware_cfg(panel) -> HarnessConfig:
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    return HarnessConfig(
        rebalance_cadence="monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )


def _cap_aware_stocks_only_cfg() -> HarnessConfig:
    """Trial 9 / cycle07a Trial 3 native config (cap_aware on stocks)."""
    return HarnessConfig(
        construction_mode="cap_aware",
        rebalance_cadence="monthly",
        top_n=10,
        horizon_days=21,
        cluster_cap=0.20,
        max_single_weight=0.10,
        cluster_map=STOCK_RISK_CLUSTER_MAP,
    )


def _global_top_n_cfg(cadence: str = "monthly") -> HarnessConfig:
    """RCMv1 / Cand-2 native config (global_top_n)."""
    return HarnessConfig(
        construction_mode="global_top_n",
        rebalance_cadence=cadence,
        top_n=10,
        horizon_days=21,
    )


def _build_nav(name, feats, weights, family_counts, panel, factors, mask, cfg, holding_freq="monthly") -> pd.Series:
    print(f"[{name}] Building NAV with {len(feats)} factor(s) via {cfg.construction_mode} / {cfg.rebalance_cadence}...")
    t0 = time.time()
    panel_map = {f: factors[f] for f in feats if f in factors}
    if len(panel_map) != len(feats):
        missing = [f for f in feats if f not in factors]
        raise SystemExit(f"  ✗ {name} missing factors: {missing}")
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=tuple(weights),
        family_counts=family_counts, holding_freq=holding_freq,
    )
    r = evaluate_composite_spec(
        spec=spec, factor_panel_map=panel_map, price_df=panel["close"],
        open_df=panel["open"], spy_series=spy, qqq_series=qqq,
        config=cfg, research_mask=mask,
    )
    elapsed = time.time() - t0
    print(f"  ✓ {name} NAV: n={len(r.nav)}, last={r.nav.iloc[-1]:.4f} ({elapsed:.1f}s)")
    return r.nav


def main() -> int:
    print("[cycle09b §5.1] Loading panel + factors via cycle09b _load_panel()...")
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape}, factors={len(factors)} ({time.time()-t0:.1f}s)")

    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")

    navs: Dict[str, pd.Series] = {}

    # ── cycle09b Trial 1 (5a99868072e6) — cap_aware_cross_asset ──
    navs["cycle09b_trial1"] = _build_nav(
        "cycle09b Trial 1",
        feats=["rs_vs_spy_63d", "cpi_yoy_pct", "rd_intensity_ttm"],
        weights=[1/3, 1/3, 1/3],
        family_counts={"A": 1, "P": 1, "N": 1},
        panel=panel, factors=factors, mask=mask,
        cfg=_cap_aware_cfg(panel),
        holding_freq="monthly",
    )

    # ── RCMv1 — global_top_n, monthly ──
    rcm_w_raw = (0.186, 0.302, 0.395, 0.117)
    rcm_w = tuple(w / sum(rcm_w_raw) for w in rcm_w_raw)
    navs["rcm_v1"] = _build_nav(
        "RCMv1",
        feats=["beta_spy_60d", "drawup_from_252d_low", "days_since_52w_high", "amihud_20d"],
        weights=list(rcm_w),
        family_counts={"A": 1, "B": 1, "C": 1, "F": 1},
        panel=panel, factors=factors, mask=mask,
        cfg=_global_top_n_cfg("monthly"),
        holding_freq="monthly",
    )

    # ── Cand-2 — global_top_n, monthly ──
    navs["cand_2"] = _build_nav(
        "Cand-2",
        feats=["ret_5d", "rs_vs_spy_126d", "hl_range"],
        weights=[1/3, 1/3, 1/3],
        family_counts={"D": 1, "E": 1, "F": 1},
        panel=panel, factors=factors, mask=mask,
        cfg=_global_top_n_cfg("monthly"),
        holding_freq="monthly",
    )

    # ── Trial 9 v1/v2 — cap_aware (stocks only) ──
    navs["trial_9"] = _build_nav(
        "Trial 9",
        feats=["beta_spy_60d", "max_dd_126d", "ret_1d"],
        weights=[1/3, 1/3, 1/3],
        family_counts={"A": 1, "B": 1, "F": 1},
        panel=panel, factors=factors, mask=mask,
        cfg=_cap_aware_stocks_only_cfg(),
        holding_freq="monthly",
    )

    # ── cycle07a Trial 3 — cap_aware (stocks only) ──
    navs["cycle07a_trial3"] = _build_nav(
        "cycle07a Trial 3",
        feats=["drawup_from_252d_low", "mom_63d", "ret_1d"],
        weights=[1/3, 1/3, 1/3],
        family_counts={"B": 1, "D": 1, "F": 1},
        panel=panel, factors=factors, mask=mask,
        cfg=_cap_aware_stocks_only_cfg(),
        holding_freq="monthly",
    )

    # ── cycle08 top-1 (8ac6bccbeed1) — cap_aware_cross_asset, weekly
    # (per data/research_candidates/track-c-cycle-2026-05-08-01_promotion_criteria.yaml
    # construction.mode = cap_aware_cross_asset)
    cluster_map_xa = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map_xa = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map_xa[sym]]
        for sym in panel["close"].columns if sym in cluster_map_xa
    }
    weekly_cfg = HarnessConfig(
        construction_mode="cap_aware_cross_asset",
        rebalance_cadence="weekly",
        top_n=10, horizon_days=21,
        cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map_xa,
        asset_class_map=asset_class_map_xa,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )
    navs["cycle08_top1"] = _build_nav(
        "cycle08 top-1",
        feats=["max_dd_126d", "mom_252d", "reversal_21d"],
        weights=[1/3, 1/3, 1/3],
        family_counts={"B": 1, "A": 1, "F": 1},
        panel=panel, factors=factors, mask=mask,
        cfg=weekly_cfg,
        holding_freq="weekly",
    )

    # ── Pair correlations ──
    print("\n[cycle09b §5.1] Computing pair correlations...")
    cand_nav = navs["cycle09b_trial1"]
    pair_results = []
    for anchor_name in ["rcm_v1", "cand_2", "trial_9", "cycle07a_trial3", "cycle08_top1"]:
        pc = _pair_corr(cand_nav, navs[anchor_name], spy, qqq, anchor_name)
        pair_results.append(pc)
        if pc.get("pooled_pearson_raw") is not None:
            tier = _classify_raw(pc["pooled_pearson_raw"])
            print(
                f"  Trial 1 vs {anchor_name:16s}: raw={pc['pooled_pearson_raw']:.3f}  "
                f"res_spy={pc['pooled_pearson_residual_vs_spy']:.3f}  "
                f"res_qqq={pc['pooled_pearson_residual_vs_qqq']:.3f}  "
                f"n={pc['n_overlap_days']}  tier={tier}"
            )

    verdict = _verdict(pair_results)
    print(f"\n=== VERDICT: {verdict['tier']} ===")
    print(f"reason: {verdict['reason']}")
    if "max_raw" in verdict:
        print(f"max_raw={verdict['max_raw']:.3f}  max_residual={verdict['max_residual']:.3f}")
    if "per_anchor_raw_tier" in verdict:
        print("Per-anchor raw tiers:")
        for anchor, t in verdict["per_anchor_raw_tier"].items():
            print(f"  {anchor:16s}: {t}")

    out = {
        "cycle": "track-c-cycle-2026-05-12-09b",
        "audit_section": "§5.1 extended panel NAV correlation vs 5 anchors",
        "candidate_id": "cycle09b_trial1_5a99868072e6",
        "candidate_spec": {
            "features": ["rs_vs_spy_63d", "cpi_yoy_pct", "rd_intensity_ttm"],
            "weights": [1/3, 1/3, 1/3],
            "construction_mode": "cap_aware_cross_asset",
            "rebalance_cadence": "monthly",
            "top_n": 10,
            "horizon_days": 21,
        },
        "anchors_count": 5,
        "panel_dates": [str(panel["close"].index[0].date()), str(panel["close"].index[-1].date())],
        "panel_shape": list(panel["close"].shape),
        "pair_correlations": pair_results,
        "verdict": verdict,
        "tier_thresholds": {
            "true_diversifier": "raw < 0.50",
            "partial_diversifier": "0.50 ≤ raw < 0.70",
            "warn_label_void": "0.70 ≤ raw < 0.85",
            "reject_step5": "raw ≥ 0.85",
        },
    }
    out_path = PROJ / "data" / "audit" / "cycle09b_trial1_extended_nav_correlation.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[cycle09b §5.1] Output: {out_path.relative_to(PROJ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
