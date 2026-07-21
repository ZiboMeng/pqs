from __future__ import annotations

import pytest

from core.data.yahoo_corporate_actions import (
    parse_yahoo_corporate_actions,
    yahoo_symbol,
)


def _payload(symbol: str = "BRK-B") -> dict:
    return {
        "chart": {
            "error": None,
            "result": [{
                "meta": {"symbol": symbol},
                "events": {
                    "dividends": {
                        "1": {"amount": 0.25, "date": 1704205800},
                    },
                    "splits": {
                        "2": {
                            "date": 1704292200,
                            "numerator": 4.0,
                            "denominator": 1.0,
                        },
                    },
                },
            }],
        }
    }


def test_parses_actions_and_class_share_symbol():
    parsed = parse_yahoo_corporate_actions(
        _payload(), expected_symbol="BRK.B")
    assert yahoo_symbol("BRK.B") == "BRK-B"
    assert parsed.distributions.iloc[0]["cash_amount"] == 0.25
    assert str(parsed.distributions.iloc[0]["ex_date"].date()) == "2024-01-02"
    assert parsed.splits.iloc[0]["vendor_ratio"] == 4.0
    assert str(parsed.splits.iloc[0]["date"].date()) == "2024-01-03"


def test_rejects_symbol_mismatch_and_invalid_amount():
    with pytest.raises(ValueError, match="symbol mismatch"):
        parse_yahoo_corporate_actions(_payload("OTHER"), expected_symbol="BRK.B")
    payload = _payload()
    payload["chart"]["result"][0]["events"]["dividends"]["1"]["amount"] = 0
    with pytest.raises(ValueError, match="dividend amount"):
        parse_yahoo_corporate_actions(payload, expected_symbol="BRK.B")


def test_combines_same_day_split_legs_and_rejects_duplicate_dividends():
    payload = _payload()
    payload["chart"]["result"][0]["events"]["splits"]["3"] = {
        "date": 1704292200,
        "numerator": 3.0,
        "denominator": 2.0,
    }
    parsed = parse_yahoo_corporate_actions(payload, expected_symbol="BRK.B")
    assert parsed.splits.iloc[0]["vendor_ratio"] == 6.0
    payload["chart"]["result"][0]["events"]["dividends"]["4"] = {
        "amount": 0.25,
        "date": 1704205800,
    }
    with pytest.raises(ValueError, match="duplicate dividend"):
        parse_yahoo_corporate_actions(payload, expected_symbol="BRK.B")
