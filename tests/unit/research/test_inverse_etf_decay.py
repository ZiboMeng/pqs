"""PRD-2 P2.1 R3 — 1x inverse-ETF daily-reset decay cost model (TDD).

A -1x daily-reset ETF held multi-day does NOT return -(cumulative
index move): it COMPOUNDS each day's inverse, so volatility/path
introduces drift ("beta slippage" / volatility decay). The model
returns BOTH the decay-modeled cumulative return AND the
naive-optimistic one, so the harness can report the gap explicitly
(PRD-2 §7 P2.1(c): decay optimistic-vs-modeled must both be reported,
NEVER only the optimistic).
"""
import numpy as np
import pytest

from core.research.construction_tiers import inverse_etf_decay_return


class TestInverseEtfDecay:
    def test_hand_computed_oscillation_drag(self):
        # index +10% then -13.6% (net ≈ -4.96%). A -1x daily-reset:
        # day1 -10%, day2 +13.6% -> (0.90)(1.136)-1 = +2.24%,
        # NOT +4.96%. naive (= -cumulative index) = +4.96%.
        modeled, naive = inverse_etf_decay_return([0.10, -0.136],
                                                  expense_annual=0.0)
        assert modeled == pytest.approx(0.02240, abs=1e-5)
        assert naive == pytest.approx(0.04960, abs=1e-5)
        # decay = modeled - naive < 0 (drag in oscillating market)
        assert modeled - naive == pytest.approx(-0.02720, abs=1e-5)

    def test_expense_reduces_modeled_only(self):
        flat = [0.0, 0.0, 0.0]
        m0, n0 = inverse_etf_decay_return(flat, expense_annual=0.0)
        me, ne = inverse_etf_decay_return(flat, expense_annual=0.0090)
        assert m0 == pytest.approx(0.0) and n0 == pytest.approx(0.0)
        assert me < 0.0          # expense drag on the modeled leg
        assert ne == pytest.approx(0.0)   # naive ignores expense

    def test_empty_returns_zero_zero(self):
        assert inverse_etf_decay_return([], expense_annual=0.0009) == (
            0.0, 0.0)

    def test_monotone_decline_path_dependent_not_drag(self):
        # pure -1%/day monotone fall: compounding favours the inverse
        # leg -> modeled > naive (decay is path-dependent, NOT always a
        # drag; the PRD point is "report both", not "decay<0 always").
        r = [-0.01] * 5
        m, n = inverse_etf_decay_return(r, expense_annual=0.0)
        assert m == pytest.approx((1.01) ** 5 - 1.0, abs=1e-9)
        assert n == pytest.approx(-((0.99) ** 5 - 1.0), abs=1e-9)
        assert m > n                       # path-dependent (not drag)

    def test_returns_are_floats_not_numpy(self):
        m, n = inverse_etf_decay_return([0.02, -0.03], expense_annual=0.0)
        assert type(m) is float and type(n) is float
