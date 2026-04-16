"""core.data — market data providers, cache, calendar, and validation."""

from core.data.calendar import (
    get_trading_days,
    is_trading_day,
    get_missing_trading_days,
    localize_to_eastern,
    to_et_naive,
    filter_to_market_hours,
    align_daily_index,
    align_intraday_index,
)
from core.data.provider import DataProvider, OHLCVFrame, OHLCV_COLS
from core.data.yfinance_provider import YFinanceProvider
from core.data.market_data_store import MarketDataStore
from core.data.validator import DataValidator, ValidationResult

__all__ = [
    # Calendar
    "get_trading_days", "is_trading_day", "get_missing_trading_days",
    "localize_to_eastern", "to_et_naive", "filter_to_market_hours",
    "align_daily_index", "align_intraday_index",
    # Provider
    "DataProvider", "OHLCVFrame", "OHLCV_COLS",
    "YFinanceProvider",
    # Cache
    "MarketDataStore",
    # Validation
    "DataValidator", "ValidationResult",
]
