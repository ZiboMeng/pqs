"""P3 — score_to_weight mapping TDD (PRD 20260521 §4.8)."""
import numpy as np
import pandas as pd
import pytest

from core.research.allocation.score_to_weight import (
    score_panel_to_weights,
    score_to_weight,
)


def _score(**kw):
    return pd.Series(kw, dtype=float)


class TestTopKCapped:
    def test_selects_top_k_equal_weight(self):
        s = _score(A=0.9, B=0.7, C=0.5, D=0.3, E=0.1)
        w = score_to_weight(s, mode="top_k_capped", top_k=3,
                            max_single_weight=1.0)
        # top-3 = A,B,C each 1/3; D,E = 0
        assert w["A"] == pytest.approx(1 / 3)
        assert w["B"] == pytest.approx(1 / 3)
        assert w["C"] == pytest.approx(1 / 3)
        assert w["D"] == 0.0 and w["E"] == 0.0
        assert w.sum() == pytest.approx(1.0)

    def test_long_only(self):
        s = _score(A=0.9, B=0.5, C=0.1)
        w = score_to_weight(s, mode="top_k_capped", top_k=3,
                            max_single_weight=1.0)
        assert (w >= 0.0).all()

    def test_single_name_cap_enforced(self):
        s = _score(A=0.9, B=0.6)
        # top_k=2, cap 0.4 → each capped at 0.4, sum 0.8, residual cash
        w = score_to_weight(s, mode="top_k_capped", top_k=2,
                            max_single_weight=0.4)
        assert w["A"] <= 0.4 + 1e-9
        assert w["B"] <= 0.4 + 1e-9
        assert w.sum() <= 0.8 + 1e-9

    def test_all_nan_is_cash(self):
        s = pd.Series({"A": np.nan, "B": np.nan})
        w = score_to_weight(s, mode="top_k_capped", top_k=3)
        assert (w == 0.0).all()

    def test_deterministic(self):
        s = _score(A=0.9, B=0.7, C=0.5)
        a = score_to_weight(s, mode="top_k_capped", top_k=2)
        b = score_to_weight(s, mode="top_k_capped", top_k=2)
        pd.testing.assert_series_equal(a, b)


class TestScoreProportional:
    def test_higher_score_higher_weight(self):
        s = _score(A=0.9, B=0.6, C=0.3)
        w = score_to_weight(s, mode="score_proportional_clipped",
                            top_k=3, max_single_weight=1.0)
        assert w["A"] > w["B"] > w["C"] > 0.0
        assert w.sum() == pytest.approx(1.0)


class TestScoreVolScaled:
    def test_lower_vol_higher_weight(self):
        s = _score(A=0.8, B=0.8)          # equal score
        vol = _score(A=0.10, B=0.40)      # A much lower vol
        w = score_to_weight(s, mode="score_vol_scaled", top_k=2,
                            max_single_weight=1.0, vol=vol)
        assert w["A"] > w["B"]            # inverse-vol tilt

    def test_requires_vol(self):
        s = _score(A=0.8, B=0.5)
        with pytest.raises(ValueError, match="vol"):
            score_to_weight(s, mode="score_vol_scaled", top_k=2)


class TestValidationAndPanel:
    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="unknown mapping mode"):
            score_to_weight(_score(A=0.5), mode="bogus")

    def test_panel_wrapper(self):
        idx = pd.bdate_range("2020-01-01", periods=4)
        score_df = pd.DataFrame(
            np.random.default_rng(0).random((4, 5)),
            index=idx, columns=[f"S{i}" for i in range(5)])
        w = score_panel_to_weights(score_df, mode="top_k_capped",
                                   top_k=3, max_single_weight=0.5)
        assert w.shape == score_df.shape
        assert (w >= 0.0).to_numpy().all()           # long-only
        assert (w.sum(axis=1) <= 1.0 + 1e-9).all()   # ≤ fully invested
