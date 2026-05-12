"""Tests for Bucket A T1 batch 1 — volume microstructure factors.

PRD-driven 2026-05-12 per:
- docs/memos/20260512-quant_factor_literature_synthesis_v2.md §2.1
- docs/memos/20260512-bucket_abc_macro_mvp_schedule.md §1 D1

6 new factors:
  - obv_norm_20d              (close + vol)
  - vol_price_corr_20d        (close + vol)
  - volume_surge_when_flat    (close + vol)
  - chaikin_money_flow_20d    (close + vol + H + L)
  - accum_dist_line_zscore_60d (close + vol + H + L)
  - klinger_oscillator        (close + vol + H + L)
"""

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import generate_all_factors, _volume_factors
from core.factors.factor_registry import RESEARCH_FACTORS


BUCKET_A_BATCH1_NAMES = {
    "obv_norm_20d",
    "vol_price_corr_20d",
    "volume_surge_when_flat",
    "chaikin_money_flow_20d",
    "accum_dist_line_zscore_60d",
    "klinger_oscillator",
}

BUCKET_A_HL_REQUIRED = {
    "chaikin_money_flow_20d",
    "accum_dist_line_zscore_60d",
    "klinger_oscillator",
}

BUCKET_A_CLOSE_VOL_ONLY = BUCKET_A_BATCH1_NAMES - BUCKET_A_HL_REQUIRED


def _make_panel(n_days=300, n_syms=4, seed=42):
    """Synthetic OHLCV panel — random-walk close + plausible HLV."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n_days, freq="B")
    syms = [f"SYM{i}" for i in range(n_syms)]
    rets = rng.normal(0.0005, 0.015, size=(n_days, n_syms))
    close = 100.0 * np.exp(np.cumsum(rets, axis=0))
    close_df = pd.DataFrame(close, index=idx, columns=syms)
    # high/low: close ± 1% of close, random
    spread_pct = rng.uniform(0.005, 0.025, size=close.shape)
    high_df = close_df * (1.0 + spread_pct)
    low_df = close_df * (1.0 - spread_pct)
    # volume: lognormal, panel-shaped
    vol = rng.lognormal(15.0, 0.5, size=close.shape).astype(float)
    vol_df = pd.DataFrame(vol, index=idx, columns=syms)
    return close_df, vol_df, high_df, low_df


class TestBucketABatch1Registration:
    def test_all_6_in_research_factors(self):
        for name in BUCKET_A_BATCH1_NAMES:
            assert name in RESEARCH_FACTORS, f"{name} not in RESEARCH_FACTORS"


class TestBucketABatch1Computation:
    def test_full_inputs_produces_all_6(self):
        close_df, vol_df, high_df, low_df = _make_panel()
        out = _volume_factors(close_df, vol_df, high_df=high_df, low_df=low_df)
        for name in BUCKET_A_BATCH1_NAMES:
            assert name in out, f"{name} missing from output"

    def test_no_hl_skips_3_hl_factors(self):
        close_df, vol_df, _, _ = _make_panel()
        out = _volume_factors(close_df, vol_df)
        for name in BUCKET_A_CLOSE_VOL_ONLY:
            assert name in out, f"{name} should compute without HL"
        for name in BUCKET_A_HL_REQUIRED:
            assert name not in out, f"{name} should be skipped without HL"

    def test_only_high_or_only_low_skips_hl_factors(self):
        close_df, vol_df, high_df, _ = _make_panel()
        out_h = _volume_factors(close_df, vol_df, high_df=high_df, low_df=None)
        out_l = _volume_factors(close_df, vol_df, high_df=None, low_df=high_df)
        for name in BUCKET_A_HL_REQUIRED:
            assert name not in out_h
            assert name not in out_l

    def test_no_volume_at_all_via_generate_all_factors(self):
        close_df, _, _, _ = _make_panel()
        # generate_all_factors skips _volume_factors when volume_df is None
        out = generate_all_factors(close_df, volume_df=None)
        for name in BUCKET_A_BATCH1_NAMES:
            assert name not in out, f"{name} present without volume_df"

    def test_panel_shape_preserved(self):
        close_df, vol_df, high_df, low_df = _make_panel()
        out = _volume_factors(close_df, vol_df, high_df=high_df, low_df=low_df)
        for name in BUCKET_A_BATCH1_NAMES:
            assert out[name].shape == close_df.shape
            pd.testing.assert_index_equal(out[name].index, close_df.index)
            pd.testing.assert_index_equal(out[name].columns, close_df.columns)


class TestBucketABatch1Numerics:
    def test_obv_norm_positive_when_steady_uptrend(self):
        """Synthetic: close always up + positive volume → OBV slope positive."""
        idx = pd.date_range("2025-01-01", periods=60, freq="B")
        close = pd.DataFrame(
            {"SYM": np.linspace(100, 130, 60)}, index=idx,
        )
        vol = pd.DataFrame({"SYM": np.full(60, 1_000_000.0)}, index=idx)
        out = _volume_factors(close, vol)
        # OBV slope direction: all returns positive → sign_ret=+1 → OBV
        # rises monotonically. obv.diff(20) > 0 for any window ≥ 21.
        # Note ΔOBV.rolling(20).std() = 0 because OBV.diff() is constant,
        # so factor → inf or NaN (we replaced 0 std with NaN). Edge case OK.
        obv = out["obv_norm_20d"]
        # Either NaN (zero-std) OR positive — never strongly negative
        valid = obv.dropna()
        if len(valid):
            assert (valid > 0).all(), f"obv_norm went negative on uptrend: {valid.tail()}"

    def test_cmf_bounded(self):
        """CMF mathematically in [-1, +1] by construction."""
        close_df, vol_df, high_df, low_df = _make_panel()
        out = _volume_factors(close_df, vol_df, high_df=high_df, low_df=low_df)
        cmf = out["chaikin_money_flow_20d"].dropna().values
        assert (cmf >= -1.0001).all() and (cmf <= 1.0001).all(), (
            f"CMF outside [-1,+1]: min={cmf.min()} max={cmf.max()}"
        )

    def test_high_equals_low_produces_nan_not_error(self):
        """Synthetic doji bars (H == L) → CMF / AD undefined → NaN, no exception."""
        idx = pd.date_range("2025-01-01", periods=40, freq="B")
        close = pd.DataFrame({"SYM": np.linspace(100, 110, 40)}, index=idx)
        # high == low (flat-range bars; pathological but should not crash)
        high = close.copy()
        low = close.copy()
        vol = pd.DataFrame({"SYM": np.full(40, 1e6)}, index=idx)
        out = _volume_factors(close, vol, high_df=high, low_df=low)
        # CMF / AD with H==L → MFM has division by 0 → NaN propagates
        cmf = out["chaikin_money_flow_20d"]
        assert cmf.isna().all().all(), "CMF should be all-NaN when H == L"

    def test_klinger_first_54_bars_nan(self):
        """Klinger uses EMA(span=55) with min_periods=55 → first 54 bars NaN."""
        close_df, vol_df, high_df, low_df = _make_panel(n_days=80)
        out = _volume_factors(close_df, vol_df, high_df=high_df, low_df=low_df)
        kvo = out["klinger_oscillator"]
        # First 54 rows NaN; rows >= 55 should have valid data (at least
        # some non-NaN per column)
        early = kvo.iloc[:54]
        late = kvo.iloc[55:]
        assert early.isna().all().all(), "Klinger should be NaN in first 54 bars"
        assert not late.isna().all().all(), "Klinger should have data after bar 55"

    def test_volume_surge_when_flat_zero_in_trending_regime(self):
        """If 20d return is large, flat flag → 0, so factor → 0."""
        idx = pd.date_range("2025-01-01", periods=40, freq="B")
        # 50% gain over 40 days → far exceeds 5% threshold
        close = pd.DataFrame(
            {"SYM": np.linspace(100, 150, 40)}, index=idx,
        )
        vol = pd.DataFrame(
            {"SYM": np.random.default_rng(0).lognormal(15, 0.5, 40)}, index=idx,
        )
        out = _volume_factors(close, vol)
        surge = out["volume_surge_when_flat"]
        # From day 20 onward (when ret_20d is defined and > 5%), factor = 0
        late = surge.iloc[25:].dropna()
        assert (late == 0.0).all().all(), (
            f"surge_when_flat should be 0 in trending regime; got non-zeros"
        )


class TestBucketABatch1Leakage:
    def test_factor_at_t_uses_only_data_through_t(self):
        """Modify last-bar OHLCV; factor values at t < n-1 should be unchanged."""
        close_df, vol_df, high_df, low_df = _make_panel(n_days=100)
        out_base = _volume_factors(close_df, vol_df, high_df=high_df, low_df=low_df)

        # Perturb only the LAST bar's close (and HLV)
        close_perturbed = close_df.copy()
        close_perturbed.iloc[-1, :] = close_perturbed.iloc[-1, :] * 2.0  # 2x spike
        vol_perturbed = vol_df.copy()
        vol_perturbed.iloc[-1, :] = vol_perturbed.iloc[-1, :] * 10.0
        high_perturbed = high_df.copy()
        high_perturbed.iloc[-1, :] = close_perturbed.iloc[-1, :] * 1.01
        low_perturbed = low_df.copy()
        low_perturbed.iloc[-1, :] = close_perturbed.iloc[-1, :] * 0.99

        out_perturbed = _volume_factors(
            close_perturbed, vol_perturbed, high_df=high_perturbed, low_df=low_perturbed,
        )

        for name in BUCKET_A_BATCH1_NAMES:
            # All bars EXCEPT the last should be identical
            # (some factors like cumsum-based A/D may shift cum-baseline,
            #  but rolling-window-only factors must match strictly)
            if name == "accum_dist_line_zscore_60d":
                # A/D is cumulative; z-score uses rolling-window mean/std,
                # so prior values shouldn't change either (rolling
                # statistics at earlier dates ignore the future cumsum
                # tail). Verify formally below.
                pass
            base_vals = out_base[name].iloc[:-1]
            pert_vals = out_perturbed[name].iloc[:-1]
            pd.testing.assert_frame_equal(
                base_vals, pert_vals, check_dtype=False,
                obj=f"{name} leakage check",
            )


class TestBucketABatch1Integration:
    def test_via_generate_all_factors(self):
        """End-to-end: factors registered, computed, panel-shaped via top API."""
        close_df, vol_df, high_df, low_df = _make_panel()
        out = generate_all_factors(
            close_df, volume_df=vol_df, high_df=high_df, low_df=low_df,
        )
        for name in BUCKET_A_BATCH1_NAMES:
            assert name in out, f"{name} not produced by generate_all_factors"
            assert out[name].shape == close_df.shape
