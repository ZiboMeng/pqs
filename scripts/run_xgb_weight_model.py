#!/usr/bin/env python
"""XGBoost-driven weight generation model (PRD M7, research-only).

Train XGBoost on factor panel → predict per-(date, symbol) forward return
score → convert to per-date cross-sectional weights (top-K pick or softmax).
Compare resulting portfolio CAGR / Sharpe / MaxDD against equal-weight
top-K baseline.

**SCOPE**: research-only. Does NOT modify config/production_strategy.yaml.
Output artifact lives under data/ml/xgb_weights/<tag>/. A future M7 v2
could wire this through production if results are compelling.

Usage:
  python scripts/run_xgb_weight_model.py --horizon 21 --top-k 5
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
from core.factors.factor_generator import generate_all_factors
from core.factors.factor_generator import compute_forward_returns
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("xgb_weights")


def _build_panel(cfg, store, horizon: int):
    """Returns (panel DataFrame, price_df, feature_cols).

    Reuses the panel-building logic from run_xgb_importance.py, kept inline
    here to avoid refactoring that script during M7."""
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]

    start = cfg.backtest.start_date or "2007-01-02"
    # PRD 20260424 P3 + §7: full OHLCV + research_mask hardening.
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

    from core.factors.base_masks import research_mask_default
    mask_panel = (
        research_mask_default(price_df, vol_df)
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
    return panel, price_df, feature_cols


def _train_model(panel: pd.DataFrame, feature_cols: list[str],
                 split_frac: float = 0.7):
    """Returns (trained xgb model, test panel slice, train_r2, test_r2)."""
    try:
        import xgboost as xgb
    except ImportError:
        raise RuntimeError(
            "xgboost not installed. pip install xgboost or "
            "conda install -c conda-forge xgboost"
        )
    # PRD 20260424 §7: no fillna(0) — XGBoost handles NaN natively via
    # its `missing=np.nan` default. Preserves the 4-state distinction
    # (true-zero / warmup / non-tradable / data-missing).
    X = panel[feature_cols]
    y = panel["fwd_return"]
    dates = panel["date"].sort_values().unique()
    split_date = dates[int(len(dates) * split_frac)]
    train_mask = panel["date"] < split_date
    test_mask = panel["date"] >= split_date
    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    train_r2 = float(model.score(X_train, y_train))
    test_r2 = float(model.score(X_test, y_test))
    logger.info("XGB R² train=%.4f test=%.4f  split_date=%s",
                train_r2, test_r2, split_date)
    return model, panel[test_mask].copy(), train_r2, test_r2


def _score_to_weights(
    test_panel: pd.DataFrame,
    model,
    feature_cols: list[str],
    top_k: int,
) -> pd.DataFrame:
    """Produce date × symbol weight matrix via top-K pick on model scores."""
    test_panel = test_panel.copy()
    # PRD 20260424 §7: predict with NaN-aware XGBoost (missing=np.nan default).
    test_panel["score"] = model.predict(test_panel[feature_cols])
    # For each date, pick top_k symbols by score, equal-weight
    weights: dict = {}
    for date, grp in test_panel.groupby("date"):
        ranked = grp.nlargest(top_k, "score")
        n = max(1, len(ranked))
        for _, row in ranked.iterrows():
            weights.setdefault(date, {})[row["symbol"]] = 1.0 / n
    # Weight matrix fillna(0) is legitimate (zero-weight for absent symbol);
    # this is the "true-zero = no position" semantic, not a feature-value
    # imputation.
    return pd.DataFrame(weights).T.fillna(0)


def _simulate_portfolio(
    weights: pd.DataFrame,
    price_df: pd.DataFrame,
    rebalance_every: int = 21,
) -> pd.Series:
    """Simple equal-weighted top-K portfolio simulation (no costs, no slippage)
    — research-grade comparison of weight schemes."""
    weights = weights.reindex(columns=price_df.columns, fill_value=0.0).fillna(0.0)
    weights = weights.reindex(price_df.index, method="ffill").fillna(0.0)
    rets = price_df.pct_change().fillna(0.0)
    # Apply rebalance cadence: freeze weights between rebalance dates
    rebalance_mask = np.arange(len(weights)) % rebalance_every == 0
    frozen_w = weights.where(pd.Series(rebalance_mask, index=weights.index), np.nan).ffill().fillna(0.0)
    # Portfolio return = weighted symbol returns (shift weights by 1 to avoid lookahead)
    w_shifted = frozen_w.shift(1).fillna(0.0)
    port_rets = (w_shifted * rets).sum(axis=1)
    return (1 + port_rets).cumprod()


def _equal_weight_baseline(
    test_panel: pd.DataFrame,
    price_df: pd.DataFrame,
    top_k: int,
    rebalance_every: int,
) -> pd.Series:
    """Baseline: equal-weight top-K by quality factor (ordinary proxy)."""
    if "quality" not in test_panel.columns:
        # fallback: random pick (just for baseline comparison)
        pick_col = test_panel.columns[-1]
    else:
        pick_col = "quality"
    weights: dict = {}
    for date, grp in test_panel.groupby("date"):
        ranked = grp.nlargest(top_k, pick_col)
        n = max(1, len(ranked))
        for _, row in ranked.iterrows():
            weights.setdefault(date, {})[row["symbol"]] = 1.0 / n
    wdf = pd.DataFrame(weights).T.fillna(0)
    return _simulate_portfolio(wdf, price_df, rebalance_every)


def _compute_metrics(equity: pd.Series) -> dict:
    rets = equity.pct_change().dropna()
    if len(rets) < 2:
        return {"CAGR": None, "Sharpe": None, "MaxDD": None}
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    peak = equity.cummax()
    dd = (equity / peak - 1).min()
    return {
        "CAGR": float(cagr), "Sharpe": float(sharpe), "MaxDD": float(dd),
        "final_equity": float(equity.iloc[-1]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="XGBoost weight research model (PRD M7)")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--split-frac", type=float, default=0.7)
    parser.add_argument("--rebalance-days", type=int, default=21)
    parser.add_argument("--out-tag", default="default")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml/xgb_weights")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    logger.info("Building panel (H=%d)...", args.horizon)
    panel, price_df, feature_cols = _build_panel(cfg, store, args.horizon)
    logger.info("Panel: %d rows × %d features", len(panel), len(feature_cols))

    logger.info("Training XGBoost...")
    model, test_panel, train_r2, test_r2 = _train_model(
        panel, feature_cols, split_frac=args.split_frac,
    )

    logger.info("Converting model scores to weights (top-%d)...", args.top_k)
    xgb_weights = _score_to_weights(test_panel, model, feature_cols, args.top_k)
    xgb_equity = _simulate_portfolio(xgb_weights, price_df, args.rebalance_days)
    xgb_metrics = _compute_metrics(xgb_equity)

    logger.info("Equal-weight baseline (top-%d by quality)...", args.top_k)
    baseline_equity = _equal_weight_baseline(test_panel, price_df, args.top_k, args.rebalance_days)
    baseline_metrics = _compute_metrics(baseline_equity)

    # Write artifacts
    out_root = Path(args.out_dir) / args.out_tag
    out_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).isoformat()
    summary = {
        "timestamp": ts,
        "scope": "research-only (PRD M7); not wired to production",
        "config": {
            "horizon": args.horizon,
            "top_k": args.top_k,
            "split_frac": args.split_frac,
            "rebalance_days": args.rebalance_days,
            "n_features": len(feature_cols),
            "n_panel_rows": len(panel),
        },
        "xgb_model": {
            "train_r2": train_r2,
            "test_r2_oos": test_r2,
            "n_estimators": 200, "max_depth": 4,
        },
        "performance": {
            "xgb_weighted": xgb_metrics,
            "equal_weighted_baseline": baseline_metrics,
            "xgb_vs_baseline_cagr_delta_pct": (
                xgb_metrics.get("CAGR", 0) - baseline_metrics.get("CAGR", 0)
                if xgb_metrics.get("CAGR") is not None and baseline_metrics.get("CAGR") is not None
                else None
            ),
        },
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2))
    xgb_weights.to_parquet(out_root / "xgb_weights.parquet")
    xgb_equity.to_frame("equity").to_parquet(out_root / "xgb_equity.parquet")
    baseline_equity.to_frame("equity").to_parquet(out_root / "baseline_equity.parquet")

    print("=" * 70)
    print("XGBoost weight model (PRD M7 research)")
    print("=" * 70)
    print(f"  Train R²:  {train_r2:+.4f}")
    print(f"  Test R²:   {test_r2:+.4f}  (OOS)")
    print()
    print(f"  XGB-weighted portfolio:   CAGR={xgb_metrics['CAGR']:+.2%}  "
          f"Sharpe={xgb_metrics['Sharpe']:+.2f}  MaxDD={xgb_metrics['MaxDD']:+.2%}")
    print(f"  Equal-weight baseline:    CAGR={baseline_metrics['CAGR']:+.2%}  "
          f"Sharpe={baseline_metrics['Sharpe']:+.2f}  MaxDD={baseline_metrics['MaxDD']:+.2%}")
    if summary["performance"]["xgb_vs_baseline_cagr_delta_pct"] is not None:
        delta = summary["performance"]["xgb_vs_baseline_cagr_delta_pct"]
        print(f"  XGB vs baseline CAGR delta: {delta:+.2%}")
    print()
    print(f"Artifacts: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
