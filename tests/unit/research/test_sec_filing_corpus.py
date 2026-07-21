from __future__ import annotations

from dataclasses import replace

import pytest

from core.research.sec_filing_corpus import (
    filing_document_url,
    parse_recent_submissions,
    records_frame,
)


def _payload():
    return {
        "filings": {"recent": {
            "accessionNumber": ["0001-24-000001", "0001-24-000002", "0001-24-000003"],
            "form": ["8-K", "8-K", "10-Q"],
            "filingDate": ["2024-01-02"] * 3,
            "reportDate": ["2023-12-31"] * 3,
            "acceptanceDateTime": ["2024-01-02T21:01:02.000Z"] * 3,
            "items": ["2.02,9.01", "1.01", ""],
            "primaryDocument": ["earnings.htm", "other.htm", "quarter.htm"],
            "primaryDocDescription": ["Earnings", "Other", "Quarter"],
            "size": [100, 200, 300],
            "isXBRL": [1, 0, 1],
            "isInlineXBRL": [1, 0, 1],
        }}
    }


def test_parser_selects_governed_forms_and_8k_items():
    records = parse_recent_submissions(_payload(), ticker="ABC", cik=1)
    assert [record.form for record in records] == ["8-K", "10-Q"]
    assert records[0].acceptance_datetime_utc.endswith("+00:00")
    assert records_frame(records)["accession_number"].is_unique
    assert filing_document_url(records[0]).endswith(
        "/1/000124000001/earnings.htm")


def test_parser_rejects_naive_acceptance_time():
    payload = _payload()
    payload["filings"]["recent"]["acceptanceDateTime"][0] = "2024-01-02T16:01:02"
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_recent_submissions(payload, ticker="ABC", cik=1)


def test_parser_rejects_unsafe_primary_document():
    payload = _payload()
    payload["filings"]["recent"]["primaryDocument"][0] = "../secret"
    with pytest.raises(ValueError, match="unsafe"):
        parse_recent_submissions(payload, ticker="ABC", cik=1)


def test_missing_primary_document_is_kept_for_structured_metadata_only():
    payload = _payload()
    payload["filings"]["recent"]["primaryDocument"][0] = ""
    records = parse_recent_submissions(payload, ticker="ABC", cik=1)
    assert records[0].primary_document == ""
    with pytest.raises(ValueError, match="unsafe"):
        filing_document_url(records[0])


def test_same_accession_for_different_cik_is_a_valid_cofiling():
    record = parse_recent_submissions(_payload(), ticker="ABC", cik=1)[0]
    cofiled = replace(record, ticker="XYZ", cik=2)
    assert len(records_frame([record, cofiled])) == 2


def test_same_cik_accession_duplicate_fails_closed():
    record = parse_recent_submissions(_payload(), ticker="ABC", cik=1)[0]
    with pytest.raises(ValueError, match="CIK/accession"):
        records_frame([record, record])


def test_historical_shard_top_level_arrays_are_parsed():
    shard = _payload()["filings"]["recent"]
    records = parse_recent_submissions(shard, ticker="ABC", cik=1)
    assert [record.form for record in records] == ["8-K", "10-Q"]
