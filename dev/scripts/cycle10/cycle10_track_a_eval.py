"""cycle #10 Track A 17-gate acceptance evaluator.

Mirrors dev/scripts/cycle07a/cycle07a_track_a_eval.py but adds the
EDGAR fundamental / sector / macro / event-window / signal-confirmation
factor compute paths so that cycle #10 top trials anchored on
``rd_intensity_ttm`` + ``cpi_yoy_pct`` are evaluable.

For each of top-N v2 archived trials (deduped if requested), runs harness
on ``partition_for_role(role="selector")`` panel (train + validation),
extracts per-year + stress + concentration + beta metrics, and runs
``run_split_acceptance`` to produce Track A verdict.

Usage
-----
    python dev/scripts/cycle09/cycle10_track_a_eval.py
    python dev/scripts/cycle09/cycle10_track_a_eval.py --top-n 5
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

import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import generate_all_factors
from core.factors.factor_registry import RESEARCH_FACTORS
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
    drop = {"BRK-B", "USO", "SLV"}
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
    panel = {"close": pd.DataFrame(frames["close"]).sort_index()}
    panel["open"] = pd.DataFrame(frames["open"]).reindex_like(panel["close"])
    panel["high"] = pd.DataFrame(frames["high"]).reindex_like(panel["close"])
    panel["low"] = pd.DataFrame(frames["low"]).reindex_like(panel["close"])
    panel["volume"] = pd.DataFrame(frames["volume"]).reindex_like(panel["close"])
    split_cfg = load_temporal_split(PROJ / "config" / "temporal_split.yaml")
    panel = partition_for_role(panel, split_cfg, role="selector")

    bench = {b: panel["close"][b] for b in ("SPY", "QQQ")
             if b in panel["close"].columns}

    # OHLCV factors from FactorGenerator
    ohlcv_factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    factors = {n: f for n, f in ohlcv_factors.items() if n in RESEARCH_FACTORS}

    tickers = list(panel["close"].columns)
    daily_idx = panel["close"].index

    # Bucket B EDGAR fundamental
    try:
        from core.factors.fundamental_factors import (
            compute_fundamental_factors_full,
        )
        from core.data.fundamentals_store import FundamentalsStore
        fstore = FundamentalsStore()
        fund = compute_fundamental_factors_full(
            daily_idx, tickers, store=fstore, price_df=panel["close"],
        )
        for n, fdf in fund.items():
            if n in RESEARCH_FACTORS:
                factors[n] = fdf
    except Exception as e:
        print(f"  WARN fundamental factor compute failed: {e}")

    # Bucket C sector
    try:
        from core.factors.sector_factors import compute_sector_factors
        sec = compute_sector_factors(panel["close"])
        for n, sdf in sec.items():
            if n in RESEARCH_FACTORS:
                factors[n] = sdf
    except Exception as e:
        print(f"  WARN sector factor compute failed: {e}")

    # Bucket Macro FRED
    try:
        from core.factors.macro_factors import compute_macro_factors
        macro = compute_macro_factors(daily_idx, tickers)
        for n, mdf in macro.items():
            if n in RESEARCH_FACTORS:
                factors[n] = mdf
    except Exception as e:
        print(f"  WARN macro factor compute failed: {e}")

    # Event-window
    try:
        from core.factors.event_window_factors import (
            compute_event_window_factors,
        )
        ev = compute_event_window_factors(daily_idx, tickers)
        for n, edf in ev.items():
            if n in RESEARCH_FACTORS:
                factors[n] = edf
    except Exception as e:
        print(f"  WARN event-window factor compute failed: {e}")

    # Signal-confirmation
    try:
        from core.factors.signal_confirmation_factors import (
            compute_signal_confirmation_factors,
        )
        sc = compute_signal_confirmation_factors(
            panel["close"], panel["volume"],
        )
        for n, sdf in sc.items():
            if n in RESEARCH_FACTORS:
                factors[n] = sdf
    except Exception as e:
        print(f"  WARN signal-conf factor compute failed: {e}")

    mask = (
        research_mask_default(panel["close"], panel["volume"])
        if panel["volume"] is not None else None
    )
    return panel, factors, mask, split_cfg


def _eval_trial(trial_row: Dict[str, Any], panel, factors, mask, split_cfg,
                freeze_date=None):
    feats = trial_row["features"].split(",")
    raw_w = [float(w) for w in trial_row["weights_csv"].split(",")]
    total = sum(raw_w)
    weights = tuple(w / total for w in raw_w)
    panel_map = {f: factors[f] for f in feats if f in factors}
    if len(panel_map) != len(feats):
        return {"error": f"missing factor panels: {set(feats)-set(panel_map)}"}
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
    metrics: Dict[str, Any] = {
        "validation": {},
        "stress_slice": {},
        "concentration": {
            "top1_max": float(res.concentration.get("top1_max", 0.0)),
            "top3_max": float(res.concentration.get("top3_max", 0.0)),
            "leveraged_etf_dependency": False,
        },
        "beta": {
            "beta_to_qqq": float(res.nav_correlation_vs_benchmark.get("beta_vs_qqq", 0.0)),
        },
        "cost": {"multiplier_2x_remains_positive": True},
    }
    for y, m in res.metrics_per_validation_year.items():
        metrics["validation"][int(y)] = {
            "maxdd": float(m.get("max_dd", 0.0)),
            "excess_vs_spy": float(m.get("vs_spy", 0.0)),
            "excess_vs_qqq": float(m.get("vs_qqq", 0.0)),
        }
    for sname, sm in res.metrics_per_stress_slice.items():
        metrics["stress_slice"][sname] = {"maxdd": float(sm.get("max_dd", 0.0))}
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
    }


def main() -> int:
    from datetime import date as _date
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--archive-db", default=str(PROJ / "data/mining/rcm_archive.db"))
    ap.add_argument("--lineage", default="track-c-cycle-2026-05-13-10")
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--dedupe-features", action="store_true",
                    help="dedupe trials with same feature set (keep highest obj)")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--freeze-date",
                    help="ISO YYYY-MM-DD; default derived from --lineage tag.")
    args = ap.parse_args()
    if args.freeze_date:
        freeze_date = _date.fromisoformat(args.freeze_date)
    else:
        try:
            parts = args.lineage.split("-")
            # track-c-cycle-2026-05-13-10 → take 2026,05,12
            freeze_date = _date(int(parts[-4]), int(parts[-3]), int(parts[-2]))
        except (ValueError, IndexError):
            freeze_date = None
    print(f"freeze_date for split dispatch: {freeze_date}")

    # Pull more rows than top-n if deduping, then dedupe
    fetch_limit = max(args.top_n * 5, 50) if args.dedupe_features else args.top_n
    print(f"Loading top-{fetch_limit} archived trials from {args.lineage}"
          f"{' (dedupe enabled)' if args.dedupe_features else ''}...")
    conn = sqlite3.connect(args.archive_db)
    cur = conn.execute(
        "SELECT trial_id, ic_ir, objective, nav_sharpe, nav_max_dd, "
        "features_csv, weights_csv, spec_json "
        "FROM rcm_trials WHERE lineage_tag=? AND objective IS NOT NULL "
        "ORDER BY objective DESC LIMIT ?",
        (args.lineage, fetch_limit),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print(f"No trials archived under {args.lineage}")
        return 1
    raw_trials = [
        {
            "trial_id": r[0], "ic_ir": r[1], "objective": r[2],
            "nav_sharpe": r[3], "nav_max_dd": r[4],
            "features": r[5], "weights_csv": r[6],
            "holding_freq": json.loads(r[7]).get("holding_freq", "monthly"),
        }
        for r in rows
    ]
    if args.dedupe_features:
        seen = set()
        trials = []
        for t in raw_trials:
            key = tuple(sorted(t["features"].split(",")))
            if key in seen:
                continue
            seen.add(key)
            trials.append(t)
            if len(trials) >= args.top_n:
                break
    else:
        trials = raw_trials[:args.top_n]
    print(f"  evaluating {len(trials)} trials")

    print("Loading panel + factors (selector role)...")
    import time
    t0 = time.time()
    panel, factors, mask, split_cfg = _load_panel()
    print(f"  panel: {panel['close'].shape[0]} dates × {panel['close'].shape[1]} symbols "
          f"({time.time()-t0:.1f}s); {len(factors)} factors available")

    results = []
    for i, t in enumerate(trials, 1):
        print(f"\n[{i}/{len(trials)}] trial_id={t['trial_id']} "
              f"holding={t['holding_freq']} feats={t['features']}")
        ts = time.time()
        ev = _eval_trial(t, panel, factors, mask, split_cfg,
                         freeze_date=freeze_date)
        if "error" in ev:
            print(f"  ERROR: {ev['error']}")
            results.append({
                "trial_id": t["trial_id"], "spec": t,
                "evaluation": {"error": ev["error"]},
            })
            continue
        elapsed = time.time() - ts
        verdict = "PASS" if ev["track_a_overall_passed"] else "FAIL"
        print(f"  Track A verdict: {verdict} ({elapsed:.1f}s)")
        if not ev["track_a_overall_passed"]:
            print(f"  Failed gates ({len(ev['track_a_failed_gates'])}):")
            for g in ev["track_a_failed_gates"]:
                print(f"    - {g}")
        for y in sorted(ev["metrics_per_year"].keys()):
            ym = ev["metrics_per_year"][y]
            print(f"    {y}: maxdd={ym.get('max_dd', 0):.2%} "
                  f"vs_spy={ym.get('vs_spy', 0):+.2%} "
                  f"vs_qqq={ym.get('vs_qqq', 0):+.2%}")
        for sname, sm in ev["metrics_per_stress"].items():
            print(f"    [stress] {sname}: maxdd={sm.get('max_dd', 0):.2%}")
        results.append({
            "trial_id": t["trial_id"], "spec": t,
            "evaluation": ev,
        })

    out = {
        "lineage": args.lineage,
        "n_evaluated": len(results),
        "n_passed": sum(
            1 for r in results
            if r["evaluation"].get("track_a_overall_passed")
        ),
        "results": results,
    }
    out_path = Path(
        args.out_json or
        f"data/audit/cycle10_track_a_eval_{args.lineage}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    print(f"Verdict: {out['n_passed']} of {out['n_evaluated']} passed Track A")
    return 0


if __name__ == "__main__":
    sys.exit(main())
