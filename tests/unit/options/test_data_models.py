from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from core.options.data import (
    OptionChain,
    OptionContract,
    OptionQuote,
    OptionRight,
    QuoteQualityError,
)

NOW = datetime(2026, 7, 17, 20, 0, tzinfo=UTC)


def contract(**overrides) -> OptionContract:
    values = {
        "contract_id": "SPY-20260821-P-600",
        "occ_symbol": "SPY260821P00600000",
        "underlying": "spy",
        "expiry": date(2026, 8, 21),
        "strike": 600.0,
        "right": OptionRight.PUT,
    }
    values.update(overrides)
    return OptionContract(**values)


def quote(**overrides) -> OptionQuote:
    values = {
        "contract": contract(),
        "bid": 4.90,
        "ask": 5.10,
        "bid_size": 20,
        "ask_size": 25,
        "quote_time": NOW - timedelta(seconds=2),
        "received_time": NOW - timedelta(seconds=1),
        "underlying_price": 625.0,
    }
    values.update(overrides)
    return OptionQuote(**values)


def test_contract_normalizes_underlying_and_rejects_bad_multiplier():
    assert contract().underlying == "SPY"
    with pytest.raises(ValueError, match="multiplier"):
        contract(multiplier=0)


def test_quote_requires_utc_event_and_received_timestamps():
    with pytest.raises(ValueError, match="quote_time"):
        quote(quote_time=datetime(2026, 7, 17, 20, 0))
    with pytest.raises(ValueError, match="cannot precede"):
        quote(received_time=NOW - timedelta(seconds=10))


def test_tradeable_quote_mid_spread_and_quality():
    valid = quote()
    assert valid.midpoint == pytest.approx(5.0)
    assert valid.spread == pytest.approx(0.2)
    valid.require_tradeable(now_utc=NOW, max_age=timedelta(seconds=10))


def test_stale_crossed_wide_or_zero_size_quotes_fail_closed():
    stale = quote(quote_time=NOW - timedelta(minutes=5), received_time=NOW)
    with pytest.raises(QuoteQualityError, match="STALE_QUOTE"):
        stale.require_tradeable(now_utc=NOW, max_age=timedelta(seconds=10))

    bad = quote(bid=6.0, ask=5.0, bid_size=0)
    reasons = bad.quality_reasons(now_utc=NOW, max_age=timedelta(seconds=10))
    assert "CROSSED_MARKET" in reasons
    assert "ZERO_DISPLAYED_SIZE" in reasons


def test_chain_rejects_mixed_underlyings_and_filters_quality():
    good = quote()
    stale = quote(
        contract=contract(contract_id="SPY-stale", occ_symbol="SPY260821P00590000", strike=590),
        quote_time=NOW - timedelta(minutes=5),
        received_time=NOW,
    )
    chain = OptionChain(
        underlying="SPY",
        provider="fixture",
        as_of=NOW - timedelta(seconds=2),
        received_at=NOW,
        quotes=(good, stale),
        is_synthetic=True,
    )
    assert chain.tradeable_quotes(now_utc=NOW, max_age=timedelta(seconds=10)) == (good,)

    with pytest.raises(ValueError, match="chain underlying"):
        OptionChain(
            underlying="QQQ",
            provider="fixture",
            as_of=NOW,
            received_at=NOW,
            quotes=(good,),
        )
