"""M11b parity test — BacktestEngine vs PaperTradingEngine.

Goal: with identical signals, prices, opens, and cost model, the two
engines must produce equity curves that match within tight tolerance
(every-day < 1 bps, cumulative < 5 bps). Pre-M11b-fix this would FAIL
because `run_day_daily`:
  (a) marked EOD equity at the prev-day close instead of exec-day close,
      producing a one-day-stale equity series, AND
  (b) stamped `signal_date = date` (where `date` was the execution day),
      so fill_date came out as exec_date + 1 BDay instead of exec_date.

The test deliberately uses a gap-open scenario (T+1 open ≠ T close) so
that the prev-vs-eod-close mismatch from bug (a) shows up as a real
equity divergence rather than coincidentally cancelling.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker


def _zero_cost_model() -> CostModel:
    cm = CostModel(load_config(Path("config")).cost_model)
    return cm


def _build_panel():
    """5 trading days, 3 symbols, deliberate gap-open on day 1 and day 3."""
    idx = pd.bdate_range("2024-01-02", periods=6)
    closes = pd.DataFrame(
        {
            "AAA": [100.0, 105.0, 102.0, 108.0, 110.0, 112.0],
            "BBB": [50.0, 49.0, 52.0, 51.0, 53.0, 54.0],
            "CCC": [200.0, 198.0, 205.0, 207.0, 210.0, 212.0],
        },
        index=idx,
    )
    # Gap-opens: the open of day t can differ materially from close of day t-1.
    opens = pd.DataFrame(
        {
            "AAA": [100.0, 103.0, 104.0, 106.0, 109.0, 111.0],  # gaps on D1, D3
            "BBB": [50.0, 49.5, 51.0, 51.5, 52.5, 53.5],
            "CCC": [200.0, 197.0, 203.0, 206.0, 209.0, 211.0],
        },
        index=idx,
    )
    # Static rebalance signal — non-trivial mix to force fills.
    signals = pd.DataFrame(
        {"AAA": 0.4, "BBB": 0.3, "CCC": 0.3},
        index=idx,
    )
    return idx, signals, closes, opens


def _run_paper_engine_day_by_day(tmp_path, signals, closes, opens):
    """Drive PaperTradingEngine.run_day_daily exactly as scripts/run_paper.py does."""
    cm = _zero_cost_model()
    db = tmp_path / "paper_state.db"
    tracker = PnLTracker()
    eng = PaperTradingEngine(
        cost_model=cm, pnl_tracker=tracker, db_path=db,
        initial_capital=100_000.0, integer_shares=False,
        kill_switch=None,
    )

    dates = signals.index
    for i in range(len(dates) - 1):
        date_t = dates[i]      # signal day
        date_tp1 = dates[i + 1]  # execution day = row index for run_day_daily
        target = {s: float(w) for s, w in signals.loc[date_t].items() if w > 0}
        prev_close = {s: float(closes.loc[date_t, s]) for s in closes.columns
                      if not pd.isna(closes.loc[date_t, s])}
        exec_open = {s: float(opens.loc[date_tp1, s]) for s in opens.columns
                     if not pd.isna(opens.loc[date_tp1, s])}
        eod_close = {s: float(closes.loc[date_tp1, s]) for s in closes.columns
                     if not pd.isna(closes.loc[date_tp1, s])}
        eng.run_day_daily(
            exec_date=date_tp1,
            target_wts=target,
            prev_close=prev_close,
            exec_open=exec_open,
            eod_close=eod_close,
        )

    return tracker.equity_curve.rename("paper_equity")


def test_paper_vs_backtest_equity_parity_under_gap_opens(tmp_path):
    """Headline M11b test: equity curves must match within 1 bps per day."""
    idx, signals, closes, opens = _build_panel()

    # BacktestEngine reference path
    bt_eng = BacktestEngine(
        cost_model=_zero_cost_model(),
        initial_capital=100_000.0,
        integer_shares=False,
        stale_days_threshold=10,
    )
    bt_result = bt_eng.run(signals_df=signals, price_df=closes, open_df=opens)
    bt_equity = bt_result.equity_curve

    # PaperTradingEngine driven day-by-day
    paper_equity = _run_paper_engine_day_by_day(tmp_path, signals, closes, opens)

    # We compare on the trading days the paper engine actually wrote
    # (that excludes the very first signal day, since paper's first call
    # is for the first execution day = dates[1]).
    common = paper_equity.index.intersection(bt_equity.index)
    assert len(common) >= 3, f"Need ≥3 overlapping days, got {len(common)}: {common}"

    bt_aligned = bt_equity.loc[common]
    paper_aligned = paper_equity.loc[common]

    # Per-day relative drift in bps
    rel_drift_bps = (paper_aligned - bt_aligned).abs() / bt_aligned * 10_000

    max_daily_bps = float(rel_drift_bps.max())
    assert max_daily_bps < 1.0, (
        f"Per-day equity drift exceeds 1 bps tolerance: max={max_daily_bps:.3f} bps\n"
        f"BT:    {bt_aligned.values}\n"
        f"Paper: {paper_aligned.values}"
    )

    # Cumulative final-equity drift in bps
    cum_drift_bps = abs(paper_aligned.iloc[-1] - bt_aligned.iloc[-1]) \
        / bt_aligned.iloc[-1] * 10_000
    assert cum_drift_bps < 5.0, (
        f"Cumulative equity drift exceeds 5 bps tolerance: {cum_drift_bps:.3f} bps"
    )


def test_paper_engine_uses_eod_close_not_prev_close(tmp_path):
    """Smoking-gun test for the pre-M11b-fix bug. Construct a day where
    eod_close is materially higher than prev_close, hold a long position,
    and assert paper engine's recorded equity reflects the eod_close
    move (not the stale prev_close)."""
    idx = pd.bdate_range("2024-01-02", periods=3)
    cm = _zero_cost_model()
    tracker = PnLTracker()
    eng = PaperTradingEngine(
        cost_model=cm, pnl_tracker=tracker,
        db_path=tmp_path / "p.db",
        initial_capital=10_000.0, integer_shares=False,
    )

    # Day 1: enter 100% AAA at $100.
    eng.run_day_daily(
        exec_date=idx[0],
        target_wts={"AAA": 1.0},
        prev_close={"AAA": 100.0},
        exec_open={"AAA": 100.0},
        eod_close={"AAA": 100.0},
    )
    # Day 2: prev close is still 100; T+1 open ALSO 100; but T+1 EOD close
    # ramps to 110 (10% intra-day move). Hold the position (target = 1.0).
    eng.run_day_daily(
        exec_date=idx[1],
        target_wts={"AAA": 1.0},
        prev_close={"AAA": 100.0},
        exec_open={"AAA": 100.0},
        eod_close={"AAA": 110.0},
    )

    # 100 shares × 110 close ≈ 11,000 (no costs in zero cost model)
    eod_equity = float(tracker.equity_curve.iloc[-1])
    assert 10_900 < eod_equity < 11_010, (
        f"Expected EOD equity ≈ 11,000 from 10% intraday move, got {eod_equity}. "
        f"Pre-M11b-fix this would have been ≈ 10,000 (using prev_close)."
    )
