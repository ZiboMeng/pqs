#!/usr/bin/env python3
"""
scripts/run_model_comparison.py — Round 9 Topic H (2026-04-20):
ridge vs XGBoost feature importance.

Trains both a Ridge (L2-regularized linear) regressor and an
XGBRegressor on the SAME (date × symbol, factor) feature panel +
forward-return target. Computes permutation importance on the
held-out test set for each, and prints a side-by-side top-20
leaderboard.

Purpose
-------
Before entering the LLM-assisted factor mining phase (see
docs/20260420-prd_llm_factor_mining.md), establish a reproducible baseline
showing which factors the CLASSICAL models consider important.
This is a RESEARCH tool — output feeds no production path.

Methodology honesty
-------------------
- Temporal train/test split (no random shuffle) — required for time-
  series data
- Permutation importance on OOS test set (not train set) to reduce
  overfit-signal
- Ridge uses L2 alpha tuned via 5-fold time-series CV on train set
- Rank agreement (Spearman rho) between the two rankings is reported
  to quantify "do the two models agree?"

Usage
-----
    python scripts/run_model_comparison.py
    python scripts/run_model_comparison.py --horizon 5
    python scripts/run_model_comparison.py --top-k 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import (
    generate_all_factors, compute_forward_returns,
)
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("run_model_comparison")


def _load_backfill_tickers(symbols) -> set:
    try:
        return set(symbols) & BarStore().list_backfill_tickers(freq="daily")
    except Exception:
        return set()


def _build_panel(cfg, horizon: int):
    """Load price_df, compute factors + forward returns, stack into
    (date, symbol) × factor panel."""
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradeable = [s for s in all_syms
                 if s not in uni.blacklist and s not in uni.macro_reference]

    price_frames, vol_frames = {}, {}
    for sym in tradeable:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                price_frames[sym] = df["close"]
            if "volume" in df.columns:
                vol_frames[sym] = df["volume"]
    price_df = pd.DataFrame(price_frames).sort_index()
    vol_df = pd.DataFrame(vol_frames).sort_index() if vol_frames else None

    start = cfg.backtest.start_date or "2013-01-02"
    price_df = price_df[price_df.index >= start]
    if vol_df is not None:
        vol_df = vol_df[vol_df.index >= start]

    backfill = _load_backfill_tickers(price_df.columns)
    factors = generate_all_factors(
        price_df, vol_df, backfill_tickers=backfill,
    )
    fwd = compute_forward_returns(price_df, [horizon])[horizon]

    # Stack to long format: (date, symbol) × factors + target
    rows = []
    dates = price_df.index[252:-horizon]
    for date in dates:
        for sym in tradeable:
            if sym not in fwd.columns:
                continue
            y = fwd.loc[date].get(sym)
            if pd.isna(y):
                continue
            row = {"date": date, "symbol": sym, "fwd_return": y}
            for fname, fdf in factors.items():
                if date in fdf.index and sym in fdf.columns:
                    row[fname] = fdf.loc[date].get(sym)
                else:
                    row[fname] = np.nan
            rows.append(row)
    panel = pd.DataFrame(rows)
    logger.info("Panel: %d rows, %d factors", len(panel), len(factors))
    return panel, list(factors.keys())


def _train_ridge(X_train, y_train):
    """Ridge with 5-fold time-series CV to pick alpha."""
    from sklearn.linear_model import RidgeCV
    from sklearn.model_selection import TimeSeriesSplit
    tscv = TimeSeriesSplit(n_splits=5)
    alphas = np.logspace(-2, 3, 20)
    model = RidgeCV(alphas=alphas, cv=tscv)
    model.fit(X_train.values, y_train.values)
    return model, float(model.alpha_)


def _train_xgb(X_train, y_train, X_test, y_test):
    import xgboost as xgb
    model = xgb.XGBRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, n_jobs=-1, verbosity=0,
    )
    model.fit(X_train.values, y_train.values,
              eval_set=[(X_test.values, y_test.values)], verbose=False)
    return model


def _perm_importance(model, X_test, y_test):
    from sklearn.inspection import permutation_importance
    res = permutation_importance(
        model, X_test.values, y_test.values,
        n_repeats=10, random_state=42, n_jobs=-1,
    )
    return pd.Series(res.importances_mean, index=X_test.columns)


def _rank_correlation(a: pd.Series, b: pd.Series) -> float:
    """Spearman rank correlation between two importance series."""
    from scipy.stats import spearmanr
    common = a.index.intersection(b.index)
    rho, _ = spearmanr(a.loc[common], b.loc[common])
    return float(rho) if not np.isnan(rho) else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon",   type=int, default=21)
    parser.add_argument("--top-k",     type=int, default=20)
    parser.add_argument("--test-frac", type=float, default=0.3,
                        help="Fraction of panel rows (by date) reserved for test")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    panel, feature_cols = _build_panel(cfg, args.horizon)
    X = panel[feature_cols].fillna(0.0)
    y = panel["fwd_return"]

    # Temporal split — last args.test_frac of unique dates go to test
    dates_sorted = sorted(panel["date"].unique())
    split_idx = int(len(dates_sorted) * (1 - args.test_frac))
    split_date = dates_sorted[split_idx]
    train_mask = panel["date"] < split_date
    test_mask = panel["date"] >= split_date
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]
    logger.info("Temporal split at %s — train=%d, test=%d",
                split_date.date(), len(X_train), len(X_test))

    # Train Ridge + XGBoost
    logger.info("Training Ridge (CV-tuned)...")
    ridge_model, ridge_alpha = _train_ridge(X_train, y_train)
    logger.info("Ridge alpha: %.3f", ridge_alpha)

    logger.info("Training XGBoost...")
    xgb_model = _train_xgb(X_train, y_train, X_test, y_test)

    # R² on OOS
    ridge_r2 = float(ridge_model.score(X_test.values, y_test.values))
    xgb_r2 = float(xgb_model.score(X_test.values, y_test.values))
    logger.info("OOS R²: ridge=%.5f, xgb=%.5f", ridge_r2, xgb_r2)

    # Permutation importance
    logger.info("Computing Ridge permutation importance...")
    ridge_imp = _perm_importance(ridge_model, X_test, y_test).sort_values(ascending=False)
    logger.info("Computing XGBoost permutation importance...")
    xgb_imp = _perm_importance(xgb_model, X_test, y_test).sort_values(ascending=False)

    rank_agreement = _rank_correlation(ridge_imp, xgb_imp)

    # Side-by-side top-K leaderboard
    print("\n" + "=" * 78)
    print(f"Model Comparison: Ridge vs XGBoost  (horizon={args.horizon}d)")
    print(f"  Train/test split: {split_date.date()}  "
          f"n_train={len(X_train)}  n_test={len(X_test)}")
    print(f"  OOS R²:  ridge={ridge_r2:+.5f}   xgb={xgb_r2:+.5f}")
    print(f"  Ridge alpha (CV): {ridge_alpha:.3f}")
    print(f"  Rank-agreement (Spearman ρ on feature importance): "
          f"{rank_agreement:+.3f}")
    print("=" * 78)

    print(f"\n{'rank':>4}  {'Ridge (perm)':<28} {'XGBoost (perm)':<28}")
    print("-" * 70)
    top_k = min(args.top_k, len(ridge_imp), len(xgb_imp))
    for i in range(top_k):
        r_name = ridge_imp.index[i]
        r_val = ridge_imp.iloc[i]
        x_name = xgb_imp.index[i]
        x_val = xgb_imp.iloc[i]
        mark = " ✓" if r_name == x_name else "  "
        print(f"{i+1:>4}{mark}{r_name:<26} {r_val:+.5f}   "
              f"{x_name:<26} {x_val:+.5f}")

    # Save artifacts
    artifacts = Path("data/ml")
    artifacts.mkdir(parents=True, exist_ok=True)
    run_config = {
        "round":          "9-topic-H",
        "horizon":        args.horizon,
        "test_frac":      args.test_frac,
        "split_date":     str(split_date.date()),
        "n_train":        int(len(X_train)),
        "n_test":         int(len(X_test)),
        "n_features":     int(len(feature_cols)),
        "ridge_alpha":    ridge_alpha,
        "ridge_r2":       round(ridge_r2, 5),
        "xgb_r2":         round(xgb_r2, 5),
        "rank_agreement": round(rank_agreement, 3),
    }
    (artifacts / "model_comparison_config.json").write_text(
        json.dumps(run_config, indent=2)
    )
    ridge_imp.to_frame("ridge_perm_imp").to_parquet(
        artifacts / "ridge_perm_importance.parquet"
    )
    xgb_imp.to_frame("xgb_perm_imp").to_parquet(
        artifacts / "xgb_perm_importance_comparison.parquet"
    )

    # Side-by-side leaderboard as DataFrame → parquet + CSV
    leaderboard = pd.DataFrame({
        "ridge_rank":    range(1, len(ridge_imp) + 1),
        "ridge_factor":  ridge_imp.index,
        "ridge_imp":     ridge_imp.values,
    })
    xgb_lb = pd.DataFrame({
        "xgb_rank":   range(1, len(xgb_imp) + 1),
        "xgb_factor": xgb_imp.index,
        "xgb_imp":    xgb_imp.values,
    })
    combined = pd.concat([leaderboard.reset_index(drop=True),
                          xgb_lb.reset_index(drop=True)], axis=1)
    combined.head(args.top_k).to_csv(
        artifacts / "model_comparison_top20.csv", index=False,
    )
    logger.info("Artifacts saved to %s", artifacts)

    # Interpretation
    print()
    print("=" * 78)
    if rank_agreement >= 0.7:
        print("✓ HIGH AGREEMENT — Ridge and XGBoost converge on largely the "
              "same top features.")
        print("  Linear signal dominates; XGBoost's nonlinear capacity adds "
              "little marginal info.")
    elif rank_agreement >= 0.3:
        print("· MODERATE AGREEMENT — Some overlap in top features but "
              "meaningful divergence.")
        print("  XGBoost is finding nonlinear / interaction structure that "
              "Ridge misses.")
    else:
        print("⚠ LOW AGREEMENT — Models rank features very differently.")
        print("  Likely driven by feature collinearity or small OOS sample. "
              "Interpret both with care.")
    print("=" * 78)


if __name__ == "__main__":
    main()
