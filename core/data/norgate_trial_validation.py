"""Fail-closed, non-directional Norgate free-trial field validation.

The tracked artifact contains only interface names, counts, booleans and status
codes.  It never persists vendor security rows, symbols, prices, credentials or
personal registration details.  A trial can show that an interface exists; it
cannot silently turn an interface gap into a formal PIT capability.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, cast

import pandas as pd
import yaml

from core.data.pit_contract import PitDataContract


class NorgateTrialValidationError(ValueError):
    """The trial configuration or runtime evidence is invalid."""


@dataclass(frozen=True, slots=True)
class NorgateTrialValidationConfig:
    schema_version: int
    validation_id: str
    provider: str
    contract_id: str
    evidence_scope: str
    paid_subscription_enabled: bool
    directional_compute_enabled: bool
    credentials_must_not_be_collected: bool
    personal_eula_acceptance_required: bool
    tracked_artifacts_must_not_contain_vendor_rows: bool
    expected_package: str
    expected_duration_days: int
    expected_history_years: int
    current_database: str
    delisted_database: str
    max_securities_per_database: int
    max_price_rows_per_security: int
    max_timeseries_probe_securities: int
    required_capabilities: tuple[str, ...]
    documented_interfaces: Mapping[str, tuple[str, ...]]
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "NorgateTrialValidationConfig":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise NorgateTrialValidationError("validation config must be a mapping")
        boundaries = payload.get("boundaries")
        trial = payload.get("trial")
        sampling = payload.get("sampling")
        documented = payload.get("documented_interfaces")
        if not all(
            isinstance(value, Mapping)
            for value in (boundaries, trial, sampling, documented)
        ):
            raise NorgateTrialValidationError(
                "boundaries, trial, sampling and documented_interfaces are required"
            )
        boundaries_map = cast(Mapping[str, Any], boundaries)
        trial_map = cast(Mapping[str, Any], trial)
        sampling_map = cast(Mapping[str, Any], sampling)
        documented_map = cast(Mapping[str, Any], documented)
        config = cls(
            schema_version=int(payload.get("schema_version", 0)),
            validation_id=str(payload.get("validation_id", "")),
            provider=str(payload.get("provider", "")),
            contract_id=str(payload.get("contract_id", "")),
            evidence_scope=str(boundaries_map.get("evidence_scope", "")),
            paid_subscription_enabled=bool(
                boundaries_map.get("paid_subscription_enabled", True)
            ),
            directional_compute_enabled=bool(
                boundaries_map.get("directional_compute_enabled", True)
            ),
            credentials_must_not_be_collected=bool(
                boundaries_map.get("credentials_must_not_be_collected", False)
            ),
            personal_eula_acceptance_required=bool(
                boundaries_map.get("personal_eula_acceptance_required", False)
            ),
            tracked_artifacts_must_not_contain_vendor_rows=bool(
                boundaries_map.get("tracked_artifacts_must_not_contain_vendor_rows", False)
            ),
            expected_package=str(trial_map.get("expected_package", "")),
            expected_duration_days=int(trial_map.get("expected_duration_days", 0)),
            expected_history_years=int(trial_map.get("expected_history_years", 0)),
            current_database=str(trial_map.get("current_database", "")),
            delisted_database=str(trial_map.get("delisted_database", "")),
            max_securities_per_database=int(
                sampling_map.get("max_securities_per_database", 0)
            ),
            max_price_rows_per_security=int(
                sampling_map.get("max_price_rows_per_security", 0)
            ),
            max_timeseries_probe_securities=int(
                sampling_map.get("max_timeseries_probe_securities", 0)
            ),
            required_capabilities=tuple(
                str(value) for value in payload.get("required_capabilities", [])
            ),
            documented_interfaces={
                str(group): tuple(str(value) for value in values)
                for group, values in documented_map.items()
            },
            raw=payload,
        )
        config.validate()
        return config

    def validate(self) -> None:
        expected_capabilities = {
            "permanent_security_id",
            "ticker_and_name_history",
            "listing_and_delisting_history",
            "daily_open_close_volume",
            "distributions_and_splits",
            "delisting_disposition",
            "revision_policy",
        }
        if self.schema_version != 1:
            raise NorgateTrialValidationError("only schema_version=1 is supported")
        if self.provider != "norgate" or not self.validation_id:
            raise NorgateTrialValidationError("provider and validation_id are invalid")
        if self.evidence_scope != "DATA_ENGINEERING_NO_DIRECTIONAL_RETURN":
            raise NorgateTrialValidationError("trial must remain non-directional")
        if self.paid_subscription_enabled or self.directional_compute_enabled:
            raise NorgateTrialValidationError(
                "paid subscriptions and directional compute must remain disabled"
            )
        if not self.credentials_must_not_be_collected:
            raise NorgateTrialValidationError("credential collection must be forbidden")
        if not self.personal_eula_acceptance_required:
            raise NorgateTrialValidationError("licensee must personally accept the EULA")
        if not self.tracked_artifacts_must_not_contain_vendor_rows:
            raise NorgateTrialValidationError("tracked vendor rows must be forbidden")
        if set(self.required_capabilities) != expected_capabilities:
            raise NorgateTrialValidationError("required capability set is incomplete")
        if not self.expected_package or not self.current_database or not self.delisted_database:
            raise NorgateTrialValidationError("trial/database names are required")
        if self.expected_duration_days != 21 or self.expected_history_years != 2:
            raise NorgateTrialValidationError("trial duration/history must match approval")
        limits = (
            self.max_securities_per_database,
            self.max_price_rows_per_security,
            self.max_timeseries_probe_securities,
        )
        if any(value <= 0 for value in limits):
            raise NorgateTrialValidationError("sampling limits must be positive")


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    capability_id: str
    status: str
    runtime_verified: bool
    evidence: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "PARTIAL", "BLOCKED"}:
            raise NorgateTrialValidationError(f"invalid capability status {self.status}")
        if self.status == "PASS" and not self.runtime_verified:
            raise NorgateTrialValidationError("PASS requires runtime evidence")


class NorgateRuntime(Protocol):
    """Small adapter boundary used by the real module and deterministic tests."""

    @property
    def package_version(self) -> str: ...

    def status(self) -> bool: ...

    def databases(self) -> Sequence[str]: ...

    def database(self, name: str) -> Sequence[Any]: ...

    def assetid(self, symbol_or_assetid: Any) -> Any: ...

    def symbol(self, assetid: Any) -> Any: ...

    def metadata(self, symbol_or_assetid: Any) -> Mapping[str, Any]: ...

    def raw_price_probe(
        self, symbol_or_assetid: Any, *, limit: int
    ) -> pd.DataFrame: ...

    def listing_probe(self, symbol_or_assetid: Any) -> Any: ...

    def capital_event_probe(self, symbol_or_assetid: Any) -> Any: ...


class PythonNorgateRuntime:
    """Thin wrapper around the vendor's public ``norgatedata`` Python API."""

    def __init__(self, module: Any) -> None:
        self._module = module

    @classmethod
    def import_installed(cls) -> "PythonNorgateRuntime":
        try:
            module = importlib.import_module("norgatedata")
        except ImportError as exc:
            raise NorgateTrialValidationError(
                "norgatedata package is not installed in this Python environment"
            ) from exc
        return cls(module)

    @property
    def package_version(self) -> str:
        return str(getattr(self._module, "__version__", "UNKNOWN"))

    def status(self) -> bool:
        return bool(self._module.status())

    def databases(self) -> Sequence[str]:
        return tuple(str(value) for value in self._module.databases())

    def database(self, name: str) -> Sequence[Any]:
        return tuple(self._module.database(name))

    def assetid(self, symbol_or_assetid: Any) -> Any:
        return self._module.assetid(symbol_or_assetid)

    def symbol(self, assetid: Any) -> Any:
        return self._module.symbol(assetid)

    def metadata(self, symbol_or_assetid: Any) -> Mapping[str, Any]:
        functions = {
            "security_name": "security_name",
            "exchange_name": "exchange_name",
            "domicile": "domicile",
            "base_type": "base_type",
            "subtype1": "subtype1",
            "subtype2": "subtype2",
            "subtype3": "subtype3",
            "first_quoted_date": "first_quoted_date",
            "second_last_quoted_date": "second_last_quoted_date",
        }
        return {
            field: getattr(self._module, function)(symbol_or_assetid)
            for field, function in functions.items()
        }

    def raw_price_probe(
        self, symbol_or_assetid: Any, *, limit: int
    ) -> pd.DataFrame:
        frame = self._module.price_timeseries(
            symbol_or_assetid,
            stock_price_adjustment_setting=self._module.StockPriceAdjustmentType.NONE,
            padding_setting=self._module.PaddingType.NONE,
            limit=limit,
            timeseriesformat="pandas-dataframe",
        )
        if not isinstance(frame, pd.DataFrame):
            raise NorgateTrialValidationError("price_timeseries did not return a DataFrame")
        return frame

    def listing_probe(self, symbol_or_assetid: Any) -> Any:
        return self._module.major_exchange_listed_timeseries(
            symbol_or_assetid,
            timeseriesformat="numpy-recarray",
        )

    def capital_event_probe(self, symbol_or_assetid: Any) -> Any:
        return self._module.capital_event_timeseries(
            symbol_or_assetid,
            timeseriesformat="numpy-recarray",
        )


def _record_mapping(record: Any) -> Mapping[str, Any]:
    if isinstance(record, Mapping):
        return record
    if hasattr(record, "_asdict"):
        mapped = record._asdict()
        if isinstance(mapped, Mapping):
            return mapped
    if all(hasattr(record, field) for field in ("symbol", "assetid", "name")):
        return {
            "symbol": getattr(record, "symbol"),
            "assetid": getattr(record, "assetid"),
            "name": getattr(record, "name"),
        }
    if isinstance(record, (tuple, list)) and len(record) >= 3:
        return {"symbol": record[0], "assetid": record[1], "name": record[2]}
    raise NorgateTrialValidationError("unsupported database record shape")


def _field(mapping: Mapping[str, Any], name: str) -> Any:
    by_lower = {str(key).lower(): value for key, value in mapping.items()}
    aliases = {"name": ("name", "securityname")}
    for candidate in aliases.get(name.lower(), (name.lower(),)):
        if candidate in by_lower:
            return by_lower[candidate]
    return None


def _base_artifact(
    *, config: NorgateTrialValidationConfig, contract: PitDataContract
) -> dict[str, Any]:
    if config.contract_id != contract.contract_id:
        raise NorgateTrialValidationError("trial config is bound to another PIT contract")
    contract.assert_operation_allowed("vendor_field_validation")
    return {
        "schema_version": 1,
        "validation_id": config.validation_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": config.provider,
        "contract_id": contract.contract_id,
        "evidence_scope": config.evidence_scope,
        "expected_package": config.expected_package,
        "expected_duration_days": config.expected_duration_days,
        "expected_history_years": config.expected_history_years,
        "paid_subscription_created": False,
        "directional_compute_performed": False,
        "credentials_collected": False,
        "vendor_rows_persisted": False,
    }


def build_norgate_preflight_artifact(
    *, config: NorgateTrialValidationConfig, contract: PitDataContract
) -> dict[str, Any]:
    """Build documentation/environment preflight without pretending it is runtime QA."""

    artifact = _base_artifact(config=config, contract=contract)
    capabilities = (
        CapabilityEvidence(
            "permanent_security_id",
            "PARTIAL",
            False,
            ("documented:assetid", "documented:database"),
            "unique unchanging assetid is documented but trial data is not connected",
        ),
        CapabilityEvidence(
            "ticker_and_name_history",
            "BLOCKED",
            False,
            ("documented:assetid_to_current_symbol_only",),
            "public Python API does not document dated ticker/name alias intervals",
        ),
        CapabilityEvidence(
            "listing_and_delisting_history",
            "PARTIAL",
            False,
            (
                "documented:major_exchange_listed_timeseries",
                "documented:first_quoted_date",
                "documented:second_last_quoted_date",
            ),
            "interfaces are documented but trial coverage and delisting semantics are unverified",
        ),
        CapabilityEvidence(
            "daily_open_close_volume",
            "PARTIAL",
            False,
            ("documented:price_timeseries", "documented:no_adjustment_no_padding"),
            "raw daily interface is documented but trial fields are unverified",
        ),
        CapabilityEvidence(
            "distributions_and_splits",
            "BLOCKED",
            False,
            ("documented:capital_event_binary_indicator",),
            "binary capital-event indication is not an auditable event type/amount ledger",
        ),
        CapabilityEvidence(
            "delisting_disposition",
            "BLOCKED",
            False,
            ("documented:no_disposition_interface",),
            "public Python API does not document delisting reason, consideration or disposition amount",
        ),
        CapabilityEvidence(
            "revision_policy",
            "BLOCKED",
            False,
            ("documented:corrections_may_be_published",),
            "no immutable licensed edition/export and replay policy has been runtime verified",
        ),
    )
    artifact.update(
        {
            "runtime_status": "BLOCKED_PERSONAL_TRIAL_REGISTRATION_REQUIRED",
            "formal_source_eligible": False,
            "capabilities": [asdict(row) for row in capabilities],
            "personal_action_required": (
                "licensee must register with genuine identity and personally accept EULA"
            ),
        }
    )
    contract.assert_artifact_non_directional(artifact)
    return artifact


def validate_norgate_runtime(
    runtime: NorgateRuntime,
    *,
    config: NorgateTrialValidationConfig,
    contract: PitDataContract,
) -> dict[str, Any]:
    """Probe a running free trial and retain aggregate/interface evidence only."""

    artifact = _base_artifact(config=config, contract=contract)
    if not runtime.status():
        raise NorgateTrialValidationError("NDU is not running or not reachable")
    database_names = tuple(runtime.databases())
    required_databases = {config.current_database, config.delisted_database}
    if not required_databases.issubset(database_names):
        missing = sorted(required_databases - set(database_names))
        raise NorgateTrialValidationError(f"trial databases are missing: {missing}")

    record_counts: dict[str, int] = {}
    sampled_records: list[Mapping[str, Any]] = []
    for database_name in (config.current_database, config.delisted_database):
        records = runtime.database(database_name)
        record_counts[database_name] = len(records)
        bounded = records[: config.max_securities_per_database]
        mapped = [_record_mapping(record) for record in bounded]
        sampled_records.extend(mapped)

    assetids = [_field(row, "assetid") for row in sampled_records]
    symbols = [_field(row, "symbol") for row in sampled_records]
    names = [_field(row, "name") for row in sampled_records]
    non_null_assetids = [value for value in assetids if value not in (None, "")]
    permanent_id_pass = bool(sampled_records) and len(non_null_assetids) == len(
        sampled_records
    ) and len(set(non_null_assetids)) == len(non_null_assetids)

    roundtrip_checks = 0
    metadata_field_presence: dict[str, int] = {}
    raw_daily_probes = 0
    raw_daily_required_columns = {"Open", "Close", "Volume"}
    raw_daily_column_sets: set[tuple[str, ...]] = set()
    listing_probes = 0
    capital_event_probes = 0
    probe_assetids = non_null_assetids[: config.max_timeseries_probe_securities]
    for assetid in probe_assetids:
        if runtime.assetid(runtime.symbol(assetid)) == assetid:
            roundtrip_checks += 1
        metadata = runtime.metadata(assetid)
        for field, value in metadata.items():
            if value not in (None, ""):
                metadata_field_presence[field] = metadata_field_presence.get(field, 0) + 1
        frame = runtime.raw_price_probe(
            assetid, limit=config.max_price_rows_per_security
        )
        columns = tuple(sorted(str(column) for column in frame.columns))
        raw_daily_column_sets.add(columns)
        if raw_daily_required_columns.issubset(set(frame.columns)) and not frame.empty:
            raw_daily_probes += 1
        if runtime.listing_probe(assetid) is not None:
            listing_probes += 1
        if runtime.capital_event_probe(assetid) is not None:
            capital_event_probes += 1

    permanent_runtime_pass = permanent_id_pass and roundtrip_checks == len(probe_assetids)
    raw_daily_pass = bool(probe_assetids) and raw_daily_probes == len(probe_assetids)
    listing_partial = bool(probe_assetids) and listing_probes == len(probe_assetids)
    action_indicator_runtime = bool(probe_assetids) and capital_event_probes == len(
        probe_assetids
    )

    capabilities = (
        CapabilityEvidence(
            "permanent_security_id",
            "PASS" if permanent_runtime_pass else "BLOCKED",
            permanent_runtime_pass,
            ("runtime:assetid_non_null_unique", "runtime:assetid_symbol_roundtrip"),
            "bounded current/delisted sample has stable unique IDs"
            if permanent_runtime_pass
            else "asset IDs or round-trip identity failed",
        ),
        CapabilityEvidence(
            "ticker_and_name_history",
            "BLOCKED",
            False,
            ("runtime:current_symbol_and_name_only",),
            "runtime metadata still exposes current identity, not dated alias intervals",
        ),
        CapabilityEvidence(
            "listing_and_delisting_history",
            "PARTIAL" if listing_partial else "BLOCKED",
            listing_partial,
            ("runtime:listing_timeseries", "runtime:delisted_database"),
            "listing series and delisted inventory exist, but disposition semantics are separate",
        ),
        CapabilityEvidence(
            "daily_open_close_volume",
            "PASS" if raw_daily_pass else "BLOCKED",
            raw_daily_pass,
            ("runtime:no_adjustment_no_padding_price_probe",),
            "raw Open/Close/Volume present in all bounded probes"
            if raw_daily_pass
            else "required raw daily fields were absent or empty",
        ),
        CapabilityEvidence(
            "distributions_and_splits",
            "PARTIAL" if action_indicator_runtime else "BLOCKED",
            action_indicator_runtime,
            ("runtime:capital_event_indicator",),
            "capital-event signal is reachable but lacks formal event type/amount provenance",
        ),
        CapabilityEvidence(
            "delisting_disposition",
            "BLOCKED",
            False,
            ("runtime:no_disposition_interface",),
            "no source-bound reason/consideration/disposition amount was exposed",
        ),
        CapabilityEvidence(
            "revision_policy",
            "BLOCKED",
            False,
            ("runtime:mutable_local_database",),
            "trial has no certified immutable edition and replay contract",
        ),
    )
    all_required_pass = all(row.status == "PASS" for row in capabilities)
    artifact.update(
        {
            "runtime_status": "COMPLETE",
            "package_version": runtime.package_version,
            "available_database_names": sorted(database_names),
            "database_record_counts": record_counts,
            "sample_summary": {
                "records_examined": len(sampled_records),
                "assetids_non_null": len(non_null_assetids),
                "symbols_non_null": sum(value not in (None, "") for value in symbols),
                "names_non_null": sum(value not in (None, "") for value in names),
                "identity_roundtrips": roundtrip_checks,
                "metadata_field_presence": metadata_field_presence,
                "raw_daily_probes": raw_daily_probes,
                "raw_daily_column_sets": [list(value) for value in sorted(raw_daily_column_sets)],
                "listing_probes": listing_probes,
                "capital_event_probes": capital_event_probes,
            },
            "formal_source_eligible": all_required_pass,
            "capabilities": [asdict(row) for row in capabilities],
        }
    )
    contract.assert_artifact_non_directional(artifact)
    return artifact


__all__ = [
    "CapabilityEvidence",
    "NorgateRuntime",
    "NorgateTrialValidationConfig",
    "NorgateTrialValidationError",
    "PythonNorgateRuntime",
    "build_norgate_preflight_artifact",
    "validate_norgate_runtime",
]
