"""PRD-2 P2.1 R2-b — construction-tier signal overlay + HarnessConfig routing.

apply_tier_overlay = the single hook evaluate_composite_spec calls after
signals are built. T0 MUST be the identity (bit-identical to the
pre-tier path). T1 overlays the 1x inverse-ETF hedge per rebalance row.
T2 permanently gated. HarnessConfig: T1 no longer raises (R1 stub
flipped) given valid hedge params; bad hedge params rejected; T2 stays
ValueError-gated.
"""
import numpy as np
import pandas as pd
import pytest

from core.research.construction_tiers import apply_tier_overlay
from core.research.harness.composite_evaluator import HarnessConfig


def _sig():
    # 3 rebalance dates x 2 names; one all-zero (no-trade) row
    idx = pd.to_datetime(["2020-01-31", "2020-02-28", "2020-03-31"])
    return pd.DataFrame(
        {"AAA": [0.6, 0.0, 0.5], "BBB": [0.4, 0.0, 0.5]}, index=idx)


class TestApplyTierOverlay:
    def test_T0_is_identity_bit_identical(self):
        s = _sig()
        out = apply_tier_overlay(s, "T0", "SH", 0.0)
        pd.testing.assert_frame_equal(out, s)
        # identity must not even copy-mutate dtypes/order
        assert list(out.columns) == list(s.columns)

    def test_T1_zero_frac_is_identity(self):
        s = _sig()
        out = apply_tier_overlay(s, "T1", "SH", 0.0)
        pd.testing.assert_frame_equal(out[s.columns], s)

    def test_T1_overlay_hedges_nonzero_rows_only(self):
        s = _sig()
        out = apply_tier_overlay(s, "T1", "SH", 0.20)
        assert "SH" in out.columns
        # row 0: 0.6/0.4 -> 0.48/0.32 + SH 0.20 ; sum preserved =1
        assert out.loc[s.index[0], "AAA"] == pytest.approx(0.48)
        assert out.loc[s.index[0], "BBB"] == pytest.approx(0.32)
        assert out.loc[s.index[0], "SH"] == pytest.approx(0.20)
        assert out.loc[s.index[0]].sum() == pytest.approx(1.0)
        # row 1: all-zero (no trade) -> untouched, no hedge injected
        assert out.loc[s.index[1]].abs().sum() == pytest.approx(0.0)
        # all weights >= 0 (invariant preserved)
        assert (out.values >= -1e-12).all()

    def test_T2_permanently_gated(self):
        with pytest.raises((ValueError, NotImplementedError)):
            apply_tier_overlay(_sig(), "T2", "SH", 0.0)


class TestHarnessConfigT1Routing:
    def _cfg(self, **kw):
        base = dict(construction_mode="global_top_n", top_n=10)
        base.update(kw)
        return HarnessConfig(**base)

    def test_T1_valid_no_longer_raises(self):
        c = self._cfg(construction_tier="T1", hedge_etf="PSQ",
                      hedge_frac=0.15)
        assert c.construction_tier == "T1"
        assert c.hedge_etf == "PSQ"
        assert c.hedge_frac == pytest.approx(0.15)

    def test_T1_default_hedge_params(self):
        c = self._cfg(construction_tier="T1")
        assert c.hedge_etf == "SH" and c.hedge_frac == 0.0  # == T0 effect

    def test_T1_bad_hedge_etf_rejected(self):
        with pytest.raises(ValueError):
            self._cfg(construction_tier="T1", hedge_etf="SQQQ")

    def test_T1_hedge_frac_out_of_bounds_rejected(self):
        with pytest.raises(ValueError):
            self._cfg(construction_tier="T1", hedge_frac=0.9)  # > cap

    def test_T2_still_permanently_gated(self):
        with pytest.raises((ValueError, NotImplementedError)):
            self._cfg(construction_tier="T2")

    def test_T0_default_unaffected(self):
        c = self._cfg()
        assert c.construction_tier == "T0"
