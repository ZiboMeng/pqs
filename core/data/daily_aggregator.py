"""
1m -> daily aggregator (data-integrity round-3 step 1).

Canonical contract per docs/memos/20260425-data_integrity_round3_implementation_note.md:

  * Input: 1m bars (per symbol) with ET-naive `DatetimeIndex` and
    OHLCV columns. The 1m parquet store at data/intraday/1m/ already
    matches this convention (verified round-2 §2.4.2).
  * Output (daily_df):
      - index = real ET trading day (no shift, no Sat/Sun rows)
      - columns = open / high / low / close / volume / partial_day
      - close      = bar at 15:59 ET (regular session last minute)
                     OR bar at canonical_close_at on partial-day NYSE
                     half-sessions (whitelist driven)
      - open       = bar at 09:30 ET
      - high/low   = max/min over [09:30, 15:59] ET regular session
      - volume     = sum over [09:30, 15:59] ET regular session
      - partial_day = True only on NYSE half-session days
  * Output (audit_df): one row per quarantined incomplete day —
    NEVER silently filled. Carries reason / n_bars / first/last 1m ts.
  * Adjustment: aggregator outputs RAW (no split cascade). Cascade
    is read-time via splits.parquet at BarStore.load(adjusted=True).

This module does NOT touch the daily parquet store. Its callers
decide whether to overwrite, append, or stage. Step 1 of round-3
ships the aggregator + unit tests only; step 3 will use it to
rebuild data/intraday/1m derivatives.
"""

from __future__ import annotations

from typing import Iterable, Optional, Set, Tuple

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# Regular trading session (ET-naive)
_RT_OPEN = pd.Timedelta(hours=9, minutes=30)
_RT_CLOSE_FULL = pd.Timedelta(hours=15, minutes=59)  # last full-session 1m bar
_RT_CLOSE_HALF = pd.Timedelta(hours=12, minutes=59)  # last half-session 1m bar
                                                      # (NYSE half-day closes 13:00 ET)

# Two-tier bar-count thresholds for full sessions (09:30..15:59 = 390 min):
#   n_bars >= _DEFAULT_N_MIN_COMPLETE (350, ~90%): "complete"
#   _DEFAULT_N_MIN_THIN <= n_bars < _DEFAULT_N_MIN_COMPLETE: "thin_data" —
#       still written, flagged as thin_data=True in the sidecar
#   n_bars < _DEFAULT_N_MIN_THIN (300, ~77%): quarantined
# Half-session days (NYSE half-day whitelist) bypass the n_bars
# threshold entirely; they expect ~210 bars and are accepted on
# the strength of the whitelist.
_DEFAULT_N_MIN_COMPLETE = 350
_DEFAULT_N_MIN_THIN = 300


def _half_session_days_from_calendar(
    start: pd.Timestamp, end: pd.Timestamp,
) -> Set[pd.Timestamp]:
    """
    NYSE half-session whitelist between [start, end] inclusive,
    derived dynamically from `pandas_market_calendars` schedule.

    A day is half-session iff its ET market_close hour ≠ 16. The
    standard half-session close is 13:00 ET. Comparing in **ET**, not
    UTC, is critical: NYSE close in UTC shifts between 21:00 (winter,
    EST) and 20:00 (summer, EDT) due to daylight saving time, so a
    naive UTC compare to "21:00 UTC" mislabels every DST-summer day
    as half-session.

    Returns a set of normalized ET-naive timestamps.
    """
    try:
        import pandas_market_calendars as mcal
    except ImportError:
        logger.warning(
            "pandas_market_calendars not installed; half-session "
            "whitelist will be empty. Install with "
            "`pip install pandas-market-calendars`."
        )
        return set()
    cal = mcal.get_calendar("NYSE")
    sched = cal.schedule(
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )
    if sched.empty:
        return set()
    # Convert market_close to America/New_York then check the local
    # clock. Standard NYSE close hour in ET is 16; half-day is 13.
    close_et = sched["market_close"].dt.tz_convert("America/New_York")
    half_mask = close_et.dt.hour != 16
    half_days = sched.index[half_mask]
    return {pd.Timestamp(d).normalize() for d in half_days}


def aggregate_1m_to_daily(
    bars_1m: pd.DataFrame,
    *,
    n_min_threshold: int = _DEFAULT_N_MIN_COMPLETE,
    n_min_thin_threshold: int = _DEFAULT_N_MIN_THIN,
    partial_day_whitelist: Optional[Iterable[pd.Timestamp]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Aggregate 1m bars into daily OHLCV per the round-3 contract.

    Parameters
    ----------
    bars_1m : pd.DataFrame
        ET-naive `DatetimeIndex` (no timezone). Required columns:
        open, high, low, close, volume.
    n_min_threshold : int, default 350
        Minimum regular-session 1m bar count for a full-session day
        to be flagged as "complete" (`thin_data=False`).
    n_min_thin_threshold : int, default 300
        Lower bound for "thin_data accepted" rows. Days with
        `n_min_thin_threshold <= n_bars < n_min_threshold` AND both
        endpoint bars present are accepted into daily_df with
        `thin_data=True` flagged in a sidecar column. Days with
        `n_bars < n_min_thin_threshold` (or missing 09:30 / 15:59
        anchor) are QUARANTINED into audit_df. NO silent fallback
        to a different source.
    partial_day_whitelist : iterable of Timestamp, optional
        Set of dates known to be NYSE half-sessions. If None, the
        whitelist is derived dynamically from `pandas_market_calendars`
        over the input range.

    Returns
    -------
    daily_df : pd.DataFrame
        Index = real ET trading day (no Sat/Sun, no offset).
        Columns: open, high, low, close, volume, partial_day, thin_data.
        - partial_day=True only on NYSE half-session days.
        - thin_data=True only on full-session days with bar count
          between [n_min_thin_threshold, n_min_threshold).
    audit_df : pd.DataFrame
        Quarantined incomplete days. Columns: reason, n_bars,
        first_bar_ts, last_bar_ts. Empty if no incomplete days.
    """
    if bars_1m.empty:
        return _empty_daily(), _empty_audit()

    if not isinstance(bars_1m.index, pd.DatetimeIndex):
        raise TypeError(
            f"bars_1m must have DatetimeIndex; got {type(bars_1m.index).__name__}"
        )
    if bars_1m.index.tz is not None:
        raise ValueError(
            "bars_1m must be tz-naive ET. Strip timezone before calling."
        )

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(bars_1m.columns)
    if missing:
        raise ValueError(f"bars_1m missing required columns: {sorted(missing)}")

    # Compute time-of-day mask once
    tod = bars_1m.index.normalize()
    minute_of_day = (
        bars_1m.index.hour.astype("int64") * 60
        + bars_1m.index.minute.astype("int64")
    )
    rt_open_min = 9 * 60 + 30   # 570
    rt_close_min_full = 15 * 60 + 59  # 959 (last bar inclusive)
    # Regular session 09:30 .. 15:59 inclusive = full-session window
    rt_mask_full = (minute_of_day >= rt_open_min) & (minute_of_day <= rt_close_min_full)

    if partial_day_whitelist is None:
        date_min = bars_1m.index.normalize().min()
        date_max = bars_1m.index.normalize().max()
        whitelist_set = _half_session_days_from_calendar(date_min, date_max)
    else:
        whitelist_set = {pd.Timestamp(d).normalize() for d in partial_day_whitelist}

    # Group by date
    rows_daily: list = []
    rows_audit: list = []

    for day, day_bars in bars_1m.groupby(tod, sort=True):
        is_partial_known = pd.Timestamp(day) in whitelist_set
        # Choose canonical close minute
        if is_partial_known:
            close_minute = 12 * 60 + 59  # 13:00 ET half-day → last RT bar = 12:59
            # On half-days the RT window is 09:30 .. 12:59
            rt_mask_day = (
                (day_bars.index.hour * 60 + day_bars.index.minute >= rt_open_min)
                & (day_bars.index.hour * 60 + day_bars.index.minute <= close_minute)
            )
            n_min_required = 0  # half-day: don't apply full-session threshold
        else:
            close_minute = rt_close_min_full
            rt_mask_day = (
                (day_bars.index.hour * 60 + day_bars.index.minute >= rt_open_min)
                & (day_bars.index.hour * 60 + day_bars.index.minute <= close_minute)
            )
            n_min_required = n_min_threshold

        rt_bars = day_bars.loc[rt_mask_day]
        n_bars = int(len(rt_bars))

        # Mandatory anchor bars: 09:30 open and the canonical close minute
        open_bar = rt_bars[
            (rt_bars.index.hour == 9) & (rt_bars.index.minute == 30)
        ]
        close_bar = rt_bars[
            (rt_bars.index.hour * 60 + rt_bars.index.minute) == close_minute
        ]

        if open_bar.empty:
            rows_audit.append({
                "date": pd.Timestamp(day),
                "reason": "missing_0930_open",
                "n_bars": n_bars,
                "first_bar_ts": rt_bars.index.min() if n_bars else pd.NaT,
                "last_bar_ts": rt_bars.index.max() if n_bars else pd.NaT,
                "partial_day_whitelisted": is_partial_known,
            })
            continue
        if close_bar.empty:
            rows_audit.append({
                "date": pd.Timestamp(day),
                "reason": (
                    "missing_1259_close" if is_partial_known else "missing_1559_close"
                ),
                "n_bars": n_bars,
                "first_bar_ts": rt_bars.index.min() if n_bars else pd.NaT,
                "last_bar_ts": rt_bars.index.max() if n_bars else pd.NaT,
                "partial_day_whitelisted": is_partial_known,
            })
            continue
        # Full-session two-tier classification (half-days bypass).
        # n_bars >= n_min_threshold       → complete (thin_data=False)
        # n_min_thin <= n_bars < n_min   → thin_data accepted (thin_data=True)
        # n_bars < n_min_thin             → quarantine
        if not is_partial_known:
            if n_bars < n_min_thin_threshold:
                rows_audit.append({
                    "date": pd.Timestamp(day),
                    "reason": f"low_bar_count<{n_min_thin_threshold}",
                    "n_bars": n_bars,
                    "first_bar_ts": rt_bars.index.min(),
                    "last_bar_ts": rt_bars.index.max(),
                    "partial_day_whitelisted": False,
                })
                continue
            thin_data_flag = n_bars < n_min_threshold
        else:
            thin_data_flag = False  # half-day, by-whitelist accepted

        rows_daily.append({
            "date": pd.Timestamp(day),
            "open": float(open_bar["open"].iloc[0]),
            "high": float(rt_bars["high"].max()),
            "low": float(rt_bars["low"].min()),
            "close": float(close_bar["close"].iloc[0]),
            "volume": float(rt_bars["volume"].sum()),
            "partial_day": is_partial_known,
            "thin_data": thin_data_flag,
        })

    if not rows_daily:
        daily_df = _empty_daily()
    else:
        daily_df = pd.DataFrame(rows_daily).set_index("date").sort_index()
        daily_df.index.name = "date"

    if not rows_audit:
        audit_df = _empty_audit()
    else:
        audit_df = pd.DataFrame(rows_audit).set_index("date").sort_index()
        audit_df.index.name = "date"

    return daily_df, audit_df


def _empty_daily() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["open", "high", "low", "close", "volume", "partial_day",
                 "thin_data"],
        index=pd.DatetimeIndex([], name="date"),
    )


def _empty_audit() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "reason", "n_bars", "first_bar_ts", "last_bar_ts",
            "partial_day_whitelisted",
        ],
        index=pd.DatetimeIndex([], name="date"),
    )


__all__ = ["aggregate_1m_to_daily"]
