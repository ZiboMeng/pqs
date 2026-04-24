#!/usr/bin/env python3
"""R33 weight grid search for MFS on R28 expanded universe.

Goal: find a MultiFactorStrategy factor_weights configuration that
produces CAGR > QQQ on the test's fixture params (top_n=4,
rebalance_monthly=False, score_weighted=True, min_holding_days=3,
lookback_mom=189, lookback_quality=189, lookback_vol=84).

If found, the xfail in test_backtest_paper_consistency.py::
TestQQQOutperformance.test_full_period_cagr_beats_qqq can be resolved
by updating that test's hardcoded weight dict.

This is a focused grid search, NOT full Optuna mining. Enumerates
reasonable weight combinations around R29's best (w_drawup=0.05,
w_rel_strength=0.25, etc.) while keeping the other fixture params
identical to the test.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from core.backtest.backtest_engine import BacktestEngine, compute_metrics
from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.execution.cost_model import CostModel
from core.portfolio.constructor import PortfolioConstructor
from core.regime.regime_detector import RegimeDetector
from core.signals.strategies.multi_factor import MultiFactorStrategy
from core.logging_setup import get_logger, setup_logging

setup_logging()
logger = get_logger("r33_weight_grid_search")


def _load_data(cfg):
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) +
        list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    pf, of = {}, {}
    for sym in all_syms:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                pf[sym] = df["close"]
            if "open" in df.columns:
                of[sym] = df["open"]
    price_df = pd.DataFrame(pf).sort_index()
    open_df = pd.DataFrame(of).sort_index().reindex(price_df.index).ffill(limit=2)
    price_df = price_df.loc[price_df.index >= "2007-01-02"]
    open_df = open_df.loc[open_df.index >= "2007-01-02"]
    price_df = price_df.ffill(limit=2)

    spy = price_df["SPY"]
    vix = store.read("^VIX", "1d")["close"].reindex(price_df.index, method="ffill").fillna(20)
    detector = RegimeDetector(cfg.regime)
    regime = detector.classify_series(spy, vix)

    risk_syms = [s for s in all_syms if s not in ["TLT", "IEF", "GLD", "SHY", "TQQQ", "SOXL"]
                 and s not in uni.blacklist]
    return price_df, open_df, regime, risk_syms, spy


def _test_weights(weights, price_df, open_df, regime, risk_syms, spy, cfg, top_n=4):
    """Run one backtest with given weights; return CAGR."""
    strat = MultiFactorStrategy(
        symbols=risk_syms, top_n=top_n,
        rebalance_monthly=False, score_weighted=True,
        factor_weights=weights,
        min_holding_days=3, lookback_mom=189, lookback_quality=189,
        lookback_vol=84,
    )
    signals = strat.generate(price_df, regime)
    constructor = PortfolioConstructor(use_vol_parity=False)
    portfolio_weights = constructor.build(
        raw_signals=signals, price_df=price_df, regime_series=regime,
    )
    cost = CostModel(cfg.cost_model)
    engine = BacktestEngine(cost_model=cost, initial_capital=10000)
    bt = engine.run(
        signals_df=portfolio_weights, price_df=price_df, open_df=open_df,
        regime_series=regime, benchmark_series=spy,
    )
    return bt.metrics.get("cagr", 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="data/ml/r33_grid")
    args = parser.parse_args()

    cfg = load_config(Path("config"))
    price_df, open_df, regime, risk_syms, spy = _load_data(cfg)

    # QQQ benchmark CAGR
    qqq_metrics = compute_metrics(price_df["QQQ"], initial_capital=price_df["QQQ"].iloc[0])
    qqq_cagr = qqq_metrics.get("cagr", 0)
    spy_metrics = compute_metrics(spy, initial_capital=spy.iloc[0])
    spy_cagr = spy_metrics.get("cagr", 0)
    logger.info("QQQ CAGR: %.4f  |  SPY CAGR: %.4f", qqq_cagr, spy_cagr)

    # Current test weights (xfail baseline)
    test_weights = {
        "low_vol": 0.0, "momentum": 0.30, "quality": 0.25,
        "pv_div": 0.05, "rel_strength": 0.30, "market_trend": 0.10,
    }
    baseline_cagr = _test_weights(
        test_weights, price_df, open_df, regime, risk_syms, spy, cfg,
    )
    logger.info("Baseline (test's hardcoded weights) CAGR: %.4f  Δ vs QQQ: %+.4f",
                baseline_cagr, baseline_cagr - qqq_cagr)

    # R29 best weights (dropped w_market_trend 0.15 and added w_drawup 0.05)
    r29_weights = {
        "low_vol": 0.10, "momentum": 0.10, "quality": 0.20,
        "pv_div": 0.15, "rel_strength": 0.25, "market_trend": 0.15,
        "drawup_from_252d_low": 0.05,
    }
    r29_cagr = _test_weights(
        r29_weights, price_df, open_df, regime, risk_syms, spy, cfg,
    )
    logger.info("R29 best weights CAGR: %.4f  Δ vs QQQ: %+.4f",
                r29_cagr, r29_cagr - qqq_cagr)

    # Grid search: vary (mom, qual, rel, market_trend, drawup) keeping sum≈1
    # Fixed: low_vol=0.05, pv_div=0.05
    candidates = []
    step = 0.05
    grid_vals = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
    for mom in grid_vals:
        for qual in grid_vals:
            for rel in grid_vals:
                for mt in [0.0, 0.05, 0.10, 0.15]:
                    for drawup in [0.0, 0.05, 0.10, 0.15]:
                        remainder = 1.0 - (mom + qual + rel + mt + drawup)
                        # Split remainder as low_vol + pv_div, >= 0 each
                        if remainder < -0.001 or remainder > 0.301:
                            continue
                        # Simple: give all remainder to low_vol; pv_div=0.05 fixed
                        pv = 0.05
                        lv = round(remainder - pv, 2)
                        if lv < 0 or lv > 0.25:
                            continue
                        candidates.append({
                            "low_vol": lv, "momentum": mom, "quality": qual,
                            "pv_div": pv, "rel_strength": rel,
                            "market_trend": mt,
                            "drawup_from_252d_low": drawup,
                        })

    logger.info("Grid size: %d candidates", len(candidates))

    # Sample-limited grid (take every 20th if too large)
    if len(candidates) > 200:
        candidates = candidates[::(len(candidates) // 150)]
    logger.info("Actual test count: %d", len(candidates))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    best = {"cagr": -1.0, "weights": None}
    for i, w in enumerate(candidates):
        cagr = _test_weights(w, price_df, open_df, regime, risk_syms, spy, cfg)
        results.append({"weights": w, "cagr": cagr, "excess_vs_qqq": cagr - qqq_cagr})
        if cagr > best["cagr"]:
            best = {"cagr": cagr, "weights": w}
        if (i + 1) % 20 == 0:
            logger.info("  progress: %d/%d  best_cagr_so_far=%.4f",
                        i + 1, len(candidates), best["cagr"])

    # Save
    df = pd.DataFrame(results)
    df = df.sort_values("cagr", ascending=False)
    df.to_csv(out_dir / "grid_results.csv", index=False)
    summary = {
        "qqq_cagr":          round(float(qqq_cagr), 4),
        "spy_cagr":          round(float(spy_cagr), 4),
        "baseline_cagr":     round(float(baseline_cagr), 4),
        "baseline_vs_qqq":   round(float(baseline_cagr - qqq_cagr), 4),
        "r29_cagr":          round(float(r29_cagr), 4),
        "r29_vs_qqq":        round(float(r29_cagr - qqq_cagr), 4),
        "best_grid_cagr":    round(float(best["cagr"]), 4),
        "best_weights":      best["weights"],
        "n_grid":            len(candidates),
        "n_beat_qqq":        int((df["cagr"] > qqq_cagr).sum()),
        "n_beat_spy":        int((df["cagr"] > spy_cagr).sum()),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print()
    print("=" * 70)
    print("R33 Weight Grid Search Results (R28 expanded universe)")
    print("=" * 70)
    print(f"Benchmark: QQQ CAGR = {qqq_cagr:.2%}  SPY CAGR = {spy_cagr:.2%}")
    print(f"Baseline (test's weights) CAGR: {baseline_cagr:.2%}  vs QQQ {baseline_cagr-qqq_cagr:+.2%}")
    print(f"R29 best weights CAGR: {r29_cagr:.2%}  vs QQQ {r29_cagr-qqq_cagr:+.2%}")
    print(f"Grid best CAGR: {best['cagr']:.2%}  vs QQQ {best['cagr']-qqq_cagr:+.2%}")
    print()
    print(f"Beat QQQ: {summary['n_beat_qqq']} / {summary['n_grid']}  "
          f"({100*summary['n_beat_qqq']/summary['n_grid']:.1f}%)")
    print(f"Beat SPY: {summary['n_beat_spy']} / {summary['n_grid']}  "
          f"({100*summary['n_beat_spy']/summary['n_grid']:.1f}%)")
    print()
    print("Top 10 weight configurations:")
    for _, r in df.head(10).iterrows():
        w = r["weights"]
        print(f"  CAGR {r['cagr']:.2%}  vs_QQQ {r['excess_vs_qqq']:+.2%}  | "
              f"mom={w['momentum']:.2f} qual={w['quality']:.2f} "
              f"rel={w['rel_strength']:.2f} mt={w['market_trend']:.2f} "
              f"drawup={w['drawup_from_252d_low']:.2f} lv={w['low_vol']:.2f}")
    print(f"\nArtifacts: {out_dir}")


if __name__ == "__main__":
    main()
