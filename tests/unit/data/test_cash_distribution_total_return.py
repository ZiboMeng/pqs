from __future__ import annotations

import pandas as pd
import pytest

from core.data.cash_distribution_total_return import apply_cash_distributions


def test_cash_distribution_removes_ex_date_price_drop():
    dates = pd.bdate_range("2024-01-02", periods=3)
    bars = pd.DataFrame({
        "open": [100.0, 99.0, 100.0],
        "high": [101.0, 100.0, 101.0],
        "low": [99.0, 98.0, 99.0],
        "close": [100.0, 99.0, 100.0],
    }, index=dates)
    events = pd.DataFrame({"ex_date": [dates[1]], "cash_amount": [1.0]})
    result = apply_cash_distributions(bars, events)
    assert result.applied_events == 1
    assert result.factors.tolist() == [0.99, 1.0, 1.0]
    assert result.frame["total_return_close"].tolist() == [99.0, 99.0, 100.0]


def test_skips_event_before_price_history_and_rejects_impossible_cash():
    dates = pd.bdate_range("2024-01-02", periods=2)
    bars = pd.DataFrame({
        "open": [10.0, 10.0], "high": [10.0, 10.0],
        "low": [10.0, 10.0], "close": [10.0, 10.0],
    }, index=dates)
    before = pd.DataFrame({"ex_date": [dates[0]], "cash_amount": [1.0]})
    assert apply_cash_distributions(
        bars, before).skipped_pre_history_events == 1
    impossible = pd.DataFrame({"ex_date": [dates[1]], "cash_amount": [10.0]})
    with pytest.raises(ValueError, match="invalid cash adjustment"):
        apply_cash_distributions(bars, impossible)
