#!/usr/bin/env python
"""PRD #4 P4.2 walk-forward retraining driver (Round 32, audit priority 3).

Single-split R28-R29 surfaced overfit (train F1 0.58 → val F1 0.42;
train precision 0.80 → val precision 0.39, -60% drop). PRD #4 P4.2
explicitly required "Walk-forward retraining cadence (e.g. quarterly)"
but single-split was shipped first.

Round 32 closes that gap: rolling 5y train / 1y val folds, per-fold
metrics + aggregate mean. If mean precision(VETO) ≥ 0.55, P4.2 AC
PASSES; otherwise the FAIL is a model/feature issue not a luck issue
and the next lever is hyperparam search.

Per fold:
  - Stage 1 rank from cycle06 3-feature zscore-rank (on train+val slice)
  - top-decile mask
  - binary sign labels (forward 21d > 0)
  - assemble X, y on top-decile cells (raw context values per R28
    R3 catch — Family S regime factors are broadcast)
  - train Logistic OR XGB on train slice
  - eval on held-out val slice

Discipline:
  - strict-chronological (no interleaved selector)
  - sealed-2026 guard via WalkForwardConfig
  - non-blanket per-fold failures (per `feedback_no_blanket_failure_verdict`)
  - per-fold metrics aggregated; mean rank-IC/IR semantic borrowed

Usage:
  python dev/scripts/ml/walk_forward_sign_classifier.py
  python dev/scripts/ml/walk_forward_sign_classifier.py --model xgb \
      --start-year 2010 --end-year 2024 --train-window 5 --val-window 1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.factors.base_masks import research_mask_default  # noqa: E402
from core.factors.factor_generator import generate_all_factors  # noqa: E402
from core.research.ml.context_features import extract_feature_bundle  # noqa: E402
from core.research.ml.labels import (  # noqa: E402
    apply_tradeable_mask,
    assert_bar_integrity,
    assert_no_sealed_year,
)
from core.research.ml.pipeline import (  # noqa: E402
    DEFAULT_SEALED_YEARS,
    WalkForwardConfig,
    iter_folds,
)
from core.research.ml.rank_model import _cross_sectional_rank, _cross_sectional_standardize  # noqa: E402
from core.research.ml.sign_classifier import (  # noqa: E402
    LogisticRegressionSignClassifier,
    XGBSignClassifier,
    compute_binary_sign_labels,
    select_top_decile_mask,
)

CYCLE06_FEATURES: Tuple[str, ...] = (
    "drawup_from_252d_low", "trend_tstat_20d", "ret_2d",
)


def _load_panel():
    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)))
    drop = {"BRK-B", "USO", "SLV"}
    syms = [s for s in syms if s not in uni.blacklist
            and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in syms:
            syms.append(b)
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.load(sym, freq="1d", adjusted=True,
                        adjusted_total_return=True, fallback="local")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames["close"][sym] = df["close"]
        for col in ("open", "high", "low", "volume"):
            if col in df.columns:
                frames[col][sym] = df[col]
    close = pd.DataFrame(frames["close"]).sort_index()
    panel = {
        "close": close,
        "open": pd.DataFrame(frames["open"]).reindex_like(close),
        "high": pd.DataFrame(frames["high"]).reindex_like(close),
        "low": pd.DataFrame(frames["low"]).reindex_like(close),
        "volume": pd.DataFrame(frames["volume"]).reindex_like(close),
    }
    bench = {b: close[b] for b in ("SPY", "QQQ") if b in close.columns}
    factors = generate_all_factors(
        close, volume_df=panel["volume"], open_df=panel["open"],
        high_df=panel["high"], low_df=panel["low"], benchmark_map=bench)
    mask = (research_mask_default(close, panel["volume"])
            if panel["volume"] is not None else None)
    return panel, factors, mask


def _build_stage1_rank(factors, feature_names):
    standardized = [_cross_sectional_standardize(factors[n]) for n in feature_names]
    avg = sum(standardized) / len(standardized)
    return _cross_sectional_rank(avg)


def _assemble_xy(
    stage1_rank: pd.DataFrame, sign_labels: pd.DataFrame,
    context: Dict[str, pd.DataFrame], decile: float,
    start: pd.Timestamp, end: pd.Timestamp,
) -> Tuple[np.ndarray, np.ndarray]:
    """Assemble (X, y) from top-decile cells within [start, end]."""
    rank_slice = stage1_rank.loc[(stage1_rank.index >= start)
                                 & (stage1_rank.index <= end)]
    label_slice = sign_labels.loc[(sign_labels.index >= start)
                                  & (sign_labels.index <= end)]
    mask = select_top_decile_mask(rank_slice, decile=decile)
    ctx_names = sorted(context.keys())
    X_rows, y_rows = [], []
    for date in rank_slice.index:
        row_mask = mask.loc[date]
        eligible = row_mask[row_mask].index
        for sym in eligible:
            if sym not in label_slice.columns or date not in label_slice.index:
                continue
            y = label_slice.at[date, sym]
            if pd.isna(y):
                continue
            vec = [rank_slice.at[date, sym]]
            ok = True
            for cn in ctx_names:
                p = context[cn]
                if date not in p.index or sym not in p.columns:
                    ok = False
                    break
                v = p.at[date, sym]
                if pd.isna(v):
                    ok = False
                    break
                vec.append(v)
            if ok:
                X_rows.append(vec)
                y_rows.append(int(y))
    return np.asarray(X_rows), np.asarray(y_rows)


def _classifier_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    if len(y_true) == 0:
        return {"n": 0, "accuracy": float("nan"),
                "precision_veto": float("nan"),
                "recall_veto": float("nan"),
                "f1_veto": float("nan"),
                "veto_count": 0}
    acc = float((y_true == y_pred).mean())
    veto_pred = (y_pred == 0)
    veto_true = (y_true == 0)
    tn = int((veto_pred & veto_true).sum())
    fp = int((veto_pred & ~veto_true).sum())
    precision_veto = tn / max(tn + fp, 1)
    recall_veto = tn / max(int(veto_true.sum()), 1)
    f1_veto = (2 * precision_veto * recall_veto
               / max(precision_veto + recall_veto, 1e-9))
    return {
        "n": int(len(y_true)),
        "accuracy": acc,
        "precision_veto": precision_veto,
        "recall_veto": recall_veto,
        "f1_veto": f1_veto,
        "veto_count": int(veto_pred.sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PRD #4 P4.2 walk-forward sign classifier retraining")
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-year", type=int, default=2024,
                        help="< 2026 (sealed guard)")
    parser.add_argument("--train-window", type=int, default=5)
    parser.add_argument("--val-window", type=int, default=1)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--horizon-days", type=int, default=21)
    parser.add_argument("--decile", type=float, default=0.9)
    parser.add_argument("--model", default="xgb",
                        choices=["logistic", "xgb"])
    parser.add_argument("--context-bundle", default="regime_state")
    parser.add_argument("--out-dir", default="data/audit")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"=== PRD #4 P4.2 walk-forward sign classifier ===")
    print(f"range={args.start_year}-{args.end_year}  "
          f"train={args.train_window}y val={args.val_window}y step={args.step}y")
    print(f"horizon={args.horizon_days}d  decile={args.decile}  "
          f"model={args.model}  context={args.context_bundle}")

    print(f"\n[1/4] Load panel + factors + mask...")
    panel, factors, mask = _load_panel()
    print(f"  close {panel['close'].shape}  factors {len(factors)}")

    # Slice to backtest year range BEFORE smoke
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
    print(f"  sliced + smoke ✅")

    print(f"\n[2/4] Build Stage 1 rank + binary labels + context bundle...")
    stage1_rank = _build_stage1_rank(factors, CYCLE06_FEATURES)
    sign_labels = compute_binary_sign_labels(panel["close"], args.horizon_days)
    sign_labels = apply_tradeable_mask(sign_labels, mask)
    context = (extract_feature_bundle(factors, args.context_bundle)
               if args.context_bundle != "NONE" else {})
    print(f"  stage1_rank {stage1_rank.shape}  labels non-NaN "
          f"{int(sign_labels.notna().sum().sum())}  context {len(context)} bundles")

    print(f"\n[3/4] Walk-forward train+eval per fold...")
    cfg = WalkForwardConfig(
        start_year=args.start_year, end_year=args.end_year,
        train_window_years=args.train_window,
        val_window_years=args.val_window, step_years=args.step,
        embargo_days=args.horizon_days)  # P1 §8.2: purge+embargo = horizon
    per_fold_metrics: List[Dict[str, Any]] = []
    for fold in iter_folds(cfg, DEFAULT_SEALED_YEARS):
        X_train, y_train = _assemble_xy(
            stage1_rank, sign_labels, context, args.decile,
            fold.train_start, fold.train_end)
        X_val, y_val = _assemble_xy(
            stage1_rank, sign_labels, context, args.decile,
            fold.val_start, fold.val_end)
        fold_record: Dict[str, Any] = {
            "fold_idx": fold.fold_idx,
            "train": f"{fold.train_start.date()}..{fold.train_end.date()}",
            "val": f"{fold.val_start.date()}..{fold.val_end.date()}",
            "n_train": int(len(y_train)), "n_val": int(len(y_val)),
        }
        if len(y_train) == 0 or len(y_val) == 0:
            fold_record["error"] = "zero observations"
            fold_record["train_metrics"] = None
            fold_record["val_metrics"] = None
            per_fold_metrics.append(fold_record)
            print(f"  fold {fold.fold_idx}: SKIP (zero obs)")
            continue
        try:
            if args.model == "logistic":
                model = LogisticRegressionSignClassifier()
            else:
                model = XGBSignClassifier(
                    n_estimators=100, max_depth=4,
                    learning_rate=0.1, random_state=args.seed)
            model.fit(X_train, y_train)
            pred_train = model.predict(X_train)
            pred_val = model.predict(X_val)
            train_m = _classifier_metrics(y_train, pred_train)
            val_m = _classifier_metrics(y_val, pred_val)
        except Exception as exc:
            fold_record["error"] = f"{type(exc).__name__}: {exc}"
            fold_record["train_metrics"] = None
            fold_record["val_metrics"] = None
            per_fold_metrics.append(fold_record)
            print(f"  fold {fold.fold_idx}: ERROR {exc}")
            continue
        fold_record["error"] = None
        fold_record["train_metrics"] = train_m
        fold_record["val_metrics"] = val_m
        per_fold_metrics.append(fold_record)
        print(f"  fold {fold.fold_idx} ({fold_record['train']} → "
              f"{fold_record['val']}): "
              f"train F1={train_m['f1_veto']:.3f} prec={train_m['precision_veto']:.3f} | "
              f"val F1={val_m['f1_veto']:.3f} prec={val_m['precision_veto']:.3f}")

    print(f"\n[4/4] Aggregate verdict")
    ok_folds = [f for f in per_fold_metrics if f["error"] is None]
    if not ok_folds:
        print(f"  ❌ no successful folds")
        return 1
    val_f1 = np.array([f["val_metrics"]["f1_veto"] for f in ok_folds])
    val_prec = np.array([f["val_metrics"]["precision_veto"] for f in ok_folds])
    val_n = np.array([f["val_metrics"]["n"] for f in ok_folds])
    mean_f1 = float(np.mean(val_f1))
    mean_prec = float(np.mean(val_prec))
    weighted_f1 = float(np.average(val_f1, weights=val_n))
    weighted_prec = float(np.average(val_prec, weights=val_n))
    print(f"  successful folds: {len(ok_folds)}/{len(per_fold_metrics)}")
    print(f"  mean val F1(VETO):        {mean_f1:.4f}")
    print(f"  mean val precision(VETO): {mean_prec:.4f}")
    print(f"  weighted val F1(VETO):    {weighted_f1:.4f}")
    print(f"  weighted val precision:   {weighted_prec:.4f}")
    p42_ac_f1 = mean_f1 > 0.0
    p42_ac_prec = mean_prec > 0.55
    print(f"  P4.2 AC F1(VETO) > 0:          {'✅ PASS' if p42_ac_f1 else '❌ FAIL'}")
    print(f"  P4.2 AC Precision(VETO) > 0.55:{'✅ PASS' if p42_ac_prec else '❌ FAIL'}")

    out_dir = PROJ / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "config": vars(args),
        "per_fold": per_fold_metrics,
        "aggregate": {
            "n_successful_folds": len(ok_folds),
            "n_total_folds": len(per_fold_metrics),
            "mean_val_f1_veto": mean_f1,
            "mean_val_precision_veto": mean_prec,
            "weighted_val_f1_veto": weighted_f1,
            "weighted_val_precision_veto": weighted_prec,
            "p42_ac_f1_pass": p42_ac_f1,
            "p42_ac_precision_pass": p42_ac_prec,
        },
        "trained_at_utc": trained_at,
    }
    out_path = out_dir / f"r32_walkforward_sign_{args.model}_{trained_at}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nsummary → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
