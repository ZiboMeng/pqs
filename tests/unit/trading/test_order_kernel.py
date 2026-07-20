from __future__ import annotations

from dataclasses import replace

import pytest

from core.trading.order import OrderIntent, OrderState, TradingSide
from core.trading.risk import PreTradeRiskEngine, RiskLimits, RiskSnapshot
from core.trading.service import OrderRegistrationService
from core.trading.store import (
    IdempotencyConflictError,
    InvalidOrderTransitionError,
    OrderStore,
)


def intent(**overrides) -> OrderIntent:
    values = {
        "symbol": "SPY",
        "side": TradingSide.BUY,
        "quantity": 100.0,
        "reference_price": 100.0,
        "signal_id": "sig-1",
        "strategy_id": "stable-base",
        "decision_id": "decision-1",
        "idempotency_key": "stable-base:decision-1:SPY:BUY",
    }
    values.update(overrides)
    return OrderIntent(**values)


def snapshot(**overrides) -> RiskSnapshot:
    values = {
        "equity": 100_000.0,
        "cash": 100_000.0,
        "positions": {},
        "prices": {"SPY": 100.0},
        "data_fresh": True,
        "reconciliation_ok": True,
    }
    values.update(overrides)
    return RiskSnapshot(**values)


def test_order_intent_rejects_invalid_numeric_values():
    with pytest.raises(ValueError, match="quantity"):
        intent(quantity=float("nan"))
    with pytest.raises(ValueError, match="reference_price"):
        intent(reference_price=0)


def test_pretrade_approves_order_inside_every_limit():
    decision = PreTradeRiskEngine(RiskLimits()).evaluate(intent(), snapshot())
    assert decision.approved
    assert decision.reason_codes == ()


def test_pretrade_fails_closed_on_operational_gates():
    decision = PreTradeRiskEngine(RiskLimits()).evaluate(
        intent(),
        snapshot(
            data_fresh=False,
            reconciliation_ok=False,
            kill_switch_active=True,
            manual_pause=True,
        ),
    )
    assert not decision.approved
    assert set(decision.reason_codes) >= {
        "STALE_MARKET_DATA",
        "RECONCILIATION_NOT_OK",
        "KILL_SWITCH_ACTIVE",
        "MANUAL_PAUSE_ACTIVE",
    }


def test_pretrade_rejects_cash_position_gross_and_turnover_breaches():
    limits = RiskLimits(
        max_gross_exposure=0.20,
        max_single_position=0.15,
        min_cash_fraction=0.90,
        max_daily_turnover_fraction=0.05,
        max_order_notional_fraction=0.20,
    )
    decision = PreTradeRiskEngine(limits).evaluate(intent(quantity=250), snapshot())
    assert not decision.approved
    assert set(decision.reason_codes) >= {
        "MIN_CASH_BREACH",
        "SYMBOL_CAP_BREACH",
        "GROSS_EXPOSURE_BREACH",
        "DAILY_TURNOVER_LIMIT",
        "MAX_ORDER_NOTIONAL_BREACH",
    }


def test_pretrade_reserves_estimated_cost_above_minimum_cash():
    limits = RiskLimits(
        max_gross_exposure=1.0,
        max_single_position=1.0,
        min_cash_fraction=0.05,
        max_order_notional_fraction=1.0,
    )
    decision = PreTradeRiskEngine(limits).evaluate(
        intent(quantity=950),
        snapshot(estimated_order_cost=1.0),
    )
    assert not decision.approved
    assert "MIN_CASH_BREACH" in decision.reason_codes


def test_pretrade_allows_sell_that_reduces_existing_limit_breaches():
    limits = RiskLimits(
        max_gross_exposure=0.30,
        max_single_position=0.30,
        max_order_notional_fraction=0.01,
        max_daily_turnover_fraction=0.01,
        blocked_symbols=frozenset({"QQQ"}),
    )
    order = intent(
        symbol="QQQ",
        side=TradingSide.SELL,
        quantity=50.0,
        reference_price=100.0,
    )
    decision = PreTradeRiskEngine(limits).evaluate(
        order,
        snapshot(
            cash=60_000.0,
            positions={"QQQ": 400.0},
            prices={"QQQ": 100.0},
            daily_pnl=-4_000.0,
            daily_turnover=50_000.0,
            kill_switch_active=True,
        ),
    )
    assert decision.approved
    assert decision.reason_codes == ()


def test_pretrade_does_not_exempt_sell_from_data_pause_or_reconciliation():
    order = intent(
        side=TradingSide.SELL,
        quantity=10.0,
    )
    decision = PreTradeRiskEngine(RiskLimits()).evaluate(
        order,
        snapshot(
            cash=90_000.0,
            positions={"SPY": 100.0},
            data_fresh=False,
            manual_pause=True,
            reconciliation_ok=False,
        ),
    )
    assert not decision.approved
    assert set(decision.reason_codes) >= {
        "STALE_MARKET_DATA",
        "MANUAL_PAUSE_ACTIVE",
        "RECONCILIATION_NOT_OK",
    }


def test_pretrade_rejects_stale_reference_price_deviation():
    decision = PreTradeRiskEngine(
        RiskLimits(max_reference_price_deviation=0.02)
    ).evaluate(intent(reference_price=90.0), snapshot())
    assert not decision.approved
    assert decision.reason_codes == ("REFERENCE_PRICE_DEVIATION",)


def test_pretrade_rejects_short_and_missing_position_marks():
    sell = intent(side=TradingSide.SELL, quantity=2)
    decision = PreTradeRiskEngine(RiskLimits()).evaluate(
        sell,
        snapshot(positions={"SPY": 1, "QQQ": 1}),
    )
    assert not decision.approved
    assert "SHORT_POSITION_FORBIDDEN" in decision.reason_codes
    assert "MISSING_POSITION_PRICE:QQQ" in decision.reason_codes


def test_store_is_idempotent_and_survives_restart(tmp_path):
    db = tmp_path / "orders.db"
    first_store = OrderStore(db)
    original = intent()
    first, created = first_store.create_or_get(original)
    assert created
    assert first.state is OrderState.CREATED

    duplicate_intent = replace(original, order_id="ord_duplicate")
    duplicate, created = OrderStore(db).create_or_get(duplicate_intent)
    assert not created
    assert duplicate.intent.order_id == original.order_id
    assert len(OrderStore(db).events(original.order_id)) == 1


def test_store_rejects_idempotency_key_reuse_for_different_intent(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    store.create_or_get(intent())
    with pytest.raises(IdempotencyConflictError):
        store.create_or_get(intent(symbol="QQQ"))


def test_store_enforces_lifecycle_and_fill_quantity(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    order = intent(quantity=10)
    store.create_or_get(order)
    with pytest.raises(InvalidOrderTransitionError):
        store.transition(order.order_id, OrderState.FILLED, reason="skip")

    store.transition(order.order_id, OrderState.VALIDATED, reason="risk")
    store.transition(order.order_id, OrderState.SUBMITTED, reason="submit")
    store.transition(
        order.order_id,
        OrderState.ACKNOWLEDGED,
        reason="ack",
        broker_order_id="broker-1",
    )
    partial = store.transition(
        order.order_id,
        OrderState.PARTIALLY_FILLED,
        reason="fill",
        filled_quantity=4,
    )
    assert partial.filled_quantity == 4
    filled = store.transition(
        order.order_id,
        OrderState.FILLED,
        reason="fill",
        filled_quantity=10,
    )
    assert filled.state is OrderState.FILLED
    assert [event["to_state"] for event in store.events(order.order_id)] == [
        "CREATED",
        "VALIDATED",
        "SUBMITTED",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "FILLED",
    ]


def test_registration_service_durably_records_veto_and_deduplicates(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    service = OrderRegistrationService(store, PreTradeRiskEngine(RiskLimits()))
    order = intent()
    result = service.register(order, snapshot(data_fresh=False))
    assert result.order.state is OrderState.REJECTED
    assert result.risk_decision is not None
    assert result.risk_decision.reason_codes == ("STALE_MARKET_DATA",)

    duplicate = service.register(order, snapshot())
    assert duplicate.duplicate
    assert duplicate.order.state is OrderState.REJECTED
    assert duplicate.risk_decision is None


def test_simulator_partial_fill_closes_unfilled_remainder_atomically(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    service = OrderRegistrationService(store, PreTradeRiskEngine(RiskLimits()))
    order = intent(quantity=10)
    assert service.register(order, snapshot()).order.state is OrderState.VALIDATED

    service.commit_simulated_execution([(order.order_id, 4.0)], persist=lambda conn: None)

    completed = store.get(order.order_id)
    assert completed is not None
    assert completed.state is OrderState.CANCELLED
    assert completed.filled_quantity == 4.0
    assert [event["to_state"] for event in store.events(order.order_id)][-2:] == [
        "PARTIALLY_FILLED",
        "CANCELLED",
    ]


def test_restart_quarantines_possibly_submitted_orders_without_retry(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    service = OrderRegistrationService(store, PreTradeRiskEngine(RiskLimits()))
    order = intent()
    result = service.register(order, snapshot())
    assert result.order.state is OrderState.VALIDATED
    service.mark_submitted(order.order_id, broker_order_id="broker-unknown")

    recovered = OrderRegistrationService(
        OrderStore(tmp_path / "orders.db"),
        PreTradeRiskEngine(RiskLimits()),
    ).quarantine_after_restart()
    assert len(recovered) == 1
    assert recovered[0].state is OrderState.UNKNOWN
    assert recovered[0].broker_order_id == "broker-unknown"
