"""Candidate robustness window schema.

Defines the schema for ``<candidate_id>_robustness_window.yaml`` artifacts
that pin the historical window over which a frozen candidate's robustness
eval was executed.

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R1
PRD v3: docs/prd/20260425-oos_validation_framework_codex_v3.md §B/§C
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class EvidenceClass(str, Enum):
    """Evidence classification for a candidate's eval window.

    - ``pseudo_oos_robustness``: historical window before frozen-date,
      treated as pseudo-out-of-sample for robustness assessment. Not
      deployable OOS evidence (PRD v3 §1.1 + §1.3).
    - ``forward_oos``: real forward observation post-frozen-date — the
      only class that constitutes deployable OOS evidence.
    - ``historical_replay``: in-sample window that overlaps candidate
      construction; explicitly rejected by acceptance smoke tests.
    """

    pseudo_oos_robustness = "pseudo_oos_robustness"
    forward_oos = "forward_oos"
    historical_replay = "historical_replay"


class ShrinkReasonCode(str, Enum):
    """Allowed reason codes when ``actual_trading_days < target``."""

    data_coverage_short = "data_coverage_short"
    regime_boundary = "regime_boundary"
    candidate_history_short = "candidate_history_short"
    other = "other"


class ShrinkReason(BaseModel):
    """Justification when actual window is shorter than target."""

    code: ShrinkReasonCode
    note: str = Field(min_length=1, description="Human-readable explanation")


class DataIntegritySnapshot(BaseModel):
    """Pin to a specific data-layer state at the moment of the eval.

    All three fields are mandatory: an eval is only reproducible if the
    data store hash, baseline snapshot, and timestamp are all known.
    """

    daily_store_rebuild_commit: str = Field(
        min_length=12,
        description="Git commit hash that produced data/daily/*.parquet",
    )
    baseline_snapshot_path: str = Field(
        min_length=1,
        description="Path to data/baseline/latest.json (or pinned snapshot)",
    )
    generated_at_utc: datetime = Field(description="Eval generation time, UTC")


class CandidateRobustnessWindow(BaseModel):
    """Schema for ``<candidate_id>_robustness_window.yaml``.

    ``evidence_class`` is intentionally without a default so YAML files
    that omit it fail validation rather than silently default to a
    permissive value.
    """

    candidate_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    start_date: date
    end_date: date
    actual_trading_days: int = Field(ge=1)
    target_trading_days: int = Field(default=252, ge=1)
    shrink_reason: Optional[ShrinkReason] = None
    data_integrity_snapshot: DataIntegritySnapshot

    @model_validator(mode="after")
    def _check_shrink_reason_required(self) -> "CandidateRobustnessWindow":
        if self.actual_trading_days < self.target_trading_days and self.shrink_reason is None:
            raise ValueError(
                f"actual_trading_days ({self.actual_trading_days}) < "
                f"target_trading_days ({self.target_trading_days}) requires shrink_reason"
            )
        return self

    @model_validator(mode="after")
    def _check_date_order(self) -> "CandidateRobustnessWindow":
        if self.end_date < self.start_date:
            raise ValueError(
                f"end_date {self.end_date} must be >= start_date {self.start_date}"
            )
        return self
