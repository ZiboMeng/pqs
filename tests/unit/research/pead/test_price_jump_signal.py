"""Unit tests for core/research/pead/price_jump_signal.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.pead.price_jump_signal import (
    compute_abnormal_returns,
    build_price_jump_signal_panel,
)


def _earnings_row(ticker, filed_date):
    return {
        "ticker": ticker,
        "period_end": pd.Timestamp(filed_date) - pd.Timedelta(days=30),
        "period_start": pd.Timestamp(filed_date) - pd.Timedelta(days=120),
        "first_filed_date": pd.Timestamp(filed_date),
        "form": "10-Q",
        "fy": 2020,
        "fp": "Q1",
        "eps_value": 1.0,
        "duration_days": 91,
    }


def _close_panel(dates, columns, values=None):
    """Build close_df. values dict maps {col: list_of_close_per_date}."""
    if values is None:
        values = {c: list(range(100, 100 + len(dates))) for c in columns}
    df = pd.DataFrame({c: values[c] for c in columns}, index=pd.DatetimeIndex(dates))
    return df


# ── Empty handling ──

def test_empty_earnings_returns_empty():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
    )
    df = compute_abnormal_returns(pd.DataFrame(), close)
    assert df.empty


def test_missing_benchmark_raises():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL"],
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    with pytest.raises(ValueError, match="benchmark_symbol"):
        compute_abnormal_returns(earn, close)


def test_ticker_not_in_close_df_skipped():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["SPY"],
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.empty


# ── Basic AR computation ──

def test_ar_basic_positive_surprise():
    """Stock up 10%, SPY flat → AR = +10%."""
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, 110], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert len(df) == 1
    assert df.iloc[0]["ret_stock"] == pytest.approx(0.10)
    assert df.iloc[0]["ret_bench"] == pytest.approx(0.0)
    assert df.iloc[0]["abnormal_return"] == pytest.approx(0.10)


def test_ar_market_subtraction():
    """Stock up 5%, SPY up 2% → AR = +3%."""
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, 105], "SPY": [100, 102]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.iloc[0]["abnormal_return"] == pytest.approx(0.05 - 0.02)


def test_ar_negative_surprise():
    """Stock down 8%, SPY flat → AR = -8%."""
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, 92], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.iloc[0]["abnormal_return"] == pytest.approx(-0.08)


# ── Edge cases ──

def test_nan_prices_skipped():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, np.nan], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.empty


def test_zero_prior_price_skipped():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [0, 110], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.empty


def test_filed_date_before_panel_rolls_forward_but_needs_prior_close():
    """If filed before panel starts, event_date = panel start but T-1 missing → skip."""
    close = _close_panel(
        ["2021-01-02", "2021-01-03"], ["AAPL", "SPY"],
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    # event_date = 2021-01-02 (first available); T-1 doesn't exist in panel → skip
    assert df.empty


def test_no_prior_close_skipped():
    """If event_date is first row of price_index, no T-1 → skip."""
    close = _close_panel(
        ["2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100], "SPY": [100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.empty


def test_filed_after_panel_end_skipped():
    close = _close_panel(
        ["2019-01-02", "2019-01-03"], ["AAPL", "SPY"],
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    df = compute_abnormal_returns(earn, close)
    assert df.empty


def test_weekend_filed_rolls_forward():
    """Filed on Saturday → event_date = next trading day (Monday)."""
    # Friday + Monday only
    close = _close_panel(
        ["2020-01-03", "2020-01-06"], ["AAPL", "SPY"],
        values={"AAPL": [100, 105], "SPY": [100, 101]},
    )
    # Filed on Saturday 2020-01-04
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-04")])
    df = compute_abnormal_returns(earn, close)
    assert len(df) == 1
    assert df.iloc[0]["event_date"] == pd.Timestamp("2020-01-06")
    assert df.iloc[0]["abnormal_return"] == pytest.approx(0.05 - 0.01)


# ── Multi-ticker / panel ──

def test_multi_ticker_independent_computation():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "MSFT", "SPY"],
        values={"AAPL": [100, 110], "MSFT": [200, 198], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([
        _earnings_row("AAPL", "2020-01-03"),
        _earnings_row("MSFT", "2020-01-03"),
    ])
    df = compute_abnormal_returns(earn, close)
    assert len(df) == 2
    aapl = df[df["ticker"] == "AAPL"].iloc[0]
    msft = df[df["ticker"] == "MSFT"].iloc[0]
    assert aapl["abnormal_return"] == pytest.approx(0.10)
    assert msft["abnormal_return"] == pytest.approx(-0.01)


# ── Signal panel construction ──

def test_build_signal_panel_basic():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, 110], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    ar_df = compute_abnormal_returns(earn, close)
    entry = build_price_jump_signal_panel(
        ar_df, ar_threshold=0.05,
        price_index=close.index, universe=["AAPL", "SPY"]
    )
    assert entry.loc["2020-01-03", "AAPL"]
    assert not entry.loc["2020-01-02", "AAPL"]
    assert entry.values.sum() == 1


def test_build_signal_panel_threshold_filters():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, 102], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    ar_df = compute_abnormal_returns(earn, close)
    # AR = +2%, threshold = +5% → no signal
    entry = build_price_jump_signal_panel(
        ar_df, ar_threshold=0.05,
        price_index=close.index, universe=["AAPL", "SPY"]
    )
    assert entry.values.sum() == 0


def test_build_signal_panel_ticker_not_in_universe():
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "MSFT", "SPY"],
        values={"AAPL": [100, 110], "MSFT": [200, 220], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([
        _earnings_row("AAPL", "2020-01-03"),
        _earnings_row("MSFT", "2020-01-03"),
    ])
    ar_df = compute_abnormal_returns(earn, close)
    # Universe only includes AAPL (MSFT excluded)
    entry = build_price_jump_signal_panel(
        ar_df, ar_threshold=0.05,
        price_index=close.index, universe=["AAPL"]
    )
    assert entry.values.sum() == 1
    assert entry.loc["2020-01-03", "AAPL"]


def test_build_signal_panel_empty_ar_returns_zero_signals():
    entry = build_price_jump_signal_panel(
        pd.DataFrame(), ar_threshold=0.05,
        price_index=pd.date_range("2020-01-01", "2020-01-10"),
        universe=["AAPL"]
    )
    assert entry.values.sum() == 0


def test_negative_ar_does_not_trigger():
    """Negative AR should not trigger long-only signal."""
    close = _close_panel(
        ["2020-01-02", "2020-01-03"], ["AAPL", "SPY"],
        values={"AAPL": [100, 90], "SPY": [100, 100]},
    )
    earn = pd.DataFrame([_earnings_row("AAPL", "2020-01-03")])
    ar_df = compute_abnormal_returns(earn, close)
    entry = build_price_jump_signal_panel(
        ar_df, ar_threshold=0.05,
        price_index=close.index, universe=["AAPL"]
    )
    assert entry.values.sum() == 0
