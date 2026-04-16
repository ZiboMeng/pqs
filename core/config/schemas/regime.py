"""Regime detection configuration schemas."""

from typing import Dict, Optional
from pydantic import BaseModel, Field, model_validator


class VixThresholdsConfig(BaseModel):
    """VIX level boundaries between regime states. Values must be strictly ascending."""

    bull: float = Field(default=15.0)
    risk_on: float = Field(default=20.0)
    neutral: float = Field(default=25.0)
    cautious: float = Field(default=30.0)
    risk_off: float = Field(default=35.0)
    crisis: float = Field(default=45.0)

    @model_validator(mode="after")
    def ascending_order(self) -> "VixThresholdsConfig":
        vals = [self.bull, self.risk_on, self.neutral, self.cautious, self.risk_off, self.crisis]
        if vals != sorted(vals):
            raise ValueError("VIX thresholds must be strictly ascending: bull < risk_on < ... < crisis")
        return self


class DrawdownThresholdsConfig(BaseModel):
    """SPY drawdown from peak thresholds that force minimum regime level."""

    cautious: float = Field(default=-0.05, le=0)
    risk_off: float = Field(default=-0.10, le=0)
    crisis: float = Field(default=-0.20, le=0)

    @model_validator(mode="after")
    def descending_order(self) -> "DrawdownThresholdsConfig":
        if not (self.cautious > self.risk_off > self.crisis):
            raise ValueError(
                "Drawdown thresholds must satisfy: cautious > risk_off > crisis (all negative)"
            )
        return self


class RegimePositionConstraintConfig(BaseModel):
    """Position constraints active in a specific regime state."""

    target_cash_pct_min: float = Field(ge=0, le=1.0)
    target_cash_pct_max: float = Field(ge=0, le=1.0)
    max_single_position: float = Field(ge=0, le=1.0)
    leveraged_etf_allowed: bool = True
    left_side_trading_allowed: bool = False
    left_side_max_single: float = Field(default=0.05, ge=0, le=0.20)

    @model_validator(mode="after")
    def cash_range_valid(self) -> "RegimePositionConstraintConfig":
        if self.target_cash_pct_min > self.target_cash_pct_max:
            raise ValueError("target_cash_pct_min must be <= target_cash_pct_max")
        return self


class RegimeConfig(BaseModel):
    """Full regime detection configuration."""

    spy_ema_fast: int = Field(default=50, ge=5, le=200)
    spy_ema_slow: int = Field(default=200, ge=20, le=500)
    vix_symbol: str = "^VIX"
    tnx_symbol: str = "^TNX"
    tnx_spike_threshold: float = Field(default=0.15, ge=0)  # 10Y rate daily rise in %

    # Regime smoothing: avoid flip-flopping between states
    smoothing_window: int = Field(default=3, ge=1, le=10)

    vix_thresholds: VixThresholdsConfig = Field(default_factory=VixThresholdsConfig)
    drawdown_thresholds: DrawdownThresholdsConfig = Field(default_factory=DrawdownThresholdsConfig)

    position_constraints: Dict[str, RegimePositionConstraintConfig] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def all_regimes_have_constraints(self) -> "RegimeConfig":
        required = {"BULL", "RISK_ON", "NEUTRAL", "CAUTIOUS", "RISK_OFF", "CRISIS"}
        missing = required - set(self.position_constraints.keys())
        if missing:
            raise ValueError(f"Missing position_constraints for regimes: {missing}")
        return self
