"""
NYSE market calendar and timezone utilities.

Provides:
- is_trading_day()
- get_trading_days()
- filter_to_market_hours()
- localize_to_eastern()
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# US/Eastern timezone
_ET = "America/New_York"
_MARKET_OPEN  = pd.Timedelta(hours=9, minutes=30)
_MARKET_CLOSE = pd.Timedelta(hours=16, minutes=0)


@lru_cache(maxsize=4)
def _get_nyse_calendar():
    """Return NYSE calendar (cached; imports pandas_market_calendars lazily)."""
    try:
        import pandas_market_calendars as mcal
        return mcal.get_calendar("NYSE")
    except ImportError:
        logger.warning(
            "pandas_market_calendars not installed; falling back to weekday-only calendar. "
            "Install with: pip install pandas-market-calendars"
        )
        return None


def get_trading_days(
    start: str | date | pd.Timestamp,
    end:   str | date | pd.Timestamp,
) -> pd.DatetimeIndex:
    """
    Return NYSE trading days in [start, end] inclusive.

    Falls back to weekdays if pandas_market_calendars is unavailable.
    """
    start = pd.Timestamp(start).normalize()
    end   = pd.Timestamp(end).normalize()

    cal = _get_nyse_calendar()
    if cal is not None:
        schedule = cal.schedule(
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
        return pd.DatetimeIndex(schedule.index).normalize()

    # Fallback: Mon–Fri only (ignores US holidays)
    return pd.bdate_range(start=start, end=end)


def is_trading_day(dt: str | date | pd.Timestamp) -> bool:
    """Return True if dt is a NYSE trading day."""
    dt = pd.Timestamp(dt).normalize()
    days = get_trading_days(dt, dt)
    return len(days) > 0


def get_missing_trading_days(
    index: pd.DatetimeIndex,
    start: str | date | pd.Timestamp,
    end:   str | date | pd.Timestamp,
) -> pd.DatetimeIndex:
    """Return trading days in [start, end] that are absent from index."""
    expected = get_trading_days(start, end)
    present  = pd.DatetimeIndex(index).normalize()
    return expected.difference(present)


def localize_to_eastern(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """
    Ensure a DatetimeIndex is in US/Eastern.
    - If tz-aware: convert to ET.
    - If tz-naive: localize assuming UTC, then convert.
    """
    if index.tz is None:
        return index.tz_localize("UTC").tz_convert(_ET)
    return index.tz_convert(_ET)


def to_et_naive(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Convert to US/Eastern, then strip timezone (for consistent comparisons)."""
    return localize_to_eastern(index).tz_localize(None)


def filter_to_market_hours(
    df: pd.DataFrame,
    include_extended: bool = False,
) -> pd.DataFrame:
    """
    Filter an intraday DataFrame to regular market hours (9:30–16:00 ET).
    Assumes the index is already in ET (with or without tz).
    """
    if df.empty:
        return df

    idx = df.index
    if idx.tz is not None:
        idx_et = idx.tz_convert(_ET)
    else:
        idx_et = idx  # assume already ET

    time_of_day = idx_et.hour * 60 + idx_et.minute
    open_min  = 9 * 60 + 30   # 570
    close_min = 16 * 60        # 960

    if include_extended:
        # Pre-market 4:00, after-hours 20:00
        mask = (time_of_day >= 4 * 60) & (time_of_day < 20 * 60)
    else:
        mask = (time_of_day >= open_min) & (time_of_day < close_min)

    return df.loc[mask]


def align_daily_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise a daily OHLCV DataFrame:
    - Strip time component, keep date only
    - Remove timezone info
    - Name the index 'date'
    """
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    idx = idx.normalize()
    idx.name = "date"
    df = df.copy()
    df.index = idx
    return df.sort_index()


def align_intraday_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise an intraday OHLCV DataFrame:
    - Convert to US/Eastern tz-naive
    - Name the index 'datetime'
    """
    idx = pd.DatetimeIndex(df.index)
    idx = to_et_naive(idx)
    idx.name = "datetime"
    df = df.copy()
    df.index = idx
    return df.sort_index()
