#!/usr/bin/env python
"""XGBoost with TimeSeriesSplit CV + permutation importance (PRD R3/R42).

Extends scripts/run_xgb_importance.py with:
  - K-fold temporal CV (sklearn TimeSeriesSplit)
  - Per-fold OOS R² stability report
  - Per-fold feature importance (aggregate mean + std)
  - Optional SHAP attribution (R43)

Usage:
  python scripts/run_xgb_cv.py --horizon 21 --n-splits 5
  python scripts/run_xgb_cv.py --n-splits 5 --shap       # SHAP enabled
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import compute_forward_returns, generate_all_factors
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("xgb_cv")


def _build_panel(cfg, store, horizon: int):
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    start = cfg.backtest.start_date or "2007-01-02"
    # PRD 20260424 P3 + §7: load OHLCV and build research_mask.
    price_frames, open_frames, high_frames, low_frames, vol_frames = {}, {}, {}, {}, {}
    for sym in tradable:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        price_frames[sym] = df["close"]
        if "open" in df.columns:
            open_frames[sym] = df["open"]
        if "high" in df.columns:
            high_frames[sym] = df["high"]
        if "low" in df.columns:
            low_frames[sym] = df["low"]
        if "volume" in df.columns:
            vol_frames[sym] = df["volume"]
    price_df = pd.DataFrame(price_frames).sort_index()
    open_df = pd.DataFrame(open_frames).reindex_like(price_df) if open_frames else None
    high_df = pd.DataFrame(high_frames).reindex_like(price_df) if high_frames else None
    low_df = pd.DataFrame(low_frames).reindex_like(price_df) if low_frames else None
    vol_df = pd.DataFrame(vol_frames).reindex_like(price_df) if vol_frames else None
    if start:
        price_df = price_df[price_df.index >= start]
        for df_ref in (open_df, high_df, low_df, vol_df):
            if df_ref is not None:
                df_ref.drop(df_ref.index[df_ref.index < pd.Timestamp(start)], inplace=True)
    # PRD 20260424 §7 mask hardening
    from core.factors.base_masks import research_mask
    mask_panel = (
        research_mask(price_df, vol_df, min_price=5.0, min_usd=20e6, window=20)
        if vol_df is not None else None
    )

    factors = generate_all_factors(
        price_df, volume_df=vol_df,
        open_df=open_df, high_df=high_df, low_df=low_df,
    )
    fwd = compute_forward_returns(price_df, [horizon])[horizon]

    rows = []
    n_masked_out = 0
    dates = price_df.index[252:-horizon]
    for date in dates:
        for sym in tradable:
            if sym not in fwd.columns:
                continue
            y = fwd.loc[date].get(sym)
            if pd.isna(y):
                continue
            # PRD §7: skip non-tradable (date, symbol) pairs
            if mask_panel is not None:
                mv = (
                    mask_panel.loc[date, sym]
                    if date in mask_panel.index and sym in mask_panel.columns
                    else False
                )
                if not mv:
                    n_masked_out += 1
                    continue
            row = {"date": date, "symbol": sym, "fwd_return": y}
            for fname, fdf in factors.items():
                val = fdf.loc[date].get(sym) if date in fdf.index and sym in fdf.columns else np.nan
                row[fname] = val
            rows.append(row)
    panel = pd.DataFrame(rows)
    if mask_panel is not None:
        logger.info("Research mask excluded %d non-tradable samples", n_masked_out)
    feature_cols = [c for c in panel.columns if c not in ("date", "symbol", "fwd_return")]
    return panel, feature_cols


def _run_cv(panel, feature_cols, n_splits, enable_shap):
    import xgboost as xgb
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import r2_score

    # PRD 20260424 §7: no .fillna(0) — XGBoost handles NaN natively via
    # its `missing=np.nan` default (preserves the 4-state distinction:
    # true-zero vs warmup vs non-tradable vs data-missing)
    X = panel[feature_cols].values
    y = panel["fwd_return"].values

    # TimeSeriesSplit on sorted panel (already sorted by date in _build_panel
    # because iteration over date loop is ordered)
    # Reorder by date for safety
    panel_sorted = panel.sort_values("date").reset_index(drop=True)
    X = panel_sorted[feature_cols].values
    y = panel_sorted["fwd_return"].values
    dates = panel_sorted["date"].values

    tscv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics = []
    fold_importances = []
    fold_shap = []

    for fold_i, (train_idx, test_idx) in enumerate(tscv.split(X), start=1):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        train_start, train_end = dates[train_idx[0]], dates[train_idx[-1]]
        test_start, test_end = dates[test_idx[0]], dates[test_idx[-1]]

        model = xgb.XGBRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            reg_alpha=0.1, reg_lambda=0.1, random_state=42,
        )
        model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
        y_pred = model.predict(X_test)
        r2 = float(r2_score(y_test, y_pred))

        # Permutation importance on OOS
        perm = permutation_importance(
            model, X_test, y_test, n_repeats=5, random_state=42, n_jobs=1,
        )
        imp_df = pd.DataFrame({
            "feature": feature_cols,
            "importance_mean": perm.importances_mean,
            "importance_std": perm.importances_std,
            "fold": fold_i,
        }).sort_values("importance_mean", ascending=False)

        fold_metrics.append({
            "fold": fold_i,
            "train_start": str(pd.Timestamp(train_start).date()),
            "train_end": str(pd.Timestamp(train_end).date()),
            "test_start": str(pd.Timestamp(test_start).date()),
            "test_end": str(pd.Timestamp(test_end).date()),
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
            "oos_r2": r2,
        })
        fold_importances.append(imp_df)
        logger.info("Fold %d/%d: train=%d test=%d r2=%.4f  [%s → %s]",
                    fold_i, n_splits, len(train_idx), len(test_idx), r2,
                    fold_metrics[-1]["test_start"], fold_metrics[-1]["test_end"])

        # Optional SHAP
        if enable_shap:
            try:
                import shap
                explainer = shap.TreeExplainer(model)
                sv = explainer.shap_values(X_test[:1000])  # cap for speed
                shap_mean_abs = pd.DataFrame({
                    "feature": feature_cols,
                    "shap_mean_abs": np.abs(sv).mean(axis=0),
                    "fold": fold_i,
                }).sort_values("shap_mean_abs", ascending=False)
                fold_shap.append(shap_mean_abs)
                logger.info("Fold %d SHAP top-5: %s", fold_i,
                            shap_mean_abs.head(5)["feature"].tolist())
            except Exception as exc:
                logger.warning("Fold %d SHAP failed: %s", fold_i, exc)

    return fold_metrics, fold_importances, fold_shap


def _aggregate_importance(fold_importances):
    """Combine per-fold importances into mean + stability."""
    if not fold_importances:
        return None
    concat = pd.concat(fold_importances)
    agg = concat.groupby("feature")["importance_mean"].agg(["mean", "std", "count"])
    agg = agg.reset_index().sort_values("mean", ascending=False)
    return agg


def main() -> int:
    parser = argparse.ArgumentParser(description="XGBoost TimeSeriesSplit CV (PRD R3/R42)")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--shap", action="store_true", help="Enable SHAP per-fold")
    parser.add_argument("--out-tag", default="default")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml/xgb_cv")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    logger.info("Building panel (H=%d)...", args.horizon)
    panel, feature_cols = _build_panel(cfg, store, args.horizon)
    logger.info("Panel: %d rows × %d features", len(panel), len(feature_cols))

    logger.info("TimeSeriesSplit CV (%d folds)...", args.n_splits)
    fold_metrics, fold_importances, fold_shap = _run_cv(
        panel, feature_cols, args.n_splits, args.shap,
    )

    agg_imp = _aggregate_importance(fold_importances)
    r2_list = [m["oos_r2"] for m in fold_metrics]
    r2_mean = float(np.mean(r2_list))
    r2_std = float(np.std(r2_list))

    # Write artifacts
    out_root = Path(args.out_dir) / args.out_tag
    out_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()

    summary = {
        "timestamp": ts,
        "scope": "XGBoost TimeSeriesSplit CV + permutation importance (PRD R3/R42)",
        "config": {
            "horizon": args.horizon,
            "n_splits": args.n_splits,
            "shap_enabled": args.shap,
            "n_features": len(feature_cols),
            "n_panel_rows": len(panel),
        },
        "fold_metrics": fold_metrics,
        "oos_r2_stats": {
            "mean": r2_mean,
            "std": r2_std,
            "min": float(min(r2_list)),
            "max": float(max(r2_list)),
            "positive_folds": int(sum(1 for r in r2_list if r > 0)),
        },
        "top_20_features": agg_imp.head(20).to_dict(orient="records") if agg_imp is not None else [],
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    if agg_imp is not None:
        agg_imp.to_parquet(out_root / "aggregated_importance.parquet")
    if fold_importances:
        pd.concat(fold_importances).to_parquet(out_root / "per_fold_importance.parquet")
    if fold_shap:
        pd.concat(fold_shap).to_parquet(out_root / "per_fold_shap.parquet")

    print("=" * 70)
    print(f"XGBoost CV ({args.n_splits} folds, H={args.horizon})")
    print("=" * 70)
    print(f"OOS R²: mean={r2_mean:+.4f} std={r2_std:.4f} "
          f"[{min(r2_list):+.4f}, {max(r2_list):+.4f}]  "
          f"(positive folds: {sum(1 for r in r2_list if r > 0)}/{args.n_splits})")
    print("\nPer-fold:")
    for m in fold_metrics:
        print(f"  Fold {m['fold']}: r2={m['oos_r2']:+.4f}  test=[{m['test_start']} → {m['test_end']}]")
    if agg_imp is not None:
        print("\nTop-15 features (aggregated mean importance):")
        for _, row in agg_imp.head(15).iterrows():
            print(f"  {row['feature']:<35} mean={row['mean']:+.5f}  std={row['std']:.5f}")
    print(f"\nArtifacts: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
