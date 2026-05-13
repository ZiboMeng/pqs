"""Phase 1.5 Bug 1 investigation — why do LOTYO folds 2009-2014 return NaN IC?

Reproduces Phase 1 minimal pipeline focused on early-year fold behavior:
- Build ML panel
- Train minimal model on 2010-2017 ex-2009 (skip 2009 for fold-2009 case)
- Predict on 2009
- Inspect: how many dates have >= 5 valid stocks? y_pred.std()? y_pred.nunique()?

Output: prints diagnostic table; saves data/audit/phase_1_5_bug1_nan_ic.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.research.temporal_split import load_temporal_split, partition_for_role
from core.factors.base_masks import research_mask_default
from core.factors.factor_generator import compute_forward_returns, generate_all_factors
from core.factors.factor_registry import RESEARCH_FACTORS
from core.data.bar_store import BarStore

from core.ml.feature_panel_builder import build_ml_panel
from core.ml.xgb_alpha import XGBAlphaModel, compute_rank_ic


def _build_minimal_panel():
    """Lightweight: just OHLCV factors (no EDGAR/sector/macro for speed)."""
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
    frames = {k: {} for k in ("close", "open", "high", "low", "volume")}
    for sym in syms:
        df = store.load(sym, freq="1d", adjusted=True, fallback="local")
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
    factors = generate_all_factors(
        panel["close"], volume_df=panel["volume"],
        open_df=panel["open"], high_df=panel["high"], low_df=panel["low"],
        benchmark_map=bench,
    )
    factors = {n: f for n, f in factors.items() if n in RESEARCH_FACTORS}
    return panel, factors


def main() -> int:
    print("[Bug 1 investigation] Loading panel + OHLCV factors...")
    t0 = time.time()
    panel, factors = _build_minimal_panel()
    print(f"  panel: {panel['close'].shape}, factors={len(factors)} ({time.time()-t0:.1f}s)")

    fwd_dict = compute_forward_returns(panel["close"], horizons=[21], mode="cc")
    fwd = fwd_dict[21]
    mask = research_mask_default(panel["close"], panel["volume"])

    print("[Bug 1] Building ML panel with cross-sectional ranks...")
    ml_panel, feature_cols = build_ml_panel(
        factors, fwd, research_mask=mask, apply_rank=True,
    )
    print(f"  ml_panel: {len(ml_panel)} rows × {len(feature_cols)} features")

    # Stats per year on raw ml_panel
    ml_panel["year"] = ml_panel["date"].dt.year
    print("\n[Bug 1] Per-year ml_panel row counts + unique stocks per date:")
    rows = []
    for y, grp in ml_panel.groupby("year"):
        n_rows = len(grp)
        n_dates = grp["date"].nunique()
        n_stocks_per_date = grp.groupby("date").size()
        n_stocks_avg = n_stocks_per_date.mean()
        n_stocks_min = n_stocks_per_date.min()
        n_stocks_max = n_stocks_per_date.max()
        n_dates_ge_5 = (n_stocks_per_date >= 5).sum()
        n_dates_ge_3 = (n_stocks_per_date >= 3).sum()
        rows.append({
            "year": int(y), "n_rows": int(n_rows), "n_dates": int(n_dates),
            "n_stocks_avg": float(n_stocks_avg),
            "n_stocks_min": int(n_stocks_min),
            "n_stocks_max": int(n_stocks_max),
            "n_dates_ge_5": int(n_dates_ge_5),
            "n_dates_ge_3": int(n_dates_ge_3),
        })
        print(f"  {y}: n_rows={n_rows} n_dates={n_dates} stocks/date avg={n_stocks_avg:.1f} "
              f"min={n_stocks_min} max={n_stocks_max} "
              f"n_dates_≥5={n_dates_ge_5} n_dates_≥3={n_dates_ge_3}")

    # Now simulate fold-2009: train on 2010-2024 ex-2017, val=2017, test=2009
    print("\n[Bug 1] Simulating fold-2009 (train=2010-2024 ex 2017+2009; val=2017; test=2009)...")
    train_years = [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2020, 2022, 2024]
    val_year = 2017
    test_year = 2009
    train_panel = ml_panel[ml_panel["year"].isin(train_years)]
    val_panel = ml_panel[ml_panel["year"] == val_year]
    test_panel = ml_panel[ml_panel["year"] == test_year]
    print(f"  train n={len(train_panel)} val n={len(val_panel)} test n={len(test_panel)}")

    if test_panel.empty:
        print("  test_panel empty for 2009 — likely root cause: no 2009 rows in selector panel")
        out = {
            "investigation": "Bug 1 NaN-IC in 6/12 LOTYO folds",
            "per_year_stats": rows,
            "fold_2009_test_n_rows": 0,
            "verdict": "test_panel empty for 2009 → no IC computable → returns NaN",
        }
        (PROJ / "data/audit/phase_1_5_bug1_nan_ic.json").write_text(
            json.dumps(out, indent=2, default=str))
        return 0

    print("[Bug 1] Training minimal XGB...")
    model = XGBAlphaModel(n_estimators=50, max_depth=4, learning_rate=0.05)
    model.fit(
        train_panel, train_panel["fwd_return"],
        X_val=val_panel, y_val=val_panel["fwd_return"],
        feature_cols=feature_cols,
    )
    print(f"  best_iter = {model.best_iteration}")

    print("[Bug 1] Predicting on 2009...")
    y_pred = model.predict(test_panel)
    print(f"  y_pred shape: {y_pred.shape}")
    print(f"  y_pred mean: {y_pred.mean():.6f}  std: {y_pred.std():.6f}  "
          f"unique: {len(np.unique(y_pred))}")
    print(f"  y_pred min: {y_pred.min():.6f}  max: {y_pred.max():.6f}")

    print("[Bug 1] Computing rank IC on test 2009 fold...")
    ic_mean, ic_std, per_date_ic = compute_rank_ic(
        test_panel["fwd_return"], y_pred, test_panel["date"],
    )
    print(f"  ic_mean: {ic_mean}  ic_std: {ic_std}  per_date_count: {len(per_date_ic)}")

    # Diagnose per-date skip reasons
    test_panel = test_panel.copy()
    test_panel["y_pred"] = y_pred
    print("[Bug 1] Per-date diagnostic on 2009 test panel...")
    skip_n_lt_5 = 0
    skip_y_true_low_unique = 0
    skip_y_pred_zero_std = 0
    valid = 0
    for date, grp in test_panel.groupby("date"):
        if len(grp) < 5:
            skip_n_lt_5 += 1
            continue
        if grp["fwd_return"].nunique() < 2:
            skip_y_true_low_unique += 1
            continue
        if grp["y_pred"].std() == 0:
            skip_y_pred_zero_std += 1
            continue
        valid += 1
    n_dates_total = test_panel["date"].nunique()
    print(f"  total dates in 2009: {n_dates_total}")
    print(f"  skipped len<5: {skip_n_lt_5}")
    print(f"  skipped y_true nunique < 2: {skip_y_true_low_unique}")
    print(f"  skipped y_pred std == 0: {skip_y_pred_zero_std}")
    print(f"  valid: {valid}")

    out = {
        "investigation": "Bug 1 NaN-IC in 6/12 LOTYO folds",
        "per_year_stats": rows,
        "fold_2009_diagnostic": {
            "n_rows": int(len(test_panel)),
            "n_dates_total": int(n_dates_total),
            "skipped_len_lt_5": int(skip_n_lt_5),
            "skipped_y_true_low_unique": int(skip_y_true_low_unique),
            "skipped_y_pred_zero_std": int(skip_y_pred_zero_std),
            "valid_dates": int(valid),
            "ic_mean": float(ic_mean) if not np.isnan(ic_mean) else None,
            "y_pred_std": float(y_pred.std()),
            "y_pred_unique": int(len(np.unique(y_pred))),
            "best_iter": model.best_iteration,
        },
    }
    out_path = PROJ / "data/audit/phase_1_5_bug1_nan_ic.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[Bug 1] Output: {out_path.relative_to(PROJ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
