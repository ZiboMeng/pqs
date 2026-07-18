from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import Order, OrderSide
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.trading import OrderStore, PreTradeRiskEngine, RiskLimits
from core.trading.order import OrderState
from core.trading.service import OrderRegistrationService


def bars() -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2026-04-27 10:30", periods=4, freq="60min")
    prices = np.full(4, 100.0)
    return {
        "SPY": pd.DataFrame(
            {
                "open": prices,
                "high": prices + 1,
                "low": prices - 1,
                "close": prices,
                "volume": np.full(4, 1_000_000),
            },
            index=idx,
        )
    }


def engine(
    tmp_path: Path,
    *,
    data_fresh: bool,
    manually_paused: bool = False,
) -> tuple[PaperTradingEngine, OrderStore]:
    cfg = load_config(Path("config"))
    db_path = tmp_path / "paper.db"
    store = OrderStore(db_path)
    service = OrderRegistrationService(
        store,
        PreTradeRiskEngine(
            RiskLimits(
                max_single_position=0.60,
                max_gross_exposure=1.0,
                min_cash_fraction=0.05,
                max_order_notional_fraction=0.60,
            )
        ),
    )
    paper = PaperTradingEngine(
        cost_model=CostModel(cfg.cost_model),
        pnl_tracker=PnLTracker(10_000),
        db_path=db_path,
        initial_capital=10_000,
        eod_force_close=False,
        order_service=service,
        market_data_fresh=data_fresh,
        reconciliation_ok=True,
        manual_pause_check=lambda _symbol: manually_paused,
    )
    return paper, store


def test_stale_data_veto_prevents_fill_and_is_auditable(tmp_path):
    paper, store = engine(tmp_path, data_fresh=False)
    result = paper.run_day_intraday(
        run_id="paper-live-2026-04-27",
        date=pd.Timestamp("2026-04-27"),
        day_bars=bars(),
        target_wts={"SPY": 0.50},
    )
    assert result.n_trades == 0
    assert paper.get_positions() == {}

    orders = store.list_all()
    assert orders[0].state is OrderState.REJECTED
    events = store.events(orders[0].intent.order_id)
    assert events[-1]["metadata"]["reason_codes"] == ["STALE_MARKET_DATA"]


def test_fresh_order_runs_through_durable_lifecycle_once(tmp_path):
    paper, store = engine(tmp_path, data_fresh=True)
    kwargs = {
        "run_id": "paper-live-2026-04-27",
        "date": pd.Timestamp("2026-04-27"),
        "day_bars": bars(),
        "target_wts": {"SPY": 0.50},
    }
    first = paper.run_day_intraday(**kwargs)
    assert first.n_trades == 1
    assert paper.get_positions()["SPY"] > 0

    orders = store.list_all()
    assert len(orders) == 1
    assert orders[0].state is OrderState.FILLED
    assert [
        event["to_state"] for event in store.events(orders[0].intent.order_id)
    ] == [
        "CREATED",
        "VALIDATED",
        "SUBMITTED",
        "ACKNOWLEDGED",
        "FILLED",
    ]

    # Same run/bar is checkpointed; restart/retry cannot create another order.
    second = paper.run_day_intraday(**kwargs)
    assert second.n_trades == 0
    assert len(store.list_all()) == 1


def test_durable_manual_pause_vetoes_before_fill(tmp_path):
    paper, store = engine(tmp_path, data_fresh=True, manually_paused=True)
    result = paper.run_day_intraday(
        run_id="paused-run",
        date=pd.Timestamp("2026-04-27"),
        day_bars=bars(),
        target_wts={"SPY": 0.50},
    )
    assert result.n_trades == 0
    assert store.list_all()[0].state is OrderState.REJECTED
    events = store.events(store.list_all()[0].intent.order_id)
    assert events[-1]["metadata"]["reason_codes"] == ["MANUAL_PAUSE_ACTIVE"]


def test_batch_orders_use_sequential_virtual_account_snapshot(tmp_path):
    cfg = load_config(Path("config"))
    db_path = tmp_path / "batch.db"
    store = OrderStore(db_path)
    service = OrderRegistrationService(
        store,
        PreTradeRiskEngine(
            RiskLimits(
                max_single_position=0.60,
                max_gross_exposure=1.0,
                min_cash_fraction=0.05,
                max_order_notional_fraction=0.60,
            )
        ),
    )
    paper = PaperTradingEngine(
        cost_model=CostModel(cfg.cost_model),
        pnl_tracker=PnLTracker(10_000),
        db_path=db_path,
        initial_capital=10_000,
        eod_force_close=False,
        order_service=service,
        market_data_fresh=True,
        reconciliation_ok=True,
    )
    signal_date = pd.Timestamp("2026-04-27")
    orders = [
        Order("AAA", OrderSide.BUY, 50.0, signal_date),
        Order("BBB", OrderSide.BUY, 50.0, signal_date),
    ]

    accepted = paper._apply_pretrade_boundary(
        orders,
        run_id="batch-risk",
        bar_ts=signal_date,
        session_date=signal_date,
        positions={},
        cash=10_000.0,
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=10_000.0,
    )

    assert [order.symbol for order in accepted] == ["AAA"]
    stored = store.list_all()
    assert len(stored) == 2
    rejected = next(order for order in stored if order.intent.symbol == "BBB")
    assert rejected.state is OrderState.REJECTED
    assert "MIN_CASH_BREACH" in store.events(rejected.intent.order_id)[-1][
        "metadata"
    ]["reason_codes"]


def test_daily_turnover_persists_across_restart(tmp_path):
    paper, _ = engine(tmp_path, data_fresh=True)
    result = paper.run_day_intraday(
        run_id="turnover-session",
        date=pd.Timestamp("2026-04-27"),
        day_bars=bars(),
        target_wts={"SPY": 0.50},
    )
    assert result.trades

    restarted, _ = engine(tmp_path, data_fresh=True)
    assert restarted._risk_session_date == pd.Timestamp("2026-04-27")
    assert restarted._daily_turnover > 0.0


def test_intraday_fill_account_and_checkpoint_rollback_and_retry_atomically(
    tmp_path, monkeypatch
):
    paper, store = engine(tmp_path, data_fresh=True)
    original_writer = paper.save_intraday_bar

    def fail_inside_execution_transaction(*args, **kwargs):
        raise RuntimeError("injected crash before account commit")

    monkeypatch.setattr(paper, "save_intraday_bar", fail_inside_execution_transaction)
    kwargs = {
        "run_id": "atomic-retry",
        "date": pd.Timestamp("2026-04-27"),
        "day_bars": bars(),
        "target_wts": {"SPY": 0.50},
    }
    with pytest.raises(RuntimeError, match="injected crash"):
        paper.run_day_intraday(**kwargs)

    # The order intent/risk decision predates execution and remains safely
    # retryable.  FILLED, fill rows, account state, and checkpoint all roll
    # back together.
    failed_order = store.list_all()[0]
    assert failed_order.state is OrderState.VALIDATED
    with sqlite3.connect(tmp_path / "paper.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM intraday_fills").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM bar_checkpoints").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM pt_state").fetchone()[0] == 0

    monkeypatch.setattr(paper, "save_intraday_bar", original_writer)
    recovered = paper._order_service.quarantine_after_restart(
        retry_validated_local_orders=True
    )
    assert recovered[0].state is OrderState.VALIDATED
    result = paper.run_day_intraday(**kwargs)
    assert result.n_trades == 1
    assert store.list_all()[0].state is OrderState.FILLED
    with sqlite3.connect(tmp_path / "paper.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM intraday_fills").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM bar_checkpoints").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM pt_state").fetchone()[0] == 1


def test_daily_fill_and_account_state_rollback_together(tmp_path, monkeypatch):
    paper, store = engine(tmp_path, data_fresh=True)
    original_writer = paper._save_state

    def fail_state_write(*args, **kwargs):
        raise RuntimeError("injected daily state failure")

    monkeypatch.setattr(paper, "_save_state", fail_state_write)
    kwargs = {
        "exec_date": pd.Timestamp("2026-04-28"),
        "signal_date": pd.Timestamp("2026-04-27"),
        "target_wts": {"SPY": 0.50},
        "prev_close": {"SPY": 100.0},
        "exec_open": {"SPY": 100.0},
        "eod_close": {"SPY": 100.0},
    }
    with pytest.raises(RuntimeError, match="injected daily"):
        paper.run_day_daily(**kwargs)
    assert paper.get_positions() == {}
    assert paper.get_cash() == 10_000.0
    assert store.list_all()[0].state is OrderState.VALIDATED

    monkeypatch.setattr(paper, "_save_state", original_writer)
    result = paper.run_day_daily(**kwargs)
    assert result.n_trades == 1
    assert store.list_all()[0].state is OrderState.FILLED
    restarted, _ = engine(tmp_path, data_fresh=True)
    assert restarted.get_positions()["SPY"] > 0
    assert restarted.get_cash() < 10_000.0
