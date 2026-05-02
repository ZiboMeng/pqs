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
  - ``train_year_set(cfg)``: int set of years tagged ``train``.
  - ``validation_year_set(cfg)``: int set of validation years.
  - ``sealed_year_set(cfg)``: int set of sealed_test years.
  - ``restrict_frames_to_train(frames, cfg)``: filter price/volume
    frames to train_years rows only; preserves frame structure.
  - ``validate_no_holdout_leakage(frames, cfg)``: raise ValueError if
    any frame contains a row whose year is in validation or sealed
    (i.e. the panel must be train-only at this point in the pipeline).
  - ``compute_panel_max_date(frames)``: latest index date across all
    frames. Used for archive metadata + provenance audit.
  - ``ensure_role_assigned(role, cfg)``: fail-closed role check at
    mining startup (M6 C1+C2 + audit guard
    ``fail_closed_if_role_unspecified_at_mining_start``).
  - ``purge_labels_at_boundary(fwd_returns, cfg)``: M4 forward-return
    label boundary purging (drops cross-partition labels to NaN).
  - ``validate_factor_lookback(name, lookback, cfg)``: M3 factor
    warmup cap enforcement at registration time.
  - ``enforce_c5_no_role_remint(archive, spec, split_name, role)``:
    M6 C5 (codex R20 Q3) — same spec cannot remint under different
    role within same split.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "temporal_split.yaml"
_DEFAULT_PATH_V2 = Path(__file__).resolve().parent.parent.parent / "config" / "temporal_split_v2.yaml"

# Cutoff date for v2 dispatch. Candidates frozen on or after this date with
# role=diversifier read v2 thresholds (PRD §6.2 evidence-derived NAV-level
# correlation + 18%/20% maxdd tier + TD60 self-clearing). All other
# (role, freeze_date) combinations read v1 to preserve immutability of
# pre-PRD candidates (RCMv1 / Cand-2 legacy_decay_verification + cycle04+05
# archived trials). See `docs/memos/20260501-diversifier_role_decision.md`.
_V2_DISPATCH_CUTOFF = date(2026, 5, 1)


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
# Gate actions:
#   kill_candidate — hard fail, candidate cannot proceed (v1 + v2)
#   soft_warn      — candidate proceeds with a labelled warning that must
#                    be cleared by a forward observation condition (v2 only,
#                    introduced for diversifier 2025 maxdd 18-20% tier per
#                    PRD §6.2 + decision memo 20260501)
_GATE_ACTION = Literal["kill_candidate", "soft_warn"]


class GateRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: _GATE_OP
    value: float
    action: _GATE_ACTION
    # soft_warn-only fields. Required iff action == "soft_warn"; ignored
    # otherwise. Validated by _validate_soft_warn_fields below.
    soft_warn_label: Optional[str] = None
    soft_warn_clear_condition: Optional[str] = None
    soft_warn_unclear_action: Optional[str] = None

    @model_validator(mode="after")
    def _validate_soft_warn_fields(self) -> "GateRule":
        if self.action == "soft_warn":
            missing = [
                name
                for name, val in (
                    ("soft_warn_label", self.soft_warn_label),
                    ("soft_warn_clear_condition", self.soft_warn_clear_condition),
                    ("soft_warn_unclear_action", self.soft_warn_unclear_action),
                )
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"action=soft_warn requires fields {missing} on gate "
                    f"field={self.field!r} op={self.op} value={self.value}"
                )
        else:
            # kill_candidate: soft_warn fields must be unset (avoid drift).
            for name in ("soft_warn_label", "soft_warn_clear_condition",
                        "soft_warn_unclear_action"):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"action={self.action} must not set {name} "
                        f"(soft_warn-only field) on gate field={self.field!r}"
                    )
        return self


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

    For role-aware dispatch between v1 and v2 yaml, use
    ``resolve_split_path(role, freeze_date)`` to compute the path first,
    then pass it here. This keeps loader pure (loads what you give it)
    and centralises dispatch policy in one helper.
    """
    if path is None:
        path = _DEFAULT_PATH
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"temporal split config not found at {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return TemporalSplitConfig.model_validate(raw)


def resolve_split_path(
    role: str,
    freeze_date: Optional[date] = None,
    *,
    v1_path: Optional[Path] = None,
    v2_path: Optional[Path] = None,
) -> Path:
    """Dispatch between v1 and v2 temporal_split yaml.

    Rule (per PRD §6.2 + decision memo
    ``docs/memos/20260501-diversifier_role_decision.md``):

    - role == "diversifier" AND freeze_date is not None AND
      freeze_date >= 2026-05-01  → v2
    - everything else                                       → v1

    Why role + freeze_date and not just role:
      v2 yaml's diversifier thresholds are evidence-derived from cycle04+05
      partial_diversifier band (0.50-0.70 raw NAV correlation). cycle04+05
      archived trials and pre-2026-05-01 candidates predate that evidence;
      they remain bound to v1 for immutability (cycle04+05 yaml hashes
      already pinned to v1 contract).

    Why role-aware and not just date-aware:
      v2 modifies ONLY the diversifier role; core / legacy_decay_verification
      are unchanged. Routing a non-diversifier candidate to v2 would change
      nothing semantically but would pollute the audit trail (split_name
      stamped as `_v2` for a candidate whose role is not affected by v2
      changes). Conservative: only dispatch v2 when role is the affected one.

    Parameters
    ----------
    role : str
        Track A acceptance role string — one of ``"core"`` or ``"diversifier"``.
        If a Phase C-PRD-1 caller has a CandidateRole enum value
        (``"core_alpha"`` / ``"diversifier"`` / ``"legacy_decay_verification"``
        / ``"risk_control"``), translate via
        ``forward.manifest_schema.phase_c_role_to_track_a_role()`` first.
        ``"core_alpha"`` arriving here un-translated will silently route to
        v1 (no longer matches the diversifier branch) — wrong dispatch but
        not an exception, hence the explicit translation contract.
    freeze_date : Optional[date]
        Candidate freeze_date (== promoted_at date for forward candidates,
        or yaml.created_at for mining candidates). None defaults to v1
        (conservative: assume legacy contract).
    v1_path / v2_path : Optional[Path]
        Override the default yaml paths (test injection point).

    Returns
    -------
    Path to the appropriate yaml.

    Raises
    ------
    FileNotFoundError if the resolved path does not exist (catches the
    case where v2 yaml has been deleted but a diversifier candidate
    requests it).
    """
    v1 = Path(v1_path) if v1_path else _DEFAULT_PATH
    v2 = Path(v2_path) if v2_path else _DEFAULT_PATH_V2
    if (
        role == "diversifier"
        and freeze_date is not None
        and freeze_date >= _V2_DISPATCH_CUTOFF
    ):
        if not v2.exists():
            raise FileNotFoundError(
                f"v2 dispatch requested (role=diversifier, freeze_date="
                f"{freeze_date.isoformat()}) but v2 yaml not found at {v2}"
            )
        return v2
    if not v1.exists():
        raise FileNotFoundError(
            f"v1 dispatch requested (role={role!r}, freeze_date="
            f"{freeze_date.isoformat() if freeze_date else 'None'}) "
            f"but v1 yaml not found at {v1}"
        )
    return v1


def train_year_set(cfg: TemporalSplitConfig) -> set:
    """Return the set of integer years tagged as train in the split."""
    return set(_expand_year_entries(cfg.partition.train_years))


def validation_year_set(cfg: TemporalSplitConfig) -> set:
    """Return the set of integer years tagged as validation."""
    return {vy.year for vy in cfg.partition.validation_years}


def sealed_year_set(cfg: TemporalSplitConfig) -> set:
    """Return the set of integer years tagged as sealed_test."""
    return {sy.year for sy in cfg.partition.sealed_test_years}


def partition_for_role(
    frames,
    cfg: TemporalSplitConfig,
    role: str,
):
    """Filter price/volume frames to the partitions accessible by ``role``.

    Mining stage: role="miner". Reads ``cfg.access_rules.miner_may_access``
    (which for `alternating_regime_holdout_v1` = `["train"]`) → produces
    a train-only panel matching `restrict_frames_to_train` output.

    Evaluation stage: role="selector". Reads
    ``cfg.access_rules.selector_may_access`` (= `["train", "validation"]`)
    → produces a panel covering train+validation years. Sealed years
    are NEVER included unless `selector_may_access` explicitly contains
    "sealed_test", which the canonical yaml does NOT.

    Sealed evaluation: role="sealed_test_runner". Returns SEALED YEARS
    ONLY (single-shot evaluation). Mining + selector access rules do
    NOT include this; the role exists for completeness but the loader
    + sealed-eval ledger gate this so it can only run once per
    split_name.

    Why this exists (cycle #02 audit WARN #2 — 2026-04-30):
    `restrict_frames_to_train` is the right function for mining but
    the WRONG function for downstream evaluation: cycle eval needs to
    compute per-validation-year metrics, which requires the panel to
    actually CONTAIN validation-year rows. Pre-fix, the cycle #02
    eval script called restrict_frames_to_train and silently produced
    empty per-validation-year metrics. partition_for_role makes the
    role-aware access policy explicit at the API.

    Parameters
    ----------
    frames : Mapping[str, Optional[pd.DataFrame]]
        Dict of price/volume frames (close/open/high/low/volume).
        DatetimeIndex required.
    cfg : TemporalSplitConfig
    role : str
        One of {"miner", "selector", "sealed_test_runner"}.
        - "miner"               → train years only (mining)
        - "selector"            → train + validation years (evaluation)
        - "sealed_test_runner"  → sealed years only (single-shot final eval)

    Returns
    -------
    Same dict-of-frames structure with rows filtered to the role's
    accessible partitions. Sealed years are ALWAYS excluded for
    role={"miner", "selector"} regardless of yaml.

    Raises
    ------
    ValueError if role is unrecognized.
    """
    import pandas as pd

    if role == "miner":
        allowed = set(cfg.access_rules.miner_may_access)
    elif role == "selector":
        allowed = set(cfg.access_rules.selector_may_access)
    elif role == "sealed_test_runner":
        allowed = {"sealed_test"}
    else:
        raise ValueError(
            f"unknown role {role!r}; expected one of "
            f"{{miner, selector, sealed_test_runner}}"
        )

    train = train_year_set(cfg) if "train" in allowed else set()
    validation = validation_year_set(cfg) if "validation" in allowed else set()
    sealed = sealed_year_set(cfg) if "sealed_test" in allowed else set()
    all_years = train | validation | sealed

    out = {}
    for k, df in frames.items():
        if df is None:
            out[k] = None
            continue
        idx = df.index
        if not hasattr(idx, "year"):
            raise TypeError(
                f"frame {k!r} index lacks .year attribute; expected "
                f"DatetimeIndex, got {type(idx).__name__}"
            )
        mask = idx.year.isin(all_years)
        out[k] = df.loc[mask]
    return out


def restrict_frames_to_train(
    frames,
    cfg: TemporalSplitConfig,
):
    """Filter price/volume frames to rows whose year is in train_years.

    Preserves the dict-of-DataFrame structure used by mining scripts:
    ``{"close": close_df, "open": open_df, "high": high_df,
       "low": low_df, "volume": vol_df}``. Each value may be None
    (which the upstream sometimes uses for absent attributes); None
    values pass through unchanged.

    The DatetimeIndex is preserved; only rows outside train years are
    dropped. After this call, ``validate_no_holdout_leakage(frames,
    cfg)`` is guaranteed to pass (provided the original frames had
    only one row per (date, symbol) with a valid DatetimeIndex).
    """
    train = train_year_set(cfg)
    out = {}
    for k, df in frames.items():
        if df is None:
            out[k] = None
            continue
        idx = df.index
        if not hasattr(idx, "year"):
            raise TypeError(
                f"frame {k!r} index lacks .year attribute; expected "
                f"DatetimeIndex, got {type(idx).__name__}"
            )
        mask = idx.year.isin(train)
        out[k] = df.loc[mask]
    return out


def validate_no_holdout_leakage(
    frames,
    cfg: TemporalSplitConfig,
) -> None:
    """Raise ValueError if frames contain any validation or sealed year row.

    This enforces audit guards
    ``fail_closed_if_2026_row_in_train_panel`` and
    ``fail_closed_if_validation_year_in_train_panel``. Call this AFTER
    ``restrict_frames_to_train`` and BEFORE handing the panel to the
    miner. A leakage at this point indicates a bug in the upstream
    panel construction or a misconfigured split YAML.
    """
    holdout = validation_year_set(cfg) | sealed_year_set(cfg)
    for k, df in frames.items():
        if df is None or len(df) == 0:
            continue
        idx = df.index
        if not hasattr(idx, "year"):
            raise TypeError(
                f"frame {k!r} index lacks .year attribute; expected DatetimeIndex"
            )
        leaked_years = sorted(set(idx.year.unique()) & holdout)
        if leaked_years:
            sealed = sealed_year_set(cfg)
            validation = validation_year_set(cfg)
            sealed_leaked = [y for y in leaked_years if y in sealed]
            validation_leaked = [y for y in leaked_years if y in validation]
            msg_parts = [f"frame {k!r} contains holdout-year rows that must not be in the train panel"]
            if sealed_leaked:
                msg_parts.append(f"sealed years leaked: {sealed_leaked}")
            if validation_leaked:
                msg_parts.append(f"validation years leaked: {validation_leaked}")
            raise ValueError("; ".join(msg_parts))


def compute_panel_max_date(frames):
    """Return the latest pd.Timestamp across all non-empty frames.

    Used for ``audit.panel_max_date_recorded_per_run``. Returns None
    if all frames are empty or None.
    """
    import pandas as pd

    latest = None
    for df in frames.values():
        if df is None or len(df) == 0:
            continue
        idx = df.index
        if len(idx) == 0:
            continue
        cand = idx.max()
        if latest is None or cand > latest:
            latest = cand
    return latest


def ensure_role_assigned(role: Optional[str], cfg: TemporalSplitConfig) -> str:
    """Fail-closed role check at mining startup (M6 C1+C2).

    Per audit guard ``fail_closed_if_role_unspecified_at_mining_start``,
    a role MUST be declared before mining starts; the role MUST exist
    in the split's roles map. Returns the validated role name.
    """
    if not role:
        raise ValueError(
            "role must be specified at mining startup (M6 C1+C2 + audit "
            "guard fail_closed_if_role_unspecified_at_mining_start). Pass "
            "--role <name> matching one of the roles defined in "
            f"{cfg.split_name}: {sorted(cfg.roles.keys())}"
        )
    if role not in cfg.roles:
        raise ValueError(
            f"role {role!r} not declared in split {cfg.split_name!r}; "
            f"available: {sorted(cfg.roles.keys())}"
        )
    return role


def purge_labels_at_boundary(
    forward_returns,
    cfg: TemporalSplitConfig,
):
    """M4: drop forward-return labels whose window crosses a split boundary.

    Implements the financial-ML purging rule (Marcos Lopez de Prado).
    A forward-return label generated on day T with horizon H uses data
    from T to T+H. If [T, T+H] crosses any boundary between train /
    validation / sealed partitions, that row must be dropped from the
    affected partition's evaluation set.

    Concretely: if validation year 2019 evaluates a 21-day forward
    return computed on 2018-12-20, that label looks at 2018-12-20 →
    2019-01-15 — the window starts in train (2018 if 2018 were train)
    and ends in validation. The signal is a validation signal but the
    label uses train data (specifically the first ~10 trading days of
    the validation year are NOT yet "looking forward" only into
    validation). Drop them.

    Returns a DataFrame with the same index as input ``forward_returns``,
    with rows whose label window crosses any split boundary set to NaN.
    The caller filters NaNs in evaluation.

    Parameters
    ----------
    forward_returns : pd.DataFrame
        date × symbol forward return matrix. Index is DatetimeIndex.
    cfg : TemporalSplitConfig
        loaded split config. Uses purge_rules.label_horizon_days_max +
        purge_at_split_boundary + embargo_days.

    Returns
    -------
    DataFrame with cross-boundary rows set to NaN.
    """
    import pandas as pd

    pr = cfg.acceptance.purge_rules
    if not pr.purge_at_split_boundary:
        return forward_returns

    horizon = pr.label_horizon_days_max
    embargo = pr.embargo_days

    train = train_year_set(cfg)
    validation = validation_year_set(cfg)
    sealed = sealed_year_set(cfg)

    def _partition_of(year: int) -> str:
        if year in train:
            return "train"
        if year in validation:
            return "validation"
        if year in sealed:
            return "sealed"
        return "unknown"

    out = forward_returns.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        raise TypeError("forward_returns must have DatetimeIndex")

    bdays_per_calendar_day_approx = 1.45  # ~252/180 trading-to-calendar
    horizon_calendar_days = int(horizon * bdays_per_calendar_day_approx) + embargo

    for ts in out.index:
        signal_partition = _partition_of(ts.year)
        end_ts = ts + pd.Timedelta(days=horizon_calendar_days)
        end_partition = _partition_of(end_ts.year)
        if signal_partition != end_partition:
            out.loc[ts, :] = float("nan")
    return out


def validate_factor_lookback(
    factor_name: str,
    lookback_days: int,
    cfg: TemporalSplitConfig,
) -> None:
    """Enforce M3 factor warmup cap (codex R19 #5).

    Factor with lookback > ``access_rules.factor_warmup_max_lookback_days``
    is rejected at registration time. Track C mining wires this into
    factor_registry; Step A.5 ships the validator.
    """
    cap = cfg.access_rules.factor_warmup_max_lookback_days
    # Audit BUG #6 fix (2026-04-29 R1): negative lookback would mean the
    # factor looks into the future — the worst possible leak class. Reject
    # defensively even though factor_registry should never produce one.
    if lookback_days < 0:
        raise ValueError(
            f"factor {factor_name!r} declared lookback_days={lookback_days}; "
            f"negative lookback would imply a forward-looking signal (leak). "
            f"Lookback must be >= 0."
        )
    if lookback_days > cap:
        raise ValueError(
            f"factor {factor_name!r} declared lookback_days={lookback_days} "
            f"exceeds split.access_rules.factor_warmup_max_lookback_days={cap}. "
            f"Increase the cap in split YAML (and bump split_name) or reduce "
            f"factor lookback."
        )


def enforce_c5_no_role_remint(
    archive,
    spec_sha256: str,
    split_name: str,
    role: str,
) -> None:
    """Codex R20 Q3 (M6 C5): same spec cannot remint under different role.

    Queries the archive for prior trials matching ``spec_sha256`` within
    ``split_name``. If any match has a DIFFERENT role than ``role``, raise
    ValueError with a clear message naming the prior role + split.

    A trial reusing the same (spec, role, split) tuple is fine — that is
    just a deterministic re-run (rcm_archive's INSERT OR REPLACE handles
    it). The prohibited case is (spec=X, role=core) → (spec=X, role=diversifier)
    under the same split.

    ``archive`` must expose ``find_studies_by_spec_role(spec_sha256, split_name)
    -> List[dict]`` (RCMArchive does in Track A v1).
    """
    if archive is None or not hasattr(archive, "find_studies_by_spec_role"):
        return  # Pure-test paths without archive — skip
    prior = archive.find_studies_by_spec_role(spec_sha256, split_name)
    other_roles = sorted({p["role"] for p in prior
                          if p.get("role") and p["role"] != role})
    if other_roles:
        raise ValueError(
            f"M6 C5 violation: candidate spec {spec_sha256[:12]} already "
            f"mined under role(s) {other_roles} in split {split_name!r}; "
            f"cannot remint under role {role!r}. To explore role variation, "
            f"bump split_name (e.g. v1 → v2)."
        )


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
