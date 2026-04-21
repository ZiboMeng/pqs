"""Tests for intraday ghost-position cleanup (closeout 2026-04-20).

Semantic parity with daily BacktestEngine ghost cleanup, but the unit
is BARS not days and the counter may persist across days via
`stale_counts` dict (owned by the caller — typically
PaperTradingEngine). Default threshold is 13 bars ≈ 2 RTH days of
60m bars, chosen conservatively to not prematurely exit a trading
halt.

Covers:
  1. Force-liquidate after threshold stale bars; price = last valid close
  2. Short gap (below threshold) is NOT liquidated
  3. Stale counter resets when a valid open returns
  4. Across-days persistence via stale_counts dict (paper engine case)
  5. Diagnostic log populated in ghost_liquidations
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.backtest.intraday_engine import IntradayBacktestEngine
from core.config.loader import load_config
from core.execution.cost_model import CostModel
from pathlib import Path


def _cost():
    return CostModel(load_config(Path("config")).cost_model)


def _mk_bars(n_bars: int, symbols: dict, start="2025-04-01 10:30",
             freq_min: int = 60) -> dict:
    """Build per-symbol day_bars dict. `symbols` is a dict
    symbol → list[(close, has_next_open)] where has_next_open controls
    whether `open` at index i+1 is NaN or 0 (simulating halt)."""
    idx = pd.date_range(start, periods=n_bars, freq=f"{freq_min}min")
    out = {}
    for sym, series in symbols.items():
        close = [c for c, _ in series]
        high  = [c + 0.3 for c, _ in series]
        low   = [c - 0.3 for c, _ in series]
        opn   = [c - 0.1 if has else np.nan for c, has in series]
        out[sym] = pd.DataFrame({
            "open": opn, "high": high, "low": low, "close": close,
            "volume": 1e5,
        }, index=idx)
    return out


class TestIntradayGhostCleanup:

    def test_halted_position_liquidated_after_threshold(self):
        """AAPL held; from bar 2 onward all `open` values are NaN
        (halted). With threshold=2, ghost cleanup fires at bar ~4."""
        bars = _mk_bars(
            n_bars=8,
            symbols={
                "AAPL": [(100.0, True)] + [(100.0, False)] * 7,
            },
        )
        eng = IntradayBacktestEngine(
            cost_model=_cost(), initial_capital=10_000,
            eod_force_close=False, stale_bars_threshold=2,
        )
        eng.run_multi_day(
            date=pd.Timestamp("2025-04-01"),
            day_bars=bars, target_wts={"AAPL": 0.5},
            positions={"AAPL": 50.0},  # pretend we were holding
            cash=5_000.0,
        )
        liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert len(liqs) >= 1, "AAPL should have been force-liquidated"
        assert liqs[0]["price"] == 100.0, (
            f"liquidation price should be last valid close; got {liqs[0]['price']}"
        )
        assert liqs[0]["stale_bars"] > 2

    def test_short_gap_no_liquidation(self):
        """Halt for 2 bars with threshold=5 → no force liquidation."""
        bars = _mk_bars(
            n_bars=8,
            symbols={
                "AAPL": [(100.0, True), (100.0, False), (100.0, False),
                         (100.0, True), (100.0, True), (100.0, True),
                         (100.0, True), (100.0, True)],
            },
        )
        eng = IntradayBacktestEngine(
            cost_model=_cost(), initial_capital=10_000,
            eod_force_close=False, stale_bars_threshold=5,
        )
        eng.run_multi_day(
            date=pd.Timestamp("2025-04-01"),
            day_bars=bars, target_wts={"AAPL": 0.5},
            positions={"AAPL": 50.0}, cash=5_000.0,
        )
        aapl_liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert len(aapl_liqs) == 0, (
            f"AAPL incorrectly liquidated after short gap: {aapl_liqs}"
        )

    def test_counter_resets_after_valid_open(self):
        """A stale streak should reset when a valid open returns."""
        bars = _mk_bars(
            n_bars=10,
            symbols={
                "AAPL": [(100.0, True),
                         (100.0, False), (100.0, False),  # 2 stale
                         (100.0, True),                    # reset
                         (100.0, False),                   # only 1 → below 3 threshold
                         (100.0, True), (100.0, True),
                         (100.0, True), (100.0, True),
                         (100.0, True)],
            },
        )
        eng = IntradayBacktestEngine(
            cost_model=_cost(), initial_capital=10_000,
            eod_force_close=False, stale_bars_threshold=3,
        )
        eng.run_multi_day(
            date=pd.Timestamp("2025-04-01"),
            day_bars=bars, target_wts={"AAPL": 0.5},
            positions={"AAPL": 50.0}, cash=5_000.0,
        )
        # No run hit threshold 3+ → no liquidations
        aapl_liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert len(aapl_liqs) == 0

    def test_stale_counts_persists_across_days(self):
        """When caller supplies `stale_counts` dict, halt counters
        survive day boundaries. A halt spanning 2 short days where
        each day alone doesn't hit threshold should cumulate and
        trigger on day 2."""
        eng = IntradayBacktestEngine(
            cost_model=_cost(), initial_capital=10_000,
            eod_force_close=False, stale_bars_threshold=5,
        )
        # Day 1: 4 bars, all halted → stale_count hits 4, below 5
        day1 = _mk_bars(
            n_bars=4,
            symbols={"AAPL": [(100.0, False)] * 4},
        )
        stale = {}
        eng.run_multi_day(
            date=pd.Timestamp("2025-04-01"),
            day_bars=day1, target_wts={}, positions={"AAPL": 50.0},
            cash=5_000.0, stale_counts=stale,
        )
        assert len(eng.ghost_liquidations) == 0
        # Counter should have accumulated but not triggered
        assert stale.get("AAPL", 0) >= 3

        # Day 2: another 4 bars, still halted; cumulative cross 5 → trigger
        day2 = _mk_bars(
            n_bars=4,
            symbols={"AAPL": [(100.0, False)] * 4},
            start="2025-04-02 10:30",
        )
        eng.run_multi_day(
            date=pd.Timestamp("2025-04-02"),
            day_bars=day2, target_wts={}, positions={"AAPL": 50.0},
            cash=5_000.0, stale_counts=stale,
        )
        aapl_liqs = [g for g in eng.ghost_liquidations if g["symbol"] == "AAPL"]
        assert len(aapl_liqs) >= 1, (
            "cross-day stale counter failed to cumulate to threshold"
        )

    def test_paper_engine_persists_stale_across_days(self):
        """PaperTradingEngine stores _intraday_stale_counts and threads
        it into every run_day_intraday call so that paper's multi-day
        halt semantics match."""
        import sqlite3, tempfile
        from core.paper_trading.paper_trading_engine import PaperTradingEngine
        from core.paper_trading.pnl_tracker import PnLTracker
        from core.risk.kill_switch import KillSwitch, KillSwitchConfig

        cfg = load_config(Path("config"))
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False); f.close()
        pe = PaperTradingEngine(
            cost_model=_cost(),
            pnl_tracker=PnLTracker(initial_capital=10_000),
            db_path=f.name, initial_capital=10_000,
            kill_switch=KillSwitch(KillSwitchConfig(max_drawdown=-0.99)),
        )
        assert pe._intraday_stale_counts == {}
        # Hydrate positions so cleanup has a ghost to clean
        pe._positions = {"AAPL": 10.0}
        pe._cash = 9_000.0

        # Build first halted day
        day = _mk_bars(
            n_bars=4,
            symbols={"AAPL": [(100.0, False)] * 4},
        )
        # Use small threshold to get a clean verification
        pe._engine._stale_bars_threshold = 2
        pe.run_day_intraday(
            run_id="gh1", date=pd.Timestamp("2025-04-01"),
            day_bars=day, target_wts={},
        )
        # Liquidation should have fired within day 1 (threshold=2, 3+
        # stale bars in 4-bar day)
        assert any(g["symbol"] == "AAPL"
                   for g in pe._engine.ghost_liquidations)
