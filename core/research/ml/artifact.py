"""PRD #4 P4.4 sub-step 2 — artifact persistence for trained rank models.

Saves a fitted ``RankModelProtocol`` instance + metadata so:
  - same artifact can be reloaded and used for prediction
  - drift can be detected (spec_id mismatch → reject)
  - audit trail records training window / hyperparams / fold metrics /
    feature list / sealed_years / timestamp / §9.0 output_type

Layout (per artifact, two sibling files):
  data/ml/rank_<lineage_tag>.pkl    ← pickled model object
  data/ml/rank_<lineage_tag>.json   ← metadata (parsed at load time)

Determinism:
  - ``spec_id`` = sha256 of canonical-JSON metadata MINUS per-fold
    metrics / timestamp / lineage_tag. Retraining the SAME spec
    (same model class + hyperparams + train config + feature list +
    sealed years) yields the SAME spec_id — usable for promote-time
    lookup + drift detection (M3 alignment).
  - ``lineage_tag`` = readable identifier (model_class + train window
    + UTC timestamp) for ops; NOT load-bearing for spec identity.

§9.0 invariant: ``ArtifactMetadata.output_type`` MUST be ``"rank"``
for any artifact produced by this pipeline. Loaders refuse to attach
a regressor-style artifact (continuous magnitude) to the sidecar path.

PRD: docs/prd/20260520-prd_rank_first_ml_pipeline.md §P4.4
"""
from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.research.ml.pipeline import (
    FoldMetrics,
    WalkForwardConfig,
    WalkForwardResult,
)
from core.research.ml.rank_model import RankModelProtocol

__all__ = [
    "ArtifactMetadata",
    "ModelArtifact",
    "SavePaths",
    "ArtifactError",
    "ArtifactSchemaError",
    "ArtifactSpecMismatchError",
    "SCHEMA_VERSION",
    "ArtifactGovernance",
    "validate_artifact_governance",
    "compute_spec_id",
    "compute_lineage_tag",
    "make_artifact_metadata",
    "save_artifact",
    "load_artifact",
]

SCHEMA_VERSION = "1.0"


class ArtifactError(RuntimeError):
    """Base for artifact-related errors."""


class ArtifactSchemaError(ArtifactError):
    """Raised when artifact JSON is malformed or schema_version mismatched."""


class ArtifactSpecMismatchError(ArtifactError):
    """Raised when a loaded artifact's recomputed spec_id != stored spec_id.

    This is tamper / corruption detection. Either the pickle was modified
    or the metadata was edited; the pair is no longer trustworthy.
    """


@dataclass
class ArtifactGovernance:
    """PRD §10.2 governance metadata — mandated on every ML artifact
    (supplement S2 / master §10.3 "no ML artifact can be promoted
    without these fields").

    Required fields have no default — an `ArtifactGovernance` cannot be
    constructed without them. `validate_artifact_governance` additionally
    fail-closes on empty values and on missing portfolio-tier fields.
    """
    # ── always required (§10.2) ──────────────────────────────────────
    task_family: str
    source_tiers: Tuple[str, ...]
    label_mode: str
    sample_weight_mode: str
    purge_embargo: Dict[str, Any]
    context_bundle: str
    training_universe: str
    model_family: str
    objective: str
    config_hash: str
    trial_count: int
    # ── §9.6 selection outcome — present once a cross-config select ran
    dsr: Optional[float] = None
    pbo: Optional[float] = None
    # ── §10.2 conditional ────────────────────────────────────────────
    score_to_weight_mode: Optional[str] = None
    exit_policy_mode: Optional[str] = None
    reused_native_components: bool = False
    benchmark_relative_eval: Optional[Dict[str, Any]] = None
    portfolio_acceptance_path: Optional[str] = None
    # ── portfolio-level extras (§10.2) — required when is_portfolio ──
    target_weight_mode: Optional[str] = None
    risk_scaling_mode: Optional[str] = None
    constraint_set_id: Optional[str] = None
    cost_model_id: Optional[str] = None
    execution_assumption_id: Optional[str] = None


_REQUIRED_GOVERNANCE: Tuple[str, ...] = (
    "task_family", "source_tiers", "label_mode", "sample_weight_mode",
    "purge_embargo", "context_bundle", "training_universe", "model_family",
    "objective", "config_hash", "trial_count",
)
_PORTFOLIO_GOVERNANCE: Tuple[str, ...] = (
    "score_to_weight_mode", "target_weight_mode", "risk_scaling_mode",
    "constraint_set_id", "cost_model_id", "execution_assumption_id",
    "portfolio_acceptance_path",
)


def _gov_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, tuple, list, dict)):
        return len(value) == 0
    return False


def validate_artifact_governance(
    metadata: "ArtifactMetadata", *, is_portfolio: bool = False,
) -> None:
    """Fail-closed §10.2 check (supplement S2). Raises ArtifactSchemaError
    if the governance block is absent or any mandated field is empty.

    Call at promote / freeze time — an artifact missing §10.2 metadata
    must NOT be promotable (master §10.3)."""
    g = metadata.governance
    if g is None:
        raise ArtifactSchemaError(
            "artifact has no §10.2 governance block; ML artifacts cannot "
            "be promoted without it (supplement S2 / master §10.3).")
    missing = [f for f in _REQUIRED_GOVERNANCE if _gov_is_empty(getattr(g, f))]
    if not isinstance(g.trial_count, int) or g.trial_count < 1:
        missing.append("trial_count(<1)")
    if is_portfolio:
        missing += [f for f in _PORTFOLIO_GOVERNANCE
                    if _gov_is_empty(getattr(g, f))]
    if missing:
        raise ArtifactSchemaError(
            f"§10.2 governance incomplete — empty/missing fields: "
            f"{sorted(set(missing))} (is_portfolio={is_portfolio}).")


@dataclass
class ArtifactMetadata:
    """Metadata persisted alongside the pickled model.

    spec_id-defining fields (must remain stable across retraining of
    the same spec):
        model_class_name, hyperparams, train_config, feature_columns,
        sealed_years, output_type, schema_version

    Evidence fields (vary across retrains; NOT in spec_id):
        per_fold_metrics, mean_rank_ic, mean_rank_ir, n_successful_folds,
        n_failed_folds, trained_at_utc, lineage_tag
    """
    schema_version: str
    model_class_name: str
    hyperparams: Dict[str, Any]
    train_config: Dict[str, Any]               # serialized WalkForwardConfig
    feature_columns: Tuple[str, ...]
    sealed_years: Tuple[int, ...]
    output_type: str                           # MUST be "rank" per §9.0
    per_fold_metrics: List[Dict[str, Any]]
    mean_rank_ic: float
    mean_rank_ir: float
    n_successful_folds: int
    n_failed_folds: int
    trained_at_utc: str
    lineage_tag: str
    spec_id: str
    # §10.2 governance block (supplement S2). Optional at the dataclass
    # level so legacy constructions don't break; `validate_artifact_
    # governance` fail-closes on None at promote time.
    governance: Optional[ArtifactGovernance] = None

    def __post_init__(self) -> None:
        # §9.0 invariant: output_type must be discrete (rank percentile
        # OR sign vote {0,1}). Magnitude / continuous-return / proba
        # are §9.0 post-fix HARD禁.
        _ALLOWED_OUTPUT_TYPES = {"rank", "sign"}
        if self.output_type not in _ALLOWED_OUTPUT_TYPES:
            raise ValueError(
                f"§9.0 invariant: ArtifactMetadata.output_type must be "
                f"one of {sorted(_ALLOWED_OUTPUT_TYPES)}, got "
                f"{self.output_type!r}. ML sidecar pipeline refuses "
                f"continuous-magnitude artifacts.")


@dataclass
class ModelArtifact:
    """Fitted model + metadata."""
    model: RankModelProtocol
    metadata: ArtifactMetadata


@dataclass
class SavePaths:
    """Paths written by ``save_artifact``."""
    pkl_path: Path
    json_path: Path


# ---------------------------------------------------------------------------
# Canonical metadata for spec_id hashing
# ---------------------------------------------------------------------------


_SPEC_ID_FIELDS = (
    "schema_version", "model_class_name", "hyperparams", "train_config",
    "feature_columns", "sealed_years", "output_type",
)


def _canonical_json(payload: Dict[str, Any]) -> str:
    """Sorted-keys, no-whitespace JSON for deterministic hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_spec_id(spec_dict: Dict[str, Any]) -> str:
    """Deterministic sha256 of canonical metadata (spec_id-defining fields).

    Args:
        spec_dict: dict with at least the ``_SPEC_ID_FIELDS`` keys.
            Tuples are normalized to lists (JSON-serializable) before
            hashing so input form doesn't change the hash.

    Returns:
        64-char hex sha256.
    """
    payload = {}
    for k in _SPEC_ID_FIELDS:
        if k not in spec_dict:
            raise ArtifactSchemaError(
                f"compute_spec_id: missing required field {k!r}; need "
                f"all of {_SPEC_ID_FIELDS}")
        v = spec_dict[k]
        # normalize tuples -> lists for canonical form
        if isinstance(v, tuple):
            v = list(v)
        payload[k] = v
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_lineage_tag(
    model_class_name: str,
    train_start_year: int,
    train_end_year: int,
    trained_at_utc: Optional[str] = None,
) -> str:
    """Build a readable identifier: ``<model>_<startY>-<endY>_<UTC stamp>``.

    Example: ``LinearBaselineRankModel_2010-2017_20260520T230000Z``.
    """
    if trained_at_utc is None:
        trained_at_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{model_class_name}_{train_start_year}-{train_end_year}_{trained_at_utc}"


# ---------------------------------------------------------------------------
# Building metadata from a WalkForwardResult
# ---------------------------------------------------------------------------


def _fold_to_dict(fm: FoldMetrics) -> Dict[str, Any]:
    return {
        "fold_idx": fm.fold.fold_idx,
        "train_start": fm.fold.train_start.isoformat(),
        "train_end": fm.fold.train_end.isoformat(),
        "val_start": fm.fold.val_start.isoformat(),
        "val_end": fm.fold.val_end.isoformat(),
        "rank_ic": fm.rank_ic,
        "rank_ir": fm.rank_ir,
        "train_n_obs": fm.train_n_obs,
        "val_n_obs": fm.val_n_obs,
        "error": fm.error,
    }


def _config_to_dict(cfg: WalkForwardConfig) -> Dict[str, Any]:
    return {
        "start_year": cfg.start_year,
        "end_year": cfg.end_year,
        "train_window_years": cfg.train_window_years,
        "val_window_years": cfg.val_window_years,
        "step_years": cfg.step_years,
    }


def make_artifact_metadata(
    *,
    result: WalkForwardResult,
    model_class_name: str,
    hyperparams: Dict[str, Any],
    feature_columns: Tuple[str, ...],
    output_type: str = "rank",
    trained_at_utc: Optional[str] = None,
    governance: Optional[ArtifactGovernance] = None,
) -> ArtifactMetadata:
    """Build ArtifactMetadata from a completed WalkForwardResult.

    Output_type defaults to "rank" (the §9.0-valid form). Pass an
    explicit value only for downstream tooling that absolutely must
    audit a non-rank artifact — which itself is §9.0 violation.
    """
    if trained_at_utc is None:
        trained_at_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    train_config = _config_to_dict(result.config)
    per_fold = [_fold_to_dict(f) for f in result.per_fold]

    spec_dict = {
        "schema_version": SCHEMA_VERSION,
        "model_class_name": model_class_name,
        "hyperparams": hyperparams,
        "train_config": train_config,
        "feature_columns": list(feature_columns),
        "sealed_years": list(result.sealed_years),
        "output_type": output_type,
    }
    spec_id = compute_spec_id(spec_dict)
    lineage_tag = compute_lineage_tag(
        model_class_name,
        result.config.start_year,
        result.config.end_year,
        trained_at_utc=trained_at_utc,
    )

    return ArtifactMetadata(
        schema_version=SCHEMA_VERSION,
        model_class_name=model_class_name,
        hyperparams=hyperparams,
        train_config=train_config,
        feature_columns=tuple(feature_columns),
        sealed_years=tuple(result.sealed_years),
        output_type=output_type,
        per_fold_metrics=per_fold,
        mean_rank_ic=result.mean_rank_ic,
        mean_rank_ir=result.mean_rank_ir,
        n_successful_folds=result.n_successful_folds,
        n_failed_folds=result.n_failed_folds,
        trained_at_utc=trained_at_utc,
        lineage_tag=lineage_tag,
        spec_id=spec_id,
        governance=governance,
    )


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def _resolve_paths(base_path: str | Path) -> SavePaths:
    p = Path(base_path)
    # strip known suffix if present
    if p.suffix in (".pkl", ".json"):
        stem = p.with_suffix("")
    else:
        stem = p
    return SavePaths(
        pkl_path=stem.with_suffix(".pkl"),
        json_path=stem.with_suffix(".json"),
    )


def _metadata_to_jsonable(metadata: ArtifactMetadata) -> Dict[str, Any]:
    d = asdict(metadata)
    # tuples → lists for JSON
    d["feature_columns"] = list(metadata.feature_columns)
    d["sealed_years"] = list(metadata.sealed_years)
    return d


def save_artifact(
    artifact: ModelArtifact, base_path: str | Path,
) -> SavePaths:
    """Persist ``artifact.model`` to .pkl and ``artifact.metadata`` to .json.

    ``base_path`` may include any (or no) suffix; both files are written
    at the stem location.
    """
    paths = _resolve_paths(base_path)
    paths.pkl_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.pkl_path.open("wb") as f:
        pickle.dump(artifact.model, f, protocol=pickle.HIGHEST_PROTOCOL)
    paths.json_path.write_text(
        json.dumps(_metadata_to_jsonable(artifact.metadata),
                   sort_keys=True, indent=2)
    )
    return paths


def _metadata_from_json(payload: Dict[str, Any]) -> ArtifactMetadata:
    required = (
        "schema_version", "model_class_name", "hyperparams", "train_config",
        "feature_columns", "sealed_years", "output_type",
        "per_fold_metrics", "mean_rank_ic", "mean_rank_ir",
        "n_successful_folds", "n_failed_folds",
        "trained_at_utc", "lineage_tag", "spec_id",
    )
    missing = [k for k in required if k not in payload]
    if missing:
        raise ArtifactSchemaError(
            f"ArtifactMetadata JSON missing fields: {missing}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ArtifactSchemaError(
            f"ArtifactMetadata schema_version mismatch: file="
            f"{payload['schema_version']!r}, code={SCHEMA_VERSION!r}")
    return ArtifactMetadata(
        schema_version=payload["schema_version"],
        model_class_name=payload["model_class_name"],
        hyperparams=payload["hyperparams"],
        train_config=payload["train_config"],
        feature_columns=tuple(payload["feature_columns"]),
        sealed_years=tuple(payload["sealed_years"]),
        output_type=payload["output_type"],
        per_fold_metrics=payload["per_fold_metrics"],
        mean_rank_ic=payload["mean_rank_ic"],
        mean_rank_ir=payload["mean_rank_ir"],
        n_successful_folds=payload["n_successful_folds"],
        n_failed_folds=payload["n_failed_folds"],
        trained_at_utc=payload["trained_at_utc"],
        lineage_tag=payload["lineage_tag"],
        spec_id=payload["spec_id"],
        governance=(
            ArtifactGovernance(**payload["governance"])
            if payload.get("governance") is not None else None),
    )


def load_artifact(base_path: str | Path) -> ModelArtifact:
    """Reload a saved artifact + verify spec_id integrity.

    Raises:
        FileNotFoundError: pkl or json missing
        ArtifactSchemaError: JSON malformed or schema bump
        ArtifactSpecMismatchError: recomputed spec_id differs from stored
            (tamper / corruption detection)
    """
    paths = _resolve_paths(base_path)
    if not paths.pkl_path.exists():
        raise FileNotFoundError(f"ModelArtifact pkl missing: {paths.pkl_path}")
    if not paths.json_path.exists():
        raise FileNotFoundError(f"ModelArtifact json missing: {paths.json_path}")
    payload = json.loads(paths.json_path.read_text())
    metadata = _metadata_from_json(payload)
    # recompute spec_id from the persisted fields and verify
    spec_dict = {k: payload[k] for k in _SPEC_ID_FIELDS}
    recomputed = compute_spec_id(spec_dict)
    if recomputed != metadata.spec_id:
        raise ArtifactSpecMismatchError(
            f"spec_id mismatch loading {paths.json_path}: "
            f"stored={metadata.spec_id[:12]}..., recomputed="
            f"{recomputed[:12]}...; metadata likely edited.")
    with paths.pkl_path.open("rb") as f:
        model = pickle.load(f)
    return ModelArtifact(model=model, metadata=metadata)
