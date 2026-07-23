"""Acceptance-bound 10-K/10-Q document corpus contract for V6."""

from __future__ import annotations

import json
import re

import pandas as pd

from core.data.pit_fundamentals import next_session_strictly_after_acceptance
from core.data.pit_security_master import FORMAL_HISTORICAL_PIT

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})
REQUIRED_DOCUMENT_COLUMNS = frozenset(
    {
        "asset_id",
        "issuer_id",
        "cik",
        "accession_number",
        "form",
        "acceptance_datetime_utc",
        "available_from_session",
        "primary_document",
        "source_url",
        "document_sha256",
        "raw_response_sha256",
        "parser_version",
        "parser_status",
        "section_spans_json",
        "failure_reason",
        "evidence_scope",
    }
)


class PitFilingCorpusError(ValueError):
    """Filing document provenance, timing or parser coverage violation."""


class PitFilingCorpus:
    def __init__(self, documents: pd.DataFrame, *, sessions: pd.DatetimeIndex):
        missing = REQUIRED_DOCUMENT_COLUMNS - set(documents.columns)
        if missing:
            raise PitFilingCorpusError(
                f"filing corpus lacks columns: {sorted(missing)}"
            )
        self.sessions = pd.DatetimeIndex(sessions)
        if self.sessions.tz is not None:
            self.sessions = self.sessions.tz_convert("America/New_York").tz_localize(
                None
            )
        self.sessions = self.sessions.normalize()
        self._documents = self._normalize(documents)
        self._validate()

    @property
    def documents(self) -> pd.DataFrame:
        return self._documents.copy()

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()
        normalized["acceptance_datetime_utc"] = pd.to_datetime(
            normalized["acceptance_datetime_utc"], utc=True, errors="coerce"
        )
        normalized["available_from_session"] = pd.to_datetime(
            normalized["available_from_session"], errors="coerce"
        ).dt.tz_localize(None).dt.normalize()
        for column in REQUIRED_DOCUMENT_COLUMNS - {
            "cik",
            "acceptance_datetime_utc",
            "available_from_session",
        }:
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        return normalized.sort_values(
            ["available_from_session", "issuer_id", "accession_number"]
        ).reset_index(drop=True)

    def _validate(self) -> None:
        frame = self._documents
        if frame.empty:
            raise PitFilingCorpusError("formal filing corpus cannot be empty")
        if not frame["form"].isin(ALLOWED_FORMS).all():
            raise PitFilingCorpusError("formal V6 corpus permits 10-K/10-Q only")
        if not frame["evidence_scope"].eq(FORMAL_HISTORICAL_PIT).all():
            raise PitFilingCorpusError("formal filing corpus has wrong evidence scope")
        required_nonempty = (
            "asset_id",
            "issuer_id",
            "accession_number",
            "form",
            "primary_document",
            "source_url",
            "document_sha256",
            "raw_response_sha256",
            "parser_version",
            "parser_status",
        )
        for column in required_nonempty:
            if frame[column].eq("").any():
                raise PitFilingCorpusError(f"filing corpus has empty {column}")
        for column in ("document_sha256", "raw_response_sha256"):
            if not frame[column].map(
                lambda value: bool(HASH_PATTERN.fullmatch(value))
            ).all():
                raise PitFilingCorpusError(f"invalid {column}")
        if frame.duplicated(["issuer_id", "accession_number"]).any():
            raise PitFilingCorpusError("duplicate issuer/accession document")
        if not frame["parser_status"].isin({"PASS", "MISSING", "ERROR"}).all():
            raise PitFilingCorpusError("invalid parser_status")
        for row in frame.itertuples(index=False):
            expected = next_session_strictly_after_acceptance(
                row.acceptance_datetime_utc, self.sessions
            )
            if pd.Timestamp(row.available_from_session) != expected:
                raise PitFilingCorpusError(
                    f"{row.accession_number}: document availability is not strict next session"
                )
            try:
                spans = json.loads(row.section_spans_json or "[]")
            except json.JSONDecodeError as exc:
                raise PitFilingCorpusError("section_spans_json is invalid") from exc
            if row.parser_status == "PASS" and not isinstance(spans, list):
                raise PitFilingCorpusError("PASS section spans must be a list")
            if row.parser_status != "PASS" and not row.failure_reason:
                raise PitFilingCorpusError(
                    "non-PASS parser rows require explicit failure_reason"
                )

    def documents_as_of(
        self,
        decision_session: str | pd.Timestamp,
        *,
        asset_id: str | None = None,
        forms: tuple[str, ...] = ("10-K", "10-Q"),
    ) -> pd.DataFrame:
        date = pd.Timestamp(decision_session).tz_localize(None).normalize()
        rows = self._documents[
            (self._documents["available_from_session"] <= date)
            & self._documents["form"].isin(forms)
        ]
        if asset_id is not None:
            rows = rows[rows["asset_id"].eq(asset_id)]
        return rows.copy().reset_index(drop=True)

    def coverage_summary(self) -> dict[str, object]:
        counts = self._documents["parser_status"].value_counts().to_dict()
        return {
            "documents": len(self._documents),
            "issuers": int(self._documents["issuer_id"].nunique()),
            "forms": self._documents["form"].value_counts().sort_index().to_dict(),
            "parser_status_counts": counts,
            "parser_pass_fraction": float(
                counts.get("PASS", 0) / len(self._documents)
            ),
        }


__all__ = [
    "ALLOWED_FORMS",
    "PitFilingCorpus",
    "PitFilingCorpusError",
    "REQUIRED_DOCUMENT_COLUMNS",
]
