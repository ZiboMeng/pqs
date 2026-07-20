"""Three-stage, market-time Forward PAPER runtime."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
import pandas_market_calendars as mcal

from core.execution.broker_adapter import BrokerAdapter
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import ExecutionSimulator, Fill, Order, OrderSide
from core.execution.target_weight_planner import TargetWeightOrderPlanner
from core.paper_trading.forward_state import (
    ForwardStateStore,
    content_hash,
)
from core.paper_trading.phase2_runtime import PaperStrategySpec, StrategyProtocol
from core.portfolio.strategy_allocator import PortfolioAllocator
from core.regime.phase2_regime import Phase2RegimeAdapter, fail_closed_regime_scale
from core.regime.regime_detector import RegimeDetector
from core.risk.kill_switch import KillSwitch
from core.runtime.lease import LeaseToken, SQLiteLeaseManager
from core.trading.controls import ControlScope, TradingControlStore
from core.trading.order import OrderIntent, OrderState, TradingSide
from core.trading.reconciliation import (
    AccountSnapshot,
    ReconciliationResult,
    ReconciliationService,
)
from core.trading.risk import RiskSnapshot
from core.trading.service import OrderRegistrationService
from core.trading.store import OrderStore


class ForwardRuntimeError(RuntimeError):
    """Raised when a forward event cannot be processed safely."""


class ForwardEventPhase(StrEnum):
    CLOSE_DECISION = "CLOSE_DECISION"
    OPEN_EXECUTION = "OPEN_EXECUTION"
    EOD_FINALIZE = "EOD_FINALIZE"


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass(frozen=True, slots=True)
class ForwardRuntimePolicy:
    # EOD for session T must finish before the close decision for T+1 is
    # frozen.  Separate buffers make that ordering explicit for a daily-bar
    # runtime instead of relying on scheduler race order at one timestamp.
    close_buffer: timedelta = timedelta(minutes=10)
    eod_buffer: timedelta = timedelta(minutes=5)
    max_event_lag: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if min(self.close_buffer, self.eod_buffer, self.max_event_lag) < timedelta(0):
            raise ValueError("forward runtime timing policies cannot be negative")
        if self.close_buffer <= self.eod_buffer:
            raise ValueError("close decision buffer must follow the EOD buffer")


@dataclass(frozen=True, slots=True)
class MarketEvent:
    event_id: str
    phase: ForwardEventPhase
    session: date
    event_time: datetime
    available_time: datetime
    received_time: datetime
    source_batch_sha256: str

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event id is required")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_batch_sha256):
            raise ValueError("source batch hash must be lowercase SHA256 hex")
        for value in (self.event_time, self.available_time, self.received_time):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("market event timestamps must be timezone-aware")
        if self.available_time < self.event_time or self.received_time < self.available_time:
            raise ValueError("market event times must satisfy event <= available <= received")

    def payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "phase": self.phase.value,
            "session": self.session.isoformat(),
            "event_time": self.event_time.astimezone(UTC).isoformat(),
            "available_time": self.available_time.astimezone(UTC).isoformat(),
            "received_time": self.received_time.astimezone(UTC).isoformat(),
            "source_batch_sha256": self.source_batch_sha256,
        }


class ExchangeSessionCalendar:
    def __init__(self, name: str = "NYSE") -> None:
        self._calendar = mcal.get_calendar(name)

    def boundaries(self, session: date) -> tuple[datetime, datetime]:
        schedule = self._calendar.schedule(start_date=session, end_date=session)
        if schedule.empty:
            raise ForwardRuntimeError(f"not a valid exchange session: {session}")
        row = schedule.iloc[0]
        return (
            pd.Timestamp(row["market_open"]).to_pydatetime().astimezone(UTC),
            pd.Timestamp(row["market_close"]).to_pydatetime().astimezone(UTC),
        )

    def next_session(self, session: date) -> date:
        sessions = self._calendar.valid_days(
            start_date=session + timedelta(days=1),
            end_date=session + timedelta(days=14),
        )
        if sessions.empty:
            raise ForwardRuntimeError(f"cannot resolve next exchange session after {session}")
        return pd.Timestamp(sessions[0]).date()


ArtifactVerifier = Callable[[], Mapping[str, Any]]


class ForwardPaperRuntime:
    """Freeze decisions at close, execute at next open, finalize after EOD."""

    def __init__(
        self,
        *,
        spec: PaperStrategySpec,
        strategy: StrategyProtocol,
        close: pd.DataFrame,
        open_prices: pd.DataFrame,
        vix: pd.Series,
        regime_detector: RegimeDetector,
        regime_adapter: Phase2RegimeAdapter,
        allocator: PortfolioAllocator,
        kill_switch: KillSwitch,
        cost_model: CostModel,
        execution_simulator: ExecutionSimulator,
        order_planner: TargetWeightOrderPlanner,
        broker: BrokerAdapter,
        order_store: OrderStore,
        order_service: OrderRegistrationService,
        control_store: TradingControlStore,
        state_store: ForwardStateStore,
        lease_manager: SQLiteLeaseManager,
        artifact_verifier: ArtifactVerifier,
        clock: Clock,
        report_dir: str | Path,
        calendar: ExchangeSessionCalendar | None = None,
        policy: ForwardRuntimePolicy | None = None,
    ) -> None:
        if spec.status != "PAPER_APPROVED" or spec.artifact_root_sha256 is None:
            raise ForwardRuntimeError("Forward PAPER requires an approved verified artifact")
        if order_store.db_path.resolve() != state_store.db_path.resolve():
            raise ForwardRuntimeError("order and forward state must share one atomic database")
        if lease_manager.db_path.resolve() != state_store.db_path.resolve():
            raise ForwardRuntimeError("lease and forward state must share one database")
        self.spec = spec
        self.strategy = strategy
        self.close = close.sort_index()
        self.open_prices = open_prices.reindex(self.close.index)
        self.vix = vix.reindex(self.close.index)
        self.regime_detector = regime_detector
        self.regime_adapter = regime_adapter
        self.allocator = allocator
        self.kill_switch = kill_switch
        self.cost_model = cost_model
        self.execution_simulator = execution_simulator
        self.order_planner = order_planner
        self.broker = broker
        self.order_store = order_store
        self.order_service = order_service
        self.control_store = control_store
        self.state = state_store
        self.lease_manager = lease_manager
        self.artifact_verifier = artifact_verifier
        self.clock = clock
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.calendar = calendar or ExchangeSessionCalendar()
        self.policy = policy or ForwardRuntimePolicy()
        self.reconciliation = ReconciliationService(control_store)
        self._validate_panels()

    def _validate_panels(self) -> None:
        required = set(self.spec.asset_universe)
        if self.close.empty or not isinstance(self.close.index, pd.DatetimeIndex):
            raise ForwardRuntimeError("forward close panel is empty or lacks DatetimeIndex")
        if not self.close.index.is_monotonic_increasing or not self.close.index.is_unique:
            raise ForwardRuntimeError("forward close panel must be sorted and unique")
        for name, frame in (("close", self.close), ("open", self.open_prices)):
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ForwardRuntimeError(f"{name} panel missing symbols: {missing}")

    def _verify_artifact(self) -> Mapping[str, Any]:
        try:
            artifact = self.artifact_verifier()
        except Exception as exc:
            self._pause(f"strategy artifact verification unavailable: {exc}")
            raise ForwardRuntimeError(f"strategy artifact verification failed: {exc}") from exc
        if artifact.get("artifact_root_sha256") != self.spec.artifact_root_sha256:
            self._pause("strategy artifact root differs from loaded PAPER spec")
            raise ForwardRuntimeError("strategy artifact root mismatch")
        return artifact

    def _validate_event(self, event: MarketEvent, expected: ForwardEventPhase) -> None:
        if event.phase is not expected:
            raise ForwardRuntimeError(f"expected {expected.value}, received {event.phase.value}")
        now = self.clock.now().astimezone(UTC)
        if now < event.received_time.astimezone(UTC):
            raise ForwardRuntimeError("clock precedes event receipt")
        if now - event.received_time.astimezone(UTC) > self.policy.max_event_lag:
            raise ForwardRuntimeError("market event is stale")
        market_open, market_close = self.calendar.boundaries(event.session)
        boundary = market_open if expected is ForwardEventPhase.OPEN_EXECUTION else market_close
        if abs(event.event_time.astimezone(UTC) - boundary) > timedelta(seconds=1):
            raise ForwardRuntimeError("market event time does not match exchange boundary")
        minimum_available = boundary
        if expected is ForwardEventPhase.CLOSE_DECISION:
            minimum_available += self.policy.close_buffer
        elif expected is ForwardEventPhase.EOD_FINALIZE:
            minimum_available += self.policy.eod_buffer
        if event.available_time.astimezone(UTC) < minimum_available:
            raise ForwardRuntimeError("market event arrived before its completion buffer")

    def _row(self, frame: pd.DataFrame, session: date, label: str) -> dict[str, float]:
        timestamp = pd.Timestamp(session)
        if timestamp not in frame.index:
            raise ForwardRuntimeError(f"{label} data missing session {session}")
        values = frame.loc[timestamp, list(self.spec.asset_universe)]
        invalid = [
            symbol
            for symbol, value in values.items()
            if not math.isfinite(float(value)) or float(value) <= 0
        ]
        if invalid:
            raise ForwardRuntimeError(f"{label} data contains invalid values: {invalid}")
        return {str(symbol): float(value) for symbol, value in values.items()}

    def _vix(self, session: date) -> float:
        timestamp = pd.Timestamp(session)
        if timestamp not in self.vix.index:
            raise ForwardRuntimeError(f"VIX missing exact session {session}")
        value = float(self.vix.loc[timestamp])
        if not math.isfinite(value) or value <= 0:
            raise ForwardRuntimeError(f"VIX invalid for session {session}")
        return value

    def _pause(self, reason: str) -> None:
        self.control_store.set_paused(
            ControlScope.GLOBAL,
            "*",
            paused=True,
            reason=reason,
            updated_by="system:forward-paper-runtime",
        )

    def _assert_writer_lease(self, token: LeaseToken) -> None:
        try:
            self.lease_manager.assert_valid(token, now=self.clock.now())
        except Exception as exc:
            raise ForwardRuntimeError(f"forward writer lease is stale: {exc}") from exc

    def _reconcile(self, now: datetime) -> ReconciliationResult:
        account = self.state.account()
        expected_orders = frozenset(
            order.broker_order_id or order.intent.order_id
            for order in self.order_store.list_nonterminal()
            if order.state not in {OrderState.CREATED, OrderState.VALIDATED}
        )
        expected = AccountSnapshot(
            cash=account.cash,
            positions=account.positions,
            open_order_ids=expected_orders,
            observed_at=now,
            source="forward_paper_ledger",
        )
        try:
            actual = AccountSnapshot(
                cash=self.broker.get_cash(),
                positions=self.broker.get_positions(),
                open_order_ids=self.broker.get_open_order_ids(),
                observed_at=now,
                source="paper_broker",
            )
            return self.reconciliation.reconcile(expected, actual)
        except Exception as exc:
            self._pause(f"forward broker reconciliation unavailable: {exc}")
            return ReconciliationResult(False, 0.0, {}, frozenset(), frozenset())

    def process_close(self, event: MarketEvent, token: LeaseToken) -> dict[str, Any]:
        if event.phase is not ForwardEventPhase.CLOSE_DECISION:
            raise ForwardRuntimeError("expected CLOSE_DECISION event")
        artifact = self._verify_artifact()
        event_sha = content_hash(event.payload())
        existing = self.state.event_result(event.event_id, event_sha)
        if existing is not None:
            return {**existing, "reused": True}
        self._validate_event(event, ForwardEventPhase.CLOSE_DECISION)
        self._assert_writer_lease(token)
        signal_ts = pd.Timestamp(event.session)
        if signal_ts not in self.close.index:
            raise ForwardRuntimeError(f"signal session absent from close panel: {event.session}")
        history = self.close.loc[:signal_ts, list(self.spec.asset_universe)]
        if history.index.max() != signal_ts:
            raise ForwardRuntimeError("close history is not bounded at the signal session")
        self._row(self.close, event.session, "close")
        signal_vix = self._vix(event.session)
        current_session_decision = self.state.decision_for_execution(
            event.session.isoformat()
        )
        if (
            current_session_decision is not None
            and current_session_decision.state != "FINALIZED"
        ):
            raise ForwardRuntimeError(
                "current session EOD must be finalized before its close decision"
            )
        account = self.state.account()
        if (
            account.last_finalized_session is not None
            and account.last_finalized_session != event.session.isoformat()
        ):
            raise ForwardRuntimeError(
                "current session EOD must be finalized before its close decision"
            )
        reconcile = self._reconcile(self.clock.now().astimezone(UTC))
        legacy = self.regime_detector.classify_series(
            history["SPY"], self.vix.loc[:signal_ts]
        )
        regime = self.regime_adapter.classify(legacy, history["SPY"])
        regime_label = str(regime.state.loc[signal_ts])
        regime_confidence = float(regime.confidence.loc[signal_ts])
        raw_target = self.strategy.generate(history).loc[signal_ts].astype(float)
        enabled = (
            regime_label in self.spec.allowed_regimes
            and regime_confidence >= self.spec.minimum_regime_confidence
        )
        requested = raw_target if enabled else raw_target * 0.0
        nav = self.state.nav_history()
        equity_curve = pd.Series(
            [float(item["equity"]) for item in nav] or [self.state.account().equity],
            dtype=float,
        )
        kill_result = self.kill_switch.evaluate(
            equity_curve,
            vix=signal_vix,
            weights=requested.to_dict(),
        )
        manually_paused = self.control_store.is_paused(
            strategy_id=self.spec.strategy_id, symbol="*"
        )
        allocation = self.allocator.allocate(
            {self.spec.strategy_id: requested},
            regime_label=regime_label,
            regime_confidence=regime_confidence,
            data_fresh=True,
            reconciled=reconcile.passed,
            global_kill_switch=(kill_result.state == "SUSPENDED" or manually_paused),
        )
        approved = allocation.weights if allocation.accepted else allocation.weights * 0.0
        if self.spec.regime_integration_mode == "exposure_scaled":
            cap = float(
                fail_closed_regime_scale(
                    pd.Series([regime_label], index=[signal_ts]),
                    pd.Series([regime_confidence], index=[signal_ts]),
                ).iloc[0]
            )
            gross = float(approved.sum())
            if gross > cap and gross > 0:
                approved = approved * (cap / gross)
        approved *= float(kill_result.position_multiplier)
        execution_session = self.calendar.next_session(event.session)
        decision_core = {
            "strategy_id": self.spec.strategy_id,
            "strategy_version": self.spec.version,
            "artifact_root_sha256": artifact["artifact_root_sha256"],
            "signal_session": event.session.isoformat(),
            "execution_session": execution_session.isoformat(),
            "source_batch_sha256": event.source_batch_sha256,
            "data_available_cutoff_utc": event.available_time.astimezone(UTC).isoformat(),
            "data_visible_through": history.index.max().date().isoformat(),
            "history_sha256": content_hash(
                {
                    "close_json": history.to_json(date_format="iso", double_precision=15),
                    "vix_json": self.vix.loc[:signal_ts].to_json(
                        date_format="iso", double_precision=15
                    ),
                }
            ),
            "regime": regime_label,
            "regime_confidence": regime_confidence,
            "enabled": enabled,
            "raw_target": {str(k): float(v) for k, v in raw_target.items()},
            "approved_target": {str(k): float(v) for k, v in approved.items()},
            "allocation_vetoes": list(allocation.veto_reasons),
            "kill_switch_state": kill_result.state,
            "account_equity_at_decision": account.equity,
            "vix": signal_vix,
        }
        decision_id = f"fd_{content_hash(decision_core)}"
        payload = {**decision_core, "decision_id": decision_id}
        result = {
            "schema_version": 1,
            "mode": "FORWARD_PAPER",
            "live_enabled": False,
            "phase": ForwardEventPhase.CLOSE_DECISION.value,
            "session": event.session.isoformat(),
            "execution_session": execution_session.isoformat(),
            "decision_id": decision_id,
            "artifact_root_sha256": artifact["artifact_root_sha256"],
            "approved_target": payload["approved_target"],
            "regime": regime_label,
            "reconciliation_passed": reconcile.passed,
            "fencing_token": token.fencing_token,
            "reused": False,
        }
        commit_time = self.clock.now().astimezone(UTC)
        reused = self.state.record_decision(
            event_id=event.event_id,
            event_sha256=event_sha,
            signal_session=event.session.isoformat(),
            execution_session=execution_session.isoformat(),
            decision_id=decision_id,
            artifact_root_sha256=str(artifact["artifact_root_sha256"]),
            payload=payload,
            result=result,
            token=token,
            lease_manager=self.lease_manager,
            now=commit_time,
        )
        return {**result, "reused": reused}

    def process_open(self, event: MarketEvent, token: LeaseToken) -> dict[str, Any]:
        if event.phase is not ForwardEventPhase.OPEN_EXECUTION:
            raise ForwardRuntimeError("expected OPEN_EXECUTION event")
        artifact = self._verify_artifact()
        event_sha = content_hash(event.payload())
        existing = self.state.event_result(event.event_id, event_sha)
        if existing is not None:
            return {**existing, "reused": True}
        self._validate_event(event, ForwardEventPhase.OPEN_EXECUTION)
        self._assert_writer_lease(token)
        decision = self.state.decision_for_execution(event.session.isoformat())
        if decision is None:
            raise ForwardRuntimeError("no frozen prior-close decision for open event")
        if decision.state != "FROZEN":
            raise ForwardRuntimeError(f"decision is not executable: {decision.state}")
        if decision.artifact_root_sha256 != artifact["artifact_root_sha256"]:
            self._pause("frozen decision artifact differs at execution")
            raise ForwardRuntimeError("decision artifact drift")
        reconcile = self._reconcile(self.clock.now().astimezone(UTC))
        if not reconcile.passed:
            raise ForwardRuntimeError("broker reconciliation failed before open execution")
        signal_session = date.fromisoformat(decision.signal_session)
        prior_close = self._row(self.close, signal_session, "prior close")
        execution_open = self._row(self.open_prices, event.session, "execution open")
        account = self.state.account()
        execution_equity = account.cash + sum(
            quantity
            * float(execution_open.get(symbol, prior_close.get(symbol, float("nan"))))
            for symbol, quantity in account.positions.items()
        )
        planned = self.order_planner.plan(
            target_weights=decision.payload["approved_target"],
            positions=account.positions,
            cash=account.cash,
            prior_close=prior_close,
            execution_open=execution_open,
            signal_date=pd.Timestamp(signal_session),
        )
        accepted: list[Order] = []
        virtual_cash = account.cash
        virtual_positions = dict(account.positions)
        virtual_turnover = 0.0
        for order in planned:
            reference_price = execution_open[order.symbol]
            order_notional = order.qty_shares * reference_price
            estimated_cost = self.cost_model.estimate_cost(
                order.symbol, order_notional, "interday", decision.payload["vix"]
            ).total_cost_usd
            intent = OrderIntent(
                symbol=order.symbol,
                side=TradingSide(order.side.value),
                quantity=float(order.qty_shares),
                reference_price=reference_price,
                signal_id=decision.decision_id,
                strategy_id=self.spec.strategy_id,
                decision_id=decision.decision_id,
                idempotency_key=(
                    f"{self.spec.strategy_id}:{decision.decision_id}:"
                    f"{order.symbol}:{order.side.value}"
                ),
                comment="phase3_forward_open",
            )
            snapshot = RiskSnapshot(
                equity=execution_equity,
                cash=virtual_cash,
                positions=dict(virtual_positions),
                prices=execution_open,
                daily_turnover=virtual_turnover,
                estimated_order_cost=estimated_cost,
                data_fresh=True,
                kill_switch_active=(decision.payload["kill_switch_state"] == "SUSPENDED"),
                manual_pause=self.control_store.is_paused(
                    strategy_id=self.spec.strategy_id, symbol=order.symbol
                ),
                reconciliation_ok=True,
            )
            registration = self.order_service.register(intent, snapshot)
            if registration.duplicate:
                if registration.order.state is not OrderState.VALIDATED:
                    continue
            elif registration.order.state is not OrderState.VALIDATED:
                continue
            setattr(order, "canonical_order_id", registration.order.intent.order_id)
            accepted.append(order)
            quantity = float(order.qty_shares)
            if order.side is OrderSide.BUY:
                virtual_positions[order.symbol] = virtual_positions.get(order.symbol, 0.0) + quantity
                virtual_cash -= order_notional + estimated_cost
            else:
                virtual_positions[order.symbol] = max(
                    virtual_positions.get(order.symbol, 0.0) - quantity, 0.0
                )
                virtual_cash += order_notional - estimated_cost
            virtual_turnover += order_notional

        fills = self.execution_simulator.simulate_fills(
            accepted,
            execution_open,
            float(decision.payload["vix"]),
            account.cash,
            fill_date=pd.Timestamp(event.session),
        )
        fill_by_order = {id(fill.order): fill for fill in fills}
        mirrored: list[tuple[str, str, Fill]] = []
        try:
            for fill in fills:
                mirror = getattr(self.broker, "mirror_fill", None)
                ack = mirror(fill) if callable(mirror) else self.broker.submit_order(fill.order)
                if ack.status != "ACCEPTED":
                    raise ForwardRuntimeError(
                        f"paper broker rejected mirrored fill: {ack.reject_reason}"
                    )
                order_id = str(getattr(fill.order, "canonical_order_id"))
                fill_id = f"ff_{content_hash({'order_id': order_id, 'broker_id': ack.order_id, 'qty': fill.executed_qty, 'price': fill.executed_price})}"
                mirrored.append((fill_id, order_id, fill))
        except Exception as exc:
            self._pause(f"broker outcome uncertain during open execution: {exc}")
            raise

        new_cash = account.cash + sum(fill.cash_delta for fill in fills)
        new_positions = dict(account.positions)
        for fill in fills:
            previous = new_positions.get(fill.symbol, 0.0)
            if fill.side is OrderSide.BUY:
                new_positions[fill.symbol] = previous + fill.executed_qty
            else:
                new_positions[fill.symbol] = max(previous - fill.executed_qty, 0.0)
        new_positions = {symbol: qty for symbol, qty in new_positions.items() if qty > 1e-6}
        equity_at_open = new_cash + sum(
            quantity * execution_open[symbol] for symbol, quantity in new_positions.items()
        )
        orders_payload = [
            {
                "order_id": getattr(order, "canonical_order_id"),
                "symbol": order.symbol,
                "side": order.side.value,
                "quantity": order.qty_shares,
                "filled_quantity": (
                    fill_by_order[id(order)].executed_qty if id(order) in fill_by_order else 0.0
                ),
            }
            for order in accepted
        ]
        result = {
            "schema_version": 1,
            "mode": "FORWARD_PAPER",
            "live_enabled": False,
            "phase": ForwardEventPhase.OPEN_EXECUTION.value,
            "session": event.session.isoformat(),
            "decision_id": decision.decision_id,
            "artifact_root_sha256": artifact["artifact_root_sha256"],
            "orders": orders_payload,
            "fills": [
                {
                    "fill_id": fill_id,
                    "symbol": fill.symbol,
                    "side": fill.side.value,
                    "quantity": fill.executed_qty,
                    "price": fill.executed_price,
                    "cash_delta": fill.cash_delta,
                    "cost": fill.cost_breakdown.total_cost_usd,
                }
                for fill_id, _, fill in mirrored
            ],
            "cash": new_cash,
            "positions": new_positions,
            "equity_at_open": equity_at_open,
            "fencing_token": token.fencing_token,
            "reused": False,
        }
        outcomes = [
            (
                str(getattr(order, "canonical_order_id")),
                None if id(order) not in fill_by_order else fill_by_order[id(order)].executed_qty,
            )
            for order in accepted
        ]

        def persist(conn) -> None:
            commit_time = self.clock.now().astimezone(UTC)
            self.state.persist_execution(
                conn,
                event_id=event.event_id,
                event_sha256=event_sha,
                decision=decision,
                cash=new_cash,
                positions=new_positions,
                equity_at_open=equity_at_open,
                fills=mirrored,
                result=result,
                token=token,
                lease_manager=self.lease_manager,
                now=commit_time,
            )

        self.order_service.commit_simulated_execution(outcomes, persist=persist)
        return result

    def process_eod(self, event: MarketEvent, token: LeaseToken) -> dict[str, Any]:
        if event.phase is not ForwardEventPhase.EOD_FINALIZE:
            raise ForwardRuntimeError("expected EOD_FINALIZE event")
        artifact = self._verify_artifact()
        event_sha = content_hash(event.payload())
        existing = self.state.event_result(event.event_id, event_sha)
        if existing is not None:
            report_path = self.report_dir / f"{event.session.isoformat()}.json"
            if not report_path.exists():
                self._atomic_report(report_path, existing)
            return {**existing, "reused": True}
        self._validate_event(event, ForwardEventPhase.EOD_FINALIZE)
        self._assert_writer_lease(token)
        decision = self.state.decision_for_execution(event.session.isoformat())
        if decision is None or decision.state != "EXECUTED":
            raise ForwardRuntimeError("no EXECUTED decision is ready for EOD")
        if decision.artifact_root_sha256 != artifact["artifact_root_sha256"]:
            self._pause("frozen decision artifact differs at EOD")
            raise ForwardRuntimeError("decision artifact drift")
        eod_close = self._row(self.close, event.session, "EOD close")
        account = self.state.account()
        equity = account.cash + sum(
            quantity * eod_close[symbol] for symbol, quantity in account.positions.items()
        )
        daily_pnl = equity - float(decision.payload["account_equity_at_decision"])
        now = self.clock.now().astimezone(UTC)
        reconcile = self._reconcile(now)
        reconcile_payload = {
            "passed": reconcile.passed,
            "cash_difference": reconcile.cash_difference,
            "position_differences": reconcile.position_differences,
            "missing_open_orders": sorted(reconcile.missing_open_orders),
            "unexpected_open_orders": sorted(reconcile.unexpected_open_orders),
        }
        result = {
            "schema_version": 1,
            "mode": "FORWARD_PAPER",
            "live_enabled": False,
            "phase": ForwardEventPhase.EOD_FINALIZE.value,
            "session": event.session.isoformat(),
            "decision_id": decision.decision_id,
            "artifact_root_sha256": artifact["artifact_root_sha256"],
            "cash": account.cash,
            "positions": account.positions,
            "equity": equity,
            "daily_pnl": daily_pnl,
            "reconciliation": reconcile_payload,
            "fencing_token": token.fencing_token,
            "reused": False,
        }
        reused = self.state.finalize(
            event_id=event.event_id,
            event_sha256=event_sha,
            decision=decision,
            equity=equity,
            daily_pnl=daily_pnl,
            reconciliation=reconcile_payload,
            result=result,
            token=token,
            lease_manager=self.lease_manager,
            now=now,
        )
        report_path = self.report_dir / f"{event.session.isoformat()}.json"
        self._atomic_report(report_path, result)
        return {**result, "reused": reused}

    @staticmethod
    def _atomic_report(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
