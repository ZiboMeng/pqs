"""Read-only broker authority backed by a validated local snapshot file."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.execution.broker_adapter import (
    BrokerAccountSnapshot,
    BrokerAdapter,
    OrderAck,
    ReconcileResult,
)
from core.execution.execution_simulator import Fill, Order


class BrokerWriteForbiddenError(PermissionError):
    """Raised whenever Phase 3 code attempts an external broker write."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key in broker snapshot: {key}")
        result[key] = value
    return result


class FileBrokerSnapshotAdapter(BrokerAdapter):
    """Expose file-delivered account state while hard-rejecting all writes.

    The adapter is intentionally unsuitable as an execution destination.  It
    exists so a sandbox or broker export can be an independent reconciliation
    authority without importing credentials or granting order permissions.
    """

    _EXPECTED_KEYS = {
        "schema_version",
        "snapshot_id",
        "source",
        "observed_at",
        "cash",
        "positions",
        "open_order_ids",
        "fill_ids",
    }

    def __init__(self, snapshot_path: str | Path, *, maximum_bytes: int = 2_000_000):
        self.snapshot_path = Path(snapshot_path)
        if maximum_bytes <= 0:
            raise ValueError("maximum broker snapshot size must be positive")
        self.maximum_bytes = int(maximum_bytes)

    @staticmethod
    def _forbidden() -> BrokerWriteForbiddenError:
        return BrokerWriteForbiddenError(
            "Phase 3 broker adapter is read-only; external writes are forbidden"
        )

    def submit_order(self, order: Order) -> OrderAck:
        del order
        raise self._forbidden()

    def cancel_order(self, order_id: str) -> bool:
        del order_id
        raise self._forbidden()

    def mirror_fill(self, fill: Fill) -> OrderAck:
        del fill
        raise self._forbidden()

    def _snapshot(self) -> BrokerAccountSnapshot:
        path = self.snapshot_path
        if path.is_symlink():
            raise ValueError("broker snapshot symlinks are forbidden")
        before = path.stat()
        if not path.is_file() or before.st_size > self.maximum_bytes:
            raise ValueError("broker snapshot is missing, not regular, or too large")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            raw = os.read(descriptor, self.maximum_bytes + 1)
            after_descriptor = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after = path.stat()
        if len(raw) > self.maximum_bytes:
            raise ValueError("broker snapshot exceeds maximum size")
        if (
            before.st_ino != after_descriptor.st_ino
            or before.st_ino != after.st_ino
            or before.st_size != after_descriptor.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise ValueError("broker snapshot changed while being read")
        payload = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
        if not isinstance(payload, dict) or set(payload) != self._EXPECTED_KEYS:
            raise ValueError("broker snapshot schema keys do not match version 1")
        if payload["schema_version"] != 1:
            raise ValueError("unsupported broker snapshot schema")
        if not isinstance(payload["positions"], dict):
            raise ValueError("broker snapshot positions must be a mapping")
        if not isinstance(payload["open_order_ids"], list) or not isinstance(
            payload["fill_ids"], list
        ):
            raise ValueError("broker snapshot identities must be lists")
        if len(payload["open_order_ids"]) != len(set(payload["open_order_ids"])):
            raise ValueError("duplicate broker open-order identity")
        if len(payload["fill_ids"]) != len(set(payload["fill_ids"])):
            raise ValueError("duplicate broker fill identity")
        observed_at = datetime.fromisoformat(str(payload["observed_at"]))
        snapshot = BrokerAccountSnapshot(
            snapshot_id=str(payload["snapshot_id"]),
            source=str(payload["source"]),
            observed_at=observed_at,
            cash=float(payload["cash"]),
            positions={
                str(symbol): float(quantity)
                for symbol, quantity in payload["positions"].items()
            },
            open_order_ids=frozenset(str(value) for value in payload["open_order_ids"]),
            fill_ids=frozenset(str(value) for value in payload["fill_ids"]),
        )
        if not math.isfinite(snapshot.cash):
            raise ValueError("broker snapshot cash is non-finite")
        return snapshot

    def get_account_snapshot(
        self,
        *,
        observed_at: datetime | None = None,
    ) -> BrokerAccountSnapshot:
        del observed_at
        return self._snapshot()

    def get_positions(self) -> dict[str, float]:
        return dict(self._snapshot().positions)

    def get_cash(self) -> float:
        return self._snapshot().cash

    def get_open_orders(self) -> list[Order]:
        snapshot = self._snapshot()
        if snapshot.open_order_ids:
            raise RuntimeError(
                "read-only snapshot has open-order identities but no executable order bodies"
            )
        return []

    def get_open_order_ids(self) -> frozenset[str]:
        return self._snapshot().open_order_ids

    def get_fills(self, since: datetime) -> list[Fill]:
        del since
        # Stable fill identities remain available on get_account_snapshot().
        # Fabricating executable Fill objects from an account export would be
        # less safe than explicitly returning no detailed records.
        return []

    def reconcile(
        self,
        expected_positions: dict[str, float],
        expected_cash: float,
    ) -> ReconcileResult:
        snapshot = self._snapshot()
        differences = {
            symbol: snapshot.positions.get(symbol, 0.0)
            - float(expected_positions.get(symbol, 0.0))
            for symbol in set(snapshot.positions) | set(expected_positions)
            if abs(
                snapshot.positions.get(symbol, 0.0)
                - float(expected_positions.get(symbol, 0.0))
            )
            > 1e-6
        }
        cash_difference = snapshot.cash - float(expected_cash)
        passed = not differences and abs(cash_difference) <= 0.01
        return ReconcileResult(
            passed=passed,
            position_mismatches=differences,
            cash_mismatch=cash_difference,
            details=(
                f"source={snapshot.source}; snapshot={snapshot.snapshot_id}; "
                f"position_mismatches={len(differences)}; "
                f"cash_difference={cash_difference:+.4f}"
            ),
        )


def snapshot_payload(
    *,
    snapshot_id: str,
    source: str,
    observed_at: datetime,
    cash: float,
    positions: dict[str, float],
    open_order_ids: list[str] | None = None,
    fill_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the documented v1 file payload for tests and sandbox exporters."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("broker snapshot time must be timezone-aware")
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "source": source,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "cash": cash,
        "positions": positions,
        "open_order_ids": open_order_ids or [],
        "fill_ids": fill_ids or [],
    }
