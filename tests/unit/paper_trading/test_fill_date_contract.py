"""M11b fill_date contract test.

The contract (per `core/execution/execution_simulator.py` Order/Fill
docstrings):
  - Order.signal_date  = T (signal day)
  - Fill.fill_date     = T+1 (= signal_date + 1 BDay)

For PaperTradingEngine.run_day_daily called with `exec_date = T+1`,
the signal_date stamped on every order MUST be `exec_date - 1 BDay = T`,
so that ExecutionSimulator's `fill_date = signal_date + 1 BDay` lands
on `exec_date`.

Pre-M11b-fix `signal_date` was passed as `exec_date` itself, producing
fill_date = exec_date + 1 BDay = T+2, off by one trading day.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker


def _zero_cost_model() -> CostModel:
    return CostModel(load_config(Path("config")).cost_model)


def test_signal_date_is_exec_date_minus_one_bday(tmp_path):
    eng = PaperTradingEngine(
        cost_model=_zero_cost_model(),
        pnl_tracker=PnLTracker(),
        db_path=tmp_path / "p.db",
        initial_capital=10_000.0,
        integer_shares=False,
    )
    exec_date = pd.Timestamp("2024-01-04")  # Thursday
    expected_signal_date = pd.Timestamp("2024-01-03")  # Wednesday (= -1 BDay)

    result = eng.run_day_daily(
        exec_date=exec_date,
        target_wts={"AAA": 1.0},
        prev_close={"AAA": 100.0},
        exec_open={"AAA": 100.0},
        eod_close={"AAA": 100.0},
    )

    assert len(result.trades) >= 1, "Expected ≥1 fill from a 0% → 100% rebalance"
    for fill in result.trades:
        assert fill.signal_date == expected_signal_date, (
            f"signal_date mismatch: got {fill.signal_date}, "
            f"expected {expected_signal_date} (= exec_date {exec_date} - 1 BDay)"
        )
        assert fill.fill_date == exec_date, (
            f"fill_date mismatch: got {fill.fill_date}, expected {exec_date}"
        )


def test_signal_date_crosses_weekend(tmp_path):
    """exec_date = Monday → signal_date should land on prior Friday."""
    eng = PaperTradingEngine(
        cost_model=_zero_cost_model(),
        pnl_tracker=PnLTracker(),
        db_path=tmp_path / "p.db",
        initial_capital=10_000.0,
        integer_shares=False,
    )
    exec_date = pd.Timestamp("2024-01-08")   # Monday
    expected_signal_date = pd.Timestamp("2024-01-05")  # Friday (-1 BDay)

    result = eng.run_day_daily(
        exec_date=exec_date,
        target_wts={"AAA": 1.0},
        prev_close={"AAA": 100.0},
        exec_open={"AAA": 100.0},
        eod_close={"AAA": 100.0},
    )

    assert len(result.trades) >= 1
    for fill in result.trades:
        assert fill.signal_date == expected_signal_date, (
            f"weekend signal_date wrong: got {fill.signal_date}, "
            f"expected Friday {expected_signal_date}"
        )
        assert fill.fill_date == exec_date
