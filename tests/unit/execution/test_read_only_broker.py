from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from core.execution.execution_simulator import Order, OrderSide
from core.execution.read_only_broker import (
    BrokerWriteForbiddenError,
    FileBrokerSnapshotAdapter,
    snapshot_payload,
)


def _payload():
    return snapshot_payload(
        snapshot_id="snapshot-1",
        source="sandbox-export",
        observed_at=datetime(2026, 7, 20, 18, 0, tzinfo=UTC),
        cash=98_500.0,
        positions={"SPY": 3.0},
        open_order_ids=["broker-order-1"],
        fill_ids=["execution-1"],
    )


def test_file_snapshot_is_coherent_and_all_writes_are_forbidden(tmp_path) -> None:
    path = tmp_path / "broker.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    adapter = FileBrokerSnapshotAdapter(path)

    snapshot = adapter.get_account_snapshot()
    assert snapshot.cash == 98_500.0
    assert snapshot.positions == {"SPY": 3.0}
    assert snapshot.open_order_ids == frozenset({"broker-order-1"})
    assert snapshot.fill_ids == frozenset({"execution-1"})
    assert adapter.get_open_order_ids() == frozenset({"broker-order-1"})

    order = Order("SPY", OrderSide.BUY, 1.0, datetime(2026, 7, 20))
    with pytest.raises(BrokerWriteForbiddenError, match="writes are forbidden"):
        adapter.submit_order(order)
    with pytest.raises(BrokerWriteForbiddenError, match="writes are forbidden"):
        adapter.cancel_order("broker-order-1")


def test_file_snapshot_rejects_duplicate_keys_and_symlinks(tmp_path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":1,"schema_version":1}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        FileBrokerSnapshotAdapter(duplicate).get_account_snapshot()

    target = tmp_path / "target.json"
    target.write_text(json.dumps(_payload()), encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlinks"):
        FileBrokerSnapshotAdapter(link).get_account_snapshot()


def test_file_snapshot_rejects_nonfinite_or_short_account_values(tmp_path) -> None:
    payload = _payload()
    payload["positions"] = {"SPY": -1.0}
    path = tmp_path / "broker.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="long-only"):
        FileBrokerSnapshotAdapter(path).get_account_snapshot()
