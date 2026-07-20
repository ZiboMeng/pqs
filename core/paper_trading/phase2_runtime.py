"""Causal, fail-closed PAPER runtime for phase-two approved strategies."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd
import yaml

from core.execution.broker_adapter import BrokerAdapter
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.portfolio.strategy_allocator import PortfolioAllocator
from core.regime.phase2_regime import Phase2RegimeAdapter, fail_closed_regime_scale
from core.regime.regime_detector import RegimeDetector
from core.trading.controls import ControlScope, TradingControlStore
from core.trading.order import OrderState
from core.trading.reconciliation import (
    AccountSnapshot,
    ReconciliationResult,
    ReconciliationService,
)
from core.trading.store import OrderStore


class PaperRuntimeError(RuntimeError):
    """Base class for fail-closed PAPER runtime errors."""


class MarketDataQualityError(PaperRuntimeError):
    """Raised before strategy evaluation when a market event is unsafe."""


class StrategyProtocol(Protocol):
    required_symbols: tuple[str, ...]

    def generate(
        self,
        price_df: pd.DataFrame,
        regime_series: pd.Series | None = None,
    ) -> pd.DataFrame: ...


@dataclass(frozen=True)
class PaperStrategySpec:
    strategy_id: str
    version: str
    status: str
    strategy_type: str
    asset_universe: tuple[str, ...]
    parameters: Mapping[str, Any]
    allowed_regimes: frozenset[str]
    minimum_regime_confidence: float
    regime_integration_mode: str
    capital_fraction: float
    max_gross_exposure: float
    max_turnover: float
    priority: int


@dataclass(frozen=True)
class SessionReport:
    payload: Mapping[str, Any]
    path: Path
    reused: bool = False


class MarketEventGuard:
    """Reject missing, stale, duplicate and out-of-order daily events."""

    def __init__(
        self,
        required_symbols: tuple[str, ...],
        sessions: pd.DatetimeIndex,
        *,
        last_completed: pd.Timestamp | None = None,
    ) -> None:
        if sessions.has_duplicates or not sessions.is_monotonic_increasing:
            raise MarketDataQualityError("market sessions are duplicate or out of order")
        self.required_symbols = required_symbols
        self.sessions = sessions
        self.last_completed = last_completed
        self._seen_event_ids: set[str] = set()

    def validate(
        self,
        *,
        event_id: str,
        signal_date: pd.Timestamp,
        exec_date: pd.Timestamp,
        data_as_of: pd.Timestamp,
        prev_close: Mapping[str, float],
        exec_open: Mapping[str, float],
        eod_close: Mapping[str, float],
        vix: float,
    ) -> None:
        if event_id in self._seen_event_ids:
            raise MarketDataQualityError(f"duplicate market event: {event_id}")
        if self.last_completed is not None and exec_date <= self.last_completed:
            raise MarketDataQualityError(
                f"out-of-order market event: {exec_date.date()} <= {self.last_completed.date()}"
            )
        if data_as_of.normalize() < exec_date.normalize():
            raise MarketDataQualityError(
                f"stale market event: as_of={data_as_of} exec_date={exec_date.date()}"
            )
        try:
            signal_position = self.sessions.get_loc(signal_date)
            exec_position = self.sessions.get_loc(exec_date)
        except KeyError as exc:
            raise MarketDataQualityError(f"non-session market event: {exc}") from exc
        if not isinstance(signal_position, int) or not isinstance(exec_position, int):
            raise MarketDataQualityError("ambiguous session lookup")
        if exec_position != signal_position + 1:
            raise MarketDataQualityError("execution is not the next tradable session")
        for label, values in (
            ("prev_close", prev_close),
            ("exec_open", exec_open),
            ("eod_close", eod_close),
        ):
            missing = sorted(set(self.required_symbols) - set(values))
            if missing:
                raise MarketDataQualityError(f"{label} missing symbols: {missing}")
            invalid = [
                symbol
                for symbol in self.required_symbols
                if not math.isfinite(float(values[symbol])) or float(values[symbol]) <= 0.0
            ]
            if invalid:
                raise MarketDataQualityError(f"{label} has invalid prices: {invalid}")
        if not math.isfinite(float(vix)) or float(vix) <= 0.0:
            raise MarketDataQualityError("VIX is missing or invalid")

    def complete(self, event_id: str, exec_date: pd.Timestamp) -> None:
        self._seen_event_ids.add(event_id)
        self.last_completed = exec_date


def load_paper_strategy_spec(
    strategy_config_path: str | Path,
    portfolio_config_path: str | Path,
    registry_path: str | Path,
    *,
    strategy_id: str,
) -> PaperStrategySpec:
    strategy_config = _load_yaml(strategy_config_path)
    portfolio_config = _load_yaml(portfolio_config_path)
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    for payload in (strategy_config, portfolio_config):
        if payload.get("schema_version") != 1 or payload.get("mode") != "PAPER":
            raise PaperRuntimeError("invalid PAPER configuration schema or mode")
        if payload.get("live_enabled") is not False:
            raise PaperRuntimeError("LIVE must remain disabled in every PAPER config")
    configured = {
        item["strategy_id"]: item
        for item in strategy_config.get("strategies", [])
        if item.get("enabled")
    }
    registered = {
        item["strategy_id"]: item for item in registry.get("strategies", [])
    }
    if strategy_id not in configured or strategy_id not in registered:
        raise PaperRuntimeError(f"strategy is not enabled and registered: {strategy_id}")
    config_item = configured[strategy_id]
    registry_item = registered[strategy_id]
    if registry_item.get("status") != "PAPER_APPROVED":
        raise PaperRuntimeError(f"strategy status is not PAPER-approved: {strategy_id}")
    if registry_item.get("live_enabled") is not False:
        raise PaperRuntimeError("registered strategy unexpectedly enables LIVE")
    required_registry_fields = {
        "asset_universe",
        "schedule",
        "required_data",
        "risk_budget",
        "max_position",
        "max_turnover",
        "kill_switch",
        "invalidating_conditions",
        "promotion_evidence",
    }
    missing_fields = sorted(required_registry_fields - set(registry_item))
    if missing_fields:
        raise PaperRuntimeError(f"strategy registry missing fields: {missing_fields}")
    budget = portfolio_config.get("strategy_budgets", {}).get(strategy_id)
    if not isinstance(budget, dict):
        raise PaperRuntimeError(f"portfolio budget missing for {strategy_id}")
    return PaperStrategySpec(
        strategy_id=strategy_id,
        version=str(registry_item["version"]),
        status=str(registry_item["status"]),
        strategy_type=str(registry_item["strategy_type"]),
        asset_universe=tuple(str(symbol) for symbol in registry_item["asset_universe"]),
        parameters=dict(config_item["parameters"]),
        allowed_regimes=frozenset(str(item) for item in config_item["allowed_regimes"]),
        minimum_regime_confidence=float(config_item["minimum_regime_confidence"]),
        regime_integration_mode=str(config_item["regime_integration_mode"]),
        capital_fraction=float(budget["capital_fraction"]),
        max_gross_exposure=float(budget["max_gross_exposure"]),
        max_turnover=float(budget["max_turnover"]),
        priority=int(budget["priority"]),
    )


class Phase2PaperRuntime:
    """Run one strategy through the complete daily PAPER control path."""

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
        engine: PaperTradingEngine,
        broker: BrokerAdapter,
        order_store: OrderStore,
        control_store: TradingControlStore,
        report_dir: str | Path,
    ) -> None:
        self.spec = spec
        self.strategy = strategy
        self.close = close.sort_index()
        self.open_prices = open_prices.reindex(self.close.index)
        self.vix = vix.reindex(self.close.index).ffill()
        self.regime_detector = regime_detector
        self.regime_adapter = regime_adapter
        self.allocator = allocator
        self.engine = engine
        self.broker = broker
        self.order_store = order_store
        self.control_store = control_store
        self.reconciliation = ReconciliationService(control_store)
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._validate_panel()
        history = self.engine.load_history()
        last_completed = None if history.empty else pd.Timestamp(history.index.max())
        self._processed = set(pd.DatetimeIndex(history.index))
        self.guard = MarketEventGuard(
            tuple(self.spec.asset_universe),
            self.close.index,
            last_completed=last_completed,
        )
        self._reconciliation_ok = self._startup_reconcile()

    def run_range(self, start: str | pd.Timestamp, end: str | pd.Timestamp) -> list[SessionReport]:
        selected = self.close.index[
            (self.close.index >= pd.Timestamp(start))
            & (self.close.index <= pd.Timestamp(end))
        ]
        reports: list[SessionReport] = []
        for exec_date in selected:
            location = self.close.index.get_loc(exec_date)
            if not isinstance(location, int) or location == 0:
                continue
            reports.append(
                self.run_session(
                    signal_date=self.close.index[location - 1],
                    exec_date=exec_date,
                    data_as_of=exec_date,
                )
            )
        return reports

    def run_session(
        self,
        *,
        signal_date: pd.Timestamp,
        exec_date: pd.Timestamp,
        data_as_of: pd.Timestamp,
    ) -> SessionReport:
        signal_date = pd.Timestamp(signal_date)
        exec_date = pd.Timestamp(exec_date)
        event_id = f"{self.spec.strategy_id}:{exec_date.date().isoformat()}"
        report_path = self.report_dir / f"{exec_date.date().isoformat()}.json"
        if exec_date in self._processed:
            if not report_path.exists():
                payload = self._recover_committed_report(signal_date, exec_date)
                self._atomic_report(report_path, payload)
            return SessionReport(
                json.loads(report_path.read_text(encoding="utf-8")),
                report_path,
                reused=True,
            )

        symbols = list(self.spec.asset_universe)
        prev_close = self.close.loc[signal_date, symbols].to_dict()
        exec_open = self.open_prices.loc[exec_date, symbols].to_dict()
        eod_close = self.close.loc[exec_date, symbols].to_dict()
        signal_vix = float(self.vix.loc[signal_date])
        self.guard.validate(
            event_id=event_id,
            signal_date=signal_date,
            exec_date=exec_date,
            data_as_of=pd.Timestamp(data_as_of),
            prev_close=prev_close,
            exec_open=exec_open,
            eod_close=eod_close,
            vix=signal_vix,
        )

        history = self.close.loc[:signal_date, symbols]
        legacy = self.regime_detector.classify_series(
            history["SPY"],
            self.vix.loc[:signal_date],
        )
        regime = self.regime_adapter.classify(legacy, history["SPY"])
        regime_label = str(regime.state.loc[signal_date])
        regime_confidence = float(regime.confidence.loc[signal_date])
        raw_target = self.strategy.generate(history).loc[signal_date].astype(float)
        enabled = (
            regime_label in self.spec.allowed_regimes
            and regime_confidence >= self.spec.minimum_regime_confidence
        )
        requested_target = raw_target if enabled else raw_target * 0.0

        equity_curve = self.engine.get_equity_curve()
        kill_result = self.engine.kill_switch.evaluate(
            equity_curve,
            vix=signal_vix,
            weights=requested_target.to_dict(),
        )
        manually_paused = self.control_store.is_paused(
            strategy_id=self.spec.strategy_id,
            symbol="*",
        )
        allocation = self.allocator.allocate(
            {self.spec.strategy_id: requested_target},
            regime_label=regime_label,
            regime_confidence=regime_confidence,
            data_fresh=True,
            reconciled=self._reconciliation_ok,
            global_kill_switch=(kill_result.state == "SUSPENDED" or manually_paused),
        )
        approved = allocation.weights if allocation.accepted else allocation.weights * 0.0
        if self.spec.regime_integration_mode == "exposure_scaled":
            regime_cap = float(
                fail_closed_regime_scale(
                    pd.Series([regime_label], index=[signal_date]),
                    pd.Series([regime_confidence], index=[signal_date]),
                    self.spec.minimum_regime_confidence,
                ).iloc[0]
            )
        elif self.spec.regime_integration_mode == "quality_fail_closed":
            regime_cap = 1.0 if enabled else 0.0
        else:
            raise PaperRuntimeError(
                f"unknown regime integration mode: {self.spec.regime_integration_mode}"
            )
        approved_gross = float(approved.sum())
        if approved_gross > regime_cap and approved_gross > 0.0:
            approved = approved * (regime_cap / approved_gross)
        approved *= float(kill_result.position_multiplier)

        self.engine.set_operational_readiness(
            market_data_fresh=True,
            reconciliation_ok=self._reconciliation_ok,
        )
        day_result = self.engine.run_day_daily(
            exec_date=exec_date,
            signal_date=signal_date,
            target_wts=approved.to_dict(),
            prev_close=prev_close,
            exec_open=exec_open,
            eod_close=eod_close,
            vix=signal_vix,
        )
        self._processed.add(exec_date)
        reconcile_result = self._authoritative_reconcile()
        self._reconciliation_ok = reconcile_result.passed
        eod_check = self.engine.reconcile(exec_date, day_result)
        payload = self._daily_report(
            signal_date=signal_date,
            exec_date=exec_date,
            regime_label=regime_label,
            regime_confidence=regime_confidence,
            enabled=enabled,
            raw_target=raw_target,
            approved=approved,
            allocation=allocation,
            kill_result=kill_result,
            day_result=day_result,
            reconcile_result=reconcile_result,
            eod_check=eod_check,
        )
        self._atomic_report(report_path, payload)
        self.guard.complete(event_id, exec_date)
        return SessionReport(payload, report_path)

    def _authoritative_reconcile(self) -> ReconciliationResult:
        expected_orders = frozenset(
            order.broker_order_id or order.intent.order_id
            for order in self.order_store.list_nonterminal()
            if order.state not in {OrderState.CREATED, OrderState.VALIDATED}
        )
        now = datetime.now(UTC)
        expected = AccountSnapshot(
            cash=self.engine.get_cash(),
            positions=self.engine.get_positions(),
            open_order_ids=expected_orders,
            observed_at=now,
            source="paper_ledger",
        )
        try:
            actual = AccountSnapshot(
                cash=self.broker.get_cash(),
                positions=self.broker.get_positions(),
                open_order_ids=self.broker.get_open_order_ids(),
                observed_at=now,
                source="simulated_broker",
            )
            return self.reconciliation.reconcile(expected, actual)
        except Exception as exc:
            self.control_store.set_paused(
                ControlScope.GLOBAL,
                "*",
                paused=True,
                reason=f"broker reconciliation unavailable: {type(exc).__name__}: {exc}",
                updated_by="system:phase2-paper-runtime",
            )
            return ReconciliationResult(False, 0.0, {}, frozenset(), frozenset())

    def _startup_reconcile(self) -> bool:
        return self._authoritative_reconcile().passed

    def _daily_report(self, **items: Any) -> dict[str, Any]:
        allocation = items["allocation"]
        kill_result = items["kill_result"]
        day_result = items["day_result"]
        reconcile_result = items["reconcile_result"]
        eod_check = items["eod_check"]
        enabled = bool(items["enabled"])
        session_orders = self._session_order_audit(items["exec_date"])
        pretrade_rejections = sorted(
            {
                reason
                for order in session_orders
                if order["state"] == OrderState.REJECTED.value
                for reason in order["reason_codes"]
            }
        )
        manual_review: list[str] = []
        if not reconcile_result.passed:
            manual_review.append("BROKER_RECONCILIATION_FAILED")
        if not allocation.accepted:
            manual_review.extend(allocation.veto_reasons)
        if not enabled:
            manual_review.append("REGIME_NOT_ALLOWED_OR_LOW_CONFIDENCE")
        if pretrade_rejections:
            manual_review.append("PRETRADE_RISK_REJECTION")
        if not eod_check["ok"]:
            manual_review.append("EOD_ACCOUNTING_WARNING")
        return {
            "schema_version": 1,
            "strategy_id": self.spec.strategy_id,
            "status_at_run": self.spec.status,
            "mode": "PAPER_REPLAY",
            "live_enabled": False,
            "signal_date": items["signal_date"].date().isoformat(),
            "execution_date": items["exec_date"].date().isoformat(),
            "regime": items["regime_label"],
            "regime_confidence": items["regime_confidence"],
            "enabled_strategies": [self.spec.strategy_id] if enabled else [],
            "disabled_strategies": [] if enabled else [self.spec.strategy_id],
            "signals": _series_dict(items["raw_target"]),
            "approved_target": _series_dict(items["approved"]),
            "rejected_signals": [
                *allocation.veto_reasons,
                *(() if enabled else ("REGIME_NOT_ALLOWED_OR_LOW_CONFIDENCE",)),
                *pretrade_rejections,
            ],
            "risk_budget": {
                "capital_fraction": self.spec.capital_fraction,
                "max_gross_exposure": self.spec.max_gross_exposure,
                "max_turnover": self.spec.max_turnover,
                "requested_gross": allocation.requested_gross,
                "approved_gross": float(items["approved"].sum()),
            },
            "positions": self.engine.get_positions(),
            "cash": self.engine.get_cash(),
            "orders": session_orders,
            "fills": [
                {
                    "symbol": fill.symbol,
                    "side": fill.side.value,
                    "quantity": fill.executed_qty,
                    "price": fill.executed_price,
                    "cash_delta": fill.cash_delta,
                    "cost": fill.cost_breakdown.total_cost_usd,
                }
                for fill in day_result.trades
            ],
            "pnl": {
                "daily_net": day_result.net_pnl,
                "equity": self.engine.get_equity(),
                "drawdown": self.engine.get_pnl_summary()["running_drawdown"],
            },
            "data_quality": {
                "complete": True,
                "fresh": True,
                "ordered": True,
                "duplicate": False,
            },
            "reconciliation": {
                "passed": reconcile_result.passed,
                "cash_difference": reconcile_result.cash_difference,
                "position_differences": reconcile_result.position_differences,
                "missing_open_orders": sorted(reconcile_result.missing_open_orders),
                "unexpected_open_orders": sorted(
                    reconcile_result.unexpected_open_orders
                ),
                "eod_check_ok": eod_check["ok"],
                "eod_warnings": eod_check["warnings"],
            },
            "kill_switch": {
                "state": kill_result.state,
                "position_multiplier": kill_result.position_multiplier,
                "active_rules": kill_result.active_rules,
                "manual_pause": self.control_store.is_paused(
                    strategy_id=self.spec.strategy_id,
                    symbol="*",
                ),
            },
            "manual_review": sorted(set(manual_review)),
        }

    def _session_order_audit(self, exec_date: pd.Timestamp) -> list[dict[str, Any]]:
        prefix = f"daily-{exec_date.date().isoformat()}:"
        output: list[dict[str, Any]] = []
        for order in self.order_store.list_all():
            if not order.intent.decision_id.startswith(prefix):
                continue
            reason_codes: list[str] = []
            for event in self.order_store.events(order.intent.order_id):
                values = event["metadata"].get("reason_codes", [])
                reason_codes.extend(str(value) for value in values)
            output.append(
                {
                    "order_id": order.intent.order_id,
                    "symbol": order.intent.symbol,
                    "side": order.intent.side.value,
                    "quantity": order.intent.quantity,
                    "state": order.state.value,
                    "filled_quantity": order.filled_quantity,
                    "reason_codes": sorted(set(reason_codes)),
                }
            )
        return output

    def _recover_committed_report(
        self,
        signal_date: pd.Timestamp,
        exec_date: pd.Timestamp,
    ) -> dict[str, Any]:
        history = self.engine.load_history()
        row = history.loc[exec_date]
        return {
            "schema_version": 1,
            "strategy_id": self.spec.strategy_id,
            "status_at_run": self.spec.status,
            "mode": "PAPER_REPLAY",
            "live_enabled": False,
            "signal_date": signal_date.date().isoformat(),
            "execution_date": exec_date.date().isoformat(),
            "recovery_status": "COMMITTED_LEDGER_SESSION_REPORT_REBUILT",
            "positions": self.engine.get_positions(),
            "cash": self.engine.get_cash(),
            "pnl": {
                "daily_net": float(row["net_pnl"]),
                "equity": float(row["equity"]),
            },
            "orders": [],
            "fills": [],
            "reconciliation": {"passed": self._startup_reconcile()},
            "manual_review": ["REPORT_REBUILT_AFTER_POST_COMMIT_CRASH"],
        }

    def _validate_panel(self) -> None:
        if self.close.empty or self.open_prices.empty:
            raise MarketDataQualityError("PAPER panel is empty")
        if self.close.index.has_duplicates or not self.close.index.is_monotonic_increasing:
            raise MarketDataQualityError("close panel is duplicate or out of order")
        if not self.open_prices.index.equals(self.close.index):
            raise MarketDataQualityError("open and close session indexes differ")
        missing = sorted(set(self.spec.asset_universe) - set(self.close.columns))
        if missing:
            raise MarketDataQualityError(f"PAPER panel missing symbols: {missing}")

    @staticmethod
    def _atomic_report(path: Path, payload: Mapping[str, Any]) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _load_yaml(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PaperRuntimeError(f"configuration must be a mapping: {path}")
    return payload


def _series_dict(values: pd.Series) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in values.items()
        if math.isfinite(float(value)) and abs(float(value)) > 1e-12
    }


__all__ = [
    "MarketDataQualityError",
    "MarketEventGuard",
    "PaperRuntimeError",
    "PaperStrategySpec",
    "Phase2PaperRuntime",
    "SessionReport",
    "load_paper_strategy_spec",
]
