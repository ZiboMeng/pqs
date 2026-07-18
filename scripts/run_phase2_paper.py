#!/usr/bin/env python3
"""Run the phase-two strategy registry through causal local PAPER replay."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config.loader import load_config
from core.data.market_data_store import MarketDataStore
from core.data.price_access import load_adjusted_panel
from core.data.vix_loader import load_vix_series
from core.execution.broker_adapter import SimulatedBrokerAdapter
from core.execution.cost_model import CostModel
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.phase2_runtime import (
    Phase2PaperRuntime,
    load_paper_strategy_spec,
)
from core.paper_trading.pnl_tracker import PnLTracker
from core.portfolio.strategy_allocator import (
    AggregateExposurePolicy,
    PortfolioAllocator,
    StrategyRiskBudget,
)
from core.regime.phase2_regime import Phase2RegimeAdapter, RegimeAdapterConfig
from core.regime.regime_detector import RegimeDetector
from core.risk.kill_switch import KillSwitch, KillSwitchConfig
from core.signals.strategies.phase2_etf import (
    DualIndexGrowthParams,
    DualIndexGrowthStrategy,
)
from core.trading.controls import TradingControlStore
from core.trading.order import OrderState
from core.trading.risk import PreTradeRiskEngine, RiskLimits
from core.trading.service import OrderRegistrationService
from core.trading.store import OrderStore
from scripts.run_strategy_phase2 import _validate_data_manifest


def _yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return payload


def _runtime(args: argparse.Namespace) -> tuple[Phase2PaperRuntime, OrderStore]:
    _validate_data_manifest("d2")
    cfg = load_config(ROOT / "config")
    spec = load_paper_strategy_spec(
        ROOT / "config/strategies.paper.yaml",
        ROOT / "config/portfolio.paper.yaml",
        ROOT / "research/registry/strategy_registry.json",
        strategy_id=args.strategy_id,
    )
    if spec.strategy_id != "dual_index_growth_v1":
        raise ValueError(f"unsupported phase-two PAPER strategy: {spec.strategy_id}")

    panel = load_adjusted_panel(
        list(spec.asset_universe),
        ROOT / cfg.system.paths.data_dir,
        "1d",
        adjusted_total_return=True,
        fallback="local",
        require_total_return_coverage=True,
    )
    close = panel["close"]
    open_prices = panel["open"]
    store = MarketDataStore(ROOT / cfg.system.paths.data_dir)
    regime_cfg = _yaml(ROOT / "config/regime.paper.yaml")
    vix = load_vix_series(
        store,
        close.index,
        mode=str(regime_cfg["vix_mode"]),
    )
    adapter = Phase2RegimeAdapter(
        RegimeAdapterConfig(**regime_cfg["adapter"])
    )

    portfolio_cfg = _yaml(ROOT / "config/portfolio.paper.yaml")
    limits = portfolio_cfg["aggregate_limits"]
    allocator = PortfolioAllocator(
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
            symbol_caps={
                str(symbol): float(cap)
                for symbol, cap in limits["symbol_caps"].items()
            },
        ),
    )

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = state_dir / "paper_ledger.db"
    broker_path = state_dir / "simulated_broker.db"
    order_store = OrderStore(ledger_path)
    risk_limits = RiskLimits(
        max_gross_exposure=cfg.risk.max_gross_exposure,
        max_single_position=cfg.risk.position_limits.max_single_position,
        max_positions=cfg.risk.position_limits.max_positions,
        min_cash_fraction=float(limits["minimum_cash_fraction"]),
        max_daily_loss_fraction=cfg.risk.session_limits.max_daily_loss_fraction,
        max_daily_turnover_fraction=cfg.risk.session_limits.max_daily_turnover_fraction,
        max_order_notional_fraction=cfg.risk.position_limits.max_order_notional_fraction,
        max_reference_price_deviation=cfg.risk.position_limits.max_reference_price_deviation,
        symbol_caps={
            str(symbol): float(cap)
            for symbol, cap in limits["symbol_caps"].items()
        },
        blocked_symbols=frozenset(cfg.universe.blacklist),
        long_only=True,
        allow_margin=False,
    )
    order_service = OrderRegistrationService(
        order_store,
        PreTradeRiskEngine(risk_limits),
    )
    recovered = order_service.quarantine_after_restart(
        retry_validated_local_orders=True,
    )
    unresolved = [order for order in recovered if order.state is OrderState.UNKNOWN]
    control_store = TradingControlStore(ledger_path)
    cost_model = CostModel(cfg.cost_model)
    initial_capital = float(portfolio_cfg["initial_capital_usd"])
    broker = SimulatedBrokerAdapter(
        cost_model,
        initial_cash=initial_capital,
        state_db_path=broker_path,
    )
    kill_switch = KillSwitch(
        KillSwitchConfig(
            max_drawdown=-cfg.risk.drawdown_limits.halt_pct,
            degrade_dd_ratio=0.70,
            suspend_dd_ratio=1.00,
        )
    )

    def paused(symbol: str) -> bool:
        return control_store.is_paused(
            strategy_id=spec.strategy_id,
            symbol=symbol,
        )

    engine = PaperTradingEngine(
        cost_model=cost_model,
        pnl_tracker=PnLTracker(initial_capital),
        db_path=ledger_path,
        initial_capital=initial_capital,
        eod_force_close=False,
        confluence_enabled=False,
        kill_switch=kill_switch,
        replay_mode=True,
        integer_shares=not cfg.risk.position_limits.allow_fractional_shares,
        broker_adapter=broker,
        order_service=order_service,
        market_data_fresh=True,
        reconciliation_ok=not unresolved,
        manual_pause_check=paused,
    )
    runtime = Phase2PaperRuntime(
        spec=spec,
        strategy=DualIndexGrowthStrategy(DualIndexGrowthParams(**spec.parameters)),
        close=close,
        open_prices=open_prices,
        vix=vix,
        regime_detector=RegimeDetector(cfg.regime),
        regime_adapter=adapter,
        allocator=allocator,
        engine=engine,
        broker=broker,
        order_store=order_store,
        control_store=control_store,
        report_dir=state_dir / "daily_reports",
    )
    return runtime, order_store


def _summary(
    runtime: Phase2PaperRuntime,
    order_store: OrderStore,
    *,
    report_count: int,
    reused_count: int,
) -> dict[str, Any]:
    history = runtime.engine.load_history()
    canonical_history = history.to_json(date_format="iso", date_unit="ns", double_precision=15)
    orders = order_store.list_all()
    return {
        "schema_version": 1,
        "strategy_id": runtime.spec.strategy_id,
        "status_at_run": runtime.spec.status,
        "mode": "PAPER_REPLAY",
        "live_enabled": False,
        "sessions": len(history),
        "reports_returned": report_count,
        "reports_reused": reused_count,
        "nav_sha256": hashlib.sha256(canonical_history.encode("utf-8")).hexdigest(),
        "latest_equity": runtime.engine.get_equity(),
        "positions": runtime.engine.get_positions(),
        "cash": runtime.engine.get_cash(),
        "orders": len(orders),
        "order_states": {
            state.value: sum(order.state is state for order in orders)
            for state in OrderState
        },
        "broker_reconciled": runtime._startup_reconcile(),
        "global_pause": runtime.control_store.is_paused(
            strategy_id=runtime.spec.strategy_id,
            symbol="*",
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("replay", "status"))
    parser.add_argument("--strategy-id", default="dual_index_growth_v1")
    parser.add_argument("--from-date", default="2023-01-03")
    parser.add_argument("--to-date", default="2023-12-29")
    parser.add_argument(
        "--state-dir",
        default="data/paper_trading/phase2_dual_index_growth_v1",
    )
    parser.add_argument("--summary-out")
    args = parser.parse_args()
    runtime, order_store = _runtime(args)
    reports = []
    if args.mode == "replay":
        reports = runtime.run_range(args.from_date, args.to_date)
    summary = _summary(
        runtime,
        order_store,
        report_count=len(reports),
        reused_count=sum(report.reused for report in reports),
    )
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    print(rendered)
    if args.summary_out:
        output = Path(args.summary_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
