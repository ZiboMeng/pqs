"""Tests for intraday_fills.is_eod column (P1.8, 2026-04-20).

Prior behavior: EOD force-close fills were bucketed onto the last
bar_ts without any marker, making it impossible to separate "trade
on last bar" from "flatten at EOD" in attribution / analytics.

Fix adds an is_eod (INTEGER 0/1) column to intraday_fills, defaulted
to 0, and the run_day_intraday residual-fill path now writes 1.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from core.backtest.intraday_engine import BarUpdate
from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import (
    CostBreakdown, Fill, Order, OrderSide,
)
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig


def _make_engine(db_path=None):
    cfg = load_config(Path("config"))
    cost = CostModel(cfg.cost_model)
    tracker = PnLTracker(initial_capital=10_000)
    ks = KillSwitch(KillSwitchConfig(max_drawdown=-0.99))
    if db_path is None:
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = f.name
        f.close()
    engine = PaperTradingEngine(
        cost_model=cost, pnl_tracker=tracker, db_path=db_path,
        initial_capital=10_000, kill_switch=ks,
    )
    return engine, db_path


def _mk_fill(sym="AAPL", qty=1.0, price=100.0, side=OrderSide.BUY):
    order = Order(symbol=sym, side=side, qty_shares=qty,
                  signal_date=pd.Timestamp("2025-01-02"))
    notional = abs(qty * price)
    cb = CostBreakdown(symbol=sym, notional_usd=notional,
                       commission_usd=0.0, slippage_usd=0.0,
                       total_cost_usd=0.0, total_bps=0.0)
    cash_delta = -qty * price if side == OrderSide.BUY else qty * price
    return Fill(order=order, executed_price=price, executed_qty=qty,
                cost_breakdown=cb,
                fill_date=pd.Timestamp("2025-01-02"), cash_delta=cash_delta)


class TestSchema:
    def test_is_eod_column_exists(self):
        engine, db = _make_engine()
        conn = sqlite3.connect(db)
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(intraday_fills)").fetchall()}
        conn.close()
        assert "is_eod" in cols

    def test_is_eod_default_zero(self):
        engine, db = _make_engine()
        # Writing without is_eod → default 0
        engine.save_intraday_bar(
            run_id="t", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 10:30"),
            orders=[], fills=[_mk_fill()],
            positions={}, cash=10_000, equity=10_000,
        )
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT is_eod FROM intraday_fills WHERE run_id='t'"
        ).fetchall()
        conn.close()
        assert all(r[0] == 0 for r in rows)


class TestMarking:
    def test_explicit_is_eod_true_marks_rows(self):
        engine, db = _make_engine()
        engine.save_intraday_bar(
            run_id="eod", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 16:00"),
            orders=[], fills=[_mk_fill()],
            positions={}, cash=10_000, equity=10_000,
            is_eod=True,
        )
        conn = sqlite3.connect(db)
        (cnt,) = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='eod' AND is_eod=1"
        ).fetchone()
        conn.close()
        assert cnt == 1

    def test_run_day_intraday_flags_eod_residuals(self):
        """End-to-end: running a full day with EOD force-close results
        in the last-bar fills being flagged is_eod=1 while per-bar
        fills remain is_eod=0."""
        engine, db = _make_engine()
        idx = pd.date_range("2025-04-01 10:30", periods=4, freq="60min")
        closes = np.array([100.0, 100.5, 101.0, 101.5])
        day_bars = {"AAPL": pd.DataFrame({
            "open":  closes - 0.1, "high": closes + 0.3,
            "low":   closes - 0.3, "close": closes, "volume": 1e5,
        }, index=idx)}
        engine.run_day_intraday(
            run_id="day1", date=pd.Timestamp("2025-04-01"),
            day_bars=day_bars, target_wts={"AAPL": 0.5},
        )
        conn = sqlite3.connect(db)
        per_bar = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='day1' AND is_eod=0"
        ).fetchone()[0]
        eod_count = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='day1' AND is_eod=1"
        ).fetchone()[0]
        conn.close()
        assert per_bar >= 1, "no per-bar fill rows written"
        # EOD force-close is on by default in PaperTradingEngine —
        # should produce at least one is_eod=1 row flattening the
        # AAPL position at last bar close.
        assert eod_count >= 1, "EOD residual fill missing is_eod=1 flag"


class TestAttributionFiltering:
    def test_split_per_bar_vs_eod_via_column(self):
        """Downstream analytics use the column to partition fills."""
        engine, db = _make_engine()
        engine.save_intraday_bar(
            run_id="split", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 10:30"),
            orders=[], fills=[_mk_fill()],
            positions={}, cash=10_000, equity=10_000,
        )
        engine.save_intraday_bar(
            run_id="split", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 16:00"),
            orders=[], fills=[_mk_fill(side=OrderSide.SELL)],
            positions={}, cash=10_000, equity=10_000,
            is_eod=True,
        )
        conn = sqlite3.connect(db)
        per_bar = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='split' AND is_eod=0"
        ).fetchone()[0]
        eod = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='split' AND is_eod=1"
        ).fetchone()[0]
        conn.close()
        assert per_bar == 1
        assert eod == 1
