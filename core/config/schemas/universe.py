"""Universe / asset selection configuration schemas."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class UniverseLiquidityConfig(BaseModel):
    min_avg_volume_30d: int = Field(default=1_000_000, ge=0)
    min_price_usd: float = Field(default=5.0, ge=0)
    min_history_days: int = Field(default=252, ge=60)


class HighRiskSymbolConfig(BaseModel):
    """Extra constraints applied to leveraged ETFs (TQQQ, SOXL, etc.)."""

    symbols: List[str] = Field(default_factory=list)
    max_single_weight: float = Field(default=0.10, ge=0, le=1.0)
    max_total_weight: float = Field(default=0.12, ge=0, le=1.0)
    require_risk_on_regime: bool = True
    left_side_trading_multiplier: float = Field(default=0.5, ge=0, le=1.0)


class UniverseConfig(BaseModel):
    """
    Four-layer universe:
      seed_pool      → initial known symbols
      tradable       → all symbols the system may ever trade
      eligible       → passes current liquidity/quality filters
      selected       → actually enters strategy & portfolio
    """

    seed_pool: List[str] = Field(
        default=["SPY", "QQQ", "GLD", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "TQQQ", "SOXL"]
    )
    blacklist: List[str] = Field(default=["SQQQ", "SOXS"])
    high_risk_symbols: HighRiskSymbolConfig = Field(default_factory=HighRiskSymbolConfig)
    liquidity: UniverseLiquidityConfig = Field(default_factory=UniverseLiquidityConfig)

    # interday vs intraday can use different subsets
    interday_eligible_override: Optional[List[str]] = None
    intraday_eligible_override: Optional[List[str]] = None

    max_selected_symbols: int = Field(default=10, ge=1, le=50)
    min_selected_symbols: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def blacklist_not_in_seed(self) -> "UniverseConfig":
        overlap = set(self.seed_pool) & set(self.blacklist)
        if overlap:
            raise ValueError(f"Symbols in both seed_pool and blacklist: {overlap}")
        return self

    @model_validator(mode="after")
    def min_lte_max(self) -> "UniverseConfig":
        if self.min_selected_symbols > self.max_selected_symbols:
            raise ValueError("min_selected_symbols must be <= max_selected_symbols")
        return self

    def is_blacklisted(self, symbol: str) -> bool:
        return symbol in self.blacklist

    def is_high_risk(self, symbol: str) -> bool:
        return symbol in self.high_risk_symbols.symbols
