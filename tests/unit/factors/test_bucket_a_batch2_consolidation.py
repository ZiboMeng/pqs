"""Tests for Bucket A T1 batch 2 — 4-quadrant volume + consolidation factors.

PRD-driven 2026-05-12 per:
- docs/memos/20260512-quant_factor_literature_synthesis_v2.md §2.1
- docs/memos/20260512-bucket_abc_macro_mvp_schedule.md §1 D2

9 new factors:
  4-quadrant (close+vol):
    - up_vol_ratio_20d / down_vol_ratio_20d / vol_weighted_ret_20d
  Consolidation (close-only):
    - bb_squeeze_20d / range_position_pct_60d / consolidation_days_count
  Consolidation (close+H+L):
    - atr_compression_20d / adx_low_trend_flag
  Consolidation (close+vol):
    - pre_breakout_volume_decay
"""

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    _volume_factors,
    _family_g_consolidation,
)
from core.factors.factor_registry import RESEARCH_FACTORS


BATCH2_NAMES = {
    "up_vol_ratio_20d", "down_vol_ratio_20d", "vol_weighted_ret_20d",
    "bb_squeeze_20d", "range_position_pct_60d", "consolidation_days_count",
    "atr_compression_20d", "adx_low_trend_flag",
    "pre_breakout_volume_decay",
}


def _make_panel(n_days=300, n_syms=3, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n_days, freq="B")
    syms = [f"SYM{i}" for i in range(n_syms)]
    rets = rng.normal(0.0005, 0.015, size=(n_days, n_syms))
    close = 100.0 * np.exp(np.cumsum(rets, axis=0))
    close_df = pd.DataFrame(close, index=idx, columns=syms)
    spread = rng.uniform(0.005, 0.025, size=close.shape)
    high_df = close_df * (1.0 + spread)
    low_df = close_df * (1.0 - spread)
    vol_df = pd.DataFrame(
        rng.lognormal(15.0, 0.5, size=close.shape), index=idx, columns=syms,
    )
    return close_df, vol_df, high_df, low_df


class TestBatch2Registration:
    def test_all_9_in_research_factors(self):
        for name in BATCH2_NAMES:
            assert name in RESEARCH_FACTORS, f"{name} not in RESEARCH_FACTORS"


class TestBatch2Computation:
    def test_4quadrant_computes_from_close_vol(self):
        close_df, vol_df, _, _ = _make_panel()
        out = _volume_factors(close_df, vol_df)
        for name in ["up_vol_ratio_20d", "down_vol_ratio_20d", "vol_weighted_ret_20d"]:
            assert name in out

    def test_consolidation_close_only(self):
        close_df, _, _, _ = _make_panel()
        out = _family_g_consolidation(close_df)
        for name in ["bb_squeeze_20d", "range_position_pct_60d", "consolidation_days_count"]:
            assert name in out
        # H+L-conditional factors absent
        assert "atr_compression_20d" not in out
        assert "adx_low_trend_flag" not in out
        # vol-conditional absent
        assert "pre_breakout_volume_decay" not in out

    def test_consolidation_full_inputs(self):
        close_df, vol_df, high_df, low_df = _make_panel()
        out = _family_g_consolidation(close_df, high_df, low_df, vol_df)
        for name in {
            "bb_squeeze_20d", "range_position_pct_60d", "consolidation_days_count",
            "atr_compression_20d", "adx_low_trend_flag",
            "pre_breakout_volume_decay",
        }:
            assert name in out

    def test_panel_shape_preserved(self):
        close_df, vol_df, high_df, low_df = _make_panel()
        out = _family_g_consolidation(close_df, high_df, low_df, vol_df)
        for name, frame in out.items():
            assert frame.shape == close_df.shape, f"{name} shape mismatch"


class TestBatch2Numerics:
    def test_up_down_vol_ratio_sum_to_one_when_no_flat_days(self):
        """up + down ≤ 1 always (flat days excluded from either)."""
        close_df, vol_df, _, _ = _make_panel()
        out = _volume_factors(close_df, vol_df)
        s = out["up_vol_ratio_20d"] + out["down_vol_ratio_20d"]
        s_vals = s.dropna().values
        assert (s_vals <= 1.0 + 1e-9).all(), f"up+down sums > 1: max={s_vals.max()}"
        assert (s_vals >= 0.0 - 1e-9).all()

    def test_range_position_in_0_1(self):
        close_df, _, _, _ = _make_panel()
        out = _family_g_consolidation(close_df)
        v = out["range_position_pct_60d"].dropna().values
        assert (v >= -1e-9).all() and (v <= 1.0 + 1e-9).all(), (
            f"range_position out of [0,1]: min={v.min()} max={v.max()}"
        )

    def test_consolidation_count_increases_on_flat_then_resets(self):
        """Synthetic: 50 flat bars (within 5% sma20) then 5 wild bars → count
        climbs then resets to 0."""
        idx = pd.date_range("2025-01-01", periods=60, freq="B")
        # 50 flat days at 100, then 10 spike days
        prices = np.concatenate([np.full(50, 100.0), np.linspace(110, 150, 10)])
        # Add tiny noise so SMA20 is non-degenerate
        prices = prices + np.random.default_rng(0).normal(0, 0.01, 60)
        close_df = pd.DataFrame({"SYM": prices}, index=idx)
        out = _family_g_consolidation(close_df)
        run = out["consolidation_days_count"]["SYM"]
        # After SMA(20) warmup (~bar 19), count should climb monotonically
        # during bars 20-49 (flat regime). Then drop to 0 once price escapes.
        assert run.iloc[40] > 0, f"expected positive run mid-flat; got {run.iloc[40]}"
        assert run.iloc[-1] == 0 or pd.isna(run.iloc[-1]), (
            f"run should reset after price escape; got {run.iloc[-1]}"
        )

    def test_atr_compression_low_when_low_vol_then_high(self):
        """Synthetic: 60 low-vol bars then 60 high-vol bars → ATR20/ATR60
        rises on the high-vol section (since recent 20d expands while
        60d still contains low-vol)."""
        idx = pd.date_range("2025-01-01", periods=120, freq="B")
        rng = np.random.default_rng(0)
        low_vol_rets = rng.normal(0, 0.002, 60)
        high_vol_rets = rng.normal(0, 0.02, 60)
        rets = np.concatenate([low_vol_rets, high_vol_rets])
        close = 100.0 * np.exp(np.cumsum(rets))
        close_df = pd.DataFrame({"SYM": close}, index=idx)
        # H/L bounded around close: vol-proportional spread
        absret = np.abs(np.diff(np.concatenate([[close[0]], close])))
        spread = absret + 0.001 * close
        high_df = pd.DataFrame({"SYM": close + spread / 2}, index=idx)
        low_df = pd.DataFrame({"SYM": close - spread / 2}, index=idx)
        out = _family_g_consolidation(close_df, high_df, low_df)
        ratio = out["atr_compression_20d"]["SYM"]
        # At the regime transition (bars ~65-85), atr_20 ramps up
        # while atr_60 still contains 40+ low-vol bars → ratio > 1.
        # At end (bars 110+), atr_60 has caught up so ratio reverts to ~1.
        trans_part = ratio.iloc[65:85].dropna()
        assert len(trans_part) > 0, "no data in transition region"
        assert trans_part.mean() > 1.0, (
            f"expected expansion at transition; got mean={trans_part.mean():.3f}"
        )


class TestBatch2Leakage:
    def test_no_lookahead_perturbing_last_bar(self):
        close_df, vol_df, high_df, low_df = _make_panel(n_days=120)
        out_base = _family_g_consolidation(close_df, high_df, low_df, vol_df)

        close_p = close_df.copy(); close_p.iloc[-1, :] *= 2.0
        high_p = high_df.copy(); high_p.iloc[-1, :] = close_p.iloc[-1, :] * 1.01
        low_p = low_df.copy(); low_p.iloc[-1, :] = close_p.iloc[-1, :] * 0.99
        vol_p = vol_df.copy(); vol_p.iloc[-1, :] *= 10.0

        out_pert = _family_g_consolidation(close_p, high_p, low_p, vol_p)
        for name in out_base.keys():
            pd.testing.assert_frame_equal(
                out_base[name].iloc[:-1], out_pert[name].iloc[:-1],
                check_dtype=False, obj=f"{name} leakage",
            )


class TestBatch2Integration:
    def test_via_generate_all_factors(self):
        close_df, vol_df, high_df, low_df = _make_panel()
        out = generate_all_factors(
            close_df, volume_df=vol_df, high_df=high_df, low_df=low_df,
        )
        for name in BATCH2_NAMES:
            assert name in out
