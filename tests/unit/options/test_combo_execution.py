from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from core.options.data import OptionContract, OptionRight
from core.options.execution import (
    ComboExecution,
    ComboLeg,
    ComboOrder,
    ComboStatus,
    LegAction,
    LegFill,
    NetPriceType,
)


def option(contract_id: str, strike: float) -> OptionContract:
    return OptionContract(
        contract_id=contract_id,
        occ_symbol=contract_id,
        underlying="SPY",
        expiry=date(2026, 8, 21),
        strike=strike,
        right=OptionRight.PUT,
    )


def spread(quantity: int = 2) -> ComboOrder:
    return ComboOrder(
        legs=(
            ComboLeg(option("short", 600), LegAction.SELL),
            ComboLeg(option("long", 590), LegAction.BUY),
        ),
        quantity=quantity,
        net_price_type=NetPriceType.CREDIT,
        limit_price=1.25,
        strategy_id="defined-risk-put-spread",
        decision_id="decision-1",
        idempotency_key="decision-1:SPY:600-590P",
    )


def fill(contract_id: str, quantity: int, price: float) -> LegFill:
    return LegFill(contract_id, quantity, price, datetime.now(UTC))


def test_combo_requires_defined_risk_long_and_short_legs():
    order = spread()
    assert len(order.legs) == 2
    with pytest.raises(ValueError, match="both long and short"):
        ComboOrder(
            legs=(
                ComboLeg(option("a", 600), LegAction.SELL),
                ComboLeg(option("b", 590), LegAction.SELL),
            ),
            quantity=1,
            net_price_type=NetPriceType.CREDIT,
            limit_price=1,
            strategy_id="s",
            decision_id="d",
            idempotency_key="i",
        )


def test_combo_identifies_legging_risk_and_partial_fill_separately():
    order = spread(quantity=2)
    legged = ComboExecution(order, (fill("short", 2, 5.0),))
    assert legged.status is ComboStatus.LEGGED_RISK

    partial = ComboExecution(
        order,
        (fill("short", 1, 5.0), fill("long", 1, 3.75)),
    )
    assert partial.status is ComboStatus.PARTIALLY_FILLED


def test_filled_combo_computes_multiplier_aware_cash_delta():
    order = spread(quantity=2)
    execution = ComboExecution(
        order,
        (fill("short", 2, 5.0), fill("long", 2, 3.75)),
    )
    assert execution.status is ComboStatus.FILLED
    assert execution.net_cash_delta == pytest.approx(250.0)


def test_combo_rejects_overfill_and_unknown_leg():
    order = spread(quantity=2)
    with pytest.raises(ValueError, match="exceeds"):
        ComboExecution(order, (fill("short", 3, 5.0),))
    with pytest.raises(ValueError, match="unknown leg"):
        ComboExecution(order, (fill("other", 1, 5.0),))
