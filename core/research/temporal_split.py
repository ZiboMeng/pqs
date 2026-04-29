"""Temporal split configuration loader and validator.

Loads ``config/temporal_split.yaml`` and returns a frozen pydantic v2
model. Used by mining panel constructor, acceptance pack, sealed-eval
ledger, and archive metadata to enforce alternating-year regime-
stratified split with role-locked gates.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Roadmap: docs/memos/20260429-post_audit_strategic_roadmap.md (v3)

Hard schema invariants enforced by this module:
  - ``train_years`` and ``validation_years`` MUST be disjoint sets.
  - ``sealed_test_years`` MUST be disjoint from both train and
    validation.
  - Each ``stress_slices[].source_year`` MUST be a year in ``train_years``,
    and the slice date range MUST fall within that year.
  - ``factor_warmup_max_lookback_days`` MUST be in [1, 1000].
  - All ``validation_years[]`` MUST have ``manual_regime_tag`` set;
    ``auto_classifier_tag`` is None at PRD draft time but becomes
    non-None after Step A.8 regime_detector integration.
  - ``roles`` MUST contain at least ``core``; each role's
    ``validation_gates`` MUST reference fields that exist in the
    declared validation_years (e.g. "validation.2025.excess_vs_qqq"
    requires year 2025 to be in validation_years).
  - ``acceptance.fork_criteria.rules`` MUST contain at least an F1
    trigger, F2 trigger, and an escalate fallback.

Public API:
  - ``load_temporal_split(path)``: parse and validate; returns
    ``TemporalSplitConfig``.
  - ``compute_split_sha256(path)``: deterministic content hash for
    archive fingerprinting (canonicalized: dict keys sorted, list
    order preserved per F PRD convention).
  - ``expand_year_ranges(years)``: utility to flatten a mixed list of
    ``{range: [start, end]}`` and ``{year: N}`` entries into a sorted
    list of integers.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "temporal_split.yaml"


# ---------------------------------------------------------------------------
# Partition models
# ---------------------------------------------------------------------------


class _YearRange(BaseModel):
    """Inclusive integer year range, e.g. ``{range: [2009, 2017]}``."""

    model_config = ConfigDict(extra="forbid")
    range: List[int] = Field(min_length=2, max_length=2)

    @field_validator("range")
    @classmethod
    def _range_ordered(cls, v: List[int]) -> List[int]:
        if v[0] > v[1]:
            raise ValueError(f"range[0]={v[0]} must be <= range[1]={v[1]}")
        if v[0] < 1900 or v[1] > 2100:
            raise ValueError(f"range {v} out of plausible bounds [1900, 2100]")
        return v


class _SingleYear(BaseModel):
    """Single integer year, e.g. ``{year: 2020}``."""

    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=1900, le=2100)


class ReferenceYearRange(BaseModel):
    """Year range available for stress reference but excluded from alpha."""

    model_config = ConfigDict(extra="forbid")
    range: List[int] = Field(min_length=2, max_length=2)
    purpose: str
    excluded_from_alpha: bool = True


class ValidationYear(BaseModel):
    """A validation year with manual + auto regime tags and weight."""

    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=1900, le=2100)
    manual_regime_tag: str
    auto_classifier_tag: Optional[str] = None
    weight: float = Field(default=1.0, gt=0.0)


class StressSlice(BaseModel):
    """A date range borrowed from a train year for MaxDD sanity check only."""

    model_config = ConfigDict(extra="forbid")
    name: str
    start: date
    end: date
    source_year: int = Field(ge=1900, le=2100)
    mode: Literal["stress_check_only"]
    maxdd_threshold: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _start_before_end(self) -> "StressSlice":
        if self.start >= self.end:
            raise ValueError(f"slice {self.name}: start {self.start} must be < end {self.end}")
        if self.start.year != self.source_year or self.end.year != self.source_year:
            raise ValueError(
                f"slice {self.name}: start={self.start} end={self.end} "
                f"must both fall in source_year={self.source_year}"
            )
        return self


class SealedTestYear(BaseModel):
    """The sealed final-test year, single-shot evaluation."""

    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=1900, le=2100)
    mode: Literal["single_shot_evaluation"]


class Partition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_years: List[ReferenceYearRange] = Field(default_factory=list)
    train_years: List[Union[_YearRange, _SingleYear]] = Field(min_length=1)
    validation_years: List[ValidationYear] = Field(min_length=1)
    stress_slices: List[StressSlice] = Field(default_factory=list)
    sealed_test_years: List[SealedTestYear] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Access rules
# ---------------------------------------------------------------------------


_PARTITION_LITERAL = Literal["train", "validation", "sealed_test"]


class AccessRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    miner_may_access: List[_PARTITION_LITERAL] = Field(min_length=1)
    selector_may_access: List[_PARTITION_LITERAL] = Field(min_length=1)
    factor_warmup_may_cross_boundary: bool
    factor_warmup_max_lookback_days: int = Field(ge=1, le=1000)
    validation_signal_dates_must_be_in: List[_PARTITION_LITERAL] = Field(min_length=1)
    sealed_test_access: Literal["final_only_single_shot"]


# ---------------------------------------------------------------------------
# Roles + gates
# ---------------------------------------------------------------------------


_GATE_OP = Literal[">", ">=", "<", "<=", "=="]
_GATE_ACTION = Literal["kill_candidate"]


class GateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: _GATE_OP
    value: float
    action: _GATE_ACTION


class EligibilityConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: _GATE_OP
    value: float


class Role(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    eligibility_constraint: List[EligibilityConstraint] = Field(default_factory=list)
    validation_gates: List[GateRule] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Acceptance criteria (M4 / M7 / M8 + standard gates)
# ---------------------------------------------------------------------------


class ValidationYearPass(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excess_vs_spy_positive_min: int = Field(ge=0)
    excess_vs_qqq_positive_min: int = Field(ge=0)
    maxdd_per_year_max: float = Field(gt=0.0, le=1.0)


class StressSlicePass(BaseModel):
    model_config = ConfigDict(extra="forbid")
    maxdd_per_slice_max: float = Field(gt=0.0, le=1.0)


class CostRobustness(BaseModel):
    model_config = ConfigDict(extra="forbid")
    multiplier_2x_must_remain_positive: bool


class Concentration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top1_max: float = Field(gt=0.0, le=1.0)
    top3_max: float = Field(gt=0.0, le=1.0)
    no_leveraged_etf_dependency: bool


class Beta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beta_to_qqq_max: float = Field(gt=0.0)


class PurgeRules(BaseModel):
    """M4: purged label / forward-return boundary."""

    model_config = ConfigDict(extra="forbid")
    label_horizon_days_max: int = Field(ge=1, le=252)
    purge_at_split_boundary: bool
    embargo_days: int = Field(ge=0, le=30)


class DividendSafety(BaseModel):
    """M8: dividend pass margin (Track D enforces; Track A schema-only)."""

    model_config = ConfigDict(extra="forbid")
    enforce_at: Literal["track_d_promotion"]
    required_excess_margin_5yr: float = Field(gt=0.0, lt=1.0)
    fallback: str
    rationale: Optional[str] = None


class ForkCriteria(BaseModel):
    """M7: F1/F2 fork criteria — locked pre-smoke.

    Schema is intentionally permissive on the ``rules`` payload (dict
    of arbitrary metric refs). The runtime evaluator must enforce that
    at least one F1, one F2, and one escalate-fallback rule are present.
    """

    model_config = ConfigDict(extra="forbid")
    smoke_trial_count: int = Field(ge=1)
    smoke_universe: str
    smoke_split_yaml: str
    smoke_run_command: str
    rules: List[Dict] = Field(min_length=3)

    @model_validator(mode="after")
    def _has_required_branches(self) -> "ForkCriteria":
        conditions = {r.get("condition") for r in self.rules}
        required = {"F1_trigger", "F2_trigger", "escalate"}
        missing = required - conditions
        if missing:
            raise ValueError(
                f"fork_criteria.rules missing required conditions: {sorted(missing)}"
            )
        return self


class Acceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_year_pass: ValidationYearPass
    stress_slice_pass: StressSlicePass
    cost_robustness: CostRobustness
    concentration: Concentration
    beta: Beta
    purge_rules: PurgeRules
    dividend_safety: DividendSafety
    fork_criteria: ForkCriteria


# ---------------------------------------------------------------------------
# Audit (sealed-eval ledger + fail-closed guards)
# ---------------------------------------------------------------------------


class SealedLedgerFailClosedOnRepeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: List[str] = Field(min_length=1)
    action: Literal["abort_with_message"]


class SealedLedgerFailClosedOnSplitFailure(BaseModel):
    """Codex R20 B1: split-level core sealed lock."""

    model_config = ConfigDict(extra="forbid")
    role: str
    key: List[str] = Field(min_length=1)
    action: Literal["abort_with_message"]
    message: str


class SealedEvalLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    path: str
    fields: List[str] = Field(min_length=1)
    fail_closed_on_repeat: SealedLedgerFailClosedOnRepeat
    fail_closed_on_split_failure: SealedLedgerFailClosedOnSplitFailure


class Audit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config_sha256_recorded_in_archive: bool
    panel_max_date_recorded_per_run: bool
    fail_closed_if_2026_row_in_train_panel: bool
    fail_closed_if_validation_year_in_train_panel: bool
    fail_closed_if_role_unspecified_at_mining_start: bool
    fail_closed_if_regime_tag_missing_either_source: bool
    fail_closed_if_label_crosses_split_boundary: bool
    fail_closed_if_factor_lookback_exceeds_cap: bool
    record_actual_max_lookback_per_candidate: bool
    sealed_eval_ledger: SealedEvalLedger


# ---------------------------------------------------------------------------
# Top-level config + cross-section invariants
# ---------------------------------------------------------------------------


class TemporalSplitConfig(BaseModel):
    """Parsed and validated temporal_split.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    split_name: str
    created_at: date
    locked_after_first_use: bool
    partition: Partition
    access_rules: AccessRules
    roles: Dict[str, Role]
    acceptance: Acceptance
    audit: Audit

    @model_validator(mode="after")
    def _validate_cross_section(self) -> "TemporalSplitConfig":
        train_set = set(_expand_year_entries(self.partition.train_years))
        validation_set = {vy.year for vy in self.partition.validation_years}
        sealed_set = {sy.year for sy in self.partition.sealed_test_years}

        # Disjoint partition: train / validation / sealed cannot overlap.
        train_val_overlap = train_set & validation_set
        if train_val_overlap:
            raise ValueError(
                f"train_years and validation_years overlap on: {sorted(train_val_overlap)}"
            )
        train_sealed_overlap = train_set & sealed_set
        if train_sealed_overlap:
            raise ValueError(
                f"train_years and sealed_test_years overlap on: {sorted(train_sealed_overlap)}"
            )
        val_sealed_overlap = validation_set & sealed_set
        if val_sealed_overlap:
            raise ValueError(
                f"validation_years and sealed_test_years overlap on: {sorted(val_sealed_overlap)}"
            )

        # Stress slices must source from train years.
        for slc in self.partition.stress_slices:
            if slc.source_year not in train_set:
                raise ValueError(
                    f"stress_slice {slc.name}.source_year={slc.source_year} "
                    f"is not in train_years; stress slices must borrow from train"
                )

        # roles must contain at least 'core'.
        if "core" not in self.roles:
            raise ValueError("roles must contain at least 'core'")

        # Each role's validation_gates must reference declared validation
        # years. Field format: "validation.<YEAR>.<METRIC>".
        for role_name, role in self.roles.items():
            for gate in role.validation_gates:
                parts = gate.field.split(".")
                if len(parts) >= 3 and parts[0] == "validation":
                    try:
                        gate_year = int(parts[1])
                    except ValueError:
                        continue
                    if gate_year not in validation_set:
                        raise ValueError(
                            f"role={role_name} gate field {gate.field!r} references "
                            f"year {gate_year} which is not in validation_years "
                            f"{sorted(validation_set)}"
                        )

        return self


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _expand_year_entries(entries: List[Union[_YearRange, _SingleYear]]) -> List[int]:
    """Flatten a list of YearRange and SingleYear entries to sorted ints."""
    out: List[int] = []
    for entry in entries:
        if isinstance(entry, _YearRange):
            out.extend(range(entry.range[0], entry.range[1] + 1))
        elif isinstance(entry, _SingleYear):
            out.append(entry.year)
        else:
            raise TypeError(f"unexpected year entry type: {type(entry).__name__}")
    return sorted(out)


def expand_year_ranges(entries: List[dict]) -> List[int]:
    """Public utility: flatten a list of dict-form year entries.

    Accepts either ``{range: [start, end]}`` or ``{year: N}`` entries
    (matching the YAML form). Returns a sorted list of integer years.
    """
    parsed: List[Union[_YearRange, _SingleYear]] = []
    for e in entries:
        if "range" in e:
            parsed.append(_YearRange(**e))
        elif "year" in e:
            parsed.append(_SingleYear(**e))
        else:
            raise ValueError(f"year entry must have 'range' or 'year' key: {e}")
    return _expand_year_entries(parsed)


def load_temporal_split(path: Optional[Path] = None) -> TemporalSplitConfig:
    """Load and validate ``config/temporal_split.yaml``.

    Raises ``FileNotFoundError`` if the path does not exist, and
    ``pydantic.ValidationError`` for any schema violation.
    """
    if path is None:
        path = _DEFAULT_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"temporal split config not found at {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return TemporalSplitConfig.model_validate(raw)


def compute_split_sha256(path: Optional[Path] = None) -> str:
    """Deterministic content hash of temporal_split.yaml.

    Canonicalization: dict keys sorted recursively; list order preserved
    (same convention as F PRD's _canonical_yaml_sha — list ORDER may
    encode meaningful semantics, e.g. fork_criteria.rules ordering).
    Returns full hex SHA-256.
    """
    if path is None:
        path = _DEFAULT_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"temporal split config not found at {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    def _canon(obj):
        if isinstance(obj, dict):
            return {k: _canon(obj[k]) for k in sorted(obj.keys())}
        if isinstance(obj, list):
            return [_canon(x) for x in obj]
        return obj

    canonical = _canon(raw)
    canonical_bytes = yaml.safe_dump(canonical, sort_keys=False).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()
