"""Backtest and intraday configuration schemas."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from datetime import date


class WindowAnalysisConfig(BaseModel):
    """Walk-forward and rolling window backtest settings."""

    enabled: bool = True
    warmup_bars: int = Field(default=252, ge=60)     # bars before first valid window
    rolling_window_bars: int = Field(default=504, ge=120)   # 2 years
    rolling_step_bars: int = Field(default=63, ge=10)       # 3 months
    expanding_min_bars: int = Field(default=252, ge=60)
    walk_forward_train_bars: int = Field(default=756, ge=120)  # 3 years
    walk_forward_test_bars: int = Field(default=126, ge=21)    # 6 months
    forward_block_holdout_bars: int = Field(default=252, ge=60)  # 1 year

    @model_validator(mode="after")
    def train_gt_test(self) -> "WindowAnalysisConfig":
        if self.walk_forward_train_bars <= self.walk_forward_test_bars:
            raise ValueError("walk_forward_train_bars must be > walk_forward_test_bars")
        return self


class CostLeakageCheckConfig(BaseModel):
    """Settings for detecting look-ahead bias in backtests."""

    enabled: bool = True
    check_signal_uses_future: bool = True
    check_fill_price_valid: bool = True


class MultiTimeframeConfig(BaseModel):
    """Multi-timeframe auxiliary data configuration for intraday."""

    enabled: bool = True
    aux_freqs: List[str] = Field(default=["30m", "15m", "5m"])
    graceful_degradation: bool = True  # proceed without aux data if unavailable
    min_history_days: Dict[str, int] = Field(
        default={"5m": 20, "15m": 20, "30m": 20}
    )
    lookback_bars: Dict[str, int] = Field(
        default={"30m": 8, "15m": 16, "5m": 24}
    )
    timeframe_weights: Dict[str, float] = Field(
        default={"30m": 0.50, "15m": 0.35, "5m": 0.15}
    )


class ConfluenceFilterConfig(BaseModel):
    """Multi-timeframe confluence filter settings."""

    enabled: bool = True
    min_threshold: float = Field(default=0.60, ge=0, le=1.0)
    weak_threshold: float = Field(default=0.60, ge=0, le=1.0)
    strong_threshold: float = Field(default=0.80, ge=0, le=1.0)

    @model_validator(mode="after")
    def thresholds_valid(self) -> "ConfluenceFilterConfig":
        if self.weak_threshold > self.strong_threshold:
            raise ValueError("weak_threshold must be <= strong_threshold")
        if self.min_threshold > self.weak_threshold:
            raise ValueError("min_threshold must be <= weak_threshold")
        return self


class IntradayConfig(BaseModel):
    """Intraday-specific backtest and paper-trading configuration."""

    primary_freq: str = Field(default="60m", pattern="^(30m|60m)$")
    position_allow_overnight: bool = False
    eod_force_close: bool = True
    eod_slippage_multiplier: float = Field(default=1.5, ge=1.0, le=5.0)

    avoid_first_bar: bool = True
    avoid_last_n_bars: int = Field(default=1, ge=0)
    min_tradeable_bars_per_day: int = Field(default=3, ge=1)

    # Paper trading simulation mode
    paper_trading_mode: str = Field(
        default="eod_simulation",
        pattern="^(eod_simulation|intraday_polling)$"
    )
    polling_interval_minutes: int = Field(default=60, ge=5)

    intraday_uses_interday_regime: bool = True
    intraday_max_position_pct: float = Field(default=0.50, ge=0, le=1.0)

    multi_timeframe: MultiTimeframeConfig = Field(default_factory=MultiTimeframeConfig)
    confluence_filter: ConfluenceFilterConfig = Field(default_factory=ConfluenceFilterConfig)


class BacktestConfig(BaseModel):
    """Top-level backtest configuration."""

    start_date_override: Optional[date] = None
    end_date_override: Optional[date] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    benchmarks: List[str] = Field(default=["SPY", "QQQ"])
    primary_benchmark: str = "SPY"
    mining: Optional[Dict[str, Any]] = None

    window_analysis: WindowAnalysisConfig = Field(default_factory=WindowAnalysisConfig)
    leakage_check: CostLeakageCheckConfig = Field(default_factory=CostLeakageCheckConfig)
    intraday: IntradayConfig = Field(default_factory=IntradayConfig)
