"""
Smoke tests for the 1m -> daily aggregator against REAL polygon 1m data.

These spot-check that the aggregator produces sensible output when
fed the actual store contents. They are NOT exhaustive (full
correctness lives in `test_daily_aggregator.py` against synthetic
fixtures); they only verify that the contract holds when wired to
the real BarStore 1m parquet — i.e. that no schema / timezone /
column-name mismatch sneaks past the synthetic tests.

These tests skip cleanly if the 1m parquet for any required symbol
is absent.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.data.bar_store import BarStore
from core.data.daily_aggregator import aggregate_1m_to_daily


def _load_real_1m(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Load real 1m bars from BarStore (RAW) and verify schema."""
    bs = BarStore()
    df = bs.load(
        symbol, "1m",
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        adjusted=False,
    )
    if df is None or df.empty:
        pytest.skip(f"no 1m data for {symbol} {start}..{end}")
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def test_smoke_AAPL_2022_aggregator_emits_real_dates():
    """AAPL 2022-08-22..2022-09-02: aggregator output indexed at real
    ET trading days (no Sat, no +1d shift)."""
    bars = _load_real_1m("AAPL", "2022-08-22", "2022-09-03")
    daily, audit = aggregate_1m_to_daily(bars)

    expected_real_dates = {
        pd.Timestamp("2022-08-22"),  # Mon — was MISSING from BS daily
        pd.Timestamp("2022-08-23"),
        pd.Timestamp("2022-08-24"),
        pd.Timestamp("2022-08-25"),
        pd.Timestamp("2022-08-26"),
        pd.Timestamp("2022-08-29"),  # Mon — was MISSING from BS daily
        pd.Timestamp("2022-08-30"),
        pd.Timestamp("2022-08-31"),
        pd.Timestamp("2022-09-01"),
        pd.Timestamp("2022-09-02"),
    }
    actual = set(daily.index)
    missing = expected_real_dates - actual
    assert not missing, (
        f"expected real Mondays / weekdays missing from aggregator output: {missing}\n"
        f"audit reasons: {audit['reason'].to_dict() if not audit.empty else {}}"
    )
    # No Sat
    assert pd.Timestamp("2022-08-27") not in actual
    assert pd.Timestamp("2022-09-03") not in actual


def test_smoke_AAPL_close_matches_known_real_value():
    """AAPL 2022-08-29 (Mon) real close ≈ 161.38 (post-2020-split scale).
    Aggregator uses 15:59 ET 1m bar → should match within 50 bps."""
    bars = _load_real_1m("AAPL", "2022-08-29", "2022-08-30")
    daily, _ = aggregate_1m_to_daily(bars)
    if pd.Timestamp("2022-08-29") not in daily.index:
        pytest.skip("AAPL 2022-08-29 not in aggregator output (likely incomplete 1m)")
    aggregated_close = float(daily.loc[pd.Timestamp("2022-08-29"), "close"])
    real_known_close = 161.38  # AAPL 2022-08-29 post-2020-split scale
    rel_err = abs(aggregated_close - real_known_close) / real_known_close
    assert rel_err < 0.005, (
        f"AAPL 2022-08-29 aggregated close {aggregated_close} differs "
        f"from known real close {real_known_close} by {rel_err:.2%}"
    )


def test_smoke_no_weekend_rows_universe():
    """Run the aggregator across a small universe over 1 month and
    verify no Sat/Sun rows appear in the output."""
    syms = ["AAPL", "MSFT", "SPY", "QQQ", "DG"]
    for sym in syms:
        bars = _load_real_1m(sym, "2024-01-02", "2024-01-31")
        daily, _ = aggregate_1m_to_daily(bars)
        weekend = daily.index[daily.index.weekday >= 5]
        assert len(weekend) == 0, (
            f"{sym}: weekend rows found in aggregator output: {weekend.tolist()}"
        )


def test_smoke_aggregator_label_no_offset_real_data():
    """Real-data version of test_no_plus_one_day_label_offset: verify
    the aggregator does NOT emit any row at 2022-08-27 (Sat) — the
    historical BS daily store had this row, but it was a bug."""
    bars = _load_real_1m("SPY", "2022-08-22", "2022-09-03")
    daily, _ = aggregate_1m_to_daily(bars)
    assert pd.Timestamp("2022-08-27") not in daily.index
    assert pd.Timestamp("2022-08-29") in daily.index  # the real Mon


def test_smoke_audit_log_captures_low_bar_days():
    """Real-data: when 1m for a date has substantially fewer bars
    than threshold (e.g. partial-day before 2024-07-04), aggregator
    quarantines it into audit if not on the half-day whitelist."""
    # 2024-07-03 (Wed before 4th of July): NYSE half-session,
    # market closes at 13:00 ET. Should be on the dynamic whitelist
    # → accepted as partial_day=True.
    bars = _load_real_1m("AAPL", "2024-07-03", "2024-07-04")
    daily, audit = aggregate_1m_to_daily(bars)
    if pd.Timestamp("2024-07-03") in daily.index:
        # OK — aggregator correctly identified half-session
        assert bool(daily.loc[pd.Timestamp("2024-07-03"), "partial_day"]) is True
    else:
        # If for some reason the dynamic whitelist didn't fire, audit
        # should capture it
        assert pd.Timestamp("2024-07-03") in audit.index
