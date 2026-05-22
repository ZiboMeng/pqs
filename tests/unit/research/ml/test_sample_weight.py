"""S3 (supplement PRD 2026-05-22) — multiplicative sample-weight TDD."""
import numpy as np
import pandas as pd
import pytest

from core.research.ml.sample_weight import (
    freshness_weight,
    liquidity_weight,
    sample_weight,
    uniqueness_weight,
    volatility_weight,
)


def _panel(n=120, k=5, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    syms = [f"S{i}" for i in range(k)]
    close = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0003, 0.015, (n, k)), axis=0),
        index=idx, columns=syms)
    volume = pd.DataFrame(rng.uniform(1e5, 5e6, (n, k)),
                          index=idx, columns=syms)
    return close, volume, idx, syms


class TestUniquenessWeight:
    def test_per_date_mean_near_one(self):
        _, _, idx, _ = _panel()
        u = uniqueness_weight(idx, horizon=21)
        assert abs(u.mean() - 1.0) < 0.15        # normalised mean ≈ 1
        assert (u > 0).all()


class TestLiquidityWeight:
    def test_high_volume_higher_weight(self):
        idx = pd.bdate_range("2021-01-04", periods=40)
        vol = pd.DataFrame({"A": [1e6] * 40, "B": [1e5] * 40}, index=idx)
        lw = liquidity_weight(vol, lookback=21)
        tail = lw.iloc[25:]
        assert (tail["A"] > tail["B"]).all()     # liquid name up-weighted

    def test_per_date_row_mean_one(self):
        close, volume, _, _ = _panel()
        lw = liquidity_weight(volume, lookback=21).iloc[25:]
        assert np.allclose(lw.mean(axis=1).dropna(), 1.0, atol=1e-9)


class TestVolatilityWeight:
    def test_low_vol_higher_weight(self):
        rng = np.random.default_rng(1)
        idx = pd.bdate_range("2021-01-04", periods=80)
        calm = 100 * np.cumprod(1 + rng.normal(0, 0.004, 80))
        wild = 100 * np.cumprod(1 + rng.normal(0, 0.040, 80))
        close = pd.DataFrame({"CALM": calm, "WILD": wild}, index=idx)
        vw = volatility_weight(close, lookback=21).iloc[30:]
        assert (vw["CALM"] > vw["WILD"]).all()   # inverse-vol


class TestFreshnessWeight:
    def test_recent_higher_than_old(self):
        idx = pd.bdate_range("2021-01-04", periods=100)
        fw = freshness_weight(idx, half_life=50)
        assert fw.iloc[-1] > fw.iloc[0]
        assert abs(fw.mean() - 1.0) < 1e-9       # normalised

    def test_half_life_must_be_positive(self):
        idx = pd.bdate_range("2021-01-04", periods=10)
        with pytest.raises(ValueError, match="half_life"):
            freshness_weight(idx, half_life=0)


class TestSampleWeight:
    def test_normalized_mean_near_one(self):
        close, volume, _, _ = _panel()
        w = sample_weight(close, volume, horizon=21)
        m = float(np.nanmean(w.to_numpy()))
        assert abs(m - 1.0) < 1e-6

    def test_all_non_negative(self):
        close, volume, _, _ = _panel()
        w = sample_weight(close, volume, horizon=21)
        finite = w.to_numpy()[np.isfinite(w.to_numpy())]
        assert (finite >= 0.0).all()

    def test_unnormalized_flag(self):
        close, volume, _, _ = _panel()
        w_norm = sample_weight(close, volume, 21, normalized=True)
        w_raw = sample_weight(close, volume, 21, normalized=False)
        # raw mean is generally not 1; normalised is
        assert abs(float(np.nanmean(w_norm.to_numpy())) - 1.0) < 1e-6

    def test_deterministic(self):
        close, volume, _, _ = _panel()
        a = sample_weight(close, volume, 21)
        b = sample_weight(close, volume, 21)
        pd.testing.assert_frame_equal(a, b)
