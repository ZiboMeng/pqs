from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pytest

from core.data.norgate_trial_validation import (
    NorgateTrialValidationConfig,
    NorgateTrialValidationError,
    build_norgate_preflight_artifact,
    validate_norgate_runtime,
)
from core.data.pit_contract import PitDataContract

PROJECT = Path(__file__).resolve().parents[3]
CONTRACT = PitDataContract.load(PROJECT / "config" / "pit_data_v1.yaml")
CONFIG = NorgateTrialValidationConfig.load(
    PROJECT / "config" / "norgate_trial_validation_v1.yaml"
)


@dataclass(frozen=True)
class FakeSecurity:
    symbol: str
    assetid: int
    name: str


class FakeNorgateRuntime:
    package_version = "test"

    def __init__(self, *, duplicate_assetid: bool = False, running: bool = True) -> None:
        second_id = 1 if duplicate_assetid else 2
        self._running = running
        self._databases = {
            "US Equities": [FakeSecurity("CUR", 1, "Current Common")],
            "US Equities Delisted": [FakeSecurity("OLD-202601", second_id, "Old Common")],
        }
        self._symbols = {1: "CUR", second_id: "OLD-202601"}
        self._ids = {value: key for key, value in self._symbols.items()}

    def status(self) -> bool:
        return self._running

    def databases(self) -> Sequence[str]:
        return tuple(self._databases)

    def database(self, name: str) -> Sequence[Any]:
        return tuple(self._databases[name])

    def assetid(self, symbol_or_assetid: Any) -> Any:
        return self._ids[symbol_or_assetid]

    def symbol(self, assetid: Any) -> Any:
        return self._symbols[assetid]

    def metadata(self, symbol_or_assetid: Any) -> Mapping[str, Any]:
        return {
            "security_name": "present",
            "exchange_name": "present",
            "domicile": "USA",
            "base_type": "Stock Market",
            "subtype1": "Equity",
            "subtype2": "Operating/Holding Company",
            "subtype3": None,
            "first_quoted_date": "2024-01-01",
            "second_last_quoted_date": None,
        }

    def raw_price_probe(
        self, symbol_or_assetid: Any, *, limit: int
    ) -> pd.DataFrame:
        del symbol_or_assetid, limit
        return pd.DataFrame(
            {"Open": [10.0], "Close": [10.1], "Volume": [1000.0]}
        )

    def listing_probe(self, symbol_or_assetid: Any) -> Any:
        return [symbol_or_assetid, 1]

    def capital_event_probe(self, symbol_or_assetid: Any) -> Any:
        return [symbol_or_assetid, 0]


def test_config_preserves_free_non_directional_boundary():
    assert CONFIG.provider == "norgate"
    assert CONFIG.paid_subscription_enabled is False
    assert CONFIG.directional_compute_enabled is False
    assert CONFIG.credentials_must_not_be_collected is True
    assert CONFIG.personal_eula_acceptance_required is True
    assert CONFIG.expected_duration_days == 21
    assert CONFIG.expected_history_years == 2
    CONTRACT.assert_operation_allowed("vendor_field_validation")


def test_preflight_is_fail_closed_and_contains_no_vendor_rows():
    artifact = build_norgate_preflight_artifact(config=CONFIG, contract=CONTRACT)
    assert artifact["runtime_status"] == "BLOCKED_PERSONAL_TRIAL_REGISTRATION_REQUIRED"
    assert artifact["formal_source_eligible"] is False
    assert artifact["vendor_rows_persisted"] is False
    by_id = {row["capability_id"]: row for row in artifact["capabilities"]}
    assert by_id["permanent_security_id"]["status"] == "PARTIAL"
    assert by_id["ticker_and_name_history"]["status"] == "BLOCKED"
    assert by_id["delisting_disposition"]["status"] == "BLOCKED"


def test_runtime_probes_fields_but_does_not_overstate_formal_eligibility():
    artifact = validate_norgate_runtime(
        FakeNorgateRuntime(), config=CONFIG, contract=CONTRACT
    )
    assert artifact["runtime_status"] == "COMPLETE"
    assert artifact["formal_source_eligible"] is False
    assert artifact["vendor_rows_persisted"] is False
    assert artifact["sample_summary"]["records_examined"] == 2
    by_id = {row["capability_id"]: row for row in artifact["capabilities"]}
    assert by_id["permanent_security_id"]["status"] == "PASS"
    assert by_id["daily_open_close_volume"]["status"] == "PASS"
    assert by_id["listing_and_delisting_history"]["status"] == "PARTIAL"
    assert by_id["distributions_and_splits"]["status"] == "PARTIAL"
    assert by_id["delisting_disposition"]["status"] == "BLOCKED"


def test_duplicate_identity_fails_permanent_id_capability():
    artifact = validate_norgate_runtime(
        FakeNorgateRuntime(duplicate_assetid=True), config=CONFIG, contract=CONTRACT
    )
    by_id = {row["capability_id"]: row for row in artifact["capabilities"]}
    assert by_id["permanent_security_id"]["status"] == "BLOCKED"
    assert artifact["formal_source_eligible"] is False


def test_unreachable_ndu_fails_closed():
    with pytest.raises(NorgateTrialValidationError, match="not running"):
        validate_norgate_runtime(
            FakeNorgateRuntime(running=False), config=CONFIG, contract=CONTRACT
        )
