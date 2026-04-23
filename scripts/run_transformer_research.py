#!/usr/bin/env python
"""Transformer research Phase 1 — daily forward-return benchmarking.

PRD M8 Phase 1. RESEARCH-ONLY: not wired into production. Produces a
head-to-head OOS R² comparison between Ridge / XGBoost / small
transformer on the same factor panel + forward return target.

Graceful fallback: if torch is not installed, prints install instructions
and runs Ridge+XGB baselines only.

Hard limits (per PRD):
  - 1-layer encoder (d_model=64, nhead=4) — ~50k params
  - daily horizon only (intraday sequence out of scope)
  - seq_len capped at 63 (3 months lookback)
  - training time cap: 30 min (configurable via --max-minutes)

Usage:
  python scripts/run_transformer_research.py --horizon 21 --epochs 5
  python scripts/run_transformer_research.py --cpu  # force CPU
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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
from core.ml.transformer_encoder import is_torch_available, get_best_device

setup_logging()
logger = get_logger("transformer_research")


def _build_panel(cfg, store, horizon: int):
    """Reuse from M7 — build cross-sectional factor panel."""
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradable = [s for s in all_syms
                if s not in uni.blacklist and s not in uni.macro_reference]
    start = cfg.backtest.start_date or "2007-01-02"
    # PRD 20260424 P3 + §7: full OHLCV + research_mask.
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


def _ridge_xgb_benchmarks(panel, feature_cols, split_frac):
    """Run Ridge + XGBoost on the panel, return OOS R² for each.

    PRD 20260424 §7: Ridge cannot handle NaN; drop rows with any NaN
    feature. XGBoost handles NaN natively but here we use the dropped
    panel so Ridge and XGBoost see the same sample (fair comparison).
    The dropna is explicit and auditable (unlike the prior silent
    fillna(0) which conflated warmup / masked / true-zero).
    """
    clean = panel.dropna(subset=feature_cols)
    X = clean[feature_cols].values
    y = clean["fwd_return"].values
    dates_sorted = panel["date"].sort_values().unique()
    split_date = dates_sorted[int(len(dates_sorted) * split_frac)]
    train_mask = panel["date"] < split_date
    test_mask = panel["date"] >= split_date
    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]

    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score
    ridge = Ridge(alpha=1000.0)
    ridge.fit(X_train, y_train)
    ridge_r2 = r2_score(y_test, ridge.predict(X_test))

    import xgboost as xgb
    m = xgb.XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42)
    m.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    xgb_r2 = r2_score(y_test, m.predict(X_test))

    return {"ridge_r2_oos": float(ridge_r2), "xgb_r2_oos": float(xgb_r2)}


def _transformer_benchmark(
    panel, feature_cols, split_frac, epochs, batch_size, seq_len,
    max_minutes, force_cpu,
):
    """Train SmallEncoder on time-series sequences, return OOS R²."""
    if not is_torch_available():
        return {"transformer_r2_oos": None, "error": "torch not installed"}

    import torch
    import torch.nn as nn
    from core.ml.transformer_encoder import SmallEncoder, count_params
    from sklearn.metrics import r2_score

    device = "cpu" if force_cpu else get_best_device()
    logger.info("Transformer device: %s", device)

    # Build sequences: for each (symbol, date), use last seq_len daily factor
    # snapshots of that symbol as input, predict forward return at date.
    panel_sorted = panel.sort_values(["symbol", "date"])
    sequences = []
    targets = []
    indexer = []  # (symbol, date) for split alignment
    for sym, grp in panel_sorted.groupby("symbol"):
        if len(grp) < seq_len + 1:
            continue
        # PRD 20260424 §7: Transformer can't handle NaN in tensor input;
        # drop rows with any NaN feature (auditable) rather than silent
        # fillna(0) which poisons the sequence with zero-valued 'data'.
        grp_clean = grp.dropna(subset=feature_cols)
        if len(grp_clean) < seq_len + 1:
            continue
        features = grp_clean[feature_cols].values.astype(np.float32)
        fwd = grp_clean["fwd_return"].values.astype(np.float32)
        dates = grp_clean["date"].values
        for i in range(seq_len, len(grp_clean)):
            sequences.append(features[i - seq_len : i])
            targets.append(fwd[i])
            indexer.append((sym, dates[i]))

    if not sequences:
        return {"transformer_r2_oos": None, "error": "not enough sequences"}

    X = np.stack(sequences)  # (N, seq_len, n_features)
    y = np.array(targets, dtype=np.float32)
    dt_idx = pd.to_datetime([d for _, d in indexer])

    # Temporal split
    dates_sorted = pd.Series(dt_idx).sort_values().unique()
    split_date = dates_sorted[int(len(dates_sorted) * split_frac)]
    train_mask = dt_idx < split_date
    test_mask = dt_idx >= split_date
    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y[train_mask], y[test_mask]

    logger.info("Transformer: train=%d, test=%d, seq_len=%d, n_features=%d",
                len(X_train), len(X_test), seq_len, len(feature_cols))

    model = SmallEncoder(n_features=len(feature_cols), seq_len=seq_len)
    model.to(device)
    logger.info("Model params: %d", count_params(model))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()

    X_train_t = torch.from_numpy(X_train).to(device)
    y_train_t = torch.from_numpy(y_train).to(device)
    X_test_t = torch.from_numpy(X_test).to(device)

    start_time = time.time()
    for epoch in range(epochs):
        if time.time() - start_time > max_minutes * 60:
            logger.warning("Transformer training time cap reached at epoch %d", epoch)
            break
        model.train()
        # Mini-batch training
        perm = torch.randperm(X_train_t.size(0))
        epoch_loss = 0.0
        n_batches = 0
        for i in range(0, X_train_t.size(0), batch_size):
            idx = perm[i : i + batch_size]
            xb, yb = X_train_t[idx], y_train_t[idx]
            opt.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            n_batches += 1
        avg_loss = epoch_loss / max(1, n_batches)
        logger.info("Epoch %d: train_loss=%.6f", epoch + 1, avg_loss)

    model.eval()
    with torch.no_grad():
        preds = model(X_test_t).cpu().numpy()
    r2 = float(r2_score(y_test, preds))
    return {"transformer_r2_oos": r2, "n_params": count_params(model), "device": device}


def main() -> int:
    parser = argparse.ArgumentParser(description="Transformer research Phase 1 (PRD M8)")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--seq-len", type=int, default=63)
    parser.add_argument("--split-frac", type=float, default=0.8)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-minutes", type=float, default=30.0,
                        help="Training time cap")
    parser.add_argument("--cpu", action="store_true", help="Force CPU even if GPU available")
    parser.add_argument("--out-tag", default="default")
    parser.add_argument("--out-dir", default="data/ml/transformer")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    torch_available = is_torch_available()
    if not torch_available:
        print("=" * 70)
        print("⚠ PyTorch not installed. Transformer benchmark will be SKIPPED.")
        print("  To enable: pip install -r requirements-gpu.txt")
        print("  Ridge + XGBoost baselines will still run.")
        print("=" * 70)

    cfg = load_config(Path(args.config_dir))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    logger.info("Building panel (H=%d)...", args.horizon)
    panel, feature_cols = _build_panel(cfg, store, args.horizon)
    logger.info("Panel: %d rows × %d features", len(panel), len(feature_cols))

    logger.info("Ridge + XGBoost baselines...")
    baselines = _ridge_xgb_benchmarks(panel, feature_cols, args.split_frac)

    if torch_available:
        logger.info("Transformer benchmark (seq_len=%d, epochs=%d)...",
                    args.seq_len, args.epochs)
        transformer_result = _transformer_benchmark(
            panel, feature_cols, args.split_frac,
            args.epochs, args.batch_size, args.seq_len,
            args.max_minutes, args.cpu,
        )
    else:
        transformer_result = {"transformer_r2_oos": None, "error": "torch not installed"}

    # Write artifacts
    out_root = Path(args.out_dir) / args.out_tag
    out_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    summary = {
        "timestamp": ts,
        "scope": "research-only (PRD M8 Phase 1); not wired to production",
        "config": {
            "horizon": args.horizon,
            "seq_len": args.seq_len,
            "split_frac": args.split_frac,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "force_cpu": args.cpu,
        },
        "panel": {"n_rows": len(panel), "n_features": len(feature_cols)},
        "results": {
            **baselines,
            **transformer_result,
        },
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2))

    print("=" * 70)
    print("Transformer research Phase 1 (PRD M8) — OOS R² head-to-head")
    print("=" * 70)
    print(f"  Ridge:        {baselines['ridge_r2_oos']:+.6f}")
    print(f"  XGBoost:      {baselines['xgb_r2_oos']:+.6f}")
    if transformer_result.get("transformer_r2_oos") is not None:
        print(f"  Transformer:  {transformer_result['transformer_r2_oos']:+.6f}  "
              f"(device={transformer_result['device']}, {transformer_result['n_params']} params)")
    else:
        print(f"  Transformer:  SKIPPED — {transformer_result.get('error')}")
    print()
    print(f"Artifacts: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
