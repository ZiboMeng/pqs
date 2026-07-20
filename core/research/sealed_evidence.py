"""Phase 3 append-only sealed evidence, governance, and evaluation boundary."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.runtime.strategy_artifact import (
    canonical_json,
    sha256_bytes,
    verify_strategy_artifact,
)

_SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")
_ZERO_HASH = "0" * 64


class SealedEvidenceError(RuntimeError):
    """Base error for sealed evidence contract violations."""


class SealedChainError(SealedEvidenceError):
    """Raised when a batch chain is corrupt, ambiguous, or overwritten."""


class SealedBudgetError(SealedEvidenceError):
    """Raised before evaluation when any immutable information budget is spent."""


class SealedEvaluationError(SealedEvidenceError):
    """Raised when a counted evaluator attempt cannot return a valid summary."""


def _safe_id(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"unsafe {label}: {value!r}")
    return normalized


def _aware_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SealedChainError(f"duplicate JSON key in sealed record: {key}")
        result[key] = value
    return result


def _read_json_strict(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    if path.is_symlink():
        raise SealedChainError(f"sealed symlink is forbidden: {path}")
    before = path.stat()
    if not path.is_file() or before.st_size > maximum_bytes:
        raise SealedChainError(f"sealed record is missing, irregular, or too large: {path}")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        raw = os.read(descriptor, maximum_bytes + 1)
        opened = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = path.stat()
    if len(raw) > maximum_bytes:
        raise SealedChainError(f"sealed record exceeds size limit: {path}")
    if (
        before.st_ino != opened.st_ino
        or before.st_ino != after.st_ino
        or before.st_size != opened.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise SealedChainError(f"sealed record changed while being read: {path}")
    payload = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
    if not isinstance(payload, dict):
        raise SealedChainError("sealed record must be a JSON object")
    return payload


def _atomic_create(path: Path, payload: Mapping[str, Any], *, mode: int = 0o400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise SealedEvidenceError("atomic sealed path cannot traverse a symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            raw = canonical_json(dict(payload)) + b"\n"
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise SealedEvidenceError(f"immutable output already exists: {path}") from exc
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class SealedBatchInput:
    batch_id: str
    source: str
    event_time: datetime
    available_time: datetime
    received_time: datetime
    data_schema: str
    rows: Sequence[Mapping[str, Any]]
    quality_flags: tuple[str, ...] = ()
    revision_of: str | None = None

    def __post_init__(self) -> None:
        _safe_id(self.batch_id, "batch id")
        _safe_id(self.data_schema, "data schema")
        if not self.source.strip():
            raise ValueError("sealed batch source is required")
        event = _aware_utc(self.event_time, "event_time")
        available = _aware_utc(self.available_time, "available_time")
        received = _aware_utc(self.received_time, "received_time")
        if not event <= available <= received:
            raise ValueError("sealed batch times must satisfy event <= available <= received")
        if self.revision_of is not None:
            _safe_id(self.revision_of, "revision parent")
            if self.revision_of == self.batch_id:
                raise ValueError("sealed revision cannot reference itself")
        if len(set(self.quality_flags)) != len(self.quality_flags):
            raise ValueError("sealed quality flags must be unique")
        canonical_json([dict(row) for row in self.rows])


@dataclass(frozen=True, slots=True)
class SealedBatchMetadata:
    sequence: int
    batch_id: str
    source: str
    event_time_utc: str
    available_time_utc: str
    received_time_utc: str
    data_schema: str
    row_count: int
    quality_flags: tuple[str, ...]
    revision_of: str | None
    content_sha256: str
    previous_record_sha256: str
    record_sha256: str
    reused: bool = False


class SealedEvidenceStore:
    """Local append-only file chain; raw rows are not returned by public methods."""

    def __init__(
        self,
        root: str | Path,
        *,
        maximum_batch_bytes: int = 10_000_000,
        maximum_rows: int = 100_000,
    ) -> None:
        self.root = Path(root)
        if self.root.exists() and self.root.is_symlink():
            raise SealedEvidenceError("sealed store root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = self.root / "journal"
        if self.journal.exists() and self.journal.is_symlink():
            raise SealedEvidenceError("sealed journal cannot be a symlink")
        self.journal.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".append.lock"
        if maximum_batch_bytes <= 0 or maximum_rows <= 0:
            raise ValueError("sealed store limits must be positive")
        self.maximum_batch_bytes = int(maximum_batch_bytes)
        self.maximum_rows = int(maximum_rows)

    def _lock(self):
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor

    def _record_paths(self) -> list[Path]:
        unexpected = [
            path
            for path in self.journal.iterdir()
            if path.is_symlink()
            or not path.is_file()
            or not re.fullmatch(r"\d{12}_[0-9a-f]{64}\.json", path.name)
        ]
        if unexpected:
            raise SealedChainError(
                f"unexpected entries in sealed journal: {[path.name for path in unexpected]}"
            )
        return sorted(self.journal.iterdir())

    def _verify_locked(self) -> tuple[list[SealedBatchMetadata], dict[str, dict[str, Any]]]:
        metadata: list[SealedBatchMetadata] = []
        records: dict[str, dict[str, Any]] = {}
        previous = _ZERO_HASH
        for expected_sequence, path in enumerate(self._record_paths(), start=1):
            payload = _read_json_strict(path, maximum_bytes=self.maximum_batch_bytes)
            record_hash = str(payload.get("record_sha256", ""))
            hash_payload = dict(payload)
            hash_payload.pop("record_sha256", None)
            computed = sha256_bytes(canonical_json(hash_payload))
            expected_name = f"{expected_sequence:012d}_{record_hash}.json"
            if path.name != expected_name:
                raise SealedChainError("sealed journal sequence or filename hash is invalid")
            if payload.get("sequence") != expected_sequence:
                raise SealedChainError("sealed record sequence is discontinuous")
            if payload.get("previous_record_sha256") != previous:
                raise SealedChainError("sealed previous-record hash chain is broken")
            if record_hash != computed:
                raise SealedChainError("sealed record content hash is invalid")
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise SealedChainError("sealed rows must be a list")
            content_hash = sha256_bytes(canonical_json(rows))
            if payload.get("content_sha256") != content_hash:
                raise SealedChainError("sealed batch row content hash is invalid")
            batch_id = _safe_id(str(payload.get("batch_id", "")), "batch id")
            if batch_id in records:
                raise SealedChainError(f"duplicate sealed batch id: {batch_id}")
            revision_of = payload.get("revision_of")
            if revision_of is not None and revision_of not in records:
                raise SealedChainError("sealed revision parent is absent or ordered after child")
            records[batch_id] = payload
            metadata.append(self._metadata(payload))
            previous = record_hash
        return metadata, records

    @staticmethod
    def _metadata(
        payload: Mapping[str, Any],
        *,
        reused: bool = False,
    ) -> SealedBatchMetadata:
        return SealedBatchMetadata(
            sequence=int(payload["sequence"]),
            batch_id=str(payload["batch_id"]),
            source=str(payload["source"]),
            event_time_utc=str(payload["event_time_utc"]),
            available_time_utc=str(payload["available_time_utc"]),
            received_time_utc=str(payload["received_time_utc"]),
            data_schema=str(payload["data_schema"]),
            row_count=int(payload["row_count"]),
            quality_flags=tuple(payload["quality_flags"]),
            revision_of=payload.get("revision_of"),
            content_sha256=str(payload["content_sha256"]),
            previous_record_sha256=str(payload["previous_record_sha256"]),
            record_sha256=str(payload["record_sha256"]),
            reused=reused,
        )

    def verify_chain(self) -> list[SealedBatchMetadata]:
        descriptor = self._lock()
        try:
            metadata, _ = self._verify_locked()
            return metadata
        finally:
            os.close(descriptor)

    def append(self, batch: SealedBatchInput) -> SealedBatchMetadata:
        if len(batch.rows) > self.maximum_rows:
            raise SealedEvidenceError("sealed batch row count exceeds configured maximum")
        rows = [dict(row) for row in batch.rows]
        content_hash = sha256_bytes(canonical_json(rows))
        descriptor = self._lock()
        try:
            metadata, records = self._verify_locked()
            existing = records.get(batch.batch_id)
            if existing is not None:
                same = (
                    existing["content_sha256"] == content_hash
                    and existing["source"] == batch.source
                    and existing["data_schema"] == batch.data_schema
                    and existing.get("revision_of") == batch.revision_of
                    and existing["event_time_utc"]
                    == _aware_utc(batch.event_time, "event_time").isoformat()
                    and existing["available_time_utc"]
                    == _aware_utc(batch.available_time, "available_time").isoformat()
                    and existing["received_time_utc"]
                    == _aware_utc(batch.received_time, "received_time").isoformat()
                    and existing["quality_flags"] == sorted(batch.quality_flags)
                )
                if not same:
                    raise SealedChainError(
                        f"sealed batch id reused with different content: {batch.batch_id}"
                    )
                item = next(item for item in metadata if item.batch_id == batch.batch_id)
                return replace(item, reused=True)
            if batch.revision_of is not None and batch.revision_of not in records:
                raise SealedChainError("sealed revision parent does not exist")
            sequence = len(metadata) + 1
            previous = metadata[-1].record_sha256 if metadata else _ZERO_HASH
            payload: dict[str, Any] = {
                "schema_version": 1,
                "sequence": sequence,
                "batch_id": batch.batch_id,
                "source": batch.source.strip(),
                "event_time_utc": _aware_utc(batch.event_time, "event_time").isoformat(),
                "available_time_utc": _aware_utc(
                    batch.available_time, "available_time"
                ).isoformat(),
                "received_time_utc": _aware_utc(
                    batch.received_time, "received_time"
                ).isoformat(),
                "data_schema": batch.data_schema,
                "row_count": len(rows),
                "quality_flags": sorted(batch.quality_flags),
                "revision_of": batch.revision_of,
                "content_sha256": content_hash,
                "previous_record_sha256": previous,
                "rows": rows,
            }
            raw_without_hash = canonical_json(payload)
            if len(raw_without_hash) > self.maximum_batch_bytes:
                raise SealedEvidenceError("sealed batch exceeds configured byte maximum")
            payload["record_sha256"] = sha256_bytes(raw_without_hash)
            if len(canonical_json(payload)) > self.maximum_batch_bytes:
                raise SealedEvidenceError("sealed batch exceeds configured byte maximum")
            path = self.journal / (
                f"{sequence:012d}_{payload['record_sha256']}.json"
            )
            _atomic_create(path, payload)
            return self._metadata(payload)
        finally:
            os.close(descriptor)

    def metadata(self, batch_id: str) -> SealedBatchMetadata:
        safe_batch = _safe_id(batch_id, "batch id")
        for item in self.verify_chain():
            if item.batch_id == safe_batch:
                return item
        raise KeyError(f"unknown sealed batch: {safe_batch}")

    def _read_rows_for_evaluator(self, batch_id: str) -> list[dict[str, Any]]:
        """Internal capability: evaluator controller only; never return via CLI/API."""

        safe_batch = _safe_id(batch_id, "batch id")
        descriptor = self._lock()
        try:
            _, records = self._verify_locked()
            if safe_batch not in records:
                raise KeyError(f"unknown sealed batch: {safe_batch}")
            return [dict(row) for row in records[safe_batch]["rows"]]
        finally:
            os.close(descriptor)


@dataclass(frozen=True, slots=True)
class SealedBudgetPolicy:
    policy_id: str
    global_attempts: int
    family_attempts: int
    lineage_attempts: int
    artifact_version_attempts: int

    def __post_init__(self) -> None:
        _safe_id(self.policy_id, "budget policy id")
        values = (
            self.global_attempts,
            self.family_attempts,
            self.lineage_attempts,
            self.artifact_version_attempts,
        )
        if any(value <= 0 for value in values):
            raise ValueError("all sealed budget limits must be positive")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> SealedBudgetPolicy:
        return cls(
            policy_id=str(payload["policy_id"]),
            global_attempts=int(payload["global_attempts"]),
            family_attempts=int(payload["family_attempts"]),
            lineage_attempts=int(payload["lineage_attempts"]),
            artifact_version_attempts=int(payload["artifact_version_attempts"]),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "global_attempts": self.global_attempts,
            "family_attempts": self.family_attempts,
            "lineage_attempts": self.lineage_attempts,
            "artifact_version_attempts": self.artifact_version_attempts,
        }

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_json(self.payload()))


@dataclass(frozen=True, slots=True)
class HypothesisRegistration:
    hypothesis_id: str
    family_id: str
    lineage_id: str
    title: str
    economic_rationale: str
    eligible_data_start: date
    evidence_origin: str

    def __post_init__(self) -> None:
        _safe_id(self.hypothesis_id, "hypothesis id")
        _safe_id(self.family_id, "family id")
        _safe_id(self.lineage_id, "hypothesis lineage id")
        if not self.title.strip() or not self.economic_rationale.strip():
            raise ValueError("hypothesis title and rationale are required")
        if self.evidence_origin != "FUTURE_UNSEEN":
            raise ValueError("new sealed hypotheses must declare FUTURE_UNSEEN evidence")

    def payload(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "family_id": self.family_id,
            "lineage_id": self.lineage_id,
            "title": self.title.strip(),
            "economic_rationale": self.economic_rationale.strip(),
            "eligible_data_start": self.eligible_data_start.isoformat(),
            "evidence_origin": self.evidence_origin,
        }


def load_hypothesis_registry(
    path: str | Path,
) -> list[tuple[HypothesisRegistration, datetime]]:
    registry_path = Path(path)
    payload = _read_json_strict(registry_path, maximum_bytes=1_000_000)
    if set(payload) != {
        "schema_version",
        "created_at_utc",
        "registrations",
        "registry_sha256",
    } or payload["schema_version"] != 1:
        raise SealedEvidenceError("hypothesis registry schema mismatch")
    unsigned = dict(payload)
    recorded_root = unsigned.pop("registry_sha256")
    if recorded_root != sha256_bytes(canonical_json(unsigned)):
        raise SealedEvidenceError("hypothesis registry root hash mismatch")
    records = payload["registrations"]
    if not isinstance(records, list):
        raise SealedEvidenceError("hypothesis registry registrations must be a list")
    observed_ids: set[str] = set()
    result: list[tuple[HypothesisRegistration, datetime]] = []
    for record in records:
        if not isinstance(record, dict):
            raise SealedEvidenceError("hypothesis registry record must be a mapping")
        record_payload = dict(record)
        record_hash = record_payload.pop("registration_sha256", None)
        if record_hash != sha256_bytes(canonical_json(record_payload)):
            raise SealedEvidenceError("hypothesis registration hash mismatch")
        registration = HypothesisRegistration(
            hypothesis_id=str(record_payload["hypothesis_id"]),
            family_id=str(record_payload["family_id"]),
            lineage_id=str(record_payload["lineage_id"]),
            title=str(record_payload["title"]),
            economic_rationale=str(record_payload["economic_rationale"]),
            eligible_data_start=date.fromisoformat(
                str(record_payload["eligible_data_start"])
            ),
            evidence_origin=str(record_payload["evidence_origin"]),
        )
        if registration.hypothesis_id in observed_ids:
            raise SealedEvidenceError("duplicate hypothesis registry id")
        observed_ids.add(registration.hypothesis_id)
        registered_at = datetime.fromisoformat(str(record_payload["registered_at_utc"]))
        result.append((registration, _aware_utc(registered_at, "registered_at_utc")))
    return result


@dataclass(frozen=True, slots=True)
class SealedSubmission:
    submission_id: str
    hypothesis_id: str
    artifact_path: str
    artifact_id: str
    artifact_version: str
    artifact_root_sha256: str
    sealed_batch_id: str
    metric_policy_id: str
    benchmark_policy_id: str
    cost_policy_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.submission_id, "submission id"),
            (self.hypothesis_id, "hypothesis id"),
            (self.artifact_id, "artifact id"),
            (self.artifact_version, "artifact version"),
            (self.sealed_batch_id, "sealed batch id"),
            (self.metric_policy_id, "metric policy id"),
            (self.benchmark_policy_id, "benchmark policy id"),
            (self.cost_policy_id, "cost policy id"),
        ):
            _safe_id(value, label)
        artifact = Path(self.artifact_path)
        if artifact.is_absolute() or ".." in artifact.parts:
            raise ValueError("submission artifact path must be safe and repo-relative")
        if not re.fullmatch(r"[0-9a-f]{64}", self.artifact_root_sha256):
            raise ValueError("submission artifact root must be lowercase SHA256")

    def payload(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "hypothesis_id": self.hypothesis_id,
            "artifact_path": self.artifact_path,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "artifact_root_sha256": self.artifact_root_sha256,
            "sealed_batch_id": self.sealed_batch_id,
            "metric_policy_id": self.metric_policy_id,
            "benchmark_policy_id": self.benchmark_policy_id,
            "cost_policy_id": self.cost_policy_id,
        }


@dataclass(frozen=True, slots=True)
class ReservedAttempt:
    attempt_id: str
    submission_id: str
    family_id: str
    lineage_id: str
    artifact_root_sha256: str
    duplicate_of_attempt_id: str | None


class SealedGovernance:
    """Concurrent preregistration, immutable submissions, budgets, and audit."""

    def __init__(self, db_path: str | Path, policy: SealedBudgetPolicy) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sealed_budget_policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    policy_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sealed_evaluator_policy (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    policy_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sealed_hypotheses (
                    hypothesis_id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL,
                    lineage_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    registered_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sealed_hypothesis_lineage
                    ON sealed_hypotheses(lineage_id);
                CREATE TABLE IF NOT EXISTS sealed_submissions (
                    submission_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    artifact_root_sha256 TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    registered_at_utc TEXT NOT NULL,
                    FOREIGN KEY(hypothesis_id) REFERENCES sealed_hypotheses(hypothesis_id)
                );
                CREATE TABLE IF NOT EXISTS sealed_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    submission_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    lineage_id TEXT NOT NULL,
                    artifact_root_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    counted INTEGER NOT NULL,
                    duplicate_of_attempt_id TEXT,
                    summary_sha256 TEXT,
                    error_category TEXT,
                    created_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT,
                    FOREIGN KEY(submission_id) REFERENCES sealed_submissions(submission_id)
                );
                CREATE TABLE IF NOT EXISTS sealed_results (
                    submission_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL UNIQUE,
                    summary_sha256 TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    result_path TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sealed_audit_events (
                    event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL
                );
                """
            )
        self.freeze_policy()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @staticmethod
    def _now(value: datetime | None = None) -> datetime:
        return datetime.now(UTC) if value is None else _aware_utc(value, "governance time")

    @staticmethod
    def _audit_in_transaction(
        conn: sqlite3.Connection,
        event_type: str,
        subject_id: str,
        payload: Mapping[str, Any],
        now: datetime,
    ) -> None:
        conn.execute(
            """
            INSERT INTO sealed_audit_events (
                event_type, subject_id, payload_json, occurred_at_utc
            ) VALUES (?, ?, ?, ?)
            """,
            (
                event_type,
                subject_id,
                canonical_json(dict(payload)).decode("utf-8"),
                now.isoformat(),
            ),
        )

    def freeze_policy(self) -> None:
        payload_json = canonical_json(self.policy.payload()).decode("utf-8")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT policy_sha256, payload_json FROM sealed_budget_policy WHERE id = 1"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO sealed_budget_policy VALUES (1, ?, ?)",
                    (self.policy.sha256, payload_json),
                )
                self._audit_in_transaction(
                    conn,
                    "BUDGET_POLICY_FROZEN",
                    self.policy.policy_id,
                    {"policy_sha256": self.policy.sha256},
                    self._now(),
                )
            elif row["policy_sha256"] != self.policy.sha256 or row["payload_json"] != payload_json:
                raise SealedBudgetError("sealed budget policy drift is forbidden")

    def preregister(
        self,
        registration: HypothesisRegistration,
        *,
        now: datetime | None = None,
    ) -> bool:
        timestamp = self._now(now)
        payload = registration.payload()
        payload_json = canonical_json(payload).decode("utf-8")
        content_hash = sha256_bytes(payload_json.encode("utf-8"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT content_sha256 FROM sealed_hypotheses WHERE hypothesis_id = ?",
                (registration.hypothesis_id,),
            ).fetchone()
            if row is not None:
                if row["content_sha256"] != content_hash:
                    self._audit_in_transaction(
                        conn,
                        "HYPOTHESIS_CONFLICT_REJECTED",
                        registration.hypothesis_id,
                        {"submitted_content_sha256": content_hash},
                        timestamp,
                    )
                    conn.commit()
                    raise SealedEvidenceError(
                        "hypothesis id reused with different preregistration"
                    )
                self._audit_in_transaction(
                    conn,
                    "HYPOTHESIS_DUPLICATE",
                    registration.hypothesis_id,
                    {"content_sha256": content_hash},
                    timestamp,
                )
                return True
            lineage_rows = conn.execute(
                """
                SELECT family_id, payload_json FROM sealed_hypotheses
                WHERE lineage_id = ?
                """,
                (registration.lineage_id,),
            ).fetchall()
            if any(row["family_id"] != registration.family_id for row in lineage_rows):
                self._audit_in_transaction(
                    conn,
                    "HYPOTHESIS_LINEAGE_REJECTED",
                    registration.hypothesis_id,
                    {"lineage_id": registration.lineage_id},
                    timestamp,
                )
                conn.commit()
                raise SealedEvidenceError("hypothesis lineage cannot move between families")
            conn.execute(
                """
                INSERT INTO sealed_hypotheses (
                    hypothesis_id, family_id, lineage_id, content_sha256,
                    payload_json, registered_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    registration.hypothesis_id,
                    registration.family_id,
                    registration.lineage_id,
                    content_hash,
                    payload_json,
                    timestamp.isoformat(),
                ),
            )
            self._audit_in_transaction(
                conn,
                "HYPOTHESIS_PREREGISTERED",
                registration.hypothesis_id,
                {
                    "family_id": registration.family_id,
                    "lineage_id": registration.lineage_id,
                    "content_sha256": content_hash,
                },
                timestamp,
            )
        return False

    def register_submission(
        self,
        submission: SealedSubmission,
        *,
        now: datetime | None = None,
    ) -> bool:
        timestamp = self._now(now)
        payload = submission.payload()
        payload_json = canonical_json(payload).decode("utf-8")
        content_hash = sha256_bytes(payload_json.encode("utf-8"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            hypothesis = conn.execute(
                "SELECT hypothesis_id FROM sealed_hypotheses WHERE hypothesis_id = ?",
                (submission.hypothesis_id,),
            ).fetchone()
            if hypothesis is None:
                self._audit_in_transaction(
                    conn,
                    "SUBMISSION_REJECTED",
                    submission.submission_id,
                    {"reason": "HYPOTHESIS_NOT_PREREGISTERED"},
                    timestamp,
                )
                conn.commit()
                raise SealedEvidenceError("submission hypothesis was not preregistered")
            row = conn.execute(
                "SELECT content_sha256 FROM sealed_submissions WHERE submission_id = ?",
                (submission.submission_id,),
            ).fetchone()
            if row is not None:
                if row["content_sha256"] != content_hash:
                    self._audit_in_transaction(
                        conn,
                        "SUBMISSION_CONFLICT_REJECTED",
                        submission.submission_id,
                        {"submitted_content_sha256": content_hash},
                        timestamp,
                    )
                    conn.commit()
                    raise SealedEvidenceError(
                        "submission id reused with different immutable content"
                    )
                self._audit_in_transaction(
                    conn,
                    "SUBMISSION_DUPLICATE",
                    submission.submission_id,
                    {"content_sha256": content_hash},
                    timestamp,
                )
                return True
            conn.execute(
                """
                INSERT INTO sealed_submissions (
                    submission_id, hypothesis_id, artifact_root_sha256,
                    content_sha256, payload_json, registered_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    submission.submission_id,
                    submission.hypothesis_id,
                    submission.artifact_root_sha256,
                    content_hash,
                    payload_json,
                    timestamp.isoformat(),
                ),
            )
            self._audit_in_transaction(
                conn,
                "SUBMISSION_REGISTERED",
                submission.submission_id,
                {
                    "hypothesis_id": submission.hypothesis_id,
                    "artifact_root_sha256": submission.artifact_root_sha256,
                    "content_sha256": content_hash,
                },
                timestamp,
            )
        return False

    def freeze_evaluator_policy(self, payload: Mapping[str, Any]) -> str:
        payload_json = canonical_json(dict(payload)).decode("utf-8")
        policy_hash = sha256_bytes(payload_json.encode("utf-8"))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM sealed_evaluator_policy WHERE id = 1"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO sealed_evaluator_policy VALUES (1, ?, ?)",
                    (policy_hash, payload_json),
                )
                self._audit_in_transaction(
                    conn,
                    "EVALUATOR_POLICY_FROZEN",
                    "sealed-evaluator",
                    {"policy_sha256": policy_hash},
                    self._now(),
                )
            elif row["policy_sha256"] != policy_hash or row["payload_json"] != payload_json:
                raise SealedEvaluationError("sealed evaluator policy drift is forbidden")
        return policy_hash

    def _submission_context(
        self,
        conn: sqlite3.Connection,
        submission_id: str,
    ) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT s.payload_json, s.artifact_root_sha256,
                   h.family_id, h.lineage_id, h.payload_json AS hypothesis_json,
                   h.registered_at_utc
            FROM sealed_submissions s
            JOIN sealed_hypotheses h ON h.hypothesis_id = s.hypothesis_id
            WHERE s.submission_id = ?
            """,
            (submission_id,),
        ).fetchone()
        if row is None:
            raise SealedEvidenceError(f"unknown sealed submission: {submission_id}")
        return row

    def reserve_attempt(
        self,
        submission_id: str,
        *,
        now: datetime | None = None,
    ) -> ReservedAttempt:
        safe_submission = _safe_id(submission_id, "submission id")
        timestamp = self._now(now)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            context = self._submission_context(conn, safe_submission)
            dimensions = {
                "global": ("1=1", (), self.policy.global_attempts),
                "family": (
                    "family_id = ?",
                    (context["family_id"],),
                    self.policy.family_attempts,
                ),
                "lineage": (
                    "lineage_id = ?",
                    (context["lineage_id"],),
                    self.policy.lineage_attempts,
                ),
                "artifact_version": (
                    "artifact_root_sha256 = ?",
                    (context["artifact_root_sha256"],),
                    self.policy.artifact_version_attempts,
                ),
            }
            usage: dict[str, int] = {}
            for dimension, (clause, parameters, limit) in dimensions.items():
                count = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM sealed_attempts WHERE counted = 1 AND {clause}",
                        parameters,
                    ).fetchone()[0]
                )
                usage[dimension] = count
                if count >= limit:
                    self._audit_in_transaction(
                        conn,
                        "BUDGET_REJECTED",
                        safe_submission,
                        {"dimension": dimension, "used": count, "limit": limit},
                        timestamp,
                    )
                    conn.commit()
                    raise SealedBudgetError(
                        f"sealed {dimension} attempt budget exhausted: {count}/{limit}"
                    )
            previous = conn.execute(
                """
                SELECT attempt_id FROM sealed_results WHERE submission_id = ?
                """,
                (safe_submission,),
            ).fetchone()
            attempt_id = f"sea_{uuid.uuid4().hex}"
            duplicate_of = None if previous is None else str(previous["attempt_id"])
            conn.execute(
                """
                INSERT INTO sealed_attempts (
                    attempt_id, submission_id, family_id, lineage_id,
                    artifact_root_sha256, status, counted,
                    duplicate_of_attempt_id, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, 'RESERVED', 1, ?, ?)
                """,
                (
                    attempt_id,
                    safe_submission,
                    context["family_id"],
                    context["lineage_id"],
                    context["artifact_root_sha256"],
                    duplicate_of,
                    timestamp.isoformat(),
                ),
            )
            self._audit_in_transaction(
                conn,
                "ATTEMPT_RESERVED",
                attempt_id,
                {"submission_id": safe_submission, "usage_before": usage},
                timestamp,
            )
        return ReservedAttempt(
            attempt_id=attempt_id,
            submission_id=safe_submission,
            family_id=str(context["family_id"]),
            lineage_id=str(context["lineage_id"]),
            artifact_root_sha256=str(context["artifact_root_sha256"]),
            duplicate_of_attempt_id=duplicate_of,
        )

    def submission_context(self, submission_id: str) -> dict[str, Any]:
        safe_submission = _safe_id(submission_id, "submission id")
        with self._connect() as conn:
            row = self._submission_context(conn, safe_submission)
        return {
            "submission": json.loads(row["payload_json"]),
            "hypothesis": json.loads(row["hypothesis_json"]),
            "registered_at_utc": str(row["registered_at_utc"]),
        }

    def successful_result(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sealed_results WHERE submission_id = ?",
                (_safe_id(submission_id, "submission id"),),
            ).fetchone()
        return None if row is None else dict(row)

    def complete_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        summary: Mapping[str, Any] | None = None,
        result_path: str | None = None,
        error_category: str | None = None,
        infrastructure_refund: bool = False,
        now: datetime | None = None,
    ) -> None:
        allowed = {"SUCCEEDED", "EVALUATION_FAILED", "DUPLICATE", "INFRASTRUCTURE_FAILED"}
        if status not in allowed:
            raise ValueError(f"unsupported sealed attempt status: {status}")
        if infrastructure_refund != (status == "INFRASTRUCTURE_FAILED"):
            raise ValueError("only infrastructure failures may refund an attempt")
        timestamp = self._now(now)
        summary_json = None if summary is None else canonical_json(dict(summary)).decode("utf-8")
        summary_hash = (
            None if summary_json is None else sha256_bytes(summary_json.encode("utf-8"))
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM sealed_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if row is None or row["status"] != "RESERVED":
                raise SealedEvidenceError("sealed attempt is absent or already completed")
            conn.execute(
                """
                UPDATE sealed_attempts SET
                    status = ?, counted = ?, summary_sha256 = ?,
                    error_category = ?, completed_at_utc = ?
                WHERE attempt_id = ?
                """,
                (
                    status,
                    0 if infrastructure_refund else 1,
                    summary_hash,
                    None if error_category is None else error_category[:200],
                    timestamp.isoformat(),
                    attempt_id,
                ),
            )
            if status == "SUCCEEDED":
                if summary_json is None or result_path is None or summary_hash is None:
                    raise ValueError("successful sealed attempt requires summary and result path")
                conn.execute(
                    """
                    INSERT INTO sealed_results (
                        submission_id, attempt_id, summary_sha256,
                        summary_json, result_path, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["submission_id"],
                        attempt_id,
                        summary_hash,
                        summary_json,
                        result_path,
                        timestamp.isoformat(),
                    ),
                )
            self._audit_in_transaction(
                conn,
                f"ATTEMPT_{status}",
                attempt_id,
                {
                    "submission_id": row["submission_id"],
                    "counted": not infrastructure_refund,
                    "summary_sha256": summary_hash,
                    "error_category": error_category,
                },
                timestamp,
            )

    def attempts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM sealed_attempts ORDER BY created_at_utc, attempt_id"
                ).fetchall()
            ]

    def audit_events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM sealed_audit_events ORDER BY event_sequence"
                ).fetchall()
            ]

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = {
                str(row["status"]): int(row["count"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM sealed_attempts GROUP BY status"
                ).fetchall()
            }
            hypotheses = int(conn.execute("SELECT COUNT(*) FROM sealed_hypotheses").fetchone()[0])
            submissions = int(conn.execute("SELECT COUNT(*) FROM sealed_submissions").fetchone()[0])
            counted = int(
                conn.execute(
                    "SELECT COUNT(*) FROM sealed_attempts WHERE counted = 1"
                ).fetchone()[0]
            )
        return {
            "budget_policy_id": self.policy.policy_id,
            "budget_policy_sha256": self.policy.sha256,
            "hypotheses": hypotheses,
            "submissions": submissions,
            "attempt_status_counts": counts,
            "global_counted_attempts": counted,
            "global_attempt_limit": self.policy.global_attempts,
        }


class SealedEvaluator:
    _WORKER_OUTPUT_KEYS = {
        "schema_version",
        "n_sessions",
        "metrics",
        "gates",
        "passed",
    }
    _METRIC_KEYS = {
        "total_return",
        "annualized_return",
        "annualized_volatility",
        "max_drawdown",
        "sharpe",
        "beta_to_benchmark",
    }
    _GATE_KEYS = {
        "minimum_sessions",
        "maximum_drawdown",
        "minimum_sharpe",
        "maximum_beta",
        "maximum_annualized_volatility",
    }

    def __init__(
        self,
        *,
        repo_root: str | Path,
        store: SealedEvidenceStore,
        governance: SealedGovernance,
        results_directory: str | Path,
        worker_path: str | Path,
        metric_policies: Mapping[str, Mapping[str, Any]],
        allowed_benchmark_policies: Sequence[str],
        allowed_cost_policies: Sequence[str],
        timeout_seconds: int = 30,
        maximum_output_bytes: int = 100_000,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.store = store
        self.governance = governance
        self.results_directory = Path(results_directory)
        if self.results_directory.exists() and self.results_directory.is_symlink():
            raise SealedEvaluationError("sealed result directory cannot be a symlink")
        self.results_directory.mkdir(parents=True, exist_ok=True)
        worker = Path(worker_path)
        self.worker_path = worker if worker.is_absolute() else self.repo_root / worker
        if self.worker_path.is_symlink() or not self.worker_path.is_file():
            raise SealedEvaluationError("sealed worker must be a regular non-symlink file")
        self.metric_policies = {
            _safe_id(key, "metric policy id"): dict(value)
            for key, value in metric_policies.items()
        }
        self.allowed_benchmark_policies = frozenset(allowed_benchmark_policies)
        self.allowed_cost_policies = frozenset(allowed_cost_policies)
        if timeout_seconds <= 0 or maximum_output_bytes <= 0:
            raise ValueError("sealed evaluator limits must be positive")
        self.timeout_seconds = int(timeout_seconds)
        self.maximum_output_bytes = int(maximum_output_bytes)
        self.evaluator_policy_sha256 = self.governance.freeze_evaluator_policy(
            {
                "schema_version": 1,
                "worker_sha256": sha256_bytes(self.worker_path.read_bytes()),
                "metric_policies": self.metric_policies,
                "allowed_benchmark_policies": sorted(
                    self.allowed_benchmark_policies
                ),
                "allowed_cost_policies": sorted(self.allowed_cost_policies),
            }
        )

    def _validate_summary(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) != self._WORKER_OUTPUT_KEYS:
            raise SealedEvaluationError("sealed worker output schema mismatch")
        if payload["schema_version"] != 1:
            raise SealedEvaluationError("sealed worker output version mismatch")
        if not isinstance(payload["metrics"], dict) or set(payload["metrics"]) != self._METRIC_KEYS:
            raise SealedEvaluationError("sealed worker metric schema mismatch")
        if not isinstance(payload["gates"], dict) or set(payload["gates"]) != self._GATE_KEYS:
            raise SealedEvaluationError("sealed worker gate schema mismatch")
        if any(type(value) is not bool for value in payload["gates"].values()):
            raise SealedEvaluationError("sealed worker gate values must be booleans")
        if type(payload["passed"]) is not bool or payload["passed"] != all(
            payload["gates"].values()
        ):
            raise SealedEvaluationError("sealed worker pass verdict is inconsistent")
        if not isinstance(payload["n_sessions"], int) or payload["n_sessions"] <= 0:
            raise SealedEvaluationError("sealed worker session count is invalid")
        for value in payload["metrics"].values():
            if value is not None and not math.isfinite(float(value)):
                raise SealedEvaluationError("sealed worker emitted non-finite metric")
        return payload

    def _run_worker(
        self,
        *,
        rows: list[dict[str, Any]],
        artifact_root_sha256: str,
        metric_policy: Mapping[str, Any],
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="pqs-sealed-evaluator-") as temporary_name:
            temporary = Path(temporary_name)
            os.chmod(temporary, 0o700)
            input_path = temporary / "input.json"
            output_path = temporary / "output.json"
            input_path.write_bytes(
                canonical_json(
                    {
                        "schema_version": 1,
                        "artifact_root_sha256": artifact_root_sha256,
                        "rows": rows,
                        "policy": dict(metric_policy),
                    }
                )
                + b"\n"
            )
            os.chmod(input_path, 0o400)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(self.worker_path),
                    str(input_path),
                    str(output_path),
                ],
                cwd=temporary,
                env={
                    "PYTHONHASHSEED": "0",
                    "LC_ALL": "C",
                    "LANG": "C",
                },
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise SealedEvaluationError("sealed worker rejected its fixed input")
            if not output_path.is_file() or output_path.is_symlink():
                raise SealedEvaluationError("sealed worker did not create a regular output")
            if output_path.stat().st_size > self.maximum_output_bytes:
                raise SealedEvaluationError("sealed worker output exceeds fixed size limit")
            output = _read_json_strict(
                output_path,
                maximum_bytes=self.maximum_output_bytes,
            )
            return self._validate_summary(output)

    def evaluate(self, submission_id: str) -> dict[str, Any]:
        attempt = self.governance.reserve_attempt(submission_id)
        previous = self.governance.successful_result(attempt.submission_id)
        if previous is not None:
            prior_result = json.loads(previous["summary_json"])
            self.governance.complete_attempt(
                attempt.attempt_id,
                status="DUPLICATE",
                summary=prior_result,
                error_category="DUPLICATE_SUBMISSION",
            )
            return {
                **prior_result,
                "original_attempt_id": prior_result["attempt_id"],
                "attempt_id": attempt.attempt_id,
                "reused": True,
            }

        context = self.governance.submission_context(attempt.submission_id)
        submission = context["submission"]
        hypothesis = context["hypothesis"]
        try:
            metric_policy_id = str(submission["metric_policy_id"])
            if metric_policy_id not in self.metric_policies:
                raise SealedEvaluationError("submission metric policy is not allowlisted")
            if submission["benchmark_policy_id"] not in self.allowed_benchmark_policies:
                raise SealedEvaluationError("submission benchmark policy is not allowlisted")
            if submission["cost_policy_id"] not in self.allowed_cost_policies:
                raise SealedEvaluationError("submission cost policy is not allowlisted")
            artifact_path = self.repo_root / str(submission["artifact_path"])
            artifact = verify_strategy_artifact(
                artifact_path,
                repo_root=self.repo_root,
                expected_strategy_id=str(submission["artifact_id"]),
                expected_strategy_version=str(submission["artifact_version"]),
                verify_environment=True,
            )
            if artifact["artifact_root_sha256"] != submission["artifact_root_sha256"]:
                raise SealedEvaluationError("submission artifact root does not verify")
            batch = self.store.metadata(str(submission["sealed_batch_id"]))
            if batch.data_schema != "sealed_artifact_returns_v1":
                raise SealedEvaluationError("sealed evaluator batch schema is not supported")
            if batch.quality_flags:
                raise SealedEvaluationError("sealed evaluator refuses quality-flagged batches")
            batch_event = datetime.fromisoformat(batch.event_time_utc)
            registered_at = datetime.fromisoformat(context["registered_at_utc"])
            eligible_start = date.fromisoformat(hypothesis["eligible_data_start"])
            if batch_event.date() < eligible_start:
                raise SealedEvaluationError("sealed batch predates hypothesis eligibility")
            if registered_at > batch_event:
                raise SealedEvaluationError("hypothesis was registered after sealed event time")
            rows = self.store._read_rows_for_evaluator(batch.batch_id)
            summary = self._run_worker(
                rows=rows,
                artifact_root_sha256=str(submission["artifact_root_sha256"]),
                metric_policy=self.metric_policies[metric_policy_id],
            )
            result = {
                "schema_version": 1,
                "attempt_id": attempt.attempt_id,
                "submission_id": attempt.submission_id,
                "hypothesis_lineage_id": attempt.lineage_id,
                "artifact_root_sha256": attempt.artifact_root_sha256,
                "sealed_batch_id": batch.batch_id,
                "sealed_record_sha256": batch.record_sha256,
                "metric_policy_id": metric_policy_id,
                "evaluator_policy_sha256": self.evaluator_policy_sha256,
                "benchmark_policy_id": submission["benchmark_policy_id"],
                "cost_policy_id": submission["cost_policy_id"],
                "summary": summary,
                "raw_rows_returned": False,
            }
            result_path = (
                self.results_directory
                / attempt.submission_id
                / f"{attempt.attempt_id}.json"
            )
            _atomic_create(result_path, result, mode=0o444)
            self.governance.complete_attempt(
                attempt.attempt_id,
                status="SUCCEEDED",
                summary=result,
                result_path=str(result_path),
            )
            return {**result, "reused": False}
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.governance.complete_attempt(
                attempt.attempt_id,
                status="INFRASTRUCTURE_FAILED",
                error_category=type(exc).__name__,
                infrastructure_refund=True,
            )
            raise SealedEvaluationError("sealed evaluator infrastructure failed") from exc
        except Exception as exc:
            self.governance.complete_attempt(
                attempt.attempt_id,
                status="EVALUATION_FAILED",
                error_category=type(exc).__name__,
            )
            if isinstance(exc, SealedEvidenceError):
                raise
            raise SealedEvaluationError("sealed evaluator rejected submission") from exc
