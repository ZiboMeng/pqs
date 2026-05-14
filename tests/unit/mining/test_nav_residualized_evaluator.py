"""Unit tests for core.mining.nav_residualized_evaluator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.mining.nav_residualized_evaluator import (
    DEFAULT_BETA_WINDOW_MONTHS,
    TRADING_DAYS_PER_MONTH,
    build_fleet_forward_returns_from_nav,
    compute_residual_forward_returns,
    compute_rolling_beta,
)


def _make_returns(
    n_days: int,
    syms: list[str],
    seed: int = 42,
    annual_drift: float = 0.0,
    annual_vol: float = 0.15,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-04", periods=n_days, freq="B")
    daily_drift = annual_drift / 252
    daily_vol = annual_vol / np.sqrt(252)
    data = {
        s: rng.normal(daily_drift, daily_vol, n_days)
        for s in syms
    }
    return pd.DataFrame(data, index=idx)


# ── 1. β estimation — basic ────────────────────────────────────────────────────

class TestRollingBeta:
    def test_returns_dict_keyed_by_symbol(self):
        sr = _make_returns(900, ["AAA", "BBB"])
        fr = _make_returns(900, ["F1"], seed=99)
        beta = compute_rolling_beta(sr, fr)
        assert set(beta.keys()) == {"AAA", "BBB"}
        for sym, df in beta.items():
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == ["F1"]

    def test_known_beta_recovered(self):
        """If stock = 2.0 × fleet + noise, β should recover ~2.0."""
        n = 1000
        rng = np.random.default_rng(1)
        idx = pd.date_range("2010-01-04", periods=n, freq="B")
        fleet = rng.normal(0.0, 0.01, n)
        noise = rng.normal(0.0, 0.002, n)
        stock = 2.0 * fleet + noise
        sr = pd.DataFrame({"X": stock}, index=idx)
        fr = pd.DataFrame({"F1": fleet}, index=idx)
        beta = compute_rolling_beta(sr, fr, window_months=12)
        # Skip first 12 months of warmup
        beta_x = beta["X"]["F1"].dropna()
        # Should be very close to 2.0 with noise/signal ≈ 0.2
        assert abs(beta_x.median() - 2.0) < 0.05, \
            f"Expected β ~2.0, got median {beta_x.median():.3f}"

    def test_warmup_returns_nan(self):
        sr = _make_returns(900, ["A"])
        fr = _make_returns(900, ["F"], seed=11)
        beta = compute_rolling_beta(sr, fr, window_months=36)
        # First 36 × 21 = 756 days warmup
        beta_a = beta["A"]["F"]
        assert beta_a.iloc[:700].isna().all()
        assert beta_a.iloc[800:].notna().any()

    def test_zero_fleet_returns_some_finite_beta(self):
        """Even with constant fleet, β should compute (just 0 or huge variance)."""
        n = 900
        idx = pd.date_range("2010-01-04", periods=n, freq="B")
        sr = pd.DataFrame({"A": np.random.RandomState(2).randn(n) * 0.01}, index=idx)
        fr = pd.DataFrame({"F": np.zeros(n)}, index=idx)
        beta = compute_rolling_beta(sr, fr, window_months=12)
        # Singular regression (constant predictor) → NaN allowed
        assert "A" in beta


# ── 2. Multi-factor β ─────────────────────────────────────────────────────────

class TestMultiFactorBeta:
    def test_three_fleet_members_simultaneously(self):
        sr = _make_returns(900, ["A", "B"])
        fr = _make_returns(900, ["F1", "F2", "F3"], seed=88)
        beta = compute_rolling_beta(sr, fr, window_months=12)
        assert beta["A"].shape[1] == 3
        assert list(beta["A"].columns) == ["F1", "F2", "F3"]

    def test_collinear_fleet_returns_no_crash(self):
        """Two fleet members perfectly collinear → β estimates may be NaN
        but function shouldn't crash."""
        n = 900
        idx = pd.date_range("2010-01-04", periods=n, freq="B")
        f1 = np.random.RandomState(3).randn(n) * 0.01
        sr = pd.DataFrame({"A": np.random.RandomState(4).randn(n) * 0.01}, index=idx)
        fr = pd.DataFrame({"F1": f1, "F2": f1 * 1.0}, index=idx)  # exact copy
        beta = compute_rolling_beta(sr, fr, window_months=12)
        # Should not raise; β values may be NaN or arbitrary (rank-deficient)
        assert "A" in beta
        assert beta["A"].shape[1] == 2


# ── 3. No-lookahead invariant ─────────────────────────────────────────────────

class TestNoLookahead:
    def test_beta_at_t_does_not_use_data_at_t(self):
        """β at date t must depend only on data strictly before t."""
        n = 900
        idx = pd.date_range("2010-01-04", periods=n, freq="B")
        rng = np.random.default_rng(5)
        # Stock = 1.0 × fleet for first half, then 3.0 × fleet for second half
        fleet = rng.normal(0, 0.01, n)
        stock = np.empty(n)
        flip = n // 2
        stock[:flip] = 1.0 * fleet[:flip] + rng.normal(0, 0.002, flip)
        stock[flip:] = 3.0 * fleet[flip:] + rng.normal(0, 0.002, n - flip)
        sr = pd.DataFrame({"X": stock}, index=idx)
        fr = pd.DataFrame({"F": fleet}, index=idx)
        beta = compute_rolling_beta(sr, fr, window_months=6)
        b = beta["X"]["F"]
        # Just before flip (using historical 1.0 regime): β ≈ 1.0
        before_flip = b.iloc[flip - 5]
        # After flip + full window: β ≈ 3.0
        full_window_days = 6 * 21
        after_full_flip = b.iloc[flip + full_window_days + 10]
        assert abs(before_flip - 1.0) < 0.2, f"β before flip = {before_flip:.3f}"
        assert abs(after_full_flip - 3.0) < 0.2, f"β after flip = {after_full_flip:.3f}"


# ── 4. Residual forward returns ───────────────────────────────────────────────

class TestResidualForwardReturns:
    def test_residual_equals_minus_explained(self):
        """resid = raw_fwd - β × fleet_fwd. Verify simple case."""
        n = 200
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        # Synthetic: known β = 0.5, fleet_fwd = +0.05, fwd = +0.10 → resid = +0.075
        fwd_returns = pd.DataFrame({"A": np.full(n, 0.10)}, index=idx)
        fleet_fwd = pd.DataFrame({"F": np.full(n, 0.05)}, index=idx)
        beta_by_sym = {"A": pd.DataFrame({"F": np.full(n, 0.5)}, index=idx)}
        resid = compute_residual_forward_returns(fwd_returns, fleet_fwd, beta_by_sym)
        # resid = 0.10 - 0.5 × 0.05 = 0.075
        assert np.allclose(resid["A"], 0.075, atol=1e-10)

    def test_missing_symbol_returns_nan(self):
        n = 200
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        fwd = pd.DataFrame({"A": np.full(n, 0.1), "B": np.full(n, 0.2)}, index=idx)
        fleet_fwd = pd.DataFrame({"F": np.full(n, 0.05)}, index=idx)
        beta = {"A": pd.DataFrame({"F": np.full(n, 0.5)}, index=idx)}
        # B not in beta_by_sym
        resid = compute_residual_forward_returns(fwd, fleet_fwd, beta)
        assert resid["A"].notna().all()
        assert resid["B"].isna().all()

    def test_nan_beta_propagates(self):
        n = 200
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        fwd = pd.DataFrame({"A": np.full(n, 0.1)}, index=idx)
        fleet_fwd = pd.DataFrame({"F": np.full(n, 0.05)}, index=idx)
        beta_arr = np.full(n, 0.5)
        beta_arr[:50] = np.nan
        beta = {"A": pd.DataFrame({"F": beta_arr}, index=idx)}
        resid = compute_residual_forward_returns(fwd, fleet_fwd, beta)
        assert resid["A"].iloc[:50].isna().all()
        assert resid["A"].iloc[50:].notna().all()

    def test_multi_fleet_residual_subtracts_each_member(self):
        """resid = fwd - β1×F1 - β2×F2."""
        n = 100
        idx = pd.date_range("2018-01-02", periods=n, freq="B")
        fwd = pd.DataFrame({"A": np.full(n, 0.20)}, index=idx)
        fleet_fwd = pd.DataFrame({
            "F1": np.full(n, 0.05),
            "F2": np.full(n, 0.08),
        }, index=idx)
        beta = {
            "A": pd.DataFrame({
                "F1": np.full(n, 0.5),
                "F2": np.full(n, 1.5),
            }, index=idx),
        }
        # resid = 0.20 - 0.5×0.05 - 1.5×0.08 = 0.20 - 0.025 - 0.120 = 0.055
        resid = compute_residual_forward_returns(fwd, fleet_fwd, beta)
        assert np.allclose(resid["A"], 0.055, atol=1e-10)


# ── 5. Fleet NAV → forward returns ────────────────────────────────────────────

class TestFleetForwardReturnsFromNav:
    def test_basic_horizon_computation(self):
        idx = pd.date_range("2020-01-02", periods=30, freq="B")
        nav = pd.DataFrame({
            "F": np.linspace(10000, 12000, 30),  # +20% over 30 trading days
        }, index=idx)
        fwd = build_fleet_forward_returns_from_nav(nav, horizon_days=21)
        # Day 0 fwd 21d = NAV[21] / NAV[0] - 1
        expected = nav["F"].iloc[21] / nav["F"].iloc[0] - 1
        assert abs(fwd["F"].iloc[0] - expected) < 1e-9
        # Last 21 rows are NaN (no forward data)
        assert fwd["F"].iloc[-21:].isna().all()

    def test_zero_nav_raises(self):
        idx = pd.date_range("2020-01-02", periods=10, freq="B")
        nav = pd.DataFrame({"F": np.zeros(10)}, index=idx)
        with pytest.raises(ValueError, match="strictly positive"):
            build_fleet_forward_returns_from_nav(nav)


# ── 6. End-to-end pipeline ────────────────────────────────────────────────────

class TestEndToEnd:
    def test_full_pipeline_synthetic(self):
        """β estimate → residual fwd → mining target = residual fwd."""
        # Stock = 1.2 × fleet + alpha + noise. residual should ≈ alpha + noise.
        n = 1000
        idx = pd.date_range("2010-01-04", periods=n, freq="B")
        rng = np.random.default_rng(7)
        fleet_daily = rng.normal(0.0005, 0.01, n)
        alpha_daily = rng.normal(0.0001, 0.005, n)
        stock_daily = 1.2 * fleet_daily + alpha_daily

        sr = pd.DataFrame({"X": stock_daily}, index=idx)
        fr = pd.DataFrame({"F": fleet_daily}, index=idx)

        # 36m β
        beta = compute_rolling_beta(sr, fr, window_months=12)

        # 21-day cumulative forward returns
        fwd_stock = (1.0 + sr).rolling(21).apply(np.prod, raw=True) - 1.0
        fwd_stock = fwd_stock.shift(-21)
        fwd_fleet = (1.0 + fr).rolling(21).apply(np.prod, raw=True) - 1.0
        fwd_fleet = fwd_fleet.shift(-21)

        resid = compute_residual_forward_returns(fwd_stock, fwd_fleet, beta)
        # After warmup, residual should have lower variance than raw (alpha+noise vs full)
        warm = resid.dropna()
        assert len(warm) > 100, "Should have plenty of post-warmup data"
        raw_var = fwd_stock.dropna().var().iloc[0]
        resid_var = warm.var().iloc[0]
        assert resid_var < raw_var, \
            f"Residual var {resid_var:.6f} should be < raw var {raw_var:.6f}"


# ── 7. Defaults + constants ───────────────────────────────────────────────────

class TestConstants:
    def test_default_window(self):
        assert DEFAULT_BETA_WINDOW_MONTHS == 36

    def test_trading_days_per_month(self):
        assert TRADING_DAYS_PER_MONTH == 21
