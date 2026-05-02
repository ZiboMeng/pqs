"""Research candidate registry (Phase E-0 R1).

SQLite-backed governance layer for research candidates.  Separate from
the experimental trial archive (`core/mining/rcm_archive.py`) — trials
are immutable experiment records; candidates are governance objects
with a state machine, promote, and revoke workflow.

Default DB path: `data/research_candidates/registry.db`.

Schema (rationale in PRD docs/20260424-prd_phase_e_execution.md §E0-R1):

    research_candidates
        candidate_id          TEXT PRIMARY KEY
        source_trial_id       TEXT NOT NULL     -- link to rcm_trials
        source_lineage_tag    TEXT NOT NULL
        status                TEXT NOT NULL     -- S0/S1/S2/S5 only this phase
        frozen_spec_path      TEXT
        decision_memo_path    TEXT
        promoted_at           TEXT
        revoked_at            TEXT
        revoke_reason         TEXT
        revoke_memo_path      TEXT
        created_at            TEXT NOT NULL
        updated_at            TEXT NOT NULL

State machine (per PRD layered arch §4; S3/S4 enum-valid but rejected by
business logic in Phase E):

    S0_research_prototype  (freshly created)
          |
          v  research_promote (via scripts/research_promote.py, R6)
    S1_research_candidate  (passed research acceptance)
          |
          v  paper_enter (via scripts/paper_enter.py, R11)
    S2_paper_candidate     (running in paper)
          |
          v  (S3_deployment_candidate: rejected this phase)

    Revoke transition: any state -> S5_deprecated (via revoke_candidate)
    Reset transition:  S1 -> S0 (for reproducibility issues, revoke_reason=
                       'reproducibility_failed')

Invariant: trial_id from rcm_archive is NEVER mutated; registry only
stores a pointer plus governance metadata.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional

from core.logging_setup import get_logger

logger = get_logger(__name__)


# ── State enum ───────────────────────────────────────────────────────────────


class CandidateStatus(str, Enum):
    """Candidate lifecycle state. Phase E operates on S0/S1/S2/S5 only.

    S3 / S4 are schema-valid values reserved for Phase F (production
    layer). Business logic in Phase E rejects any transition to S3/S4.
    """

    S0_PROTOTYPE = "S0_research_prototype"
    S1_CANDIDATE = "S1_research_candidate"
    S2_PAPER = "S2_paper_candidate"
    S3_DEPLOYMENT = "S3_deployment_candidate"   # design-only this phase
    S4_PRODUCTION = "S4_production"             # design-only this phase
    S5_DEPRECATED = "S5_deprecated"

    @classmethod
    def phase_e_active(cls) -> set["CandidateStatus"]:
        return {cls.S0_PROTOTYPE, cls.S1_CANDIDATE, cls.S2_PAPER,
                cls.S5_DEPRECATED}


# Allowed forward transitions. Any state can revoke to S5 — handled
# separately in revoke_candidate(). Reset from S1 -> S0 also allowed
# (for reproducibility failures).
_ALLOWED_TRANSITIONS: dict[CandidateStatus, set[CandidateStatus]] = {
    CandidateStatus.S0_PROTOTYPE: {CandidateStatus.S1_CANDIDATE},
    CandidateStatus.S1_CANDIDATE: {CandidateStatus.S2_PAPER,
                                   CandidateStatus.S0_PROTOTYPE},
    CandidateStatus.S2_PAPER: set(),   # S3 transition rejected this phase
    CandidateStatus.S5_DEPRECATED: set(),   # terminal
}


# Revoke reason enum — aligns with scripts/revoke_candidate.py R3
class RevokeReason(str, Enum):
    LEAKAGE_FOUND = "leakage_found"
    REPRODUCIBILITY_FAILED = "reproducibility_failed"
    BENCHMARK_MISALIGNED = "benchmark_misaligned"
    CANDIDATE_SUPERSEDED = "candidate_superseded"
    SPEC_UNREPRODUCIBLE = "spec_unreproducible"
    OTHER = "other"


class InvalidTransitionError(ValueError):
    """Raised when requested state transition is not allowed."""


class CandidateNotFoundError(LookupError):
    """Raised when lookup by candidate_id yields nothing."""


class DuplicateCandidateError(ValueError):
    """Raised when registering a candidate_id that already exists."""


# ── Schema ────────────────────────────────────────────────────────────────────


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS research_candidates (
    candidate_id          TEXT    PRIMARY KEY,
    source_trial_id       TEXT    NOT NULL,
    source_lineage_tag    TEXT    NOT NULL,
    status                TEXT    NOT NULL,
    frozen_spec_path      TEXT,
    decision_memo_path    TEXT,
    promoted_at           TEXT,
    revoked_at            TEXT,
    revoke_reason         TEXT,
    revoke_memo_path      TEXT,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL
)
"""

_CREATE_INDEX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_research_candidates_status
    ON research_candidates(status)
"""

_CREATE_INDEX_SOURCE = """
CREATE INDEX IF NOT EXISTS idx_research_candidates_source
    ON research_candidates(source_trial_id, source_lineage_tag)
"""

# Two-Stage Allocation Architecture PRD additive (2026-05-01).
# Idempotent ALTER TABLE for `role` column; defaults to
# 'legacy_decay_verification' for existing rows. SQLite ALTER TABLE
# semantics: adding a column with default fills existing rows.
_ALTER_ADD_ROLE = """
ALTER TABLE research_candidates
ADD COLUMN role TEXT NOT NULL DEFAULT 'legacy_decay_verification'
"""

_VALID_ROLES = frozenset({
    "core_alpha", "diversifier", "legacy_decay_verification", "risk_control",
})


# ── Row dataclass ─────────────────────────────────────────────────────────────


@dataclass
class CandidateRecord:
    """In-memory view of a candidate row."""

    candidate_id: str
    source_trial_id: str
    source_lineage_tag: str
    status: CandidateStatus
    created_at: str
    updated_at: str
    frozen_spec_path: Optional[str] = None
    decision_memo_path: Optional[str] = None
    promoted_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoke_reason: Optional[str] = None
    revoke_memo_path: Optional[str] = None
    # Two-Stage Allocation Architecture PRD additive (2026-05-01).
    # IMMUTABLE post-init. See manifest_schema.CandidateRole + PRD §6.
    role: str = "legacy_decay_verification"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "candidate_id": self.candidate_id,
            "source_trial_id": self.source_trial_id,
            "source_lineage_tag": self.source_lineage_tag,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "frozen_spec_path": self.frozen_spec_path,
            "decision_memo_path": self.decision_memo_path,
            "promoted_at": self.promoted_at,
            "revoked_at": self.revoked_at,
            "revoke_reason": self.revoke_reason,
            "revoke_memo_path": self.revoke_memo_path,
            "role": self.role,
        }
        return d


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Registry class ────────────────────────────────────────────────────────────


class CandidateRegistry:
    """SQLite-backed registry for research candidates.

    Thread-safe for basic CRUD (SQLite connection-per-call pattern).
    """

    DEFAULT_DB = Path("data/research_candidates/registry.db")

    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX_STATUS)
            conn.execute(_CREATE_INDEX_SOURCE)
            # Idempotent ALTER for `role` column (Two-Stage PRD 2026-05-01).
            # Existing rows get default 'legacy_decay_verification'.
            cols = {r[1] for r in conn.execute("PRAGMA table_info(research_candidates)")}
            if "role" not in cols:
                conn.execute(_ALTER_ADD_ROLE)
                logger.info(
                    "Migrated research_candidates: added role column "
                    "(default=legacy_decay_verification for existing rows)"
                )
            conn.commit()

    # ── Registration ────────────────────────────────────────────────────

    def register(
        self,
        *,
        candidate_id: str,
        source_trial_id: str,
        source_lineage_tag: str,
        status: CandidateStatus = CandidateStatus.S0_PROTOTYPE,
        frozen_spec_path: Optional[str] = None,
        decision_memo_path: Optional[str] = None,
        promoted_at: Optional[str] = None,
        role: str = "legacy_decay_verification",
    ) -> CandidateRecord:
        """Register a new candidate.

        Default status is S0. Caller can pass a higher state (e.g. S1 for
        migration of RCMv1 memo in R3) but business rules still apply —
        if status != S0, promoted_at is required.

        ``role`` (Two-Stage Allocation Architecture PRD 2026-05-01):
        candidate role per PRD §6. IMMUTABLE post-init. Default = legacy_
        decay_verification (matches lazy-migration semantic for pre-PRD
        candidates). Valid values: core_alpha, diversifier,
        legacy_decay_verification, risk_control. Mutation of role on an
        existing candidate is REJECTED — to change role, revoke the
        candidate and re-register under a new candidate_id.

        Raises DuplicateCandidateError if candidate_id already exists.
        Raises ValueError if role is not in _VALID_ROLES.
        """
        self._validate_status(status)
        if role not in _VALID_ROLES:
            raise ValueError(
                f"role={role!r} not in valid roles {sorted(_VALID_ROLES)}"
            )
        if status != CandidateStatus.S0_PROTOTYPE and not promoted_at:
            promoted_at = _now_utc_iso()
        now = _now_utc_iso()
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO research_candidates (
                        candidate_id, source_trial_id, source_lineage_tag,
                        status, frozen_spec_path, decision_memo_path,
                        promoted_at, created_at, updated_at, role
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (candidate_id, source_trial_id, source_lineage_tag,
                     status.value, frozen_spec_path, decision_memo_path,
                     promoted_at, now, now, role),
                )
                conn.commit()
            except sqlite3.IntegrityError as e:
                raise DuplicateCandidateError(
                    f"candidate_id={candidate_id!r} already registered"
                ) from e
        logger.info(
            "Registered candidate %s (source_trial_id=%s, status=%s, role=%s)",
            candidate_id, source_trial_id, status.value, role,
        )
        return self.get(candidate_id)

    # ── Read ────────────────────────────────────────────────────────────

    def get(self, candidate_id: str) -> CandidateRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise CandidateNotFoundError(
                f"candidate_id={candidate_id!r} not in registry"
            )
        return _row_to_record(row)

    def exists(self, candidate_id: str) -> bool:
        try:
            self.get(candidate_id)
            return True
        except CandidateNotFoundError:
            return False

    def list_by_status(
        self, status: Optional[CandidateStatus] = None,
    ) -> List[CandidateRecord]:
        sql = "SELECT * FROM research_candidates"
        params: tuple = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status.value,)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_record(r) for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM research_candidates"
            ).fetchone()[0])

    # ── State transition ────────────────────────────────────────────────

    def transition(
        self,
        candidate_id: str,
        to_status: CandidateStatus,
        *,
        promoted_at: Optional[str] = None,
    ) -> CandidateRecord:
        """Transition a candidate to a new state.

        Forward transitions only via this method. Use `revoke()` for
        S5_DEPRECATED transitions — revoke carries additional metadata
        (revoke_reason, revoke_memo_path).

        Raises InvalidTransitionError if:
        - candidate does not exist
        - to_status is S3 or S4 (design-only this phase)
        - from→to is not in _ALLOWED_TRANSITIONS
        - to_status is S5 (use revoke() instead)
        """
        self._validate_status(to_status)
        if to_status == CandidateStatus.S5_DEPRECATED:
            raise InvalidTransitionError(
                "Use revoke() to reach S5_deprecated, not transition()"
            )
        current = self.get(candidate_id)
        from_status = current.status
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise InvalidTransitionError(
                f"Not allowed: {from_status.value} -> {to_status.value}; "
                f"allowed={[s.value for s in allowed]}"
            )
        now = _now_utc_iso()
        if to_status == CandidateStatus.S1_CANDIDATE:
            promoted_at = promoted_at or now
        with self._connect() as conn:
            if promoted_at and from_status == CandidateStatus.S0_PROTOTYPE:
                conn.execute(
                    """UPDATE research_candidates
                       SET status = ?, promoted_at = ?, updated_at = ?
                       WHERE candidate_id = ?""",
                    (to_status.value, promoted_at, now, candidate_id),
                )
            else:
                conn.execute(
                    """UPDATE research_candidates
                       SET status = ?, updated_at = ?
                       WHERE candidate_id = ?""",
                    (to_status.value, now, candidate_id),
                )
            conn.commit()
        logger.info(
            "Transitioned %s: %s -> %s",
            candidate_id, from_status.value, to_status.value,
        )
        return self.get(candidate_id)

    def revoke(
        self,
        candidate_id: str,
        *,
        reason: RevokeReason,
        memo_path: Optional[str] = None,
    ) -> CandidateRecord:
        """Revoke a candidate. Transitions to S5_deprecated.

        `reason` is required (enum value). `memo_path` is recommended
        (the revoke decision memo). Re-revoking an already-deprecated
        candidate is rejected.
        """
        if not isinstance(reason, RevokeReason):
            raise InvalidTransitionError(
                f"reason must be RevokeReason enum, got {type(reason)}"
            )
        current = self.get(candidate_id)
        if current.status == CandidateStatus.S5_DEPRECATED:
            raise InvalidTransitionError(
                f"candidate {candidate_id} already revoked "
                f"(reason={current.revoke_reason}, at={current.revoked_at})"
            )
        # Special case: reproducibility_failed reverts to S0 instead
        # of going to S5 — "we failed to reproduce, back to prototype"
        if reason == RevokeReason.REPRODUCIBILITY_FAILED:
            target = CandidateStatus.S0_PROTOTYPE
        else:
            target = CandidateStatus.S5_DEPRECATED
        now = _now_utc_iso()
        with self._connect() as conn:
            conn.execute(
                """UPDATE research_candidates
                   SET status = ?, revoked_at = ?, revoke_reason = ?,
                       revoke_memo_path = ?, updated_at = ?
                   WHERE candidate_id = ?""",
                (target.value, now, reason.value, memo_path, now,
                 candidate_id),
            )
            conn.commit()
        logger.warning(
            "Revoked candidate %s (reason=%s, target=%s, memo=%s)",
            candidate_id, reason.value, target.value, memo_path,
        )
        return self.get(candidate_id)

    # ── Update auxiliary fields ─────────────────────────────────────────

    def update_paths(
        self,
        candidate_id: str,
        *,
        frozen_spec_path: Optional[str] = None,
        decision_memo_path: Optional[str] = None,
    ) -> CandidateRecord:
        """Update frozen_spec_path and/or decision_memo_path."""
        current = self.get(candidate_id)
        now = _now_utc_iso()
        new_frozen = (frozen_spec_path if frozen_spec_path is not None
                      else current.frozen_spec_path)
        new_memo = (decision_memo_path if decision_memo_path is not None
                    else current.decision_memo_path)
        with self._connect() as conn:
            conn.execute(
                """UPDATE research_candidates
                   SET frozen_spec_path = ?, decision_memo_path = ?,
                       updated_at = ?
                   WHERE candidate_id = ?""",
                (new_frozen, new_memo, now, candidate_id),
            )
            conn.commit()
        return self.get(candidate_id)

    # ── Validation helpers ──────────────────────────────────────────────

    def _validate_status(self, status: CandidateStatus) -> None:
        if not isinstance(status, CandidateStatus):
            raise InvalidTransitionError(
                f"status must be CandidateStatus enum, got {type(status)}"
            )
        if status in {CandidateStatus.S3_DEPLOYMENT,
                      CandidateStatus.S4_PRODUCTION}:
            raise InvalidTransitionError(
                f"{status.value} is out of scope for Phase E "
                "(design-only; use Phase F tooling when built)"
            )


def _row_to_record(row: sqlite3.Row) -> CandidateRecord:
    # `role` column is added via ALTER TABLE migration; rows from a
    # pre-PRD DB that just had migration applied have role=
    # 'legacy_decay_verification' (column DEFAULT). Defensive .get-style
    # access via dict() so older sqlite3.Row variants without the column
    # still work for testing.
    row_dict = dict(row)
    return CandidateRecord(
        candidate_id=row_dict["candidate_id"],
        source_trial_id=row_dict["source_trial_id"],
        source_lineage_tag=row_dict["source_lineage_tag"],
        status=CandidateStatus(row_dict["status"]),
        created_at=row_dict["created_at"],
        updated_at=row_dict["updated_at"],
        frozen_spec_path=row_dict.get("frozen_spec_path"),
        decision_memo_path=row_dict.get("decision_memo_path"),
        promoted_at=row_dict.get("promoted_at"),
        revoked_at=row_dict.get("revoked_at"),
        revoke_reason=row_dict.get("revoke_reason"),
        revoke_memo_path=row_dict.get("revoke_memo_path"),
        role=row_dict.get("role", "legacy_decay_verification"),
    )
