from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
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
