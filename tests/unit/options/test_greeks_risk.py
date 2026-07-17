from __future__ import annotations

from datetime import date

import pytest

from core.options.data import OptionContract, OptionRight
from core.options.risk import (
    OptionsRiskLimits,
    PositionGreeks,
    aggregate_greeks,
    evaluate_options_risk,
)


def position(**overrides) -> PositionGreeks:
    values = {
        "contract": OptionContract(
            contract_id="SPY-P-600",
            occ_symbol="SPY260821P00600000",
            underlying="SPY",
            expiry=date(2026, 8, 21),
            strike=600,
            right=OptionRight.PUT,
        ),
        "signed_contracts": 1,
        "underlying_price": 625.0,
        "delta": -0.20,
        "gamma": 0.005,
        "vega": 0.15,
        "theta": -0.05,
        "defined_max_loss": 2_000.0,
    }
    values.update(overrides)
    return PositionGreeks(**values)


def test_aggregate_greeks_applies_contract_multiplier_and_sign():
    aggregate = aggregate_greeks((position(),))
    assert aggregate.dollar_delta == pytest.approx(-12_500.0)
    assert aggregate.vega == pytest.approx(15.0)
    assert aggregate.theta == pytest.approx(-5.0)
    assert aggregate.defined_max_loss == 2_000.0


def test_options_risk_approves_bounded_defined_loss():
    decision = evaluate_options_risk(
        (position(),),
        equity=100_000,
        limits=OptionsRiskLimits(),
    )
    assert decision.approved
    assert decision.reason_codes == ()


def test_options_risk_reports_all_breaches_without_short_circuit():
    decision = evaluate_options_risk(
        (
            position(
                signed_contracts=10,
                gamma=0.05,
                vega=20,
                theta=-20,
                defined_max_loss=20_000,
            ),
        ),
        equity=100_000,
        limits=OptionsRiskLimits(),
    )
    assert not decision.approved
    assert set(decision.reason_codes) == {
        "OPTIONS_DELTA_LIMIT",
        "OPTIONS_GAMMA_LIMIT",
        "OPTIONS_VEGA_LIMIT",
        "OPTIONS_THETA_LIMIT",
        "OPTIONS_MAX_LOSS_LIMIT",
    }
