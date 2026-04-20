"""Universe / asset selection configuration schemas."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator, ConfigDict


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


class DataSensitivityConfig(BaseModel):
    """Guard rails for factor computation when data sources have different
    volume / micro-structure semantics.

    Motivation: trades_backfill ETF bars apply a minimal filter
    (correction<1 + late-report dedup) while the stocks-only CSV source uses
    a different volume aggregation rule. Absolute volume values are not
    apples-to-apples across sources — so factors that depend on volume
    semantics (VWAP deviation, block-trade rate, exchange share, etc.) should
    NOT be trusted for tickers in trades_backfill provenance.

    `volume_sensitive_factors` lists factor names (as produced by
    factor_generator) that should be masked to NaN for trades_backfill
    tickers. Callers pass the set of backfill tickers (from BarStore
    provenance) and the generator nulls those cells.
    """

    volume_sensitive_factors: List[str] = Field(
        default_factory=lambda: [
            # Currently produced by factor_generator:
            "volume_surge_20d",
            "price_volume_div",
            # Extras from trades_scanner (not yet computed by factor_generator
            # but reserved for future):
            "vwap_deviation",
            "volume_weighted_skew",
            "large_trade_intensity",
            "exch_top1_volume_share",
            "buy_volume_proxy_ratio",
            "sell_volume_proxy_ratio",
            "block_trade_rate",
        ]
    )
    rationale: str = Field(
        default=("volume semantics unverified for trades_backfill tickers; "
                 "differs from stocks-only CSV source by ~20-50% at minute level")
    )


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

    sector_etfs:    List[str] = Field(default_factory=list)
    factor_etfs:    List[str] = Field(default_factory=list)
    cross_asset:    List[str] = Field(default_factory=list)
    macro_reference: List[str] = Field(default_factory=list)
    high_risk_symbols: HighRiskSymbolConfig = Field(default_factory=HighRiskSymbolConfig)
    liquidity: UniverseLiquidityConfig = Field(default_factory=UniverseLiquidityConfig)
    data_sensitivity: DataSensitivityConfig = Field(default_factory=DataSensitivityConfig)

    first_trade_dates: Dict[str, str] = Field(default_factory=dict)

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
