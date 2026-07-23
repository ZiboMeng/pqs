"""Permanent-identity security master and causal historical universe for V6."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from core.research.dynamic_universe import (
    DynamicEligibilityConfig,
    build_dynamic_eligibility_mask,
)

FORMAL_HISTORICAL_PIT = "FORMAL_HISTORICAL_PIT"
FREE_PROSPECTIVE_PIT = "FREE_PROSPECTIVE_PIT"
SURVIVOR_BIASED_DEVELOPMENT_ONLY = "SURVIVOR_BIASED_DEVELOPMENT_ONLY"

REQUIRED_COLUMNS = frozenset(
    {
        "asset_id",
        "vendor_security_id",
        "issuer_id",
        "cik",
        "ticker",
        "name",
        "exchange",
        "share_class",
        "security_type",
        "domicile",
        "valid_from_session",
        "valid_to_session_exclusive",
        "list_date",
        "delist_date",
        "delist_code",
        "predecessor_asset_id",
        "successor_asset_id",
        "source_id",
        "source_record_id",
        "source_as_of",
        "ingested_at_utc",
        "raw_payload_sha256",
        "evidence_scope",
    }
)

FORMAL_SECURITY_TYPES = frozenset({"common_stock"})
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class SecurityMasterError(ValueError):
    """Security-master identity, interval or provenance violation."""


def _overlap(left_start, left_end, right_start, right_end) -> bool:
    infinity = pd.Timestamp.max.normalize()
    return left_start < (right_end if pd.notna(right_end) else infinity) and (
        right_start < (left_end if pd.notna(left_end) else infinity)
    )


class PitSecurityMaster:
    """Validated interval table keyed by permanent ``asset_id``."""

    def __init__(self, intervals: pd.DataFrame):
        self._intervals = self._normalize(intervals)
        self._validate()

    @property
    def intervals(self) -> pd.DataFrame:
        return self._intervals.copy()

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        missing = REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise SecurityMasterError(
                f"security master lacks required columns: {sorted(missing)}"
            )
        normalized = frame.copy()
        for column in (
            "valid_from_session",
            "valid_to_session_exclusive",
            "list_date",
            "delist_date",
        ):
            normalized[column] = pd.to_datetime(
                normalized[column], errors="coerce"
            ).dt.tz_localize(None).dt.normalize()
        normalized["source_as_of"] = pd.to_datetime(
            normalized["source_as_of"], utc=True, errors="coerce"
        )
        normalized["ingested_at_utc"] = pd.to_datetime(
            normalized["ingested_at_utc"], utc=True, errors="coerce"
        )
        for column in (
            "asset_id",
            "vendor_security_id",
            "issuer_id",
            "ticker",
            "name",
            "exchange",
            "share_class",
            "security_type",
            "domicile",
            "source_id",
            "source_record_id",
            "raw_payload_sha256",
            "evidence_scope",
        ):
            normalized[column] = normalized[column].fillna("").astype(str).str.strip()
        normalized["ticker"] = normalized["ticker"].str.upper()
        return normalized.sort_values(
            ["valid_from_session", "exchange", "ticker", "asset_id"]
        ).reset_index(drop=True)

    def _validate(self) -> None:
        frame = self._intervals
        if frame.empty:
            raise SecurityMasterError("security master cannot be empty")
        required_nonempty = (
            "asset_id",
            "issuer_id",
            "ticker",
            "name",
            "exchange",
            "security_type",
            "source_id",
            "source_record_id",
            "raw_payload_sha256",
            "evidence_scope",
        )
        for column in required_nonempty:
            if frame[column].eq("").any():
                raise SecurityMasterError(f"security master has empty {column}")
        if frame["valid_from_session"].isna().any():
            raise SecurityMasterError("valid_from_session is required")
        invalid_end = frame["valid_to_session_exclusive"].notna() & (
            frame["valid_to_session_exclusive"] <= frame["valid_from_session"]
        )
        if invalid_end.any():
            raise SecurityMasterError("valid_to_session_exclusive must be after start")
        if frame["source_as_of"].isna().any() or frame["ingested_at_utc"].isna().any():
            raise SecurityMasterError("source_as_of and ingested_at_utc are required")
        if not frame["raw_payload_sha256"].map(
            lambda value: bool(HASH_PATTERN.fullmatch(value))
        ).all():
            raise SecurityMasterError("raw_payload_sha256 must be lowercase SHA-256")

        formal = frame["evidence_scope"].eq(FORMAL_HISTORICAL_PIT)
        if formal.any():
            if frame.loc[formal, "vendor_security_id"].eq("").any():
                raise SecurityMasterError(
                    "formal historical rows require vendor_security_id"
                )
            invalid_type = ~frame.loc[formal, "security_type"].isin(
                FORMAL_SECURITY_TYPES
            )
            if invalid_type.any():
                raise SecurityMasterError(
                    "formal V6 master initially permits common_stock only"
                )

        asset_vendor_counts = (
            frame.loc[frame["vendor_security_id"].ne("")]
            .groupby("asset_id")["vendor_security_id"]
            .nunique()
        )
        if (asset_vendor_counts > 1).any():
            raise SecurityMasterError("one asset_id maps to multiple vendor IDs")
        vendor_asset_counts = (
            frame.loc[frame["vendor_security_id"].ne("")]
            .groupby("vendor_security_id")["asset_id"]
            .nunique()
        )
        if (vendor_asset_counts > 1).any():
            raise SecurityMasterError("one vendor ID maps to multiple asset_ids")

        for asset_id, group in frame.groupby("asset_id", sort=False):
            rows = group.sort_values("valid_from_session").to_dict("records")
            for previous, current in zip(rows, rows[1:]):
                if _overlap(
                    previous["valid_from_session"],
                    previous["valid_to_session_exclusive"],
                    current["valid_from_session"],
                    current["valid_to_session_exclusive"],
                ):
                    raise SecurityMasterError(
                        f"overlapping intervals for asset_id {asset_id}"
                    )

        # Ticker reuse is valid only when the exchange+ticker intervals do not
        # overlap.  The resolver can then distinguish the old and new asset by
        # session without treating ticker as permanent identity.
        for key, group in frame.groupby(["exchange", "ticker"], sort=False):
            rows = group.sort_values("valid_from_session").to_dict("records")
            for previous, current in zip(rows, rows[1:]):
                if previous["asset_id"] == current["asset_id"]:
                    continue
                if _overlap(
                    previous["valid_from_session"],
                    previous["valid_to_session_exclusive"],
                    current["valid_from_session"],
                    current["valid_to_session_exclusive"],
                ):
                    raise SecurityMasterError(
                        "overlapping ticker identity intervals for " f"{key}"
                    )

    def as_of(
        self,
        session: str | pd.Timestamp,
        *,
        evidence_scope: str | None = None,
    ) -> pd.DataFrame:
        date = pd.Timestamp(session).tz_localize(None).normalize()
        frame = self._intervals
        active = frame[
            (frame["valid_from_session"] <= date)
            & (
                frame["valid_to_session_exclusive"].isna()
                | (frame["valid_to_session_exclusive"] > date)
            )
        ]
        if evidence_scope is not None:
            active = active[active["evidence_scope"].eq(evidence_scope)]
        duplicated = active["asset_id"].duplicated(keep=False)
        if duplicated.any():
            raise SecurityMasterError(
                f"multiple active rows for asset IDs at {date.date()}"
            )
        return active.sort_values(["exchange", "ticker", "asset_id"]).reset_index(
            drop=True
        )

    def resolve_ticker(
        self,
        ticker: str,
        session: str | pd.Timestamp,
        *,
        exchange: str | None = None,
    ) -> str:
        active = self.as_of(session)
        matches = active[active["ticker"].eq(str(ticker).upper())]
        if exchange is not None:
            matches = matches[matches["exchange"].eq(exchange)]
        if len(matches) != 1:
            raise SecurityMasterError(
                f"ticker {ticker!r} resolves to {len(matches)} assets at {session}"
            )
        return str(matches.iloc[0]["asset_id"])


@dataclass(frozen=True, slots=True)
class PitUniverseConfig:
    eligibility: DynamicEligibilityConfig
    max_assets: int = 600
    evidence_scope: str = FORMAL_HISTORICAL_PIT
    security_types: tuple[str, ...] = ("common_stock",)

    def __post_init__(self) -> None:
        if self.max_assets < 1:
            raise ValueError("max_assets must be positive")


def build_pit_universe_mask(
    master: PitSecurityMaster,
    close: pd.DataFrame,
    volume: pd.DataFrame,
    *,
    decision_dates: Sequence[pd.Timestamp] | pd.DatetimeIndex,
    config: PitUniverseConfig,
) -> pd.DataFrame:
    """Build a formal, causal universe using permanent asset-id columns."""

    decisions = pd.DatetimeIndex(decision_dates)
    base = build_dynamic_eligibility_mask(
        close,
        volume,
        config.eligibility,
        decision_dates=decisions,
    )
    density_min = max(
        1,
        int(
            config.eligibility.lookback_sessions
            * config.eligibility.min_observation_density
        ),
    )
    finite = close.notna() & volume.notna() & (close > 0) & (volume >= 0)
    liquidity = (close * volume).where(finite).rolling(
        config.eligibility.lookback_sessions,
        min_periods=density_min,
    ).median()

    result = pd.DataFrame(False, index=decisions, columns=close.columns, dtype=bool)
    for date in decisions:
        active = master.as_of(date, evidence_scope=config.evidence_scope)
        active = active[active["security_type"].isin(config.security_types)]
        active_ids = set(active["asset_id"])
        candidates = [
            asset_id
            for asset_id in close.columns
            if asset_id in active_ids and bool(base.loc[date, asset_id])
        ]
        candidates.sort(
            key=lambda asset_id: (
                -float(liquidity.loc[date, asset_id]),
                str(asset_id),
            )
        )
        result.loc[date, candidates[: config.max_assets]] = True
    return result


__all__ = [
    "FORMAL_HISTORICAL_PIT",
    "FREE_PROSPECTIVE_PIT",
    "PitSecurityMaster",
    "PitUniverseConfig",
    "REQUIRED_COLUMNS",
    "SURVIVOR_BIASED_DEVELOPMENT_ONLY",
    "SecurityMasterError",
    "build_pit_universe_mask",
]
