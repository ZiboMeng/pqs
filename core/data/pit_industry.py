"""Point-in-time industry classification intervals for V6."""

from __future__ import annotations

import re

import pandas as pd

from core.data.pit_security_master import FORMAL_HISTORICAL_PIT

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_COLUMNS = frozenset(
    {
        "asset_id",
        "classification_system",
        "industry_code",
        "industry_label",
        "valid_from_session",
        "valid_to_session_exclusive",
        "source_id",
        "source_record_id",
        "source_as_of",
        "raw_payload_sha256",
        "evidence_scope",
    }
)


class PitIndustryError(ValueError):
    pass


class PitIndustryStore:
    def __init__(self, intervals: pd.DataFrame):
        missing = REQUIRED_COLUMNS - set(intervals.columns)
        if missing:
            raise PitIndustryError(
                f"industry intervals lack columns: {sorted(missing)}"
            )
        frame = intervals.copy()
        for column in ("valid_from_session", "valid_to_session_exclusive"):
            frame[column] = pd.to_datetime(
                frame[column], errors="coerce"
            ).dt.tz_localize(None).dt.normalize()
        frame["source_as_of"] = pd.to_datetime(
            frame["source_as_of"], utc=True, errors="coerce"
        )
        for column in REQUIRED_COLUMNS - {
            "valid_from_session",
            "valid_to_session_exclusive",
            "source_as_of",
        }:
            frame[column] = frame[column].fillna("").astype(str).str.strip()
        self._intervals = frame.sort_values(
            ["asset_id", "classification_system", "valid_from_session"]
        ).reset_index(drop=True)
        self._validate()

    @property
    def intervals(self) -> pd.DataFrame:
        return self._intervals.copy()

    def _validate(self) -> None:
        frame = self._intervals
        if frame.empty:
            raise PitIndustryError("industry store cannot be empty")
        for column in (
            "asset_id",
            "classification_system",
            "industry_code",
            "source_id",
            "source_record_id",
        ):
            if frame[column].eq("").any():
                raise PitIndustryError(f"industry interval has empty {column}")
        if frame["valid_from_session"].isna().any() or frame["source_as_of"].isna().any():
            raise PitIndustryError("industry interval dates/provenance are required")
        if not frame["evidence_scope"].eq(FORMAL_HISTORICAL_PIT).all():
            raise PitIndustryError("formal industry store has wrong evidence scope")
        if not frame["raw_payload_sha256"].map(
            lambda value: bool(HASH_PATTERN.fullmatch(value))
        ).all():
            raise PitIndustryError("invalid industry raw_payload_sha256")
        invalid = frame["valid_to_session_exclusive"].notna() & (
            frame["valid_to_session_exclusive"] <= frame["valid_from_session"]
        )
        if invalid.any():
            raise PitIndustryError("industry valid-to must be after valid-from")
        for key, group in frame.groupby(
            ["asset_id", "classification_system"], sort=False
        ):
            rows = group.sort_values("valid_from_session")
            previous_end = None
            for row in rows.itertuples(index=False):
                if previous_end is None:
                    pass
                elif pd.isna(previous_end) or row.valid_from_session < previous_end:
                    raise PitIndustryError(f"overlapping industry intervals for {key}")
                previous_end = row.valid_to_session_exclusive

    def as_of(
        self,
        asset_id: str,
        session: str | pd.Timestamp,
        *,
        classification_system: str,
    ) -> pd.Series:
        date = pd.Timestamp(session).tz_localize(None).normalize()
        rows = self._intervals[
            self._intervals["asset_id"].eq(asset_id)
            & self._intervals["classification_system"].eq(classification_system)
            & (self._intervals["valid_from_session"] <= date)
            & (
                self._intervals["valid_to_session_exclusive"].isna()
                | (self._intervals["valid_to_session_exclusive"] > date)
            )
        ]
        if len(rows) != 1:
            raise KeyError(
                f"no unique {classification_system} industry for {asset_id} at {date.date()}"
            )
        return rows.iloc[0].copy()


__all__ = ["PitIndustryError", "PitIndustryStore", "REQUIRED_COLUMNS"]
