"""Tests for S/R-anchored stop-loss helper (core/risk/sr_stops.py).

PRD 20260505 Step 4. Pure functional; no consumer wired yet.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.risk.sr_stops import (
    SRStopParams,
    compute_atr,
    compute_sr_anchored_stop,
)


# ── compute_sr_anchored_stop ─────────────────────────────────────


class TestSAnchoredPath:

    def test_stop_at_support_minus_atr_buffer_when_unbounded(self):
        """S-anchored: stop = S - atr*atr_buffer_mult, when within bounds."""
        # Entry $100, S=$95 (5% below), ATR=$1, buffer_mult=1.0
        # Candidate = 95 - 1*1 = 94 → 6% below entry → within [2%, 15%] ✓
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=95.0, atr=1.0,
            params=SRStopParams(),
        )
        assert abs(stop - 94.0) < 1e-9

    def test_stop_at_support_when_atr_zero(self):
        """ATR=0 → stop = S (no buffer)."""
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=95.0, atr=0.0,
        )
        assert abs(stop - 95.0) < 1e-9

    def test_atr_buffer_mult_scales_buffer(self):
        """buffer_mult=2.0 → 2 ATRs below S."""
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=95.0, atr=0.5,
            params=SRStopParams(atr_buffer_mult=2.0),
        )
        # 95 - 0.5*2 = 94
        assert abs(stop - 94.0) < 1e-9

    def test_support_above_entry_falls_back_to_fixed(self):
        """S >= entry is degenerate (S below entry by definition for
        a long position). Fall back to fixed-pct rule."""
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=105.0, atr=1.0,
            params=SRStopParams(fixed_stop_fallback_pct=0.08),
        )
        assert abs(stop - 92.0) < 1e-9  # 100 * (1 - 0.08)


class TestFallbackPath:

    def test_stop_uses_fixed_pct_when_support_none(self):
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=None,
            params=SRStopParams(fixed_stop_fallback_pct=0.08),
        )
        assert abs(stop - 92.0) < 1e-9

    def test_atr_optional_in_fallback_path(self):
        """ATR not used when falling back to fixed pct."""
        stop_no_atr = compute_sr_anchored_stop(
            entry_price=100.0, support_level=None, atr=None,
        )
        stop_with_atr = compute_sr_anchored_stop(
            entry_price=100.0, support_level=None, atr=5.0,
        )
        assert stop_no_atr == stop_with_atr  # ATR irrelevant in fallback


class TestBoundedDistance:

    def test_floor_at_max_stop_pct(self):
        """S far below entry would produce excessive stop distance →
        clamp at max_stop_pct = 15% by default."""
        # Entry $100, S=$50 (very far below). Without clamp, stop = 50
        # (50% drawdown). Clamp → stop = 100 * 0.85 = 85.
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=50.0, atr=0.0,
            params=SRStopParams(max_stop_pct=0.15),
        )
        assert abs(stop - 85.0) < 1e-9

    def test_ceil_at_min_stop_pct(self):
        """S right at entry → stop too tight → clamp at min_stop_pct = 2%."""
        # Entry $100, S=$99.50, ATR=0. Without clamp, stop = 99.50
        # (0.5% from entry — too tight). Clamp → stop = 100 * 0.98 = 98.
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=99.50, atr=0.0,
            params=SRStopParams(min_stop_pct=0.02),
        )
        assert abs(stop - 98.0) < 1e-9

    def test_atr_buffer_extends_below_floor_then_clamps(self):
        """If ATR buffer pulls candidate below floor, clamp at floor."""
        # Entry $100, S=$90, ATR=$10 (huge), buffer 1.0
        # Candidate = 90 - 10 = 80 → 20% below entry → clamp at 85
        stop = compute_sr_anchored_stop(
            entry_price=100.0, support_level=90.0, atr=10.0,
            params=SRStopParams(max_stop_pct=0.15),
        )
        assert abs(stop - 85.0) < 1e-9

    def test_invariant_within_bounds(self):
        """Across all edge cases, stop ∈ [entry*0.85, entry*0.98]."""
        params = SRStopParams(min_stop_pct=0.02, max_stop_pct=0.15)
        for s in [None, 30.0, 95.0, 99.5, 100.0, 110.0]:
            for a in [None, 0.0, 0.5, 5.0, 50.0]:
                stop = compute_sr_anchored_stop(100.0, s, a, params=params)
                assert 85.0 <= stop <= 98.0, (
                    f"stop {stop} out of bounds for S={s}, atr={a}"
                )


class TestValidation:

    def test_zero_entry_raises(self):
        with pytest.raises(ValueError):
            compute_sr_anchored_stop(0.0, support_level=95.0)

    def test_negative_entry_raises(self):
        with pytest.raises(ValueError):
            compute_sr_anchored_stop(-100.0, support_level=95.0)


# ── compute_atr ─────────────────────────────────────────────────


class TestComputeATR:

    def test_atr_classical_value(self):
        """For 15 bars with H-L=$1 and no gaps, TR=1 each → ATR=1."""
        h = [101.0] * 15
        l_ = [100.0] * 15
        c = [100.5] * 15
        atr = compute_atr(h, l_, c, n=14)
        assert atr is not None
        assert abs(atr - 1.0) < 1e-9

    def test_atr_with_gap(self):
        """When prior close > today high, TR = |today_low - prior_close|."""
        # 14 bars at H=L=C=100; then 15th bar gaps DOWN to H=99, L=98, C=98.5
        # TR_15 = max(1, |99 - 100|=1, |98 - 100|=2) = 2
        h = [100.0] * 14 + [99.0]
        l_ = [100.0] * 14 + [98.0]
        c = [100.0] * 14 + [98.5]
        atr = compute_atr(h, l_, c, n=14)
        # First 13 TRs are 0 (constant H=L=C), 14th TR is 2 from the gap.
        # ATR = (sum of last 14 TRs) / 14 = (0*13 + 2) / 14 ≈ 0.143
        assert atr is not None
        assert abs(atr - (2.0 / 14.0)) < 1e-9

    def test_atr_returns_none_for_short_input(self):
        h = [100.0] * 5
        l_ = [99.0] * 5
        c = [99.5] * 5
        assert compute_atr(h, l_, c, n=14) is None

    def test_atr_returns_none_for_mismatched_lengths(self):
        h = [100.0] * 15
        l_ = [99.0] * 14
        c = [99.5] * 15
        assert compute_atr(h, l_, c, n=14) is None

    def test_atr_accepts_numpy_arrays(self):
        h = np.array([101.0] * 15)
        l_ = np.array([100.0] * 15)
        c = np.array([100.5] * 15)
        atr = compute_atr(h, l_, c, n=14)
        assert atr is not None
        assert abs(atr - 1.0) < 1e-9


# ── integration sanity ───────────────────────────────────────────


def test_sr_stop_with_realistic_atr():
    """Entry $280, S=$275, ATR=$3 (typical large-cap 60m ATR) →
    stop = 275 - 3 = 272 (2.86% below entry, within bounds)."""
    stop = compute_sr_anchored_stop(
        entry_price=280.0, support_level=275.0, atr=3.0,
    )
    assert abs(stop - 272.0) < 1e-9
    drawdown = (280.0 - stop) / 280.0
    assert 0.02 < drawdown < 0.05  # reasonable for large-cap


def test_default_params_accessible():
    p = SRStopParams()
    assert p.atr_buffer_mult == 1.0
    assert p.fixed_stop_fallback_pct == 0.08
    assert p.max_stop_pct == 0.15
    assert p.min_stop_pct == 0.02
