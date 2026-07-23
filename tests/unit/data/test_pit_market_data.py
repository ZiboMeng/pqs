from __future__ import annotations

import pandas as pd
import pytest

from core.data.pit_market_data import (
    ACTION_COLUMNS,
    DELIST_COLUMNS,
    PitMarketDataError,
    PitMarketDataStore,
    adjustment_parity_error,
)
from core.data.pit_security_master import FORMAL_HISTORICAL_PIT, PitSecurityMaster


def _master(delisted: bool = True):
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
                    "valid_to_session_exclusive": "2020-01-03" if delisted else None,
                    "list_date": "2010-01-01",
                    "delist_date": "2020-01-03" if delisted else None,
                    "delist_code": "500",
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


def _bars():
    return pd.DataFrame(
        {
            "asset_id": ["A", "A"],
            "session": ["2020-01-02", "2020-01-03"],
            "open": [10.0, 8.0],
            "high": [11.0, 8.5],
            "low": [9.5, 0.1],
            "close": [10.5, 1.0],
            "volume": [1000.0, 2000.0],
            "currency": ["USD", "USD"],
            "source_id": ["vendor", "vendor"],
            "source_record_id": ["bar1", "bar2"],
            "source_as_of": ["2026-07-23T00:00:00Z"] * 2,
            "ingested_at_utc": ["2026-07-23T01:00:00Z"] * 2,
            "raw_payload_sha256": ["b" * 64] * 2,
            "evidence_scope": [FORMAL_HISTORICAL_PIT] * 2,
        }
    )


def _actions():
    row = {column: None for column in ACTION_COLUMNS}
    row.update(
        {
            "asset_id": "A",
            "action_id": "split-1",
            "action_type": "split",
            "ex_session": "2020-01-02",
            "pay_session": "2020-01-02",
            "split_factor": 2.0,
            "currency": "USD",
            "source_id": "vendor",
            "source_record_id": "action-1",
            "source_as_of": "2026-07-23T00:00:00Z",
            "raw_payload_sha256": "c" * 64,
            "evidence_scope": FORMAL_HISTORICAL_PIT,
        }
    )
    return pd.DataFrame([row])


def _delistings(include: bool = True):
    if not include:
        return pd.DataFrame(columns=sorted(DELIST_COLUMNS))
    row = {column: None for column in DELIST_COLUMNS}
    row.update(
        {
            "asset_id": "A",
            "delist_session": "2020-01-03",
            "disposition_type": "bankruptcy",
            "disposition_factor": 0.0,
            "currency": "USD",
            "reason_code": "500",
            "source_id": "vendor",
            "source_record_id": "delist-1",
            "source_as_of": "2026-07-23T00:00:00Z",
            "raw_payload_sha256": "d" * 64,
            "evidence_scope": FORMAL_HISTORICAL_PIT,
        }
    )
    return pd.DataFrame([row])


def test_formal_store_requires_source_bound_delisting_disposition():
    store = PitMarketDataStore(
        _bars(), _actions(), _delistings(), security_master=_master()
    )
    disposition = store.delisting_disposition("A")
    assert disposition["disposition_factor"] == 0.0
    with pytest.raises(PitMarketDataError, match="last-stale-price"):
        store.delisting_disposition("UNKNOWN")


def test_missing_delisting_disposition_fails_closed():
    with pytest.raises(PitMarketDataError, match="lacks disposition"):
        PitMarketDataStore(
            _bars(), _actions(), _delistings(False), security_master=_master()
        )


def test_invalid_ohlc_and_action_factor_are_rejected():
    bars = _bars()
    bars.loc[0, "high"] = 9.0
    with pytest.raises(PitMarketDataError, match="OHLC"):
        PitMarketDataStore(
            bars, _actions(), _delistings(), security_master=_master()
        )
    actions = _actions()
    actions.loc[0, "split_factor"] = 0.0
    with pytest.raises(PitMarketDataError, match="split_factor"):
        PitMarketDataStore(
            _bars(), actions, _delistings(), security_master=_master()
        )


def test_adjustment_parity_reports_factor_error_without_performance_metrics():
    index = pd.DatetimeIndex(["2020-01-02", "2020-02-03"])
    result = adjustment_parity_error(
        pd.Series([2.0, 1.5], index=index),
        pd.Series([2.0, 1.4], index=index),
    )
    assert result["events"] == 2
    assert result["mismatch_events"] == 1
    assert result["max_abs_factor_error"] == pytest.approx(0.1)
