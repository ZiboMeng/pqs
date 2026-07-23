from __future__ import annotations

import json

import pandas as pd
import pytest

from core.data.pit_fundamentals import (
    COMPANYFACTS_RECONCILIATION_ONLY,
    PitFundamentalError,
    PitFundamentalStore,
    extract_companyfacts_reconciliation_rows,
    next_session_strictly_after_acceptance,
)
from core.data.pit_security_master import FORMAL_HISTORICAL_PIT

SESSIONS = pd.bdate_range("2020-01-01", "2020-03-31")


def _fact(
    accession: str,
    accepted: str,
    available: str,
    value: float,
    *,
    form: str = "10-Q",
    amendment_of: str = "",
):
    return {
        "asset_id": "A1",
        "issuer_id": "I1",
        "cik": 1,
        "accession_number": accession,
        "form": form,
        "amendment_of_accession": amendment_of,
        "acceptance_datetime_utc": accepted,
        "filed_date": accepted[:10],
        "report_date": "2019-12-31",
        "period_start": "2019-10-01",
        "period_end": "2019-12-31",
        "fiscal_year": 2019,
        "fiscal_period": "Q4",
        "taxonomy": "us-gaap",
        "taxonomy_version": "2019",
        "namespace": "us-gaap",
        "concept": "Revenue",
        "label": "Revenue",
        "unit": "USD",
        "decimals": -6,
        "scale": 0,
        "dimensions_json": json.dumps({}, sort_keys=True),
        "context_id": f"CTX-{accession}",
        "value": value,
        "is_nil": False,
        "document_sha256": "a" * 64,
        "instance_sha256": "b" * 64,
        "available_from_session": available,
        "parser_version": "fixture-v1",
        "selection_rule_version": "raw-v1",
        "source_url": "https://www.sec.gov/Archives/fixture",
        "source_payload_sha256": "c" * 64,
        "evidence_scope": FORMAL_HISTORICAL_PIT,
    }


def test_acceptance_maps_to_strict_next_exchange_session_even_preopen_or_weekend():
    assert next_session_strictly_after_acceptance(
        "2020-01-02T12:00:00Z", SESSIONS
    ) == pd.Timestamp("2020-01-03")
    assert next_session_strictly_after_acceptance(
        "2020-01-03T23:00:00Z", SESSIONS
    ) == pd.Timestamp("2020-01-06")
    with pytest.raises(PitFundamentalError, match="timezone-aware"):
        next_session_strictly_after_acceptance("2020-01-02 12:00:00", SESSIONS)


def test_amendment_is_new_vintage_and_does_not_rewrite_pre_amendment_asof():
    initial = _fact(
        "0000000001-20-000001",
        "2020-01-02T21:00:00Z",
        "2020-01-03",
        100.0,
    )
    amended = _fact(
        "0000000001-20-000002",
        "2020-02-03T21:00:00Z",
        "2020-02-04",
        80.0,
        form="10-Q/A",
        amendment_of=initial["accession_number"],
    )
    store = PitFundamentalStore(pd.DataFrame([initial, amended]), sessions=SESSIONS)
    before = store.latest_period_fact_as_of(
        asset_id="A1", concept="Revenue", decision_session="2020-02-03", unit="USD"
    )
    after = store.latest_period_fact_as_of(
        asset_id="A1", concept="Revenue", decision_session="2020-02-04", unit="USD"
    )
    assert before["value"] == 100.0
    assert after["value"] == 80.0
    history = store.vintage_history(
        asset_id="A1", concept="Revenue", period_end="2019-12-31", unit="USD"
    )
    assert history["value"].tolist() == [100.0, 80.0]


def test_future_vintage_append_is_prefix_invariant():
    initial = _fact(
        "0000000001-20-000001",
        "2020-01-02T21:00:00Z",
        "2020-01-03",
        100.0,
    )
    amended = _fact(
        "0000000001-20-000002",
        "2020-02-03T21:00:00Z",
        "2020-02-04",
        80.0,
    )
    prefix = PitFundamentalStore(pd.DataFrame([initial]), sessions=SESSIONS)
    full = PitFundamentalStore(pd.DataFrame([initial, amended]), sessions=SESSIONS)
    left = prefix.facts_as_of("2020-02-03")
    right = full.facts_as_of("2020-02-03")
    pd.testing.assert_frame_equal(left, right)


def test_wrong_same_day_availability_is_rejected():
    bad = _fact(
        "0000000001-20-000001",
        "2020-01-02T12:00:00Z",
        "2020-01-02",
        100.0,
    )
    with pytest.raises(PitFundamentalError, match="strict next session"):
        PitFundamentalStore(pd.DataFrame([bad]), sessions=SESSIONS)


def test_companyfacts_adapter_preserves_old_and_amended_accessions_as_reconciliation():
    payload = {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "Revenue": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "accn": "0000000001-20-000001",
                                "end": "2019-12-31",
                                "val": 100.0,
                                "form": "10-Q",
                                "filed": "2020-01-02",
                            },
                            {
                                "accn": "0000000001-20-000002",
                                "end": "2019-12-31",
                                "val": 80.0,
                                "form": "10-Q/A",
                                "filed": "2020-02-03",
                            },
                        ]
                    },
                }
            }
        },
    }
    metadata = pd.DataFrame(
        {
            "accession_number": [
                "0000000001-20-000001",
                "0000000001-20-000002",
            ],
            "acceptance_datetime_utc": [
                "2020-01-02T21:00:00Z",
                "2020-02-03T21:00:00Z",
            ],
        }
    )
    rows = extract_companyfacts_reconciliation_rows(
        payload, metadata, asset_id="A1", sessions=SESSIONS
    )
    assert rows["value"].tolist() == [100.0, 80.0]
    assert rows["evidence_scope"].unique().tolist() == [
        COMPANYFACTS_RECONCILIATION_ONLY
    ]
