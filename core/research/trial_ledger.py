"""Append-only, hash-chained trial accounting for governed mining.

Every computation that can influence model or candidate selection registers an
intent before it runs.  The content hash deliberately excludes ``trial_id`` so
renaming an unchanged configuration cannot reset the independent-trial count
used by DSR/PBO governance.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
_CONTENT_FIELDS = (
    "hypothesis_family",
    "mechanism_id",
    "universe_hash",
    "data_hash",
    "config_hash",
    "code_commit",
    "feature_id",
    "model_id",
    "label_id",
    "construction_id",
    "cost_id",
    "execution_id",
    "seed",
    "period_start",
    "period_end",
    "observed_through",
    "parent_content_hash",
)


class TrialLedgerError(RuntimeError):
    """Raised when the ledger is invalid or an append violates its contract."""


@dataclass(frozen=True, slots=True)
class TrialIntent:
    trial_id: str
    hypothesis_family: str
    mechanism_id: str
    universe_hash: str
    data_hash: str
    config_hash: str
    code_commit: str
    feature_id: str
    model_id: str
    label_id: str
    construction_id: str
    cost_id: str
    execution_id: str
    seed: int
    period_start: str
    period_end: str
    observed_through: str
    parent_content_hash: str | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "parent_content_hash":
                continue
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"TrialIntent.{name} must be non-empty")
        if not isinstance(self.seed, int):
            raise TypeError("TrialIntent.seed must be an int")

    def content_payload(self) -> dict[str, Any]:
        raw = asdict(self)
        return {field: raw[field] for field in _CONTENT_FIELDS}

    @property
    def content_hash(self) -> str:
        return _sha256_json(self.content_payload())


@dataclass(frozen=True, slots=True)
class TrialRegistration:
    trial_id: str
    content_hash: str
    event_type: str
    independent_trial: bool
    original_trial_id: str


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _event_hash(event_without_hash: Mapping[str, Any]) -> str:
    return _sha256_json(event_without_hash)


class AppendOnlyTrialLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read_verified_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        expected_previous = GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.endswith("\n"):
                    raise TrialLedgerError(
                        f"ledger has a truncated line at {line_number}")
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TrialLedgerError(
                        f"ledger JSON is invalid at line {line_number}: {exc}"
                    ) from exc
                if event.get("schema_version") != SCHEMA_VERSION:
                    raise TrialLedgerError(
                        f"unsupported schema at line {line_number}")
                if event.get("sequence") != line_number:
                    raise TrialLedgerError(
                        f"non-contiguous sequence at line {line_number}")
                if event.get("previous_event_hash") != expected_previous:
                    raise TrialLedgerError(
                        f"hash-chain break at line {line_number}")
                stored_hash = event.get("event_hash")
                without_hash = dict(event)
                without_hash.pop("event_hash", None)
                computed_hash = _event_hash(without_hash)
                if stored_hash != computed_hash:
                    raise TrialLedgerError(
                        f"event hash mismatch at line {line_number}")
                expected_previous = stored_hash
                events.append(event)
        return events

    def verified_events(self) -> list[dict[str, Any]]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            try:
                return self._read_verified_unlocked()
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append_unlocked(
        self,
        events: list[dict[str, Any]],
        *,
        event_type: str,
        trial_id: str,
        content_hash: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        previous = events[-1]["event_hash"] if events else GENESIS_HASH
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_type": event_type,
            "trial_id": trial_id,
            "content_hash": content_hash,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "previous_event_hash": previous,
            "payload": dict(payload),
        }
        event["event_hash"] = _event_hash(event)
        encoded = (_canonical_json(event) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise TrialLedgerError("short write while appending trial ledger")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    def register_intent(self, intent: TrialIntent) -> TrialRegistration:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                events = self._read_verified_unlocked()
                intent_events = [
                    event for event in events
                    if event["event_type"] in {"INTENT", "REPLAY_INTENT"}
                ]
                same_id = [
                    event for event in intent_events
                    if event["trial_id"] == intent.trial_id
                ]
                if same_id:
                    event = same_id[0]
                    if event["content_hash"] != intent.content_hash:
                        raise TrialLedgerError(
                            f"trial_id {intent.trial_id!r} already has different content"
                        )
                    original = event["payload"].get(
                        "original_trial_id", intent.trial_id)
                    return TrialRegistration(
                        intent.trial_id,
                        intent.content_hash,
                        event["event_type"],
                        event["event_type"] == "INTENT",
                        original,
                    )

                same_content = [
                    event for event in intent_events
                    if event["content_hash"] == intent.content_hash
                ]
                if same_content:
                    original = same_content[0]["payload"].get(
                        "original_trial_id", same_content[0]["trial_id"])
                    event_type = "REPLAY_INTENT"
                    independent = False
                else:
                    original = intent.trial_id
                    event_type = "INTENT"
                    independent = True
                self._append_unlocked(
                    events,
                    event_type=event_type,
                    trial_id=intent.trial_id,
                    content_hash=intent.content_hash,
                    payload={
                        "intent": asdict(intent),
                        "content_payload": intent.content_payload(),
                        "original_trial_id": original,
                        "independent_trial": independent,
                    },
                )
                return TrialRegistration(
                    intent.trial_id,
                    intent.content_hash,
                    event_type,
                    independent,
                    original,
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def record_outcome(
        self,
        trial_id: str,
        outcome: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                events = self._read_verified_unlocked()
                intents = [
                    event for event in events
                    if event["trial_id"] == trial_id
                    and event["event_type"] in {"INTENT", "REPLAY_INTENT"}
                ]
                if not intents:
                    raise TrialLedgerError(
                        f"cannot record outcome before intent for {trial_id!r}")
                if any(
                    event["trial_id"] == trial_id
                    and event["event_type"] == "OUTCOME"
                    for event in events
                ):
                    raise TrialLedgerError(
                        f"outcome already exists for trial {trial_id!r}")
                return self._append_unlocked(
                    events,
                    event_type="OUTCOME",
                    trial_id=trial_id,
                    content_hash=intents[0]["content_hash"],
                    payload={"outcome": dict(outcome)},
                )
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def independent_trial_count(self, hypothesis_family: str | None = None) -> int:
        events = self.verified_events()
        intents = [event for event in events if event["event_type"] == "INTENT"]
        if hypothesis_family is not None:
            intents = [
                event for event in intents
                if event["payload"]["intent"]["hypothesis_family"]
                == hypothesis_family
            ]
        return len(intents)

    def incomplete_trial_ids(self) -> list[str]:
        events = self.verified_events()
        intended = {
            event["trial_id"] for event in events
            if event["event_type"] in {"INTENT", "REPLAY_INTENT"}
        }
        complete = {
            event["trial_id"] for event in events
            if event["event_type"] == "OUTCOME"
        }
        return sorted(intended - complete)


def count_independent_trials(events: Iterable[Mapping[str, Any]]) -> int:
    """Pure helper for reports that already loaded and verified events."""

    return sum(1 for event in events if event.get("event_type") == "INTENT")
