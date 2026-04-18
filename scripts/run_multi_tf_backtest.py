#!/usr/bin/env python3
"""
Multi-timescale intraday backtest.

Uses 60m (trend) + 30m (confirmation) to generate cross-TF signals,
then executes via IntradayBacktestEngine.run_multi_day().

Daily MFS provides target weights → cross-TF signal scales them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.execution.cost_model import CostModel
from core.regime.regime_detector import RegimeDetector
from core.signals.strategies.multi_factor import MultiFactorStrategy
from core.portfolio.constructor import PortfolioConstructor
from core.backtest.backtest_engine import BacktestEngine, compute_metrics
from core.backtest.intraday_engine import IntradayBacktestEngine
from core.intraday.multi_timescale import (
    load_multi_timescale_bars, build_context, evaluate_cross_tf_signal,
)
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("multi_tf_backtest")


def main():
    cfg = load_config(Path("config"))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    uni = cfg.universe
    all_syms = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs) + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    risk_syms = [s for s in all_syms if s not in ["TLT", "IEF", "GLD", "SHY", "TQQQ", "SOXL"]
                 and s not in uni.blacklist]

    # Load daily data for MFS signal generation
    pf, of = {}, {}
    for sym in all_syms:
        df = store.read(sym, "1d")
        if df is not None and not df.empty:
            if "close" in df.columns:
                pf[sym] = df["close"]
            if "open" in df.columns:
                of[sym] = df["open"]
    price_df = pd.DataFrame(pf).sort_index()
    open_df = pd.DataFrame(of).sort_index()
    price_df = price_df[price_df.index >= "2007-01-02"]
    open_df = open_df.reindex(price_df.index)

    spy = price_df["SPY"]
    vix = store.read("^VIX", "1d")["close"].reindex(price_df.index, method="ffill").fillna(20)
    detector = RegimeDetector(cfg.regime)
    regime = detector.classify_series(spy, vix)

    # Generate daily MFS target weights
    strat = MultiFactorStrategy(
        symbols=risk_syms, top_n=4, rebalance_monthly=False, score_weighted=True,
        factor_weights={"low_vol": 0, "momentum": 0.30, "quality": 0.25,
                        "pv_div": 0.05, "rel_strength": 0.30, "market_trend": 0.10},
        min_holding_days=3, lookback_mom=189, lookback_quality=189, lookback_vol=84,
    )
    signals = strat.generate(price_df, regime)
    constructor = PortfolioConstructor(use_vol_parity=False)
    daily_weights = constructor.build(raw_signals=signals, price_df=price_df, regime_series=regime)

    # Load multi-TF intraday data
    mt_symbols = [s for s in risk_syms if store.get_last_date(s, "60m") is not None][:15]
    multi_bars = load_multi_timescale_bars(store, mt_symbols, freqs=["60m", "30m"])
    logger.info("Multi-TF data: %s", {f: len(d) for f, d in multi_bars.items()})

    if "60m" not in multi_bars:
        logger.error("No 60m data available")
        return

    # Find overlapping date range
    ref_sym = next(iter(multi_bars["60m"]))
    ref_df = multi_bars["60m"][ref_sym]
    all_dates = sorted(set(ref_df.index.date))
    logger.info("Available intraday dates: %d (%s ~ %s)", len(all_dates),
                all_dates[0], all_dates[-1])

    # Run multi-TF backtest
    cost = CostModel(cfg.cost_model)
    # C-mode: daily strategy holds positions overnight — no EOD force close
    engine = IntradayBacktestEngine(cost_model=cost, initial_capital=10000, eod_force_close=False)

    cash = 10000.0
    positions = {}
    equity_records = []
    trade_count = 0
    veto_count = 0

    for date in all_dates:
        date_ts = pd.Timestamp(date)

        # Get daily target weights for this date
        if date_ts not in daily_weights.index:
            equity_records.append((date_ts, cash))
            continue

        day_wts = daily_weights.loc[date_ts]
        base_targets = {s: float(v) for s, v in day_wts.items() if v > 0.001}

        # Build day-level intraday bars
        day_bars = {}
        for sym in set(list(base_targets) + list(positions)):
            if "60m" in multi_bars and sym in multi_bars["60m"]:
                df60 = multi_bars["60m"][sym]
                mask = df60.index.date == date
                if mask.any():
                    day_bars[sym] = df60[mask]

        if not day_bars:
            equity_records.append((date_ts, cash))
            continue

        # Evaluate cross-TF signals — regime-conditional
        adjusted_targets = {}
        ref_bars = next(iter(day_bars.values()))
        if len(ref_bars) < 2:
            equity_records.append((date_ts, cash))
            continue

        # Cross-TF signal evaluation (soft — all regimes)
        mid_bar_ts = ref_bars.index[len(ref_bars) // 2]

        for sym, base_w in base_targets.items():
            ctx = build_context(multi_bars, sym, mid_bar_ts)
            sig = evaluate_cross_tf_signal(ctx, sym, base_w)
            if sig.vetoed:
                veto_count += 1
            else:
                adjusted_targets[sym] = base_w * sig.strength

        # Execute via intraday engine (unified path for both regimes)
        result = engine.run_multi_day(
            date=date_ts, day_bars=day_bars, target_wts=adjusted_targets,
            positions=positions, cash=cash,
        )
        positions = result.eod_positions
        cash = result.eod_cash
        trade_count += result.n_trades

        eod_equity = cash
        for sym, qty in positions.items():
            if sym in day_bars and len(day_bars[sym]) > 0:
                eod_equity += qty * float(day_bars[sym]["close"].iloc[-1])
        equity_records.append((date_ts, eod_equity))

    # Results
    eq_df = pd.DataFrame(equity_records, columns=["date", "equity"]).set_index("date")
    eq_series = eq_df["equity"]

    if len(eq_series) < 2:
        logger.error("Not enough data for metrics")
        return

    m = compute_metrics(eq_series, initial_capital=10000)
    spy_period = spy.loc[eq_series.index[0]:eq_series.index[-1]]
    spy_m = compute_metrics(spy_period, initial_capital=spy_period.iloc[0])

    print("\n=== Multi-Timescale Backtest (60m + 30m) ===")
    print(f"Period: {eq_series.index[0].date()} ~ {eq_series.index[-1].date()} ({len(eq_series)} days)")
    print(f"Strategy: CAGR={m.get('cagr', 0):.1%}  Sharpe={m.get('sharpe', 0):.2f}  MaxDD={m.get('max_drawdown', 0):.1%}")
    print(f"SPY:      CAGR={spy_m.get('cagr', 0):.1%}  Sharpe={spy_m.get('sharpe', 0):.2f}  MaxDD={spy_m.get('max_drawdown', 0):.1%}")
    print(f"Trades: {trade_count}  |  Vetoed signals: {veto_count}")
    print(f"Win rate: {m.get('win_rate', 0):.1%}  |  Avg DD duration: {m.get('avg_dd_duration', 0):.0f} days")


if __name__ == "__main__":
    main()
