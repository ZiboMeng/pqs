from __future__ import annotations

import json
from pathlib import Path

from core.data.pit_contract import PitDataContract
from core.data.prospective_pit import (
    collect_prospective_snapshot,
    parse_nasdaq_listed,
    parse_other_listed,
    parse_sec_company_tickers_exchange,
    verify_prospective_ledger,
)

PROJECT = Path(__file__).resolve().parents[3]
CONTRACT = PitDataContract.load(PROJECT / "config" / "pit_data_v1.yaml")


def _payloads(sec_ticker: str = "AAA"):
    sec = json.dumps(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[1, "Alpha", sec_ticker, "Nasdaq"]],
        }
    ).encode()
    nasdaq = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\r\n"
        "AAA|Alpha Inc|Q|N|N|100|N|N\r\n"
        "File Creation Time: 0101202021:00|||||||\r\n"
    ).encode()
    other = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol\r\n"
        "BBB|Beta Inc|N|BBB|N|100|N|BBB\r\n"
        "File Creation Time: 0101202021:00|||||||\r\n"
    ).encode()
    return {
        "sec_company_tickers_exchange": {"url": "sec", "content": sec},
        "nasdaq_listed": {"url": "nasdaq", "content": nasdaq},
        "other_listed": {"url": "other", "content": other},
    }


def test_official_snapshot_parsers_produce_prospective_records():
    payloads = _payloads()
    assert parse_sec_company_tickers_exchange(
        payloads["sec_company_tickers_exchange"]["content"]
    )[0]["ticker"] == "AAA"
    assert parse_nasdaq_listed(payloads["nasdaq_listed"]["content"])[0][
        "exchange"
    ] == "NASDAQ"
    assert parse_other_listed(payloads["other_listed"]["content"])[0][
        "exchange"
    ] == "NYSE"


def test_snapshots_are_immutable_diffed_and_hash_chained(tmp_path: Path):
    first = collect_prospective_snapshot(
        _payloads("AAA"),
        output_root=tmp_path,
        captured_at="2026-07-23T10:00:00Z",
        contract=CONTRACT,
    )
    second = collect_prospective_snapshot(
        _payloads("CCC"),
        output_root=tmp_path,
        captured_at="2026-07-24T10:00:00Z",
        contract=CONTRACT,
    )
    assert first["diff_counts"]["added"] == 3
    assert second["diff_counts"] == {"added": 1, "removed": 1, "changed": 0}
    verified = verify_prospective_ledger(tmp_path)
    assert verified["events"] == 2
    assert verified["integrity_pass"] is True
