"""PRD-2 P2.2 R8 — cross-asset acceptance EXPERIMENT.

experiment round (NOT build): AC = ran + recorded + verdict per
PRD-2 §7 P2.2 + ROOT CAUSE if negative; negative does NOT terminate
the loop (config-scoped, no blanket).

Reuses cycle06 _load_panel via importlib (single SoT, leakage-correct,
partition 'selector' = train+val, sealed 2026 NEVER read). Same
representative spec as R5 (drawup_from_252d_low + trend_tstat_20d +
ret_2d, equal-weight monthly). Two cap_aware_cross_asset configs:
  (i)  cross-asset ENABLED  : asset_class_caps {eq .70/bond .40/
       comm .20/cash .30} (cycle06 default — admits non-equity).
  (ii) equities-ONLY baseline: asset_class_caps {eq 1.0/others 0}.

§7 P2.2 gates (quantified from EvaluatedComposite.weights, real):
  - non_equity_weight_avg utilization in (i) (mean over held days of
    Σ weight where asset_class != equities).
  - DD improvement: (i) full + stress-slice max_dd vs (ii) — cross-
    asset should NOT worsen DD (diversification benefit; report delta).
  - no leveraged-inverse in held columns (R6 guard already GREEN;
    re-assert at holdings level here).

Usage: python dev/scripts/prd2/p2_2_r8_cross_asset_acceptance.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER, make_unified_cluster_map,
)
from core.mining.research_miner import ResearchCompositeSpec

_REPR_FEATS = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")
_LEVERAGED_INVERSE = {"SQQQ", "SPXU", "SPXS", "SDS", "SOXS", "TZA",
                      "QID", "DXD", "SDOW"}


def _load_cycle06_panel():
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    spec = importlib.util.spec_from_file_location("_c6eval", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel()


def _run(spec, panel_map, panel, hc_base, acaps, vys, sslices, mask):
    hc = HarnessConfig(**{**hc_base, "asset_class_caps": acaps})
    return evaluate_composite_spec(
        spec=spec, factor_panel_map=panel_map,
        price_df=panel["close"], open_df=panel["open"],
        spy_series=panel["close"].get("SPY"),
        qqq_series=panel["close"].get("QQQ"),
        config=hc, validation_years=vys, stress_slices=sslices,
        research_mask=mask)


def _non_equity_avg(weights: pd.DataFrame, acmap: dict) -> float:
    if weights is None or weights.empty:
        return float("nan")
    ne_cols = [c for c in weights.columns
               if acmap.get(c, "equities") != "equities"]
    if not ne_cols:
        return 0.0
    held = weights[(weights.abs().sum(axis=1) > 1e-9)]
    if held.empty:
        return 0.0
    return float(held[ne_cols].sum(axis=1).mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    panel, factors, mask, split_cfg = _load_cycle06_panel()
    yrs = {ts.year for ts in panel["close"].index}
    assert 2026 not in yrs, f"SEALED GUARD: 2026 present {sorted(yrs)}"
    feats = [f for f in _REPR_FEATS if f in factors]
    assert len(feats) == len(_REPR_FEATS), f"missing factor {feats}"
    panel_map = {f: factors[f] for f in feats}
    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=tuple([1 / len(feats)] * len(feats)),
        family_counts={"X": len(feats)}, holding_freq="monthly")
    cmap = make_unified_cluster_map(include_cross_asset=True)
    acmap = {s: ASSET_CLASS_BY_CLUSTER[cmap[s]]
             for s in panel["close"].columns if s in cmap}
    hc_base = dict(
        rebalance_cadence="monthly", construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cmap, asset_class_map=acmap)
    vys = sorted({v.year for v in split_cfg.partition.validation_years})
    sslices = {s.name: (s.start.isoformat(), s.end.isoformat())
               for s in split_cfg.partition.stress_slices}
    caps_xasset = {"equities": 0.70, "bonds": 0.40,
                   "commodities": 0.20, "cash_anchor": 0.30}
    caps_eqonly = {"equities": 1.0, "bonds": 0.0,
                   "commodities": 0.0, "cash_anchor": 0.0}
    n_ne = sum(1 for c in panel["close"].columns
               if acmap.get(c, "equities") != "equities")

    if args.smoke:
        HarnessConfig(**{**hc_base, "asset_class_caps": caps_xasset})
        HarnessConfig(**{**hc_base, "asset_class_caps": caps_eqonly})
        leaked = set(panel["close"].columns) & _LEVERAGED_INVERSE
        print(f"SMOKE OK: non-equity instruments in panel={n_ne} "
              f"feats={feats} leveraged_inverse_in_panel={leaked or 'NONE'} "
              f"train+val (sealed excluded)")
        return 0

    xa = _run(spec, panel_map, panel, hc_base, caps_xasset, vys, sslices, mask)
    eo = _run(spec, panel_map, panel, hc_base, caps_eqonly, vys, sslices, mask)
    xa_mfp, eo_mfp = dict(xa.metrics_full_period), dict(eo.metrics_full_period)
    xa_ss = {k: dict(v) for k, v in xa.metrics_per_stress_slice.items()}
    eo_ss = {k: dict(v) for k, v in eo.metrics_per_stress_slice.items()}
    ne_avg = _non_equity_avg(xa.weights, acmap)
    leaked = sorted(set(xa.weights.columns) & _LEVERAGED_INVERSE
                    if xa.weights is not None else set())

    dd_full = {"xasset": float(xa_mfp.get("max_dd", 0.0)),
               "eqonly": float(eo_mfp.get("max_dd", 0.0))}
    dd_full["improvement_pp"] = (abs(dd_full["eqonly"])
                                 - abs(dd_full["xasset"])) * 100
    dd_ss = {}
    for sl in ("covid_flash", "rate_hike_2022"):
        x = abs(float(xa_ss.get(sl, {}).get("max_dd", 0.0)))
        e = abs(float(eo_ss.get(sl, {}).get("max_dd", 0.0)))
        dd_ss[sl] = {"xasset_dd": x, "eqonly_dd": e,
                     "improvement_pp": (e - x) * 100}

    gates = {
        "non_equity_utilization": {
            "non_equity_weight_avg": ne_avg,
            "pass": (ne_avg is not None and ne_avg > 0.0)},
        "dd_not_worse": {
            "full": dd_full, "stress": dd_ss,
            "pass": dd_full["improvement_pp"] >= -0.01},  # not worse
        "no_leveraged_inverse": {
            "leaked": leaked, "pass": not leaked},
    }
    verdict = "PASS" if all(g["pass"] for g in gates.values()) \
        else "FAIL_recorded_root_cause"
    out = {"experiment": "p2_2_r8_cross_asset_acceptance",
           "sealed_2026_read": False, "spec_feats": list(feats),
           "non_equity_instruments_in_panel": n_ne,
           "xasset_mfp": xa_mfp, "eqonly_mfp": eo_mfp,
           "gates": gates, "verdict": verdict}
    p = Path("data/audit/ml_redo/p2_2_r8_cross_asset.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"P2.2 R8 verdict={verdict} -> {p}")
    print(f"  non_equity_weight_avg={ne_avg:.4f} (pass="
          f"{gates['non_equity_utilization']['pass']})")
    print(f"  full max_dd xasset={dd_full['xasset']:.4f} "
          f"eqonly={dd_full['eqonly']:.4f} "
          f"improvement={dd_full['improvement_pp']:.2f}pp "
          f"(not-worse pass={gates['dd_not_worse']['pass']})")
    print(f"  leveraged_inverse_leaked={leaked or 'NONE'} "
          f"(pass={gates['no_leveraged_inverse']['pass']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
