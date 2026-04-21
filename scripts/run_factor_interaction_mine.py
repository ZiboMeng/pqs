#!/usr/bin/env python3
"""LLM-Round 7 tool: factor interaction mining (PRD §9 LLM-8, §7).

Takes top-K features from Round 6's XGBoost importance ranking, builds
all pairwise multiplicative interaction factors (A * B), computes
cross-sectional IC vs 21d forward return, and ranks by INCREMENTAL IC
over parents.

Output: ranked list of top interactions with parent factors, interaction
IC, parent ICs, and incremental IC (interaction − max(parent ICs)).

Per PRD §2.2: LLM is never the final judge. This tool produces the
ranked candidate list; the human (or next round) decides which
interactions deserve YAML candidate creation + full funnel.

Usage
-----
    python scripts/run_factor_interaction_mine.py
    python scripts/run_factor_interaction_mine.py --top-k 8 --out-top 10
"""

from __future__ import annotations

import argparse
import glob
import importlib
import itertools
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
logger = get_logger("run_factor_interaction_mine")


def _discover_llm_factors(price_df: pd.DataFrame) -> dict:
    """Compute all LLM candidate factors on given price panel."""
    root = Path("research/llm_candidates")
    factors = {}
    for y in sorted(glob.glob(str(root / "round_*" / "*.yaml"))):
        try:
            c = load_candidate_from_yaml(y)
            if not c.compute_fn_path:
                continue
            module_name, func_name = c.compute_fn_path.split(":", 1)
            fn = getattr(importlib.import_module(module_name), func_name)
            df = fn(price_df)
            if isinstance(df, pd.DataFrame) and not df.empty:
                factors[c.factor_name] = df
        except Exception as exc:
            logger.warning("LLM %s skipped: %s", y, exc)
    return factors


def _load_price_panel(cfg):
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    tradeable = [s for s in all_syms
                 if s not in uni.blacklist and s not in uni.macro_reference]
    pf = {}
    vf = {}
    for sym in tradeable:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                pf[sym] = df["close"]
            if "volume" in df.columns:
                vf[sym] = df["volume"]
    price_df = pd.DataFrame(pf).sort_index()
    vol_df = pd.DataFrame(vf).sort_index() if vf else None
    start = cfg.backtest.start_date or "2013-01-02"
    price_df = price_df[price_df.index >= start]
    if vol_df is not None:
        vol_df = vol_df[vol_df.index >= start]
    return price_df, vol_df


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _cs_ic(factor: pd.DataFrame, fwd: pd.DataFrame) -> float:
    """Average cross-sectional Spearman rank IC."""
    ic_vals = []
    for date in factor.index:
        if date not in fwd.index:
            continue
        c_row = factor.loc[date].dropna()
        f_row = fwd.loc[date].dropna()
        common = c_row.index.intersection(f_row.index)
        if len(common) < 5:
            continue
        rho = c_row.loc[common].rank().corr(
            f_row.loc[common].rank(), method="pearson")
        if not np.isnan(rho):
            ic_vals.append(float(rho))
    return float(np.mean(ic_vals)) if ic_vals else 0.0


# Top-K list from Round 6 XGBoost permutation importance.
# We use these specific features as interaction parents.
_DEFAULT_TOP_FEATURES = [
    "max_dd_126d",       # classical, XGB #1
    "mom_126d",          # classical, XGB #2
    "rs_vs_qqq_63d",     # LLM,       XGB #3
    "vol_63d",           # classical, XGB #4
    "spy_trend_200d",    # classical, XGB #5
    "mom_252d",          # classical, XGB #6
    "drawup_from_252d_low",  # LLM,   XGB #7
    "mom_63d",           # classical, XGB #8
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=8,
                        help="Number of parent features from Round 6 top-K")
    parser.add_argument("--out-top", type=int, default=10,
                        help="Top N interactions to report")
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--out-dir", default="data/ml/factor_interactions")
    parser.add_argument("--config-dir", default="config")
    args = parser.parse_args()

    cfg = load_config(args.config_dir)

    # Build full factor panel (classical + LLM)
    price_df, vol_df = _load_price_panel(cfg)
    logger.info("Price panel: %s", price_df.shape)
    classical = generate_all_factors(price_df, vol_df)
    llm_factors = _discover_llm_factors(price_df)
    all_factors = {**classical, **llm_factors}
    logger.info("Factors: %d classical + %d LLM = %d total",
                len(classical), len(llm_factors), len(all_factors))

    # Select top-K parents
    parents = [f for f in _DEFAULT_TOP_FEATURES[:args.top_k] if f in all_factors]
    missing = [f for f in _DEFAULT_TOP_FEATURES[:args.top_k] if f not in all_factors]
    if missing:
        logger.warning("Missing parent factors (skipping): %s", missing)
    logger.info("Parent factors: %s", parents)

    # Forward returns
    fwd = compute_forward_returns(price_df, [args.horizon])[args.horizon]

    # Parent ICs
    parent_ic = {}
    for p in parents:
        ic = _cs_ic(all_factors[p], fwd)
        parent_ic[p] = ic
        logger.info("  parent %s IC=%+.4f", p, ic)

    # Build pairwise interactions (A * B) with z-score normalization
    interactions = []
    for a, b in itertools.combinations(parents, 2):
        A = all_factors[a]
        B = all_factors[b]
        # Align on common dates × common symbols
        common_idx = A.index.intersection(B.index)
        common_cols = A.columns.intersection(B.columns)
        if len(common_idx) < 100 or len(common_cols) < 5:
            continue
        Aa = A.loc[common_idx, common_cols]
        Bb = B.loc[common_idx, common_cols]
        inter = _zscore_cs(Aa * Bb)
        ic = _cs_ic(inter, fwd)
        parent_max = max(abs(parent_ic.get(a, 0.0)), abs(parent_ic.get(b, 0.0)))
        incremental = abs(ic) - parent_max
        interactions.append({
            "pair":        f"{a} × {b}",
            "a":           a,
            "b":           b,
            "ic":          round(ic, 5),
            "a_ic":        round(parent_ic.get(a, 0.0), 5),
            "b_ic":        round(parent_ic.get(b, 0.0), 5),
            "incremental": round(incremental, 5),
            "n_dates":     int(len(common_idx)),
        })

    interactions.sort(key=lambda r: r["incremental"], reverse=True)

    # Print
    print()
    print("=" * 86)
    print(f"Factor Interaction Mining (LLM-Round 7, Topic LLM-8)")
    print(f"  horizon={args.horizon}d  n_parents={len(parents)}  "
          f"n_interactions={len(interactions)}")
    print("=" * 86)
    print()
    print("Parent factor ICs:")
    for p in parents:
        print(f"  {p:<32}  IC={parent_ic[p]:+.4f}")
    print()
    print(f"Top {args.out_top} interactions (by incremental |IC|):")
    print(f"{'rank':>4}  {'pair':<58}  {'IC':>8}  {'|parent max|':>10}  {'incr':>7}")
    print("-" * 94)
    for i, r in enumerate(interactions[:args.out_top]):
        print(f"{i+1:>4}  {r['pair']:<58}  "
              f"{r['ic']:+.5f}  {max(abs(r['a_ic']), abs(r['b_ic'])):>10.4f}  "
              f"{r['incremental']:+7.4f}")
    print()
    print(f"Bottom 5 (worst incremental):")
    for i, r in enumerate(interactions[-5:]):
        print(f"      {r['pair']:<58}  IC={r['ic']:+.5f}  incr={r['incremental']:+.4f}")
    print("=" * 86)

    # Persist
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(interactions).to_parquet(out / "interactions.parquet")
    summary = {
        "horizon":         args.horizon,
        "parents":         parents,
        "parent_ics":      {k: round(v, 5) for k, v in parent_ic.items()},
        "top_interactions": interactions[:args.out_top],
        "n_total":         len(interactions),
        "n_with_positive_incremental": sum(
            1 for r in interactions if r["incremental"] > 0
        ),
    }
    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
    print(f"Artifacts: {out}")


if __name__ == "__main__":
    main()
