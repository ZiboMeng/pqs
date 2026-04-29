"""
Acceptance-tier thresholds — single source of truth.

These thresholds gate Tier D promotion (WindowAnalyzer), walk-forward /
OOS pass criteria, and factor auto-tier classification (factor_evaluator).
Tunable via ``config/acceptance.yaml``.

Out of scope: mining gates (see ``config/backtest.yaml::mining``,
consumed by ``MiningEvaluator``); ``acceptance_pack._THRESHOLDS``
(intentionally frozen contract for promoted artifacts — codex round-13
§"Decision 3"); concentration gate (PRD v3 §C derived).

Shape mandated by codex round-13: three nested submodels under
``AcceptanceThresholds``, one policy surface, three semantic groups.
See ``docs/prd/20260428-acceptance_threshold_unification_prd.md`` v1.1
§4.1 for design rationale and §4.4 for consumer wiring.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TierDThresholds(BaseModel):
    """Tier D acceptance thresholds (consumed by ``WindowAnalyzer.evaluate_tier_d``)."""

    model_config = ConfigDict(extra="forbid")

    min_excess_return_vs_spy: float = Field(default=0.05, ge=0)
    min_ir_vs_spy: float = Field(default=0.30, ge=0)
    max_dd_vs_spy_multiplier: float = Field(default=1.50, ge=1.0)


class WalkForwardThresholds(BaseModel):
    """Walk-forward / OOS validation thresholds.

    Codex round-13 §"Decision 1": these are governance thresholds; they
    belong here (one policy surface) rather than in ``MiningEvaluator``,
    which is the consumer not the owner. ``MiningEvaluator`` may later
    read from ``cfg.acceptance.walk_forward`` but it does NOT define
    these defaults.
    """

    model_config = ConfigDict(extra="forbid")

    min_oos_vs_is_return_ratio: float = Field(default=0.50, ge=0)
    min_windows_positive_excess_pct: float = Field(default=0.60, ge=0, le=1.0)
    auto_fail_single_period_contribution: float = Field(default=0.50, ge=0, le=1.0)
    auto_fail_single_asset_contribution: float = Field(default=0.40, ge=0, le=1.0)
    auto_fail_crisis_vs_benchmark_multiplier: float = Field(default=2.0, ge=1.0)
    max_crisis_drawdown_abs: float = Field(default=0.25, ge=0, le=1.0)


class FactorTierThresholds(BaseModel):
    """Factor auto-tier IR cuts (consumed by ``factor_evaluator._auto_tier``).

    Codex round-13 §"Decision 2": separate submodel because factor-tier
    semantics are adjacent to but not identical to strategy-tier
    semantics (the letter overlap S/A/B/C/D between Tier D and factor
    tiers is coincidental).
    """

    model_config = ConfigDict(extra="forbid")

    s_min_ir: float = Field(default=0.80, ge=0)
    a_min_ir: float = Field(default=0.50, ge=0)
    b_min_ir: float = Field(default=0.30, ge=0)
    c_min_ir: float = Field(default=0.10, ge=0)


class AcceptanceThresholds(BaseModel):
    """Single source of truth for acceptance-tier thresholds.

    Three nested groups: ``tier_d`` (Tier D promotion gate),
    ``walk_forward`` (OOS / walk-forward governance), ``factor_tiers``
    (factor IR auto-tier cuts).
    """

    model_config = ConfigDict(extra="forbid")

    tier_d: TierDThresholds = Field(default_factory=TierDThresholds)
    walk_forward: WalkForwardThresholds = Field(default_factory=WalkForwardThresholds)
    factor_tiers: FactorTierThresholds = Field(default_factory=FactorTierThresholds)
