#!/usr/bin/env python3
"""LLM-Round 20 tool: universe alpha/beta diagnostic.

Per user directive (R19, 2026-04-21): "当前的暴露太偏大科技 需要进行
筛选 来实现alpha正值 而不是纯赚beta". This tool quantifies which of
the current 30 universe symbols contribute ALPHA vs BETA when compared
to SPY benchmark.

For each symbol, compute:
  - CAPM beta (full-period + 252d rolling)
  - alpha (excess return vs SPY after beta adjustment)
  - absolute Sharpe
  - correlation with SPY
  - rolling 252d excess return vs SPY
  - beta concentration (top quintile high-beta symbols)

Categorization:
  - PURE_BETA: beta > 1.3 AND alpha ≤ 0 (amplifies market moves without
    producing excess return)
  - BETA_PLUS_ALPHA: beta > 1.3 AND alpha > 0 (high risk but compensated)
  - MARKET_LIKE: 0.7 ≤ beta ≤ 1.3 (roughly tracks market)
  - ALPHA_GENERATOR: 0.7 ≤ beta ≤ 1.3 AND alpha > 3% (worth keeping)
  - DIVERSIFIER: beta < 0.7 (low correlation, regime diversifier)

Output:
  - `data/ml/universe_alpha_diagnostic.csv` — symbol-level stats
  - `data/ml/universe_alpha_summary.json` — category counts + retention
    recommendation for universe redesign

This is research data for the R30 blocker report's §6.1 (universe
expansion). Does not modify any config or strategy.

Usage
-----
    python scripts/universe_alpha_diagnostic.py
    python scripts/universe_alpha_diagnostic.py --start 2020-01-01
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
from core.data.market_data_store import MarketDataStore
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("universe_alpha_diagnostic")


def _load_panel(cfg, start: str, symbols_override: list = None):
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    if symbols_override:
        # User-supplied list: keep SPY (required as benchmark); filter dupes
        symbols = list(dict.fromkeys(["SPY"] + symbols_override))
    else:
        uni = cfg.universe
        all_syms = list(dict.fromkeys(
            list(uni.seed_pool) + list(uni.sector_etfs) +
            list(uni.factor_etfs) + list(uni.cross_asset)
        ))
        symbols = [s for s in all_syms
                   if s not in uni.blacklist and s not in uni.macro_reference]
    pf = {}
    for s in symbols:
        df = store.read(s, "1d")
        if df is not None and not df.empty and "close" in df.columns:
            pf[s] = df["close"]
    price_df = pd.DataFrame(pf).sort_index()
    price_df = price_df.loc[price_df.index >= start]
    return price_df


def _beta_alpha(symbol_ret: pd.Series, spy_ret: pd.Series) -> dict:
    """CAPM beta and alpha via OLS: r_s = α + β * r_spy + ε."""
    common = symbol_ret.dropna().index.intersection(spy_ret.dropna().index)
    if len(common) < 100:
        return {"beta": None, "alpha_annual": None, "r2": None, "n": len(common)}
    s = symbol_ret.loc[common].values
    m = spy_ret.loc[common].values
    # OLS via lstsq with intercept
    X = np.column_stack([np.ones(len(m)), m])
    try:
        coef, *_ = np.linalg.lstsq(X, s, rcond=None)
    except np.linalg.LinAlgError:
        return {"beta": None, "alpha_annual": None, "r2": None, "n": len(common)}
    alpha_daily, beta = float(coef[0]), float(coef[1])
    # Residual R²
    pred = X @ coef
    ss_res = np.sum((s - pred) ** 2)
    ss_tot = np.sum((s - s.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return {
        "beta":         round(beta, 3),
        "alpha_annual": round(float(alpha_daily * 252), 4),
        "r2":           round(float(r2), 3),
        "n":            int(len(common)),
    }


def _perf_stats(prices: pd.Series) -> dict:
    """CAGR / Sharpe / MaxDD."""
    if len(prices) < 50:
        return {"cagr": None, "sharpe": None, "max_dd": None}
    nav = prices / prices.iloc[0]
    n_years = len(nav) / 252.0
    cagr = float(nav.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 else 0.0
    ret = nav.pct_change().dropna()
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 1e-10 else 0.0
    roll_max = nav.cummax()
    max_dd = float(((nav - roll_max) / roll_max).min())
    return {
        "cagr":   round(cagr, 4),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 4),
    }


def _categorize(beta: float, alpha_annual: float) -> str:
    if beta is None or alpha_annual is None:
        return "UNKNOWN"
    if beta > 1.3:
        return "BETA_PLUS_ALPHA" if alpha_annual > 0.03 else "PURE_BETA"
    if beta < 0.7:
        return "DIVERSIFIER"
    # 0.7 ≤ beta ≤ 1.3
    if alpha_annual > 0.03:
        return "ALPHA_GENERATOR"
    return "MARKET_LIKE"


def _retention_recommendation(cat: str) -> str:
    """For universe redesign: recommend KEEP / DROP / REVIEW."""
    return {
        "ALPHA_GENERATOR":  "KEEP (alpha source)",
        "BETA_PLUS_ALPHA":  "KEEP (alpha-compensated risk)",
        "DIVERSIFIER":      "KEEP (regime diversifier)",
        "MARKET_LIKE":      "REVIEW (benchmark proxy; keep at most 1-2)",
        "PURE_BETA":        "DROP (passes through beta without alpha)",
        "UNKNOWN":          "DATA_ISSUE",
    }.get(cat, "REVIEW")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated list of symbols. Overrides "
                             "config universe. SPY auto-included as "
                             "benchmark.")
    parser.add_argument("--out-name", default="universe_alpha_diagnostic",
                        help="Output file stem (default covers current "
                             "universe; use to distinguish experiments)")
    args = parser.parse_args()

    cfg = load_config(Path(args.config_dir))
    symbols_override = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else None
    )
    price_df = _load_panel(cfg, args.start, symbols_override=symbols_override)
    logger.info("Price panel: %s", price_df.shape)

    if "SPY" not in price_df.columns:
        logger.error("SPY not in panel — required for beta regression")
        sys.exit(2)

    spy = price_df["SPY"]
    spy_ret = spy.pct_change()
    spy_stats = _perf_stats(spy)

    rows = []
    for sym in price_df.columns:
        s = price_df[sym]
        s_ret = s.pct_change()
        ba = _beta_alpha(s_ret, spy_ret)
        perf = _perf_stats(s)
        cat = _categorize(ba["beta"], ba["alpha_annual"])
        rec = _retention_recommendation(cat)
        excess_cagr = (
            round(perf["cagr"] - spy_stats["cagr"], 4)
            if perf["cagr"] is not None and spy_stats["cagr"] is not None
            else None
        )
        rows.append({
            "symbol":        sym,
            "n_days":        ba["n"],
            "beta":          ba["beta"],
            "alpha_annual":  ba["alpha_annual"],
            "r2":            ba["r2"],
            "cagr":          perf["cagr"],
            "excess_cagr":   excess_cagr,
            "sharpe":        perf["sharpe"],
            "max_dd":        perf["max_dd"],
            "category":      cat,
            "recommendation": rec,
        })

    df = pd.DataFrame(rows).sort_values("beta", ascending=False, na_position="last")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / f"{args.out_name}.csv", index=False)

    # Summary
    counts = df["category"].value_counts().to_dict()
    summary = {
        "universe_size":   len(df),
        "start":           args.start,
        "spy_cagr":        spy_stats["cagr"],
        "spy_sharpe":      spy_stats["sharpe"],
        "spy_max_dd":      spy_stats["max_dd"],
        "category_counts": counts,
        "keep_symbols":    df.loc[
            df["category"].isin({"ALPHA_GENERATOR", "BETA_PLUS_ALPHA",
                                  "DIVERSIFIER"}),
            "symbol",
        ].tolist(),
        "drop_symbols":    df.loc[df["category"] == "PURE_BETA", "symbol"].tolist(),
        "review_symbols":  df.loc[df["category"] == "MARKET_LIKE", "symbol"].tolist(),
    }
    (out_dir / f"{args.out_name}_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )

    # Print
    print()
    print("=" * 94)
    print(f"Universe Alpha/Beta Diagnostic (LLM-Round 20)")
    print(f"  N={len(df)} symbols, {args.start} → {price_df.index[-1].date()}")
    print(f"  SPY: CAGR {spy_stats['cagr']:+.1%}  Sharpe {spy_stats['sharpe']:+.2f}  MaxDD {spy_stats['max_dd']:.1%}")
    print("=" * 94)
    print(f"\n{'symbol':<8} {'beta':>6} {'α/yr':>7} {'r²':>5} {'CAGR':>7} {'xCAGR':>7} {'Sh':>5} {'MaxDD':>7} {'cat':<18} rec")
    print("-" * 94)
    for _, r in df.iterrows():
        print(f"{r['symbol']:<8} "
              f"{r['beta'] if r['beta'] is not None else 'nan':>6} "
              f"{str(r['alpha_annual']) if r['alpha_annual'] is not None else 'nan':>7} "
              f"{str(r['r2']) if r['r2'] is not None else 'nan':>5} "
              f"{r['cagr'] if r['cagr'] is not None else 'nan':>7} "
              f"{str(r['excess_cagr']) if r['excess_cagr'] is not None else 'nan':>7} "
              f"{r['sharpe'] if r['sharpe'] is not None else 'nan':>5} "
              f"{r['max_dd'] if r['max_dd'] is not None else 'nan':>7} "
              f"{r['category']:<18} {r['recommendation']}")

    print()
    print("=" * 94)
    print(f"Category counts: {counts}")
    print(f"KEEP ({len(summary['keep_symbols'])}): {summary['keep_symbols']}")
    print(f"REVIEW ({len(summary['review_symbols'])}): {summary['review_symbols']}")
    print(f"DROP ({len(summary['drop_symbols'])}): {summary['drop_symbols']}")
    print("=" * 94)
    print(f"Artifacts: {out_dir}/universe_alpha_diagnostic.csv")
    print(f"           {out_dir}/universe_alpha_summary.json")


if __name__ == "__main__":
    main()
