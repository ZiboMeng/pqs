"""PRD-2 P2.1 R5 — T1-vs-T0 leakage-correct ACCEPTANCE EXPERIMENT.

experiment round (NOT a build): AC = ran + recorded + verdict per
PRD-2 §7 P2.1 quantified gates + ROOT CAUSE if negative. A negative
result does NOT terminate the loop (config-scoped, no blanket).

Setup (leakage-correct, sealed-NEVER-read by construction): reuse
cycle06_track_a_eval._load_panel (partition_for_role 'selector' =
train+validation only; sealed 2026 excluded). Representative spec =
the cycle06 forward-init'd composite (drawup_from_252d_low +
trend_tstat_20d + ret_2d, equal-weight, monthly). The hedge ETF SH
is AUGMENTED into the priced panel (else evaluate_composite_spec's
common_syms filter would silently drop the T1 sleeve → invalid test;
SH parquet is curated-clean, 0 weekend rows, R3-verified).

§7 P2.1 gates:
  (a) per-stress-slice maxdd: T1 abs-drop vs T0 ≥ 3pp on covid_flash
      / rate_hike_2022.
  (b) full-period vs_spy: T1 net ≥ T0 − 1pp (hedge must not white-kill
      alpha).
  (c) decay BOTH legs reported: realized T1 (real SH prices = decay-
      inclusive) vs a synthetic no-decay-optimistic hedge leg
      (inverse_etf_decay_return) — never only-optimistic.

Usage:  python dev/scripts/prd2/p2_1_r5_t1_vs_t0_experiment.py [--smoke]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]  # dev/scripts/prd2/ → repo root
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.data.bar_store import BarStore
from core.config.loader import load_config
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER, make_unified_cluster_map,
)
from core.research.construction_tiers import inverse_etf_decay_return
from core.mining.research_miner import ResearchCompositeSpec

_HEDGE_ETF = "SH"
_REPR_FEATS = ("drawup_from_252d_low", "trend_tstat_20d", "ret_2d")
_FRAC_SWEEP = (0.10, 0.20, 0.30)


def _load_cycle06_panel():
    """Import the canonical leakage-correct panel builder (single SoT,
    no duplication) from the cycle06 eval script by path."""
    p = PROJ / "dev/scripts/cycle06/cycle06_track_a_eval.py"
    spec = importlib.util.spec_from_file_location("_c6eval", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._load_panel()


def _augment_hedge(panel):
    """Add SH close/open to the priced panel so the T1 sleeve is
    actually valued (curated-clean, adjusted)."""
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    df = store.load(_HEDGE_ETF, freq="1d", adjusted=True, fallback="local")
    if df is None or df.empty or "close" not in df.columns:
        raise RuntimeError(f"hedge ETF {_HEDGE_ETF} price load failed")
    for k in ("close", "open"):
        col = df[k] if k in df.columns else df["close"]
        panel[k][_HEDGE_ETF] = col.reindex(panel["close"].index)
    return panel


def _run(tier, frac, spec, panel_map, panel, hc_base, vys, sslices, mask):
    hc = HarnessConfig(**{**hc_base, "construction_tier": tier,
                          "hedge_etf": _HEDGE_ETF, "hedge_frac": frac})
    return evaluate_composite_spec(
        spec=spec, factor_panel_map=panel_map,
        price_df=panel["close"], open_df=panel["open"],
        spy_series=panel["close"].get("SPY"),
        qqq_series=panel["close"].get("QQQ"),
        config=hc, validation_years=vys, stress_slices=sslices,
        research_mask=mask)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    panel, factors, mask, split_cfg = _load_cycle06_panel()
    panel = _augment_hedge(panel)
    assert _HEDGE_ETF in panel["close"].columns, "hedge not priced!"
    yrs = {ts.year for ts in panel["close"].index}
    assert 2026 not in yrs, f"SEALED GUARD: 2026 present {sorted(yrs)}"

    feats = [f for f in _REPR_FEATS if f in factors]
    assert len(feats) == len(_REPR_FEATS), f"missing factor {feats}"
    panel_map = {f: factors[f] for f in feats}
    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=tuple([1 / len(feats)] * len(feats)),
        family_counts={"X": len(feats)}, holding_freq="monthly")
    cmap = make_unified_cluster_map(include_cross_asset=True)
    hc_base = dict(
        rebalance_cadence="monthly", construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10, cluster_map=cmap,
        asset_class_map={s: ASSET_CLASS_BY_CLUSTER[cmap[s]]
                         for s in panel["close"].columns if s in cmap},
        asset_class_caps={"equities": 0.70, "bonds": 0.40,
                          "commodities": 0.20, "cash_anchor": 0.30})
    vys = sorted({v.year for v in split_cfg.partition.validation_years})
    sslices = {s.name: (s.start.isoformat(), s.end.isoformat())
               for s in split_cfg.partition.stress_slices}

    if args.smoke:
        # build-correctness only: SH priced, T0/T1 configs valid, no run
        HarnessConfig(**{**hc_base, "construction_tier": "T0"})
        HarnessConfig(**{**hc_base, "construction_tier": "T1",
                         "hedge_etf": _HEDGE_ETF, "hedge_frac": 0.20})
        print(f"SMOKE OK: SH priced={_HEDGE_ETF in panel['close'].columns} "
              f"feats={feats} train+val yrs={sorted(yrs)} (sealed excluded)")
        return 0

    t0 = _run("T0", 0.0, spec, panel_map, panel, hc_base, vys, sslices, mask)
    t0_mfp = dict(t0.metrics_full_period)
    t0_ss = {k: dict(v) for k, v in t0.metrics_per_stress_slice.items()}
    out = {"experiment": "p2_1_r5_t1_vs_t0", "spec_feats": list(feats),
           "sealed_2026_read": False, "T0": {"mfp": t0_mfp, "stress": t0_ss},
           "T1": {}, "gates": {}, "decay_both_legs": {}}

    for fr in _FRAC_SWEEP:
        r = _run("T1", fr, spec, panel_map, panel, hc_base, vys, sslices, mask)
        mfp = dict(r.metrics_full_period)
        ss = {k: dict(v) for k, v in r.metrics_per_stress_slice.items()}
        # gate (a): per-slice maxdd abs-drop >= 3pp
        ga = {}
        for sl in ("covid_flash", "rate_hike_2022"):
            d0 = abs(float(t0_ss.get(sl, {}).get("max_dd", 0.0)))
            d1 = abs(float(ss.get(sl, {}).get("max_dd", 0.0)))
            ga[sl] = {"t0_dd": d0, "t1_dd": d1, "abs_drop_pp": (d0 - d1) * 100,
                      "pass": (d0 - d1) >= 0.03}
        # gate (b): full vs_spy net >= T0 - 1pp
        vb = {"t0_vs_spy": float(t0_mfp.get("vs_spy", 0.0)),
              "t1_vs_spy": float(mfp.get("vs_spy", 0.0))}
        vb["pass"] = vb["t1_vs_spy"] >= vb["t0_vs_spy"] - 0.01
        out["T1"][f"frac_{fr}"] = {"mfp": mfp, "stress": ss}
        out["gates"][f"frac_{fr}"] = {"a_stress_maxdd": ga, "b_vs_spy": vb}

    # gate (c): decay both legs on SH realized daily returns (period)
    sh = panel["close"][_HEDGE_ETF].dropna()
    sh_ret = sh.pct_change().dropna().to_numpy()
    modeled, naive = inverse_etf_decay_return(sh_ret, expense_annual=0.0090)
    out["decay_both_legs"] = {
        "note": "realized SH price path already embeds real daily-reset "
                "decay; naive-optimistic is the no-decay counterfactual. "
                "Both reported (PRD-2 §7 P2.1c — never only optimistic).",
        "sh_modeled_cum": modeled, "sh_naive_optimistic_cum": naive,
        "decay_drag_pp": (modeled - naive) * 100}

    verdict_pass = all(
        g["b_vs_spy"]["pass"] and any(v["pass"] for v in
                                      g["a_stress_maxdd"].values())
        for g in out["gates"].values())
    out["verdict"] = "PASS" if verdict_pass else "FAIL_recorded_root_cause"
    p = Path("data/audit/ml_redo/p2_1_r5_t1_vs_t0.json")
    p.write_text(json.dumps(out, indent=2, default=str))
    print(f"P2.1 R5 verdict={out['verdict']} -> {p}")
    for fr in _FRAC_SWEEP:
        g = out["gates"][f"frac_{fr}"]
        print(f"  frac={fr}: vs_spy {g['b_vs_spy']['t0_vs_spy']:.3f}->"
              f"{g['b_vs_spy']['t1_vs_spy']:.3f}(pass={g['b_vs_spy']['pass']}) "
              f"covid dd-drop {g['a_stress_maxdd']['covid_flash']['abs_drop_pp']:.2f}pp")
    print(f"  decay: modeled={modeled:.4f} naive={naive:.4f} "
          f"drag={(modeled-naive)*100:.2f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
