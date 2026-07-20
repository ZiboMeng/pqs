#!/usr/bin/env python3
"""Operate the Phase 3 three-stage Forward PAPER runtime."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config.loader import load_config  # noqa: E402
from core.data.market_data_store import MarketDataStore  # noqa: E402
from core.data.price_access import load_adjusted_panel  # noqa: E402
from core.data.vix_loader import load_vix_series  # noqa: E402
from core.execution.broker_adapter import SimulatedBrokerAdapter  # noqa: E402
from core.execution.cost_model import CostModel  # noqa: E402
from core.execution.execution_simulator import ExecutionSimulator  # noqa: E402
from core.execution.target_weight_planner import (  # noqa: E402
    TargetWeightOrderPlanner,
    TargetWeightPlannerConfig,
)
from core.paper_trading.forward_runtime import (  # noqa: E402
    ExchangeSessionCalendar,
    ForwardEventPhase,
    ForwardPaperRuntime,
    ForwardRuntimePolicy,
    MarketEvent,
    SystemClock,
)
from core.paper_trading.forward_state import ForwardStateStore  # noqa: E402
from core.paper_trading.phase2_runtime import (  # noqa: E402
    StrategyProtocol,
    load_paper_strategy_spec,
)
from core.portfolio.strategy_allocator import (  # noqa: E402
    AggregateExposurePolicy,
    PortfolioAllocator,
    StrategyRiskBudget,
)
from core.regime.phase2_regime import (  # noqa: E402
    Phase2RegimeAdapter,
    RegimeAdapterConfig,
)
from core.regime.regime_detector import RegimeDetector  # noqa: E402
from core.risk.kill_switch import KillSwitch, KillSwitchConfig  # noqa: E402
from core.runtime.lease import SQLiteLeaseManager  # noqa: E402
from core.runtime.strategy_artifact import verify_strategy_artifact  # noqa: E402
from core.signals.strategies.phase2_etf import (  # noqa: E402
    DualIndexGrowthParams,
    DualIndexGrowthStrategy,
)
from core.trading.controls import TradingControlStore  # noqa: E402
from core.trading.risk import PreTradeRiskEngine, RiskLimits  # noqa: E402
from core.trading.service import OrderRegistrationService  # noqa: E402
from core.trading.store import OrderStore  # noqa: E402
from scripts.run_strategy_phase2 import _validate_data_manifest  # noqa: E402


def _yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return payload


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("event metadata times must include a UTC offset")
    return parsed.astimezone(UTC)


def _build_runtime(args: argparse.Namespace):
    phase3 = _yaml(ROOT / "config/forward_paper.yaml")
    if phase3.get("schema_version") != 1:
        raise ValueError("unsupported Forward PAPER configuration schema")
    if phase3.get("mode") != "PAPER" or phase3.get("live_enabled") is not False:
        raise ValueError("Forward PAPER config violates runtime-mode boundary")
    if (
        phase3.get("broker_write_enabled") is not False
        or phase3.get("paid_cloud_create_enabled") is not False
        or phase3.get("broker", {}).get("external_write_enabled") is not False
        or phase3.get("broker", {}).get("adapter") != "simulated"
    ):
        raise ValueError("external broker writes and paid cloud creates are forbidden")
    _validate_data_manifest("d2")
    config = load_config(ROOT / "config")
    artifact_path = ROOT / phase3["strategy"]["artifact"]
    spec = load_paper_strategy_spec(
        ROOT / "config/strategies.paper.yaml",
        ROOT / "config/portfolio.paper.yaml",
        ROOT / "research/registry/strategy_registry.json",
        strategy_id=phase3["strategy"]["strategy_id"],
        artifact_path=artifact_path,
        repo_root=ROOT,
        verify_artifact_environment=True,
    )
    panel = load_adjusted_panel(
        list(spec.asset_universe),
        ROOT / config.system.paths.data_dir,
        "1d",
        adjusted_total_return=True,
        fallback="local",
        require_total_return_coverage=True,
    )
    close = panel["close"]
    open_prices = panel["open"]
    vix = load_vix_series(
        MarketDataStore(ROOT / config.system.paths.data_dir),
        close.index,
        mode="strict",
    )

    state_root = Path(args.state_dir or phase3["state"]["directory"])
    if not state_root.is_absolute():
        state_root = ROOT / state_root
    state_root.mkdir(parents=True, exist_ok=True)
    database = state_root / phase3["state"]["database"]
    broker_database = state_root / phase3["state"]["broker_database"]
    report_dir = state_root / phase3["state"]["reports_directory"]
    portfolio = _yaml(ROOT / "config/portfolio.paper.yaml")
    initial_capital = float(portfolio["initial_capital_usd"])
    order_store = OrderStore(database)
    controls = TradingControlStore(database)
    state = ForwardStateStore(database, initial_capital=initial_capital)
    lease = SQLiteLeaseManager(database)
    limits = portfolio["aggregate_limits"]
    order_service = OrderRegistrationService(
        order_store,
        PreTradeRiskEngine(
            RiskLimits(
                max_gross_exposure=config.risk.max_gross_exposure,
                max_single_position=config.risk.position_limits.max_single_position,
                max_positions=config.risk.position_limits.max_positions,
                min_cash_fraction=float(limits["minimum_cash_fraction"]),
                max_daily_loss_fraction=config.risk.session_limits.max_daily_loss_fraction,
                max_daily_turnover_fraction=(
                    config.risk.session_limits.max_daily_turnover_fraction
                ),
                max_order_notional_fraction=(
                    config.risk.position_limits.max_order_notional_fraction
                ),
                max_reference_price_deviation=(
                    config.risk.position_limits.max_reference_price_deviation
                ),
                symbol_caps={str(k): float(v) for k, v in limits["symbol_caps"].items()},
                blocked_symbols=frozenset(config.universe.blacklist),
                long_only=True,
                allow_margin=False,
            )
        ),
    )
    order_service.quarantine_after_restart(retry_validated_local_orders=True)
    cost_model = CostModel(config.cost_model)
    broker = SimulatedBrokerAdapter(
        cost_model,
        initial_cash=initial_capital,
        state_db_path=broker_database,
    )
    regime_config = _yaml(ROOT / "config/regime.paper.yaml")
    calendar_config = phase3["calendar"]

    def verify_artifact():
        return verify_strategy_artifact(
            artifact_path,
            repo_root=ROOT,
            expected_strategy_id=spec.strategy_id,
            expected_strategy_version=spec.version,
            expected_promotion_status="PAPER_APPROVED",
            verify_environment=True,
        )

    runtime = ForwardPaperRuntime(
        spec=spec,
        strategy=cast(
            StrategyProtocol,
            DualIndexGrowthStrategy(DualIndexGrowthParams(**spec.parameters)),
        ),
        close=close,
        open_prices=open_prices,
        vix=vix,
        regime_detector=RegimeDetector(config.regime),
        regime_adapter=Phase2RegimeAdapter(
            RegimeAdapterConfig(**regime_config["adapter"])
        ),
        allocator=PortfolioAllocator(
            {
                spec.strategy_id: StrategyRiskBudget(
                    spec.strategy_id,
                    spec.capital_fraction,
                    max_gross_exposure=spec.max_gross_exposure,
                    max_turnover=spec.max_turnover,
                    priority=spec.priority,
                )
            },
            AggregateExposurePolicy(
                max_gross_exposure=float(limits["max_gross_exposure"]),
                max_single_position=float(limits["max_single_position"]),
                symbol_caps={str(k): float(v) for k, v in limits["symbol_caps"].items()},
            ),
        ),
        kill_switch=KillSwitch(
            KillSwitchConfig(
                max_drawdown=-config.risk.drawdown_limits.halt_pct,
                degrade_dd_ratio=0.70,
                suspend_dd_ratio=1.00,
            )
        ),
        cost_model=cost_model,
        execution_simulator=ExecutionSimulator(
            cost_model,
            freq="interday",
            allow_partial=True,
            integer_shares=bool(phase3["execution"]["integer_shares"]),
        ),
        order_planner=TargetWeightOrderPlanner(
            TargetWeightPlannerConfig(
                minimum_trade_usd=float(phase3["execution"]["minimum_trade_usd"]),
                rebalance_threshold=float(phase3["execution"]["rebalance_threshold"]),
                integer_shares=bool(phase3["execution"]["integer_shares"]),
            )
        ),
        broker=broker,
        order_store=order_store,
        order_service=order_service,
        control_store=controls,
        state_store=state,
        lease_manager=lease,
        artifact_verifier=verify_artifact,
        clock=SystemClock(),
        report_dir=report_dir,
        calendar=ExchangeSessionCalendar(calendar_config["exchange"]),
        policy=ForwardRuntimePolicy(
            close_buffer=timedelta(seconds=calendar_config["close_buffer_seconds"]),
            eod_buffer=timedelta(seconds=calendar_config["eod_buffer_seconds"]),
            max_event_lag=timedelta(seconds=calendar_config["max_event_lag_seconds"]),
            max_broker_snapshot_age=timedelta(
                seconds=calendar_config["max_broker_snapshot_age_seconds"]
            ),
            max_broker_clock_skew=timedelta(
                seconds=calendar_config["max_broker_clock_skew_seconds"]
            ),
        ),
    )
    return runtime, lease, phase3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "run-once"))
    parser.add_argument("--phase", choices=("close", "open", "eod"))
    parser.add_argument("--session")
    parser.add_argument("--event-id")
    parser.add_argument("--source-batch-sha256")
    parser.add_argument("--available-at")
    parser.add_argument("--received-at")
    parser.add_argument("--owner-id", default=f"{socket.gethostname()}:{os.getpid()}")
    parser.add_argument("--state-dir")
    args = parser.parse_args()
    token = None
    lease = None
    try:
        runtime, lease, config = _build_runtime(args)
        if args.command == "status":
            result = {
                "schema_version": 1,
                "mode": "FORWARD_PAPER",
                "live_enabled": False,
                "artifact_root_sha256": runtime.spec.artifact_root_sha256,
                "state": runtime.state.status(),
            }
        else:
            required = {
                "phase": args.phase,
                "session": args.session,
                "event_id": args.event_id,
                "source_batch_sha256": args.source_batch_sha256,
                "available_at": args.available_at,
                "received_at": args.received_at,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(f"run-once missing arguments: {missing}")
            phase = {
                "close": ForwardEventPhase.CLOSE_DECISION,
                "open": ForwardEventPhase.OPEN_EXECUTION,
                "eod": ForwardEventPhase.EOD_FINALIZE,
            }[args.phase]
            session = datetime.fromisoformat(args.session).date()
            market_open, market_close = runtime.calendar.boundaries(session)
            event_time = market_open if phase is ForwardEventPhase.OPEN_EXECUTION else market_close
            event = MarketEvent(
                event_id=args.event_id,
                phase=phase,
                session=session,
                event_time=event_time,
                available_time=_parse_time(args.available_at),
                received_time=_parse_time(args.received_at),
                source_batch_sha256=args.source_batch_sha256,
            )
            now = datetime.now(UTC)
            token = lease.acquire(
                config["scheduler"]["lease_name"],
                args.owner_id,
                now=now,
                ttl=timedelta(seconds=config["scheduler"]["lease_ttl_seconds"]),
            )
            if phase is ForwardEventPhase.CLOSE_DECISION:
                result = runtime.process_close(event, token)
            elif phase is ForwardEventPhase.OPEN_EXECUTION:
                result = runtime.process_open(event, token)
            else:
                result = runtime.process_eod(event, token)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    finally:
        if token is not None and lease is not None:
            lease.release(token, now=datetime.now(UTC))


if __name__ == "__main__":
    raise SystemExit(main())
