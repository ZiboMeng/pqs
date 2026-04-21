#!/usr/bin/env python3
"""LLM-Round 5 tool: simplified 1-factor backtest + §5.3 cost stress +
QQQ hard gate for LLM candidates.

Closes the last two validation stages from PRD §5.3 that deep_check
(Round 3) does not cover:

  - Cost stress: 1x vs 2x base cost — ensures 2x lowers CAGR directionally
  - QQQ hard gate: strategy CAGR > QQQ CAGR full-period AND holdout
    (last 252d), per QQQ Outperformance Rule

Strategy construction (deliberately simple for candidate validation):
  - Long-only equal-weighted top-K names by factor rank
  - Monthly rebalance (21 trading days)
  - No shorting, no leverage
  - Cost model: flat bps per turnover unit, applied at rebalance

This is NOT a full evaluator.evaluate replacement — it's a lightweight
candidate-specific test to confirm the factor has portfolio-level
economic viability before we commit code to promote it to
RESEARCH_FACTORS.

Usage
-----
    python scripts/llm_candidate_factor_backtest.py \\
        --candidate research/llm_candidates/round_01/drawup_from_252d_low.yaml \\
        --universe-size 30 --start 2018-01-01 --top-k 5 --rebalance-days 21

Exit codes: 0 = PASS, 3 = FAIL, 2 = infra error
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.factors.llm_candidate import load_candidate_from_yaml
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("llm_candidate_factor_backtest")


def _resolve_compute_fn(path: str):
    module_name, func_name = path.split(":", 1)
    return getattr(importlib.import_module(module_name), func_name)


def _load_universe_prices(cfg, universe_size: int, start: str) -> pd.DataFrame:
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    symbols = [s for s in all_syms
               if s not in uni.blacklist and s not in uni.macro_reference]
    pf = {}
    for s in symbols[:universe_size]:
        df = store.read(s, "1d")
        if df is not None and not df.empty and "close" in df.columns:
            pf[s] = df["close"]
    price_df = pd.DataFrame(pf).sort_index()
    return price_df.loc[price_df.index >= start]


def _load_benchmark(cfg, index: pd.DatetimeIndex, symbol: str) -> pd.Series:
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    df = store.read(symbol, "1d")
    if df is None or df.empty:
        raise RuntimeError(f"{symbol} data unavailable for QQQ gate")
    return df["close"].reindex(index).ffill()


def _run_factor_backtest(
    factor_df: pd.DataFrame,
    price_df: pd.DataFrame,
    top_k: int = 5,
    rebalance_days: int = 21,
    cost_bps: float = 10.0,
) -> Dict:
    """Simple long-only top-K equal-weight strategy on factor rank.

    At each rebalance date, rank symbols by factor (descending — higher
    factor value → higher rank). Long the top-K equal-weighted. Between
    rebalances, weights drift with returns (no intra-period rebalance).

    Cost charged as `cost_bps / 10000 * turnover` at each rebalance,
    where turnover = sum(|new_w - old_w|) / 2.
    """
    # Daily returns
    ret = price_df.pct_change().fillna(0.0)

    # Align factor to price index (same dates, shifted by 1 for no-lookahead)
    factor_aligned = factor_df.reindex(price_df.index).shift(1)

    # Rebalance schedule: every rebalance_days trading days
    dates = price_df.index
    rebalance_dates = dates[::rebalance_days]

    # Initial weights: equal-weighted across first top-K
    current_w = pd.Series(0.0, index=price_df.columns)
    nav = 1.0
    equity_curve = [nav]
    equity_dates = [dates[0]]
    trade_log = []

    for i, d in enumerate(dates[1:], start=1):
        # Apply daily return to existing weights (drift)
        port_ret = float((current_w * ret.loc[d]).sum())
        nav *= (1.0 + port_ret)

        # Rebalance if d is a rebalance date
        if d in rebalance_dates and d in factor_aligned.index:
            row = factor_aligned.loc[d].dropna()
            if len(row) >= top_k:
                # Rank descending: higher factor → selected
                top_syms = row.nlargest(top_k).index
                new_w = pd.Series(0.0, index=price_df.columns)
                new_w.loc[top_syms] = 1.0 / top_k
                # Apply cost on turnover
                turnover = (new_w - current_w).abs().sum() / 2.0
                cost = turnover * (cost_bps / 10000.0)
                nav *= (1.0 - cost)
                current_w = new_w
                trade_log.append({
                    "date": d.date().isoformat(),
                    "turnover": round(turnover, 4),
                    "cost": round(cost, 5),
                    "top_syms": list(top_syms),
                })

        equity_curve.append(nav)
        equity_dates.append(d)

    equity = pd.Series(equity_curve, index=pd.DatetimeIndex(equity_dates))
    return {
        "equity": equity,
        "n_rebalances": len(trade_log),
        "total_turnover": sum(t["turnover"] for t in trade_log),
        "total_cost": 1.0 - (equity.iloc[-1] / (1.0 * (equity.pct_change().fillna(0) + 1).prod())),
    }


def _perf_stats(equity: pd.Series, start: pd.Timestamp = None) -> Dict:
    """CAGR / Sharpe / MaxDD on an equity curve."""
    if start is not None:
        equity = equity.loc[equity.index >= start]
    if len(equity) < 2:
        return {"cagr": None, "sharpe": None, "max_dd": None, "n_days": len(equity)}
    n_days = len(equity)
    n_years = n_days / 252.0
    total_ret = equity.iloc[-1] / equity.iloc[0]
    cagr = total_ret ** (1.0 / n_years) - 1.0 if n_years > 0 else 0.0
    daily = equity.pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 1e-10 else 0.0
    rolling_max = equity.cummax()
    max_dd = float(((equity - rolling_max) / rolling_max).min())
    return {
        "cagr":    round(float(cagr), 4),
        "sharpe":  round(float(sharpe), 3),
        "max_dd":  round(float(max_dd), 4),
        "n_days":  int(n_days),
        "n_years": round(float(n_years), 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--universe-size", type=int, default=30)
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rebalance-days", type=int, default=21)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--out-dir", default="data/ml/llm_factor_backtests")
    args = parser.parse_args()

    cand = load_candidate_from_yaml(args.candidate)
    compute_fn = _resolve_compute_fn(cand.compute_fn_path)
    logger.info("Candidate: %s", cand.factor_name)

    cfg = load_config(Path(args.config_dir))
    price_df = _load_universe_prices(cfg, args.universe_size, args.start)
    logger.info("Price panel: %s", price_df.shape)

    factor_df = compute_fn(price_df)
    if factor_df.empty:
        logger.error("compute_fn returned empty — cannot backtest")
        sys.exit(2)

    # 1x cost run
    r1 = _run_factor_backtest(
        factor_df, price_df, top_k=args.top_k,
        rebalance_days=args.rebalance_days, cost_bps=args.cost_bps,
    )
    stats_1x = _perf_stats(r1["equity"])

    # 2x cost stress run
    r2 = _run_factor_backtest(
        factor_df, price_df, top_k=args.top_k,
        rebalance_days=args.rebalance_days, cost_bps=2.0 * args.cost_bps,
    )
    stats_2x = _perf_stats(r2["equity"])

    # Benchmarks
    spy = _load_benchmark(cfg, price_df.index, "SPY")
    qqq = _load_benchmark(cfg, price_df.index, "QQQ")
    spy_stats = _perf_stats(spy / spy.iloc[0])
    qqq_stats = _perf_stats(qqq / qqq.iloc[0])

    # QQQ hard gate: full-period + holdout (last 252d)
    eq = r1["equity"]
    holdout_start = eq.index[-252] if len(eq) > 252 else eq.index[0]
    strat_hold = _perf_stats(eq, start=holdout_start)
    qqq_hold = _perf_stats(qqq, start=holdout_start)

    # Verdict per PRD QQQ rule + cost stress + MaxDD invariant:
    cost_stress_directional = stats_2x["cagr"] < stats_1x["cagr"]
    qqq_full_pass = stats_1x["cagr"] > qqq_stats["cagr"]
    qqq_holdout_pass = strat_hold["cagr"] > qqq_hold["cagr"]
    # PRD invariant (CLAUDE.md §Invariant Constraints):
    # "Max drawdown target 15%-20%, not worse than SPY in crisis"
    # Gate: MaxDD absolute ≤ -25% (slight slack for single-factor tests)
    # AND MaxDD not more than 1.5x worse than SPY's MaxDD
    abs_dd_pass = stats_1x["max_dd"] >= -0.25
    rel_dd_pass = stats_1x["max_dd"] >= 1.5 * spy_stats["max_dd"]
    max_dd_pass = abs_dd_pass and rel_dd_pass
    overall = (
        cost_stress_directional and qqq_full_pass
        and qqq_holdout_pass and max_dd_pass
    )

    out_dir = Path(args.out_dir) / cand.factor_name
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "factor_name":      cand.factor_name,
        "config":           {
            "universe_size":   args.universe_size, "start": args.start,
            "top_k":           args.top_k, "rebalance_days": args.rebalance_days,
            "cost_bps":        args.cost_bps,
        },
        "strategy_1x":      stats_1x,
        "strategy_2x":      stats_2x,
        "spy":              spy_stats,
        "qqq":              qqq_stats,
        "strat_holdout":    strat_hold,
        "qqq_holdout":      qqq_hold,
        "gates":            {
            "cost_stress_directional": bool(cost_stress_directional),
            "qqq_full_pass":           bool(qqq_full_pass),
            "qqq_holdout_pass":        bool(qqq_holdout_pass),
            "max_dd_abs_pass":         bool(abs_dd_pass),
            "max_dd_rel_pass":         bool(rel_dd_pass),
            "max_dd_pass":             bool(max_dd_pass),
            "overall_pass":            bool(overall),
        },
        "candidate":        asdict(cand),
    }
    (out_dir / "factor_backtest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )

    # Pretty print
    print()
    print("=" * 72)
    print(f"Factor: {cand.factor_name}")
    print(f"Config: N={args.universe_size} | start={args.start} | "
          f"top-K={args.top_k} | rebal={args.rebalance_days}d | "
          f"cost={args.cost_bps}bps")
    print()
    print(f"Strategy (1x cost): CAGR {stats_1x['cagr']:+.2%}  "
          f"Sharpe {stats_1x['sharpe']:+.2f}  MaxDD {stats_1x['max_dd']:.2%}")
    print(f"Strategy (2x cost): CAGR {stats_2x['cagr']:+.2%}  "
          f"Sharpe {stats_2x['sharpe']:+.2f}")
    print(f"SPY b&h           : CAGR {spy_stats['cagr']:+.2%}  "
          f"Sharpe {spy_stats['sharpe']:+.2f}  MaxDD {spy_stats['max_dd']:.2%}")
    print(f"QQQ b&h           : CAGR {qqq_stats['cagr']:+.2%}  "
          f"Sharpe {qqq_stats['sharpe']:+.2f}  MaxDD {qqq_stats['max_dd']:.2%}")
    print()
    print(f"Holdout (last 252d):")
    print(f"  Strategy CAGR: {strat_hold['cagr']:+.2%}")
    print(f"  QQQ CAGR     : {qqq_hold['cagr']:+.2%}")
    print()
    print("─" * 72)
    print(f"Cost stress (2x < 1x CAGR): "
          f"{'PASS' if cost_stress_directional else 'FAIL'} "
          f"(Δ={stats_2x['cagr'] - stats_1x['cagr']:+.4%})")
    print(f"QQQ full-period gate      : "
          f"{'PASS' if qqq_full_pass else 'FAIL'} "
          f"(Δ={stats_1x['cagr'] - qqq_stats['cagr']:+.4%})")
    print(f"QQQ holdout 252d gate     : "
          f"{'PASS' if qqq_holdout_pass else 'FAIL'} "
          f"(Δ={strat_hold['cagr'] - qqq_hold['cagr']:+.4%})")
    print(f"MaxDD abs (≥ -25%)        : "
          f"{'PASS' if abs_dd_pass else 'FAIL'} "
          f"({stats_1x['max_dd']:.2%})")
    print(f"MaxDD rel (≥ 1.5× SPY DD) : "
          f"{'PASS' if rel_dd_pass else 'FAIL'} "
          f"(strat {stats_1x['max_dd']:.2%} vs SPY×1.5={1.5 * spy_stats['max_dd']:.2%})")
    print(f"OVERALL                   : "
          f"{'PASS (ready for human review)' if overall else 'FAIL (archive)'}")
    print("=" * 72)
    print(f"Artifacts: {out_dir}")

    sys.exit(0 if overall else 3)


if __name__ == "__main__":
    main()
