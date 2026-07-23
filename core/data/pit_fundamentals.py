"""Accession-bound, acceptance-timed fundamental vintages for V6 PIT data."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

import pandas as pd

from core.data.pit_security_master import FORMAL_HISTORICAL_PIT

COMPANYFACTS_RECONCILIATION_ONLY = "COMPANYFACTS_RECONCILIATION_ONLY"
ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

FORMAL_FACT_COLUMNS = frozenset(
    {
        "asset_id",
        "issuer_id",
        "cik",
        "accession_number",
        "form",
        "amendment_of_accession",
        "acceptance_datetime_utc",
        "filed_date",
        "report_date",
        "period_start",
        "period_end",
        "fiscal_year",
        "fiscal_period",
        "taxonomy",
        "taxonomy_version",
        "namespace",
        "concept",
        "label",
        "unit",
        "decimals",
        "scale",
        "dimensions_json",
        "context_id",
        "value",
        "is_nil",
        "document_sha256",
        "instance_sha256",
        "available_from_session",
        "parser_version",
        "selection_rule_version",
        "source_url",
        "source_payload_sha256",
        "evidence_scope",
    }
)


class PitFundamentalError(ValueError):
    """A filing fact lacks formal provenance or violates PIT timing."""


def _normalize_sessions(sessions: pd.DatetimeIndex) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(sessions)
    if index.tz is not None:
        index = index.tz_convert("America/New_York").tz_localize(None)
    index = index.normalize()
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise PitFundamentalError("session calendar must be sorted and unique")
    return index


def next_session_strictly_after_acceptance(
    acceptance_datetime: str | pd.Timestamp,
    sessions: pd.DatetimeIndex,
) -> pd.Timestamp:
    """Map acceptance to the first exchange-session date after local date.

    V6 deliberately applies this conservative rule even when a filing was
    accepted before the open.  It removes pre-open/after-close branching from
    the daily strategy and guarantees that same-date execution is impossible.
    """

    accepted = pd.Timestamp(acceptance_datetime)
    if accepted.tzinfo is None:
        raise PitFundamentalError("acceptance datetime must be timezone-aware")
    local_date = accepted.tz_convert("America/New_York").tz_localize(None).normalize()
    calendar = _normalize_sessions(sessions)
    position = calendar.searchsorted(local_date, side="right")
    if position >= len(calendar):
        raise PitFundamentalError("session calendar does not extend past acceptance")
    return calendar[position]


class PitFundamentalStore:
    """Validated formal filing facts preserving every amendment vintage."""

    def __init__(self, facts: pd.DataFrame, *, sessions: pd.DatetimeIndex):
        self.sessions = _normalize_sessions(sessions)
        self._facts = self._normalize(facts)
        self._validate()

    @property
    def facts(self) -> pd.DataFrame:
        return self._facts.copy()

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        missing = FORMAL_FACT_COLUMNS - set(frame.columns)
        if missing:
            raise PitFundamentalError(
                f"formal fact table lacks columns: {sorted(missing)}"
            )
        normalized = frame.copy()
        normalized["acceptance_datetime_utc"] = pd.to_datetime(
            normalized["acceptance_datetime_utc"], utc=True, errors="coerce"
        )
        for column in (
            "filed_date",
            "report_date",
            "period_start",
            "period_end",
            "available_from_session",
        ):
            normalized[column] = pd.to_datetime(
                normalized[column], errors="coerce"
            ).dt.tz_localize(None).dt.normalize()
        for column in (
            "asset_id",
            "issuer_id",
            "accession_number",
            "form",
            "amendment_of_accession",
            "taxonomy",
            "taxonomy_version",
            "namespace",
            "concept",
            "label",
            "unit",
            "dimensions_json",
            "context_id",
            "document_sha256",
            "instance_sha256",
            "parser_version",
            "selection_rule_version",
            "source_url",
            "source_payload_sha256",
            "evidence_scope",
        ):
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        return normalized.sort_values(
            [
                "available_from_session",
                "asset_id",
                "concept",
                "period_end",
                "accession_number",
                "context_id",
            ]
        ).reset_index(drop=True)

    def _validate(self) -> None:
        frame = self._facts
        if frame.empty:
            raise PitFundamentalError("formal fact store cannot be empty")
        required_nonempty = (
            "asset_id",
            "issuer_id",
            "accession_number",
            "form",
            "namespace",
            "concept",
            "unit",
            "context_id",
            "document_sha256",
            "instance_sha256",
            "parser_version",
            "selection_rule_version",
            "source_url",
            "source_payload_sha256",
            "evidence_scope",
        )
        for column in required_nonempty:
            if frame[column].eq("").any():
                raise PitFundamentalError(f"formal fact has empty {column}")
        if not frame["accession_number"].map(
            lambda value: bool(ACCESSION_PATTERN.fullmatch(value))
        ).all():
            raise PitFundamentalError("invalid SEC accession number")
        for column in (
            "document_sha256",
            "instance_sha256",
            "source_payload_sha256",
        ):
            if not frame[column].map(
                lambda value: bool(HASH_PATTERN.fullmatch(value))
            ).all():
                raise PitFundamentalError(f"{column} must be lowercase SHA-256")
        if not frame["evidence_scope"].eq(FORMAL_HISTORICAL_PIT).all():
            raise PitFundamentalError(
                "formal fact store accepts FORMAL_HISTORICAL_PIT rows only"
            )
        if frame["acceptance_datetime_utc"].isna().any():
            raise PitFundamentalError("acceptance datetime is required")
        if frame["available_from_session"].isna().any():
            raise PitFundamentalError("available_from_session is required")
        if frame["period_end"].isna().any():
            raise PitFundamentalError("period_end is required")

        for row in frame.itertuples(index=False):
            expected = next_session_strictly_after_acceptance(
                row.acceptance_datetime_utc, self.sessions
            )
            if pd.Timestamp(row.available_from_session) != expected:
                raise PitFundamentalError(
                    f"{row.accession_number}: available_from_session must equal "
                    f"strict next session {expected.date()}"
                )
            try:
                dimensions = json.loads(row.dimensions_json)
            except json.JSONDecodeError as exc:
                raise PitFundamentalError("dimensions_json must be valid JSON") from exc
            if not isinstance(dimensions, (dict, list)):
                raise PitFundamentalError("dimensions_json must encode mapping/list")

        duplicate_key = frame.duplicated(
            [
                "asset_id",
                "accession_number",
                "context_id",
                "namespace",
                "concept",
                "unit",
                "dimensions_json",
            ],
            keep=False,
        )
        if duplicate_key.any():
            raise PitFundamentalError("duplicate accession/context/concept fact key")

    def facts_as_of(
        self,
        decision_session: str | pd.Timestamp,
        *,
        asset_id: str | None = None,
        concept: str | None = None,
    ) -> pd.DataFrame:
        date = pd.Timestamp(decision_session).tz_localize(None).normalize()
        visible = self._facts[self._facts["available_from_session"] <= date]
        if asset_id is not None:
            visible = visible[visible["asset_id"].eq(asset_id)]
        if concept is not None:
            visible = visible[visible["concept"].eq(concept)]
        return visible.copy().reset_index(drop=True)

    def vintage_history(
        self,
        *,
        asset_id: str,
        concept: str,
        period_end: str | pd.Timestamp,
        unit: str | None = None,
    ) -> pd.DataFrame:
        end = pd.Timestamp(period_end).tz_localize(None).normalize()
        rows = self._facts[
            self._facts["asset_id"].eq(asset_id)
            & self._facts["concept"].eq(concept)
            & self._facts["period_end"].eq(end)
        ]
        if unit is not None:
            rows = rows[rows["unit"].eq(unit)]
        return rows.sort_values(
            ["available_from_session", "accession_number", "context_id"]
        ).reset_index(drop=True)

    def latest_period_fact_as_of(
        self,
        *,
        asset_id: str,
        concept: str,
        decision_session: str | pd.Timestamp,
        unit: str | None = None,
    ) -> pd.Series:
        visible = self.facts_as_of(
            decision_session, asset_id=asset_id, concept=concept
        )
        if unit is not None:
            visible = visible[visible["unit"].eq(unit)]
        if visible.empty:
            raise KeyError(
                f"no visible fact for {asset_id}/{concept} at {decision_session}"
            )
        latest_period = visible["period_end"].max()
        period_rows = visible[visible["period_end"].eq(latest_period)]
        latest_available = period_rows["available_from_session"].max()
        latest = period_rows[
            period_rows["available_from_session"].eq(latest_available)
        ]
        if len(latest) != 1:
            raise PitFundamentalError(
                "latest fact is ambiguous across contexts/dimensions; use explicit selector"
            )
        return latest.iloc[0].copy()


def extract_companyfacts_reconciliation_rows(
    payload: Mapping[str, Any],
    submissions_metadata: pd.DataFrame,
    *,
    asset_id: str,
    sessions: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Preserve Company Facts rows without pretending they are formal facts.

    Company Facts lacks the complete filing-instance context/dimension surface
    required by the V6 formal store.  This adapter joins acceptance by accession
    and is useful for reconciliation only.  It intentionally keeps every
    accession row, including older values later amended or restated.
    """

    required = {"accession_number", "acceptance_datetime_utc"}
    missing = required - set(submissions_metadata.columns)
    if missing:
        raise PitFundamentalError(
            f"submissions metadata lacks columns: {sorted(missing)}"
        )
    metadata = submissions_metadata.copy()
    metadata["acceptance_datetime_utc"] = pd.to_datetime(
        metadata["acceptance_datetime_utc"], utc=True, errors="coerce"
    )
    if metadata["acceptance_datetime_utc"].isna().any():
        raise PitFundamentalError("submissions acceptance timestamps are required")
    if metadata["accession_number"].duplicated().any():
        raise PitFundamentalError("submissions accession numbers must be unique")
    acceptance_by_accession = metadata.set_index("accession_number")[
        "acceptance_datetime_utc"
    ].to_dict()

    rows: list[dict[str, Any]] = []
    facts = payload.get("facts", {})
    if not isinstance(facts, Mapping):
        raise PitFundamentalError("Company Facts payload facts must be a mapping")
    for namespace, concepts in facts.items():
        if not isinstance(concepts, Mapping):
            continue
        for concept, definition in concepts.items():
            if not isinstance(definition, Mapping):
                continue
            label = str(definition.get("label", ""))
            units = definition.get("units", {})
            if not isinstance(units, Mapping):
                continue
            for unit, observations in units.items():
                if not isinstance(observations, list):
                    continue
                for observation in observations:
                    accession = str(observation.get("accn", ""))
                    accepted = acceptance_by_accession.get(accession)
                    if accepted is None:
                        continue
                    rows.append(
                        {
                            "asset_id": asset_id,
                            "cik": payload.get("cik"),
                            "accession_number": accession,
                            "acceptance_datetime_utc": accepted,
                            "available_from_session": next_session_strictly_after_acceptance(
                                accepted, sessions
                            ),
                            "namespace": str(namespace),
                            "concept": str(concept),
                            "label": label,
                            "unit": str(unit),
                            "start": observation.get("start"),
                            "end": observation.get("end"),
                            "value": observation.get("val"),
                            "form": observation.get("form"),
                            "filed": observation.get("filed"),
                            "fiscal_year": observation.get("fy"),
                            "fiscal_period": observation.get("fp"),
                            "frame": observation.get("frame"),
                            "evidence_scope": COMPANYFACTS_RECONCILIATION_ONLY,
                        }
                    )
    return pd.DataFrame(rows).sort_values(
        ["available_from_session", "accession_number", "namespace", "concept", "unit"]
    ).reset_index(drop=True) if rows else pd.DataFrame()


__all__ = [
    "COMPANYFACTS_RECONCILIATION_ONLY",
    "FORMAL_FACT_COLUMNS",
    "PitFundamentalError",
    "PitFundamentalStore",
    "extract_companyfacts_reconciliation_rows",
    "next_session_strictly_after_acceptance",
]
