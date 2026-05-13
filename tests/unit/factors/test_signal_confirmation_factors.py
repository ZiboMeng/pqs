"""Tests for signal-confirmation multi-bar factors (Round F)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.signal_confirmation_factors import (
    SIGNAL_CONFIRMATION_FACTOR_NAMES,
    compute_signal_confirmation_factors,
)
from core.signals.strategies.confirmation_pattern import (
    ConfirmationPatternConfig,
    ConfirmationPatternStrategy,
)


def _make_panel(n=200, n_syms=3, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    syms = [f"SYM{i}" for i in range(n_syms)]
    rets = rng.normal(0.0005, 0.015, size=(n, n_syms))
    close = 100.0 * np.exp(np.cumsum(rets, axis=0))
    return (
        pd.DataFrame(close, index=idx, columns=syms),
        pd.DataFrame(rng.lognormal(15, 0.5, size=(n, n_syms)), index=idx, columns=syms),
    )


class TestRegistration:
    def test_all_5_in_research_factors(self):
        for name in SIGNAL_CONFIRMATION_FACTOR_NAMES:
            assert name in RESEARCH_FACTORS


class TestFactorComputation:
    def test_factors_produced(self):
        close_df, vol_df = _make_panel()
        out = compute_signal_confirmation_factors(close_df, vol_df)
        for n in SIGNAL_CONFIRMATION_FACTOR_NAMES:
            assert n in out
            assert out[n].shape == close_df.shape

    def test_breakout_signal_age_is_capped_at_5(self):
        """Age values must be in [0, 5] or NaN — capped per definition."""
        close_df, _ = _make_panel(n=100)
        out = compute_signal_confirmation_factors(close_df)
        age = out["breakout_signal_age_5d"]
        v = age.dropna().values.flatten()
        assert (v >= 0).all() and (v <= 5).all()

    def test_retest_proximity_in_0_inf(self):
        close_df, _ = _make_panel()
        out = compute_signal_confirmation_factors(close_df)
        v = out["retest_proximity_pct"].dropna().values.flatten()
        assert (v >= 0).all()  # (close - min_5) ≥ 0 by definition

    def test_volume_required_for_3_factors(self):
        close_df, _ = _make_panel()
        out = compute_signal_confirmation_factors(close_df, volume_df=None)
        # 3 vol-conditional factors should be all-NaN
        for n in ["time_since_arm_bars", "volume_surge_ratio_at_setup"]:
            assert out[n].isna().all().all()
        # confirmation_strength is volume-independent
        assert not out["confirmation_strength"].isna().all().all()

    def test_no_lookahead(self):
        """Perturb last bar → values at t<last must be unchanged."""
        close_df, vol_df = _make_panel(n=80)
        out_base = compute_signal_confirmation_factors(close_df, vol_df)

        close_p = close_df.copy()
        close_p.iloc[-1, :] *= 2.0
        vol_p = vol_df.copy()
        vol_p.iloc[-1, :] *= 10.0
        out_pert = compute_signal_confirmation_factors(close_p, vol_p)

        for name in SIGNAL_CONFIRMATION_FACTOR_NAMES:
            base = out_base[name].iloc[:-1]
            pert = out_pert[name].iloc[:-1]
            pd.testing.assert_frame_equal(
                base, pert, check_dtype=False, obj=f"{name} leakage check",
            )


class TestStrategyClass:
    def test_strategy_class_instantiates(self):
        s = ConfirmationPatternStrategy()
        assert s.config.arm_type == "breakout_high_n"

    def test_strategy_generates_weights(self):
        close_df, vol_df = _make_panel(n=100)
        s = ConfirmationPatternStrategy(
            ConfirmationPatternConfig(
                arm_type="volume_gate_same_bar",
                confirmation_threshold_pct=0.5,
                volume_multiplier=1.0,  # permissive for synthetic data
            )
        )
        w = s.generate(close_df, vol_df)
        assert w.shape == close_df.shape
        # Weights ≥ 0 always
        assert (w.values >= 0).all()
        # Weights ≤ 1 always
        assert (w.values <= 1.0001).all()
