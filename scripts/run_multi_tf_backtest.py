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
# MultiFactorStrategy import removed 2026-04-21 (PRD M1) — builder via
# core.config.production_strategy.build_strategy_from_config is now the
# only construction path.
from core.portfolio.constructor import PortfolioConstructor
from core.backtest.backtest_engine import BacktestEngine, compute_metrics
from core.backtest.intraday_engine import IntradayBacktestEngine
from core.intraday.multi_timescale import (
    load_multi_timescale_bars, build_context,
    decide_timing, TimingAggregator, TimingThresholds,
)
from core.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("multi_tf_backtest")


def main():
    cfg = load_config(Path("config"))
    store = MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))

    # PRD M3/M13: runtime alignment check (WARN in backtest scope regardless
    # of yaml mode, same as run_backtest.py)
    from core.alignment import check_alignment, write_alignment_report, AlignmentMode
    ac = cfg.system.alignment
    mode = AlignmentMode.FAIL if (ac.mode == "fail" and not ac.live_only_fail) else AlignmentMode.WARN
    alignment = check_alignment(Path.cwd(), mode=mode)
    logger.info(alignment.summary_line())
    try:
        write_alignment_report(alignment)
    except Exception as exc:
        logger.warning("Could not write alignment artifact: %s", exc)

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
    from core.data.vix_loader import load_vix_series
    vix = load_vix_series(store, price_df.index, mode="lenient")
    detector = RegimeDetector(cfg.regime)
    regime = detector.classify_series(spy, vix)

    # PRD M1: strategy from config/production_strategy.yaml (single source of
    # truth). Previously this file had its own hardcoded factor_weights which
    # drifted from run_paper.py / run_backtest.py. All three now share.
    from core.config.production_strategy import load_production_strategy, build_strategy_from_config
    ps_cfg = load_production_strategy()
    strat = build_strategy_from_config(ps_cfg, cfg.risk, risk_syms)
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
    regime_log = []  # (date, regime, n_targets, n_adjusted, n_vetoed, strength_avg)
    # TimingAggregator replaces the legacy AttributionAggregator as part
    # of约束 3 closure — multi-TF is a timing layer, not an alpha voter.
    timing_agg = TimingAggregator()
    timing_th = TimingThresholds.from_config(cfg.risk.intraday_timing)

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
        day_regime = str(regime.loc[date_ts]) if date_ts in regime.index else "NEUTRAL"
        day_vetoes = 0
        day_strengths = []

        for sym, base_w in base_targets.items():
            ctx = build_context(multi_bars, sym, mid_bar_ts)
            decision = decide_timing(
                ctx, sym, base_weight=base_w, daily_side=1,
                thresholds=timing_th,
            )
            timing_agg.add(decision)
            if not decision.execute:
                veto_count += 1
                day_vetoes += 1
            else:
                adjusted_targets[sym] = decision.effective_weight
                day_strengths.append(decision.timing_scale)

        regime_log.append((date_ts, day_regime, len(base_targets), len(adjusted_targets),
                           day_vetoes, np.mean(day_strengths) if day_strengths else 0))

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

    # Per-regime breakdown
    if regime_log:
        rl = pd.DataFrame(regime_log, columns=["date", "regime", "n_targets", "n_adjusted", "n_vetoed", "avg_strength"])
        print("\n=== Per-Regime Cross-TF Analysis ===")
        print("%-12s %5s %7s %6s %8s" % ("Regime", "Days", "Vetoes", "Veto%", "AvgStr"))
        for reg in ["BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"]:
            sub = rl[rl["regime"] == reg]
            if len(sub) == 0:
                continue
            total_v = int(sub["n_vetoed"].sum())
            total_t = int(sub["n_targets"].sum())
            veto_pct = total_v / max(total_t, 1) * 100
            avg_s = float(sub["avg_strength"].mean())
            print("%-12s %5d %7d %5.0f%% %8.2f" % (reg, len(sub), total_v, veto_pct, avg_s))

        # Equity by regime
        eq_df["regime"] = [str(regime.loc[d]) if d in regime.index else "?" for d in eq_df.index]
        eq_df["daily_ret"] = eq_series.pct_change()
        print("\n=== Per-Regime Return ===")
        print("%-12s %8s %8s" % ("Regime", "Mean Ret", "Days"))
        for reg in ["BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"]:
            sub = eq_df[eq_df["regime"] == reg]["daily_ret"].dropna()
            if len(sub) > 0:
                ann = float(sub.mean() * 252 * 100)
                print("%-12s %+7.1f%% %8d" % (reg, ann, len(sub)))

    # Timing report (per-TF confirm/contradict/neutral counts + execute/defer
    # rates + avg timing_scale). Emphasizes the timing-layer role instead
    # of alpha-vote accounting.
    print()
    print(timing_agg.format_report())

    # Per-TF IC analysis
    _print_per_tf_ic(multi_bars, mt_symbols)
    _print_extended_ic_analysis(multi_bars, mt_symbols)

    # Cost sensitivity
    _print_cost_sensitivity(cfg, all_dates, daily_weights, multi_bars, mt_symbols)

    # Walk-forward temporal validation
    _print_walk_forward(cfg, all_dates, daily_weights, multi_bars)


def _print_per_tf_ic(
    multi_bars: dict,
    symbols: list,
):
    """Compute per-timeframe IC: bar direction vs next-bar forward return."""
    from scipy.stats import spearmanr

    print("\n=== Per-Timeframe IC Analysis ===")
    print("%-6s %8s %8s %8s %8s" % ("TF", "MeanIC", "StdIC", "IR", "N_obs"))

    for freq in ["60m", "30m", "15m"]:
        if freq not in multi_bars:
            continue

        daily_ics = []
        for sym in symbols:
            if sym not in multi_bars[freq]:
                continue
            df = multi_bars[freq][sym]
            if len(df) < 10:
                continue

            direction = np.where(
                df["close"] > df["open"] * 1.001, 1,
                np.where(df["close"] < df["open"] * 0.999, -1, 0),
            ).astype(float)
            fwd_ret = df["close"].pct_change().shift(-1).values

            valid = ~(np.isnan(direction) | np.isnan(fwd_ret))
            if valid.sum() < 10:
                continue

            rho, _ = spearmanr(direction[valid], fwd_ret[valid])
            if not np.isnan(rho):
                daily_ics.append(rho)

        if daily_ics:
            ic_arr = np.array(daily_ics)
            mean_ic = float(ic_arr.mean())
            std_ic = float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else 0
            ir = mean_ic / std_ic if std_ic > 1e-10 else 0
            print("%-6s %+8.4f %8.4f %+8.2f %8d" % (freq, mean_ic, std_ic, ir, len(ic_arr)))
        else:
            print("%-6s %8s" % (freq, "no data"))

    # Combined signal IC (60m direction * 0.6 + 30m direction * 0.4)
    if "60m" in multi_bars:
        combo_ics = []
        for sym in symbols:
            has_60 = sym in multi_bars.get("60m", {})
            has_30 = sym in multi_bars.get("30m", {})
            if not has_60:
                continue
            df60 = multi_bars["60m"][sym]
            dir_60 = np.where(
                df60["close"] > df60["open"] * 1.001, 1,
                np.where(df60["close"] < df60["open"] * 0.999, -1, 0),
            ).astype(float)
            fwd_60 = df60["close"].pct_change().shift(-1).values

            if has_30:
                df30 = multi_bars["30m"][sym]
                dir_30 = np.where(
                    df30["close"] > df30["open"] * 1.001, 1,
                    np.where(df30["close"] < df30["open"] * 0.999, -1, 0),
                ).astype(float)
                dir_30_aligned = np.full_like(dir_60, 0.0)
                idx_map = {ts: i for i, ts in enumerate(df60.index)}
                for j, ts30 in enumerate(df30.index):
                    nearest = df60.index[df60.index <= ts30]
                    if len(nearest) > 0:
                        k = idx_map.get(nearest[-1])
                        if k is not None:
                            dir_30_aligned[k] = dir_30[j]
                combo = dir_60 * 0.6 + dir_30_aligned * 0.4
            else:
                combo = dir_60

            valid = ~(np.isnan(combo) | np.isnan(fwd_60))
            if valid.sum() < 10:
                continue
            rho, _ = spearmanr(combo[valid], fwd_60[valid])
            if not np.isnan(rho):
                combo_ics.append(rho)

        if combo_ics:
            ic_arr = np.array(combo_ics)
            mean_ic = float(ic_arr.mean())
            std_ic = float(ic_arr.std(ddof=1)) if len(ic_arr) > 1 else 0
            ir = mean_ic / std_ic if std_ic > 1e-10 else 0
            print("%-6s %+8.4f %8.4f %+8.2f %8d" % ("combo", mean_ic, std_ic, ir, len(ic_arr)))


def _print_extended_ic_analysis(multi_bars: dict, symbols: list):
    """Extended IC: test multiple bar features and mean-reversion hypothesis."""
    from scipy.stats import spearmanr

    print("\n=== Extended IC Analysis (60m) ===")
    print("%-20s %8s %8s %8s %8s" % ("Feature", "MeanIC", "StdIC", "IR", "N"))

    if "60m" not in multi_bars:
        return

    features = {}
    for sym in symbols:
        if sym not in multi_bars["60m"]:
            continue
        df = multi_bars["60m"][sym]
        if len(df) < 20:
            continue

        c, o, h, l, v = df["close"].values, df["open"].values, df["high"].values, df["low"].values, df["volume"].values
        fwd = np.roll(c, -1) / c - 1
        fwd[-1] = np.nan

        feats = {
            "bar_direction": np.where(c > o * 1.001, 1, np.where(c < o * 0.999, -1, 0)).astype(float),
            "neg_bar_dir (MR)": np.where(c > o * 1.001, -1, np.where(c < o * 0.999, 1, 0)).astype(float),
            "bar_return": (c - o) / o,
            "neg_bar_return": -(c - o) / o,
            "range_expansion": (h - l) / o,
            "upper_shadow": (h - np.maximum(c, o)) / (h - l + 1e-10),
            "lower_shadow": (np.minimum(c, o) - l) / (h - l + 1e-10),
            "volume_zscore": (v - np.convolve(v, np.ones(20)/20, mode='same')) / (np.std(v[:20]) + 1e-10),
        }

        for fname, fvals in feats.items():
            if fname not in features:
                features[fname] = []
            valid = ~(np.isnan(fvals) | np.isnan(fwd))
            if valid.sum() < 20:
                continue
            rho, _ = spearmanr(fvals[valid], fwd[valid])
            if not np.isnan(rho):
                features[fname].append(rho)

    for fname, ics in features.items():
        if not ics:
            continue
        arr = np.array(ics)
        m, s = float(arr.mean()), float(arr.std(ddof=1)) if len(arr) > 1 else 0
        ir = m / s if s > 1e-10 else 0
        print("%-20s %+8.4f %8.4f %+8.2f %8d" % (fname, m, s, ir, len(arr)))


def _print_cost_sensitivity(cfg, all_dates, daily_weights, multi_bars, mt_symbols):
    """Test strategy robustness across cost multipliers."""
    import copy

    print("\n=== Cost Sensitivity Analysis ===")
    print("%-12s %8s %8s %8s %8s" % ("Cost", "CAGR", "Sharpe", "MaxDD", "Trades"))

    for mult_name, mult in [("0.5x", 0.5), ("1x (base)", 1.0), ("2x", 2.0), ("3x", 3.0)]:
        cost_cfg = copy.deepcopy(cfg.cost_model)
        for tier in cost_cfg.tiers.values():
            tier.commission_bps *= mult
            tier.slippage_interday_bps *= mult
            tier.slippage_intraday_bps *= mult
        cost = CostModel(cost_cfg)
        engine = IntradayBacktestEngine(cost_model=cost, initial_capital=10000, eod_force_close=False)

        cash = 10000.0
        positions = {}
        equity_records = []
        trade_count = 0

        for date in all_dates:
            date_ts = pd.Timestamp(date)
            if date_ts not in daily_weights.index:
                equity_records.append((date_ts, cash))
                continue

            day_wts = daily_weights.loc[date_ts]
            base_targets = {s: float(v) for s, v in day_wts.items() if v > 0.001}

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
            ref_bars = next(iter(day_bars.values()))
            if len(ref_bars) < 2:
                equity_records.append((date_ts, cash))
                continue

            mid_bar_ts = ref_bars.index[len(ref_bars) // 2]
            adjusted_targets = {}
            for sym, base_w in base_targets.items():
                ctx = build_context(multi_bars, sym, mid_bar_ts)
                decision = decide_timing(ctx, sym, base_weight=base_w,
                                         daily_side=1)
                if decision.execute:
                    adjusted_targets[sym] = decision.effective_weight

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

        eq = pd.Series([e for _, e in equity_records], index=[d for d, _ in equity_records])
        if len(eq) > 2:
            m = compute_metrics(eq, initial_capital=10000)
            print("%-12s %+7.1f%% %8.2f %7.1f%% %8d" % (
                mult_name, m.get("cagr", 0) * 100, m.get("sharpe", 0),
                m.get("max_drawdown", 0) * 100, trade_count))


def _print_walk_forward(cfg, all_dates, daily_weights, multi_bars):
    """Walk-forward validation: 4-fold temporal split on 60m bars."""
    import copy

    n = len(all_dates)
    fold_size = n // 4
    folds = []
    for i in range(4):
        s = i * fold_size
        e = (i + 1) * fold_size if i < 3 else n
        folds.append(all_dates[s:e])

    cost = CostModel(cfg.cost_model)
    print("\n=== Walk-Forward Analysis (60m temporal split, 4 folds) ===")
    print("%-8s %12s %12s %8s %8s %8s %8s" % ("Fold", "Start", "End", "Days", "CAGR", "Sharpe", "MaxDD"))

    sharpes = []
    for fi, fold_dates in enumerate(folds):
        engine = IntradayBacktestEngine(cost_model=cost, initial_capital=10000, eod_force_close=False)
        cash = 10000.0
        positions = {}
        equity_records = []

        for date in fold_dates:
            date_ts = pd.Timestamp(date)
            if date_ts not in daily_weights.index:
                equity_records.append((date_ts, cash))
                continue
            day_wts = daily_weights.loc[date_ts]
            base_targets = {s: float(v) for s, v in day_wts.items() if v > 0.001}

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
            ref_bars = next(iter(day_bars.values()))
            if len(ref_bars) < 2:
                equity_records.append((date_ts, cash))
                continue
            mid_bar_ts = ref_bars.index[len(ref_bars) // 2]

            adjusted = {}
            for sym, base_w in base_targets.items():
                ctx = build_context(multi_bars, sym, mid_bar_ts)
                decision = decide_timing(ctx, sym, base_weight=base_w,
                                         daily_side=1)
                if decision.execute:
                    adjusted[sym] = decision.effective_weight

            result = engine.run_multi_day(
                date=date_ts, day_bars=day_bars, target_wts=adjusted,
                positions=positions, cash=cash,
            )
            positions = result.eod_positions
            cash = result.eod_cash

            eod_equity = cash
            for sym, qty in positions.items():
                if sym in day_bars and len(day_bars[sym]) > 0:
                    eod_equity += qty * float(day_bars[sym]["close"].iloc[-1])
            equity_records.append((date_ts, eod_equity))

        eq = pd.Series([e for _, e in equity_records], index=[d for d, _ in equity_records])
        if len(eq) > 2:
            m = compute_metrics(eq, initial_capital=10000)
            sharpe = m.get("sharpe", 0)
            sharpes.append(sharpe)
            print("%-8s %12s %12s %8d %+7.1f%% %8.2f %7.1f%%" % (
                f"F{fi+1}", fold_dates[0], fold_dates[-1], len(fold_dates),
                m.get("cagr", 0) * 100, sharpe, m.get("max_drawdown", 0) * 100))

    if sharpes:
        pos = sum(1 for s in sharpes if s > 0)
        print(f"Positive folds: {pos}/{len(sharpes)}  |  Mean Sharpe: {np.mean(sharpes):.2f}")


if __name__ == "__main__":
    main()
