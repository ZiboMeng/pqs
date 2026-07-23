"""Formal V6 market-data, corporate-action and delisting contracts."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from core.data.pit_security_master import FORMAL_HISTORICAL_PIT, PitSecurityMaster

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BAR_COLUMNS = frozenset(
    {
        "asset_id",
        "session",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "currency",
        "source_id",
        "source_record_id",
        "source_as_of",
        "ingested_at_utc",
        "raw_payload_sha256",
        "evidence_scope",
    }
)
ACTION_COLUMNS = frozenset(
    {
        "asset_id",
        "action_id",
        "action_type",
        "ex_session",
        "pay_session",
        "cash_amount",
        "split_factor",
        "currency",
        "source_id",
        "source_record_id",
        "source_as_of",
        "raw_payload_sha256",
        "evidence_scope",
    }
)
DELIST_COLUMNS = frozenset(
    {
        "asset_id",
        "delist_session",
        "disposition_type",
        "cash_consideration",
        "stock_successor_asset_id",
        "disposition_factor",
        "currency",
        "reason_code",
        "source_id",
        "source_record_id",
        "source_as_of",
        "raw_payload_sha256",
        "evidence_scope",
    }
)


class PitMarketDataError(ValueError):
    """Formal price/action/delisting data is incomplete or inconsistent."""


def _require_columns(frame: pd.DataFrame, required: frozenset[str], name: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise PitMarketDataError(f"{name} lacks columns: {sorted(missing)}")


def _validate_provenance(frame: pd.DataFrame, name: str) -> None:
    for column in ("asset_id", "source_id", "source_record_id", "evidence_scope"):
        if frame[column].fillna("").astype(str).str.strip().eq("").any():
            raise PitMarketDataError(f"{name} has empty {column}")
    if not frame["evidence_scope"].eq(FORMAL_HISTORICAL_PIT).all():
        raise PitMarketDataError(f"{name} must contain formal historical rows only")
    if not frame["raw_payload_sha256"].astype(str).map(
        lambda value: bool(HASH_PATTERN.fullmatch(value))
    ).all():
        raise PitMarketDataError(f"{name} raw_payload_sha256 is invalid")
    source_as_of = pd.to_datetime(frame["source_as_of"], utc=True, errors="coerce")
    if source_as_of.isna().any():
        raise PitMarketDataError(f"{name} source_as_of is required")
    if "ingested_at_utc" in frame:
        ingested = pd.to_datetime(
            frame["ingested_at_utc"], utc=True, errors="coerce"
        )
        if ingested.isna().any():
            raise PitMarketDataError(f"{name} ingested_at_utc is required")


class PitMarketDataStore:
    """Validated raw OHLCV plus source-bound actions and delist dispositions."""

    def __init__(
        self,
        bars: pd.DataFrame,
        actions: pd.DataFrame,
        delistings: pd.DataFrame,
        *,
        security_master: PitSecurityMaster,
    ):
        self.master = security_master
        self._bars = self._normalize_bars(bars)
        self._actions = self._normalize_actions(actions)
        self._delistings = self._normalize_delistings(delistings)
        self._validate_delisting_completeness()

    @property
    def bars(self) -> pd.DataFrame:
        return self._bars.copy()

    @property
    def actions(self) -> pd.DataFrame:
        return self._actions.copy()

    @property
    def delistings(self) -> pd.DataFrame:
        return self._delistings.copy()

    @staticmethod
    def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
        _require_columns(frame, BAR_COLUMNS, "bars")
        bars = frame.copy()
        bars["session"] = pd.to_datetime(
            bars["session"], errors="coerce"
        ).dt.tz_localize(None).dt.normalize()
        _validate_provenance(bars, "bars")
        if bars.empty:
            raise PitMarketDataError("formal bars cannot be empty")
        if bars["session"].isna().any():
            raise PitMarketDataError("bar session is required")
        if bars.duplicated(["asset_id", "session"]).any():
            raise PitMarketDataError("duplicate asset/session bars")
        numeric = bars[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce"
        )
        if numeric.isna().any().any():
            raise PitMarketDataError("formal OHLCV cannot contain missing values")
        if (numeric[["open", "high", "low", "close"]] <= 0).any().any():
            raise PitMarketDataError("formal OHLC prices must be positive")
        if (numeric["volume"] < 0).any():
            raise PitMarketDataError("formal volume cannot be negative")
        if (
            (numeric["high"] < numeric[["open", "close"]].max(axis=1)).any()
            or (numeric["low"] > numeric[["open", "close"]].min(axis=1)).any()
            or (numeric["high"] < numeric["low"]).any()
        ):
            raise PitMarketDataError("invalid OHLC bounds")
        bars.loc[:, numeric.columns] = numeric
        return bars.sort_values(["session", "asset_id"]).reset_index(drop=True)

    @staticmethod
    def _normalize_actions(frame: pd.DataFrame) -> pd.DataFrame:
        _require_columns(frame, ACTION_COLUMNS, "actions")
        actions = frame.copy()
        if actions.empty:
            return actions
        actions["ex_session"] = pd.to_datetime(
            actions["ex_session"], errors="coerce"
        ).dt.tz_localize(None).dt.normalize()
        actions["pay_session"] = pd.to_datetime(
            actions["pay_session"], errors="coerce"
        ).dt.tz_localize(None).dt.normalize()
        _validate_provenance(actions, "actions")
        if actions["action_id"].fillna("").astype(str).str.strip().eq("").any():
            raise PitMarketDataError("actions require action_id")
        if actions.duplicated(["source_id", "action_id"]).any():
            raise PitMarketDataError("duplicate source/action_id")
        allowed = {"cash_distribution", "special_distribution", "split"}
        if not actions["action_type"].isin(allowed).all():
            raise PitMarketDataError("unsupported action_type")
        cash = pd.to_numeric(actions["cash_amount"], errors="coerce")
        split = pd.to_numeric(actions["split_factor"], errors="coerce")
        cash_rows = actions["action_type"].isin(
            {"cash_distribution", "special_distribution"}
        )
        split_rows = actions["action_type"].eq("split")
        if (cash_rows & (cash.isna() | (cash < 0))).any():
            raise PitMarketDataError("distribution actions require nonnegative cash")
        if (split_rows & (split.isna() | (split <= 0))).any():
            raise PitMarketDataError("split actions require positive split_factor")
        actions["cash_amount"] = cash
        actions["split_factor"] = split
        return actions.sort_values(["ex_session", "asset_id", "action_id"]).reset_index(
            drop=True
        )

    @staticmethod
    def _normalize_delistings(frame: pd.DataFrame) -> pd.DataFrame:
        _require_columns(frame, DELIST_COLUMNS, "delistings")
        delistings = frame.copy()
        if delistings.empty:
            return delistings
        delistings["delist_session"] = pd.to_datetime(
            delistings["delist_session"], errors="coerce"
        ).dt.tz_localize(None).dt.normalize()
        _validate_provenance(delistings, "delistings")
        if delistings["delist_session"].isna().any():
            raise PitMarketDataError("delist_session is required")
        if delistings["asset_id"].duplicated().any():
            raise PitMarketDataError("one formal delisting disposition per asset required")
        cash = pd.to_numeric(delistings["cash_consideration"], errors="coerce")
        factor = pd.to_numeric(delistings["disposition_factor"], errors="coerce")
        successor = delistings["stock_successor_asset_id"].fillna("").astype(str)
        has_disposition = cash.notna() | factor.notna() | successor.ne("")
        if not has_disposition.all():
            raise PitMarketDataError("delisting disposition cannot be missing")
        if (cash.dropna() < 0).any() or (factor.dropna() < 0).any():
            raise PitMarketDataError("delisting cash/factor cannot be negative")
        delistings["cash_consideration"] = cash
        delistings["disposition_factor"] = factor
        return delistings.sort_values(["delist_session", "asset_id"]).reset_index(
            drop=True
        )

    def _validate_delisting_completeness(self) -> None:
        intervals = self.master.intervals
        formal_delisted = intervals[
            intervals["evidence_scope"].eq(FORMAL_HISTORICAL_PIT)
            & intervals["delist_date"].notna()
        ][["asset_id", "delist_date"]].drop_duplicates()
        by_asset = self._delistings.set_index("asset_id") if not self._delistings.empty else None
        for row in formal_delisted.itertuples(index=False):
            if by_asset is None or row.asset_id not in by_asset.index:
                raise PitMarketDataError(
                    f"formal delisted asset {row.asset_id} lacks disposition"
                )
            disposition = by_asset.loc[row.asset_id]
            if pd.Timestamp(disposition["delist_session"]) != pd.Timestamp(row.delist_date):
                raise PitMarketDataError(
                    f"{row.asset_id} delist session does not match security master"
                )

    def delisting_disposition(self, asset_id: str) -> pd.Series:
        rows = self._delistings[self._delistings["asset_id"].eq(asset_id)]
        if len(rows) != 1:
            raise PitMarketDataError(
                f"asset {asset_id} has no unique source-bound delisting disposition; "
                "last-stale-price liquidation is forbidden"
            )
        return rows.iloc[0].copy()

    def bars_as_of(self, session: str | pd.Timestamp) -> pd.DataFrame:
        date = pd.Timestamp(session).tz_localize(None).normalize()
        return self._bars[self._bars["session"] <= date].copy().reset_index(drop=True)


def adjustment_parity_error(
    project_factors: pd.Series, vendor_factors: pd.Series
) -> dict[str, Any]:
    """Non-directional event-factor parity diagnostic."""

    if not project_factors.index.equals(vendor_factors.index):
        raise PitMarketDataError("adjustment factor indexes must match exactly")
    left = pd.to_numeric(project_factors, errors="coerce")
    right = pd.to_numeric(vendor_factors, errors="coerce")
    if left.isna().any() or right.isna().any():
        raise PitMarketDataError("adjustment factors cannot be missing")
    difference = (left - right).abs()
    return {
        "events": len(difference),
        "max_abs_factor_error": float(difference.max()) if len(difference) else 0.0,
        "mismatch_events": int((difference > 1e-12).sum()),
    }


__all__ = [
    "ACTION_COLUMNS",
    "BAR_COLUMNS",
    "DELIST_COLUMNS",
    "PitMarketDataError",
    "PitMarketDataStore",
    "adjustment_parity_error",
]
