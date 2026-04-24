"""Round 12 (2026-04-20, off-menu): PaperTradingEngine ↔ BrokerAdapter
mirror integration.

PRD: CLAUDE.md §4.1 'Data Provider and Broker Adapter Separation' now
has a concrete integration seam. When a `SimulatedBrokerAdapter` (or any
future real adapter) is wired into `PaperTradingEngine`, every fill
booked by the engine is mirrored through `submit_order` and an EOD
`reconcile()` compares engine state to adapter state.

These tests verify:
  1. Legacy path (no adapter) unchanged — absence of the `broker_adapter`
     kwarg is a no-op.
  2. With adapter: fills reach the adapter; broker state tracks engine
     state (≈, using zero-cost config to avoid double-counting slippage).
  3. EOD reconcile runs and surfaces `ReconcileResult` via the public
     `get_broker_reconcile_results()`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.broker_adapter import (
    ReconcileResult,
    SimulatedBrokerAdapter,
)
from core.execution.cost_model import CostModel
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker


def _zero_cost_model() -> CostModel:
    """Cost model that produces zero slippage + zero commission.

    Using zero cost ensures engine executed_price == bar open price, so
    when we pin that price into `SimulatedBrokerAdapter.set_next_fill_price`
    the adapter's own simulate_fill produces identical output — no
    double-counting slippage."""
    cfg = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[],
                commission_bps=0.0,
                slippage_interday_bps=0.0,
                slippage_intraday_bps=0.0,
            )
        }
    )
    return CostModel(cfg)


def _make_engine(
    tmp_path: Path,
    cost_model: CostModel,
    broker=None,
    initial_capital: float = 100_000.0,
) -> PaperTradingEngine:
    return PaperTradingEngine(
        cost_model=cost_model,
        pnl_tracker=PnLTracker(initial_capital),
        db_path=tmp_path / "paper_trading.db",
        initial_capital=initial_capital,
        eod_force_close=False,
        confluence_enabled=False,
        broker_adapter=broker,
    )


class TestBackwardCompatNoAdapter:
    """Without broker_adapter kwarg, engine behaves exactly as before."""

    def test_legacy_run_day_daily_no_broker(self, tmp_path):
        engine = _make_engine(tmp_path, _zero_cost_model())
        assert engine._broker is None
        assert engine.get_broker_reconcile_results() == []

        engine.run_day_daily(
            date=pd.Timestamp("2024-01-02"),
            target_wts={"AAPL": 0.5},
            prices={"AAPL": 100.0},
            open_prices={"AAPL": 100.0},
        )
        # No reconcile result should have been generated.
        assert engine.get_broker_reconcile_results() == []

    def test_public_api_is_stable(self, tmp_path):
        engine = _make_engine(tmp_path, _zero_cost_model())
        # New helpers exist but work as no-ops without a broker.
        assert engine.get_broker_reconcile_results() == []
        engine._run_broker_reconcile(date=pd.Timestamp("2024-01-02"))
        assert engine.get_broker_reconcile_results() == []
        engine._mirror_fills_to_broker([])  # empty list, no-op
        assert engine.get_broker_reconcile_results() == []


class TestMirrorDailyPath:
    """run_day_daily forwards every fill to the adapter and reconciles
    at EOD."""

    def test_fills_mirrored_to_broker(self, tmp_path):
        cm = _zero_cost_model()
        broker = SimulatedBrokerAdapter(
            cost_model=cm, initial_cash=100_000.0,
        )
        # SimulatedBrokerAdapter requires a price oracle for the first
        # call — engine pins per-fill prices; default is fallback only.
        broker.set_default_fill_price(100.0)

        engine = _make_engine(tmp_path, cm, broker=broker)
        engine.run_day_daily(
            date=pd.Timestamp("2024-01-02"),
            target_wts={"AAPL": 0.5},
            prices={"AAPL": 100.0},
            open_prices={"AAPL": 100.0},
        )
        # Broker should have received at least one fill via submit_order.
        from datetime import datetime, timedelta
        fills = broker.get_fills(since=datetime.now() - timedelta(seconds=30))
        assert len(fills) >= 1
        assert any(f.order.symbol == "AAPL" for f in fills)

    def test_reconcile_recorded_at_eod(self, tmp_path):
        cm = _zero_cost_model()
        broker = SimulatedBrokerAdapter(
            cost_model=cm, initial_cash=100_000.0,
        )
        broker.set_default_fill_price(100.0)
        engine = _make_engine(tmp_path, cm, broker=broker)
        engine.run_day_daily(
            date=pd.Timestamp("2024-01-02"),
            target_wts={"AAPL": 0.5},
            prices={"AAPL": 100.0},
            open_prices={"AAPL": 100.0},
        )
        results = engine.get_broker_reconcile_results()
        assert len(results) == 1
        assert isinstance(results[0], ReconcileResult)

    def test_zero_cost_reconcile_passes(self, tmp_path):
        """Under zero-cost model + pinned prices, broker should track
        engine exactly → reconcile.passed is True."""
        cm = _zero_cost_model()
        broker = SimulatedBrokerAdapter(
            cost_model=cm, initial_cash=100_000.0,
        )
        broker.set_default_fill_price(100.0)
        engine = _make_engine(tmp_path, cm, broker=broker)
        engine.run_day_daily(
            date=pd.Timestamp("2024-01-02"),
            target_wts={"AAPL": 0.5},
            prices={"AAPL": 100.0},
            open_prices={"AAPL": 100.0},
        )
        r = engine.get_broker_reconcile_results()[0]
        assert r.passed is True, (
            f"expected clean reconcile under zero-cost model; "
            f"got details={r.details!r} pos={r.position_mismatches} "
            f"cash={r.cash_mismatch}"
        )
        assert r.position_mismatches == {}
        assert abs(r.cash_mismatch) < 1e-4

    def test_multi_day_accumulates_reconcile_results(self, tmp_path):
        cm = _zero_cost_model()
        broker = SimulatedBrokerAdapter(
            cost_model=cm, initial_cash=100_000.0,
        )
        broker.set_default_fill_price(100.0)
        engine = _make_engine(tmp_path, cm, broker=broker)
        for d in ("2024-01-02", "2024-01-03", "2024-01-04"):
            engine.run_day_daily(
                date=pd.Timestamp(d),
                target_wts={"AAPL": 0.5},
                prices={"AAPL": 100.0},
                open_prices={"AAPL": 100.0},
            )
        results = engine.get_broker_reconcile_results()
        assert len(results) == 3


class TestBrokerInterfaceContract:
    """Regression: the mirror must NOT swallow critical adapter errors
    silently. A misconfigured adapter (no price set) produces a REJECTED
    ack which we log but don't raise — engine keeps running."""

    def test_broker_reject_does_not_crash_engine(self, tmp_path):
        cm = _zero_cost_model()
        broker = SimulatedBrokerAdapter(
            cost_model=cm, initial_cash=100_000.0,
        )
        # Intentionally DON'T set a default price; engine will try to
        # pin per-fill via set_next_fill_price, so mirror should still
        # succeed. But if we call without any price setup at all, the
        # adapter rejects. Here we verify the engine survives regardless.
        engine = _make_engine(tmp_path, cm, broker=broker)
        engine.run_day_daily(
            date=pd.Timestamp("2024-01-02"),
            target_wts={"AAPL": 0.5},
            prices={"AAPL": 100.0},
            open_prices={"AAPL": 100.0},
        )
        # Engine reconciled; should pass because pin-price path works.
        results = engine.get_broker_reconcile_results()
        assert len(results) == 1
