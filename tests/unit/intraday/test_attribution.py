"""Tests for per-TF attribution infrastructure."""

import pandas as pd

from core.intraday.multi_timescale import (
    AttributionAggregator,
    MultiTimescaleContext,
    TimescaleBar,
    evaluate_cross_tf_signal,
)


def _bar(direction: int, freq: str) -> TimescaleBar:
    o = 100.0
    c = 101.5 if direction == 1 else (98.5 if direction == -1 else 100.0)
    return TimescaleBar(
        timestamp=pd.Timestamp("2025-04-01 10:30"),
        freq=freq, open=o, high=102, low=98, close=c, volume=1e5,
    )


def _ctx(dir_60=None, dir_30=None, dir_15=None) -> MultiTimescaleContext:
    bars = {}
    if dir_60 is not None:
        bars["60m"] = _bar(dir_60, "60m")
    if dir_30 is not None:
        bars["30m"] = _bar(dir_30, "30m")
    if dir_15 is not None:
        bars["15m"] = _bar(dir_15, "15m")
    return MultiTimescaleContext(
        decision_time=pd.Timestamp("2025-04-01 10:30"), bars=bars,
    )


class TestPerTFFieldsPopulated:
    def test_bullish_confirmed_confirm_flags(self):
        sig = evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1, dir_15=1), "SPY")
        assert sig.base_strength == 1.0
        assert sig.confirm_30m is True
        assert sig.confirm_15m is True
        # 30m mult is 1.0 when both bullish; 15m boost clips at 1.0 → mult <=1.1
        assert sig.mult_30m == 1.0
        assert 1.0 <= sig.mult_15m <= 1.1

    def test_30m_contradicts_60m(self):
        sig = evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=-1), "SPY")
        assert sig.confirm_30m is False
        assert sig.mult_30m == 0.4

    def test_30m_neutral(self):
        sig = evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=0), "SPY")
        assert sig.confirm_30m is None
        assert sig.mult_30m == 0.7

    def test_15m_reduces_when_opposed(self):
        sig = evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1, dir_15=-1), "SPY")
        assert sig.confirm_15m is False
        assert sig.mult_15m == 0.6

    def test_no_15m_default_mult_one(self):
        sig = evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1), "SPY")
        assert sig.confirm_15m is None
        assert sig.mult_15m == 1.0


class TestAttributionAggregator:
    def test_empty_summary(self):
        agg = AttributionAggregator()
        s = agg.summary()
        assert s.n_signals == 0
        assert s.n_vetoed == 0
        assert s.n_active == 0
        assert "no signals" in agg.format_report()

    def test_counts_confirm_contradict_neutral(self):
        agg = AttributionAggregator()
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1), "A"))
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=-1), "B"))
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=0), "C"))
        s = agg.summary()
        assert s.n_signals == 3
        assert s.n_vetoed == 0
        assert s.confirm_30m_counts == {
            "confirm": 1, "contradict": 1, "neutral_or_absent": 1,
        }

    def test_veto_counted(self):
        agg = AttributionAggregator()
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=None, dir_30=1), "A"))
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1), "B"))
        s = agg.summary()
        assert s.n_signals == 2
        assert s.n_vetoed == 1
        assert s.n_active == 1
        # vetoed signals don't contribute to confirm counts
        assert sum(s.confirm_30m_counts.values()) == 1

    def test_format_report_contains_expected_sections(self):
        agg = AttributionAggregator()
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1, dir_15=1), "A"))
        rep = agg.format_report()
        assert "Multi-TF Attribution Report" in rep
        assert "30m" in rep
        assert "15m" in rep
        assert "Avg base" in rep

    def test_avg_strengths_computed(self):
        agg = AttributionAggregator()
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=1), "A"))
        agg.add(evaluate_cross_tf_signal(_ctx(dir_60=1, dir_30=-1), "B"))
        s = agg.summary()
        # base = 1.0 for both; mult_30m = 1.0 and 0.4 → avg = 0.7
        assert abs(s.avg_base_strength - 1.0) < 1e-6
        assert abs(s.avg_mult_30m - 0.7) < 1e-6
        # avg final = mean(1.0, 0.4) = 0.7
        assert abs(s.avg_final_strength - 0.7) < 1e-6
