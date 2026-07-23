from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.data.pit_security_master import (
    FORMAL_HISTORICAL_PIT,
    PitSecurityMaster,
    PitUniverseConfig,
    SecurityMasterError,
    build_pit_universe_mask,
)
from core.research.dynamic_universe import DynamicEligibilityConfig


def _row(
    asset_id: str,
    ticker: str,
    start: str,
    end: str | None,
    *,
    vendor_id: str | None = None,
    exchange: str = "NASDAQ",
):
    return {
        "asset_id": asset_id,
        "vendor_security_id": vendor_id or f"V-{asset_id}",
        "issuer_id": f"I-{asset_id}",
        "cik": 1,
        "ticker": ticker,
        "name": f"Company {asset_id}",
        "exchange": exchange,
        "share_class": "A",
        "security_type": "common_stock",
        "domicile": "US",
        "valid_from_session": start,
        "valid_to_session_exclusive": end,
        "list_date": start,
        "delist_date": end,
        "delist_code": "",
        "predecessor_asset_id": "",
        "successor_asset_id": "",
        "source_id": "fixture",
        "source_record_id": f"R-{asset_id}-{start}",
        "source_as_of": "2026-07-23T00:00:00Z",
        "ingested_at_utc": "2026-07-23T01:00:00Z",
        "raw_payload_sha256": "a" * 64,
        "evidence_scope": FORMAL_HISTORICAL_PIT,
    }


def test_ticker_reuse_resolves_by_session_not_current_identity():
    master = PitSecurityMaster(
        pd.DataFrame(
            [
                _row("OLD", "ABC", "2010-01-01", "2015-01-01"),
                _row("NEW", "ABC", "2020-01-01", None),
            ]
        )
    )
    assert master.resolve_ticker("ABC", "2014-01-02") == "OLD"
    assert master.resolve_ticker("ABC", "2024-01-02") == "NEW"
    with pytest.raises(SecurityMasterError, match="0 assets"):
        master.resolve_ticker("ABC", "2017-01-02")


def test_overlapping_ticker_reuse_fails_closed():
    with pytest.raises(SecurityMasterError, match="overlapping ticker"):
        PitSecurityMaster(
            pd.DataFrame(
                [
                    _row("A", "ABC", "2010-01-01", "2020-01-01"),
                    _row("B", "ABC", "2019-01-01", None),
                ]
            )
        )


def test_formal_rows_require_vendor_permanent_identity():
    row = _row("A", "AAA", "2010-01-01", None)
    row["vendor_security_id"] = ""
    with pytest.raises(SecurityMasterError, match="vendor_security_id"):
        PitSecurityMaster(pd.DataFrame([row]))


def test_historical_universe_includes_delisted_asset_before_delist_and_not_after():
    master = PitSecurityMaster(
        pd.DataFrame(
            [
                _row("DEAD", "DEAD", "2010-01-01", "2020-01-15"),
                _row("LIVE", "LIVE", "2010-01-01", None),
            ]
        )
    )
    dates = pd.bdate_range("2019-12-02", periods=50)
    close = pd.DataFrame(
        {"DEAD": np.linspace(10, 11, len(dates)), "LIVE": np.linspace(20, 21, len(dates))},
        index=dates,
    )
    volume = pd.DataFrame(1_000_000.0, index=dates, columns=close.columns)
    cfg = PitUniverseConfig(
        eligibility=DynamicEligibilityConfig(
            min_history_sessions=5,
            lookback_sessions=3,
            min_observation_density=1.0,
            min_price=5.0,
            min_median_dollar_volume=1_000_000.0,
        ),
        max_assets=2,
    )
    decisions = pd.DatetimeIndex([dates[10], dates[40]])
    mask = build_pit_universe_mask(
        master, close, volume, decision_dates=decisions, config=cfg
    )
    assert mask.loc[dates[10], "DEAD"]
    assert mask.loc[dates[10], "LIVE"]
    assert not mask.loc[dates[40], "DEAD"]
    assert mask.loc[dates[40], "LIVE"]


def test_universe_mask_is_prefix_invariant_and_liquidity_capped():
    master = PitSecurityMaster(
        pd.DataFrame(
            [
                _row("A", "A", "2010-01-01", None),
                _row("B", "B", "2010-01-01", None),
            ]
        )
    )
    dates = pd.bdate_range("2020-01-01", periods=20)
    close = pd.DataFrame(10.0, index=dates, columns=["A", "B"])
    volume = pd.DataFrame({"A": 2_000_000.0, "B": 1_000_000.0}, index=dates)
    cfg = PitUniverseConfig(
        eligibility=DynamicEligibilityConfig(
            min_history_sessions=5,
            lookback_sessions=3,
            min_observation_density=1.0,
            min_price=5.0,
            min_median_dollar_volume=1_000_000.0,
        ),
        max_assets=1,
    )
    decision = pd.DatetimeIndex([dates[10]])
    full = build_pit_universe_mask(
        master, close, volume, decision_dates=decision, config=cfg
    )
    prefix = build_pit_universe_mask(
        master,
        close.loc[: dates[10]],
        volume.loc[: dates[10]],
        decision_dates=decision,
        config=cfg,
    )
    pd.testing.assert_frame_equal(full, prefix)
    assert full.loc[dates[10], "A"]
    assert not full.loc[dates[10], "B"]
