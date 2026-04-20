#!/usr/bin/env python3
"""
scripts/run_xgb_importance.py — XGBoost feature importance analysis.

Uses XGBoost to predict forward returns from factor exposures,
then extracts feature importance to understand which factors
actually drive alpha.

Usage:
    python scripts/run_xgb_importance.py
    python scripts/run_xgb_importance.py --horizon 21
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import generate_all_factors, compute_forward_returns
from core.logging_setup import setup_logging, get_logger


def _load_backfill_tickers(symbols) -> set:
    """Intersect BarStore daily-provenance backfill set with the symbols
    in our universe (returns the subset whose daily data came from trades
    backfill; empty if sidecar missing)."""
    try:
        backfill = BarStore().list_backfill_tickers(freq="daily")
    except Exception:
        return set()
    return set(symbols) & backfill

setup_logging()
logger = get_logger("run_xgb")


def main():
    parser = argparse.ArgumentParser(description="XGBoost factor importance")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradeable = [s for s in all_syms if s not in uni.blacklist and s not in uni.macro_reference]

    start = cfg.backtest.start_date or "2007-01-02"
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
    if start:
        price_df = price_df[price_df.index >= start]
        if vol_df is not None:
            vol_df = vol_df[vol_df.index >= start]

    logger.info("Price matrix: %d x %d", len(price_df), len(price_df.columns))

    logger.info("Generating factors...")
    # Factor guard: mask volume-sensitive factors for trades_backfill tickers
    # (their volume semantics differ from stocks_csv source; see
    # DataSensitivityConfig in config/universe.yaml).
    backfill_tickers = _load_backfill_tickers(price_df.columns)
    if backfill_tickers:
        logger.info("data sensitivity guard: %d backfill tickers will get NaN "
                    "for volume-sensitive factors", len(backfill_tickers))
    factors = generate_all_factors(price_df, vol_df,
                                    backfill_tickers=backfill_tickers)
    logger.info("Generated %d factors", len(factors))

    logger.info("Computing forward returns (H=%d)...", args.horizon)
    fwd = compute_forward_returns(price_df, [args.horizon])
    fwd_df = fwd[args.horizon]

    # Build panel: stack (date, symbol) → factor values + forward return
    rows = []
    dates = price_df.index[252:-args.horizon]  # skip warmup and forward period
    for date in dates:
        for sym in tradeable:
            if sym not in fwd_df.columns:
                continue
            y = fwd_df.loc[date].get(sym)
            if pd.isna(y):
                continue
            row = {"date": date, "symbol": sym, "fwd_return": y}
            for fname, fdf in factors.items():
                val = fdf.loc[date].get(sym) if date in fdf.index and sym in fdf.columns else np.nan
                row[fname] = val
            rows.append(row)

    panel = pd.DataFrame(rows)
    logger.info("Panel: %d rows", len(panel))

    feature_cols = [c for c in panel.columns if c not in ("date", "symbol", "fwd_return")]
    X = panel[feature_cols].fillna(0)
    y = panel["fwd_return"]

    # Train/test split by time
    split_date = dates[int(len(dates) * 0.7)]
    train_mask = panel["date"] < split_date
    test_mask = panel["date"] >= split_date

    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    logger.info("Train: %d, Test: %d", len(X_train), len(X_test))

    import xgboost as xgb

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    train_score = model.score(X_train, y_train)
    test_score = model.score(X_test, y_test)
    logger.info("R2: train=%.4f, test=%.4f", train_score, test_score)

    # Feature importance
    importance = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)

    # Save artifacts
    artifacts_dir = Path("data/ml")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_config = {
        "model": "XGBRegressor",
        "n_estimators": 200, "max_depth": 4, "learning_rate": 0.05,
        "subsample": 0.8, "colsample_bytree": 0.8, "random_state": 42,
        "horizon": args.horizon,
        "train_end": str(split_date.date()),
        "n_train": len(X_train), "n_test": len(X_test),
        "n_features": len(feature_cols),
        "r2_train": round(train_score, 4),
        "r2_test": round(test_score, 4),
    }
    import json
    (artifacts_dir / "xgb_config.json").write_text(json.dumps(run_config, indent=2))
    importance.to_frame("importance").to_parquet(artifacts_dir / "xgb_importance.parquet")
    logger.info("Artifacts saved to %s", artifacts_dir)

    print("\n=== XGBoost Feature Importance (H=%d) ===" % args.horizon)
    print("R2: train=%.4f, test=%.4f\n" % (train_score, test_score))
    for fname, imp in importance.head(20).items():
        bar = "#" * int(imp * 200)
        print("  %-25s  %.4f  %s" % (fname, imp, bar))

    print("\nTop 5 most important:", list(importance.head(5).index))
    print("Bottom 5 least important:", list(importance.tail(5).index))

    # Permutation importance on test set (model-agnostic, more reliable)
    from sklearn.inspection import permutation_importance
    logger.info("Computing permutation importance on test set...")
    perm_result = permutation_importance(model, X_test, y_test, n_repeats=10,
                                          random_state=42, n_jobs=-1)
    perm_imp = pd.Series(perm_result.importances_mean, index=feature_cols).sort_values(ascending=False)
    perm_imp.to_frame("perm_importance").to_parquet(artifacts_dir / "xgb_perm_importance.parquet")

    print("\n=== Permutation Importance (OOS, H=%d) ===" % args.horizon)
    for fname, imp in perm_imp.head(15).items():
        bar = "#" * max(0, int(imp * 5000))
        print("  %-25s  %+.5f  %s" % (fname, imp, bar))

    # Compare XGB built-in vs permutation rankings
    print("\n=== Ranking Comparison (Top 10) ===")
    print("%-5s  %-25s  %-25s" % ("Rank", "XGB built-in", "Permutation (OOS)"))
    for i in range(min(10, len(importance))):
        xgb_name = importance.index[i]
        perm_name = perm_imp.index[i] if i < len(perm_imp) else "—"
        print("%-5d  %-25s  %-25s" % (i + 1, xgb_name, perm_name))


if __name__ == "__main__":
    main()
