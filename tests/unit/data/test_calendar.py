"""
Unit tests for core.data.calendar.

Tests use known NYSE market dates so that results are deterministic
regardless of when they are run.
"""

import pandas as pd
import pytest

from core.data.calendar import (
    align_daily_index,
    align_intraday_index,
    filter_to_market_hours,
    get_missing_trading_days,
    get_trading_days,
    is_trading_day,
    localize_to_eastern,
    to_et_naive,
)


# ── get_trading_days ──────────────────────────────────────────────────────────

class TestGetTradingDays:
    def test_single_trading_day(self):
        days = get_trading_days("2024-01-02", "2024-01-02")
        assert len(days) == 1
        assert pd.Timestamp("2024-01-02") in days

    def test_excludes_weekends(self):
        # Week of 2024-01-01 (Mon holiday): Tue–Fri = 4 trading days
        days = get_trading_days("2024-01-02", "2024-01-05")
        for d in days:
            assert d.dayofweek < 5, f"{d} is a weekend"

    def test_new_years_holiday(self):
        # 2024-01-01 is New Year's Day — not a trading day
        days = get_trading_days("2024-01-01", "2024-01-01")
        assert len(days) == 0

    def test_thanksgiving_2023(self):
        # 2023-11-23 Thanksgiving: not trading
        days = get_trading_days("2023-11-23", "2023-11-23")
        assert len(days) == 0

    def test_returns_datetime_index(self):
        days = get_trading_days("2024-01-02", "2024-01-05")
        assert isinstance(days, pd.DatetimeIndex)

    def test_start_equals_end_non_trading(self):
        days = get_trading_days("2024-01-06", "2024-01-06")  # Saturday
        assert len(days) == 0


# ── is_trading_day ────────────────────────────────────────────────────────────

class TestIsTradingDay:
    def test_regular_weekday(self):
        assert is_trading_day("2024-01-02") is True

    def test_weekend(self):
        assert is_trading_day("2024-01-06") is False  # Saturday

    def test_holiday(self):
        assert is_trading_day("2024-01-01") is False  # New Year's


# ── get_missing_trading_days ──────────────────────────────────────────────────

class TestGetMissingTradingDays:
    def test_no_missing_days(self):
        days = get_trading_days("2024-01-02", "2024-01-05")
        missing = get_missing_trading_days(days, "2024-01-02", "2024-01-05")
        assert len(missing) == 0

    def test_one_missing_day(self):
        days = get_trading_days("2024-01-02", "2024-01-05")
        # Remove the first day
        trimmed = days[1:]
        missing = get_missing_trading_days(trimmed, "2024-01-02", "2024-01-05")
        assert len(missing) == 1
        assert pd.Timestamp("2024-01-02") in missing

    def test_all_missing(self):
        empty_idx = pd.DatetimeIndex([])
        missing = get_missing_trading_days(empty_idx, "2024-01-02", "2024-01-05")
        # Should equal the full trading day set for that range
        expected = get_trading_days("2024-01-02", "2024-01-05")
        assert len(missing) == len(expected)


# ── filter_to_market_hours ────────────────────────────────────────────────────

class TestFilterToMarketHours:
    def _make_intraday(self, times):
        """Build a tiny DataFrame with the given time strings on 2024-01-02."""
        idx = pd.DatetimeIndex(
            [pd.Timestamp(f"2024-01-02 {t}") for t in times]
        )
        df = pd.DataFrame({"close": 1.0}, index=idx)
        return df

    def test_keeps_market_hours(self):
        df = self._make_intraday(["09:30", "12:00", "15:59"])
        out = filter_to_market_hours(df)
        assert len(out) == 3

    def test_removes_pre_market(self):
        df = self._make_intraday(["08:00", "09:29", "09:30"])
        out = filter_to_market_hours(df)
        assert len(out) == 1  # only 09:30

    def test_removes_after_hours(self):
        df = self._make_intraday(["15:59", "16:00", "17:00"])
        out = filter_to_market_hours(df)
        assert len(out) == 1  # only 15:59

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame()
        out = filter_to_market_hours(df)
        assert out.empty


# ── align_daily_index ─────────────────────────────────────────────────────────

class TestAlignDailyIndex:
    def test_strips_time_component(self):
        idx = pd.DatetimeIndex(["2024-01-02 00:00:00", "2024-01-03 16:00:00"])
        df = pd.DataFrame({"close": [1, 2]}, index=idx)
        out = align_daily_index(df)
        for ts in out.index:
            assert ts.hour == 0 and ts.minute == 0

    def test_removes_tz(self):
        idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], tz="UTC")
        df = pd.DataFrame({"close": [1, 2]}, index=idx)
        out = align_daily_index(df)
        assert out.index.tz is None

    def test_index_named_date(self):
        idx = pd.DatetimeIndex(["2024-01-02"])
        df = pd.DataFrame({"close": [1]}, index=idx)
        out = align_daily_index(df)
        assert out.index.name == "date"

    def test_sorted(self):
        idx = pd.DatetimeIndex(["2024-01-05", "2024-01-02", "2024-01-03"])
        df = pd.DataFrame({"close": [3, 1, 2]}, index=idx)
        out = align_daily_index(df)
        assert out.index.is_monotonic_increasing


# ── align_intraday_index ──────────────────────────────────────────────────────

class TestAlignIntradayIndex:
    def test_converts_utc_to_et_naive(self):
        # 2024-01-02 14:30 UTC = 09:30 ET
        idx = pd.DatetimeIndex(["2024-01-02 14:30:00"], tz="UTC")
        df = pd.DataFrame({"close": [1]}, index=idx)
        out = align_intraday_index(df)
        assert out.index.tz is None
        assert out.index[0].hour == 9
        assert out.index[0].minute == 30

    def test_index_named_datetime(self):
        idx = pd.DatetimeIndex(["2024-01-02 14:30:00"], tz="UTC")
        df = pd.DataFrame({"close": [1]}, index=idx)
        out = align_intraday_index(df)
        assert out.index.name == "datetime"
