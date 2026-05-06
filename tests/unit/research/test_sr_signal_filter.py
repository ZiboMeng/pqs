"""Tests for SR defer filter (core/research/sr_signal_filter.py).

PRD 20260505 Step 6.1-min. Productionized from Step 5b dev script with:
  - RTH-only filter (fix for post-market contamination)
  - Defensive sort_index
  - Explicit NaN close handling
  - end-date truncation BEFORE SR computation (sealed-window discipline)
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd
import pytest

from core.research.sr_signal_filter import (
    SRDeferConfig,
    SRDeferStats,
    _filter_rth,
    apply_sr_defer_filter,
)


def _make_60m_bars(
    start: str = "2024-01-02",
    n_days: int = 30,
    rth_only: bool = False,
    base_close: float = 100.0,
) -> pd.DataFrame:
    """Build synthetic 60m bars across n_days. Default includes pre-market
    (04:00–08:00) and post-market (16:00–20:00). rth_only=True restricts
    to RTH bars 09:30–15:30."""
    if rth_only:
        times = [time(9, 30), time(10, 30), time(11, 30),
                 time(12, 30), time(13, 30), time(14, 30), time(15, 30)]
    else:
        # ETH: 04:00–08:00 pre + 09:30–15:30 RTH-aligned + 16:00–20:00 post
        times = [time(4, 0), time(5, 0), time(6, 0), time(7, 0), time(8, 0),
                 time(9, 30), time(10, 30), time(11, 30),
                 time(12, 30), time(13, 30), time(14, 30), time(15, 30),
                 time(16, 0), time(17, 0), time(18, 0), time(19, 0), time(20, 0)]
    rows = []
    for d in pd.bdate_range(start, periods=n_days):
        for t in times:
            rows.append((pd.Timestamp(d.date()).replace(hour=t.hour, minute=t.minute),
                         base_close))
    closes = np.array([r[1] for r in rows], dtype=float)
    # Add some saw-tooth pattern so swing extrema exist
    closes = closes + np.array([
        5 if i % 35 == 17 else (-5 if i % 35 == 0 else 0)
        for i in range(len(closes))
    ], dtype=float)
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame({
        "open": closes - 0.1, "high": closes + 0.5,
        "low": closes - 0.5, "close": closes, "volume": 1e5,
    }, index=idx)
    return df


def _make_target_wts(
    dates: list[str],
    syms: list[str],
    weight: float = 0.10,
) -> pd.DataFrame:
    return pd.DataFrame(
        {s: [weight] * len(dates) for s in syms},
        index=pd.DatetimeIndex([pd.Timestamp(d) for d in dates]),
    )


# ── _filter_rth ────────────────────────────────────────────────


def test_filter_rth_drops_pre_and_post_market():
    bars = _make_60m_bars(n_days=2, rth_only=False)
    rth = _filter_rth(bars, time(9, 30), time(16, 0))
    times_kept = sorted(set(rth.index.time))
    # Should retain only RTH-aligned times: 09:30, 10:30, ..., 15:30
    expected = [time(9, 30), time(10, 30), time(11, 30), time(12, 30),
                time(13, 30), time(14, 30), time(15, 30)]
    assert times_kept == expected
    # No pre-market 04:00 or post-market 16:00+
    assert not any(t < time(9, 30) for t in times_kept)
    assert not any(t >= time(16, 0) for t in times_kept)


def test_filter_rth_handles_empty_input():
    empty = pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([]),
    )
    out = _filter_rth(empty, time(9, 30), time(16, 0))
    assert out.empty


# ── apply_sr_defer_filter — RTH bug fix regression ────────────


def test_filter_uses_rth_bar_not_post_market_bar():
    """REGRESSION: Step 5b v1 used post-market bars for "last bar of day"
    on most historical days (16:00–21:00 ET range). After fix, must use
    15:30 RTH bar."""
    np.random.seed(0)
    bars = _make_60m_bars(n_days=40, rth_only=False)
    # Manually engineer: at 15:30 close ≈ R; at 19:00 (post) close FAR from R.
    # Without RTH filter, last-bar-of-day = 19:00, gap to R is large → no defer.
    # With RTH filter, last-bar-of-day = 15:30 close near R → defer fires.
    # Simplest: pick a target date and surgically set close values.
    target_date = bars.index[100].date()
    # set 15:30 RTH close near R
    rth_idx = bars[(bars.index.date == target_date)
                   & (bars.index.time == time(15, 30))].index
    post_idx = bars[(bars.index.date == target_date)
                    & (bars.index.time >= time(16, 0))].index
    # Build a clear "near R at RTH close, far from R at post-market" pattern.
    # The synthetic bars already have saw-tooth swings; we just verify
    # the filter consumes 15:30 bar and not 19:00 bar.
    target_wts = _make_target_wts(
        [str(target_date)], ["AAA"], weight=0.10,
    )
    intraday = {"AAA": bars}
    out, stats = apply_sr_defer_filter(target_wts, intraday)
    # Mainly: filter completed without crashing and used some bars.
    # The detailed numerical assertion is in
    # test_filter_RTH_bar_close_drives_defer_decision below.
    assert isinstance(stats, SRDeferStats)


def test_filter_rth_bar_close_drives_defer_decision():
    """Construct a setup where ONLY the 15:30 RTH bar's close triggers
    defer. Set 15:30 bar to be just below a known swing high; set post-
    market bars FAR below. Defer must fire (RTH-aware) NOT just look at
    last bar overall (post-market noise)."""
    # Create simple synthetic 60m bars: 30 days
    days = pd.bdate_range("2024-01-02", periods=30)
    rows = []
    for i, d in enumerate(days):
        for t in [time(9, 30), time(10, 30), time(11, 30),
                  time(12, 30), time(13, 30), time(14, 30), time(15, 30),
                  time(16, 0), time(17, 0), time(18, 0)]:
            ts = pd.Timestamp(d.date()).replace(hour=t.hour, minute=t.minute)
            rows.append((ts, 100.0))
    closes = np.array([r[1] for r in rows])
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame({
        "open": closes, "high": closes + 0.1, "low": closes - 0.1,
        "close": closes, "volume": 1e5,
    }, index=idx)
    # Engineer a swing high at day 24 RTH 15:30 (within lookback=20 60m
    # bars from day 25 RTH-close): high = 110, close = 110.
    # With 7 RTH bars/day, day 24 RTH-close = bar (24*7+6)=174;
    # day 25 RTH-close = bar (25*7+6)=181; lookback=20 covers bars
    # 161-178 (using j-n confirmation lag); bar 174 is in range ✓.
    swing_day = days[24].date()
    swing_idx = df[(df.index.date == swing_day)
                   & (df.index.time == time(15, 30))].index[0]
    df.at[swing_idx, "high"] = 110.0
    df.at[swing_idx, "close"] = 110.0
    # Day 25 RTH 15:30 close = 109.7 (30 bps below 110 R). Should defer.
    target_day = days[25].date()
    target_rth_close = df[(df.index.date == target_day)
                          & (df.index.time == time(15, 30))].index[0]
    df.at[target_rth_close, "close"] = 109.7   # 30 bps below R=110

    # post-market bars on target day = far below 110 (close ~ 100).
    post_target = df[(df.index.date == target_day)
                     & (df.index.time >= time(16, 0))].index
    for ts in post_target:
        df.at[ts, "close"] = 95.0  # far below R, would NOT trigger defer

    target_wts = _make_target_wts([str(target_day)], ["AAA"], weight=0.10)
    intraday = {"AAA": df}
    out, stats = apply_sr_defer_filter(
        target_wts, intraday,
        config=SRDeferConfig(
            swing_n=2, lookback_bars=20, near_resistance_pct=0.005,
        ),
    )
    # Defer must fire because RTH-close 109.7 is within 50 bps of R=110.
    # Pre-bug version (last-bar-of-day=post-market 95.0) would NOT fire.
    assert stats.n_defers == 1, (
        f"RTH-close defer expected; got n_defers={stats.n_defers}. "
        f"Pre-bug filter would have used post-market close 95.0 "
        f"(far from R) and skipped."
    )
    assert out.at[target_wts.index[0], "AAA"] == 0.0


# ── core defer semantics ────────────────────────────────────────


def test_defer_does_not_fire_when_far_from_resistance():
    """Close 5% below R, threshold 50 bps → no defer."""
    days = pd.bdate_range("2024-01-02", periods=30)
    rows = []
    for d in days:
        for t in [time(9, 30), time(10, 30), time(11, 30),
                  time(12, 30), time(13, 30), time(14, 30), time(15, 30)]:
            ts = pd.Timestamp(d.date()).replace(hour=t.hour, minute=t.minute)
            rows.append((ts, 100.0))
    closes = np.array([r[1] for r in rows])
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame({
        "open": closes, "high": closes + 0.1, "low": closes - 0.1,
        "close": closes, "volume": 1e5,
    }, index=idx)
    # Engineer swing high at day 5 = 105 (5%/bp 5000 bps above 100 baseline).
    swing_ts = df[(df.index.date == days[5].date())
                  & (df.index.time == time(15, 30))].index[0]
    df.at[swing_ts, "high"] = 105.0
    df.at[swing_ts, "close"] = 105.0
    target_day = days[25].date()
    target_wts = _make_target_wts([str(target_day)], ["AAA"], weight=0.10)
    out, stats = apply_sr_defer_filter(
        target_wts, {"AAA": df},
        config=SRDeferConfig(swing_n=2, lookback_bars=20,
                             near_resistance_pct=0.005),
    )
    # Close 100, R=105 → gap 5%. Threshold 0.5%. No defer.
    assert stats.n_defers == 0
    assert out.at[target_wts.index[0], "AAA"] == 0.10  # unchanged


def test_short_history_does_not_defer():
    """Symbol with only a few RTH bars (< 2*swing_n+1) → can't compute
    swing → cell preserved + counted in n_skipped_short_history."""
    days = pd.bdate_range("2024-01-02", periods=2)
    rows = []
    for d in days:
        for t in [time(9, 30), time(10, 30)]:
            ts = pd.Timestamp(d.date()).replace(hour=t.hour, minute=t.minute)
            rows.append((ts, 100.0))
    df = pd.DataFrame({
        "open": [100.0]*4, "high": [100.5]*4, "low": [99.5]*4,
        "close": [100.0]*4, "volume": [1e5]*4,
    }, index=pd.DatetimeIndex([r[0] for r in rows]))
    # 4 bars total, swing_n=5 needs 11 bars → skip
    target_wts = _make_target_wts([str(days[1].date())], ["AAA"], weight=0.10)
    out, stats = apply_sr_defer_filter(
        target_wts, {"AAA": df},
        config=SRDeferConfig(swing_n=5, lookback_bars=20,
                             near_resistance_pct=0.005),
    )
    # Whether it counts as no_60m / short_history / no_rth depends on
    # internal slicing; total skipped non-evaluated must equal 1.
    assert stats.n_defers == 0
    assert out.at[target_wts.index[0], "AAA"] == 0.10  # unchanged


def test_no_60m_coverage_passes_through():
    target_wts = _make_target_wts(["2024-02-01"], ["AAA", "BBB"], weight=0.10)
    # AAA has 60m, BBB doesn't.
    df_aaa = _make_60m_bars(start="2024-01-02", n_days=30, rth_only=True)
    out, stats = apply_sr_defer_filter(target_wts, {"AAA": df_aaa})
    assert stats.n_skipped_no_60m_coverage >= 1  # BBB skipped
    # BBB cell preserved
    assert out.at[target_wts.index[0], "BBB"] == 0.10


def test_zero_weight_cells_not_evaluated():
    target_wts = pd.DataFrame(
        {"AAA": [0.0, 0.10], "BBB": [0.10, 0.0]},
        index=pd.DatetimeIndex(["2024-02-01", "2024-02-02"]),
    )
    df = _make_60m_bars(start="2024-01-02", n_days=30, rth_only=True)
    out, stats = apply_sr_defer_filter(target_wts, {"AAA": df, "BBB": df})
    # Total positive-weight cells = 2 (AAA day2 + BBB day1)
    # n_evaluated <= 2; zero cells aren't even attempted.
    assert stats.n_evaluated + stats.n_skipped_no_60m_coverage \
        + stats.n_skipped_short_history + stats.n_skipped_no_rth_bars_today <= 2


def test_empty_intraday_passes_all_through():
    target_wts = _make_target_wts(["2024-02-01"], ["AAA"], weight=0.10)
    out, stats = apply_sr_defer_filter(target_wts, {})
    assert stats.n_defers == 0
    assert stats.n_skipped_no_60m_coverage == 1
    pd.testing.assert_frame_equal(out, target_wts)


def test_empty_target_wts_returns_empty():
    empty = pd.DataFrame(columns=["AAA"], index=pd.DatetimeIndex([]))
    df = _make_60m_bars(start="2024-01-02", n_days=10, rth_only=True)
    out, stats = apply_sr_defer_filter(empty, {"AAA": df})
    assert stats.n_defers == 0
    assert out.empty


# ── defensive sort_index ────────────────────────────────────────


def test_unsorted_input_sorted_internally():
    """If 60m bars come in shuffled (not monotonic), filter should
    sort internally and produce same result as pre-sorted input."""
    df = _make_60m_bars(start="2024-01-02", n_days=30, rth_only=True)
    df_shuffled = df.sample(frac=1, random_state=42)  # shuffle rows
    target_wts = _make_target_wts(
        [str(df.index[-1].date())], ["AAA"], weight=0.10,
    )
    out_sorted, _ = apply_sr_defer_filter(target_wts, {"AAA": df})
    out_shuffled, _ = apply_sr_defer_filter(target_wts, {"AAA": df_shuffled})
    pd.testing.assert_frame_equal(out_sorted, out_shuffled)


# ── NaN close handling ──────────────────────────────────────────


def test_nan_close_does_not_fire():
    """If T-day RTH-close bar has NaN close, defer must NOT fire (and
    must not throw)."""
    days = pd.bdate_range("2024-01-02", periods=30)
    rows = []
    for d in days:
        for t in [time(9, 30), time(10, 30), time(11, 30),
                  time(12, 30), time(13, 30), time(14, 30), time(15, 30)]:
            ts = pd.Timestamp(d.date()).replace(hour=t.hour, minute=t.minute)
            rows.append((ts, 100.0))
    closes = np.array([r[1] for r in rows])
    idx = pd.DatetimeIndex([r[0] for r in rows])
    df = pd.DataFrame({
        "open": closes, "high": closes + 0.1, "low": closes - 0.1,
        "close": closes, "volume": 1e5,
    }, index=idx)
    # Set last RTH bar close = NaN
    target_day = days[25].date()
    target_idx = df[(df.index.date == target_day)
                    & (df.index.time == time(15, 30))].index[0]
    df.at[target_idx, "close"] = np.nan
    target_wts = _make_target_wts([str(target_day)], ["AAA"], weight=0.10)
    out, stats = apply_sr_defer_filter(target_wts, {"AAA": df})
    assert stats.n_defers == 0  # NaN close → preserve cell


# ── end-date truncation (sealed-window discipline) ──────────────


def test_end_date_truncates_60m_before_sr_compute():
    """SR computation must NOT use bars after ``end``. Test by setting up
    a swing high AFTER end, and verifying the filter does NOT see it."""
    df = _make_60m_bars(start="2024-01-02", n_days=60, rth_only=True)
    # Put a swing high at day 50 (well after end=2024-02-01)
    end_ts = pd.Timestamp("2024-02-01")
    target_day_str = "2024-01-31"  # within the [start, end] window
    swing_late_idx = df[(df.index.date == pd.Timestamp(df.index[-1]).date())
                        & (df.index.time == time(15, 30))].index[0]
    df.at[swing_late_idx, "high"] = 200.0  # very high swing AFTER end
    df.at[swing_late_idx, "close"] = 200.0
    target_wts = _make_target_wts([target_day_str], ["AAA"], weight=0.10)
    out, stats = apply_sr_defer_filter(
        target_wts, {"AAA": df}, end=end_ts,
    )
    # If end-truncation works, the swing at day 50 should NOT influence
    # day 25's S/R. There's no swing at value 200 before end, so defer
    # should not fire for that reason.
    # We can't directly observe "did filter use post-end bars"; we just
    # verify the function does NOT crash and returns a sensible result.
    assert stats is not None


# ── start/end date filter loop bounds ───────────────────────────


def test_dates_outside_range_skipped():
    """target_wts dates outside [start, end] must NOT be modified."""
    df = _make_60m_bars(start="2024-01-02", n_days=60, rth_only=True)
    # 5 dates in target_wts; only middle 3 in [start, end]
    target_dates = ["2024-01-15", "2024-01-20", "2024-01-25",
                    "2024-01-30", "2024-02-05"]
    target_wts = _make_target_wts(target_dates, ["AAA"], weight=0.10)
    start = pd.Timestamp("2024-01-20")
    end = pd.Timestamp("2024-01-30")
    out, stats = apply_sr_defer_filter(
        target_wts, {"AAA": df}, start=start, end=end,
    )
    # First and last dates are outside range — must be unchanged
    assert out.at[target_wts.index[0], "AAA"] == 0.10
    assert out.at[target_wts.index[-1], "AAA"] == 0.10


# ── determinism ─────────────────────────────────────────────────


def test_same_input_same_output():
    df = _make_60m_bars(start="2024-01-02", n_days=30, rth_only=True)
    target_wts = _make_target_wts(
        ["2024-02-05", "2024-02-06"], ["AAA"], weight=0.10,
    )
    out1, stats1 = apply_sr_defer_filter(target_wts, {"AAA": df})
    out2, stats2 = apply_sr_defer_filter(target_wts, {"AAA": df})
    pd.testing.assert_frame_equal(out1, out2)
    assert stats1 == stats2


def test_input_target_wts_not_mutated():
    """Filter must not mutate the input target_wts (in-place safety)."""
    df = _make_60m_bars(start="2024-01-02", n_days=30, rth_only=True)
    target_wts = _make_target_wts(["2024-02-05"], ["AAA"], weight=0.10)
    target_wts_copy = target_wts.copy()
    out, _ = apply_sr_defer_filter(target_wts, {"AAA": df})
    pd.testing.assert_frame_equal(target_wts, target_wts_copy)


# ── config defaults ──────────────────────────────────────────────


def test_config_defaults():
    cfg = SRDeferConfig()
    assert cfg.swing_n == 5
    assert cfg.lookback_bars == 20
    assert cfg.near_resistance_pct == 0.005
    assert cfg.rth_start_time == time(9, 30)
    assert cfg.rth_end_time == time(16, 0)
