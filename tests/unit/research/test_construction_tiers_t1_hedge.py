"""PRD-2 P2.1 R2 — T1 1x inverse-ETF hedge weight construction (TDD).

T1 = invariant-PRESERVING hedge: BUY a 1x inverse ETF (SH/PSQ/DOG) as
a sleeve. All weights stay >= 0 (the inverse ETF is itself a LONG
position), sum <= 1.0 (no margin). This is mechanistically distinct
from core/research/long_short_config.py (true short / negative
weights = T2 territory, PRD-2 §6 permanently gated) — T1 must NOT be
routed through that schema (would conflate invariant-preserving hedge
with invariant-breaking short). SQQQ + any leveraged inverse are
permanently blacklisted (CLAUDE.md invariant); only 1x SH/PSQ/DOG.
"""
import numpy as np
import pandas as pd
import pytest

from core.research.construction_tiers import (
    T1HedgeConfig,
    apply_t1_inverse_hedge,
)


class TestT1HedgeConfig:
    def test_defaults_invariant_preserving(self):
        c = T1HedgeConfig()
        assert c.hedge_etf in ("SH", "PSQ", "DOG")
        assert c.hedge_frac == 0.0          # default = no hedge (== T0)
        assert 0.0 < c.max_hedge_frac <= 0.5

    def test_sqqq_and_leveraged_inverse_permanently_blacklisted(self):
        for bad in ("SQQQ", "SPXU", "SDS", "QID", "PSQ3X"):
            with pytest.raises(ValueError):
                T1HedgeConfig(hedge_etf=bad)

    def test_hedge_frac_bounds(self):
        with pytest.raises(ValueError):
            T1HedgeConfig(hedge_frac=-0.01)
        with pytest.raises(ValueError):
            T1HedgeConfig(hedge_frac=0.6, max_hedge_frac=0.30)  # > cap


class TestApplyT1InverseHedge:
    def test_hand_computed_overlay(self):
        lw = pd.Series({"AAA": 0.6, "BBB": 0.4})
        out = apply_t1_inverse_hedge(lw, hedge_etf="SH", hedge_frac=0.20)
        # long sleeve scaled to (1-0.20); hedge 0.20 in SH
        assert out["AAA"] == pytest.approx(0.48)
        assert out["BBB"] == pytest.approx(0.32)
        assert out["SH"] == pytest.approx(0.20)

    def test_frac_zero_is_noop_equals_T0(self):
        lw = pd.Series({"AAA": 0.5, "BBB": 0.5})
        out = apply_t1_inverse_hedge(lw, hedge_etf="SH", hedge_frac=0.0)
        pd.testing.assert_series_equal(out.sort_index(), lw.sort_index())

    def test_invariants_no_margin_no_negative(self):
        lw = pd.Series({"AAA": 0.7, "BBB": 0.3})
        out = apply_t1_inverse_hedge(lw, hedge_etf="PSQ", hedge_frac=0.25)
        assert (out >= -1e-12).all()                 # all long (incl PSQ)
        assert out.sum() == pytest.approx(1.0)        # no margin (sum=1)
        assert out["PSQ"] == pytest.approx(0.25)

    def test_hedge_etf_must_be_1x_inverse(self):
        lw = pd.Series({"AAA": 1.0})
        with pytest.raises(ValueError):
            apply_t1_inverse_hedge(lw, hedge_etf="SQQQ", hedge_frac=0.1)

    def test_hedge_etf_collision_with_existing_long_position(self):
        # if SH already held long, hedge must add onto it coherently,
        # not silently overwrite -> combined weight, still sum<=1, >=0
        lw = pd.Series({"AAA": 0.8, "SH": 0.2})
        out = apply_t1_inverse_hedge(lw, hedge_etf="SH", hedge_frac=0.10)
        assert out.sum() == pytest.approx(1.0)
        assert (out >= -1e-12).all()
        # SH = scaled existing (0.2*0.9=0.18) + hedge 0.10 = 0.28
        assert out["SH"] == pytest.approx(0.28)
        assert out["AAA"] == pytest.approx(0.72)

    def test_negative_input_weight_rejected(self):
        # T1 is invariant-preserving: a negative input weight means the
        # caller already broke long-only -> refuse (that is T2 territory)
        lw = pd.Series({"AAA": 1.2, "BBB": -0.2})
        with pytest.raises(ValueError):
            apply_t1_inverse_hedge(lw, hedge_etf="SH", hedge_frac=0.1)
