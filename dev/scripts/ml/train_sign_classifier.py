#!/usr/bin/env python
"""PRD #4 P4.5 sub-step A — train Stage 2 sign classifier on Stage 1 output.

Two-stage pipeline:
  Stage 1 = cycle06 3-feature composite rank (via in-driver z-score then
    average across features); selects top-decile entry-eligible cells
  Stage 2 = sign classifier on top-decile {date, sym} pairs;
    X = (stage1_rank, [context features...]); y = (forward_return > 0)

Default uses cycle06 3 features (drawup_from_252d_low / trend_tstat_20d /
ret_2d) since the R25 driver already validated these produce rank-IC > 0.02
on real data. Stage 2 horizon defaults to 21 (monthly) per PRD #4 P4.2 text
(differs from Stage 1 horizon=5 — Stage 2's "winner ≥ 0 over 21d" is the
PRD-canonical target).

Discipline:
  - bar-integrity smoke before training
  - sealed-year guard (2026 off-limits)
  - strict-chronological train/val split (no walk-forward in this driver —
    sub-step A ships ONE training set / ONE val set; walk-forward
    retraining cadence is sub-step B P4.5)
  - §9.0: trained classifier.predict() returns {0, 1} only

Output:
  - data/ml/sign_<lineage>.pkl (pickled classifier)
  - data/ml/sign_<lineage>.json (metadata, output_type="sign")

Usage:
  python dev/scripts/ml/train_sign_classifier.py
  python dev/scripts/ml/train_sign_classifier.py --model xgb --horizon-days 21
  python dev/scripts/ml/train_sign_classifier.py --train-end 2022 --val-end 2024
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Tuple

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core.config.loader import load_config  # noqa: E402
from core.data.bar_store import BarStore  # noqa: E402
from core.factors.base_masks import research_mask_default  # noqa: E402
from core.factors.factor_generator import generate_all_factors  # noqa: E402
from core.research.ml.artifact import (  # noqa: E402
    ArtifactMetadata,
    ModelArtifact,
    SCHEMA_VERSION,
    compute_lineage_tag,
    compute_spec_id,
    save_artifact,
)
from core.research.ml.context_features import extract_feature_bundle  # noqa: E402
from core.research.ml.labels import (  # noqa: E402
    apply_tradeable_mask,
    assert_bar_integrity,
    assert_no_sealed_year,
)
from core.research.ml.pipeline import DEFAULT_SEALED_YEARS  # noqa: E402
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


def _load_panel_and_factors(
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], pd.DataFrame]:
    """Reuse R25 cycle06 pattern (BarStore adjusted=True ATR)."""
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
    frames: Dict[str, Dict[str, pd.Series]] = {
        k: {} for k in ("close", "open", "high", "low", "volume")}
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
        close, volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    mask = (research_mask_default(close, panel["volume"])
            if panel["volume"] is not None else None)
    return panel, factors, mask


def _build_stage1_rank(
    factors: Dict[str, pd.DataFrame], feature_names: Tuple[str, ...],
) -> pd.DataFrame:
    """Stage 1 = z-score each feature cross-sectionally, equal-weight
    average, then percentile rank. Matches cycle06 spec semantics
    (`transforms.standardization: zscore_cross_sectional`).
    """
    standardized = [
        _cross_sectional_standardize(factors[n]) for n in feature_names
    ]
    avg = sum(standardized) / len(standardized)
    return _cross_sectional_rank(avg)


def _build_xy_for_stage2(
    stage1_rank: pd.DataFrame,
    sign_labels: pd.DataFrame,
    context: Dict[str, pd.DataFrame],
    decile: float = 0.9,
) -> Tuple[np.ndarray, np.ndarray, Tuple[str, ...]]:
    """Assemble X (n_obs × n_features) and y (n_obs,) from top-decile cells.

    Feature vector per (date, sym):
        [stage1_rank, context_feat_1, context_feat_2, ...]
    Label: 0/1 from sign_labels (forward return > 0).

    Only includes cells where Stage 1 says top-decile AND label is non-NaN.

    Context features are taken as RAW VALUES (no cross-sectional
    standardize). Family S regime factors are broadcast (same value
    across all symbols per date) → cross-sectional std = 0 → zscore = NaN
    → ALL cells drop. The classifier (Logistic / XGB) handles its own
    feature scaling. R28 R3 catch.
    """
    mask = select_top_decile_mask(stage1_rank, decile=decile)
    feature_names = ("stage1_rank",) + tuple(sorted(context.keys()))
    X_rows: list = []
    y_rows: list = []
    for date in stage1_rank.index:
        row_mask = mask.loc[date]
        eligible_syms = row_mask[row_mask].index
        for sym in eligible_syms:
            if sym not in sign_labels.columns or date not in sign_labels.index:
                continue
            y_val = sign_labels.at[date, sym]
            if pd.isna(y_val):
                continue
            x_vec: list = [stage1_rank.at[date, sym]]
            ok = True
            for ctx_name in feature_names[1:]:
                if (date not in context[ctx_name].index
                        or sym not in context[ctx_name].columns):
                    ok = False
                    break
                v = context[ctx_name].at[date, sym]
                if pd.isna(v):
                    ok = False
                    break
                x_vec.append(v)
            if ok:
                X_rows.append(x_vec)
                y_rows.append(int(y_val))
    return np.asarray(X_rows), np.asarray(y_rows), feature_names


def _print_classifier_metrics(name: str, y_true: np.ndarray, y_pred: np.ndarray):
    if len(y_true) == 0:
        print(f"  {name}: NO observations")
        return
    acc = float((y_true == y_pred).mean())
    # binary VETO = class 0; NO_VOTE = class 1
    veto_mask = y_pred == 0
    if veto_mask.any():
        # precision(VETO) = P(true label = 0 | predicted = 0)
        # = TN / (TN + FN where pred=0)
        tn = int(((y_true == 0) & (y_pred == 0)).sum())
        fp_in_veto = int(((y_true == 1) & (y_pred == 0)).sum())
        precision_veto = tn / max(tn + fp_in_veto, 1)
        recall_veto = tn / max(int((y_true == 0).sum()), 1)
        f1_veto = (
            2 * precision_veto * recall_veto
            / max(precision_veto + recall_veto, 1e-9)
        )
    else:
        precision_veto = recall_veto = f1_veto = 0.0
    baseline_no_vote_f1 = 0.0  # always-abstain F1(VETO) = 0
    print(f"  {name}:")
    print(f"    n_obs={len(y_true)}  pred_veto_count={int(veto_mask.sum())}")
    print(f"    accuracy={acc:.4f}  prior_class1={(y_true==1).mean():.4f}")
    print(f"    precision(VETO)={precision_veto:.4f}  "
          f"recall(VETO)={recall_veto:.4f}  F1(VETO)={f1_veto:.4f}")
    print(f"    AC: F1(VETO) > baseline 0  → "
          f"{'PASS' if f1_veto > baseline_no_vote_f1 else 'FAIL'}")
    print(f"    AC: precision(VETO) > 0.55 → "
          f"{'PASS' if precision_veto > 0.55 else 'FAIL'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PRD #4 P4.5 sub-step A: train Stage 2 sign classifier",
    )
    parser.add_argument("--horizon-days", type=int, default=21,
                        help="forward-return horizon for sign labels (default 21 "
                             "= monthly per PRD #4 P4.2 default; cycle06 uses "
                             "weekly=5 but P4.2 binding text says 21)")
    parser.add_argument("--decile", type=float, default=0.9,
                        help="Stage 1 top-decile mask threshold")
    parser.add_argument("--train-start", type=int, default=2010)
    parser.add_argument("--train-end", type=int, default=2022)
    parser.add_argument("--val-start", type=int, default=2023)
    parser.add_argument("--val-end", type=int, default=2024)
    parser.add_argument("--model", default="logistic",
                        choices=["logistic", "xgb"])
    parser.add_argument("--context-bundle", default="regime_state",
                        help="context feature bundle name (regime_state / "
                             "drawdown_context / overnight / trend_macro / "
                             "all_context / NONE)")
    parser.add_argument("--save-dir", default="data/ml")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.val_end >= 2026:
        print(f"ERROR: val_end={args.val_end} would touch sealed year 2026",
              file=sys.stderr)
        return 3

    print(f"=== Stage 2 sign classifier training ===")
    print(f"horizon_days={args.horizon_days}  decile={args.decile}  "
          f"train={args.train_start}-{args.train_end}  "
          f"val={args.val_start}-{args.val_end}")
    print(f"model={args.model}  context_bundle={args.context_bundle}")

    print(f"\n[1/6] Loading panel + factors...")
    panel, factors, mask = _load_panel_and_factors()
    print(f"  close: {panel['close'].shape}  factors: {len(factors)}")

    # Slice to train+val range BEFORE smoke (excludes sealed 2026)
    slice_start = pd.Timestamp(f"{args.train_start}-01-01")
    slice_end = pd.Timestamp(f"{args.val_end}-12-31")
    panel = {k: v.loc[(v.index >= slice_start) & (v.index <= slice_end)]
             for k, v in panel.items()}
    factors = {k: v.loc[(v.index >= slice_start) & (v.index <= slice_end)]
               for k, v in factors.items() if not v.empty}
    if mask is not None:
        mask = mask.loc[(mask.index >= slice_start) & (mask.index <= slice_end)]
    print(f"  sliced to {args.train_start}-{args.val_end}: "
          f"close {panel['close'].shape}  factors {len(factors)}")

    print(f"\n[2/6] Bar-integrity + sealed-year smoke...")
    assert_bar_integrity(panel["close"], name="panel.close")
    assert_no_sealed_year(panel["close"], DEFAULT_SEALED_YEARS, name="panel.close")
    print(f"  ✅ ok")

    print(f"\n[3/6] Build Stage 1 rank (cycle06 3-feature equal-weight zscore)...")
    stage1_rank = _build_stage1_rank(factors, CYCLE06_FEATURES)
    print(f"  stage1_rank shape: {stage1_rank.shape}, "
          f"non-NaN cells: {int(stage1_rank.notna().sum().sum())}")

    print(f"\n[4/6] Build Stage 2 binary labels (forward {args.horizon_days}d)...")
    sign_labels = compute_binary_sign_labels(
        panel["close"], horizon_days=args.horizon_days)
    sign_labels = apply_tradeable_mask(sign_labels, mask)
    print(f"  sign_labels non-NaN (tradeable): "
          f"{int(sign_labels.notna().sum().sum())}")

    print(f"\n[5/6] Assemble X, y on top-decile cells + slice train/val...")
    if args.context_bundle == "NONE":
        context = {}
    else:
        context = extract_feature_bundle(factors, args.context_bundle)
    # slice TRAIN
    train_start = pd.Timestamp(f"{args.train_start}-01-01")
    train_end = pd.Timestamp(f"{args.train_end}-12-31")
    val_start = pd.Timestamp(f"{args.val_start}-01-01")
    val_end = pd.Timestamp(f"{args.val_end}-12-31")
    s1_train = stage1_rank.loc[(stage1_rank.index >= train_start)
                               & (stage1_rank.index <= train_end)]
    s1_val = stage1_rank.loc[(stage1_rank.index >= val_start)
                             & (stage1_rank.index <= val_end)]
    y_train_labels = sign_labels.loc[(sign_labels.index >= train_start)
                                     & (sign_labels.index <= train_end)]
    y_val_labels = sign_labels.loc[(sign_labels.index >= val_start)
                                   & (sign_labels.index <= val_end)]
    ctx_train = {n: p.loc[(p.index >= train_start) & (p.index <= train_end)]
                 for n, p in context.items()}
    ctx_val = {n: p.loc[(p.index >= val_start) & (p.index <= val_end)]
               for n, p in context.items()}
    X_train, y_train, feature_names = _build_xy_for_stage2(
        s1_train, y_train_labels, ctx_train, decile=args.decile)
    X_val, y_val, _ = _build_xy_for_stage2(
        s1_val, y_val_labels, ctx_val, decile=args.decile)
    print(f"  X_train: {X_train.shape}  y_train mean={y_train.mean():.4f} "
          f"(class 1 prior)")
    print(f"  X_val:   {X_val.shape}  y_val mean={y_val.mean():.4f}")
    print(f"  features: {feature_names}")
    if len(y_train) == 0:
        print(f"ERROR: zero train observations after top-decile filter",
              file=sys.stderr)
        return 4

    print(f"\n[6/6] Train Stage 2 classifier + eval on val...")
    if args.model == "logistic":
        model = LogisticRegressionSignClassifier()
        hyperparams = {"n_iter": 5, "decision_threshold": 0.5,
                       "fit_intercept": True}
    else:
        model = XGBSignClassifier(n_estimators=100, max_depth=4,
                                  learning_rate=0.1,
                                  random_state=args.seed)
        hyperparams = {"n_estimators": 100, "max_depth": 4,
                       "learning_rate": 0.1, "random_state": args.seed}
    model.fit(X_train, y_train)
    print(f"  fitted.")

    # In-sample
    pred_train = model.predict(X_train)
    _print_classifier_metrics("TRAIN (in-sample)", y_train, pred_train)

    # Held-out val
    if len(y_val) > 0:
        pred_val = model.predict(X_val)
        _print_classifier_metrics("VAL (held-out)", y_val, pred_val)
    else:
        print(f"  VAL: zero observations (skip)")
        pred_val = np.array([])

    if not args.no_save:
        save_dir = PROJ / args.save_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        trained_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        model_class = type(model).__name__
        spec_dict = {
            "schema_version": SCHEMA_VERSION,
            "model_class_name": model_class,
            "hyperparams": hyperparams,
            "train_config": {
                "horizon_days": args.horizon_days, "decile": args.decile,
                "train_start": args.train_start, "train_end": args.train_end,
                "val_start": args.val_start, "val_end": args.val_end,
                "context_bundle": args.context_bundle,
                "stage1_features": list(CYCLE06_FEATURES),
            },
            "feature_columns": list(feature_names),
            "sealed_years": list(DEFAULT_SEALED_YEARS),
            "output_type": "sign",
        }
        spec_id = compute_spec_id(spec_dict)
        # per_fold_metrics format reuses pipeline schema (one fold = train/val)
        per_fold = [
            {
                "fold_idx": 0,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "val_start": val_start.isoformat(),
                "val_end": val_end.isoformat(),
                "rank_ic": float(np.nan),  # not applicable for sign classifier
                "rank_ir": float(np.nan),
                "train_n_obs": int(len(y_train)),
                "val_n_obs": int(len(y_val)),
                "error": None,
                "train_accuracy": float((pred_train == y_train).mean()),
                "val_accuracy": (float((pred_val == y_val).mean())
                                  if len(y_val) > 0 else None),
            }
        ]
        metadata = ArtifactMetadata(
            schema_version=SCHEMA_VERSION,
            model_class_name=model_class,
            hyperparams=hyperparams,
            train_config=spec_dict["train_config"],
            feature_columns=tuple(feature_names),
            sealed_years=DEFAULT_SEALED_YEARS,
            output_type="sign",
            per_fold_metrics=per_fold,
            mean_rank_ic=float("nan"),  # not meaningful for sign
            mean_rank_ir=float("nan"),
            n_successful_folds=1, n_failed_folds=0,
            trained_at_utc=trained_at,
            lineage_tag=compute_lineage_tag(
                model_class, args.train_start, args.val_end,
                trained_at_utc=trained_at,
            ),
            spec_id=spec_id,
        )
        artifact = ModelArtifact(model=model, metadata=metadata)
        base = save_dir / f"sign_{model_class}_{args.train_start}-{args.val_end}_{trained_at}"
        paths = save_artifact(artifact, base)
        print(f"\nsaved → {paths.pkl_path.name}")
        print(f"        {paths.json_path.name}")
        # Summary JSON for run history
        summary_path = save_dir / f"sign_summary_{trained_at}.json"
        summary_path.write_text(json.dumps({
            "args": vars(args), "spec_id": spec_id,
            "lineage_tag": metadata.lineage_tag,
            "metrics": per_fold[0], "trained_at_utc": trained_at,
        }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
