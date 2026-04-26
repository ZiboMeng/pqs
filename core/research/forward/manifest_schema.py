"""Forward run manifest schema (SCHEMA ONLY — no runner).

Defines the schema for ``forward_run_manifest.json`` per PRD v3 §B.
Forward observation is the **only** evidence class that constitutes
deployable OOS evidence; this manifest pins the forward run's contract
(spec hash, benchmark, cost assumptions, checkpoint cadence, data
integrity snapshot) before any forward bar is observed, so that the
candidate's forward result cannot be hindsight-tuned.

Hard schema invariants:
  - ``evidence_class`` MUST equal ``EvidenceClass.forward_oos``. Any
    other value (including ``pseudo_oos_robustness`` or
    ``historical_replay``) is rejected at schema construction. This is
    the contract acceptance smoke (R6) deliberately exercises by
    setting ``historical_replay`` and verifying rejection.
  - ``data_integrity_snapshot`` is mandatory and reuses the same
    ``DataIntegritySnapshot`` model used by robustness eval, so a
    manifest is reproducible only if the data store hash, baseline
    snapshot, and timestamp are all known.
  - The schema deliberately does NOT include any runner / executor /
    state-mutation hooks. PRD v3 §B: schema only, no automation.

PRD: docs/prd/20260425-oos_validation_framework_codex_v3.md §B
Execution PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R5
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from core.research.robustness.window_spec import (
    DataIntegritySnapshot,
    EvidenceClass,
)


class ForwardRunStatus(str, Enum):
    """Lifecycle status of a forward run.

    The MVP manifest only ships ``not_started``. Other values are
    enumerated for forward-compatibility so future automation can write
    them without re-versioning the schema.
    """

    not_started = "not_started"
    in_progress = "in_progress"
    decision_pending = "decision_pending"
    completed_success = "completed_success"
    completed_fail = "completed_fail"
    aborted = "aborted"


class CostAssumptions(BaseModel):
    """Cost-model assumptions frozen at forward-run start.

    PRD v3 §B requires the cost model + its config hash to be pinned
    so that "the candidate's forward result cannot be hindsight-tuned"
    by tweaking the cost model after seeing forward NAV.
    """

    source: str = Field(
        min_length=1,
        description="Path to the cost model config (e.g. config/cost_model.yaml)",
    )
    config_hash: str = Field(
        min_length=12,
        description="SHA-256 (or equivalent) hash of the config bytes; >=12 chars",
    )


class CheckpointCadence(BaseModel):
    """Operational checkpoint cadence frozen at forward-run start.

    PRD v3 §B specifies weekly + 10/20/40/60 TD decision days. These are
    defaults; manifests can override but the cadence MUST be frozen
    before forward begins.
    """

    weekly: bool = True
    decision_days: list[int] = Field(default_factory=lambda: [10, 20, 40, 60])

    @model_validator(mode="after")
    def _check_decision_days_positive_and_sorted(self) -> "CheckpointCadence":
        if any(d <= 0 for d in self.decision_days):
            raise ValueError(
                f"decision_days must all be positive integers, got {self.decision_days}"
            )
        if list(self.decision_days) != sorted(self.decision_days):
            raise ValueError(
                f"decision_days must be ascending, got {self.decision_days}"
            )
        if len(set(self.decision_days)) != len(self.decision_days):
            raise ValueError(
                f"decision_days must be unique, got {self.decision_days}"
            )
        return self


class ForwardRun(BaseModel):
    """A single forward observation entry.

    The MVP ships an empty ``runs`` list. Future automation will append
    one entry per checkpoint as forward observation accumulates. The
    schema defines the entry shape now so future writers don't have to
    re-version the manifest.

    ``source_mix`` (post-2026-04-26 audit, additive optional field):
    True if the bars used to compute this entry come from a different
    source layer than the candidate's frozen construction layer (i.e.,
    the observation window includes any held-symbol bar that is in
    that symbol's yfinance frontier — see
    ``core.data.source_boundaries``). False if the entry is entirely
    on the candidate's construction source layer. None if boundary
    state cannot be determined.
    """

    checkpoint_label: str = Field(min_length=1, description="e.g. '10TD' / 'weekly_w03'")
    as_of_date: date
    n_observed_trading_days: int = Field(ge=0)
    cum_ret: Optional[float] = None
    sharpe: Optional[float] = None
    max_dd: Optional[float] = None
    vs_spy: Optional[float] = None
    vs_qqq: Optional[float] = None
    notes: Optional[str] = None
    source_mix: Optional[bool] = None


class ForwardRunManifest(BaseModel):
    """Schema for ``forward_run_manifest.json`` (PRD v3 §B).

    Hard invariant enforced by ``_check_evidence_class``:
        evidence_class == EvidenceClass.forward_oos
    Any other value is rejected at construction; this is the contract
    R6 acceptance smoke deliberately exercises with ``historical_replay``.
    """

    schema_version: str = Field(default="1.0", min_length=1)
    candidate_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    spec_hash: str = Field(
        min_length=12,
        description="Frozen-spec hash (>=12 chars) — pins exact strategy artifact",
    )
    start_date: date
    benchmark: str = Field(default="SPY", min_length=1)
    secondary_benchmark: Optional[str] = "QQQ"
    cost_assumptions: CostAssumptions
    checkpoint_cadence: CheckpointCadence = Field(default_factory=CheckpointCadence)
    current_status: ForwardRunStatus = ForwardRunStatus.not_started
    data_integrity_snapshot: DataIntegritySnapshot
    runs: list[ForwardRun] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_evidence_class(self) -> "ForwardRunManifest":
        if self.evidence_class is not EvidenceClass.forward_oos:
            raise ValueError(
                f"forward_run_manifest.evidence_class must be "
                f"{EvidenceClass.forward_oos.value!r}, got {self.evidence_class.value!r}. "
                f"Pseudo-OOS robustness and historical replay never qualify as forward "
                f"OOS evidence (PRD v3 §1.1 + §1.3)."
            )
        return self
