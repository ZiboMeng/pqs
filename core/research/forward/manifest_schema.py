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

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.research.robustness.window_spec import (
    DataIntegritySnapshot,
    EvidenceClass,
)


class ForwardRunStatus(str, Enum):
    """Lifecycle status of a forward run.

    The MVP manifest only ships ``not_started``. Other values are
    enumerated for forward-compatibility so future automation can write
    them without re-versioning the schema.

    ``requires_data_review`` (added v2.1, PRD §4.4 escalation):
    revalidate detected a material data revision and the user must
    decide() before observe() can append again.
    """

    not_started = "not_started"
    in_progress = "in_progress"
    decision_pending = "decision_pending"
    completed_success = "completed_success"
    completed_fail = "completed_fail"
    aborted = "aborted"
    requires_data_review = "requires_data_review"


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


class PerScopeHashInputs(BaseModel):
    """Reproducibility + materiality evidence for one input-scope hash.

    Captured at TD observation time inside ``observe()``. NOT mutated
    afterwards — revalidate compares the stored snapshot against the
    current store. PRD v2.1 §4.3.

    Storage layout note: ``per_cell_digest`` and
    ``materiality_anchor_values`` use ISO-date string keys (e.g.
    ``"2026-04-27"``) because JSON object keys must be strings;
    pydantic round-trips them losslessly.
    """

    scope: Literal["signal_input", "execution_nav", "benchmark"]
    symbols: list[str] = Field(default_factory=list)
    bar_attributes: list[str] = Field(default_factory=list)
    window_start: date
    window_end: date
    bar_revision: str = Field(
        min_length=1,
        description=(
            "Canonical-source pin (e.g. trades_v2_late_report_dedup_2026-04-19 "
            "for polygon-canonical bars; yfinance_frontier for source-boundary "
            "frontier bars)."
        ),
    )
    per_cell_digest: dict = Field(
        default_factory=dict,
        description=(
            "{ sym: { iso_date: { attr: digest_short } } }. 8-char prefix of "
            "sha256(value-as-:.10g-string). Lets revalidate identify exactly "
            "which (sym, date, attr) cells were revised."
        ),
    )
    materiality_anchor_values: dict = Field(
        default_factory=dict,
        description=(
            "{ sym: { iso_date: { 'close': float, 'open': float } } } over the "
            "held-or-traded set on the last 10 trading days before-or-at "
            "as_of_date. Lets revalidate compute deterministic NAV-impact bps "
            "for revisions inside the ring."
        ),
    )


class BarHashInputs(BaseModel):
    """Top-level container holding all three per-scope evidence sets.

    Stored on each TD entry; ``signal_input`` / ``execution_nav`` /
    ``benchmark`` correspond 1:1 to ``signal_input_hash`` /
    ``execution_nav_hash`` / ``benchmark_hash`` on the same entry.
    """

    signal_input:  PerScopeHashInputs
    execution_nav: PerScopeHashInputs
    benchmark:     PerScopeHashInputs


class SourceLayerView(BaseModel):
    """One source-layer count view: bucket counts of how many symbols
    fall in each layer.

    The validator is permissive: it does not enforce any cross-bucket
    sum constraint here because the relevant universe size differs by
    view (as_of_held vs window_input) and is enforced by the caller.
    """

    canonical_only_n_symbols: int = Field(default=0, ge=0)
    frontier_only_n_symbols:  int = Field(default=0, ge=0)
    mixed_n_symbols:          int = Field(default=0, ge=0)


class SourceLayerBreakdown(BaseModel):
    """Per-TD source-layer attribution at two granularities.

    PRD v2.1 §G3 + §4.5: the legacy aggregate ``source_mix`` boolean
    captured today's held layer only and missed window-spanning cases.
    v2.1 records both:
      - ``as_of_held_source``    — held-symbol layer at as_of_date
      - ``window_input_source``  — every (sym, date, attr) cell folded
                                   into the three input-scope hashes
    """

    as_of_held_source:   SourceLayerView
    window_input_source: SourceLayerView


class DataRevisionEvent(BaseModel):
    """Set on a TD entry when revalidate detects a divergence between
    the entry's stored input-scope hashes and the current store.

    PRD v2.1 §4.1 + §4.4 + §4.6.

    Materiality fields are populated when the revision falls within
    the 10-day anchor ring; for out-of-ring revisions or revisions on
    attributes not anchored (high/low/volume on held names; any
    attribute on non-held universe names), ``estimated_*_bps`` are
    None and ``materiality_estimate_class="bound_only"`` is recorded
    in ``delta_summary``. Per §4.4 fail-closed rule, bound_only
    revisions escalate to ``policy_decision="invalidated"``.
    """

    detected_at_utc: datetime
    revised_symbols: list[str] = Field(default_factory=list)
    detected_by_run_label: str = Field(
        min_length=1,
        description="Subsequent observe() call that surfaced this divergence",
    )
    delta_summary: str = Field(default="", description="Human-readable per-symbol summary")
    estimated_nav_impact_bps:    Optional[float] = None
    estimated_cum_ret_drift_bps: Optional[float] = None
    estimated_vs_spy_drift_bps:  Optional[float] = None
    estimated_vs_qqq_drift_bps:  Optional[float] = None
    decision_sign_flip: bool = False
    raw_max_close_drift_pct: Optional[float] = None
    affected_scopes: list[Literal["signal_input", "execution_nav", "benchmark"]] = Field(
        default_factory=list,
    )
    policy_decision: Literal["flagged_only", "invalidated"]


class ConfigSnapshot(BaseModel):
    """Config-side hashes pinned at forward init time (PRD F v1.1 §5.1).

    Distinct from :class:`CostAssumptions` (cost yaml) and
    :class:`DataIntegritySnapshot` (data tier commit) because those
    existed pre-PRD-F. This new model captures the 5 config sources
    whose silent edits would otherwise misclassify as data revisions.

    Append-only: once an entry is on a manifest it does not mutate.
    Pre-PRD-F manifests have ``config_snapshot=None`` and are treated as
    legacy at revalidate time (skip drift check, log INFO once per
    run). Backfill is opt-in via
    ``dev/scripts/forward/backfill_config_snapshot.py``.

    Severity policy when a hash drifts after init (PRD F §5.3 + codex
    round-14 §"F PRD modifications"):

    - ``universe_hash`` / ``factor_registry_hash`` / ``risk_config_hash``
      → halt (flips manifest status to ``requires_data_review``)
    - ``research_mask_hash`` / ``system_config_hash`` → warn (record-only)

    ``extra='forbid'`` (audit round 2 finding): hash field set is
    enumerated. Adding a new hash source MUST go through a versioned
    PRD round (schema change + severity-policy decision + tests); a
    typo in the backfill utility ("factory_registry_hash" misspell)
    or yaml hand-edit must fail loudly rather than silently appear as
    an unparsed extra. Mirrors the codex round-13 strict-schema
    pattern adopted on ``core/config/schemas/acceptance.py``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", min_length=1)
    universe_hash: str = Field(min_length=12)
    factor_registry_hash: str = Field(min_length=12)
    research_mask_hash: str = Field(min_length=12)
    risk_config_hash: str = Field(min_length=12)
    system_config_hash: str = Field(min_length=12)
    snapshot_at_utc: datetime
    sources: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of hash field name → source path. Recorded for "
            "human-readable audit, e.g. "
            "{'universe_hash': 'config/universe.yaml', "
            "'factor_registry_hash': "
            "'core/factors/factor_registry.py::PRODUCTION+RESEARCH+MAP'}."
        ),
    )
    migration_note: Optional[str] = Field(
        default=None,
        description=(
            "Set by the opt-in backfill utility to indicate the snapshot was "
            "stamped post-init (assumed unchanged since init). None on "
            "snapshots populated at init time."
        ),
    )


class ConfigDriftEvent(BaseModel):
    """Emitted when revalidate detects config-side drift between the
    snapshot at init and the current source (PRD F v1.1 §5.2).

    Distinct from :class:`DataRevisionEvent` (which fires on bar-side
    drift) — codex round-11 §B3 mandate: "data revision 和 config
    drift 如何分账". The two event classes have different severity
    semantics (E1-E5 NAV materiality vs source-class halt/warn),
    different remediation paths, and must NOT be collapsed.

    A single TD entry can carry both a ``data_revision_event`` and a
    ``config_drift_event`` if both kinds of drift surface in the same
    observe call.

    ``extra='forbid'`` (audit round 2 finding): same rationale as
    :class:`ConfigSnapshot` — drift event field set is enumerated;
    schema-level diversion of new fields requires an explicit PRD round.
    """

    model_config = ConfigDict(extra="forbid")

    detected_at_utc: datetime
    detected_by_run_label: str = Field(
        min_length=1,
        description="Subsequent observe() / revalidate() call that surfaced this drift",
    )
    affected_run_id: Optional[str] = Field(
        default=None,
        description="checkpoint_label of the TD entry whose recompute saw this drift",
    )
    drifted_sources: list[str] = Field(
        min_length=1,
        description=(
            "Subset of {'universe_hash', 'factor_registry_hash', "
            "'research_mask_hash', 'risk_config_hash', 'system_config_hash'}."
        ),
    )
    snapshot_hashes: dict[str, str] = Field(
        description="Hash values stored in manifest.config_snapshot at init time",
    )
    current_hashes: dict[str, str] = Field(
        description="Hash values recomputed at revalidate time",
    )
    severity: Literal["warn", "halt"]


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

    ── v2.1 evidence-hardening fields (PRD `forward_evidence_hardening_prd.md`) ──

    All v2.1 fields default ``None`` so existing TD001 entries on
    RCMv1 / Cand-2 continue to load without rewriting their numerics.
    The first v2 ``observe()`` call sets ``legacy_unhashed_inputs=True``
    on those grandfathered rows (metadata-only mutation; numerics
    untouched).
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

    # ── v2.1 additive fields ────────────────────────────────────────
    legacy_unhashed_inputs: Optional[bool] = Field(
        default=None,
        description=(
            "True for entries written before the v2.1 input-scope schema "
            "shipped (e.g., TD001 baseline rows). Out of revision-guard "
            "scope. None on v2.1+ entries."
        ),
    )
    signal_input_hash: Optional[str] = Field(default=None, min_length=12)
    execution_nav_hash: Optional[str] = Field(default=None, min_length=12)
    benchmark_hash: Optional[str] = Field(default=None, min_length=12)
    bar_hash: Optional[str] = Field(
        default=None, min_length=12,
        description=(
            "Roll-up = sha256(signal_input_hash || execution_nav_hash || "
            "benchmark_hash)[:24]. Cheap top-level diff."
        ),
    )
    bar_hash_inputs: Optional[BarHashInputs] = None
    source_layer_breakdown: Optional[SourceLayerBreakdown] = None
    data_revision_event: Optional[DataRevisionEvent] = None
    # held_today_weights: portfolio weights at as_of_date, captured at
    # observation time. Required for revalidate's NAV-impact bps calc
    # under §4.4 E1-E2: NAV_impact_bps ≈ Σ weight[sym] × close_drift_pct.
    # None on legacy TD001 entries (no weights captured pre-v2.1) →
    # revalidate fails-closed for any revision against those rows.
    held_today_weights: Optional[dict] = None

    # ── PRD F additive: config-drift event (separate class from
    # data_revision_event; never collapse — codex round-11 §B3) ────
    config_drift_event: Optional[ConfigDriftEvent] = None


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
    # PRD F additive: pinned config-side hashes at init. Optional so
    # legacy v2.1.3 manifests (TD001-TD003 era, pre-PRD-F) keep loading.
    # Lazy migration: revalidate skips drift check when None and logs
    # INFO once per run id. Backfill utility:
    # ``dev/scripts/forward/backfill_config_snapshot.py``.
    config_snapshot: Optional[ConfigSnapshot] = None
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
