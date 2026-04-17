"""Tests for factor_generator module."""

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    compute_forward_returns,
)


def _make_price_volume(n=500, n_syms=5):
    idx = pd.bdate_range("2020-01-01", periods=n)
    np.random.seed(42)
    prices = pd.DataFrame(
        {f"SYM{i}": 100 + np.cumsum(np.random.randn(n) * 0.5) for i in range(n_syms)},
        index=idx,
    )
    prices["SPY"] = 100 + np.cumsum(np.random.randn(n) * 0.3)
    volumes = pd.DataFrame(
        {f"SYM{i}": np.random.uniform(1e6, 5e6, n) for i in range(n_syms)},
        index=idx,
    )
    return prices, volumes


class TestGenerateAllFactors:
    def test_returns_dict(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        assert isinstance(factors, dict)
        assert len(factors) > 0

    def test_factor_count_with_volume(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        assert len(factors) >= 20

    def test_factor_count_without_volume(self):
        prices, _ = _make_price_volume()
        factors = generate_all_factors(prices)
        assert len(factors) >= 15

    def test_factor_shape_matches_price(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        for name, df in factors.items():
            assert df.index.equals(prices.index), f"{name} index mismatch"

    def test_momentum_factors_exist(self):
        prices, _ = _make_price_volume()
        factors = generate_all_factors(prices)
        assert "mom_21d" in factors
        assert "mom_252d" in factors
        assert "mom_12_1" in factors

    def test_volatility_factors_exist(self):
        prices, _ = _make_price_volume()
        factors = generate_all_factors(prices)
        assert "vol_21d" in factors
        assert "vol_63d" in factors

    def test_relative_strength_factors_exist(self):
        prices, _ = _make_price_volume()
        factors = generate_all_factors(prices)
        assert "rs_vs_spy_63d" in factors

    def test_macro_factors_exist(self):
        prices, _ = _make_price_volume()
        factors = generate_all_factors(prices)
        assert "spy_trend_200d" in factors
        assert "market_vol_ratio" in factors


class TestComputeForwardReturns:
    def test_returns_dict(self):
        prices, _ = _make_price_volume()
        fwd = compute_forward_returns(prices, [5, 10])
        assert isinstance(fwd, dict)
        assert 5 in fwd
        assert 10 in fwd

    def test_forward_return_shape(self):
        prices, _ = _make_price_volume()
        fwd = compute_forward_returns(prices, [5])
        assert fwd[5].shape == prices.shape

    def test_forward_return_is_shifted(self):
        prices, _ = _make_price_volume()
        fwd = compute_forward_returns(prices, [5])
        assert pd.isna(fwd[5].iloc[-1].iloc[0])
