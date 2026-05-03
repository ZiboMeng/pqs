"""Lock multi-leg spread combination math.

Tests assert: net_credit / max_loss / max_profit / breakeven formulas
match textbook + at-expiry payoff degenerate to deterministic intrinsic.
"""
from __future__ import annotations

import math
import pytest

from core.options.strategies.spreads import (
    BullPutSpread, BearCallSpread, IronCondor, SpreadMetrics,
    bull_put_spread_metrics, bear_call_spread_metrics, iron_condor_metrics,
    bull_put_spread_mtm, bear_call_spread_mtm, iron_condor_mtm,
    bull_put_spread_expiry_payoff, bear_call_spread_expiry_payoff,
    iron_condor_expiry_payoff,
)


# -- Bull put spread ---------------------------------------------------------

def test_bull_put_spread_net_credit_positive():
    """Selling a higher-strike put + buying lower-strike put → net credit > 0."""
    spread = BullPutSpread(
        spot_at_open=400.0, k_short_put=380.0, k_long_put=375.0,
        t_years=30/365, sigma=0.20, r=0.045,
    )
    m = bull_put_spread_metrics(spread)
    assert m.net_credit_per_share > 0
    assert m.max_profit_per_share == m.net_credit_per_share
    assert m.width_per_share == 5.0


def test_bull_put_spread_max_loss_formula():
    """max_loss = width - net_credit."""
    spread = BullPutSpread(
        spot_at_open=400.0, k_short_put=380.0, k_long_put=375.0,
        t_years=30/365, sigma=0.30, r=0.045,
    )
    m = bull_put_spread_metrics(spread)
    assert m.max_loss_per_share == pytest.approx(5.0 - m.net_credit_per_share, abs=1e-8)
    assert m.breakeven_low == pytest.approx(380.0 - m.net_credit_per_share)


def test_bull_put_spread_strike_order_validation():
    with pytest.raises(ValueError, match="long put strike"):
        bull_put_spread_metrics(BullPutSpread(
            spot_at_open=400.0, k_short_put=375.0, k_long_put=380.0,  # swapped!
            t_years=30/365, sigma=0.20, r=0.045,
        ))


def test_bull_put_spread_expiry_payoff_above_short_strike_zero():
    """Spot > k_short → both puts OTM → no obligation."""
    pay = bull_put_spread_expiry_payoff(k_short=380, k_long=375, spot_at_expiry=420)
    assert pay == 0.0


def test_bull_put_spread_expiry_payoff_below_long_strike_capped():
    """Spot < k_long → spread fully ITM → loss = width."""
    pay = bull_put_spread_expiry_payoff(k_short=380, k_long=375, spot_at_expiry=350)
    assert pay == 5.0  # width


def test_bull_put_spread_expiry_payoff_between_strikes():
    """Spot between strikes → partial loss = k_short - spot."""
    pay = bull_put_spread_expiry_payoff(k_short=380, k_long=375, spot_at_expiry=378)
    assert pay == 2.0


# -- Bear call spread --------------------------------------------------------

def test_bear_call_spread_net_credit_positive():
    spread = BearCallSpread(
        spot_at_open=400.0, k_short_call=420.0, k_long_call=425.0,
        t_years=30/365, sigma=0.20, r=0.045,
    )
    m = bear_call_spread_metrics(spread)
    assert m.net_credit_per_share > 0
    assert m.width_per_share == 5.0


def test_bear_call_spread_max_loss_formula():
    spread = BearCallSpread(
        spot_at_open=400.0, k_short_call=420.0, k_long_call=425.0,
        t_years=30/365, sigma=0.30, r=0.045,
    )
    m = bear_call_spread_metrics(spread)
    assert m.max_loss_per_share == pytest.approx(5.0 - m.net_credit_per_share, abs=1e-8)
    assert m.breakeven_high == pytest.approx(420.0 + m.net_credit_per_share)


def test_bear_call_spread_strike_order_validation():
    with pytest.raises(ValueError, match="long call strike"):
        bear_call_spread_metrics(BearCallSpread(
            spot_at_open=400.0, k_short_call=425.0, k_long_call=420.0,
            t_years=30/365, sigma=0.20, r=0.045,
        ))


def test_bear_call_spread_expiry_payoff_below_short_strike_zero():
    pay = bear_call_spread_expiry_payoff(k_short=420, k_long=425, spot_at_expiry=400)
    assert pay == 0.0


def test_bear_call_spread_expiry_payoff_above_long_strike_capped():
    pay = bear_call_spread_expiry_payoff(k_short=420, k_long=425, spot_at_expiry=440)
    assert pay == 5.0


# -- Iron condor -------------------------------------------------------------

def test_iron_condor_credit_equals_sum_of_legs():
    ic = IronCondor(
        spot_at_open=400.0,
        k_long_put=375, k_short_put=380, k_short_call=420, k_long_call=425,
        t_years=30/365, sigma=0.20, r=0.045,
    )
    bull = BullPutSpread(spot_at_open=400.0, k_short_put=380, k_long_put=375,
                         t_years=30/365, sigma=0.20, r=0.045)
    bear = BearCallSpread(spot_at_open=400.0, k_short_call=420, k_long_call=425,
                          t_years=30/365, sigma=0.20, r=0.045)
    ic_m = iron_condor_metrics(ic)
    bull_m = bull_put_spread_metrics(bull)
    bear_m = bear_call_spread_metrics(bear)
    assert ic_m.net_credit_per_share == pytest.approx(
        bull_m.net_credit_per_share + bear_m.net_credit_per_share, abs=1e-10,
    )


def test_iron_condor_max_loss_only_one_side():
    """At expiry, spot CANNOT be both below put strikes AND above call strikes
    simultaneously. So max_loss = max(width_put, width_call) - net_credit,
    NOT sum of both sides' max losses."""
    ic = IronCondor(
        spot_at_open=400.0,
        k_long_put=375, k_short_put=380, k_short_call=420, k_long_call=425,
        t_years=30/365, sigma=0.20, r=0.045,
    )
    m = iron_condor_metrics(ic)
    # Both sides equal-width 5-pt; max_loss = 5 - net_credit
    assert m.max_loss_per_share == pytest.approx(5.0 - m.net_credit_per_share, abs=1e-8)
    # NOT 2 * 5 - net_credit
    assert m.max_loss_per_share < 10.0


def test_iron_condor_strike_order_validation():
    with pytest.raises(ValueError, match="ordered"):
        iron_condor_metrics(IronCondor(
            spot_at_open=400.0,
            k_long_put=380, k_short_put=375,  # swapped
            k_short_call=420, k_long_call=425,
            t_years=30/365, sigma=0.20, r=0.045,
        ))


def test_iron_condor_expiry_payoff_inside_wings_zero():
    """Spot between short strikes → all options OTM → no payout."""
    pay = iron_condor_expiry_payoff(
        k_long_put=375, k_short_put=380, k_short_call=420, k_long_call=425,
        spot_at_expiry=400,
    )
    assert pay == 0.0


def test_iron_condor_expiry_payoff_below_put_wing():
    """Spot below k_long_put → put side fully ITM → loss = width."""
    pay = iron_condor_expiry_payoff(
        k_long_put=375, k_short_put=380, k_short_call=420, k_long_call=425,
        spot_at_expiry=370,
    )
    assert pay == 5.0  # width of put side


def test_iron_condor_expiry_payoff_above_call_wing():
    pay = iron_condor_expiry_payoff(
        k_long_put=375, k_short_put=380, k_short_call=420, k_long_call=425,
        spot_at_expiry=430,
    )
    assert pay == 5.0  # width of call side


# -- MtM continuity (at t→0, MtM == intrinsic) ------------------------------

def test_bull_put_mtm_approaches_intrinsic_at_expiry():
    """As t→0, MtM(spread) → at-expiry payoff."""
    spread = BullPutSpread(spot_at_open=400, k_short_put=380, k_long_put=375,
                           t_years=30/365, sigma=0.20, r=0.045)
    # At t→0 (1 hour from expiry), spot=378 → intrinsic = 380-378 - max(375-378,0) = 2.0
    mtm = bull_put_spread_mtm(spread, spot_now=378, sigma_now=0.20,
                              t_now=1/(365*24), r_now=0.045)
    assert mtm == pytest.approx(2.0, abs=0.05)


def test_iron_condor_mtm_zero_when_far_otm():
    """Spot deep inside wings + low time: MtM near zero (we owe nothing)."""
    ic = IronCondor(spot_at_open=400, k_long_put=370, k_short_put=375,
                    k_short_call=425, k_long_call=430,
                    t_years=30/365, sigma=0.15, r=0.045)
    mtm = iron_condor_mtm(ic, spot_now=400, sigma_now=0.15,
                          t_now=1/(365*24), r_now=0.045)
    assert abs(mtm) < 0.10
