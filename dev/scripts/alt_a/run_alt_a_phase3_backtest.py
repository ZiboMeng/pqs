"""Phase 3 Step B: alt-A 8-year backtest on 53-stock universe 2018-2025.

Per `docs/memos/20260512-alt_a_phase_2_closeout.md` §4 Phase 3 Step B.
Generates NAV series for Track A acceptance + anti-sibling NAV correlation.

PRD §11 LOCKED:
  - Universe: 53-stock cycle04+ (PIT filter for IPOs / renames / splits)
  - Holding: 5d hard cap
  - Entry: T+1 first-60m-bar (alt_a_intraday_inputs)
  - Cost: 2.5bp slip per leg

Output:
  data/audit/alt_a_phase3_nav.parquet  (alt-A NAV series + trades)
  data/audit/alt_a_phase3_summary.json (summary metrics)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJ))

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.data.bar_store import BarStore
from core.backtest.backtest_engine import BacktestEngine
from core.backtest.intraday_reversal_bridge import (
    build_alt_a_cost_model, build_intraday_reversal_signals,
    estimate_alt_a_turnover,
)
from core.factors.alt_a_intraday_inputs import compute_alt_a_intraday_inputs
from core.factors.factor_generator import generate_all_factors
from core.signals.strategies.intraday_reversal import (
    IntradayReversalConfig, IntradayReversalStrategy,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


ALT_A_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "PWR", "WMT", "GILD",
    "JNJ", "VZ", "OXY", "GIS", "WEC", "EA", "ED", "DG", "CLX", "GS", "MS", "C",
    "LRCX", "KLAC", "CAT", "MU", "AVGO", "TER", "TJX", "TKO", "TRGP", "TRV",
    "TSN", "TT", "TXN", "UNP", "VICI", "COST", "AXP", "BKNG", "APD", "ABT",
    "CMG", "COP", "UNH", "LLY", "ISRG", "NEE", "MCK", "CME", "TMO", "A", "ACGL",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-02")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--initial-capital", type=float, default=10_000.0)
    args = ap.parse_args()

    cfg = load_config(PROJ / "config")
    store = BarStore(root=Path(cfg.system.paths.data_dir))

    # Load 2-month warmup buffer for factor_generator rolling windows
    warmup = (pd.Timestamp(args.start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    end = args.end

    log.info("Phase 3 Step B: alt-A 8-year backtest")
    log.info(f"  Universe: {len(ALT_A_UNIVERSE)} stocks")
    log.info(f"  Range: {args.start} → {end} (warmup from {warmup})")

    # Step 1: Load daily panel
    log.info("Step 1: load daily panels...")
    t0 = time.time()
    daily_close, daily_vol, daily_open = {}, {}, {}
    for sym in ALT_A_UNIVERSE:
        try:
            df = store.load(sym, freq="1d", adjusted=True)
        except Exception as e:
            log.warning(f"  {sym}: load fail: {e}")
            continue
        if df is None or df.empty:
            log.warning(f"  {sym}: empty daily")
            continue
        df.index = pd.to_datetime(df.index)
        df = df[(df.index >= warmup) & (df.index <= end)]
        if df.empty:
            continue
        daily_close[sym] = df["close"]
        daily_vol[sym] = df.get("volume", pd.Series(0, index=df.index))
        daily_open[sym] = df.get("open", df["close"])
    close = pd.DataFrame(daily_close).sort_index()
    vol = pd.DataFrame(daily_vol).reindex(close.index)
    opn = pd.DataFrame(daily_open).reindex(close.index)
    log.info(f"  Daily panel: {close.shape} ({time.time()-t0:.1f}s)")
    log.info(f"  Symbols with data: {len(close.columns)}/{len(ALT_A_UNIVERSE)}")

    # Step 2: Compute factors
    log.info("Step 2: compute factors (weekly_reversal_signal_5d + vol_21d)...")
    t0 = time.time()
    factors = generate_all_factors(close, volume_df=vol, open_df=opn)
    if "weekly_reversal_signal_5d" not in factors:
        log.error("weekly_reversal_signal_5d not in factor output")
        return 1
    if "vol_21d" not in factors:
        log.error("vol_21d not in factor output")
        return 1
    wr = factors["weekly_reversal_signal_5d"]
    vol_21d = factors["vol_21d"]
    log.info(f"  Factors computed ({time.time()-t0:.1f}s)")

    # Step 3: Load 60m bars + compute intraday inputs
    log.info("Step 3: load 60m bars + compute intraday inputs...")
    t0 = time.time()
    bars_60m = {}
    for sym in close.columns:
        try:
            df60 = store.load(sym, freq="60m")
        except Exception as e:
            continue
        if df60 is None or df60.empty:
            continue
        df60.index = pd.to_datetime(df60.index)
        df60 = df60[(df60.index >= args.start) & (df60.index <= end)]
        if not df60.empty:
            bars_60m[sym] = df60
    log.info(f"  60m bars loaded for {len(bars_60m)} symbols")

    # Daily dates for analysis (exclude warmup)
    dates = close.index[(close.index >= args.start) & (close.index <= end)]
    log.info(f"  Daily date grid: {len(dates)} business days")

    intra = compute_alt_a_intraday_inputs(bars_60m, dates, rolling_window_days=20)
    iv = intra["intraday_volume_60m_zscore"]
    er = intra["early_session_return_pct"]
    log.info(f"  intraday_volume_60m_zscore: {iv.shape}; non-NaN: {iv.notna().sum().sum()}")
    log.info(f"  early_session_return_pct: {er.shape}; non-NaN: {er.notna().sum().sum()}")
    log.info(f"  ({time.time()-t0:.1f}s)")

    # Step 4: Bridge
    log.info("Step 4: bridge → signals_df...")
    t0 = time.time()
    wr_in = wr.reindex(dates)
    vol_in = vol_21d.reindex(dates)
    strat = IntradayReversalStrategy(IntradayReversalConfig(
        setup_quantile_threshold=0.05,
        vol_filter_min_pct=0.30,
        volume_surge_at_open_60m_min=1.5,
        top_n=5,
        holding_period_max_days=5,
    ))
    signals = build_intraday_reversal_signals(
        strat, wr_in, vol_in, iv, er, dates,
    )
    nonzero_rows = (signals != 0).any(axis=1).sum()
    log.info(f"  Signals: {signals.shape}; rows with positions: {nonzero_rows}")
    log.info(f"  Total weight days: {signals.sum().sum():.1f}")
    log.info(f"  Annualized turnover: {estimate_alt_a_turnover(signals):.1f}x")
    log.info(f"  ({time.time()-t0:.1f}s)")

    # Step 5: Backtest
    log.info("Step 5: BacktestEngine.run(execution_freq='intraday')...")
    t0 = time.time()
    cost_model = build_alt_a_cost_model(list(close.columns), intraday_slip_bps=2.5)
    bt = BacktestEngine(
        cost_model=cost_model,
        initial_capital=args.initial_capital,
        integer_shares=False,
        execution_freq="intraday",
    )
    # Subset price/open to analysis range
    close_in = close.reindex(dates)
    opn_in = opn.reindex(dates)
    result = bt.run(
        signals_df=signals,
        price_df=close_in,
        open_df=opn_in,
        vix_series=pd.Series(15.0, index=dates),
    )
    log.info(f"  Backtest done ({time.time()-t0:.1f}s)")

    # Step 6: Save
    log.info("Step 6: save NAV + summary...")
    out_dir = PROJ / "data/audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    nav_df = pd.DataFrame({
        "equity": result.equity_curve,
        "cash": result.cash_curve,
    })
    nav_df.to_parquet(out_dir / "alt_a_phase3_nav.parquet")
    log.info(f"  Saved NAV: {out_dir/'alt_a_phase3_nav.parquet'}")

    # Compute summary metrics
    final = float(result.equity_curve.iloc[-1])
    initial = float(args.initial_capital)
    total_ret_pct = (final - initial) / initial * 100
    n_trades = len(result.trades)
    # Drawdown
    nav = result.equity_curve
    peak = nav.cummax()
    dd = (nav - peak) / peak
    max_dd = float(dd.min())

    # vs SPY
    try:
        spy_df = store.load("SPY", freq="1d", adjusted=True)
        spy_df.index = pd.to_datetime(spy_df.index)
        spy_in = spy_df.loc[(spy_df.index >= args.start) & (spy_df.index <= end), "close"]
        spy_total_ret_pct = (spy_in.iloc[-1] - spy_in.iloc[0]) / spy_in.iloc[0] * 100
    except Exception:
        spy_total_ret_pct = None

    summary = {
        "lineage": "alt-archetype-intraday-reversal-2026-05-12",
        "phase": "Phase 3 Step B",
        "universe_size": len(close.columns),
        "date_range": [args.start, end],
        "initial_capital": initial,
        "final_equity": final,
        "total_return_pct": total_ret_pct,
        "max_dd_pct": max_dd * 100,
        "n_trades": n_trades,
        "signal_days_with_positions": int(nonzero_rows),
        "total_business_days": int(len(dates)),
        "annualized_turnover": float(estimate_alt_a_turnover(signals)),
        "spy_total_return_pct": spy_total_ret_pct,
        "vs_spy_pct": total_ret_pct - spy_total_ret_pct if spy_total_ret_pct is not None else None,
    }
    summary_path = out_dir / "alt_a_phase3_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    log.info(f"  Saved summary: {summary_path}")

    log.info("=" * 60)
    log.info(f"alt-A Phase 3 Step B verdict:")
    log.info(f"  Final equity: ${final:,.2f}")
    log.info(f"  Total return: {total_ret_pct:+.2f}%")
    log.info(f"  SPY return:   {spy_total_ret_pct:+.2f}%" if spy_total_ret_pct else "  SPY: N/A")
    log.info(f"  vs SPY:       {total_ret_pct - spy_total_ret_pct:+.2f}%" if spy_total_ret_pct else "")
    log.info(f"  Max DD:       {max_dd*100:+.2f}%")
    log.info(f"  Trades:       {n_trades}")
    log.info(f"  Signal-days:  {nonzero_rows}/{len(dates)}")
    log.info(f"  Turnover:     {estimate_alt_a_turnover(signals):.1f}x annualized")
    return 0


if __name__ == "__main__":
    sys.exit(main())
