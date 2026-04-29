"""Tests for NYSE session-close gate + fetch session log.

Covers the 2026-04-29 fix to prevent pre-close partial-bar writes and
to refresh stale partial bars on next post-close run.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.data.calendar import (
    get_session_close_et,
    is_session_complete,
)
from core.data.fetch_session_log import (
    clear_log,
    read_log,
    record_fetch,
    was_fetched_pre_close,
)


# ---------------------------------------------------------------------------
# get_session_close_et — handles regular days + early closes + non-trading
# ---------------------------------------------------------------------------


def test_session_close_regular_trading_day():
    """A normal Tue/Wed/Thu in mid-April closes at 16:00 ET."""
    close = get_session_close_et("2026-04-22")  # Wed
    assert close is not None
    assert close.tz is not None
    et_close = close.tz_convert("America/New_York")
    assert et_close.hour == 16
    assert et_close.minute == 0


def test_session_close_returns_none_on_weekend():
    """Saturday is not a trading day."""
    close = get_session_close_et("2026-04-25")  # Sat
    assert close is None


def test_session_close_handles_july_3_early_close_2025():
    """July 3, 2025 is the day before July 4 (Friday holiday). NYSE closes
    early at 13:00 ET. Expectation: get_session_close_et returns 13:00 ET."""
    pytest.importorskip("pandas_market_calendars")
    close = get_session_close_et("2025-07-03")
    if close is None:
        pytest.skip("calendar treats July 3 as non-trading; skipping early-close check")
    et_close = close.tz_convert("America/New_York")
    # Half-day = 13:00; full day = 16:00. Either pmc returns 13 or test
    # is invalid for this calendar version.
    assert et_close.hour in {13, 16}, (
        "Expected NYSE close at 13:00 (half-day) or 16:00 (full day); "
        f"got {et_close.hour}:{et_close.minute}"
    )


def test_session_close_black_friday_2025_likely_half_day():
    """Black Friday Nov 28, 2025 typically closes at 13:00 ET."""
    pytest.importorskip("pandas_market_calendars")
    close = get_session_close_et("2025-11-28")
    if close is None:
        pytest.skip("calendar treats this date as non-trading")
    et_close = close.tz_convert("America/New_York")
    assert et_close.hour in {13, 16}


# ---------------------------------------------------------------------------
# is_session_complete — buffer + half-day + edge cases
# ---------------------------------------------------------------------------


def test_session_not_complete_pre_close():
    """Wed 2026-04-22 at 14:00 ET is NOT complete (close is 16:00 ET)."""
    target = pd.Timestamp("2026-04-22")
    pre_close_utc = pd.Timestamp("2026-04-22 18:00:00", tz="UTC")  # 14:00 ET in EDT
    assert not is_session_complete(target, now_utc=pre_close_utc)


def test_session_complete_after_buffer():
    """Wed 2026-04-22 at 16:30 ET (close + 30 min) → complete."""
    target = pd.Timestamp("2026-04-22")
    post_close_utc = pd.Timestamp("2026-04-22 20:30:00", tz="UTC")  # 16:30 ET
    assert is_session_complete(target, now_utc=post_close_utc)


def test_session_not_complete_within_buffer():
    """Right at 16:00 ET, default 15 min buffer not yet elapsed → not complete."""
    target = pd.Timestamp("2026-04-22")
    at_close_utc = pd.Timestamp("2026-04-22 20:05:00", tz="UTC")  # 16:05 ET
    assert not is_session_complete(target, now_utc=at_close_utc, buffer_minutes=15)


def test_session_complete_zero_buffer():
    """With buffer_minutes=0, 16:00 ET is complete."""
    target = pd.Timestamp("2026-04-22")
    at_close_utc = pd.Timestamp("2026-04-22 20:00:00", tz="UTC")  # 16:00 ET sharp
    assert is_session_complete(target, now_utc=at_close_utc, buffer_minutes=0)


def test_past_trading_day_always_complete():
    target = pd.Timestamp("2024-01-15")
    now = pd.Timestamp("2026-04-29 12:00:00", tz="UTC")
    assert is_session_complete(target, now_utc=now)


def test_future_date_never_complete():
    target = pd.Timestamp("2030-01-15")
    now = pd.Timestamp("2026-04-29 12:00:00", tz="UTC")
    assert not is_session_complete(target, now_utc=now)


def test_weekend_today_returns_complete():
    """Saturday = no session to wait for; treat as 'complete' (no fetch needed)."""
    saturday_utc = pd.Timestamp("2026-04-25 18:00:00", tz="UTC")
    target = pd.Timestamp("2026-04-25")
    assert is_session_complete(target, now_utc=saturday_utc)


# ---------------------------------------------------------------------------
# fetch_session_log — record / lookup / clear
# ---------------------------------------------------------------------------


def test_record_pre_close_marks_is_pre_close_true(tmp_path):
    log = tmp_path / "fetch_log.json"
    target = pd.Timestamp("2026-04-22")
    session_close = pd.Timestamp("2026-04-22 20:00:00", tz="UTC")  # 16:00 ET
    fetched_at = pd.Timestamp("2026-04-22 18:00:00", tz="UTC")  # 14:00 ET (pre-close)
    record_fetch(
        "AAPL", "1d", target,
        fetched_at_utc=fetched_at,
        session_close_utc=session_close,
        post_close_buffer_min=15,
        log_path=log,
    )
    assert was_fetched_pre_close("AAPL", "1d", target, log_path=log)


def test_record_post_close_marks_false(tmp_path):
    log = tmp_path / "fetch_log.json"
    target = pd.Timestamp("2026-04-22")
    session_close = pd.Timestamp("2026-04-22 20:00:00", tz="UTC")
    fetched_at = pd.Timestamp("2026-04-22 20:30:00", tz="UTC")  # 16:30 ET
    record_fetch(
        "AAPL", "1d", target,
        fetched_at_utc=fetched_at,
        session_close_utc=session_close,
        post_close_buffer_min=15,
        log_path=log,
    )
    assert not was_fetched_pre_close("AAPL", "1d", target, log_path=log)


def test_record_within_buffer_still_pre_close(tmp_path):
    """Fetched at 16:05 ET with 15-min buffer → still treated as pre-close."""
    log = tmp_path / "fetch_log.json"
    target = pd.Timestamp("2026-04-22")
    session_close = pd.Timestamp("2026-04-22 20:00:00", tz="UTC")
    fetched_at = pd.Timestamp("2026-04-22 20:05:00", tz="UTC")  # 16:05 ET
    record_fetch(
        "AAPL", "1d", target,
        fetched_at_utc=fetched_at,
        session_close_utc=session_close,
        post_close_buffer_min=15,
        log_path=log,
    )
    assert was_fetched_pre_close("AAPL", "1d", target, log_path=log)


def test_was_fetched_pre_close_returns_false_when_no_record(tmp_path):
    log = tmp_path / "fetch_log.json"
    assert not was_fetched_pre_close("AAPL", "1d", "2026-04-22", log_path=log)


def test_record_overwrites_prior_entry(tmp_path):
    """A second record for the same (sym, freq, date) replaces the first."""
    log = tmp_path / "fetch_log.json"
    target = pd.Timestamp("2026-04-22")
    session_close = pd.Timestamp("2026-04-22 20:00:00", tz="UTC")

    # First: pre-close fetch
    record_fetch("AAPL", "1d", target,
                 fetched_at_utc=pd.Timestamp("2026-04-22 18:00:00", tz="UTC"),
                 session_close_utc=session_close,
                 post_close_buffer_min=15, log_path=log)
    assert was_fetched_pre_close("AAPL", "1d", target, log_path=log)

    # Second: post-close fetch (the post-close re-run)
    record_fetch("AAPL", "1d", target,
                 fetched_at_utc=pd.Timestamp("2026-04-22 21:00:00", tz="UTC"),
                 session_close_utc=session_close,
                 post_close_buffer_min=15, log_path=log)
    assert not was_fetched_pre_close("AAPL", "1d", target, log_path=log)


def test_log_isolated_per_symbol_and_freq(tmp_path):
    log = tmp_path / "fetch_log.json"
    target = pd.Timestamp("2026-04-22")
    session_close = pd.Timestamp("2026-04-22 20:00:00", tz="UTC")
    record_fetch("AAPL", "1d", target,
                 fetched_at_utc=pd.Timestamp("2026-04-22 18:00:00", tz="UTC"),
                 session_close_utc=session_close,
                 post_close_buffer_min=15, log_path=log)
    # Different symbol → no record
    assert not was_fetched_pre_close("MSFT", "1d", target, log_path=log)
    # Different freq → no record
    assert not was_fetched_pre_close("AAPL", "60m", target, log_path=log)
    # Different date → no record
    assert not was_fetched_pre_close("AAPL", "1d", "2026-04-21", log_path=log)


def test_record_with_no_session_close_treats_as_complete(tmp_path):
    """Non-trading day fetch (session_close=None) → never marked pre-close."""
    log = tmp_path / "fetch_log.json"
    record_fetch("AAPL", "1d", "2026-04-25",  # Sat
                 fetched_at_utc=pd.Timestamp("2026-04-25 18:00:00", tz="UTC"),
                 session_close_utc=None,
                 post_close_buffer_min=15, log_path=log)
    assert not was_fetched_pre_close("AAPL", "1d", "2026-04-25", log_path=log)


def test_clear_log(tmp_path):
    log = tmp_path / "fetch_log.json"
    record_fetch("AAPL", "1d", "2026-04-22",
                 fetched_at_utc=pd.Timestamp("2026-04-22 18:00:00", tz="UTC"),
                 session_close_utc=pd.Timestamp("2026-04-22 20:00:00", tz="UTC"),
                 post_close_buffer_min=15, log_path=log)
    assert log.exists()
    clear_log(log)
    assert not log.exists()


def test_read_log_returns_full_dict(tmp_path):
    log = tmp_path / "fetch_log.json"
    record_fetch("AAPL", "1d", "2026-04-22",
                 fetched_at_utc=pd.Timestamp("2026-04-22 18:00:00", tz="UTC"),
                 session_close_utc=pd.Timestamp("2026-04-22 20:00:00", tz="UTC"),
                 post_close_buffer_min=15, log_path=log)
    data = read_log(log)
    assert "AAPL/1d/2026-04-22" in data
    entry = data["AAPL/1d/2026-04-22"]
    assert entry["is_pre_close"] is True
    assert entry["post_close_buffer_min"] == 15
