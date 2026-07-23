from __future__ import annotations

import json

import pandas as pd
import pytest

from core.data.pit_filings import PitFilingCorpus, PitFilingCorpusError
from core.data.pit_security_master import FORMAL_HISTORICAL_PIT

SESSIONS = pd.bdate_range("2020-01-01", "2020-04-01")


def _document(accession: str, accepted: str, available: str, status: str = "PASS"):
    return {
        "asset_id": "A",
        "issuer_id": "I",
        "cik": 1,
        "accession_number": accession,
        "form": "10-Q",
        "acceptance_datetime_utc": accepted,
        "available_from_session": available,
        "primary_document": "form10q.htm",
        "source_url": "https://www.sec.gov/Archives/fixture",
        "document_sha256": "a" * 64,
        "raw_response_sha256": "b" * 64,
        "parser_version": "sections-v1",
        "parser_status": status,
        "section_spans_json": json.dumps(
            [{"section": "MD&A", "start": 0, "end": 100}] if status == "PASS" else []
        ),
        "failure_reason": "" if status == "PASS" else "malformed html",
        "evidence_scope": FORMAL_HISTORICAL_PIT,
    }


def test_corpus_is_acceptance_bound_and_future_append_prefix_invariant():
    first = _document(
        "0000000001-20-000001", "2020-01-02T21:00:00Z", "2020-01-03"
    )
    future = _document(
        "0000000001-20-000002", "2020-03-02T21:00:00Z", "2020-03-03"
    )
    prefix = PitFilingCorpus(pd.DataFrame([first]), sessions=SESSIONS)
    full = PitFilingCorpus(pd.DataFrame([first, future]), sessions=SESSIONS)
    pd.testing.assert_frame_equal(
        prefix.documents_as_of("2020-02-01"), full.documents_as_of("2020-02-01")
    )
    assert len(full.documents_as_of("2020-03-03")) == 2


def test_parser_failures_remain_in_coverage_with_reason():
    corpus = PitFilingCorpus(
        pd.DataFrame(
            [
                _document(
                    "0000000001-20-000001",
                    "2020-01-02T21:00:00Z",
                    "2020-01-03",
                ),
                _document(
                    "0000000001-20-000002",
                    "2020-03-02T21:00:00Z",
                    "2020-03-03",
                    status="ERROR",
                ),
            ]
        ),
        sessions=SESSIONS,
    )
    summary = corpus.coverage_summary()
    assert summary["documents"] == 2
    assert summary["parser_status_counts"] == {"PASS": 1, "ERROR": 1}
    assert summary["parser_pass_fraction"] == 0.5


def test_same_day_availability_and_silent_parser_drop_are_rejected():
    same_day = _document(
        "0000000001-20-000001", "2020-01-02T12:00:00Z", "2020-01-02"
    )
    with pytest.raises(PitFilingCorpusError, match="strict next session"):
        PitFilingCorpus(pd.DataFrame([same_day]), sessions=SESSIONS)
    failed = _document(
        "0000000001-20-000001",
        "2020-01-02T21:00:00Z",
        "2020-01-03",
        status="ERROR",
    )
    failed["failure_reason"] = ""
    with pytest.raises(PitFilingCorpusError, match="failure_reason"):
        PitFilingCorpus(pd.DataFrame([failed]), sessions=SESSIONS)
