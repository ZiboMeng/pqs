"""
NYSE market calendar and timezone utilities.

Provides:
- is_trading_day()
- get_trading_days()
- get_session_close_et()         (handles half-day early closes)
- is_session_complete()          (refuses pre-close fetches)
- filter_to_market_hours()
- localize_to_eastern()
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Optional

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# US/Eastern timezone
_ET = "America/New_York"
_MARKET_OPEN  = pd.Timedelta(hours=9, minutes=30)
_MARKET_CLOSE = pd.Timedelta(hours=16, minutes=0)
_HALF_DAY_CLOSE = pd.Timedelta(hours=13, minutes=0)
# Buffer beyond official close to allow late tape settlement / yfinance
# vendor lag. Codex round 20 operational note: 15-30 min after 16:00 ET
# is the safest fetch window. We use 15 as the minimum.
_DEFAULT_POST_CLOSE_BUFFER_MIN = 15


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


def get_session_close_et(
    target_date: str | date | pd.Timestamp,
) -> Optional[pd.Timestamp]:
    """Return the ET-localized timestamp of NYSE session close for target_date.

    Handles half-day early closes (Black Friday, Christmas Eve, July 3 when
    July 4 is a regular weekday) automatically via pandas_market_calendars'
    schedule(). The ``market_close`` field returns 13:00 ET on early-close
    days and 16:00 ET on regular days.

    Returns None if target_date is not a trading day (weekend / holiday).

    Falls back to a hardcoded heuristic when pandas_market_calendars is
    not installed: regular weekdays close at 16:00 ET; weekend = None.
    The fallback does NOT detect half-day events.
    """
    target = pd.Timestamp(target_date).normalize()
    cal = _get_nyse_calendar()
    if cal is not None:
        schedule = cal.schedule(
            start_date=target.strftime("%Y-%m-%d"),
            end_date=target.strftime("%Y-%m-%d"),
        )
        if len(schedule) == 0:
            return None
        close_utc = schedule.iloc[0]["market_close"]
        # Convert to ET tz-aware
        return pd.Timestamp(close_utc).tz_convert(_ET)
    # Fallback: weekday → 16:00 ET, no half-day detection
    if target.weekday() >= 5:
        return None
    return target.tz_localize(_ET) + _MARKET_CLOSE


def is_session_complete(
    target_date: str | date | pd.Timestamp,
    *,
    now_utc: Optional[pd.Timestamp] = None,
    buffer_minutes: int = _DEFAULT_POST_CLOSE_BUFFER_MIN,
) -> bool:
    """Return True iff NYSE has closed for target_date as of now_utc.

    "Closed" means now_utc >= session_close_utc + buffer_minutes. The
    buffer (default 15 min) accounts for late-tape settlement and
    yfinance vendor lag — a fetch immediately at 16:00 ET often returns
    the same partial-close value the user observed at 15:55. Codex R20
    operational note recommends 15-30 minutes; 15 is the lower bound.

    Returns:
      True  — session has closed AND buffer elapsed; safe to fetch
              today's data and trust it as final.
      False — session not yet closed (or weekend / holiday). Caller
              should NOT fetch target_date's bar.

    Special cases:
      - target_date in the future → False (cannot be complete)
      - target_date is a non-trading day → True (no session to wait for;
        any "data for that date" must be a vendor anomaly, not partial)
      - target_date in the past (any prior trading day) → True

    Half-day handling: get_session_close_et() returns 13:00 ET on
    early-close days, so this function correctly treats Black Friday at
    13:30 ET as session-complete.
    """
    target = pd.Timestamp(target_date).normalize()
    now_utc = now_utc if now_utc is not None else pd.Timestamp.now(tz="UTC")
    if now_utc.tz is None:
        now_utc = now_utc.tz_localize("UTC")

    today_et = now_utc.tz_convert(_ET).normalize().tz_localize(None)
    if target > today_et:
        return False

    if target < today_et:
        # Past trading days: always considered complete. (We do not
        # validate "was a trading day" here — caller's responsibility.)
        return True

    # target == today (in ET)
    close_et = get_session_close_et(target)
    if close_et is None:
        # Today is a non-trading day (weekend / holiday).
        return True
    deadline = close_et + pd.Timedelta(minutes=buffer_minutes)
    return now_utc >= deadline.tz_convert("UTC")


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
    - If tz-aware: convert to US/Eastern FIRST (so the calendar date reflects
      the NYSE trading date), then strip timezone
    - Strip time component, keep date only
    - Name the index 'date'

    History: pre-2026-05-13 this function did `tz_localize(None)` without
    a prior tz_convert, which on tz-aware data caused the day to roll
    forward by +1 calendar day when the UTC time of the bar landed past
    midnight ET (e.g. yfinance UTC-midnight bars). This produced the
    off-by-one bug postmortem'd at
    docs/memos/20260513-spy_off_by_one_date_label_postmortem.md.
    """
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        # CRITICAL: convert to ET BEFORE stripping timezone, so the calendar
        # date matches the NYSE trading day. Pre-fix this was tz_localize(None)
        # which loses the timezone information and produces off-by-one labels
        # for UTC-midnight bars.
        idx = idx.tz_convert(_ET).tz_localize(None)
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
