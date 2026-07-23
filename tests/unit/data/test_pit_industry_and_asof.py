from __future__ import annotations

import pandas as pd
import pytest

from core.data.pit_asof import PitAsOfData, PitAsOfError
from core.data.pit_industry import PitIndustryStore
from core.data.pit_security_master import FORMAL_HISTORICAL_PIT, PitSecurityMaster


def _master():
    return PitSecurityMaster(
        pd.DataFrame(
            [
                {
                    "asset_id": "A",
                    "vendor_security_id": "VA",
                    "issuer_id": "IA",
                    "cik": 1,
                    "ticker": "AAA",
                    "name": "Alpha",
                    "exchange": "NASDAQ",
                    "share_class": "A",
                    "security_type": "common_stock",
                    "domicile": "US",
                    "valid_from_session": "2010-01-01",
                    "valid_to_session_exclusive": None,
                    "list_date": "2010-01-01",
                    "delist_date": None,
                    "delist_code": "",
                    "predecessor_asset_id": "",
                    "successor_asset_id": "",
                    "source_id": "vendor",
                    "source_record_id": "master-A",
                    "source_as_of": "2026-07-23T00:00:00Z",
                    "ingested_at_utc": "2026-07-23T01:00:00Z",
                    "raw_payload_sha256": "a" * 64,
                    "evidence_scope": FORMAL_HISTORICAL_PIT,
                }
            ]
        )
    )


def _industries():
    base = {
        "asset_id": "A",
        "classification_system": "SIC",
        "industry_label": "Fixture",
        "source_id": "vendor",
        "source_as_of": "2026-07-23T00:00:00Z",
        "raw_payload_sha256": "b" * 64,
        "evidence_scope": FORMAL_HISTORICAL_PIT,
    }
    return PitIndustryStore(
        pd.DataFrame(
            [
                {
                    **base,
                    "industry_code": "1000",
                    "valid_from_session": "2010-01-01",
                    "valid_to_session_exclusive": "2020-01-01",
                    "source_record_id": "sic-old",
                },
                {
                    **base,
                    "industry_code": "2000",
                    "valid_from_session": "2020-01-01",
                    "valid_to_session_exclusive": None,
                    "source_record_id": "sic-new",
                },
            ]
        )
    )


def test_industry_reclassification_is_point_in_time_not_backfilled():
    store = _industries()
    assert store.as_of("A", "2019-12-31", classification_system="SIC")[
        "industry_code"
    ] == "1000"
    assert store.as_of("A", "2020-01-02", classification_system="SIC")[
        "industry_code"
    ] == "2000"


def test_unified_asof_api_requires_explicit_session_and_provenance():
    dates = pd.DatetimeIndex(["2020-01-31"])
    mask = pd.DataFrame({"A": [True]}, index=dates)
    api = PitAsOfData(
        security_master=_master(), industries=_industries(), universe_mask=mask
    )
    state = api.get_security_state("A", "2020-01-31")
    assert state["source_record_id"] == "master-A"
    eligible = api.get_eligible_assets("2020-01-31")
    assert eligible.asset_ids == ("A",)
    industry = api.get_industry("A", "2020-01-31", classification_system="SIC")
    assert industry["source_record_id"] == "sic-new"
    with pytest.raises(PitAsOfError, match="market data"):
        api.get_price("A", "2020-01-31")


def test_universe_mask_cannot_include_inactive_asset():
    mask = pd.DataFrame({"A": [True]}, index=pd.DatetimeIndex(["2000-01-31"]))
    api = PitAsOfData(security_master=_master(), universe_mask=mask)
    with pytest.raises(PitAsOfError, match="inactive"):
        api.get_eligible_assets("2000-01-31")
