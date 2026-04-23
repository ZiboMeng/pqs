"""FrozenStrategySpec dataclass (Phase E-1 R4).

Structured representation of a research candidate's frozen strategy
spec. Used by:
  - scripts/freeze_research_candidate.py (R5) to WRITE
  - scripts/research_promote.py (R6) to VALIDATE before S0->S1
  - scripts/run_paper_candidate.py (R8) to READ inputs to paper layer
  - scripts/paper_drift_report.py (R10) for attribution

Contract (8 mandatory fields — auditor minimum per PRD 2 §6.1):

    candidate_id               : str    e.g. "rcm_v1_defensive_composite_01"
    strategy_version           : str    e.g. "rcm-v1-2026-04-24"
    source_trial_id            : str    link back to rcm_archive
    feature_set                : list   >=1 FeatureEntry(name, weight, ...)
    benchmark_relative_summary : dict|str  SPY/QQQ excess or memo text
    oos_holdout_summary        : dict|str  IC_IR + walk-forward or memo
    robustness_summary         : dict|str  sensitivity + cost or memo
    decision_memo              : str    markdown path OR inline text

Optional fields (match RCMv1 memo §2 verbatim — extend as needed):
    strategy_type, family, transforms, composite_rule, labels,
    panel_contract, rebalance, weighting_rule, benchmark_definition,
    risk_overlay, cost_model_version, alternative_weighting_variant,
    source, research_evidence

Flexibility: summary fields accept either structured dict (preferred,
machine-checkable) or markdown string (memo-style, auditor-readable).
When structured, `decision_memo` can be a path pointing at a more
detailed markdown file. When inline, the whole spec self-contains.

YAML round-trip: `from_yaml()` tolerates the RCMv1-style nested
layout (e.g. `source.trial_id` used to populate `source_trial_id`).
`to_yaml()` emits flat-canonical form where required, keeping nested
blocks for optional sections that are naturally dict-shaped.

Reference PRDs:
    docs/20260424-prd_phase_e_execution.md §2 E1-R4
    docs/20260424-prd_research_to_paper_promote_standard.md §6
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml

from core.logging_setup import get_logger

logger = get_logger(__name__)


# strategy_version pattern: name-vN[-suffix]  (lenient; doesn't enforce
# date or specific separator form — just rejects empty / single-char).
_STRATEGY_VERSION_PATTERN = re.compile(r"^[a-zA-Z][\w\-.]{1,}$")


class FrozenSpecError(ValueError):
    """Raised when spec validation fails."""


@dataclass
class FeatureEntry:
    """One feature in a composite spec's feature_set."""

    name: str
    weight: Optional[float] = None
    family: Optional[str] = None
    source: Optional[str] = None
    # Optional extras passthrough
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.family is not None:
            d["family"] = self.family
        if self.weight is not None:
            d["weight"] = self.weight
        if self.source is not None:
            d["source"] = self.source
        for k, v in self.extras.items():
            d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeatureEntry":
        known = {"name", "weight", "family", "source"}
        if "name" not in d:
            raise FrozenSpecError(
                f"FeatureEntry missing 'name' field: {d}"
            )
        extras = {k: v for k, v in d.items() if k not in known}
        return cls(
            name=str(d["name"]),
            weight=float(d["weight"]) if d.get("weight") is not None else None,
            family=d.get("family"),
            source=d.get("source"),
            extras=extras,
        )


@dataclass
class FrozenStrategySpec:
    """Frozen research candidate strategy spec (8 mandatory fields)."""

    # ── 8 mandatory ────────────────────────────────────────────────────
    candidate_id: str
    strategy_version: str
    source_trial_id: str
    feature_set: list[FeatureEntry]
    benchmark_relative_summary: Union[dict, str]
    oos_holdout_summary: Union[dict, str]
    robustness_summary: Union[dict, str]
    decision_memo: str  # path (preferred) OR inline markdown text

    # ── Optional structural ────────────────────────────────────────────
    strategy_type: Optional[str] = None
    family: Optional[str] = None
    transforms: Optional[dict] = None
    composite_rule: Optional[dict] = None
    labels: Optional[dict] = None
    panel_contract: Optional[dict] = None
    rebalance: Optional[dict] = None
    weighting_rule: Optional[Any] = None   # str "TBD" or dict
    benchmark_definition: Optional[dict] = None
    risk_overlay: Optional[dict] = None
    cost_model_version: Optional[str] = None
    alternative_weighting_variant: Optional[dict] = None

    # ── Optional provenance ────────────────────────────────────────────
    source: Optional[dict] = None          # rcm_archive back-reference
    research_evidence: Optional[dict] = None
    notes: Optional[str] = None

    # ── Extras (catch-all for future fields) ──────────────────────────
    extras: dict = field(default_factory=dict)

    # ── Validation ─────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        # candidate_id
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise FrozenSpecError("candidate_id required (non-empty string)")

        # strategy_version
        if not isinstance(self.strategy_version, str):
            raise FrozenSpecError("strategy_version must be a string")
        if not _STRATEGY_VERSION_PATTERN.match(self.strategy_version):
            raise FrozenSpecError(
                f"strategy_version {self.strategy_version!r} invalid; "
                "must match ^[a-zA-Z][\\w\\-.]{1,}$ (e.g. 'rcm-v1-2026-04-24')"
            )

        # source_trial_id
        if not isinstance(self.source_trial_id, str) or not self.source_trial_id.strip():
            raise FrozenSpecError(
                "source_trial_id required (non-empty string back-pointer to rcm_archive)"
            )

        # feature_set
        if not isinstance(self.feature_set, list) or len(self.feature_set) == 0:
            raise FrozenSpecError("feature_set must be non-empty list")
        for i, f in enumerate(self.feature_set):
            if not isinstance(f, FeatureEntry):
                raise FrozenSpecError(
                    f"feature_set[{i}] must be FeatureEntry, got {type(f).__name__}"
                )

        # Summaries must be non-empty
        for name in ("benchmark_relative_summary", "oos_holdout_summary",
                     "robustness_summary"):
            v = getattr(self, name)
            if v is None or (isinstance(v, (str, list, dict)) and len(v) == 0):
                raise FrozenSpecError(
                    f"{name} required (dict or non-empty string)"
                )

        # decision_memo: non-empty string
        if not isinstance(self.decision_memo, str) or not self.decision_memo.strip():
            raise FrozenSpecError(
                "decision_memo required (path to markdown file or inline text)"
            )

    # ── YAML round-trip ────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Canonical dict form. Suitable for yaml.safe_dump."""
        d: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "strategy_version": self.strategy_version,
            "source_trial_id": self.source_trial_id,
            "feature_set": [f.to_dict() for f in self.feature_set],
            "benchmark_relative_summary": self.benchmark_relative_summary,
            "oos_holdout_summary": self.oos_holdout_summary,
            "robustness_summary": self.robustness_summary,
            "decision_memo": self.decision_memo,
        }
        # Optional fields — include only if set
        for field_name in (
            "strategy_type", "family", "transforms", "composite_rule",
            "labels", "panel_contract", "rebalance", "weighting_rule",
            "benchmark_definition", "risk_overlay", "cost_model_version",
            "alternative_weighting_variant", "source", "research_evidence",
            "notes",
        ):
            v = getattr(self, field_name)
            if v is not None:
                d[field_name] = v
        # Extras
        for k, v in self.extras.items():
            if k not in d:
                d[k] = v
        return d

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        return yaml.safe_dump(self.to_dict(), sort_keys=False,
                              default_flow_style=False, allow_unicode=True)

    def to_yaml_file(self, path: str | Path) -> Path:
        """Write YAML to disk; returns the path written."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_yaml())
        return p

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FrozenStrategySpec":
        """Construct from a dict. Tolerant of nested source.trial_id layout.

        Required 8 fields must be resolvable; optional fields come through.
        Unknown top-level keys land in `extras`.
        """
        if not isinstance(d, dict):
            raise FrozenSpecError(f"from_dict: expected dict, got {type(d).__name__}")

        # Resolve source_trial_id: top-level OR source.trial_id
        source_trial_id = d.get("source_trial_id")
        if not source_trial_id and isinstance(d.get("source"), dict):
            source_trial_id = d["source"].get("trial_id")

        # Resolve summaries with fallback into research_evidence for
        # RCMv1-style YAML (which puts them under research_evidence.full_period
        # etc.)
        evidence = d.get("research_evidence") or {}
        brs = d.get("benchmark_relative_summary")
        if brs is None and isinstance(evidence, dict):
            # Fall back: RCMv1 has no explicit benchmark_relative_summary;
            # use a derived dict pointing at research_evidence
            if "full_period" in evidence:
                brs = {
                    "note": "derived from research_evidence (RCMv1 pre-schema)",
                    "ic_ir_full_period": evidence["full_period"].get("ic_ir"),
                    "positive_rate": evidence["full_period"].get("positive_rate"),
                }
        oos = d.get("oos_holdout_summary")
        if oos is None and isinstance(evidence, dict):
            if "walk_forward_n_folds" in evidence:
                oos = {
                    "note": "derived from research_evidence (RCMv1 pre-schema)",
                    "n_folds": evidence.get("walk_forward_n_folds"),
                    "folds_positive": evidence.get("walk_forward_folds_positive"),
                }
        rob = d.get("robustness_summary")
        if rob is None and isinstance(evidence, dict):
            if "weight_sensitivity_ir_range" in evidence:
                rob = {
                    "note": "derived from research_evidence (RCMv1 pre-schema)",
                    "sensitivity_ir_range": evidence.get("weight_sensitivity_ir_range"),
                    "sensitivity_ir_std": evidence.get("weight_sensitivity_ir_std"),
                    "random_baseline_best_ir": evidence.get("random_baseline_best_ir"),
                }

        # Resolve decision_memo: either top-level string, or
        # source.decision_memo, or inline note
        decision_memo = d.get("decision_memo")
        if decision_memo is None:
            # RCMv1 frozen YAML doesn't have decision_memo inside the YAML;
            # the memo is a separate .md file referenced from registry.
            # Accept empty-but-noted for migration case.
            decision_memo = d.get("notes", "")

        feature_raw = d.get("feature_set", [])
        if not isinstance(feature_raw, list):
            raise FrozenSpecError(
                f"feature_set must be list, got {type(feature_raw).__name__}"
            )
        feature_set = [FeatureEntry.from_dict(f) for f in feature_raw]

        # Unknown top-level keys → extras
        known = {
            "candidate_id", "strategy_version", "source_trial_id",
            "feature_set", "benchmark_relative_summary",
            "oos_holdout_summary", "robustness_summary", "decision_memo",
            "strategy_type", "family", "transforms", "composite_rule",
            "labels", "panel_contract", "rebalance", "weighting_rule",
            "benchmark_definition", "risk_overlay", "cost_model_version",
            "alternative_weighting_variant", "source", "research_evidence",
            "notes",
        }
        extras = {k: v for k, v in d.items() if k not in known}

        return cls(
            candidate_id=d.get("candidate_id", ""),
            strategy_version=d.get("strategy_version", ""),
            source_trial_id=source_trial_id or "",
            feature_set=feature_set,
            benchmark_relative_summary=brs or "",
            oos_holdout_summary=oos or "",
            robustness_summary=rob or "",
            decision_memo=decision_memo,
            strategy_type=d.get("strategy_type"),
            family=d.get("family"),
            transforms=d.get("transforms"),
            composite_rule=d.get("composite_rule"),
            labels=d.get("labels"),
            panel_contract=d.get("panel_contract"),
            rebalance=d.get("rebalance"),
            weighting_rule=d.get("weighting_rule"),
            benchmark_definition=d.get("benchmark_definition"),
            risk_overlay=d.get("risk_overlay"),
            cost_model_version=d.get("cost_model_version"),
            alternative_weighting_variant=d.get("alternative_weighting_variant"),
            source=d.get("source"),
            research_evidence=d.get("research_evidence"),
            notes=d.get("notes"),
            extras=extras,
        )

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "FrozenStrategySpec":
        d = yaml.safe_load(yaml_text)
        if not isinstance(d, dict):
            raise FrozenSpecError(
                f"YAML root must be a mapping, got {type(d).__name__}"
            )
        return cls.from_dict(d)

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "FrozenStrategySpec":
        p = Path(path)
        if not p.exists():
            raise FrozenSpecError(f"YAML file not found: {p}")
        return cls.from_yaml(p.read_text())
