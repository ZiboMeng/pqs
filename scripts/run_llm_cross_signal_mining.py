#!/usr/bin/env python3
"""LLM-Round 6 tool: XGBoost cross-signal mining across LLM candidates
(PRD §9 LLM-5, §7 Cross-Signal Mining).

Extends `scripts/run_model_comparison.py` by auto-discovering all LLM
candidates from `research/llm_candidates/round_*/*.yaml`, computing
their factor values on the same price panel used by existing
research factors, and running Ridge + XGBoost + permutation
importance on the COMBINED feature set.

Purpose per PRD §9 LLM-5 completion signal: "xgb_importance.parquet
显示 LLM 候选在 top-20". This tool outputs precisely that: the top-K
permutation importance ranking, marked with whether each feature is
an existing research factor or an LLM candidate.

Also addresses PRD §7.2 step 3 (IC screen + XGBoost importance +
orthogonalization), at least the XGBoost-importance part.

LLM is NOT the judge (§2.2). This tool produces structured evidence —
if an LLM candidate ranks in top-20 + has incremental explanatory
power, a human decides whether to pursue it.

Usage
-----
    python scripts/run_llm_cross_signal_mining.py
    python scripts/run_llm_cross_signal_mining.py --horizon 5 --top-k 30
    python scripts/run_llm_cross_signal_mining.py --llm-only  # LLM features only
"""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import (
    compute_forward_returns, generate_all_factors,
)
from core.factors.llm_candidate import load_candidate_from_yaml
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("run_llm_cross_signal_mining")


def _discover_llm_candidates() -> list:
    """Glob all LLM candidate YAMLs under research/llm_candidates/round_*/.
    Returns list of (yaml_path, candidate) tuples."""
    root = Path("research/llm_candidates")
    out = []
    for yaml_path in sorted(glob.glob(str(root / "round_*" / "*.yaml"))):
        try:
            cand = load_candidate_from_yaml(yaml_path)
            out.append((yaml_path, cand))
        except Exception as exc:
            logger.warning("Failed to load %s: %s", yaml_path, exc)
    return out


def _compute_llm_factors(
    price_df: pd.DataFrame, candidates: list,
) -> dict:
    """Import each candidate's compute_fn and compute factor values.
    Returns dict of {factor_name: DataFrame}. Candidates whose compute_fn
    fails or returns empty are skipped with a warning."""
    factors = {}
    for yaml_path, cand in candidates:
        if not cand.compute_fn_path:
            continue
        try:
            module_name, func_name = cand.compute_fn_path.split(":", 1)
            mod = importlib.import_module(module_name)
            fn = getattr(mod, func_name)
            df = fn(price_df)
            if isinstance(df, pd.DataFrame) and not df.empty:
                factors[cand.factor_name] = df
                logger.info("LLM factor ok: %s (shape %s)",
                            cand.factor_name, df.shape)
            else:
                logger.warning("LLM factor empty: %s", cand.factor_name)
        except Exception as exc:
            logger.warning("LLM factor %s compute_fn failed: %s",
                           cand.factor_name, exc)
    return factors


def _load_backfill_tickers(symbols) -> set:
    """Copy from run_model_comparison — backfill tickers flagged by
    provenance sidecar get volume-sensitive factors masked."""
    try:
        prov = pd.read_parquet("data/ref/bar_provenance.parquet")
        flagged = set(prov.loc[
            prov["source_type"] == "trades_backfill", "symbol"
        ].unique())
        return flagged & set(symbols)
    except Exception:
        return set()


def _build_panel(cfg, horizon: int, include_llm: bool, llm_only: bool):
    """Load price panel + compute classical + LLM factors + forward returns."""
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

    classical = {}
    if not llm_only:
        backfill = _load_backfill_tickers(price_df.columns)
        classical = generate_all_factors(
            price_df, vol_df, backfill_tickers=backfill,
        )
        logger.info("Classical factors: %d", len(classical))

    llm_factors = {}
    llm_names = set()
    if include_llm or llm_only:
        cands = _discover_llm_candidates()
        logger.info("Discovered %d LLM candidate YAMLs", len(cands))
        llm_factors = _compute_llm_factors(price_df, cands)
        llm_names = set(llm_factors.keys())

    # Namespace collision guard: if an LLM candidate shares a name with
    # a classical factor (shouldn't happen due to CandidateValidationError,
    # but defensive), LLM version wins.
    factors = {**classical, **llm_factors}
    logger.info("Total factors: %d (classical=%d, llm=%d)",
                len(factors), len(classical), len(llm_names))

    fwd = compute_forward_returns(price_df, [horizon])[horizon]

    # Stack to long panel
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
    return panel, list(factors.keys()), llm_names


def _train_ridge(X_train, y_train):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--test-frac", type=float, default=0.3)
    parser.add_argument("--no-llm", action="store_true",
                        help="Exclude LLM candidates (baseline)")
    parser.add_argument("--llm-only", action="store_true",
                        help="Use LLM candidates only (no classical)")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml")
    args = parser.parse_args()

    if args.no_llm and args.llm_only:
        logger.error("--no-llm and --llm-only are mutually exclusive")
        sys.exit(2)

    cfg = load_config(Path(args.config_dir))
    panel, feature_cols, llm_names = _build_panel(
        cfg, args.horizon,
        include_llm=(not args.no_llm),
        llm_only=args.llm_only,
    )
    X = panel[feature_cols].fillna(0.0)
    y = panel["fwd_return"]

    dates_sorted = sorted(panel["date"].unique())
    split_idx = int(len(dates_sorted) * (1 - args.test_frac))
    split_date = dates_sorted[split_idx]
    train_mask = panel["date"] < split_date
    test_mask = panel["date"] >= split_date
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    logger.info("Training Ridge (CV-tuned)...")
    ridge_model, ridge_alpha = _train_ridge(X_train, y_train)
    logger.info("Ridge alpha=%.3f", ridge_alpha)

    logger.info("Training XGBoost...")
    xgb_model = _train_xgb(X_train, y_train, X_test, y_test)

    ridge_r2 = float(ridge_model.score(X_test.values, y_test.values))
    xgb_r2 = float(xgb_model.score(X_test.values, y_test.values))

    logger.info("Computing Ridge perm importance...")
    ridge_imp = _perm_importance(ridge_model, X_test, y_test).sort_values(ascending=False)
    logger.info("Computing XGBoost perm importance...")
    xgb_imp = _perm_importance(xgb_model, X_test, y_test).sort_values(ascending=False)

    # Print top-K
    def _tag(name):
        return "[LLM]" if name in llm_names else "     "

    print("\n" + "=" * 86)
    print(f"LLM Cross-Signal Mining (LLM-Round 6, Topic LLM-5)")
    print(f"  horizon={args.horizon}d  n_features={len(feature_cols)}  "
          f"n_llm={len(llm_names)}")
    print(f"  train/test split: {split_date.date()}  "
          f"n_train={len(X_train)}  n_test={len(X_test)}")
    print(f"  OOS R²:  Ridge={ridge_r2:+.5f}   XGBoost={xgb_r2:+.5f}")
    print("=" * 86)

    top_k = min(args.top_k, len(ridge_imp), len(xgb_imp))
    print(f"\n{'rank':>4}  {'Ridge (perm)':<35} {'XGBoost (perm)':<35}")
    print("-" * 86)
    for i in range(top_k):
        r_name = ridge_imp.index[i]; r_val = ridge_imp.iloc[i]
        x_name = xgb_imp.index[i];   x_val = xgb_imp.iloc[i]
        print(f"{i+1:>4}  {_tag(r_name)}{r_name:<29} {r_val:+.6f}   "
              f"{_tag(x_name)}{x_name:<29} {x_val:+.6f}")

    # LLM-specific report: where do LLM candidates rank?
    print("\n" + "=" * 86)
    print("LLM Candidate Rankings (out of all features):")
    print("=" * 86)
    ridge_rank = {n: r + 1 for r, n in enumerate(ridge_imp.index)}
    xgb_rank = {n: r + 1 for r, n in enumerate(xgb_imp.index)}
    for name in sorted(llm_names):
        rr = ridge_rank.get(name, "—")
        xr = xgb_rank.get(name, "—")
        r_val = ridge_imp.get(name, np.nan)
        x_val = xgb_imp.get(name, np.nan)
        top20_flag = " 🎯" if (
            (isinstance(xr, int) and xr <= 20) or
            (isinstance(rr, int) and rr <= 20)
        ) else ""
        print(f"  {name:<32}  Ridge rank: {str(rr):>4}  "
              f"(imp={r_val:+.6f})   XGB rank: {str(xr):>4}  "
              f"(imp={x_val:+.6f}){top20_flag}")

    # Save artifacts
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    combined = pd.DataFrame({
        "ridge_imp": ridge_imp, "xgb_imp": xgb_imp,
        "is_llm": [n in llm_names for n in ridge_imp.index],
    }).fillna(0.0)
    combined.to_parquet(out / "llm_xgb_importance.parquet")
    logger.info("Saved %s", out / "llm_xgb_importance.parquet")

    # Top-20 specifically (PRD §9 LLM-5 completion signal)
    xgb_top20 = xgb_imp.head(20)
    llm_in_top20 = [n for n in xgb_top20.index if n in llm_names]
    summary = {
        "horizon":          args.horizon,
        "split_date":       str(split_date.date()),
        "n_features":       len(feature_cols),
        "n_llm_features":   len(llm_names),
        "ridge_oos_r2":     round(ridge_r2, 5),
        "xgb_oos_r2":       round(xgb_r2, 5),
        "ridge_alpha":      ridge_alpha,
        "llm_candidates_in_xgb_top20": llm_in_top20,
        "llm_candidates_in_ridge_top20": [
            n for n in ridge_imp.head(20).index if n in llm_names
        ],
    }
    (out / "llm_cross_signal_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    logger.info("Saved %s", out / "llm_cross_signal_summary.json")

    print()
    print("=" * 86)
    print(f"PRD §9 LLM-5 completion signal: "
          f"{'MET' if llm_in_top20 else 'NOT MET'} — "
          f"{len(llm_in_top20)} LLM candidate(s) in XGBoost top-20")
    if llm_in_top20:
        for n in llm_in_top20:
            print(f"  - {n}  (XGB rank {xgb_rank[n]})")
    print("=" * 86)


if __name__ == "__main__":
    main()
