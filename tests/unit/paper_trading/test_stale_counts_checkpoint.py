"""Round 3 Topic C (2026-04-20): tests for stale_counts persistence
across process restarts via bar_checkpoints.

Prior behavior: PaperTradingEngine._intraday_stale_counts was
process-local. If a halted-for-3-days symbol accumulated 12 stale
bars on day 1, and the process died overnight, day 2's fresh
engine started with empty stale_counts. The counter never crossed
threshold and ghost cleanup never fired for multi-day halts.

Fix: save stale_counts inside bar_checkpoints.state_json; always
restore from checkpoint regardless of date. Cross-day halts now
cumulate correctly.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
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
    eng = PaperTradingEngine(
        cost_model=cost, pnl_tracker=tracker, db_path=db_path,
        initial_capital=10_000, kill_switch=ks,
    )
    return eng, db_path


class TestStaleCountsPersistence:

    def test_save_includes_stale_counts(self):
        eng, db = _make_engine()
        eng._intraday_stale_counts = {"AAPL": 8, "HALTED": 3}
        eng.save_bar_checkpoint(
            run_id="r1", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 15:00"),
            positions={"AAPL": 10.0}, cash=5_000.0,
        )
        conn = sqlite3.connect(db)
        (state_json,) = conn.execute(
            "SELECT state_json FROM bar_checkpoints WHERE run_id='r1'"
        ).fetchone()
        conn.close()
        import json
        state = json.loads(state_json)
        assert state["stale_counts"] == {"AAPL": 8, "HALTED": 3}
        assert state["positions"] == {"AAPL": 10.0}
        assert state["cash"] == 5_000.0

    def test_load_returns_stale_counts(self):
        eng, db = _make_engine()
        eng._intraday_stale_counts = {"AAPL": 12}
        eng.save_bar_checkpoint(
            run_id="r2", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 16:00"),
            positions={}, cash=10_000.0,
        )
        cp = eng.load_bar_checkpoint("r2")
        assert cp is not None
        assert cp["stale_counts"] == {"AAPL": 12}

    def test_legacy_checkpoint_without_stale_counts_returns_empty_dict(self):
        """Back-compat: if state_json was written before Round 3 (no
        stale_counts key), load should return empty dict not crash."""
        eng, db = _make_engine()
        # Manually insert legacy-style checkpoint
        import json
        legacy_state = json.dumps({"positions": {"X": 1.0}, "cash": 9_000.0})
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO bar_checkpoints (run_id, date, last_bar_ts, "
            "state_json, updated_at) VALUES (?,?,?,?,?)",
            ("r-legacy", "2025-01-02", "2025-01-02 15:30", legacy_state,
             "2025-01-02T15:30:00"),
        )
        conn.commit(); conn.close()

        cp = eng.load_bar_checkpoint("r-legacy")
        assert cp is not None
        assert cp["stale_counts"] == {}
        assert cp["positions"] == {"X": 1.0}


class TestCrossDayRestore:

    def test_fresh_engine_restores_stale_counts_same_day(self):
        """Simulate kill-restart mid-day: fresh engine instance on
        same DB reads back the persisted stale_counts."""
        eng_a, db = _make_engine()
        eng_a._intraday_stale_counts = {"X": 4, "Y": 2}
        eng_a.save_bar_checkpoint(
            run_id="same-day", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 12:00"),
            positions={"X": 1.0}, cash=5_000.0,
        )
        # Fresh engine on same DB
        eng_b, _ = _make_engine(db_path=db)
        assert eng_b._intraday_stale_counts == {}  # starts empty

        # Running run_day_intraday on matching date restores everything
        idx = pd.date_range("2025-04-01 10:30", periods=4, freq="60min")
        day_bars = {"X": pd.DataFrame({
            "open":  [100.0] * 4, "high": [101.0] * 4,
            "low":   [99.0] * 4,  "close": [100.5] * 4,
            "volume": [1e5] * 4,
        }, index=idx)}
        eng_b.run_day_intraday(
            run_id="same-day", date=pd.Timestamp("2025-04-01"),
            day_bars=day_bars, target_wts={"X": 0.5},
        )
        # After resume, stale_counts should have been restored from
        # checkpoint (and may have been updated / reset during the
        # bar loop, but at least NOT {} initially)
        # We can only observe final state; Y was never in day_bars so
        # its counter should NOT exist after the loop
        # X was in day_bars with valid open → stale_counts[X] resets
        # to 0 after first processed bar
        # But during the initial load, self._intraday_stale_counts
        # should've been set to {"X": 4, "Y": 2}
        # After the loop: Y is untouched (was in dict but no bars)
        assert eng_b._intraday_stale_counts.get("Y") == 2, (
            f"Y stale_count should survive the loop untouched, "
            f"got {eng_b._intraday_stale_counts}"
        )

    def test_fresh_engine_restores_stale_counts_cross_day(self):
        """The critical multi-day halt scenario: engine dies on day 1,
        new engine on day 2 reads back stale_counts even though the
        checkpoint date doesn't match today's date."""
        eng_a, db = _make_engine()
        eng_a._intraday_stale_counts = {"HALTED_SYM": 10}
        eng_a.save_bar_checkpoint(
            run_id="cross-day", date=pd.Timestamp("2025-04-01"),
            bar_ts=pd.Timestamp("2025-04-01 16:00"),
            positions={}, cash=10_000.0,
        )

        # Day 2: fresh engine on same DB. Calling load_bar_checkpoint
        # directly returns the cross-day stale_counts.
        eng_b, _ = _make_engine(db_path=db)
        cp = eng_b.load_bar_checkpoint("cross-day")
        assert cp is not None
        assert cp["stale_counts"] == {"HALTED_SYM": 10}

        # run_day_intraday on day 2 restores stale_counts even though
        # date != cp.date (positions are NOT restored because that
        # would be a different-day confusion; just the counter).
        idx_d2 = pd.date_range("2025-04-02 10:30", periods=3, freq="60min")
        day_bars = {"OTHER": pd.DataFrame({
            "open":  [50.0] * 3, "high": [51.0] * 3, "low": [49.0] * 3,
            "close": [50.5] * 3, "volume": [1e5] * 3,
        }, index=idx_d2)}
        eng_b.run_day_intraday(
            run_id="cross-day", date=pd.Timestamp("2025-04-02"),
            day_bars=day_bars, target_wts={},
        )
        # HALTED_SYM was not in day 2's bars, so its counter survives
        assert eng_b._intraday_stale_counts.get("HALTED_SYM") == 10


class TestMultiDayHaltTriggersCleanup:

    def test_cumulative_halt_across_two_days_triggers_cleanup(self):
        """Integration: symbol halted day 1 (5 bars) + day 2 (6 bars)
        should hit threshold=8 mid-day 2 (cumulative 11 > 8)
        even across a process restart."""
        eng_a, db = _make_engine()
        eng_a._engine._stale_bars_threshold = 8
        eng_a._positions = {"AAPL": 10.0}
        eng_a._cash = 9_000.0

        # Day 1: 5 halted bars (open all NaN)
        idx_d1 = pd.date_range("2025-04-01 10:30", periods=5, freq="60min")
        day1 = {"AAPL": pd.DataFrame({
            "open":  [np.nan] * 5,
            "high":  [100.0] * 5, "low": [100.0] * 5,
            "close": [100.0] * 5, "volume": [1e5] * 5,
        }, index=idx_d1)}
        eng_a.run_day_intraday(
            run_id="halt-2d", date=pd.Timestamp("2025-04-01"),
            day_bars=day1, target_wts={},
        )
        # Day 1 accumulated ≤ 5 stale bars, below threshold 8
        # (actual count depends on loop iteration count)
        assert len(eng_a._engine.ghost_liquidations) == 0
        assert eng_a._intraday_stale_counts.get("AAPL", 0) >= 3

        # Kill + restart: fresh engine on same DB
        eng_b, _ = _make_engine(db_path=db)
        eng_b._engine._stale_bars_threshold = 8
        eng_b._positions = {"AAPL": 10.0}
        eng_b._cash = 9_000.0

        # Day 2: another 6 halted bars — should trigger cumulative
        idx_d2 = pd.date_range("2025-04-02 10:30", periods=6, freq="60min")
        day2 = {"AAPL": pd.DataFrame({
            "open":  [np.nan] * 6,
            "high":  [100.0] * 6, "low": [100.0] * 6,
            "close": [100.0] * 6, "volume": [1e5] * 6,
        }, index=idx_d2)}
        eng_b.run_day_intraday(
            run_id="halt-2d", date=pd.Timestamp("2025-04-02"),
            day_bars=day2, target_wts={},
        )
        # Cross-day cumulation should trigger ghost cleanup on day 2
        assert any(g["symbol"] == "AAPL"
                   for g in eng_b._engine.ghost_liquidations), (
            "cross-day stale_counts did not cumulate to threshold; "
            "ghost cleanup failed to fire"
        )
