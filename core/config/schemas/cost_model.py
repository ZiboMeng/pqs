"""Cost model configuration schemas."""

from typing import Dict, List
from pydantic import BaseModel, Field, model_validator


class CostTierConfig(BaseModel):
    """Cost parameters for a group of symbols."""

    symbols: List[str] = Field(default_factory=list)
    commission_bps: float = Field(ge=0, le=50)
    slippage_interday_bps: float = Field(ge=0, le=200)
    slippage_intraday_bps: float = Field(ge=0, le=200)

    @model_validator(mode="after")
    def intraday_slippage_gte_interday(self) -> "CostTierConfig":
        if self.slippage_intraday_bps < self.slippage_interday_bps:
            raise ValueError(
                f"intraday slippage ({self.slippage_intraday_bps}bps) must be >= "
                f"interday slippage ({self.slippage_interday_bps}bps)"
            )
        return self


class CapacityModelConfig(BaseModel):
    enabled: bool = False
    threshold_usd: float = Field(default=500_000, ge=0)
    impact_bps_per_100k: float = Field(default=1.0, ge=0)


class CostModelConfig(BaseModel):
    """
    Layered cost model: commission + slippage, tiered by symbol type.
    All values in basis points (bps). 1 bps = 0.01%.
    """

    mode: str = Field(default="bps_based", pattern="^(bps_based|spread_based)$")
    vix_stress_threshold: float = Field(default=30.0, ge=15, le=80)
    stress_slippage_multiplier: float = Field(default=2.5, ge=1.0, le=10.0)

    tiers: Dict[str, CostTierConfig] = Field(default_factory=dict)
    capacity_model: CapacityModelConfig = Field(default_factory=CapacityModelConfig)

    @model_validator(mode="after")
    def default_tier_exists(self) -> "CostModelConfig":
        if "default" not in self.tiers:
            raise ValueError("cost_model.tiers must include a 'default' tier as fallback")
        return self

    def get_tier_for_symbol(self, symbol: str) -> CostTierConfig:
        """Return the matching tier for a symbol, falling back to default."""
        for tier in self.tiers.values():
            if symbol in tier.symbols:
                return tier
        return self.tiers["default"]

    def get_slippage_bps(self, symbol: str, freq: str, vix: float) -> float:
        """
        Return total slippage in bps for a symbol/freq/vix combination.
        freq: 'interday' | 'intraday'
        """
        tier = self.get_tier_for_symbol(symbol)
        base = (
            tier.slippage_interday_bps
            if freq == "interday"
            else tier.slippage_intraday_bps
        )
        multiplier = self.stress_slippage_multiplier if vix >= self.vix_stress_threshold else 1.0
        return base * multiplier

    def get_commission_bps(self, symbol: str) -> float:
        return self.get_tier_for_symbol(symbol).commission_bps

    def get_total_cost_bps(self, symbol: str, freq: str, vix: float) -> float:
        return self.get_commission_bps(symbol) + self.get_slippage_bps(symbol, freq, vix)
