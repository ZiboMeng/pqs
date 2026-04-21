"""Risk management configuration schemas."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from enum import Enum


class KillSwitchLevel(str, Enum):
    WARNING = "WARNING"
    REDUCE = "REDUCE"
    DEFENSIVE = "DEFENSIVE"
    HALT = "HALT"


class DrawdownLimitsConfig(BaseModel):
    """Portfolio-level drawdown limits that trigger escalating responses."""

    warning_pct: float = Field(default=0.10, ge=0, le=1.0)
    reduce_pct: float = Field(default=0.15, ge=0, le=1.0)
    defensive_pct: float = Field(default=0.20, ge=0, le=1.0)
    halt_pct: float = Field(default=0.25, ge=0, le=1.0)

    # Benchmark comparison: strategy drawdown must not exceed benchmark * multiplier
    max_drawdown_vs_benchmark_multiplier: float = Field(default=1.5, ge=1.0, le=5.0)

    # Single crisis event absolute cap
    single_crisis_drawdown_cap: float = Field(default=0.25, ge=0, le=1.0)

    @model_validator(mode="after")
    def ascending_order(self) -> "DrawdownLimitsConfig":
        vals = [self.warning_pct, self.reduce_pct, self.defensive_pct, self.halt_pct]
        if vals != sorted(vals):
            raise ValueError(
                "Drawdown limits must be ascending: warning < reduce < defensive < halt"
            )
        return self


class PositionLimitsConfig(BaseModel):
    """Hard position size constraints."""

    max_single_position: float = Field(default=0.35, ge=0, le=1.0)
    max_positions: int = Field(default=10, ge=1, le=50)
    min_position_size_usd: float = Field(default=500.0, ge=0)
    allow_fractional_shares: bool = False

    # Per-symbol overrides (symbol → max weight)
    symbol_caps: Dict[str, float] = Field(default_factory=dict)

    def get_cap(self, symbol: str) -> float:
        return self.symbol_caps.get(symbol, self.max_single_position)


class BudgetConfig(BaseModel):
    """
    Portfolio budget allocation by bucket.
    Buckets: core / tactical / enhancer / cash
    All weights must sum to <= 1.0.
    """

    core: float = Field(default=0.58, ge=0, le=1.0)
    tactical: float = Field(default=0.27, ge=0, le=1.0)
    enhancer: float = Field(default=0.10, ge=0, le=1.0)
    # cash is implicit: 1.0 - (core + tactical + enhancer)

    @model_validator(mode="after")
    def total_lte_one(self) -> "BudgetConfig":
        total = self.core + self.tactical + self.enhancer
        if total > 1.0:
            raise ValueError(
                f"Budget sum ({total:.3f}) exceeds 1.0. "
                "Reduce core/tactical/enhancer allocations."
            )
        return self

    @property
    def min_cash(self) -> float:
        return 1.0 - (self.core + self.tactical + self.enhancer)


class LeftSideTradingConfig(BaseModel):
    """Configuration for the controlled left-side trading enhancement module."""

    enabled: bool = False
    allowed_regimes: List[str] = Field(default=["RISK_OFF"])
    min_drawdown_from_peak: float = Field(default=-0.15, le=0)
    min_factor_consensus: int = Field(default=3, ge=1)
    max_vix: float = Field(default=40.0, ge=0)
    no_active_kill_switch: bool = True

    max_single_position: float = Field(default=0.05, ge=0, le=0.15)
    build_in_tranches: int = Field(default=3, ge=1, le=10)
    tranche_interval_days: int = Field(default=3, ge=1)

    time_stop_days: int = Field(default=15, ge=1)
    loss_stop_pct: float = Field(default=-0.08, le=0)
    profit_target_pct: float = Field(default=0.15, ge=0)

    auto_disable_on_consecutive_loss: int = Field(default=3, ge=1)


class StrategyConcentrationConfig(BaseModel):
    """Strategy-level concentration control (closeout 2026-04-20).

    Deliberately separate from PositionLimitsConfig.max_single_position,
    which is the portfolio HARD cap enforced by PortfolioConstructor.
    These are SOFT knobs applied by individual strategies (e.g.
    MultiFactorStrategy) BEFORE the constructor hard cap:

      soft_cap_max_single   : if a raw per-symbol weight exceeds this,
                              clip + iteratively redistribute to the
                              non-violators, preserving total exposure.
                              None / 0 → disabled (constructor still
                              enforces hard cap).
      concentration_warn    : purely diagnostic. Log WARNING whenever
                              any date's max single weight exceeds this.

    Rationale: keeping these separate means strategies can fail soft
    (redistribute then log) while the portfolio constructor fails hard
    (reject or clip without redistribute) — consistent with the
    'defense in depth' pattern in CLAUDE.md.
    """

    enabled: bool = True
    soft_cap_max_single:          Optional[float] = Field(default=0.35, ge=0, le=1.0)
    concentration_warn_threshold: Optional[float] = Field(default=0.40, ge=0, le=1.0)


class IntradayTimingConfig(BaseModel):
    """Thresholds and scaling rules for the multi-TF timing layer
    (core/intraday/multi_timescale.py::decide_timing).

    Migrated from hardcoded module constants (2026-04-20, P1 闭环) so
    thresholds can be tuned without code change.
    """

    # Lowest timing_scale allowed under strong higher-TF contradict.
    # Below this floor, the soft veto becomes a hard veto (execute=False).
    min_timing_scale: float = Field(default=0.0, ge=0.0, le=1.0)

    # If timing_scale falls below this, defer execution for the bar.
    execute_threshold: float = Field(default=0.15, ge=0.0, le=1.0)

    # Scaling applied when 60m contradicts a long daily target (soft veto).
    scale_when_60m_contradict: float = Field(default=0.5, ge=0.0, le=1.0)

    # Scaling applied when 60m is neutral (flat bar).
    scale_when_60m_neutral: float = Field(default=0.8, ge=0.0, le=1.0)

    # Multiplicative 30m confirmation / contradiction / neutral factors.
    mult_30m_contradict: float = Field(default=0.5, ge=0.0, le=1.0)
    mult_30m_neutral:    float = Field(default=0.8, ge=0.0, le=1.0)


class RiskConfig(BaseModel):
    """Top-level risk management configuration."""

    # Hard constraints (never violated)
    long_only: bool = True
    allow_margin: bool = False
    allow_short: bool = False
    max_gross_exposure: float = Field(default=1.0, ge=0, le=1.0)

    drawdown_limits: DrawdownLimitsConfig = Field(default_factory=DrawdownLimitsConfig)
    position_limits: PositionLimitsConfig = Field(default_factory=PositionLimitsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    left_side_trading: LeftSideTradingConfig = Field(default_factory=LeftSideTradingConfig)
    intraday_timing: IntradayTimingConfig = Field(default_factory=IntradayTimingConfig)
    strategy_concentration: StrategyConcentrationConfig = Field(
        default_factory=StrategyConcentrationConfig,
    )

    @model_validator(mode="after")
    def hard_constraints_immutable(self) -> "RiskConfig":
        if not self.long_only:
            raise ValueError("long_only must be True — this is a hard constraint")
        if self.allow_margin:
            raise ValueError("allow_margin must be False — this is a hard constraint")
        if self.allow_short:
            raise ValueError("allow_short must be False — this is a hard constraint")
        return self
