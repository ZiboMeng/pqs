"""Unit tests for core/data/data_completeness_gate.py — P0.b Codex fix."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.data.data_completeness_gate import (
    GapSpan,
    SymbolCompletenessResult,
    PanelCompletenessReport,
    check_symbol_completeness,
    check_panel_completeness,
    _detect_gap_spans,
)


def _panel(dates_per_sym):
    """Build a panel from {sym: [dates]} dict."""
    all_dates = sorted(set(d for ds in dates_per_sym.values() for d in ds))
    df = pd.DataFrame(index=pd.DatetimeIndex(all_dates), columns=list(dates_per_sym))
    for sym, dates in dates_per_sym.items():
        for d in dates:
            df.at[pd.Timestamp(d), sym] = 100.0
    return df


# ── _detect_gap_spans low-level ─────────────────────────────────────────

def test_detect_gap_spans_no_missing():
    expected = pd.bdate_range("2020-01-06", "2020-01-10")  # Mon-Fri
    actual = expected
    assert _detect_gap_spans(actual, expected) == []


def test_detect_gap_spans_single_day_gap():
    expected = pd.bdate_range("2020-01-06", "2020-01-10")
    actual = expected.drop(pd.Timestamp("2020-01-08"))  # remove Wed
    spans = _detect_gap_spans(actual, expected)
    assert len(spans) == 1
    s, e, n = spans[0]
    assert s == pd.Timestamp("2020-01-08")
    assert e == pd.Timestamp("2020-01-08")
    assert n == 1


def test_detect_gap_spans_multi_day_consecutive():
    expected = pd.bdate_range("2020-01-06", "2020-01-17")  # 10 BD
    # remove Wed-Thu of week 1 (2 consecutive BD)
    actual = expected.drop([pd.Timestamp("2020-01-08"), pd.Timestamp("2020-01-09")])
    spans = _detect_gap_spans(actual, expected)
    assert len(spans) == 1
    assert spans[0][2] == 2


def test_detect_gap_spans_multiple_separated_spans():
    expected = pd.bdate_range("2020-01-06", "2020-01-17")
    actual = expected.drop([
        pd.Timestamp("2020-01-08"),  # span 1, 1 BD
        pd.Timestamp("2020-01-14"), pd.Timestamp("2020-01-15"),  # span 2, 2 BD
    ])
    spans = _detect_gap_spans(actual, expected)
    assert len(spans) == 2
    assert spans[0][2] == 1
    assert spans[1][2] == 2


# ── check_symbol_completeness ───────────────────────────────────────────

def test_symbol_missing_from_panel():
    df = _panel({"AAPL": ["2020-01-06", "2020-01-07"]})
    res = check_symbol_completeness(df, "XXX")
    assert not res.passed
    assert res.n_rows == 0


def test_symbol_all_present_passes():
    dates = list(pd.bdate_range("2020-01-06", "2020-01-17"))
    df = _panel({"AAPL": dates})
    res = check_symbol_completeness(df, "AAPL")
    assert res.passed
    assert res.n_severe_gaps == 0
    assert res.total_missing_bd == 0
    assert res.n_rows == len(dates)


def test_symbol_5_bd_gap_below_threshold_passes():
    # threshold=5 means n_bd > 5 is severe; n_bd <= 5 is minor
    expected = pd.bdate_range("2020-01-06", "2020-02-07")  # ~25 BD
    actual_dates = list(expected.drop(list(expected[5:10])))  # 5 BD gap
    df = _panel({"AAPL": actual_dates})
    res = check_symbol_completeness(df, "AAPL", max_consecutive_missing_bd=5)
    assert res.passed
    assert len(res.minor_gaps) == 1
    assert res.minor_gaps[0].n_business_days == 5
    assert res.n_severe_gaps == 0


def test_symbol_6_bd_gap_above_threshold_fails():
    expected = pd.bdate_range("2020-01-06", "2020-02-07")
    actual_dates = list(expected.drop(list(expected[5:11])))  # 6 BD gap
    df = _panel({"AAPL": actual_dates})
    res = check_symbol_completeness(df, "AAPL", max_consecutive_missing_bd=5)
    assert not res.passed
    assert res.n_severe_gaps == 1
    assert res.severe_gaps[0].n_business_days == 6


def test_symbol_first_trade_date_excludes_pre_gaps():
    """Gaps BEFORE first_trade_date should not count (e.g., ticker history)."""
    expected = pd.bdate_range("2018-01-02", "2020-12-31")
    actual_dates = list(expected[expected >= pd.Timestamp("2020-01-02")])  # starts late
    df = _panel({"AAPL": actual_dates})
    # Without first_trade_date: full window gap (early years) → fail
    res_no_ftd = check_symbol_completeness(df, "AAPL")
    assert res_no_ftd.passed  # window starts at actual first date
    # With first_trade_date 2020-01-02: window matches actual exactly
    res_ftd = check_symbol_completeness(df, "AAPL",
                                         first_trade_date=pd.Timestamp("2020-01-02"))
    assert res_ftd.passed
    assert res_ftd.total_missing_bd == 0


def test_symbol_first_trade_date_after_panel_end_returns_empty_window():
    df = _panel({"AAPL": ["2020-01-06", "2020-01-07"]})
    res = check_symbol_completeness(df, "AAPL",
                                     first_trade_date=pd.Timestamp("2025-01-01"))
    assert res.passed  # empty window is degenerate-pass
    assert res.n_expected_business_days == 0


# ── check_panel_completeness ────────────────────────────────────────────

def test_panel_empty_universe():
    df = _panel({"AAPL": ["2020-01-06"]})
    report = check_panel_completeness(df, [])
    assert report.overall_passed
    assert report.n_pass == 0
    assert report.n_fail == 0


def test_panel_all_clean_universe_passes():
    dates = list(pd.bdate_range("2020-01-06", "2020-01-17"))
    df = _panel({"AAPL": dates, "MSFT": dates})
    report = check_panel_completeness(df, ["AAPL", "MSFT"])
    assert report.overall_passed
    assert report.n_pass == 2
    assert report.n_fail == 0


def test_panel_mixed_pass_fail():
    expected = pd.bdate_range("2020-01-06", "2020-02-07")
    msft_dates = list(expected.drop(list(expected[5:11])))  # 6 BD gap → FAIL
    aapl_dates = list(expected)  # full → PASS
    df = _panel({"AAPL": aapl_dates, "MSFT": msft_dates})
    report = check_panel_completeness(df, ["AAPL", "MSFT"],
                                        max_consecutive_missing_bd=5)
    assert not report.overall_passed
    assert report.failed_symbols == ["MSFT"]
    assert report.passed_symbols == ["AAPL"]


def test_panel_uses_first_trade_dates_dict():
    expected = pd.bdate_range("2018-01-02", "2020-12-31")
    late_starter_dates = list(expected[expected >= pd.Timestamp("2020-01-02")])
    df = _panel({"AAPL": late_starter_dates})
    # Without first_trade_dates: pre-2020 gap counts as severe (large)
    report_no = check_panel_completeness(df, ["AAPL"])
    # With first_trade_dates: window starts at 2020-01-02 → no gap
    report_with = check_panel_completeness(
        df, ["AAPL"], first_trade_dates={"AAPL": "2020-01-02"}
    )
    assert report_with.overall_passed


def test_panel_report_to_dict_serializable():
    """Verify report can be JSON-serialized for audit logging."""
    import json
    dates = list(pd.bdate_range("2020-01-06", "2020-01-17"))
    df = _panel({"AAPL": dates})
    report = check_panel_completeness(df, ["AAPL"])
    d = report.to_dict()
    assert json.dumps(d)  # must not raise
    assert d["universe_size"] == 1
    assert d["overall_passed"] is True


def test_threshold_inclusive_boundary():
    """Threshold semantics: > threshold is severe; <= is minor."""
    expected = pd.bdate_range("2020-01-06", "2020-02-07")
    # gap exactly = threshold → minor (passes)
    actual_5 = list(expected.drop(list(expected[5:10])))
    res = check_symbol_completeness(_panel({"X": actual_5})[["X"]].rename(columns={"X": "X"}),
                                     "X", max_consecutive_missing_bd=5)
    # Need to re-use _panel:
    df = _panel({"X": actual_5})
    res = check_symbol_completeness(df, "X", max_consecutive_missing_bd=5)
    assert res.passed  # n_bd=5 <= threshold

    actual_6 = list(expected.drop(list(expected[5:11])))
    df6 = _panel({"X": actual_6})
    res6 = check_symbol_completeness(df6, "X", max_consecutive_missing_bd=5)
    assert not res6.passed  # n_bd=6 > threshold


def test_gap_span_to_dict():
    span = GapSpan(
        start_date=pd.Timestamp("2020-01-08"),
        end_date=pd.Timestamp("2020-01-10"),
        n_business_days=3,
    )
    d = span.to_dict()
    assert d == {
        "start_date": "2020-01-08",
        "end_date": "2020-01-10",
        "n_business_days": 3,
    }
