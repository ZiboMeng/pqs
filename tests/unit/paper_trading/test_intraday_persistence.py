"""Tests for PaperTradingEngine intraday persistence, recovery, and idempotency."""

import sqlite3
import tempfile
import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import Order, OrderSide
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from pathlib import Path


def _make_engine(db_path=None):
    cfg = load_config(Path("config"))
    cost = CostModel(cfg.cost_model)
    tracker = PnLTracker(initial_capital=10000)
    ks = KillSwitch(KillSwitchConfig(max_drawdown=-0.99))
    if db_path is None:
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = f.name
        f.close()
    engine = PaperTradingEngine(
        cost_model=cost, pnl_tracker=tracker, db_path=db_path,
        initial_capital=10000, kill_switch=ks,
    )
    return engine, db_path


def _make_mock_order(symbol="AAPL", side=OrderSide.BUY, qty=10):
    return Order(symbol=symbol, side=side, qty_shares=qty,
                 signal_date=pd.Timestamp("2025-01-02"))


class TestIntradayPersistenceSchema:
    """All 5 intraday tables must exist."""

    def test_tables_created(self):
        engine, db_path = _make_engine()
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        for t in ["intraday_orders", "intraday_fills", "intraday_positions",
                   "intraday_equity", "bar_checkpoints"]:
            assert t in tables, f"Missing table: {t}"


class TestSaveIntradayBar:
    """save_intraday_bar must persist orders, fills, positions, equity."""

    def test_writes_equity(self):
        engine, db_path = _make_engine()
        engine.save_intraday_bar(
            run_id="test-run", date=pd.Timestamp("2025-01-02"),
            bar_ts=pd.Timestamp("2025-01-02 10:30"),
            orders=[], fills=[], positions={"AAPL": 10}, cash=5000, equity=7000,
        )
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM intraday_equity").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][4] == 7000.0  # equity
        assert rows[0][5] == 5000.0  # cash

    def test_writes_positions(self):
        engine, db_path = _make_engine()
        engine.save_intraday_bar(
            run_id="r1", date=pd.Timestamp("2025-01-02"),
            bar_ts=pd.Timestamp("2025-01-02 10:30"),
            orders=[], fills=[], positions={"AAPL": 10, "MSFT": 5},
            cash=5000, equity=7000,
        )
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT symbol, qty FROM intraday_positions ORDER BY symbol").fetchall()
        conn.close()
        assert len(rows) == 2
        assert rows[0] == ("AAPL", 10.0)
        assert rows[1] == ("MSFT", 5.0)


class TestBarCheckpoint:
    """Checkpoint save and load for restart recovery."""

    def test_save_and_load(self):
        engine, db_path = _make_engine()
        positions = {"AAPL": 10, "MSFT": 5}
        engine.save_bar_checkpoint(
            run_id="run-1", date=pd.Timestamp("2025-01-02"),
            bar_ts=pd.Timestamp("2025-01-02 11:30"),
            positions=positions, cash=8000.0,
        )
        cp = engine.load_bar_checkpoint("run-1")
        assert cp is not None
        assert cp["cash"] == 8000.0
        assert cp["positions"]["AAPL"] == 10
        assert cp["last_bar_ts"] == pd.Timestamp("2025-01-02 11:30")

    def test_load_nonexistent(self):
        engine, _ = _make_engine()
        assert engine.load_bar_checkpoint("nonexistent") is None

    def test_checkpoint_overwrites(self):
        engine, db_path = _make_engine()
        engine.save_bar_checkpoint("r1", pd.Timestamp("2025-01-02"),
                                   pd.Timestamp("2025-01-02 10:30"), {"A": 5}, 9000)
        engine.save_bar_checkpoint("r1", pd.Timestamp("2025-01-02"),
                                   pd.Timestamp("2025-01-02 11:30"), {"A": 10}, 8000)
        cp = engine.load_bar_checkpoint("r1")
        assert cp["cash"] == 8000.0
        assert cp["last_bar_ts"] == pd.Timestamp("2025-01-02 11:30")


class TestIdempotency:
    """has_fill_for_bar prevents duplicate fills."""

    def test_no_fills_initially(self):
        engine, _ = _make_engine()
        assert engine.has_fill_for_bar("r1", pd.Timestamp("2025-01-02 10:30")) is False

    def test_has_fill_after_save(self):
        engine, db_path = _make_engine()
        # Write a fill manually
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO intraday_fills (run_id, date, bar_ts, symbol, side, qty, price, "
            "slippage_usd, commission_usd, cash_delta) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("r1", "2025-01-02", "2025-01-02 10:30:00", "AAPL", "BUY", 10, 150.0, 0.5, 0.1, -1500.6),
        )
        conn.commit()
        conn.close()
        assert engine.has_fill_for_bar("r1", pd.Timestamp("2025-01-02 10:30")) is True

    def test_different_bar_not_flagged(self):
        engine, db_path = _make_engine()
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO intraday_fills (run_id, date, bar_ts, symbol, side, qty, price, "
            "slippage_usd, commission_usd, cash_delta) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("r1", "2025-01-02", "2025-01-02 10:30:00", "AAPL", "BUY", 10, 150.0, 0, 0, -1500),
        )
        conn.commit()
        conn.close()
        assert engine.has_fill_for_bar("r1", pd.Timestamp("2025-01-02 11:30")) is False
