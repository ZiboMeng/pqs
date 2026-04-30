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

Schema-side additions per shipping step:
  - Step 1 — FleetCandidate / FleetConfig / FleetManifest / FleetRebalance / FleetEvent.
  - Step 4 — ConcentrationSnapshot (M12 top1 / top3 / n_dates).
  - Step 5 — CorrelationPair / CorrelationBudgetStatus + ``corr_min_overlap_days``
    config field with ordering validator (≤ ``corr_lookback_days``).

The runtime methods live in ``core.fleet.allocator`` and are pure-
functional through Step 5 (no manifest mutation). Step 8 (frozen)
is the boundary that translates Step 5's ``CorrelationBudgetStatus``
and Step 4's ``ConcentrationSnapshot`` into manifest events.
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


# ---------------------------------------------------------------------------
# Track A ↔ Fleet role vocabulary bridge (codex R25 P1)
# ---------------------------------------------------------------------------
#
# Track A (research / mining governance) labels candidates ``core`` or
# ``diversifier``. Fleet (capital allocation) labels them ``core`` or
# ``satellite``. Both share ``core`` semantically. The labels diverge for
# the secondary role because Track A's name reflects the GOVERNANCE
# constraint (a diversifier must demonstrate low correlation to existing
# core to be eligible) while Fleet's name reflects the ALLOCATION
# semantic (satellite sleeve is the ≤ 40% capacity outside core).
#
# When a Track-A-promoted candidate enters the Fleet, its role label
# must NOT be silently reused — translate via ``track_a_role_to_fleet_role``
# below so the promotion is auditable.

TRACK_A_TO_FLEET_ROLE_MAP: Dict[str, str] = {
    "core":         "core",
    "diversifier":  "satellite",
}


def track_a_role_to_fleet_role(track_a_role: str) -> str:
    """Translate a Track A role to its Fleet equivalent.

    Codex R25 P1: Track A uses ``core`` / ``diversifier`` (governance
    labels reflecting eligibility constraints). Fleet uses ``core`` /
    ``satellite`` (allocation labels reflecting sleeve capacity).
    Both share ``core`` semantically; ``diversifier`` → ``satellite``
    is the deterministic translation.

    Raises ``ValueError`` for unknown inputs to prevent silent
    re-interpretation at promotion time.
    """
    if track_a_role not in TRACK_A_TO_FLEET_ROLE_MAP:
        raise ValueError(
            f"unknown Track A role {track_a_role!r}; expected one of "
            f"{sorted(TRACK_A_TO_FLEET_ROLE_MAP)}. If a new Track A role "
            f"is introduced, extend TRACK_A_TO_FLEET_ROLE_MAP explicitly "
            f"and document the mapping in the temporal_split.yaml + "
            f"fleet.yaml docstrings."
        )
    return TRACK_A_TO_FLEET_ROLE_MAP[track_a_role]


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
    corr_min_overlap_days: int = Field(ge=21, default=60)

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
    def _ordered_corr_overlap(self) -> "FleetConfig":
        if self.corr_min_overlap_days > self.corr_lookback_days:
            raise ValueError(
                f"corr_min_overlap_days ({self.corr_min_overlap_days}) must "
                f"be <= corr_lookback_days ({self.corr_lookback_days})"
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

    @model_validator(mode="after")
    def _manual_overrides_must_sum_to_one(self) -> "FleetConfig":
        """Audit D7 (2026-04-29 R2): when split_policy=manual_overrides,
        the configured base_weights MUST sum to 1.0 (within 1e-9). Catching
        this at config-load — rather than waiting until the first
        ``compute_capital_split()`` call — gives the operator a clear
        error at startup instead of partway through a mining run.

        equal_weight is not subject to this check (base_weight is ignored).
        """
        if self.split_policy != "manual_overrides":
            return self
        total = sum(c.base_weight for c in self.candidates)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"split_policy=manual_overrides requires sum(base_weight) "
                f"== 1.0 (within 1e-9); got {total}. Adjust base_weights "
                f"or switch to split_policy=equal_weight."
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
    """M12 fleet-level concentration metrics (Step 4).

    Codex R25 P0.2 fix (2026-04-29): added ``m12_n_dates_with_weights``
    so the output of ``FleetAllocator.compute_concentration_metrics()``
    can be passed directly into this model without ``extra="forbid"``
    rejecting the third field. The PRD §5.3 manifest example already
    listed n-dates-with-weights conceptually; the schema now matches.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    m12_top1_weight_max: float = Field(ge=0.0, le=1.0)
    m12_top3_weight_max: float = Field(ge=0.0, le=1.0)
    m12_n_dates_with_weights: int = Field(ge=0)


_CorrLevel = Literal["ok", "warn", "reject", "insufficient_data"]


class CorrelationPair(BaseModel):
    """One pairwise candidate-return correlation entry (Step 5 / C2).

    ``level`` is the per-pair classification against the fleet-config
    thresholds (``warn`` ≥ ``max_pairwise_corr_warn`` and < reject;
    ``reject`` ≥ ``max_pairwise_corr_reject``). Aggregate across all
    pairs surfaces in ``CorrelationBudgetStatus.level``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_a: str = Field(min_length=1)
    candidate_b: str = Field(min_length=1)
    correlation: float = Field(ge=-1.0, le=1.0)
    level: Literal["ok", "warn", "reject"]


class CorrelationBudgetStatus(BaseModel):
    """C2 pairwise correlation budget status (Step 5).

    Pure-functional return value of
    ``FleetAllocator.check_correlation_budget()``. Caller (allocator
    composition / observe wiring at Step 8) decides whether to convert
    this into a FleetEvent (``c2_corr_violation``) on the manifest.
    Step 5 itself does NOT mutate the manifest; the manifest-write
    pathway (``observe`` / Step 8) is the codex-frozen boundary.

    Levels:
      - ``ok``                 — every pairwise correlation < warn threshold.
      - ``warn``               — at least one pair ≥ warn but < reject.
      - ``reject``             — at least one pair ≥ reject; composition
                                 must not proceed without manual override.
      - ``insufficient_data``  — not enough overlapping observations to
                                 compute a stable correlation (per
                                 ``corr_min_overlap_days``); composition
                                 must not proceed (fail-closed).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: _CorrLevel
    max_pairwise_corr: Optional[float]
    n_observations: int = Field(ge=0)
    lookback_requested: int = Field(ge=0)
    pairs: List[CorrelationPair] = Field(default_factory=list)
    reason: Optional[str] = None


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
