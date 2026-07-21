from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from core.research.company_pool import (
    CompanyPoolConfig,
    canonical_artifact_hash,
    parse_sec_company_tickers,
    select_company_pool,
)
from dev.scripts.mining_v4 import build_company_pool


def _bars(price: float, volume: float, *, n: int = 8, end: str = "2026-07-17"):
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"close": price, "volume": volume}, index=idx)


def _config():
    return CompanyPoolConfig(
        max_symbols=2,
        exchanges=("Nasdaq", "NYSE"),
        min_history_sessions_at_snapshot=5,
        freshness_calendar_days=5,
        min_price=5.0,
        trailing_liquidity_sessions=3,
        min_median_dollar_volume=10_000_000.0,
        excluded_name_patterns=(r"(?i)\bETF\b", r"(?i)^PROSHARES\b"),
    )


def test_parse_sec_schema_and_reject_drift():
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[1, "Example Inc", "exm", "Nasdaq"]],
    }
    assert parse_sec_company_tickers(payload) == [{
        "cik": 1, "name": "Example Inc", "ticker": "EXM",
        "exchange": "Nasdaq",
    }]
    with pytest.raises(ValueError, match="schema"):
        parse_sec_company_tickers({"fields": ["ticker"], "data": []})


def test_selection_filters_etp_exchange_project_and_bad_market_data():
    records = [
        {"cik": 1, "name": "NETFLIX INC", "ticker": "NFLX", "exchange": "Nasdaq"},
        {"cik": 2, "name": "SPDR S&P 500 ETF TRUST", "ticker": "SPY", "exchange": "NYSE"},
        {"cik": 3, "name": "ProShares Trust", "ticker": "UCO", "exchange": "NYSE"},
        {"cik": 4, "name": "Blocked Inc", "ticker": "BAD", "exchange": "NYSE"},
        {"cik": 5, "name": "OTC Inc", "ticker": "OTC", "exchange": "OTC"},
        {"cik": 6, "name": "Low Price Inc", "ticker": "LOW", "exchange": "NYSE"},
        {"cik": 7, "name": "Stale Inc", "ticker": "OLD", "exchange": "NYSE"},
        {"cik": 8, "name": "Liquid Inc", "ticker": "LIQ", "exchange": "NYSE"},
    ]
    bars = {
        "NFLX": _bars(100.0, 1_000_000.0),
        "LOW": _bars(2.0, 10_000_000.0),
        "OLD": _bars(100.0, 1_000_000.0, end="2026-06-01"),
        "LIQ": _bars(50.0, 4_000_000.0),
    }
    result = select_company_pool(
        records,
        bars.get,
        price_as_of="2026-07-17",
        config=_config(),
        excluded_symbols=["BAD"],
    )
    assert [row["ticker"] for row in result.selected] == ["LIQ", "NFLX"]
    assert result.rejection_counts["fund_or_etp_name"] == 2
    assert result.rejection_counts["project_exclusion"] == 1
    assert result.rejection_counts["exchange"] == 1
    assert result.rejection_counts["price"] == 1
    assert result.rejection_counts["stale"] == 1


def test_selection_uses_only_rows_through_snapshot_and_ranks_deterministically():
    records = [
        {"cik": 1, "name": "A Inc", "ticker": "AAA", "exchange": "NYSE"},
        {"cik": 2, "name": "B Inc", "ticker": "BBB", "exchange": "Nasdaq"},
        {"cik": 3, "name": "C Inc", "ticker": "CCC", "exchange": "NYSE"},
    ]
    bars = {
        "AAA": _bars(10.0, 2_000_000.0),
        "BBB": _bars(10.0, 3_000_000.0),
        "CCC": _bars(10.0, 1_500_000.0),
    }
    future = pd.DataFrame(
        {"close": [1_000.0], "volume": [1_000_000_000.0]},
        index=[pd.Timestamp("2026-07-20")],
    )
    bars["CCC"] = pd.concat([bars["CCC"], future])
    result = select_company_pool(
        records, bars.get, price_as_of="2026-07-17", config=_config())
    assert [row["ticker"] for row in result.selected] == ["BBB", "AAA"]


def test_artifact_hash_is_order_stable_and_content_sensitive():
    one = canonical_artifact_hash({"b": 2, "a": 1})
    two = canonical_artifact_hash({"a": 1, "b": 2})
    assert one == two
    assert one != canonical_artifact_hash({"a": 1, "b": 3})


def test_snapshot_candidate_list_is_a_filtered_superset():
    records = [
        {"cik": 1, "name": "A Inc", "ticker": "AAA", "exchange": "NYSE"},
        {"cik": 2, "name": "SPDR ETF", "ticker": "FUND", "exchange": "NYSE"},
        {"cik": 3, "name": "Blocked", "ticker": "BAD", "exchange": "Nasdaq"},
        {"cik": 4, "name": "OTC Inc", "ticker": "OTC", "exchange": "OTC"},
    ]
    assert build_company_pool._snapshot_candidate_tickers(
        records, _config(), {"BAD"}) == ["AAA"]


def test_market_snapshot_preserves_sec_ticker_and_price_basis(monkeypatch):
    class FakeProvider:
        def __init__(self, *, auto_adjust, progress):
            assert auto_adjust is False
            assert progress is False

        def fetch_daily(self, symbols, *, start, end):
            assert symbols == ["AAA", "BRK-B"]
            assert end == pd.Timestamp("2026-07-18")
            return {
                symbol: SimpleNamespace(df=_bars(100.0, 1_000_000.0, n=3))
                for symbol in symbols
            }

    monkeypatch.setattr(build_company_pool, "YFinanceProvider", FakeProvider)
    snapshot, failed = build_company_pool._fetch_market_snapshot(
        ["AAA", "BRK.B"],
        start=pd.Timestamp("2026-07-01"),
        end_exclusive=pd.Timestamp("2026-07-18"),
        batch_size=100,
        pause_seconds=0.0,
    )
    assert failed == []
    assert snapshot["ticker"].unique().tolist() == ["AAA", "BRK.B"]
    assert list(snapshot) == ["ticker", "date", "close", "volume"]


def test_history_prefilter_uses_only_rows_through_cutoff(tmp_path, monkeypatch):
    bars = _bars(100.0, 1_000_000.0, n=4)
    future = pd.DataFrame(
        {"close": [100.0, 100.0], "volume": [1_000_000.0, 1_000_000.0]},
        index=pd.to_datetime(["2026-07-20", "2026-07-21"]),
    )
    monkeypatch.setattr(
        build_company_pool,
        "_load_local_bars",
        lambda _root, _ticker: pd.concat([bars, future]),
    )
    assert build_company_pool._has_required_local_history(
        tmp_path,
        "AAA",
        cutoff=pd.Timestamp("2026-07-17"),
        minimum_sessions=4,
    )
    assert not build_company_pool._has_required_local_history(
        tmp_path,
        "AAA",
        cutoff=pd.Timestamp("2026-07-17"),
        minimum_sessions=5,
    )
