#!/usr/bin/env python3
"""LLM-Round 9 tool: multi-factor composite backtest for LLM candidates
(PRD §7 cross-signal, Round 5 MaxDD follow-up).

Round 5 established that `drawup_from_252d_low` alone produces MaxDD
-77.79% despite strong IC. Round 8 established that regime-gating
alone can't fix this. This tool tests the hypothesis:

  "drawup_from_252d_low composited with risk factors (low-vol +
   market_trend) recovers an acceptable MaxDD."

Composite construction:
  - Each component factor is z-scored cross-sectionally per date
  - Weighted sum produces composite z-score
  - Final rank by composite z-score → top-K equal-weight long-only
  - Same 5-gate verdict as factor_backtest: cost stress, QQQ full,
    QQQ holdout, MaxDD abs, MaxDD rel

Factor sources:
  - classical RESEARCH factors (via generate_all_factors)
  - LLM candidates (via research/llm_candidates/round_*/*.yaml)
  - component with negative weight → factor value is sign-flipped
    (supports "low_vol" = -vol_63d style inversion)

Does NOT modify PRODUCTION_FACTORS or MultiFactorStrategy. Pure
research tool.

Usage
-----
    # Baseline: drawup alone (replicate Round 5 FAIL)
    python scripts/llm_composite_backtest.py \\
        --components drawup_from_252d_low:1.0

    # Composite A: drawup + low-vol-proxy + market-trend
    python scripts/llm_composite_backtest.py \\
        --components drawup_from_252d_low:0.3,vol_63d:-0.3,spy_trend_200d:0.4

Exit codes: 0 = PASS, 3 = FAIL, 2 = infra error
"""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.factor_generator import generate_all_factors
from core.factors.llm_candidate import load_candidate_from_yaml
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("llm_composite_backtest")


def _parse_components(spec: str) -> List[Tuple[str, float]]:
    """Parse 'name1:w1,name2:w2' format."""
    out = []
    for part in spec.split(","):
        if ":" not in part:
            raise ValueError(f"component '{part}' missing ':weight'")
        name, w = part.rsplit(":", 1)
        out.append((name.strip(), float(w)))
    return out


def _load_universe_prices(cfg, universe_size: int, start: str) -> pd.DataFrame:
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    symbols = [s for s in all_syms
               if s not in uni.blacklist and s not in uni.macro_reference]
    pf, vf = {}, {}
    for s in symbols[:universe_size]:
        df = store.read(s, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                pf[s] = df["close"]
            if "volume" in df.columns:
                vf[s] = df["volume"]
    price_df = pd.DataFrame(pf).sort_index()
    vol_df = pd.DataFrame(vf).sort_index() if vf else None
    price_df = price_df.loc[price_df.index >= start]
    if vol_df is not None:
        vol_df = vol_df.loc[vol_df.index >= start]
    return price_df, vol_df


def _load_benchmark(cfg, index: pd.DatetimeIndex, symbol: str) -> pd.Series:
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    df = store.read(symbol, "1d")
    if df is None or df.empty:
        raise RuntimeError(f"{symbol} data unavailable")
    return df["close"].reindex(index).ffill()


def _zscore_cs(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def _build_factor_registry(price_df: pd.DataFrame, vol_df) -> dict:
    """Load both classical RESEARCH_FACTORS and all LLM candidates."""
    classical = generate_all_factors(price_df, vol_df)
    llm = {}
    for y in sorted(glob.glob("research/llm_candidates/round_*/*.yaml")):
        try:
            c = load_candidate_from_yaml(y)
            if not c.compute_fn_path:
                continue
            module_name, func_name = c.compute_fn_path.split(":", 1)
            fn = getattr(importlib.import_module(module_name), func_name)
            df = fn(price_df)
            if isinstance(df, pd.DataFrame) and not df.empty:
                llm[c.factor_name] = df
        except Exception as exc:
            logger.warning("Skipping LLM %s: %s", y, exc)
    all_f = {**classical, **llm}
    logger.info("Loaded %d classical + %d LLM = %d factors",
                len(classical), len(llm), len(all_f))
    return all_f


def _build_composite(
    registry: dict, components: List[Tuple[str, float]],
    index: pd.DatetimeIndex, columns: pd.Index,
) -> pd.DataFrame:
    """Build weighted composite z-score. Missing components logged and skipped."""
    zcomposite = pd.DataFrame(0.0, index=index, columns=columns)
    used = []
    for name, w in components:
        if name not in registry:
            logger.error("component '%s' not in registry — aborting", name)
            sys.exit(2)
        fdf = registry[name].reindex(index=index, columns=columns)
        zscore = _zscore_cs(fdf).fillna(0.0)
        zcomposite = zcomposite + w * zscore
        used.append(name)
        logger.info("  component %s (w=%+.3f) applied", name, w)
    return _zscore_cs(zcomposite)


def _run_backtest(
    factor_df: pd.DataFrame, price_df: pd.DataFrame,
    top_k: int = 5, rebalance_days: int = 21, cost_bps: float = 10.0,
) -> Dict:
    ret = price_df.pct_change().fillna(0.0)
    factor_aligned = factor_df.reindex(price_df.index).shift(1)
    dates = price_df.index
    rebalance_dates = dates[::rebalance_days]
    current_w = pd.Series(0.0, index=price_df.columns)
    nav = 1.0
    equity_curve, equity_dates = [nav], [dates[0]]
    turnover_total = 0.0
    for d in dates[1:]:
        port_ret = float((current_w * ret.loc[d]).sum())
        nav *= (1.0 + port_ret)
        if d in rebalance_dates and d in factor_aligned.index:
            row = factor_aligned.loc[d].dropna()
            if len(row) >= top_k:
                top_syms = row.nlargest(top_k).index
                new_w = pd.Series(0.0, index=price_df.columns)
                new_w.loc[top_syms] = 1.0 / top_k
                turnover = (new_w - current_w).abs().sum() / 2.0
                cost = turnover * (cost_bps / 10000.0)
                nav *= (1.0 - cost)
                current_w = new_w
                turnover_total += turnover
        equity_curve.append(nav)
        equity_dates.append(d)
    return {
        "equity": pd.Series(equity_curve, index=pd.DatetimeIndex(equity_dates)),
        "turnover_total": float(turnover_total),
    }


def _perf_stats(equity: pd.Series, start=None) -> Dict:
    if start is not None:
        equity = equity.loc[equity.index >= start]
    if len(equity) < 2:
        return {"cagr": None, "sharpe": None, "max_dd": None}
    n_years = len(equity) / 252.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / n_years) - 1.0
    daily = equity.pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 1e-10 else 0.0
    rolling_max = equity.cummax()
    max_dd = float(((equity - rolling_max) / rolling_max).min())
    return {
        "cagr": round(float(cagr), 4),
        "sharpe": round(float(sharpe), 3),
        "max_dd": round(float(max_dd), 4),
        "n_days": int(len(equity)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--components", required=True,
                        help="Format: 'name1:w1,name2:w2,...'")
    parser.add_argument("--universe-size", type=int, default=30)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rebalance-days", type=int, default=21)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--out-name", default=None,
                        help="Output directory name (default auto)")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--out-dir", default="data/ml/llm_composite_backtests")
    args = parser.parse_args()

    components = _parse_components(args.components)
    if args.out_name:
        name = args.out_name
    else:
        name = "__".join(f"{n}_{w}" for n, w in components)[:80]

    cfg = load_config(Path(args.config_dir))
    price_df, vol_df = _load_universe_prices(
        cfg, args.universe_size, args.start,
    )
    logger.info("Price panel: %s", price_df.shape)
    registry = _build_factor_registry(price_df, vol_df)

    composite = _build_composite(
        registry, components, price_df.index, price_df.columns,
    )

    # 1x + 2x cost runs
    r1 = _run_backtest(composite, price_df, top_k=args.top_k,
                       rebalance_days=args.rebalance_days,
                       cost_bps=args.cost_bps)
    stats_1x = _perf_stats(r1["equity"])
    r2 = _run_backtest(composite, price_df, top_k=args.top_k,
                       rebalance_days=args.rebalance_days,
                       cost_bps=2.0 * args.cost_bps)
    stats_2x = _perf_stats(r2["equity"])

    # Benchmarks
    spy = _load_benchmark(cfg, price_df.index, "SPY")
    qqq = _load_benchmark(cfg, price_df.index, "QQQ")
    spy_stats = _perf_stats(spy / spy.iloc[0])
    qqq_stats = _perf_stats(qqq / qqq.iloc[0])

    # Holdout
    eq = r1["equity"]
    holdout_start = eq.index[-252] if len(eq) > 252 else eq.index[0]
    strat_hold = _perf_stats(eq, start=holdout_start)
    qqq_hold = _perf_stats(qqq, start=holdout_start)

    # Gates
    cost_pass = stats_2x["cagr"] < stats_1x["cagr"]
    qqq_full = stats_1x["cagr"] > qqq_stats["cagr"]
    qqq_ho = strat_hold["cagr"] > qqq_hold["cagr"]
    max_dd_abs = stats_1x["max_dd"] >= -0.25
    max_dd_rel = stats_1x["max_dd"] >= 1.5 * spy_stats["max_dd"]
    overall = cost_pass and qqq_full and qqq_ho and max_dd_abs and max_dd_rel

    out_dir = Path(args.out_dir) / name
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "components": [{"name": n, "weight": w} for n, w in components],
        "config": {
            "universe_size": args.universe_size, "start": args.start,
            "top_k": args.top_k, "rebalance_days": args.rebalance_days,
            "cost_bps": args.cost_bps,
        },
        "strategy_1x": stats_1x, "strategy_2x": stats_2x,
        "spy": spy_stats, "qqq": qqq_stats,
        "strat_holdout": strat_hold, "qqq_holdout": qqq_hold,
        "total_turnover": round(r1["turnover_total"], 3),
        "gates": {
            "cost_stress":     bool(cost_pass),
            "qqq_full":        bool(qqq_full),
            "qqq_holdout":     bool(qqq_ho),
            "max_dd_abs":      bool(max_dd_abs),
            "max_dd_rel":      bool(max_dd_rel),
            "overall":         bool(overall),
        },
    }
    (out_dir / "composite_backtest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )

    print()
    print("=" * 78)
    print(f"Composite: {name}")
    components_str = " + ".join(f"{n}×{w:+.2f}" for n, w in components)
    print(f"  {components_str}")
    print(f"  N={args.universe_size}  top-K={args.top_k}  "
          f"rebal={args.rebalance_days}d  cost={args.cost_bps}bps")
    print()
    print(f"Strategy (1x cost): CAGR {stats_1x['cagr']:+.2%}  "
          f"Sharpe {stats_1x['sharpe']:+.2f}  MaxDD {stats_1x['max_dd']:.2%}")
    print(f"Strategy (2x cost): CAGR {stats_2x['cagr']:+.2%}")
    print(f"SPY b&h           : CAGR {spy_stats['cagr']:+.2%}  "
          f"MaxDD {spy_stats['max_dd']:.2%}")
    print(f"QQQ b&h           : CAGR {qqq_stats['cagr']:+.2%}  "
          f"MaxDD {qqq_stats['max_dd']:.2%}")
    print(f"Holdout 252d: strat {strat_hold['cagr']:+.2%}  vs  "
          f"QQQ {qqq_hold['cagr']:+.2%}")
    print(f"Total turnover: {r1['turnover_total']:.1f}")
    print()
    print("─" * 78)
    print(f"cost (2x<1x):      {'PASS' if cost_pass else 'FAIL'}   "
          f"Δ={stats_2x['cagr'] - stats_1x['cagr']:+.4%}")
    print(f"QQQ full:          {'PASS' if qqq_full else 'FAIL'}   "
          f"Δ={stats_1x['cagr'] - qqq_stats['cagr']:+.4%}")
    print(f"QQQ holdout 252d:  {'PASS' if qqq_ho else 'FAIL'}   "
          f"Δ={strat_hold['cagr'] - qqq_hold['cagr']:+.4%}")
    print(f"MaxDD abs (≥-25%): {'PASS' if max_dd_abs else 'FAIL'}   "
          f"{stats_1x['max_dd']:.2%}")
    print(f"MaxDD rel (≥1.5×SPY DD): {'PASS' if max_dd_rel else 'FAIL'}   "
          f"strat {stats_1x['max_dd']:.2%} vs SPY×1.5={1.5 * spy_stats['max_dd']:.2%}")
    print(f"OVERALL:           {'PASS' if overall else 'FAIL'}")
    print("=" * 78)
    print(f"Artifacts: {out_dir}")

    sys.exit(0 if overall else 3)


if __name__ == "__main__":
    main()
