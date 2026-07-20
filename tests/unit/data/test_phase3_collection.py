"""Phase 3 collection contracts, failure isolation, and chain integrity."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.data.collection import (
    BatchStatus,
    CollectionChainError,
    CollectionError,
    CollectionIngestor,
    CollectionRequest,
    CollectionStore,
    FeedKind,
    FileCollectionProvider,
    IngestionEnvelope,
    MockCollectionProvider,
)
from core.runtime.strategy_artifact import canonical_json, sha256_bytes

EVENT = datetime(2026, 7, 17, 20, 0, tzinfo=UTC)
AVAILABLE = EVENT + timedelta(seconds=1)
RECEIVED = EVENT + timedelta(seconds=2)
REQUESTED = EVENT + timedelta(minutes=1)


def _common_times() -> dict[str, str]:
    return {
        "event_time": EVENT.isoformat(),
        "available_time": AVAILABLE.isoformat(),
        "received_time": RECEIVED.isoformat(),
    }


def _daily_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "SPY",
        "session": "2026-07-17",
        "open": 620.0,
        "high": 625.0,
        "low": 619.0,
        "close": 624.0,
        "adjusted_close": 624.0,
        "total_return_factor": 1.0,
        "volume": 50_000_000,
        "dividend": 0.0,
        "split_factor": 1.0,
        "corporate_action": None,
        "calendar": "XNYS",
        **_common_times(),
        "source": "fixture",
        "quality": [],
    }
    row.update(changes)
    return row


def _intraday_row(**changes: object) -> dict[str, object]:
    start = EVENT - timedelta(minutes=1)
    row: dict[str, object] = {
        "symbol": "SPY",
        "interval": "1m",
        "bar_start": start.isoformat(),
        "bar_end": EVENT.isoformat(),
        "open": 623.0,
        "high": 624.2,
        "low": 622.8,
        "close": 624.0,
        "volume": 80_000,
        "bid": 623.99,
        "ask": 624.01,
        "session_flag": "REGULAR",
        "latency_ms": 2000.0,
        **_common_times(),
        "source": "fixture",
        "quality": [],
    }
    row.update(changes)
    return row


def _options_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "chain_id": "spy-20260717-2000",
        "contract_id": "spy-call-630-20260821",
        "occ_symbol": "SPY260821C00630000",
        "underlying": "SPY",
        "quote_time": EVENT.isoformat(),
        "expiration": "2026-08-21",
        "strike": 630.0,
        "option_type": "CALL",
        "bid": 8.10,
        "ask": 8.20,
        "last": 8.15,
        "bid_size": 15,
        "ask_size": 12,
        "volume": 1200,
        "open_interest": 9000,
        "implied_volatility": 0.18,
        "delta": 0.45,
        "gamma": 0.02,
        "theta": -0.08,
        "vega": 0.20,
        "rho": 0.04,
        "multiplier": 100,
        **_common_times(),
        "source": "fixture",
        "quality": [],
    }
    row.update(changes)
    return row


def _envelope(
    feed: FeedKind,
    *,
    batch_id: str | None = None,
    rows: list[dict[str, object]] | None = None,
    cursor: str | None = None,
    next_cursor: str | None = "cursor-1",
    revision_of: str | None = None,
) -> IngestionEnvelope:
    default_rows = {
        FeedKind.DAILY: [_daily_row()],
        FeedKind.INTRADAY: [_intraday_row()],
        FeedKind.OPTIONS: [_options_row()],
    }
    return IngestionEnvelope(
        batch_id=batch_id or f"{feed.value}-batch-1",
        feed=feed,
        source="fixture",
        data_schema={
            FeedKind.DAILY: "daily_total_return_v1",
            FeedKind.INTRADAY: "intraday_quote_bar_v1",
            FeedKind.OPTIONS: "options_chain_v1",
        }[feed],
        event_time=EVENT,
        available_time=AVAILABLE,
        received_time=RECEIVED,
        rows=default_rows[feed] if rows is None else rows,
        provider_cursor=cursor,
        next_cursor=next_cursor,
        revision_of=revision_of,
    )


def _request(feed: FeedKind, cursor: str | None = None, resource: str | None = None):
    return CollectionRequest(
        feed=feed,
        requested_at=REQUESTED,
        cursor=cursor,
        resource=resource,
    )


def _json_payload(envelope: IngestionEnvelope) -> dict[str, object]:
    return {
        "batch_id": envelope.batch_id,
        "feed": envelope.feed.value,
        "source": envelope.source,
        "data_schema": envelope.data_schema,
        "event_time": envelope.event_time.isoformat(),
        "available_time": envelope.available_time.isoformat(),
        "received_time": envelope.received_time.isoformat(),
        "rows": list(envelope.rows),
        "provider_cursor": envelope.provider_cursor,
        "next_cursor": envelope.next_cursor,
        "quality_flags": list(envelope.quality_flags),
        "revision_of": envelope.revision_of,
    }


@pytest.mark.parametrize("feed", list(FeedKind))
def test_mock_provider_runs_each_feed_end_to_end(tmp_path: Path, feed: FeedKind) -> None:
    envelope = _envelope(feed)
    store = CollectionStore(tmp_path / "store")
    result = CollectionIngestor(store, MockCollectionProvider("fixture", [envelope])).ingest(
        _request(feed)
    )

    assert result.status == BatchStatus.TRUSTED
    assert result.row_count == 1
    assert store.resume_cursor(feed, "fixture") == "cursor-1"
    manifest = store.status_manifest()
    assert manifest["mode"] == "COLLECT_ONLY"
    assert manifest["strategy_consumption_enabled"] is False
    assert manifest["feeds"][feed.value]["trusted"] == 1


def test_quarantine_preserves_last_trusted_cursor(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path / "store")
    good = _envelope(FeedKind.DAILY)
    assert store.append(good).status == BatchStatus.TRUSTED
    bad = _envelope(
        FeedKind.DAILY,
        batch_id="daily-batch-2",
        rows=[_daily_row(high=600.0)],
        cursor="cursor-1",
        next_cursor="cursor-2",
    )

    result = store.append(bad)

    assert result.status == BatchStatus.QUARANTINED
    assert result.validation_errors
    assert store.resume_cursor(FeedKind.DAILY, "fixture") == "cursor-1"
    assert len(list((tmp_path / "store/quarantined/daily").iterdir())) == 1
    assert len(list((tmp_path / "store/trusted/daily").iterdir())) == 1


def test_valid_revision_links_without_overwriting_parent(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path / "store")
    original = _envelope(FeedKind.DAILY, batch_id="original")
    parent = store.append(original)
    revised = _envelope(
        FeedKind.DAILY,
        batch_id="revision-1",
        rows=[_daily_row(close=623.5, adjusted_close=623.5)],
        cursor="cursor-1",
        next_cursor="cursor-2",
        revision_of="original",
    )

    child = store.append(revised)

    assert child.status == BatchStatus.TRUSTED
    assert child.revision_of == "original"
    assert parent.content_sha256 != child.content_sha256
    assert [item.batch_id for item in store.verify_chain()] == ["original", "revision-1"]


def test_unknown_revision_is_retained_but_quarantined(tmp_path: Path) -> None:
    result = CollectionStore(tmp_path / "store").append(
        _envelope(FeedKind.DAILY, revision_of="missing")
    )
    assert result.status == BatchStatus.QUARANTINED
    assert "REVISION:PARENT_ABSENT" in result.validation_errors


def test_exact_duplicate_is_idempotent_and_conflict_fails(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path / "store")
    envelope = _envelope(FeedKind.DAILY)
    first = store.append(envelope)
    second = store.append(envelope)

    assert second.reused is True
    assert first.record_sha256 == second.record_sha256
    with pytest.raises(CollectionError, match="conflicts"):
        store.append(replace(envelope, rows=[_daily_row(close=623.0)]))


@pytest.mark.parametrize(
    ("feed", "rows", "error_fragment"),
    [
        (
            FeedKind.INTRADAY,
            [
                _intraday_row(),
                _intraday_row(
                    bar_start=(EVENT + timedelta(minutes=1)).isoformat(),
                    bar_end=(EVENT + timedelta(minutes=2)).isoformat(),
                    event_time=(EVENT + timedelta(minutes=2)).isoformat(),
                    available_time=(EVENT + timedelta(minutes=2, seconds=1)).isoformat(),
                    received_time=(EVENT + timedelta(minutes=2, seconds=2)).isoformat(),
                ),
            ],
            "MISSING_BAR",
        ),
        (FeedKind.OPTIONS, [_options_row(delta=1.2)], "DELTA_OUT_OF_RANGE"),
    ],
)
def test_intraday_gap_and_bad_options_quote_are_quarantined(
    tmp_path: Path,
    feed: FeedKind,
    rows: list[dict[str, object]],
    error_fragment: str,
) -> None:
    row_times = [datetime.fromisoformat(str(row["event_time"])) for row in rows]
    available = [datetime.fromisoformat(str(row["available_time"])) for row in rows]
    received = [datetime.fromisoformat(str(row["received_time"])) for row in rows]
    envelope = replace(
        _envelope(feed, rows=rows),
        event_time=min(row_times),
        available_time=max(available),
        received_time=max(received),
    )
    result = CollectionStore(tmp_path / "store").append(envelope)
    assert result.status == BatchStatus.QUARANTINED
    assert any(error_fragment in error for error in result.validation_errors)


def test_file_provider_strict_json_end_to_end(tmp_path: Path) -> None:
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    path = provider_root / "daily.json"
    path.write_text(json.dumps(_json_payload(_envelope(FeedKind.DAILY))), encoding="utf-8")
    provider = FileCollectionProvider(provider_root, "fixture", maximum_bytes=100_000)

    result = CollectionIngestor(CollectionStore(tmp_path / "store"), provider).ingest(
        _request(FeedKind.DAILY, resource="daily.json")
    )

    assert result.status == BatchStatus.TRUSTED


def test_file_provider_rejects_escape_symlink_and_duplicate_keys(tmp_path: Path) -> None:
    provider_root = tmp_path / "provider"
    provider_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (provider_root / "linked.json").symlink_to(outside)
    duplicate = provider_root / "duplicate.json"
    duplicate.write_text('{"batch_id":"a","batch_id":"b"}', encoding="utf-8")
    provider = FileCollectionProvider(provider_root, "fixture", maximum_bytes=100_000)

    with pytest.raises(CollectionError, match="escapes"):
        provider.fetch(_request(FeedKind.DAILY, resource="../outside.json"))
    with pytest.raises(CollectionError, match="symlink"):
        provider.fetch(_request(FeedKind.DAILY, resource="linked.json"))
    with pytest.raises(CollectionError, match="duplicate JSON key"):
        provider.fetch(_request(FeedKind.DAILY, resource="duplicate.json"))


def test_provider_identity_cursor_and_time_are_fail_closed(tmp_path: Path) -> None:
    del tmp_path
    envelope = _envelope(FeedKind.DAILY)
    with pytest.raises(CollectionError, match="source"):
        MockCollectionProvider("other", [envelope]).fetch(_request(FeedKind.DAILY))
    with pytest.raises(CollectionError, match="found 0"):
        MockCollectionProvider("fixture", [envelope]).fetch(
            _request(FeedKind.DAILY, cursor="wrong")
        )
    with pytest.raises(CollectionError, match="after requested_at"):
        MockCollectionProvider("fixture", [envelope]).fetch(
            CollectionRequest(feed=FeedKind.DAILY, requested_at=EVENT)
        )


def test_chain_detects_raw_tampering(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path / "store")
    store.append(_envelope(FeedKind.DAILY))
    path = next((tmp_path / "store/trusted/daily").iterdir())
    os.chmod(path, 0o600)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rows"][0]["close"] = 1.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CollectionChainError, match="content hash"):
        store.verify_chain()


def test_chain_recomputes_status_even_if_attacker_rehashes_record(tmp_path: Path) -> None:
    store = CollectionStore(tmp_path / "store")
    store.append(_envelope(FeedKind.DAILY))
    old_path = next((tmp_path / "store/trusted/daily").iterdir())
    os.chmod(old_path, 0o600)
    payload = json.loads(old_path.read_text(encoding="utf-8"))
    payload["status"] = "quarantined"
    payload.pop("record_sha256")
    payload["record_sha256"] = sha256_bytes(canonical_json(payload))
    new_path = (
        tmp_path / "store/quarantined/daily" / f"000000000001_{payload['record_sha256']}.json"
    )
    old_path.rename(new_path)
    new_path.write_bytes(canonical_json(payload) + b"\n")

    with pytest.raises(CollectionChainError, match="status is inconsistent"):
        store.verify_chain()


def test_envelope_requires_exact_schema_and_time_aggregates(tmp_path: Path) -> None:
    wrong_schema = replace(_envelope(FeedKind.DAILY), data_schema="daily_v0")
    wrong_time = replace(
        _envelope(FeedKind.DAILY, batch_id="time-bad"), event_time=EVENT - timedelta(days=1)
    )

    store = CollectionStore(tmp_path / "store")
    assert store.append(wrong_schema).status == BatchStatus.QUARANTINED
    result = store.append(wrong_time)
    assert result.status == BatchStatus.QUARANTINED
    assert "ENVELOPE:EVENT_TIME_NOT_MINIMUM" in result.validation_errors
