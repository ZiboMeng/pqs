from __future__ import annotations

import pandas as pd

from core.research.sec_document_corpus import (
    document_storage_name,
    select_primary_document_requests,
)


def _metadata() -> pd.DataFrame:
    base = {
        "ticker": "ABC",
        "cik": 1,
        "accession_number": "0001-24-000001",
        "form": "8-K",
        "filing_date": "2024-01-02",
        "report_date": "2023-12-31",
        "acceptance_datetime_utc": "2024-01-02T21:00:00Z",
        "items": "2.02",
        "primary_document": "folder/earnings.htm",
        "primary_doc_description": "Earnings",
        "size_bytes": 100,
        "is_xbrl": False,
        "is_inline_xbrl": False,
    }
    return pd.DataFrame([
        base,
        {**base, "ticker": "OLD", "acceptance_datetime_utc": "2014-01-02T21:00:00Z"},
        {**base, "ticker": "Q", "form": "10-Q"},
        {**base, "ticker": "MISS", "primary_document": ""},
    ])


def test_document_selection_filters_form_year_missing_and_dedupes():
    requests = select_primary_document_requests(
        _metadata(), forms=["8-K"], start_year=2015, end_year=2024)
    assert len(requests) == 1
    assert requests[0].url.endswith("/1/000124000001/folder/earnings.htm")
    assert requests[0].storage_name.endswith(".htm")


def test_storage_name_is_path_safe_and_deterministic():
    left = document_storage_name(1, "0001-24-000001", "a/b.htm")
    right = document_storage_name(1, "0001-24-000001", "a/b.htm")
    assert left == right
    assert "/" not in left
