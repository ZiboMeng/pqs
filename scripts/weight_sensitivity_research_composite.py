#!/usr/bin/env python
"""Weight sensitivity of a research composite spec (R19b).

Takes the converged spec and probes how IC_IR responds to:
  1. ±10% perturbation on EACH weight (8 experiments)
  2. Equal-weight replacement (1 experiment)
  3. Leave-one-feature-out (N experiments where N = #features)

Purpose: confirm that the TPE-converged spec is not in a narrow weight
peak (i.e. parameter-robust). Per PRD2 §7.2 robustness criterion:
"small range parameter change should not fully flip result."

Usage:
  python scripts/weight_sensitivity_research_composite.py \
      --study rcm-v1-run-02-lag1 --lineage post-2026-04-24-rcm-v1-lag1
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.base_masks import apply_research_mask, research_mask
from core.factors.factor_generator import (
    compute_forward_returns,
    generate_all_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS
from core.logging_setup import get_logger, setup_logging
from core.mining.research_miner import (
    ResearchCompositeSpec,
    _spearman_ic_per_date,
    build_composite_series,
)

setup_logging()
logger = get_logger("rcm_weight_sensitivity")


def _load_spec(archive_db: str, lineage: str, trial_id: str | None):
    with sqlite3.connect(archive_db) as conn:
        if trial_id:
            row = conn.execute(
                "SELECT trial_id, spec_json FROM rcm_trials WHERE trial_id=?",
                (trial_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT trial_id, spec_json FROM rcm_trials "
                "WHERE lineage_tag=? AND objective IS NOT NULL "
                "ORDER BY objective DESC LIMIT 1",
                (lineage,),
            ).fetchone()
    if not row:
        raise RuntimeError("No spec found")
    parsed = json.loads(row[1])
    return (row[0], parsed)


def _build_panel(cfg, store, horizon: int):
    uni = cfg.universe
    syms = [s for s in dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ) if s not in uni.blacklist and s not in uni.macro_reference]
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close = pd.DataFrame(frames["close"]).sort_index()
    start = cfg.backtest.start_date or "2007-01-02"
    close = close[close.index >= pd.Timestamp(start)]

    def _df(col):
        if not frames[col]:
            return None
        return pd.DataFrame(frames[col]).reindex_like(close)

    volume = _df("volume")
    open_df = _df("open")
    high_df = _df("high")
    low_df = _df("low")
    benchmark_map = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    factors = generate_all_factors(
        close, volume_df=volume,
        open_df=open_df, high_df=high_df, low_df=low_df,
        benchmark_map=benchmark_map,
    )
    panel_map = {n: f for n, f in factors.items() if n in RESEARCH_FACTORS}
    mask = (
        research_mask(close, volume, min_price=5.0, min_usd=20e6, window=20)
        if volume is not None else None
    )
    fwd = compute_forward_returns(close, horizons=[horizon], mode="cc")[horizon]
    return panel_map, fwd, mask


def _eval_ic(features, weights, panel_map, fwd, mask, horizon, lag):
    # Normalize weights to sum to 1 (composite should sum to 1)
    total = sum(weights)
    if total <= 0:
        return None
    weights = [w / total for w in weights]
    spec = ResearchCompositeSpec(
        features=tuple(features),
        weights=tuple(weights),
        family_counts={"A": 1, "B": 1, "C": 1},  # dummy; only for construction
    )
    composite = build_composite_series(spec, panel_map)
    if lag > 0:
        composite = composite.shift(lag)
    if mask is not None:
        composite = apply_research_mask(composite, mask)
    ic = _spearman_ic_per_date(composite, fwd)
    if len(ic) == 0:
        return {"ic_mean": None, "ic_std": None, "ic_ir": None, "n_dates": 0}
    ic_mean = float(ic.mean())
    ic_std = float(ic.std()) if len(ic) > 1 else float("nan")
    ic_ir = (ic_mean / ic_std * np.sqrt(252 / horizon)
             if ic_std and np.isfinite(ic_std) and ic_std > 0 else float("nan"))
    return {
        "ic_mean": ic_mean, "ic_std": ic_std, "ic_ir": ic_ir,
        "n_dates": int(len(ic)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--lineage", default="post-2026-04-24-rcm-v1-lag1")
    parser.add_argument("--trial-id", default=None)
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--lag", type=int, default=1)
    parser.add_argument("--perturbation", type=float, default=0.10)
    parser.add_argument("--archive-db", default="data/mining/rcm_archive.db")
    parser.add_argument("--out-dir", default="data/ml/research_miner")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    trial_id, spec_dict = _load_spec(args.archive_db, args.lineage, args.trial_id)
    features = spec_dict["features"]
    base_weights = spec_dict["weights"]
    logger.info("Base spec %s:", trial_id)
    for f, w in zip(features, base_weights):
        logger.info("  %s: %+.4f", f, w)

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    panel_map, fwd, mask = _build_panel(cfg, store, args.horizon)

    experiments = []

    # 0: baseline
    b = _eval_ic(features, base_weights, panel_map, fwd, mask,
                 args.horizon, args.lag)
    b["experiment"] = "baseline"
    b["perturbation"] = None
    experiments.append(b)

    # 1: ±perturbation on each weight
    for i, f in enumerate(features):
        for sign in (+1, -1):
            new_w = list(base_weights)
            new_w[i] = max(0.0, new_w[i] * (1 + sign * args.perturbation))
            r = _eval_ic(features, new_w, panel_map, fwd, mask,
                         args.horizon, args.lag)
            r["experiment"] = f"perturb_{f}_{'+' if sign>0 else '-'}{int(args.perturbation*100)}%"
            r["perturbation"] = {"feature": f, "sign": sign,
                                 "pct": args.perturbation}
            experiments.append(r)

    # 2: equal weights
    eq_w = [1.0 / len(features)] * len(features)
    r = _eval_ic(features, eq_w, panel_map, fwd, mask, args.horizon, args.lag)
    r["experiment"] = "equal_weights"
    r["perturbation"] = None
    experiments.append(r)

    # 3: leave-one-out
    for i, f in enumerate(features):
        sub_feats = features[:i] + features[i+1:]
        sub_w = base_weights[:i] + base_weights[i+1:]
        r = _eval_ic(sub_feats, sub_w, panel_map, fwd, mask,
                     args.horizon, args.lag)
        r["experiment"] = f"drop_{f}"
        r["perturbation"] = {"dropped": f}
        experiments.append(r)

    # Summary
    base_ir = b["ic_ir"]
    base_ic = b["ic_mean"]
    irs = [e["ic_ir"] for e in experiments
           if e["ic_ir"] is not None and np.isfinite(e["ic_ir"])]
    sens_summary = {
        "baseline_ic_ir": base_ir,
        "baseline_ic_mean": base_ic,
        "n_experiments": len(experiments),
        "ir_min": float(min(irs)) if irs else None,
        "ir_max": float(max(irs)) if irs else None,
        "ir_std": float(np.std(irs)) if irs else None,
        "experiments": experiments,
    }

    out_root = Path(args.out_dir) / args.study / "acceptance"
    out_root.mkdir(parents=True, exist_ok=True)
    out_file = out_root / f"weight_sensitivity_{trial_id}.json"
    out_file.write_text(json.dumps(sens_summary, indent=2, default=str))
    logger.info("Sensitivity artifact: %s", out_file)

    print("=" * 70)
    print(f"Weight Sensitivity — {args.study} / trial {trial_id}")
    print("=" * 70)
    print(f"\nBaseline: IC_mean={base_ic:+.4f}  IR={base_ir:+.4f}")
    print(f"\n{'Experiment':45s} {'IC_mean':>10s} {'IR':>10s} {'ΔIR':>10s}")
    print("-" * 80)
    for e in experiments:
        ir = e["ic_ir"]
        ic_m = e["ic_mean"]
        delta = ir - base_ir if ir is not None and base_ir is not None else None
        ir_s = f"{ir:+.4f}" if ir is not None and np.isfinite(ir) else "nan"
        ic_s = f"{ic_m:+.4f}" if ic_m is not None and np.isfinite(ic_m) else "nan"
        d_s = f"{delta:+.4f}" if delta is not None and np.isfinite(delta) else "nan"
        print(f"{e['experiment']:45s} {ic_s:>10s} {ir_s:>10s} {d_s:>10s}")
    print(f"\nIR range across {len(experiments)} experiments: "
          f"[{sens_summary['ir_min']:+.4f}, {sens_summary['ir_max']:+.4f}] "
          f"(std={sens_summary['ir_std']:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
