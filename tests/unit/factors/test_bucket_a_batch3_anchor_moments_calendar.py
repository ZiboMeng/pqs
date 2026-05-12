"""Tests for Bucket A T1 batch 3 — anchor + reversal + BAB + higher moments + calendar.

PRD-driven 2026-05-12 per:
- docs/memos/20260512-quant_factor_literature_synthesis_v2.md §2.1 + §7.8/9
- docs/memos/20260512-bucket_abc_macro_mvp_schedule.md §1 D3

9 new factors:
  Anchor + reversal + BAB: nearness_to_52w_high / weekly_reversal_signal_5d / bab_score_60d
  Higher moments: coskew_60d_spy / cokurt_60d_spy / idiosyncratic_skew_60d
  Calendar: turn_of_month_flag / sell_in_may_seasonal / month_end_quarter_end
"""

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    _family_h_higher_moments,
    _family_i_anchor_bab,
    _family_j_calendar,
)
from core.factors.factor_registry import RESEARCH_FACTORS


BATCH3_NAMES = {
    "coskew_60d_spy", "cokurt_60d_spy", "idiosyncratic_skew_60d",
    "nearness_to_52w_high", "weekly_reversal_signal_5d", "bab_score_60d",
    "turn_of_month_flag", "sell_in_may_seasonal", "month_end_quarter_end",
}


def _make_panel_with_spy(n_days=400, n_syms=3, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
    syms = [f"SYM{i}" for i in range(n_syms)] + ["SPY"]
    rets = rng.normal(0.0005, 0.015, size=(n_days, len(syms)))
    close = 100.0 * np.exp(np.cumsum(rets, axis=0))
    close_df = pd.DataFrame(close, index=idx, columns=syms)
    vol_df = pd.DataFrame(
        rng.lognormal(15.0, 0.5, size=close.shape), index=idx, columns=syms,
    )
    return close_df, vol_df


class TestBatch3Registration:
    def test_all_9_in_research_factors(self):
        for name in BATCH3_NAMES:
            assert name in RESEARCH_FACTORS


class TestHigherMoments:
    def test_higher_moments_factors_present(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_h_higher_moments(close_df, benchmark_col="SPY", window=60)
        assert "coskew_60d_spy" in out
        assert "cokurt_60d_spy" in out
        assert "idiosyncratic_skew_60d" in out

    def test_higher_moments_skipped_without_spy(self):
        idx = pd.date_range("2024-01-01", periods=100, freq="B")
        close = pd.DataFrame({"AAPL": np.random.default_rng(0).normal(100, 5, 100)}, index=idx)
        out = _family_h_higher_moments(close, benchmark_col="SPY")
        assert out == {}, "should return empty when SPY column missing"

    def test_panel_shape_preserved(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_h_higher_moments(close_df, benchmark_col="SPY")
        for name, frame in out.items():
            assert frame.shape == close_df.shape


class TestAnchorBAB:
    def test_nearness_to_52w_high_in_0_1(self):
        close_df, _ = _make_panel_with_spy(n_days=300)
        out = _family_i_anchor_bab(close_df, benchmark_col="SPY")
        n = out["nearness_to_52w_high"].dropna().values
        assert (n >= -1e-9).all() and (n <= 1.0 + 1e-9).all()

    def test_bab_score_requires_spy(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_i_anchor_bab(close_df, benchmark_col="SPY")
        assert "bab_score_60d" in out

        # No SPY → no BAB
        close_no_spy = close_df.drop(columns=["SPY"])
        out2 = _family_i_anchor_bab(close_no_spy, benchmark_col="SPY")
        assert "bab_score_60d" not in out2

    def test_weekly_reversal_requires_volume(self):
        close_df, vol_df = _make_panel_with_spy()
        out_with = _family_i_anchor_bab(close_df, volume_df=vol_df)
        out_no = _family_i_anchor_bab(close_df, volume_df=None)
        assert "weekly_reversal_signal_5d" in out_with
        assert "weekly_reversal_signal_5d" not in out_no


class TestCalendar:
    def test_calendar_factors_present(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_j_calendar(close_df)
        assert "turn_of_month_flag" in out
        assert "sell_in_may_seasonal" in out
        assert "month_end_quarter_end" in out

    def test_turn_of_month_flag_binary(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_j_calendar(close_df)
        tom = out["turn_of_month_flag"]
        unique_vals = set(np.unique(tom.values))
        assert unique_vals <= {0.0, 1.0}, f"non-binary: {unique_vals}"

    def test_sell_in_may_seasonal_signs(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_j_calendar(close_df)
        s = out["sell_in_may_seasonal"]
        # Dec 2024 = Nov-Apr range → +1
        dec_row = s.loc[s.index.month == 12].iloc[0, 0]
        assert dec_row == 1.0
        # Jul 2024 = May-Oct → -1
        jul_row = s.loc[s.index.month == 7].iloc[0, 0]
        assert jul_row == -1.0

    def test_month_end_quarter_end_only_in_qend_months(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_j_calendar(close_df)
        flag = out["month_end_quarter_end"]
        # Flag rows only in months [3, 6, 9, 12]
        flagged_dates = flag.index[flag.iloc[:, 0] == 1.0]
        for d in flagged_dates:
            assert d.month in (3, 6, 9, 12), f"non-qend month flagged: {d}"

    def test_calendar_broadcast_identical_across_symbols(self):
        close_df, _ = _make_panel_with_spy()
        out = _family_j_calendar(close_df)
        # Calendar factors don't depend on symbol → all columns identical
        for name in ("turn_of_month_flag", "sell_in_may_seasonal", "month_end_quarter_end"):
            df = out[name]
            for col in df.columns[1:]:
                np.testing.assert_array_equal(df[col].values, df[df.columns[0]].values)


class TestBatch3Leakage:
    def test_perturb_last_bar_no_leak_higher_moments(self):
        close_df, _ = _make_panel_with_spy(n_days=200)
        out_base = _family_h_higher_moments(close_df, benchmark_col="SPY")
        close_p = close_df.copy()
        close_p.iloc[-1, :] *= 1.5
        out_pert = _family_h_higher_moments(close_p, benchmark_col="SPY")
        for name in out_base.keys():
            pd.testing.assert_frame_equal(
                out_base[name].iloc[:-1], out_pert[name].iloc[:-1],
                check_dtype=False, obj=f"{name} leakage",
            )


class TestBatch3Integration:
    def test_via_generate_all_factors_with_spy(self):
        close_df, vol_df = _make_panel_with_spy()
        out = generate_all_factors(close_df, volume_df=vol_df, benchmark_col="SPY")
        for name in BATCH3_NAMES:
            assert name in out, f"{name} missing from generate_all_factors output"
