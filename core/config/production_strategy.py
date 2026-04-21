"""Production strategy single-source-of-truth loader + builder.

PRD: docs/prd_framework_completion.md §M1

`config/production_strategy.yaml` is the ONE authoritative definition of
the current production strategy. This module:
  - parses + validates the YAML via pydantic
  - enforces lifecycle invariants (active requires filled source + validation)
  - builds a MultiFactorStrategy instance from the config, wiring runtime
    safety knobs (concentration, registry strict mode) from risk.yaml

Used by:
  - scripts/run_backtest.py (baseline `multi_factor` strategy)
  - scripts/run_paper.py (live/replay paper trading)
  - scripts/run_multi_tf_backtest.py (multi-TF wrapper)
  - scripts/promote_strategy.py (M2, reads + writes this artifact)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from core.logging_setup import get_logger

logger = get_logger(__name__)


# Lifecycle states — see config/production_strategy.yaml header for semantics.
StatusLiteral = Literal["active", "conservative_default", "no_validated_best"]
SourceModeLiteral = Literal["manual", "promoted_from_archive"]

_FACTOR_WEIGHT_SUM_TOL = 1e-6


class ProductionStrategySource(BaseModel):
    mode: SourceModeLiteral = "manual"
    spec_id: str = ""
    lineage_tag: str = ""
    promoted_at: str = ""
    rationale: str = ""


class ProductionStrategyValidation(BaseModel):
    post_fix_validated: bool = False
    passed_oos_gate: bool = False
    passed_qqq_gate: bool = False
    passed_paper_backtest_alignment: bool = False
    notes: str = ""

    @property
    def all_passed(self) -> bool:
        return (
            self.post_fix_validated
            and self.passed_oos_gate
            and self.passed_qqq_gate
            and self.passed_paper_backtest_alignment
        )


class ProductionStrategyFingerprints(BaseModel):
    universe_hash: str = ""
    factor_registry_hash: str = ""
    config_hash: str = ""

    @property
    def all_filled(self) -> bool:
        return bool(self.universe_hash and self.factor_registry_hash and self.config_hash)


class ProductionStrategyConfig(BaseModel):
    schema_version: str = "1.0"
    status: StatusLiteral
    strategy_type: str = "multi_factor"
    source: ProductionStrategySource = Field(default_factory=ProductionStrategySource)
    params: Dict[str, Any] = Field(default_factory=dict)
    factor_weights: Dict[str, float] = Field(default_factory=dict)
    validation: ProductionStrategyValidation = Field(default_factory=ProductionStrategyValidation)
    fingerprints: ProductionStrategyFingerprints = Field(default_factory=ProductionStrategyFingerprints)

    @field_validator("factor_weights")
    @classmethod
    def _weights_sum_to_one(cls, v: Dict[str, float]) -> Dict[str, float]:
        if not v:
            return v
        s = sum(v.values())
        if abs(s - 1.0) > _FACTOR_WEIGHT_SUM_TOL:
            raise ValueError(f"factor_weights must sum to 1.0 (got {s:.6f})")
        return v

    @field_validator("factor_weights")
    @classmethod
    def _weights_names_in_registry(cls, v: Dict[str, float]) -> Dict[str, float]:
        if not v:
            return v
        # Import here to avoid circular import at module load
        from core.factors.factor_registry import PRODUCTION_FACTORS
        unknown = set(v.keys()) - set(PRODUCTION_FACTORS)
        if unknown:
            raise ValueError(
                f"factor_weights contains unknown names (not in PRODUCTION_FACTORS): "
                f"{sorted(unknown)}. Valid names: {sorted(PRODUCTION_FACTORS)}"
            )
        return v

    @model_validator(mode="after")
    def _active_requires_source_and_validation(self) -> "ProductionStrategyConfig":
        if self.status == "active":
            if self.source.mode != "promoted_from_archive":
                raise ValueError(
                    "status=active requires source.mode='promoted_from_archive'; "
                    "use scripts/promote_strategy.py, do not hand-edit status."
                )
            if not self.source.spec_id or not self.source.lineage_tag or not self.source.promoted_at:
                raise ValueError(
                    "status=active requires source.spec_id / lineage_tag / promoted_at to be non-empty"
                )
            if not self.validation.all_passed:
                raise ValueError(
                    "status=active requires validation.{post_fix_validated, passed_oos_gate, "
                    "passed_qqq_gate, passed_paper_backtest_alignment} all true"
                )
            if not self.fingerprints.all_filled:
                raise ValueError(
                    "status=active requires fingerprints.{universe_hash, factor_registry_hash, "
                    "config_hash} to be non-empty"
                )
        return self

    def summary_line(self) -> str:
        """One-line diagnostic string for startup log."""
        if self.status == "active":
            return (
                f"ProductionStrategy: status=active strategy_type={self.strategy_type} "
                f"spec_id={self.source.spec_id[:12]} lineage={self.source.lineage_tag}"
            )
        return (
            f"ProductionStrategy: status={self.status} strategy_type={self.strategy_type} "
            f"(no validated spec_id; {len(self.factor_weights)} factor weights)"
        )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = "config/production_strategy.yaml"


class ProductionStrategyError(RuntimeError):
    """Raised when production strategy cannot be loaded or used."""


def load_production_strategy(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> ProductionStrategyConfig:
    """Load + validate the production strategy artifact.

    Raises ProductionStrategyError if file missing or schema invalid.
    """
    p = Path(path)
    if not p.exists():
        raise ProductionStrategyError(
            f"Production strategy artifact not found at {p}. "
            f"See docs/prd_framework_completion.md §M1."
        )
    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise ProductionStrategyError(f"Failed to parse {p}: {exc}") from exc
    try:
        return ProductionStrategyConfig(**raw)
    except Exception as exc:
        raise ProductionStrategyError(f"Invalid schema in {p}: {exc}") from exc


# ---------------------------------------------------------------------------
# Builder — constructs an actual strategy instance from config
# ---------------------------------------------------------------------------


def build_strategy_from_config(
    ps_cfg: ProductionStrategyConfig,
    risk_cfg: Any,
    symbols: List[str],
):
    """Build a strategy instance from production_strategy config.

    Args:
        ps_cfg: parsed ProductionStrategyConfig
        risk_cfg: parsed RiskConfig (from config/risk.yaml); provides
                  runtime safety knobs (concentration, strict_registry)
        symbols: the list of eligible trading symbols (risk_syms)

    Returns:
        Strategy instance (currently only MultiFactorStrategy supported)

    Raises:
        ProductionStrategyError for unsupported strategy_type or
        for `no_validated_best` status.
    """
    if ps_cfg.status == "no_validated_best":
        raise ProductionStrategyError(
            "Production strategy status is 'no_validated_best'. "
            "Run `scripts/promote_strategy.py` to promote a validated "
            "spec_id, or pass --strategy X / --override-production to "
            "force a non-production strategy for research use."
        )

    if ps_cfg.strategy_type != "multi_factor":
        raise ProductionStrategyError(
            f"Unsupported strategy_type={ps_cfg.strategy_type!r}. "
            f"Currently only 'multi_factor' can be driven by the artifact."
        )

    # Log provenance at construction time
    logger.info(ps_cfg.summary_line())
    if ps_cfg.status == "conservative_default":
        logger.warning(
            "Using CONSERVATIVE_DEFAULT production strategy. No post-fix "
            "validated best exists yet. For live paper trading this is "
            "allowed but runtime alignment (M3) will WARN."
        )

    from core.signals.strategies.multi_factor import MultiFactorStrategy

    params = dict(ps_cfg.params)  # copy

    # Runtime safety knobs from risk.yaml (not intrinsic to strategy; may
    # change without re-promoting).
    concentration_enabled = getattr(
        getattr(risk_cfg, "strategy_concentration", None), "enabled", False
    )
    soft_cap = (
        risk_cfg.strategy_concentration.soft_cap_max_single
        if concentration_enabled else None
    )
    conc_warn = (
        risk_cfg.strategy_concentration.concentration_warn_threshold
        if concentration_enabled else None
    )
    strict_registry = getattr(
        getattr(risk_cfg, "factor_registry", None), "strict_mode", False
    )

    return MultiFactorStrategy(
        symbols=symbols,
        factor_weights=dict(ps_cfg.factor_weights),
        soft_cap_max_single=soft_cap,
        concentration_warn_threshold=conc_warn,
        strict_registry=strict_registry,
        **params,
    )


# ---------------------------------------------------------------------------
# Convenience: load + build in one call
# ---------------------------------------------------------------------------


def load_and_build(
    risk_cfg: Any,
    symbols: List[str],
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[ProductionStrategyConfig, Any]:
    """Shortcut: load artifact + build strategy. Returns (cfg, strategy)."""
    ps_cfg = load_production_strategy(path)
    strat = build_strategy_from_config(ps_cfg, risk_cfg, symbols)
    return ps_cfg, strat
