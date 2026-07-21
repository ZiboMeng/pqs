from __future__ import annotations

import pytest

from core.data.yahoo_daily_snapshot import (
    corporate_actions_match,
    parse_yahoo_daily_bars,
)


def _payload(close=(100.0, 102.0), adj=(90.0, 91.8)) -> dict:
    return {
        "chart": {
            "error": None,
            "result": [{
                "meta": {"symbol": "AAA"},
                "timestamp": [1704205800, 1704292200],
                "events": {
                    "dividends": {"1": {"amount": 1.0, "date": 1704205800}},
                },
                "indicators": {
                    "quote": [{
                        "open": [99.0, 101.0],
                        "high": [101.0, 103.0],
                        "low": [98.0, 100.0],
                        "close": list(close),
                        "volume": [1000, 1100],
                    }],
                    "adjclose": [{"adjclose": list(adj)}],
                },
            }],
        }
    }


def test_parses_split_adjusted_and_total_return_ohlc():
    parsed = parse_yahoo_daily_bars(_payload(), expected_symbol="AAA")
    frame = parsed.frame
    assert list(frame.index.astype(str)) == ["2024-01-02", "2024-01-03"]
    assert frame.iloc[0]["total_return_close"] == 90.0
    assert frame.iloc[0]["total_return_open"] == pytest.approx(89.1)
    assert frame.iloc[1]["total_return_high"] == pytest.approx(92.7)


def test_rejects_missing_values_and_symbol_mismatch():
    payload = _payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["open"][0] = None
    with pytest.raises(ValueError, match="missing/non-finite"):
        parse_yahoo_daily_bars(payload, expected_symbol="AAA")
    with pytest.raises(ValueError, match="symbol mismatch"):
        parse_yahoo_daily_bars(_payload(), expected_symbol="BBB")


def test_corporate_action_consistency_is_order_independent_but_value_sensitive():
    left = _payload()
    right = _payload()
    assert corporate_actions_match(left, right, expected_symbol="AAA")
    right["chart"]["result"][0]["events"]["dividends"]["1"]["amount"] = 2.0
    assert not corporate_actions_match(left, right, expected_symbol="AAA")
