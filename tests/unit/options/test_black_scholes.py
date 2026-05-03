"""Lock Black-Scholes pricing for synthetic option backtests.

Reference values cross-checked against py_vollib + manual textbook
computation. If any of these drift, the synthetic backtest results
become non-reproducible.
"""
from __future__ import annotations

import math

import pytest

from core.options.pricing.black_scholes import BSInputs, put_price, call_price, put_greeks


def test_put_call_parity():
    """C - P = S*exp(-qT) - K*exp(-rT)."""
    inp = BSInputs(spot=100.0, strike=100.0, t_years=0.25, sigma=0.20, r=0.05, q=0.0)
    c = call_price(inp)
    p = put_price(inp)
    expected = inp.spot * math.exp(-inp.q * inp.t_years) - inp.strike * math.exp(-inp.r * inp.t_years)
    assert c - p == pytest.approx(expected, abs=1e-8)


def test_atm_30dte_20pct_iv_known_value():
    """ATM put, 30 calendar days, 20% IV, 5% rate ≈ 2.07 (textbook BS)."""
    inp = BSInputs(spot=100.0, strike=100.0, t_years=30 / 365, sigma=0.20, r=0.05)
    p = put_price(inp)
    # Cross-checked against scipy/py_vollib: ~2.07
    assert p == pytest.approx(2.07, abs=0.05)


def test_5pct_otm_put_smaller_than_atm():
    """5% OTM put cheaper than ATM (intrinsic floor distinction)."""
    atm = BSInputs(spot=400.0, strike=400.0, t_years=30 / 365, sigma=0.20, r=0.045)
    otm = BSInputs(spot=400.0, strike=380.0, t_years=30 / 365, sigma=0.20, r=0.045)
    assert put_price(otm) < put_price(atm)
    assert put_price(otm) > 0


def test_long_put_delta_in_range():
    """Long put delta is in [-1, 0]; ATM-ish near -0.5."""
    inp = BSInputs(spot=100.0, strike=100.0, t_years=30 / 365, sigma=0.20, r=0.05)
    g = put_greeks(inp)
    assert -1.0 < g.delta < 0.0
    # Should be near -0.5 for short-dated ATM
    assert g.delta == pytest.approx(-0.46, abs=0.05)


def test_5pct_otm_delta_far_from_atm():
    """5% OTM 30-DTE put has |delta| ~ 0.15-0.25 typical wheel target zone."""
    inp = BSInputs(spot=400.0, strike=380.0, t_years=30 / 365, sigma=0.20, r=0.045)
    g = put_greeks(inp)
    assert -0.30 < g.delta < -0.10


def test_high_vol_inflates_premium():
    """80% IV (COVID-like) gives put premium ~10x of 20% IV."""
    low = put_price(BSInputs(spot=400.0, strike=380.0, t_years=30 / 365, sigma=0.20, r=0.045))
    high = put_price(BSInputs(spot=400.0, strike=380.0, t_years=30 / 365, sigma=0.80, r=0.045))
    assert high / low > 5.0


def test_zero_vol_intrinsic_only():
    """sigma -> very small; OTM put price approaches discounted intrinsic (0 here)."""
    inp = BSInputs(spot=400.0, strike=380.0, t_years=30 / 365, sigma=0.001, r=0.045)
    p = put_price(inp)
    assert p < 0.01  # essentially zero, since spot >> strike


def test_degenerate_inputs_raise():
    with pytest.raises(ValueError):
        put_price(BSInputs(spot=100.0, strike=100.0, t_years=0.0, sigma=0.20, r=0.05))
    with pytest.raises(ValueError):
        put_price(BSInputs(spot=100.0, strike=100.0, t_years=0.25, sigma=0.0, r=0.05))


def test_vega_positive_and_bounded():
    """Vega per 1.00 sigma move is positive and well-defined for ATM short-DTE."""
    inp = BSInputs(spot=400.0, strike=400.0, t_years=30 / 365, sigma=0.20, r=0.045)
    g = put_greeks(inp)
    assert g.vega > 0
    # Per vol-point (0.01 of sigma), expect ~0.4 dollars per share for ATM 30-DTE @ S=400
    assert g.vega / 100 == pytest.approx(0.45, abs=0.10)


def test_theta_negative_for_long_put():
    """Long put loses value as time passes (negative theta)."""
    inp = BSInputs(spot=400.0, strike=400.0, t_years=30 / 365, sigma=0.20, r=0.045)
    g = put_greeks(inp)
    assert g.theta_per_day < 0
