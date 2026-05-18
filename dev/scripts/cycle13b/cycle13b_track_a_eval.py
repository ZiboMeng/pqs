"""PRD-AC v1.1 Phase 4 cycle06 Track A acceptance eval for top-N trials.

For each of top-N v2 archived trials, runs harness on
partition_for_role(role="selector") panel (train + validation), extracts
per-year + stress + concentration + beta metrics, and runs
``run_split_acceptance`` to produce the PRD §5.3 gate 1 verdict.

Usage
-----
    python dev/scripts/cycle06/cycle06_track_a_eval.py
    python dev/scripts/cycle06/cycle06_track_a_eval.py --top-n 3
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import generate_all_factors
from core.mining.research_miner import ResearchCompositeSpec
from core.research.harness import HarnessConfig, evaluate_composite_spec
from core.research.risk_cluster_map import (
    ASSET_CLASS_BY_CLUSTER,
    CROSS_ASSET_RISK_CLUSTER_MAP,
    make_unified_cluster_map,
)
from core.research.temporal_split import (
    load_temporal_split,
    partition_for_role,
)
from core.research.temporal_split_acceptance import run_split_acceptance


def _load_panel():
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}  # cycle06 yaml drop_symbols
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
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
    panel = {
        "close": pd.DataFrame(frames["close"]).sort_index(),
    }
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")
    # ROOT-CAUSE FIX (cycle13b 0-eval): cycle06 used generate_all_factors
    # = OHLCV-family ONLY (96), but cycle13b mined the full
    # RESEARCH_FACTORS pool (187: + fundamental/sector/macro/calendar
    # via EDGAR/sector_map/FRED). beneish_m_score / month_end_quarter_end
    # are NOT in generate_all_factors → "missing factor panels". Use the
    # SAME 4-path merge the miner used (_build_factor_panel_map) so the
    # candidate's factors resolve. Same class as the W4/F3 96-vs-143
    # honest-scope finding.
    from scripts.run_research_miner import _build_factor_panel_map
    tradable = [s for s in panel["close"].columns if s not in ("SPY", "QQQ")]
    factors, _fwd, mask, _nm = _build_factor_panel_map(
        panel, tradable, horizon=21, split_cfg=split_cfg)
    return panel, factors, mask, split_cfg


def _eval_trial(trial_row: Dict[str, Any], panel, factors, mask, split_cfg,
                freeze_date=None):
    feats = trial_row["features"].split(",")
    raw_w = [float(w) for w in trial_row["weights_csv"].split(",")]
    total = sum(raw_w)
    weights = tuple(w / total for w in raw_w)
    panel_map = {f: factors[f] for f in feats if f in factors}
    if len(panel_map) != len(feats):
        return {"error": "missing factor panels"}
    spec = ResearchCompositeSpec(
        features=tuple(feats), weights=weights, family_counts={"X": len(feats)},
        holding_freq=trial_row.get("holding_freq", "monthly"),
    )
    cluster_map = make_unified_cluster_map(include_cross_asset=True)
    asset_class_map = {
        sym: ASSET_CLASS_BY_CLUSTER[cluster_map[sym]]
        for sym in panel["close"].columns if sym in cluster_map
    }
    hc = HarnessConfig(
        rebalance_cadence=spec.holding_freq or "monthly",
        construction_mode="cap_aware_cross_asset",
        top_n=10, cluster_cap=0.20, max_single_weight=0.10,
        cluster_map=cluster_map,
        asset_class_map=asset_class_map,
        asset_class_caps={
            "equities": 0.70, "bonds": 0.40,
            "commodities": 0.20, "cash_anchor": 0.30,
        },
    )
    spy = panel["close"].get("SPY")
    qqq = panel["close"].get("QQQ")
    validation_years = sorted({vy.year for vy in split_cfg.partition.validation_years})
    stress_slices = {
        ss.name: (ss.start.isoformat(), ss.end.isoformat())
        for ss in split_cfg.partition.stress_slices
    }
    res = evaluate_composite_spec(
        spec=spec, factor_panel_map=panel_map,
        price_df=panel["close"], open_df=panel["open"],
        spy_series=spy, qqq_series=qqq, config=hc,
        validation_years=validation_years, stress_slices=stress_slices,
        research_mask=mask,
    )
    # Build metrics dict in run_split_acceptance schema
    # Metrics dict mirrors temporal_split.yaml acceptance schema. _eval_beta_gate
    # in temporal_split_acceptance.py resolves "beta.beta_to_qqq" — the gate
    # fail-closes if beta is at top-level (P0 fix 2026-05-07; pre-fix all
    # cycle06/07a/08 trials had false-negative beta_to_qqq fail despite actual
    # values 0.53/0.57/-0.01 well under 0.85 cap).
    metrics: Dict[str, Any] = {
        "validation": {},
        "stress_slice": {},
        "concentration": {
            "top1_max": float(res.concentration.get("top1_max", 0.0)),
            "top3_max": float(res.concentration.get("top3_max", 0.0)),
            "leveraged_etf_dependency": False,  # cycle06 universe excludes leveraged
        },
        "beta": {
            "beta_to_qqq": float(res.nav_correlation_vs_benchmark.get("beta_vs_qqq", 0.0)),
        },
        "cost": {"multiplier_2x_remains_positive": True},  # report-only
    }
    for y, m in res.metrics_per_validation_year.items():
        metrics["validation"][int(y)] = {
            "maxdd": float(m.get("max_dd", 0.0)),
            "excess_vs_spy": float(m.get("vs_spy", 0.0)),
            "excess_vs_qqq": float(m.get("vs_qqq", 0.0)),
        }
    for sname, sm in res.metrics_per_stress_slice.items():
        metrics["stress_slice"][sname] = {"maxdd": float(sm.get("max_dd", 0.0))}

    # ── P0-B FIRST REAL USE: W7b overfit panel + W7c/d CPCV fold ──
    # honest_n_trials = 200 = cycle13b attempted trial count (the
    # selection-bias breadth the nominee was chosen from; G1 honest-N,
    # NOT a magic literal). strat_ret_d = adjusted-price backtest daily
    # returns (res.daily_returns). per_trial_period_perf=None →
    # forward-only (rcm scalar-only, audit §6).
    dr = res.daily_returns.dropna()
    metrics["overfit_inputs"] = {
        "strat_ret_d": [float(x) for x in dr.values],
        "honest_n_trials": 200,
        "actual_years": round(len(dr) / 252.0, 3),
    }
    # W7c/d cpcv_inputs — ROBUST reconstruction (fix: prior z-score
    # version collapsed on sparse fundamental [beneish: quarterly EDGAR]
    # + near-constant calendar [month_end: 0/1, xs-std≈0 → div0]).
    # Fixes: (a) per-symbol ffill so quarterly fundamentals are defined
    # daily (step-function: valid until next filing); (b) cross-sectional
    # PCT-RANK not z-score — robust to constant/sparse, AND matches how
    # the miner computes rank-IC; (c) no arbitrary 500 pre-gate —
    # cpcv_acceptance_distribution's own insufficient fail-closed decides;
    # (d) skip reason ALWAYS surfaced (never silent None — 不走过场).
    # Honest approximation noted: pred/fwd pooled (date,sym) time-ordered;
    # CPCV purge unit = rows≈horizon*n_active, not exact trading days —
    # the same pooled approximation cycle04-08 mining IC_IR uses.
    try:
        px = panel["close"]
        comp = None
        for f, w in zip(feats, weights):
            fac = panel_map[f].reindex_like(px).ffill()  # (a) step-fn
            r = fac.rank(axis=1, pct=True)               # (b) xs pct-rank
            comp = r * w if comp is None else comp + r * w
        fwd_ret = px.pct_change(21).shift(-21)
        al = pd.concat([comp.stack(dropna=False),
                        fwd_ret.stack(dropna=False)], axis=1).dropna()
        n_al = len(al)
        if n_al >= 200:                                  # (c) cpcv decides
            metrics["cpcv_inputs"] = {
                "pred": [float(x) for x in al.iloc[:, 0].values],
                "fwd": [float(x) for x in al.iloc[:, 1].values],
                "honest_n_trials": 200,
            }
            metrics["_cpcv_inputs_n"] = int(n_al)
        else:
            metrics["_cpcv_inputs_skipped"] = (
                f"only {n_al} aligned (date,sym) pairs after "
                f"ffill+rank — NOT a pass, surfaced not silent")
    except Exception as _e:  # never fake a pass; ALWAYS record
        metrics["_cpcv_inputs_skipped"] = f"{type(_e).__name__}: {_e}"

    verdict = run_split_acceptance(metrics, role="core", freeze_date=freeze_date)
    return {
        "metrics_full_period": res.metrics_full_period,
        "metrics_per_year": {int(y): dict(m) for y, m in res.metrics_per_validation_year.items()},
        "metrics_per_stress": {k: dict(v) for k, v in res.metrics_per_stress_slice.items()},
        "concentration": dict(res.concentration),
        "nav_correlation_vs_benchmark": dict(res.nav_correlation_vs_benchmark),
        "n_observed_days": int(res.n_observed_days),
        "track_a_overall_passed": bool(verdict.overall_passed),
        "track_a_failed_gates": [
            g.name for g in verdict.gates if not g.passed
        ],
        "track_a_n_gates": len(verdict.gates),
        # P0-B first real use — surface the new machinery verdicts
        "overfit_diagnostics": verdict.overfit_diagnostics,   # W7b
        "cpcv_acceptance": verdict.cpcv_acceptance,            # W7c/d
        "cpcv_gate": next(
            ({"passed": g.passed, "values": g.values}
             for g in verdict.gates
             if g.name == "cpcv_distribution_acceptance"), None),
        # never silent: why cpcv didn't fire, if it didn't
        "cpcv_inputs_n": metrics.get("_cpcv_inputs_n"),
        "cpcv_inputs_skipped": metrics.get("_cpcv_inputs_skipped"),
    }


def main() -> int:
    from datetime import date as _date
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archive-db", default=str(PROJ / "data/mining/rcm_archive.db"))
    ap.add_argument("--lineage", default="track-c-cycle-2026-05-18-13b")
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--freeze-date",
                    help="ISO YYYY-MM-DD; routes to v3 yaml if >=2026-05-02. "
                         "Default: derive from --lineage.")
    args = ap.parse_args()
    if args.freeze_date:
        freeze_date = _date.fromisoformat(args.freeze_date)
    else:
        try:
            parts = args.lineage.split("-")
            freeze_date = _date(int(parts[-4]), int(parts[-3]), int(parts[-2]))
        except (ValueError, IndexError):
            freeze_date = None
    print(f"freeze_date for split dispatch: {freeze_date}")

    print(f"Loading top-{args.top_n} archived trials from {args.lineage}...")
    conn = sqlite3.connect(args.archive_db)
    cur = conn.execute(
        "SELECT trial_id, ic_ir, objective, nav_sharpe, nav_max_dd, "
        "features_csv, weights_csv, spec_json "
        "FROM rcm_trials WHERE lineage_tag=? AND objective IS NOT NULL "
        "ORDER BY objective DESC LIMIT ?",
        (args.lineage, args.top_n),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print(f"No trials archived under {args.lineage}")
        return 1
    trials = [
        {
            "trial_id": r[0], "ic_ir": r[1], "objective": r[2],
            "nav_sharpe": r[3], "nav_max_dd": r[4],
            "features": r[5], "weights_csv": r[6],
            "holding_freq": json.loads(r[7]).get("holding_freq", "monthly"),
        }
        for r in rows
    ]

    print("Loading panel + factors (selector role)...")
    import time
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape[0]} dates × {panel['close'].shape[1]} symbols ({time.time()-t0:.1f}s)")

    results = []
    for i, t in enumerate(trials, 1):
        print(f"\n[{i}/{len(trials)}] trial_id={t['trial_id']} "
              f"holding={t['holding_freq']} feats={t['features']}")
        ts = time.time()
        ev = _eval_trial(t, panel, factors, mask, split_cfg,
                         freeze_date=freeze_date)
        if "error" in ev:
            print(f"  ERROR: {ev['error']}")
            continue
        elapsed = time.time() - ts
        verdict = "PASS" if ev["track_a_overall_passed"] else "FAIL"
        print(f"  Track A verdict: {verdict} ({elapsed:.1f}s)")
        if not ev["track_a_overall_passed"]:
            print(f"  Failed gates ({len(ev['track_a_failed_gates'])}):")
            for g in ev["track_a_failed_gates"]:
                print(f"    - {g}")
        # Surface key per-year + stress metrics
        for y in sorted(ev["metrics_per_year"].keys()):
            ym = ev["metrics_per_year"][y]
            print(f"    {y}: maxdd={ym.get('max_dd', 0):.2%} "
                  f"vs_spy={ym.get('vs_spy', 0):+.2%} "
                  f"vs_qqq={ym.get('vs_qqq', 0):+.2%}")
        for sname, sm in ev["metrics_per_stress"].items():
            print(f"    [stress] {sname}: maxdd={sm.get('max_dd', 0):.2%}")
        od = ev.get("overfit_diagnostics") or {}
        cg = ev.get("cpcv_gate") or {}
        print(f"    [W7b] DSR(honest N={od.get('dsr_n_trials')})="
              f"{od.get('dsr')}  MinBTL_gate="
              f"{(od.get('min_btl_gate') or {}).get('passed')}")
        print(f"    [W7c/d] cpcv_gate passed={cg.get('passed')} "
              f"vals={cg.get('values')}")
        print(f"    [W7c/d] cpcv_inputs_n={ev.get('cpcv_inputs_n')} "
              f"skipped={ev.get('cpcv_inputs_skipped')}")
        results.append({
            "trial_id": t["trial_id"], "spec": t,
            "evaluation": ev,
        })

    out = {
        "lineage": args.lineage,
        "n_evaluated": len(results),
        "n_passed": sum(1 for r in results if r["evaluation"]["track_a_overall_passed"]),
        "results": results,
    }
    out_path = Path(
        args.out_json or
        f"data/audit/cycle13b_track_a_eval_{args.lineage}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    print(f"Verdict: {out['n_passed']} of {out['n_evaluated']} passed Track A acceptance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
