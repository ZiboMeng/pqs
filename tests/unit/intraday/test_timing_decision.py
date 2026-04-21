"""Tests for the multi-TF timing contract (约束 3).

The multi-timescale framework is now positioned as a
TIMING / EXECUTION / RISK layer, never a direction authority. These
tests enforce that contract:
  - Lower TFs cannot flip direction, only defer
  - 60m opposite to daily long → scales down / soft vetoes
  - 30m contradict → confidence penalty
  - 15m / 5m adverse → execute=False (defer) but timing_scale preserved
  - No higher context → pass-through (execute=True, scale=1.0)
"""

from __future__ import annotations

import pandas as pd

from core.intraday.multi_timescale import (
    MultiTimescaleContext,
    TimescaleBar,
    TimingDecision,
    decide_timing,
)


def _bar(direction: int, freq: str) -> TimescaleBar:
    o = 100.0
    c = 101.5 if direction == 1 else (98.5 if direction == -1 else 100.0)
    return TimescaleBar(
        timestamp=pd.Timestamp("2025-04-01 10:30"),
        freq=freq, open=o, high=102, low=98, close=c, volume=1e5,
    )


def _ctx(**kwargs) -> MultiTimescaleContext:
    bars = {}
    for freq, direction in kwargs.items():
        if direction is not None:
            bars[freq] = _bar(direction, freq)
    return MultiTimescaleContext(
        decision_time=pd.Timestamp("2025-04-01 10:30"), bars=bars,
    )


# ──────────────────────────────────────────────────────────────────────────
# Contract: TimingDecision shape
# ──────────────────────────────────────────────────────────────────────────

class TestTimingDecisionShape:
    def test_effective_weight_zero_when_deferred(self):
        d = TimingDecision(symbol="X", decision_time=pd.Timestamp("2025-04-01"),
                           base_weight=0.3, timing_scale=0.8, execute=False)
        assert d.effective_weight == 0.0

    def test_effective_weight_scaled_when_executing(self):
        d = TimingDecision(symbol="X", decision_time=pd.Timestamp("2025-04-01"),
                           base_weight=0.3, timing_scale=0.8, execute=True)
        assert abs(d.effective_weight - 0.24) < 1e-9


# ──────────────────────────────────────────────────────────────────────────
# Contract: higher TF governs, lower TF defers
# ──────────────────────────────────────────────────────────────────────────

class TestHigherTFGoverns:

    def test_no_higher_context_passthrough(self):
        """With no 60m context, multi-TF adds nothing — execute as-is."""
        d = decide_timing(_ctx(), "SPY", base_weight=0.3)
        assert d.execute is True
        assert d.timing_scale == 1.0
        assert d.reason == "no_higher_context_passthrough"
        assert d.effective_weight == 0.3

    def test_60m_bullish_full_scale(self):
        d = decide_timing(_ctx(**{"60m": 1}), "SPY", base_weight=0.3)
        assert d.execute is True
        assert d.timing_scale == 1.0
        assert d.higher_tf_vote["60m"] == "confirm"

    def test_60m_bearish_contradicts_long_target(self):
        """60m strongly bearish vs a long daily target → soft veto
        (scale reduced but not flipped to short)."""
        d = decide_timing(_ctx(**{"60m": -1}), "SPY", base_weight=0.3)
        assert d.timing_scale < 1.0
        assert d.higher_tf_vote["60m"] == "contradict"
        # System is long-only → never flip; reason documents the reduction
        assert "contradict" in d.reason or d.reason == "deferred"

    def test_60m_neutral_mildly_reduces(self):
        d = decide_timing(_ctx(**{"60m": 0}), "SPY", base_weight=0.3)
        assert 0.7 <= d.timing_scale <= 0.9
        assert d.higher_tf_vote["60m"] == "neutral"


class TestConfirmationAndContradiction:

    def test_60m_bull_30m_confirm_full_scale(self):
        d = decide_timing(_ctx(**{"60m": 1, "30m": 1}), "SPY", base_weight=0.3)
        assert d.execute is True
        assert d.timing_scale == 1.0
        assert d.higher_tf_vote["30m"] == "confirm"

    def test_60m_bull_30m_contradict_reduces(self):
        d_confirm = decide_timing(_ctx(**{"60m": 1, "30m": 1}), "SPY", 0.3)
        d_contra = decide_timing(_ctx(**{"60m": 1, "30m": -1}), "SPY", 0.3)
        assert d_contra.timing_scale < d_confirm.timing_scale
        assert d_contra.higher_tf_vote["30m"] == "contradict"


class TestLowerTFDefersNotFlips:
    """Critical contract: 15m / 5m can only DEFER, never change direction."""

    def test_15m_adverse_defers_not_flips(self):
        """With 60m+30m both bull but 15m adverse: execute=False (defer)
        but direction still LONG (effective_weight=0, NOT negative)."""
        d = decide_timing(
            _ctx(**{"60m": 1, "30m": 1, "15m": -1}),
            "SPY", base_weight=0.3,
        )
        assert d.execute is False
        assert d.effective_weight == 0.0
        # timing_scale still reflects higher-TF confidence, not flipped
        assert d.timing_scale > 0.0

    def test_5m_adverse_also_defers(self):
        d = decide_timing(
            _ctx(**{"60m": 1, "30m": 1, "5m": -1}),
            "SPY", base_weight=0.3,
        )
        assert d.execute is False
        assert d.higher_tf_vote["5m"] == "contradict"

    def test_15m_confirm_executes(self):
        d = decide_timing(
            _ctx(**{"60m": 1, "30m": 1, "15m": 1}),
            "SPY", base_weight=0.3,
        )
        assert d.execute is True
        assert d.timing_scale == 1.0


class TestLongOnlyInvariants:

    def test_short_side_rejected(self):
        d = decide_timing(_ctx(**{"60m": 1}), "SPY", base_weight=0.3, daily_side=-1)
        assert d.execute is False
        assert d.reason == "short_not_supported"

    def test_zero_base_weight_rejected(self):
        d = decide_timing(_ctx(**{"60m": 1}), "SPY", base_weight=0.0)
        assert d.execute is False
        assert d.reason == "zero_base_weight"

    def test_timing_never_produces_negative_effective_weight(self):
        # Any combination of TFs should yield effective_weight ≥ 0
        for combos in [
            {"60m": -1}, {"60m": -1, "30m": -1},
            {"60m": 0, "30m": -1, "15m": -1, "5m": -1},
        ]:
            d = decide_timing(_ctx(**combos), "SPY", base_weight=0.3)
            assert d.effective_weight >= 0
