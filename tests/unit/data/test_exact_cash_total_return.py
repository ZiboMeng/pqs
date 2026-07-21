from __future__ import annotations

import pandas as pd
import pytest

from core.data.exact_cash_total_return import build_exact_cash_total_return


def _bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=4)
    return pd.DataFrame({
        "open": [100.0, 91.0, 93.0, 94.0],
        "high": [101.0, 93.0, 94.0, 96.0],
        "low": [99.0, 90.0, 91.0, 93.0],
        "close": [100.0, 92.0, 93.0, 95.0],
        "volume": [1000, 1100, 1200, 1300],
    }, index=dates)


def test_exact_cash_return_handles_special_distribution_without_approximation():
    bars = _bars()
    event = pd.DataFrame({
        "ex_date": [bars.index[1]],
        "cash_amount": [10.0],
    })
    result = build_exact_cash_total_return(bars, event)
    expected_event_return = (92.0 + 10.0) / 100.0 - 1.0
    actual = result.frame["total_return_close"].pct_change().iloc[1]
    assert actual == pytest.approx(expected_event_return)
    # The old vendor-style approximation would report 92 / 90 - 1.
    assert actual != pytest.approx(92.0 / 90.0 - 1.0)
    assert result.frame.loc[bars.index[1], "cash_distribution"] == 10.0
    assert result.applied_events == 1


def test_exact_cash_return_skips_unobservable_first_bar_event_and_rejects_gap():
    bars = _bars()
    first = pd.DataFrame({
        "ex_date": [bars.index[0]], "cash_amount": [1.0],
    })
    result = build_exact_cash_total_return(bars, first)
    assert result.skipped_pre_history_events == 1
    missing = pd.DataFrame({
        "ex_date": [pd.Timestamp("2024-01-07")], "cash_amount": [1.0],
    })
    with pytest.raises(ValueError, match="absent from price bars"):
        build_exact_cash_total_return(bars, missing)
