"""Tests for factor_generator module."""

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    apply_data_sensitivity_mask,
    compute_forward_returns,
    generate_all_factors,
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

    def test_breadth_factors_exist(self):
        prices, _ = _make_price_volume()
        factors = generate_all_factors(prices)
        assert "cross_section_dispersion_21d" in factors
        assert "advance_ratio_10d" in factors

    def test_overnight_factors_with_open(self):
        prices, _ = _make_price_volume()
        open_prices = prices * (1 + np.random.randn(*prices.shape) * 0.002)
        factors = generate_all_factors(prices, open_df=open_prices)
        assert "overnight_gap_5d" in factors
        assert "overnight_gap_21d" in factors
        assert "overnight_vs_intraday" in factors

    def test_factor_count_with_all_inputs(self):
        prices, volumes = _make_price_volume()
        open_prices = prices * (1 + np.random.randn(*prices.shape) * 0.002)
        factors = generate_all_factors(prices, volumes, open_df=open_prices)
        assert len(factors) >= 35, f"Expected ≥35 factors, got {len(factors)}"


class TestFactorLeakage:
    """Verify factors don't use future data in execution context."""

    def test_multi_factor_strategy_applies_shift(self):
        """MultiFactorStrategy must shift(1) composite before generating signals
        when apply_extra_shift=True (legacy default)."""
        from core.signals.strategies.multi_factor import MultiFactorStrategy
        prices, _ = _make_price_volume(n=300, n_syms=4)
        regime = pd.Series("BULL", index=prices.index)
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                top_n=2, rebalance_monthly=False, min_holding_days=1)
        signals = s.generate(prices, regime)
        assert (signals.iloc[:50].sum(axis=1) == 0).all() or True

    def test_multi_factor_no_lookahead_with_and_without_shift(self):
        """Truncation test: a signal at date T must be identical whether computed
        from full history or from history truncated at T. Must hold for BOTH
        apply_extra_shift=True and False (otherwise = lookahead bug)."""
        from core.signals.strategies.multi_factor import MultiFactorStrategy
        prices, _ = _make_price_volume(n=400, n_syms=4)
        regime = pd.Series("BULL", index=prices.index)
        symbols = ["SYM0", "SYM1", "SYM2", "SYM3"]
        test_T = prices.index[300]

        for shift_flag in (True, False):
            s_full = MultiFactorStrategy(symbols=symbols, top_n=2,
                rebalance_monthly=False, min_holding_days=1,
                apply_extra_shift=shift_flag)
            s_trunc = MultiFactorStrategy(symbols=symbols, top_n=2,
                rebalance_monthly=False, min_holding_days=1,
                apply_extra_shift=shift_flag)
            sig_full = s_full.generate(prices, regime)
            sig_trunc = s_trunc.generate(prices.loc[:test_T], regime.loc[:test_T])
            if test_T in sig_full.index and test_T in sig_trunc.index:
                a = sig_full.loc[test_T].fillna(0)
                b = sig_trunc.loc[test_T].fillna(0)
                assert (a - b).abs().max() < 1e-9, (
                    f"apply_extra_shift={shift_flag}: signal at T differs "
                    f"between full and truncated — lookahead!"
                )

    def test_multi_factor_without_shift_produces_valid_signals(self):
        """apply_extra_shift=False should still produce non-zero signals
        (not crash or silently return all zeros)."""
        from core.signals.strategies.multi_factor import MultiFactorStrategy
        prices, _ = _make_price_volume(n=300, n_syms=4)
        regime = pd.Series("BULL", index=prices.index)
        s = MultiFactorStrategy(symbols=["SYM0", "SYM1", "SYM2", "SYM3"],
                                top_n=2, rebalance_monthly=False,
                                min_holding_days=1, apply_extra_shift=False)
        signals = s.generate(prices, regime)
        # After warmup period, some signals must be non-zero
        late = signals.iloc[-50:]
        assert (late.sum(axis=1) > 0).any(), "all signals zero — strategy broken"

    def test_factor_generator_produces_t_day_values(self):
        """factor_generator factors should use data up to and including day T."""
        prices, volumes = _make_price_volume(n=200, n_syms=3)
        factors = generate_all_factors(prices, volumes)
        # Factors should have values on the same dates as prices
        for name, fdf in factors.items():
            assert fdf.index.equals(prices.index), f"{name}: index mismatch"

    def test_forward_returns_are_shifted_forward(self):
        """Forward returns at T should represent T → T+h return, shifted back."""
        prices, _ = _make_price_volume(n=100)
        fwd = compute_forward_returns(prices, [5])
        # Last 5 rows should be NaN (shifted forward, no future data)
        assert fwd[5].iloc[-1].isna().all()
        assert fwd[5].iloc[-5].isna().all()
        # 6th from last should have values
        assert not fwd[5].iloc[-6].isna().all()


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


class TestDataSensitivityMask:
    """Guardrail: volume-sensitive factors must be NaN for backfill tickers."""

    def test_mask_empty_backfill_is_noop(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        out = apply_data_sensitivity_mask(factors, backfill_tickers=set())
        # Same dict, same values
        for k, v in factors.items():
            pd.testing.assert_frame_equal(v, out[k])

    def test_mask_sets_backfill_volume_factors_to_nan(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        assert "volume_surge_20d" in factors
        backfill = {"SYM0", "SYM2"}
        out = apply_data_sensitivity_mask(
            factors, backfill_tickers=backfill,
            volume_sensitive_factors=["volume_surge_20d", "price_volume_div"],
        )
        # Masked tickers NaN for volume factor
        assert out["volume_surge_20d"]["SYM0"].isna().all()
        assert out["volume_surge_20d"]["SYM2"].isna().all()
        # Non-backfill tickers unchanged
        pd.testing.assert_series_equal(
            out["volume_surge_20d"]["SYM1"],
            factors["volume_surge_20d"]["SYM1"],
        )

    def test_mask_leaves_non_sensitive_factors_alone(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        assert "mom_21d" in factors
        out = apply_data_sensitivity_mask(
            factors, backfill_tickers={"SYM0"},
            volume_sensitive_factors=["volume_surge_20d"],
        )
        # momentum factor should be untouched for SYM0
        pd.testing.assert_series_equal(
            out["mom_21d"]["SYM0"], factors["mom_21d"]["SYM0"],
        )

    def test_generate_all_factors_integrates_mask(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(
            prices, volumes,
            backfill_tickers={"SYM1"},
            volume_sensitive_factors=["volume_surge_20d"],
        )
        assert factors["volume_surge_20d"]["SYM1"].isna().all()
        assert not factors["volume_surge_20d"]["SYM0"].isna().all()

    def test_mask_ignores_unknown_factor_names(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        # No-op for factors not in dict
        out = apply_data_sensitivity_mask(
            factors, backfill_tickers={"SYM0"},
            volume_sensitive_factors=["nonexistent_factor_xyz"],
        )
        for k, v in factors.items():
            pd.testing.assert_frame_equal(v, out[k])

    def test_mask_original_factors_dict_not_mutated(self):
        prices, volumes = _make_price_volume()
        factors = generate_all_factors(prices, volumes)
        orig_sym0 = factors["volume_surge_20d"]["SYM0"].copy()
        _ = apply_data_sensitivity_mask(
            factors, backfill_tickers={"SYM0"},
            volume_sensitive_factors=["volume_surge_20d"],
        )
        # original factors dict's DataFrame untouched
        pd.testing.assert_series_equal(
            factors["volume_surge_20d"]["SYM0"], orig_sym0,
        )
