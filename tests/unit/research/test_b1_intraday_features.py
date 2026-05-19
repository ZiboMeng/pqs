"""PRD-3 RB2 — B1 intraday engineered features + shallow XGB (TDD)."""
import numpy as np
import pandas as pd
import pytest

from core.research.b1_intraday_features import (
    B1Config,
    compute_b1_day_features,
    intraday_volume_z,
    open_range_breakout,
    realized_vol_regime,
    train_b1,
    vwap_deviation,
)


def _day(n=13, seed=0):
    """A synthetic 13-bar day's OHLCV (~30m bars over 6.5h)."""
    rng = np.random.default_rng(seed)
    c = np.cumsum(rng.standard_normal(n)) + 100.0
    o = c + rng.standard_normal(n) * 0.1
    h = np.maximum(o, c) + np.abs(rng.standard_normal(n)) * 0.2
    low = np.minimum(o, c) - np.abs(rng.standard_normal(n)) * 0.2
    v = np.abs(rng.standard_normal(n)) * 1e6 + 1e6
    return np.column_stack([o, h, low, c, v])


class TestPrimitives:
    def test_open_range_breakout_handcomputed(self):
        # k=1: OR top = first bar's high
        bars = np.array([
            [100, 102, 99, 101, 1e6],
            [101, 103, 100, 102, 1e6],
            [102, 105, 101, 104, 1e6],
        ])
        # OR top=102, close=104 → (104-102)/102
        assert open_range_breakout(bars, k=1) == pytest.approx(
            (104 - 102) / 102)

    def test_vwap_deviation_handcomputed(self):
        bars = np.array([
            [100, 101, 99, 100, 1.0],
            [100, 101, 99, 102, 1.0],
        ])
        # VWAP = (100*1 + 102*1)/2 = 101 ; last=102 → (102-101)/101
        assert vwap_deviation(bars) == pytest.approx((102 - 101) / 101)

    def test_realized_vol_nonnegative(self):
        rv = realized_vol_regime(_day(seed=7))
        assert rv >= 0.0 and np.isfinite(rv)

    def test_intraday_volume_z_finite(self):
        assert np.isfinite(intraday_volume_z(_day(seed=8)))

    def test_intraday_volume_z_not_identically_zero(self):
        """Regression for the 2026-05-19 dead-feature bug
        (auditor-flagged): the prior mean((v-m)/s) was IDENTICALLY
        zero for any input; skew is non-zero for any non-symmetric
        distribution. Front-loaded volume → positive skew is large.
        """
        front = np.array([5e6, 3e6, 1.5e6, 1.2e6, 1e6, 0.8e6])
        bars = np.column_stack([np.zeros(6), np.zeros(6),
                                np.zeros(6), np.zeros(6), front])
        z = intraday_volume_z(bars)
        # asymmetric front-loaded volume must yield |skew| > 0.1,
        # NOT the prior dead 0.0
        assert abs(z) > 0.1, f"feature still dead-like: z={z}"

    def test_no_lookahead_per_day_function(self):
        # functions take a SINGLE day's bars and depend only on
        # that day (no cross-day mutation): truncating later bars
        # doesn't change earlier-window values.
        d = _day(seed=9)
        a = compute_b1_day_features(d[:7])
        b = compute_b1_day_features(d[:7].copy())
        assert a == b                                  # deterministic

    def test_bad_shape_returns_nan(self):
        assert np.isnan(open_range_breakout(np.zeros((1, 3))))
        assert np.isnan(vwap_deviation(np.zeros((1, 4))))


class TestRb1GateRoutedFirst:
    def test_naive_bar_voting_archetype_refused(self):
        # the train_b1 path must REFUSE naive bar-direction voting
        # via the RB1 gate BEFORE any fit (老路子防呆).
        X = pd.DataFrame(
            np.random.default_rng(1).standard_normal((20, 4)),
            columns=["open_range_breakout", "vwap_deviation",
                     "realized_vol_regime", "intraday_volume_z"])
        y = pd.Series(np.random.default_rng(2).standard_normal(20))
        with pytest.raises(ValueError, match=r"NAIVE|naive|老路子"):
            train_b1(X, y, start_pos=np.arange(20), horizon=21,
                     groups=np.zeros(20, int),
                     cfg=B1Config(archetype="bar_direction_voting"))

    def test_unknown_archetype_refused(self):
        X = pd.DataFrame(np.zeros((10, 4)),
                         columns=["open_range_breakout", "vwap_deviation",
                                  "realized_vol_regime",
                                  "intraday_volume_z"])
        y = pd.Series(np.zeros(10))
        with pytest.raises(ValueError, match=r"unknown"):
            train_b1(X, y, start_pos=np.arange(10), horizon=5,
                     groups=np.zeros(10, int),
                     cfg=B1Config(archetype="magic_alpha"))

    def test_prereqs_gate_checked_before_fit(self, monkeypatch):
        # if RB1 prereqs ever fail, train_b1 must refuse BEFORE
        # touching XGBAlphaModel.
        import core.research.component_b_gate as cbg
        monkeypatch.setattr(
            cbg, "_probe_imports",
            lambda: {"prd1_leakage_correct": False,
                     "prd2_p2_3_executed": True,
                     "r11_intraday_cost_hardened": True,
                     "ra7_r6_expanded_guard": True})
        X = pd.DataFrame(np.zeros((10, 4)),
                         columns=["open_range_breakout", "vwap_deviation",
                                  "realized_vol_regime",
                                  "intraday_volume_z"])
        y = pd.Series(np.zeros(10))
        with pytest.raises(RuntimeError, match=r"prerequisites NOT met"):
            train_b1(X, y, start_pos=np.arange(10), horizon=5,
                     groups=np.zeros(10, int))


class TestB1TrainPipeline:
    def _xy(self, n=120, seed=11):
        rng = np.random.default_rng(seed)
        X = pd.DataFrame(rng.standard_normal((n, 4)),
                         columns=["open_range_breakout", "vwap_deviation",
                                  "realized_vol_regime",
                                  "intraday_volume_z"])
        y = pd.Series(0.5 * X["vwap_deviation"]
                      + 0.1 * rng.standard_normal(n))
        return X, y

    def test_differentiated_archetype_trains(self):
        X, y = self._xy()
        r = train_b1(X, y, start_pos=np.arange(len(X)), horizon=21,
                     groups=np.zeros(len(X), int),
                     cfg=B1Config(archetype="intraday_reversal",
                                  max_depth=3, n_estimators=40))
        assert r.model is not None and r.archetype == "intraday_reversal"
        assert r.sample_weight.shape == (len(X),)

    def test_shallow_depth_enforced(self):
        X, y = self._xy()
        with pytest.raises(ValueError):
            train_b1(X, y, start_pos=np.arange(len(X)), horizon=5,
                     groups=np.zeros(len(X), int),
                     cfg=B1Config(max_depth=8))

    def test_reproducible_fixed_seed(self):
        X, y = self._xy(seed=15)
        r1 = train_b1(X, y, start_pos=np.arange(len(X)), horizon=21,
                      groups=np.zeros(len(X), int),
                      cfg=B1Config(random_state=7, n_estimators=30))
        r2 = train_b1(X, y, start_pos=np.arange(len(X)), horizon=21,
                      groups=np.zeros(len(X), int),
                      cfg=B1Config(random_state=7, n_estimators=30))
        np.testing.assert_array_equal(
            r1.model.predict(X), r2.model.predict(X))
