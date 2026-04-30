"""Fleet allocator schema models (Track B Step 1).

PRD: docs/prd/20260428-candidate_fleet_allocator_prd.md v1.1 §5.2 + §5.3

Two schema layers:
  - ``FleetConfig``  — input config (config/fleet.yaml). Owned by the
    operator; pydantic-validated at load time. ``extra="forbid"`` so
    typo'd keys (``max_pairwise_corr_warning`` vs ``..._warn``) fail
    closed instead of silently disappearing.
  - ``FleetManifest`` — output ledger (data/fleet_runs/fleet_manifest.json).
    Append-only audit trail of fleet rebalances + throttle / removal
    events. Schema mirrors ``ForwardRunManifest`` style (parallel to
    forward observation but at fleet-composition layer).

Step 1 covers schema definition only — no fleet logic. Steps 2-4
implement capital split (C1), compose_weight_matrix, and C3 overlap
throttle on top of these models.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Config schema (config/fleet.yaml)
# ---------------------------------------------------------------------------


_RoleLiteral = Literal["core", "satellite"]
_SplitPolicyLiteral = Literal["equal_weight", "manual_overrides"]


class FleetCandidate(BaseModel):
    """A single candidate registered in the fleet.

    ``base_weight`` is the operator's intended capital share BEFORE any
    runtime throttle (DD, correlation, overlap). The actual realised
    weight at a rebalance can be lower, never higher (no leverage v1).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    role: _RoleLiteral
    base_weight: float = Field(ge=0.0, le=1.0)


class DDThrottleConfig(BaseModel):
    """C5 drawdown throttle thresholds (Step 6 — defined here for schema
    completeness but not consumed by Step 1-4 code)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    warning_pct: float = Field(gt=0.0, lt=1.0)
    defensive_pct: float = Field(gt=0.0, lt=1.0)
    halt_pct: float = Field(gt=0.0, lt=1.0)
    recovery_consecutive_days: int = Field(ge=1)
    rolling_window_days: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> "DDThrottleConfig":
        if not (self.warning_pct < self.defensive_pct < self.halt_pct):
            raise ValueError(
                "DD throttle thresholds must be strictly ordered: "
                f"warning ({self.warning_pct}) < defensive "
                f"({self.defensive_pct}) < halt ({self.halt_pct})"
            )
        return self


class RemovalRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    forward_decision_fail: bool = True
    pairwise_corr_above: float = Field(gt=0.0, le=1.0, default=0.95)
    m12_manual_review_streak_days: int = Field(ge=1, default=5)


class ParkingRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    m12_thin_data_extreme: float = Field(gt=0.0, lt=1.0, default=0.10)


class FleetConfig(BaseModel):
    """Top-level config/fleet.yaml schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: List[FleetCandidate] = Field(min_length=1)
    split_policy: _SplitPolicyLiteral = "equal_weight"

    # C2 correlation budget (Step 5)
    max_pairwise_corr_warn: float = Field(gt=0.0, le=1.0, default=0.70)
    max_pairwise_corr_reject: float = Field(gt=0.0, le=1.0, default=0.85)
    corr_lookback_days: int = Field(ge=21, default=252)

    # C3 overlap throttle (Step 4)
    max_fleet_symbol_weight: float = Field(gt=0.0, le=1.0, default=0.20)

    # C4 role sleeve constraints (Step 7)
    core_min_capital_pct: float = Field(ge=0.0, le=1.0, default=0.60)
    satellite_max_capital_pct: float = Field(ge=0.0, le=1.0, default=0.40)

    # C5 DD throttle (Step 6)
    dd_throttle: DDThrottleConfig = Field(
        default_factory=lambda: DDThrottleConfig(
            warning_pct=0.10, defensive_pct=0.15, halt_pct=0.20,
            recovery_consecutive_days=5, rolling_window_days=60,
        )
    )

    # C6 removal / parking rules (Step 7)
    removal_rules: RemovalRules = Field(default_factory=RemovalRules)
    parking_rules: ParkingRules = Field(default_factory=ParkingRules)

    @model_validator(mode="after")
    def _ordered_corr_budget(self) -> "FleetConfig":
        if self.max_pairwise_corr_warn >= self.max_pairwise_corr_reject:
            raise ValueError(
                f"max_pairwise_corr_warn ({self.max_pairwise_corr_warn}) "
                f"must be < max_pairwise_corr_reject "
                f"({self.max_pairwise_corr_reject})"
            )
        return self

    @model_validator(mode="after")
    def _unique_candidate_ids(self) -> "FleetConfig":
        ids = [c.candidate_id for c in self.candidates]
        if len(ids) != len(set(ids)):
            dups = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate candidate_id(s) in fleet config: {dups}")
        return self

    @model_validator(mode="after")
    def _sleeve_floor_feasible(self) -> "FleetConfig":
        # core_min_capital_pct > 0 requires at least one core candidate
        # (otherwise the floor is unreachable). Run this check unconditionally
        # — the outer "core_min + satellite_max > 1.0" gate from the original
        # draft was wrong (defaults sum to exactly 1.0 and the gate skipped
        # the feasibility check).
        n_core = sum(1 for c in self.candidates if c.role == "core")
        if n_core == 0 and self.core_min_capital_pct > 0.0:
            raise ValueError(
                "core_min_capital_pct > 0 but no core candidates configured"
            )
        return self


def load_fleet_config(path: str | Path) -> FleetConfig:
    """Load + validate config/fleet.yaml. Raises on schema violations."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"fleet config not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return FleetConfig.model_validate(raw)


# ---------------------------------------------------------------------------
# Manifest schema (data/fleet_runs/fleet_manifest.json)
# ---------------------------------------------------------------------------


class ConcentrationSnapshot(BaseModel):
    """M12 fleet-level concentration metrics (Step 4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    m12_top1_weight_max: float = Field(ge=0.0, le=1.0)
    m12_top3_weight_max: float = Field(ge=0.0, le=1.0)


class FleetEvent(BaseModel):
    """A single event recorded against a fleet rebalance.

    Categories:
      - ``c2_corr_violation`` — pairwise corr above threshold
      - ``c3_overlap_trim``   — symbol weight trimmed to cap
      - ``c5_dd_throttle``    — fleet DD trigger
      - ``c6_removal``        — candidate removed
      - ``c6_parking``        — candidate parked
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal[
        "c2_corr_violation", "c3_overlap_trim", "c5_dd_throttle",
        "c6_removal", "c6_parking",
    ]
    severity: Literal["info", "warn", "halt"]
    detail: Dict[str, object] = Field(default_factory=dict)


class FleetRebalance(BaseModel):
    """One rebalance entry in the manifest's append-only ``rebalances`` list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rebalance_date: _date
    candidate_weights: Dict[str, float]
    fleet_weight_matrix_hash: str = Field(min_length=16)
    throttle_factor: float = Field(ge=0.0, le=1.0)
    throttle_reason: Optional[str] = None
    concentration_metrics: ConcentrationSnapshot
    events: List[FleetEvent] = Field(default_factory=list)
    fleet_nav: Optional[float] = None
    fleet_dd_60d: Optional[float] = None
    spy_dd_60d: Optional[float] = None
    dd_vs_spy_60d: Optional[float] = None
    vs_spy: Optional[float] = None
    vs_qqq: Optional[float] = None
    shadow: bool = True

    @field_validator("candidate_weights")
    @classmethod
    def _weights_in_range(cls, v):
        for cid, w in v.items():
            if not (0.0 <= w <= 1.0):
                raise ValueError(f"candidate_weight for {cid!r} = {w} out of [0,1]")
        return v


class FleetManifest(BaseModel):
    """Top-level fleet manifest schema.

    Mirrors ``ForwardRunManifest``: append-only ``rebalances`` list,
    config snapshot pinned at fleet-init time, schema_version locked.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    fleet_id: str = Field(min_length=1)
    schema_version: Literal["1.0"] = "1.0"
    candidates: List[FleetCandidate] = Field(min_length=1)
    rebalances: List[FleetRebalance] = Field(default_factory=list)
    created_at_utc: datetime
