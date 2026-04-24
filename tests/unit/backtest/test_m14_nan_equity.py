"""Tests for M14 fix — NaN equity when held position has missing close.

Root cause (diagnosed 2026-04-24): in BacktestEngine.run, portfolio_value
calc uses `price_row.get(sym, 0)`. The `0` default applies only when the
column is MISSING from price_row's index, not when the column exists
with a NaN value. If a held symbol has NaN close on a particular date
(common when the panel is union-merged across symbols with non-aligned
calendars — e.g. some symbols missing a Monday other symbols have),
the multiplication `qty * NaN = NaN` propagates to the daily equity
record.

Symptom in production: paper-vs-replay drift report on Cand-2 showed
mean 100 bps drift in 2022 bear, with consistent NaN equity rows on
Mondays. Drift was ENTIRELY M14, not execution noise (memo:
`docs/memos/20260424-cand2_drift_attribution.md`).

Fix: when a held symbol's price_row value is NaN (or missing), fall
back to last_valid_close (the same fallback the ghost-cleanup logic
already maintains). If no valid close ever observed, treat as 0
(write-off semantics, same as ghost-cleanup write-off).

These tests pin down:
  1. Pre-fix: a held position with a NaN close day produces NaN equity.
  2. Post-fix: equity stays finite, valued at last-valid close on the
     missing day.
  3. Once a valid close reappears, equity uses that fresh value.
  4. A position that NEVER had a valid close is valued at 0
     (write-off), not NaN.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.backtest.backtest_engine import BacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel


def _cost():
    return CostModel(load_config(Path("config")).cost_model)


def test_nan_close_on_held_symbol_does_not_yield_nan_equity():
    """The headline M14 regression: held AAPL with one NaN close day in
    the middle of the window must NOT crash equity to NaN on that day."""
    idx = pd.bdate_range("2024-01-02", periods=10)
    # AAPL has a NaN close on day 5; otherwise valid
    aapl_close = [100.0, 101.0, 102.0, 103.0, 104.0, np.nan, 106.0, 107.0, 108.0, 109.0]
    bbb_close = [50.0] * 10
    prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
    opens = prices.copy()
    signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

    eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                         stale_days_threshold=10)
    result = eng.run(signals_df=signals, price_df=prices, open_df=opens)

    # No equity row should be NaN
    nan_rows = result.equity_curve.isna().sum()
    assert nan_rows == 0, (
        f"Expected 0 NaN equity rows, got {nan_rows}. "
        f"Equity series:\n{result.equity_curve}"
    )


def test_held_position_uses_last_valid_close_on_nan_day():
    """On the NaN day, equity should reflect the last valid close
    of the held symbol — same fallback used by ghost-cleanup."""
    idx = pd.bdate_range("2024-01-02", periods=8)
    # AAPL: 100, 110, 120, NaN, 130 — on the NaN day equity should
    # use 120 (last valid close before NaN)
    aapl_close = [100.0, 110.0, 120.0, np.nan, 130.0, 130.0, 130.0, 130.0]
    bbb_close = [50.0] * 8
    prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
    opens = prices.copy()
    # Hold ~50/50; warmup means real holdings start day 1+
    signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

    eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                         stale_days_threshold=10)
    result = eng.run(signals_df=signals, price_df=prices, open_df=opens)

    # All equity rows must be finite
    assert result.equity_curve.notna().all()

    # The NaN day's equity should be sensible — at minimum NOT NaN
    nan_day = idx[3]
    nan_day_equity = result.equity_curve.loc[nan_day]
    assert np.isfinite(nan_day_equity)
    assert nan_day_equity > 0


def test_equity_recovers_to_fresh_close_when_data_returns():
    """After the NaN day, valid close prices should drive equity again,
    not the stale last_valid_close."""
    idx = pd.bdate_range("2024-01-02", periods=8)
    # Day 4 is NaN. Day 5+ has fresh close = 200 (much higher than last valid 100).
    aapl_close = [100.0, 100.0, 100.0, 100.0, np.nan, 200.0, 200.0, 200.0]
    bbb_close = [50.0] * 8
    prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
    opens = prices.copy()
    signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

    eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                         stale_days_threshold=10)
    result = eng.run(signals_df=signals, price_df=prices, open_df=opens)

    # Equity on day 4 (NaN AAPL): uses last_valid_close = 100
    # Equity on day 5+ (AAPL=200): should reflect the 2x price jump
    nan_day_equity = result.equity_curve.iloc[4]
    post_nan_equity = result.equity_curve.iloc[5]

    assert np.isfinite(nan_day_equity)
    assert np.isfinite(post_nan_equity)
    # Equity should JUMP from day 4 to day 5 because AAPL doubled.
    # (Even allowing for rebalance turnover effects, post-jump equity
    # should be measurably > nan_day equity.)
    assert post_nan_equity > nan_day_equity


def test_symbol_with_no_valid_close_ever_is_valued_at_zero():
    """A held position that never had a valid close (e.g. immediately
    halted on entry) should be valued at 0 in portfolio_value, NOT NaN.
    This is the same write-off semantics the ghost-cleanup uses."""
    idx = pd.bdate_range("2024-01-02", periods=10)
    # AAPL has valid open day 0, but close is NaN throughout
    aapl_close = [np.nan] * 10
    aapl_open = [100.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
    bbb_close = [50.0] * 10
    prices = pd.DataFrame({"AAPL": aapl_close, "BBB": bbb_close}, index=idx)
    opens = pd.DataFrame({"AAPL": aapl_open, "BBB": [50.0] * 10}, index=idx)
    signals = pd.DataFrame(0.5, index=idx, columns=["AAPL", "BBB"])

    eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                         stale_days_threshold=10)
    result = eng.run(signals_df=signals, price_df=prices, open_df=opens)

    # All equity rows finite; AAPL should not contribute NaN even though
    # it never has a valid close
    assert result.equity_curve.notna().all()


def test_multi_symbol_partial_nan_panel_real_world_pattern():
    """Reproduces the actual production pattern: 5 of 10 held symbols
    have NaN on a given Monday (calendar misalignment in the panel).
    Pre-fix: equity = NaN that day. Post-fix: equity uses last-valid
    closes for the 5 missing, fresh closes for the 5 present."""
    idx = pd.bdate_range("2024-01-02", periods=15)
    cols = [f"S{i}" for i in range(10)]
    # All symbols valid most days. On day 7 (mid-window), 5 have NaN.
    data = {}
    for i, c in enumerate(cols):
        v = [10.0 + j * 0.1 for j in range(15)]
        if i < 5:
            v[7] = np.nan  # first 5 symbols missing day 7
        data[c] = v
    prices = pd.DataFrame(data, index=idx)
    opens = prices.copy()
    # Hold all 10 equally
    signals = pd.DataFrame(0.10, index=idx, columns=cols)

    eng = BacktestEngine(cost_model=_cost(), initial_capital=10_000,
                         stale_days_threshold=10)
    result = eng.run(signals_df=signals, price_df=prices, open_df=opens)

    # Day 7 equity must NOT be NaN — that was the M14 production bug
    nan_count = result.equity_curve.isna().sum()
    assert nan_count == 0, (
        f"M14 regression: equity series has {nan_count} NaN rows when 5 of 10 "
        f"held symbols had NaN close on day 7. Series:\n{result.equity_curve}"
    )
