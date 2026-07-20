from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest

from core.config.loader import load_config
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.broker_adapter import SimulatedBrokerAdapter
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import ExecutionSimulator
from core.execution.target_weight_planner import (
    TargetWeightOrderPlanner,
    TargetWeightPlannerConfig,
)
from core.paper_trading.forward_runtime import (
    ExchangeSessionCalendar,
    ForwardEventPhase,
    ForwardPaperRuntime,
    ForwardRuntimeError,
    ForwardRuntimePolicy,
    MarketEvent,
)
from core.paper_trading.forward_state import ForwardStateStore
from core.paper_trading.phase2_runtime import PaperStrategySpec
from core.portfolio.strategy_allocator import (
    AggregateExposurePolicy,
    PortfolioAllocator,
    StrategyRiskBudget,
)
from core.regime.phase2_regime import Phase2RegimeAdapter
from core.regime.regime_detector import RegimeDetector
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.runtime.lease import SQLiteLeaseManager, StaleFencingTokenError
from core.trading.controls import TradingControlStore
from core.trading.risk import PreTradeRiskEngine, RiskLimits
from core.trading.service import OrderRegistrationService
from core.trading.store import OrderStore

ARTIFACT_HASH = "a" * 64
SIGNAL_SESSION = date(2023, 12, 28)
EXECUTION_SESSION = date(2023, 12, 29)


class RecordingStrategy:
    required_symbols = ("SPY", "QQQ", "IEF", "GLD", "BIL", "SHY")

    def __init__(self) -> None:
        self.visible_through: list[pd.Timestamp] = []

    def generate(self, price_df, regime_series=None):
        del regime_series
        self.visible_through.append(price_df.index.max())
        weights = pd.DataFrame(0.0, index=price_df.index, columns=price_df.columns)
        weights.loc[:, "SPY"] = 0.20
        weights.loc[:, "BIL"] = 0.20
        return weights


@dataclass
class MutableClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class MutableArtifactVerifier:
    def __init__(self) -> None:
        self.root = ARTIFACT_HASH
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return {"artifact_root_sha256": self.root}


def _cost() -> CostModel:
    return CostModel(
        CostModelConfig(
            tiers={
                "default": CostTierConfig(
                    symbols=[],
                    commission_bps=0.0,
                    slippage_interday_bps=0.0,
                    slippage_intraday_bps=0.0,
                )
            }
        )
    )


def _panel(future_multiplier: float = 1.0):
    sessions = mcal.get_calendar("NYSE").valid_days(
        start_date="2022-01-03", end_date="2023-12-29"
    )
    index = pd.DatetimeIndex(sessions).tz_localize(None)[-340:]
    close = pd.DataFrame(index=index)
    for offset, symbol in enumerate(RecordingStrategy.required_symbols):
        close[symbol] = np.linspace(100 + offset, 180 + offset, len(index))
    close.loc[pd.Timestamp(EXECUTION_SESSION)] *= future_multiplier
    opens = close * 1.0005
    vix = pd.Series(15.0, index=index, name="vix")
    return close, opens, vix


def _spec() -> PaperStrategySpec:
    return PaperStrategySpec(
        strategy_id="dual_index_growth_v1",
        version="v1",
        status="PAPER_APPROVED",
        strategy_type="growth_engine",
        asset_universe=RecordingStrategy.required_symbols,
        parameters={"slow_trend": 168, "equity_gross": 0.70, "cooldown_sessions": 21},
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
        regime_integration_mode="quality_fail_closed",
        capital_fraction=1.0,
        max_gross_exposure=1.0,
        max_turnover=8.0,
        priority=10,
        artifact_root_sha256=ARTIFACT_HASH,
    )


def _runtime(root: Path, *, future_multiplier: float = 1.0):
    close, opens, vix = _panel(future_multiplier)
    database = root / "forward.db"
    broker_db = root / "broker.db"
    order_store = OrderStore(database)
    controls = TradingControlStore(database)
    state = ForwardStateStore(database, initial_capital=100_000.0)
    lease = SQLiteLeaseManager(database)
    service = OrderRegistrationService(
        order_store,
        PreTradeRiskEngine(
            RiskLimits(
                min_cash_fraction=0.05,
                max_daily_turnover_fraction=1.0,
                symbol_caps={symbol: 0.35 for symbol in RecordingStrategy.required_symbols},
            )
        ),
    )
    cost = _cost()
    broker = SimulatedBrokerAdapter(
        cost,
        initial_cash=100_000.0,
        state_db_path=broker_db,
    )
    strategy = RecordingStrategy()
    verifier = MutableArtifactVerifier()
    calendar = ExchangeSessionCalendar()
    _, close_time = calendar.boundaries(SIGNAL_SESSION)
    clock = MutableClock(close_time + timedelta(minutes=5))
    cfg = load_config("config")
    runtime = ForwardPaperRuntime(
        spec=_spec(),
        strategy=strategy,
        close=close,
        open_prices=opens,
        vix=vix,
        regime_detector=RegimeDetector(cfg.regime),
        regime_adapter=Phase2RegimeAdapter(),
        allocator=PortfolioAllocator(
            {"dual_index_growth_v1": StrategyRiskBudget("dual_index_growth_v1", 1.0)},
            AggregateExposurePolicy(
                symbol_caps={symbol: 0.35 for symbol in RecordingStrategy.required_symbols}
            ),
        ),
        kill_switch=KillSwitch(KillSwitchConfig(max_drawdown=-0.25)),
        cost_model=cost,
        execution_simulator=ExecutionSimulator(
            cost, freq="interday", allow_partial=True, integer_shares=True
        ),
        order_planner=TargetWeightOrderPlanner(
            TargetWeightPlannerConfig(integer_shares=True)
        ),
        broker=broker,
        order_store=order_store,
        order_service=service,
        control_store=controls,
        state_store=state,
        lease_manager=lease,
        artifact_verifier=verifier,
        clock=clock,
        report_dir=root / "reports",
        calendar=calendar,
    )
    token = lease.acquire(
        "forward-paper",
        "test-worker",
        now=clock.now(),
        ttl=timedelta(days=3),
    )
    return runtime, clock, token, strategy, verifier, order_store


def _event(runtime, clock, phase, session, event_id):
    market_open, market_close = runtime.calendar.boundaries(session)
    boundary = market_open if phase is ForwardEventPhase.OPEN_EXECUTION else market_close
    buffer = timedelta(0)
    if phase is ForwardEventPhase.CLOSE_DECISION:
        buffer = runtime.policy.close_buffer
    elif phase is ForwardEventPhase.EOD_FINALIZE:
        buffer = runtime.policy.eod_buffer
    available = boundary + buffer
    clock.value = available
    return MarketEvent(
        event_id=event_id,
        phase=phase,
        session=session,
        event_time=boundary,
        available_time=available,
        received_time=available,
        source_batch_sha256=hashlib.sha256(phase.value.encode("utf-8")).hexdigest(),
    )


def test_forward_three_stage_lifecycle_is_causal_idempotent_and_recoverable(tmp_path) -> None:
    runtime, clock, token, strategy, verifier, order_store = _runtime(tmp_path)
    close_event = _event(
        runtime, clock, ForwardEventPhase.CLOSE_DECISION, SIGNAL_SESSION, "close-1"
    )
    close_result = runtime.process_close(close_event, token)
    assert close_result["phase"] == "CLOSE_DECISION"
    assert close_result["execution_session"] == EXECUTION_SESSION.isoformat()
    assert strategy.visible_through == [pd.Timestamp(SIGNAL_SESSION)]
    assert runtime.state.decision(SIGNAL_SESSION.isoformat()).state == "FROZEN"

    open_event = _event(
        runtime, clock, ForwardEventPhase.OPEN_EXECUTION, EXECUTION_SESSION, "open-1"
    )
    open_result = runtime.process_open(open_event, token)
    assert open_result["fills"]
    assert runtime.state.decision(SIGNAL_SESSION.isoformat()).state == "EXECUTED"
    orders_after_open = len(order_store.list_all())

    eod_event = _event(
        runtime, clock, ForwardEventPhase.EOD_FINALIZE, EXECUTION_SESSION, "eod-1"
    )
    eod_result = runtime.process_eod(eod_event, token)
    assert eod_result["reconciliation"]["passed"] is True
    assert runtime.state.decision(SIGNAL_SESSION.isoformat()).state == "FINALIZED"
    report = tmp_path / "reports" / f"{EXECUTION_SESSION.isoformat()}.json"
    assert report.exists()

    assert runtime.process_close(close_event, token)["reused"] is True
    assert runtime.process_open(open_event, token)["reused"] is True
    report.unlink()
    assert runtime.process_eod(eod_event, token)["reused"] is True
    assert report.exists()
    assert len(order_store.list_all()) == orders_after_open
    assert verifier.calls >= 6


def test_future_close_changes_cannot_change_prior_frozen_decision(tmp_path) -> None:
    first, first_clock, first_token, first_strategy, _, _ = _runtime(tmp_path / "first")
    second, second_clock, second_token, second_strategy, _, _ = _runtime(
        tmp_path / "second", future_multiplier=9.0
    )
    first_result = first.process_close(
        _event(first, first_clock, ForwardEventPhase.CLOSE_DECISION, SIGNAL_SESSION, "close"),
        first_token,
    )
    second_result = second.process_close(
        _event(second, second_clock, ForwardEventPhase.CLOSE_DECISION, SIGNAL_SESSION, "close"),
        second_token,
    )
    assert first_result["decision_id"] == second_result["decision_id"]
    assert first_strategy.visible_through == second_strategy.visible_through == [
        pd.Timestamp(SIGNAL_SESSION)
    ]


def test_open_and_eod_cannot_run_out_of_order(tmp_path) -> None:
    runtime, clock, token, *_ = _runtime(tmp_path)
    open_event = _event(
        runtime, clock, ForwardEventPhase.OPEN_EXECUTION, EXECUTION_SESSION, "open"
    )
    with pytest.raises(ForwardRuntimeError, match="no frozen"):
        runtime.process_open(open_event, token)
    eod_event = _event(
        runtime, clock, ForwardEventPhase.EOD_FINALIZE, EXECUTION_SESSION, "eod"
    )
    with pytest.raises(ForwardRuntimeError, match="no EXECUTED"):
        runtime.process_eod(eod_event, token)


def test_artifact_drift_between_close_and_open_pauses_account(tmp_path) -> None:
    runtime, clock, token, _, verifier, _ = _runtime(tmp_path)
    runtime.process_close(
        _event(
            runtime,
            clock,
            ForwardEventPhase.CLOSE_DECISION,
            SIGNAL_SESSION,
            "close",
        ),
        token,
    )
    verifier.root = "b" * 64
    with pytest.raises(ForwardRuntimeError, match="artifact root mismatch"):
        runtime.process_open(
            _event(
                runtime,
                clock,
                ForwardEventPhase.OPEN_EXECUTION,
                EXECUTION_SESSION,
                "open",
            ),
            token,
        )
    assert runtime.control_store.is_paused(
        strategy_id=runtime.spec.strategy_id, symbol="*"
    )


def test_stale_and_prebuffer_events_are_rejected(tmp_path) -> None:
    runtime, clock, token, *_ = _runtime(tmp_path)
    _, close_time = runtime.calendar.boundaries(SIGNAL_SESSION)
    early = MarketEvent(
        event_id="early",
        phase=ForwardEventPhase.CLOSE_DECISION,
        session=SIGNAL_SESSION,
        event_time=close_time,
        available_time=close_time,
        received_time=close_time,
        source_batch_sha256="e" * 64,
    )
    clock.value = close_time
    with pytest.raises(ForwardRuntimeError, match="completion buffer"):
        runtime.process_close(early, token)

    valid = _event(
        runtime, clock, ForwardEventPhase.CLOSE_DECISION, SIGNAL_SESSION, "stale"
    )
    clock.value = valid.received_time + runtime.policy.max_event_lag + timedelta(seconds=1)
    with pytest.raises(ForwardRuntimeError, match="stale"):
        runtime.process_close(valid, token)


def test_stale_writer_is_fenced_before_any_decision_write(tmp_path) -> None:
    runtime, clock, token, *_ = _runtime(tmp_path)
    event = _event(
        runtime, clock, ForwardEventPhase.CLOSE_DECISION, SIGNAL_SESSION, "close"
    )
    stale = replace(token, expires_at=clock.now() - timedelta(seconds=1))
    with pytest.raises(ForwardRuntimeError, match="writer lease is stale"):
        runtime.process_close(event, stale)
    assert runtime.state.decision(SIGNAL_SESSION.isoformat()) is None


def test_writer_expiring_during_computation_is_fenced_at_commit(tmp_path) -> None:
    runtime, clock, token, strategy, *_ = _runtime(tmp_path)
    event = _event(
        runtime, clock, ForwardEventPhase.CLOSE_DECISION, SIGNAL_SESSION, "close"
    )

    class SlowStrategy:
        def generate(self, price_df, regime_series=None):
            result = strategy.generate(price_df, regime_series)
            clock.value += timedelta(seconds=2)
            return result

    runtime.strategy = SlowStrategy()
    expiring = replace(token, expires_at=clock.now() + timedelta(seconds=1))
    with pytest.raises(StaleFencingTokenError, match="expired"):
        runtime.process_close(event, expiring)
    assert runtime.state.decision(SIGNAL_SESSION.isoformat()) is None


def test_current_session_eod_must_precede_next_close_decision(tmp_path) -> None:
    runtime, clock, token, *_ = _runtime(tmp_path)
    runtime.process_close(
        _event(
            runtime,
            clock,
            ForwardEventPhase.CLOSE_DECISION,
            SIGNAL_SESSION,
            "close-1",
        ),
        token,
    )
    runtime.process_open(
        _event(
            runtime,
            clock,
            ForwardEventPhase.OPEN_EXECUTION,
            EXECUTION_SESSION,
            "open-1",
        ),
        token,
    )
    next_close = _event(
        runtime,
        clock,
        ForwardEventPhase.CLOSE_DECISION,
        EXECUTION_SESSION,
        "close-2",
    )
    with pytest.raises(ForwardRuntimeError, match="EOD must be finalized"):
        runtime.process_close(next_close, token)

    runtime.process_eod(
        _event(
            runtime,
            clock,
            ForwardEventPhase.EOD_FINALIZE,
            EXECUTION_SESSION,
            "eod-1",
        ),
        token,
    )
    clock.value = next_close.received_time
    result = runtime.process_close(next_close, token)
    assert result["session"] == EXECUTION_SESSION.isoformat()


def test_policy_requires_eod_buffer_before_close_buffer() -> None:
    with pytest.raises(ValueError, match="follow the EOD"):
        ForwardRuntimePolicy(
            close_buffer=timedelta(minutes=5),
            eod_buffer=timedelta(minutes=5),
        )
