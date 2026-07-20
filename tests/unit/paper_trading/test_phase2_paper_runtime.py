from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from core.config.loader import load_config
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.broker_adapter import OrderAck, SimulatedBrokerAdapter
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import Order, OrderSide
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.phase2_runtime import (
    MarketDataQualityError,
    MarketEventGuard,
    PaperRuntimeError,
    PaperStrategySpec,
    Phase2PaperRuntime,
    load_paper_strategy_spec,
)
from core.paper_trading.pnl_tracker import PnLTracker
from core.portfolio.strategy_allocator import (
    AggregateExposurePolicy,
    PortfolioAllocator,
    StrategyRiskBudget,
)
from core.regime.phase2_regime import Phase2RegimeAdapter
from core.regime.regime_detector import RegimeDetector
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.trading.controls import TradingControlStore
from core.trading.risk import PreTradeRiskEngine, RiskLimits
from core.trading.service import OrderRegistrationService
from core.trading.store import OrderStore


class RecordingStrategy:
    required_symbols = ("SPY", "QQQ", "IEF", "GLD", "BIL", "SHY")

    def __init__(self) -> None:
        self.visible_through: list[pd.Timestamp] = []

    def generate(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series | None = None,
    ) -> pd.DataFrame:
        del regime_series
        self.visible_through.append(price_df.index.max())
        weights = pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)
        weights.loc[:, "SPY"] = 0.20
        weights.loc[:, "BIL"] = 0.20
        return weights


class TimeoutBroker(SimulatedBrokerAdapter):
    def mirror_fill(self, fill):
        raise TimeoutError("injected broker timeout")


class UnknownBroker(SimulatedBrokerAdapter):
    def mirror_fill(self, fill):
        return OrderAck(
            order_id="broker-unknown",
            order=fill.order,
            submitted_at=datetime.now(),
            status="UNKNOWN",
        )


class UnexpectedOpenOrderBroker(SimulatedBrokerAdapter):
    def get_open_orders(self):
        order = Order(
            symbol="SPY",
            side=OrderSide.BUY,
            qty_shares=1.0,
            signal_date=pd.Timestamp("2020-01-01"),
        )
        setattr(order, "broker_order_id", "unexpected-broker-order")
        return [order]


def _panel(rows: int = 340) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    index = pd.bdate_range("2019-01-02", periods=rows)
    close = pd.DataFrame(index=index)
    for offset, symbol in enumerate(RecordingStrategy.required_symbols):
        close[symbol] = np.linspace(100.0 + offset, 180.0 + offset, rows)
    open_prices = close * 1.0005
    vix = pd.Series(12.0, index=index, name="vix")
    return close, open_prices, vix


def _cost_model() -> CostModel:
    return CostModel(
        CostModelConfig(
            tiers={
                "default": CostTierConfig(
                    symbols=[],
                    commission_bps=1.0,
                    slippage_interday_bps=4.0,
                    slippage_intraday_bps=7.0,
                )
            }
        )
    )


def _spec() -> PaperStrategySpec:
    loaded = load_paper_strategy_spec(
        "config/strategies.paper.yaml",
        "config/portfolio.paper.yaml",
        "research/registry/strategy_registry.json",
        strategy_id="dual_index_growth_v1",
    )
    return replace(
        loaded,
        allowed_regimes=frozenset(
            {
                "RISK_ON",
                "STRONG_BULL_TREND",
                "NEUTRAL",
                "SIDEWAYS",
                "DEFENSIVE",
                "RISK_OFF",
                "STRESSED",
            }
        ),
        minimum_regime_confidence=0.0,
    )


def test_research_qualified_strategy_cannot_cross_paper_boundary(tmp_path) -> None:
    registry = json.loads(
        Path("research/registry/strategy_registry.json").read_text(encoding="utf-8")
    )
    registry["strategies"][0]["status"] = "RESEARCH_QUALIFIED"
    registry_path = tmp_path / "strategy_registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(PaperRuntimeError, match="not PAPER-approved"):
        load_paper_strategy_spec(
            "config/strategies.paper.yaml",
            "config/portfolio.paper.yaml",
            registry_path,
            strategy_id="dual_index_growth_v1",
        )


def _runtime(
    root: Path,
    *,
    broker_type=SimulatedBrokerAdapter,
    max_daily_turnover: float = 1.0,
) -> tuple[Phase2PaperRuntime, RecordingStrategy]:
    close, open_prices, vix = _panel()
    spec = _spec()
    cost_model = _cost_model()
    ledger = root / "ledger.db"
    broker_db = root / "broker.db"
    order_store = OrderStore(ledger)
    control_store = TradingControlStore(ledger)
    service = OrderRegistrationService(
        order_store,
        PreTradeRiskEngine(
            RiskLimits(
                min_cash_fraction=0.05,
                max_daily_turnover_fraction=max_daily_turnover,
                symbol_caps={"SPY": 0.35, "BIL": 0.35},
            )
        ),
    )
    service.quarantine_after_restart(retry_validated_local_orders=True)
    broker = broker_type(
        cost_model,
        initial_cash=100_000.0,
        state_db_path=broker_db,
    )
    engine = PaperTradingEngine(
        cost_model=cost_model,
        pnl_tracker=PnLTracker(100_000.0),
        db_path=ledger,
        initial_capital=100_000.0,
        eod_force_close=False,
        confluence_enabled=False,
        kill_switch=KillSwitch(KillSwitchConfig(max_drawdown=-0.25)),
        replay_mode=True,
        integer_shares=True,
        broker_adapter=broker,
        order_service=service,
        market_data_fresh=True,
        reconciliation_ok=True,
        manual_pause_check=lambda symbol: control_store.is_paused(
            strategy_id=spec.strategy_id,
            symbol=symbol,
        ),
    )
    allocator = PortfolioAllocator(
        {spec.strategy_id: StrategyRiskBudget(spec.strategy_id, 1.0)},
        AggregateExposurePolicy(
            symbol_caps={
                "SPY": 0.35,
                "QQQ": 0.30,
                "IEF": 0.35,
                "GLD": 0.20,
                "BIL": 0.35,
                "SHY": 0.35,
            }
        ),
    )
    strategy = RecordingStrategy()
    cfg = load_config("config")
    runtime = Phase2PaperRuntime(
        spec=spec,
        strategy=strategy,
        close=close,
        open_prices=open_prices,
        vix=vix,
        regime_detector=RegimeDetector(cfg.regime),
        regime_adapter=Phase2RegimeAdapter(),
        allocator=allocator,
        engine=engine,
        broker=broker,
        order_store=order_store,
        control_store=control_store,
        report_dir=root / "reports",
    )
    return runtime, strategy


def test_causal_replay_restart_is_idempotent_and_report_complete(tmp_path) -> None:
    runtime, first_strategy = _runtime(tmp_path / "restarted")
    dates = runtime.close.index[260:270]
    first = runtime.run_range(dates[0], dates[4])
    assert first_strategy.visible_through == [
        runtime.close.index[runtime.close.index.get_loc(date) - 1]
        for date in dates[:5]
    ]
    assert all(report.payload["live_enabled"] is False for report in first)

    restarted, second_strategy = _runtime(tmp_path / "restarted")
    reports = restarted.run_range(dates[0], dates[-1])
    assert sum(report.reused for report in reports) == 5
    assert second_strategy.visible_through == [
        restarted.close.index[restarted.close.index.get_loc(date) - 1]
        for date in dates[5:]
    ]
    assert len(restarted.engine.load_history()) == 10
    assert len({report.path for report in reports}) == 10
    required = {
        "regime",
        "regime_confidence",
        "enabled_strategies",
        "signals",
        "approved_target",
        "risk_budget",
        "positions",
        "orders",
        "fills",
        "pnl",
        "data_quality",
        "reconciliation",
        "kill_switch",
        "manual_review",
    }
    assert required <= set(reports[-1].payload)

    clean, _ = _runtime(tmp_path / "clean")
    clean.run_range(dates[0], dates[-1])
    assert_frame_equal(restarted.engine.load_history(), clean.engine.load_history())


def test_broker_timeout_isolates_account_and_blocks_following_orders(tmp_path) -> None:
    runtime, _ = _runtime(tmp_path, broker_type=TimeoutBroker)
    dates = runtime.close.index[260:262]
    first = runtime.run_range(dates[0], dates[0])[0]
    assert first.payload["reconciliation"]["passed"] is False
    assert first.payload["kill_switch"]["manual_pause"] is True
    second = runtime.run_range(dates[1], dates[1])[0]
    assert "ACCOUNT_NOT_RECONCILED" in second.payload["rejected_signals"]
    assert second.payload["fills"] == []


def test_broker_unknown_isolates_account(tmp_path) -> None:
    runtime, _ = _runtime(tmp_path, broker_type=UnknownBroker)
    date = runtime.close.index[260]
    report = runtime.run_range(date, date)[0].payload
    assert report["reconciliation"]["passed"] is False
    assert "BROKER_RECONCILIATION_FAILED" in report["manual_review"]
    assert runtime.control_store.is_paused(
        strategy_id=runtime.spec.strategy_id,
        symbol="*",
    )


def test_unexpected_broker_open_order_is_not_hidden(tmp_path) -> None:
    runtime, _ = _runtime(tmp_path, broker_type=UnexpectedOpenOrderBroker)
    assert runtime._reconciliation_ok is False
    assert runtime.control_store.is_paused(
        strategy_id=runtime.spec.strategy_id,
        symbol="*",
    )

    date = runtime.close.index[260]
    report = runtime.run_range(date, date)[0].payload
    assert report["reconciliation"]["unexpected_open_orders"] == [
        "unexpected-broker-order"
    ]


def test_daily_report_includes_pretrade_rejection_reason(tmp_path) -> None:
    runtime, _ = _runtime(tmp_path, max_daily_turnover=0.10)
    date = runtime.close.index[260]
    report = runtime.run_range(date, date)[0].payload
    assert "DAILY_TURNOVER_LIMIT" in report["rejected_signals"]
    assert "PRETRADE_RISK_REJECTION" in report["manual_review"]
    assert any(order["state"] == "REJECTED" for order in report["orders"])


def test_crash_after_broker_fill_is_detected_on_restart(tmp_path, monkeypatch) -> None:
    runtime, _ = _runtime(tmp_path)
    date = runtime.close.index[260]

    def fail_ledger_write(*args, **kwargs):
        raise RuntimeError("injected ledger crash after broker fill")

    monkeypatch.setattr(runtime.engine, "_save_state", fail_ledger_write)
    with pytest.raises(RuntimeError, match="injected ledger crash"):
        runtime.run_range(date, date)
    assert runtime.engine.get_positions() == {}
    assert runtime.broker.get_positions()

    restarted, _ = _runtime(tmp_path)
    assert restarted._reconciliation_ok is False
    assert restarted.control_store.is_paused(
        strategy_id=restarted.spec.strategy_id,
        symbol="*",
    )


def test_post_commit_report_crash_rebuilds_without_duplicate_order(
    tmp_path,
    monkeypatch,
) -> None:
    runtime, _ = _runtime(tmp_path)
    date = runtime.close.index[260]
    original_writer = runtime._atomic_report

    def fail_report(*args, **kwargs):
        raise RuntimeError("injected post-commit report crash")

    monkeypatch.setattr(runtime, "_atomic_report", fail_report)
    with pytest.raises(RuntimeError, match="post-commit report crash"):
        runtime.run_range(date, date)
    orders_after_commit = len(runtime.order_store.list_all())
    assert len(runtime.engine.load_history()) == 1

    monkeypatch.setattr(runtime, "_atomic_report", original_writer)
    recovered = runtime.run_range(date, date)[0]
    assert recovered.reused
    assert recovered.payload["recovery_status"] == "COMMITTED_LEDGER_SESSION_REPORT_REBUILT"
    assert len(runtime.order_store.list_all()) == orders_after_commit
    assert len(runtime.engine.load_history()) == 1


def test_market_event_guard_rejects_missing_stale_duplicate_and_out_of_order() -> None:
    sessions = pd.bdate_range("2024-01-02", periods=3)
    guard = MarketEventGuard(("SPY",), sessions)
    good = {
        "event_id": "one",
        "signal_date": sessions[0],
        "exec_date": sessions[1],
        "data_as_of": sessions[1],
        "prev_close": {"SPY": 100.0},
        "exec_open": {"SPY": 101.0},
        "eod_close": {"SPY": 102.0},
        "vix": 15.0,
    }
    guard.validate(**good)
    guard.complete("one", sessions[1])
    with pytest.raises(MarketDataQualityError, match="duplicate"):
        guard.validate(**good)
    with pytest.raises(MarketDataQualityError, match="out-of-order"):
        guard.validate(**{**good, "event_id": "older"})

    fresh = MarketEventGuard(("SPY",), sessions)
    with pytest.raises(MarketDataQualityError, match="stale"):
        fresh.validate(**{**good, "event_id": "stale", "data_as_of": sessions[0]})
    with pytest.raises(MarketDataQualityError, match="missing"):
        fresh.validate(**{**good, "event_id": "missing", "exec_open": {}})


def test_duplicate_or_unordered_panel_fails_before_strategy(tmp_path) -> None:
    runtime, _ = _runtime(tmp_path)
    duplicate = runtime.close.iloc[[0, 0, 1]].copy()
    with pytest.raises(MarketDataQualityError, match="duplicate or out of order"):
        MarketEventGuard(("SPY",), duplicate.index)
