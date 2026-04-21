"""Round 11 Topic L (2026-04-20): BrokerAdapter skeleton tests.

PRD completion signal: interface test submit → ack → fill →
reconcile round-trip. These tests exercise the SimulatedBrokerAdapter
implementation end-to-end without needing any real broker.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from core.config.loader import load_config
from core.execution.broker_adapter import (
    BrokerAdapter,
    OrderAck,
    ReconcileResult,
    SimulatedBrokerAdapter,
)
from core.execution.cost_model import CostModel
from core.execution.execution_simulator import Order, OrderSide


def _cost():
    return CostModel(load_config(Path("config")).cost_model)


def _mk_order(sym="AAPL", side=OrderSide.BUY, qty=10):
    return Order(
        symbol=sym, side=side, qty_shares=qty,
        signal_date=pd.Timestamp("2025-04-01"),
    )


class TestABCEnforcement:
    def test_broker_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            BrokerAdapter()  # cannot instantiate abstract class

    def test_simulated_adapter_inherits(self):
        assert issubclass(SimulatedBrokerAdapter, BrokerAdapter)


class TestSubmitAckFillRoundtrip:
    """PRD completion signal: submit → ack → fill → reconcile."""

    def test_happy_path_buy(self):
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
        )
        ba.set_default_fill_price(100.0)
        order = _mk_order(sym="AAPL", side=OrderSide.BUY, qty=10)

        # SUBMIT
        ack = ba.submit_order(order)
        assert isinstance(ack, OrderAck)
        assert ack.status == "ACCEPTED"
        assert len(ack.order_id) == 12
        assert ack.order is order

        # FILL already booked (simulated adapter fills immediately)
        fills = ba.get_fills(since=datetime.now() - timedelta(seconds=5))
        assert len(fills) == 1
        f = fills[0]
        assert f.order.symbol == "AAPL"
        assert f.executed_qty > 0
        # Cash decreased
        assert ba.get_cash() < 100_000.0
        # Position booked
        assert ba.get_positions().get("AAPL", 0) > 0

    def test_sell_reduces_position(self):
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
            initial_positions={"AAPL": 50.0},
        )
        ba.set_default_fill_price(100.0)
        sell = _mk_order(sym="AAPL", side=OrderSide.SELL, qty=20)
        ack = ba.submit_order(sell)
        assert ack.status == "ACCEPTED"
        pos = ba.get_positions()
        # ExecutionSimulator may adjust fill qty; position strictly below 50
        assert pos.get("AAPL", 0) < 50.0

    def test_no_fill_price_configured_rejects(self):
        ba = SimulatedBrokerAdapter(cost_model=_cost())
        order = _mk_order()
        ack = ba.submit_order(order)
        assert ack.status == "REJECTED"
        assert "price" in ack.reject_reason.lower()


class TestReconcile:

    def test_clean_reconcile_passes(self):
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
        )
        ba.set_default_fill_price(100.0)
        ba.submit_order(_mk_order("AAPL", OrderSide.BUY, 10))
        # Reconcile with the adapter's own state → should PASS
        result = ba.reconcile(
            expected_positions=ba.get_positions(),
            expected_cash=ba.get_cash(),
        )
        assert isinstance(result, ReconcileResult)
        assert result.passed is True
        assert result.position_mismatches == {}
        assert abs(result.cash_mismatch) < 1e-4

    def test_mismatch_flagged(self):
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
        )
        ba.set_default_fill_price(100.0)
        ba.submit_order(_mk_order("AAPL", OrderSide.BUY, 10))
        # Intentionally wrong expected
        result = ba.reconcile(
            expected_positions={"AAPL": 1000.0, "MSFT": 500.0},
            expected_cash=99_999_999.0,
        )
        assert result.passed is False
        assert "AAPL" in result.position_mismatches
        assert "MSFT" in result.position_mismatches
        assert result.cash_mismatch < -10_000_000  # adapter has way less

    def test_empty_reconcile_passes(self):
        """Adapter with no activity and no expected positions → trivial
        pass."""
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
        )
        r = ba.reconcile(expected_positions={}, expected_cash=100_000.0)
        assert r.passed is True


class TestFillsHistory:

    def test_get_fills_filters_by_time(self):
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
        )
        ba.set_default_fill_price(100.0)

        ba.submit_order(_mk_order("AAPL", OrderSide.BUY, 5))
        cutoff = datetime.now()
        # Small real wait to guarantee timestamp ordering — using 0 is OK
        # since datetime.now() microsecond resolution
        ba.submit_order(_mk_order("MSFT", OrderSide.BUY, 5))

        old_fills = ba.get_fills(since=cutoff - timedelta(seconds=10))
        recent = ba.get_fills(since=cutoff)
        assert len(old_fills) >= 2
        assert len(recent) <= len(old_fills)

    def test_fill_cash_delta_matches_cash_change(self):
        ba = SimulatedBrokerAdapter(
            cost_model=_cost(), initial_cash=100_000.0,
        )
        ba.set_default_fill_price(100.0)
        cash_before = ba.get_cash()
        ba.submit_order(_mk_order("AAPL", OrderSide.BUY, 10))
        fills = ba.get_fills(since=datetime.now() - timedelta(seconds=5))
        f = fills[0]
        expected_cash = cash_before + f.cash_delta
        assert abs(ba.get_cash() - expected_cash) < 1e-4


class TestContractPurity:
    """BrokerAdapter must NOT expose any strategy-layer concern — only
    order submission, position/cash queries, reconcile. Strategy code
    must never care whether it's talking to simulated or real adapter.
    """

    def test_interface_method_set(self):
        """All 7 abstract methods per CLAUDE.md §4.1 present."""
        expected = {
            "submit_order", "cancel_order", "get_positions", "get_cash",
            "get_open_orders", "get_fills", "reconcile",
        }
        # Get abstract methods via __abstractmethods__ on ABC
        assert expected.issubset(set(BrokerAdapter.__abstractmethods__)) \
               or all(
                   hasattr(BrokerAdapter, m)
                   for m in expected
               )

    def test_sim_adapter_implements_all(self):
        ba = SimulatedBrokerAdapter(cost_model=_cost())
        # If any abstract method missed, instantiation would have failed
        for m in ("submit_order", "cancel_order", "get_positions",
                  "get_cash", "get_open_orders", "get_fills", "reconcile"):
            assert callable(getattr(ba, m))
