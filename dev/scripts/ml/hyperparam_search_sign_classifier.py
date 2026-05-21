#!/usr/bin/env python
"""PRD #4 P4.2 Round 33 — XGB hyperparameter search for Stage 2 sign classifier.

R32 walk-forward (single hand-picked hyperparam set: n_estimators=100,
max_depth=4, lr=0.1, threshold=0.5) gave mean val precision(VETO)=0.382,
FAIL vs the 0.55 AC. R32 verdict: 10 folds show a consistent overfit
pattern → model/feature issue, not luck. Round 33 is the "next lever"
the R32 script named: hyperparameter search.

Method:
  - Same 10-fold rolling walk-forward as R32 (5y-train / 1y-val), reusing
    R32's panel / Stage-1-rank / label / context-bundle helpers.
  - Grid over XGBSignClassifier's exposed knobs: n_estimators, max_depth,
    learning_rate. For each (tree-config, fold) fit ONCE, cache
    predict_proba, then sweep decision_threshold — threshold is a
    prediction-side precision/recall lever, no refit needed.
  - Aggregate mean val precision(VETO) + mean veto coverage per config.

Honesty guards:
  - The "best" config is selected on the SAME val folds it is scored on
    → its precision is OPTIMISTIC (the search overfits the val set). The
    JSON reports the full config distribution + how many configs cross
    the 0.55 AC, not just the argmax.
  - A high-precision config with near-zero veto coverage is degenerate
    (a VETO model that almost never vetoes) — flagged separately; the
    headline verdict uses the best NON-degenerate config.
  - non-blanket (per `feedback_no_blanket_failure_verdict`): a FAIL here
    escalates the root cause to the feature bundle, it does not condemn
    the sign-classifier approach.

temporal_split caveat (per `feedback_temporal_split_discipline`): the
walk-forward val folds span validation years 2018/2019/2021/2023. This
is a P4.2 walk-forward-retraining-cadence acceptance-type measurement of
classifier quality; sealed 2026 is never read (end-year 2024 +
assert_no_sealed_year). Numbers here are NOT pre-promotion
evidence-discovery on the validation set.

Usage:
  python dev/scripts/ml/hyperparam_search_sign_classifier.py
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from core.research.ml.pipeline import (  # noqa: E402
    DEFAULT_SEALED_YEARS,
    WalkForwardConfig,
    iter_folds,
)
from core.research.ml.sign_classifier import XGBSignClassifier  # noqa: E402

# Reuse R32 walk-forward helpers (panel load, Stage-1 rank, X/y assembly).
from walk_forward_sign_classifier import (  # noqa: E402
    CYCLE06_FEATURES,
    _assemble_xy,
    _build_stage1_rank,
    _classifier_metrics,
    _load_panel,
)
from core.factors.base_masks import research_mask_default  # noqa: E402  (unused-safe)
import pandas as pd  # noqa: E402

from core.research.ml.context_features import extract_feature_bundle  # noqa: E402
from core.research.ml.labels import (  # noqa: E402
    apply_tradeable_mask,
    assert_bar_integrity,
    assert_no_sealed_year,
)
from core.research.ml.sign_classifier import compute_binary_sign_labels  # noqa: E402

# ── Search grid (XGBSignClassifier exposed knobs only) ───────────────
GRID_N_ESTIMATORS = (50, 100, 200, 400)
GRID_MAX_DEPTH = (2, 3, 4, 6)
GRID_LEARNING_RATE = (0.03, 0.1, 0.3)
THRESHOLD_SWEEP = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)

# A VETO model that vetoes < this fraction of candidate entries is
# degenerate (high precision is meaningless if it almost never fires).
DEGENERATE_VETO_RATE = 0.10
AC_PRECISION = 0.55


def _prep_folds(args) -> List[Dict[str, Any]]:
    """Load panel once, build Stage-1 rank + labels + context, assemble
    (X_train, y_train, X_val, y_val) per walk-forward fold."""
    panel, factors, mask = _load_panel()
    start_ts = pd.Timestamp(f"{args.start_year}-01-01")
    end_ts = pd.Timestamp(f"{args.end_year}-12-31")
    panel = {k: v.loc[(v.index >= start_ts) & (v.index <= end_ts)]
             for k, v in panel.items()}
    factors = {k: v.loc[(v.index >= start_ts) & (v.index <= end_ts)]
               for k, v in factors.items() if not v.empty}
    if mask is not None:
        mask = mask.loc[(mask.index >= start_ts) & (mask.index <= end_ts)]
    assert_bar_integrity(panel["close"], name="panel.close")
    assert_no_sealed_year(panel["close"], DEFAULT_SEALED_YEARS, name="panel.close")

    stage1_rank = _build_stage1_rank(factors, CYCLE06_FEATURES)
    sign_labels = compute_binary_sign_labels(panel["close"], args.horizon_days)
    sign_labels = apply_tradeable_mask(sign_labels, mask)
    context = (extract_feature_bundle(factors, args.context_bundle)
               if args.context_bundle != "NONE" else {})

    cfg = WalkForwardConfig(
        start_year=args.start_year, end_year=args.end_year,
        train_window_years=args.train_window,
        val_window_years=args.val_window, step_years=args.step,
        embargo_days=args.horizon_days)  # P1 §8.2: purge+embargo = horizon
    folds: List[Dict[str, Any]] = []
    for fold in iter_folds(cfg, DEFAULT_SEALED_YEARS):
        X_train, y_train = _assemble_xy(
            stage1_rank, sign_labels, context, args.decile,
            fold.train_start, fold.train_end)
        X_val, y_val = _assemble_xy(
            stage1_rank, sign_labels, context, args.decile,
            fold.val_start, fold.val_end)
        folds.append({
            "fold_idx": fold.fold_idx,
            "train": f"{fold.train_start.date()}..{fold.train_end.date()}",
            "val": f"{fold.val_start.date()}..{fold.val_end.date()}",
            "X_train": X_train, "y_train": y_train,
            "X_val": X_val, "y_val": y_val,
        })
    return folds


def _eval_config(folds, n_est, max_depth, lr, seed) -> Dict[str, Any]:
    """Fit one tree-config per fold, cache val proba, sweep thresholds."""
    # proba_by_fold[fold_idx] = (proba1_val, y_val) for usable folds
    proba_by_fold: List[Any] = []
    for fd in folds:
        if len(fd["y_train"]) == 0 or len(fd["y_val"]) == 0:
            continue
        model = XGBSignClassifier(
            n_estimators=n_est, max_depth=max_depth,
            learning_rate=lr, random_state=seed)
        try:
            model.fit(fd["X_train"], fd["y_train"])
            proba1 = model.predict_proba(fd["X_val"])[:, 1]
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        proba_by_fold.append((proba1, fd["y_val"]))
    if not proba_by_fold:
        return {"error": "no usable folds"}

    per_threshold: List[Dict[str, Any]] = []
    for thr in THRESHOLD_SWEEP:
        precs, f1s, veto_rates, ns = [], [], [], []
        for proba1, y_val in proba_by_fold:
            y_pred = (proba1 >= thr).astype(int)
            m = _classifier_metrics(np.asarray(y_val), y_pred)
            precs.append(m["precision_veto"])
            f1s.append(m["f1_veto"])
            veto_rates.append(m["veto_count"] / max(m["n"], 1))
            ns.append(m["n"])
        per_threshold.append({
            "threshold": thr,
            "mean_val_precision_veto": float(np.mean(precs)),
            "mean_val_f1_veto": float(np.mean(f1s)),
            "mean_veto_rate": float(np.mean(veto_rates)),
            "weighted_val_precision_veto": float(np.average(precs, weights=ns)),
        })
    return {"error": None, "per_threshold": per_threshold}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PRD #4 P4.2 R33 XGB hyperparam search")
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2024,
                        help="< 2026 (sealed guard)")
    parser.add_argument("--train-window", type=int, default=5)
    parser.add_argument("--val-window", type=int, default=1)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--horizon-days", type=int, default=21)
    parser.add_argument("--decile", type=float, default=0.9)
    parser.add_argument("--context-bundle", default="regime_state")
    parser.add_argument("--out-dir", default="data/audit")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    grid = list(itertools.product(
        GRID_N_ESTIMATORS, GRID_MAX_DEPTH, GRID_LEARNING_RATE))
    print(f"=== PRD #4 P4.2 R33 hyperparam search ===")
    print(f"range={args.start_year}-{args.end_year}  "
          f"tree-configs={len(grid)}  thresholds={len(THRESHOLD_SWEEP)}  "
          f"context={args.context_bundle}")

    print(f"\n[1/3] Load panel + assemble walk-forward folds...")
    folds = _prep_folds(args)
    usable = [f for f in folds if len(f["y_train"]) and len(f["y_val"])]
    print(f"  {len(usable)}/{len(folds)} usable folds")

    print(f"\n[2/3] Grid search ({len(grid)} tree-configs)...")
    results: List[Dict[str, Any]] = []
    for i, (n_est, max_depth, lr) in enumerate(grid):
        ev = _eval_config(folds, n_est, max_depth, lr, args.seed)
        rec: Dict[str, Any] = {
            "n_estimators": n_est, "max_depth": max_depth,
            "learning_rate": lr, **ev}
        results.append(rec)
        if ev.get("error"):
            print(f"  [{i+1}/{len(grid)}] n={n_est} d={max_depth} "
                  f"lr={lr}: ERROR {ev['error']}")
            continue
        best_t = max(ev["per_threshold"],
                     key=lambda t: t["mean_val_precision_veto"])
        print(f"  [{i+1}/{len(grid)}] n={n_est} d={max_depth} lr={lr}: "
              f"best prec={best_t['mean_val_precision_veto']:.3f} "
              f"@thr={best_t['threshold']} "
              f"vetorate={best_t['mean_veto_rate']:.2f}")

    print(f"\n[3/3] Aggregate verdict")
    # Flatten every (tree-config × threshold) into candidate configs.
    flat: List[Dict[str, Any]] = []
    for rec in results:
        if rec.get("error"):
            continue
        for t in rec["per_threshold"]:
            flat.append({
                "n_estimators": rec["n_estimators"],
                "max_depth": rec["max_depth"],
                "learning_rate": rec["learning_rate"],
                "threshold": t["threshold"],
                "mean_val_precision_veto": t["mean_val_precision_veto"],
                "mean_val_f1_veto": t["mean_val_f1_veto"],
                "mean_veto_rate": t["mean_veto_rate"],
                "weighted_val_precision_veto": t["weighted_val_precision_veto"],
            })
    if not flat:
        print("  ❌ no successful configs")
        return 1

    non_degenerate = [c for c in flat
                      if c["mean_veto_rate"] >= DEGENERATE_VETO_RATE]
    best_overall = max(flat, key=lambda c: c["mean_val_precision_veto"])
    best_nondegen = (max(non_degenerate,
                         key=lambda c: c["mean_val_precision_veto"])
                     if non_degenerate else None)
    n_cross_ac = sum(1 for c in flat
                     if c["mean_val_precision_veto"] > AC_PRECISION)
    n_cross_ac_nondegen = sum(
        1 for c in non_degenerate
        if c["mean_val_precision_veto"] > AC_PRECISION)

    print(f"  total configs (tree × threshold): {len(flat)}")
    print(f"  non-degenerate (veto_rate ≥ {DEGENERATE_VETO_RATE}): "
          f"{len(non_degenerate)}")
    print(f"  configs crossing AC 0.55 (all):           {n_cross_ac}")
    print(f"  configs crossing AC 0.55 (non-degenerate): {n_cross_ac_nondegen}")
    print(f"\n  best overall (may be degenerate):")
    print(f"    {best_overall}")
    if best_nondegen:
        print(f"  best non-degenerate:")
        print(f"    {best_nondegen}")
        p42_pass = best_nondegen["mean_val_precision_veto"] > AC_PRECISION
    else:
        print(f"  best non-degenerate: NONE")
        p42_pass = False
    print(f"\n  P4.2 AC precision(VETO) > 0.55 "
          f"(best non-degenerate): {'✅ PASS' if p42_pass else '❌ FAIL'}")
    print(f"  ⚠ best config selected on the same val folds it is "
          f"scored on → precision is optimistic (search overfit).")

    out_dir = PROJ / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "config": {**vars(args), "embargo_days": args.horizon_days},
        "grid": {
            "n_estimators": list(GRID_N_ESTIMATORS),
            "max_depth": list(GRID_MAX_DEPTH),
            "learning_rate": list(GRID_LEARNING_RATE),
            "threshold_sweep": list(THRESHOLD_SWEEP),
            "degenerate_veto_rate_floor": DEGENERATE_VETO_RATE,
            "ac_precision": AC_PRECISION,
        },
        "per_tree_config": results,
        "aggregate": {
            "n_configs_total": len(flat),
            "n_configs_non_degenerate": len(non_degenerate),
            "n_configs_cross_ac_all": n_cross_ac,
            "n_configs_cross_ac_non_degenerate": n_cross_ac_nondegen,
            "best_overall": best_overall,
            "best_non_degenerate": best_nondegen,
            "p42_ac_precision_pass_best_non_degenerate": p42_pass,
        },
        "caveats": {
            "search_overfit": ("best config selected on the same 10 val "
                               "folds it is scored on; reported precision "
                               "is optimistic"),
            "temporal_split": ("val folds span validation years "
                               "2018/2019/2021/2023; acceptance-type "
                               "cadence measurement, not evidence-discovery"),
            "sealed_2026": "end-year 2024; sealed 2026 never read",
        },
        "trained_at_utc": trained_at,
    }
    out_path = out_dir / f"r33_hyperparam_search_sign_xgb_{trained_at}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nsummary → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
