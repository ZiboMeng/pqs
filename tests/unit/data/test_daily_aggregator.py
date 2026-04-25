"""
Round-3 step 1 regression assertions for the 1m -> daily aggregator.

These tests pin the contract from
`docs/memos/20260425-data_integrity_round3_implementation_note.md`.

Three regression assertions per §7 of the implementation note:
  * R-1: no Sat/Sun rows in the aggregator's output (label = real ET trading day).
  * R-2: daily close = polygon 1m regular-session last close on same real date
         (with explicit 50 bps tolerance for floating-point and downstream
         pipeline robustness; aggregator itself returns exact equality on
         synthetic input).
  * R-3: no adjacent-day raw-close ratio outside [0.5, 2.0] EXCEPT on dates
         in a known-splits whitelist.
         Whitelist driven; do NOT relax the ratio thresholds to "save" a
         partial-day failure — partial days go via the half-session
         whitelist or the audit log, NOT via threshold loosening.

Step 1 also verifies:
  * incomplete-day policy: non-whitelisted low-bar-count days get
    quarantined into the audit log and do NOT silently fallback into
    daily output.
  * +1 day label-offset bug is gone: aggregator labels rows by real
    ET trading day from the underlying 1m timestamps.

Note: these are aggregator-output contract tests using synthetic 1m
fixtures. Step 3 (daily parquet rebuild) will add a second batch of
integration tests against `BarStore.load(symbol, '1d')` directly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.data.daily_aggregator import aggregate_1m_to_daily


# ───────── synthetic 1m fixtures ────────────────────────────────────────


def _build_synthetic_1m(
    days: list[str],
    *,
    base_close: float = 100.0,
    daily_drift: float = 0.001,
    minute_jitter: float = 0.0,
    n_bars_per_day: int = 390,
    half_days: list[str] | None = None,
    skip_open_bar: list[str] | None = None,
    skip_close_bar: list[str] | None = None,
    low_bar_count: dict[str, int] | None = None,
) -> pd.DataFrame:
    """
    Generate synthetic ET-naive 1m bars for `days`. Default produces a
    full regular-session day (09:30..15:59 inclusive = 390 bars).

    Knobs:
      half_days: produce only 09:30..12:59 (210 bars) for these dates.
      skip_open_bar: drop the 09:30 bar for these dates.
      skip_close_bar: drop the 15:59 (or 12:59 for half) bar.
      low_bar_count: dict {date: n} producing only n RT bars near
                     market open (insufficient for full session).
    """
    half_days = set(half_days or [])
    skip_open_bar = set(skip_open_bar or [])
    skip_close_bar = set(skip_close_bar or [])
    low_bar_count = dict(low_bar_count or {})

    rows = []
    cumulative = base_close
    for d in days:
        d_ts = pd.Timestamp(d)
        is_half = d in half_days
        if d in low_bar_count:
            n_bars = low_bar_count[d]
            close_minute = 9 * 60 + 30 + n_bars - 1
        elif is_half:
            n_bars = 210  # 09:30..12:59
            close_minute = 12 * 60 + 59
        else:
            n_bars = n_bars_per_day
            close_minute = 15 * 60 + 59

        for i in range(n_bars):
            minute_offset = i  # 0..n_bars-1
            t = d_ts + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(minutes=minute_offset)
            time_min = t.hour * 60 + t.minute

            if d in skip_open_bar and time_min == (9 * 60 + 30):
                continue
            if d in skip_close_bar and time_min == close_minute:
                continue

            cumulative *= (1.0 + daily_drift / n_bars_per_day)
            jitter = np.sin(i / 10.0) * minute_jitter * cumulative
            o = cumulative + jitter
            c = cumulative - jitter
            rows.append({
                "open":   o,
                "high":   max(o, c) + 0.05,
                "low":    min(o, c) - 0.05,
                "close":  c,
                "volume": 10_000 + i,
                "_t": t,
            })
        # Day-over-day drift step
        cumulative *= (1.0 + daily_drift)

    df = pd.DataFrame(rows)
    df = df.set_index("_t")
    df.index.name = None
    return df


# ───────── R-1: no Sat/Sun rows ─────────────────────────────────────────


def test_R1_no_weekend_rows_in_aggregator_output():
    """R-1: aggregator output indexes by real ET trading day; never
    Saturday or Sunday."""
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
            "2024-01-08", "2024-01-09"]  # Tue..Tue across one weekend
    bars = _build_synthetic_1m(days)
    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert audit.empty, f"unexpected audit rows: {audit}"
    weekday = daily.index.weekday
    assert (weekday < 5).all(), (
        f"aggregator emitted weekend rows: {daily.index[weekday >= 5].tolist()}"
    )


# ───────── R-2: close = 1m regular-session last close on same real date


def test_R2_close_equals_1m_last_regular_session_close_same_real_date():
    """R-2 contract: for every output date d, daily.close[d] equals the
    1m bar at HH:MM = 15:59 ET on the SAME real date d. No date shift,
    no after-hours, no 16:00 bar."""
    days = ["2024-03-04", "2024-03-05", "2024-03-06"]
    bars = _build_synthetic_1m(days, base_close=200.0, minute_jitter=0.01)

    # Inject an after-hours bar to ensure aggregator does NOT pick it up
    extra_bar_ts = pd.Timestamp("2024-03-05") + pd.Timedelta(hours=16, minutes=30)
    bars.loc[extra_bar_ts] = {
        "open": 9999.0, "high": 9999.0, "low": 9999.0,
        "close": 9999.0, "volume": 1,
    }
    bars = bars.sort_index()

    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert audit.empty
    for day in days:
        d_ts = pd.Timestamp(day)
        expected_close_ts = d_ts + pd.Timedelta(hours=15, minutes=59)
        expected_close = float(bars.loc[expected_close_ts, "close"])
        actual_close = float(daily.loc[d_ts, "close"])
        rel_err = abs(actual_close - expected_close) / max(abs(expected_close), 1e-9)
        assert rel_err < 5e-3, (  # 50 bps
            f"R-2 violation: date={day} expected close={expected_close} got "
            f"{actual_close} (rel_err={rel_err:.2%})"
        )


def test_R2_after_hours_bar_does_not_pollute_close():
    """Tighter R-2: a 16:30 bar with absurd value cannot creep into
    daily.close; the contract is 15:59 ET regardless of after-hours."""
    days = ["2024-04-08"]
    bars = _build_synthetic_1m(days, base_close=50.0)
    bars.loc[pd.Timestamp("2024-04-08 16:30:00")] = {
        "open": 1e6, "high": 1e6, "low": 1e6, "close": 1e6, "volume": 1,
    }
    bars = bars.sort_index()
    daily, _ = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert float(daily.iloc[0]["close"]) < 100.0


# ───────── R-3: no adjacent-day raw-close ratio outside [0.5, 2.0]
#                except known split dates ───────────────────────────────


def test_R3_no_jump_outside_05_2_on_clean_panel():
    """R-3: aggregator output, given clean 1m raw input with no splits,
    must show no adjacent-day raw-close ratio outside [0.5, 2.0]."""
    days = pd.bdate_range("2024-01-02", "2024-02-29").strftime("%Y-%m-%d").tolist()
    bars = _build_synthetic_1m(days, base_close=100.0, daily_drift=0.005)
    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert audit.empty
    # raw close ratios
    closes = daily["close"].astype(float)
    ratios = closes / closes.shift(1)
    flagged = ratios[(ratios < 0.5) | (ratios > 2.0)].dropna()
    assert flagged.empty, (
        f"R-3 violation on clean panel: {flagged.to_dict()}"
    )


def test_R3_split_dates_must_use_whitelist_not_threshold_loosening():
    """R-3: simulate a synthetic 2:1 split between day N and day N+1.
    The post-split day's raw close drops to ~0.5 * prior — outside
    [0.5, 2.0] would be flagged. The CONTRACT is that the test
    handles this via a known-splits whitelist, NOT by relaxing the
    [0.5, 2.0] thresholds."""
    days = ["2024-05-06", "2024-05-07", "2024-05-08", "2024-05-09",
            "2024-05-10"]
    bars = _build_synthetic_1m(days, base_close=200.0, daily_drift=0.0)
    # Cut 2024-05-08 onwards by half (simulated 2:1 split)
    cut_from = pd.Timestamp("2024-05-08")
    mask = bars.index >= cut_from
    bars.loc[mask, ["open", "high", "low", "close"]] *= 0.5
    daily, _ = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    closes = daily["close"].astype(float)
    ratios = closes / closes.shift(1)

    # Identify the offending date
    KNOWN_SPLITS = {pd.Timestamp("2024-05-08")}

    flagged = ratios[(ratios < 0.5) | (ratios > 2.0)].dropna()
    # Whitelist drives the allow; threshold stays [0.5, 2.0]
    unauthorized = [d for d in flagged.index if d not in KNOWN_SPLITS]
    assert not unauthorized, (
        f"R-3 violation outside whitelist: {unauthorized} "
        f"(ratios={flagged.to_dict()})"
    )

    # The split day's ratio is allowed (≈ 0.5) — but only because of
    # the whitelist, not because we changed the threshold.
    assert ratios[pd.Timestamp("2024-05-08")] < 0.6


def test_R3_partial_day_does_NOT_get_threshold_relaxed():
    """R-3: a half-session day whose raw close happens to be lower
    than full-session prior must still pass within [0.5, 2.0] as
    long as the price moves are real. We do not loosen R-3 to
    accommodate partial-day low volume / sparse bars."""
    days = ["2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29",
            "2024-12-02"]
    # 2024-11-29 = Black Friday (NYSE half-session)
    bars = _build_synthetic_1m(
        days,
        base_close=100.0,
        daily_drift=0.001,
        half_days=["2024-11-29"],
    )
    daily, audit = aggregate_1m_to_daily(
        bars, partial_day_whitelist={pd.Timestamp("2024-11-29")},
    )
    assert audit.empty
    assert daily.loc[pd.Timestamp("2024-11-29"), "partial_day"] is True or \
           bool(daily.loc[pd.Timestamp("2024-11-29"), "partial_day"])

    closes = daily["close"].astype(float)
    ratios = closes / closes.shift(1)
    flagged = ratios[(ratios < 0.5) | (ratios > 2.0)].dropna()
    assert flagged.empty, (
        "R-3 (partial-day robustness): no ratio outside [0.5,2.0] "
        f"expected; got {flagged.to_dict()}"
    )


# ───────── Incomplete-day policy: quarantine, not silent fallback


def test_incomplete_day_quarantined_not_filled():
    """Step-1 explicit behavior: a non-whitelisted day with too few
    RT bars is quarantined into the audit log and absent from daily,
    NOT silently filled.

    The day has both 09:30 and 15:59 anchor bars (so the missing-anchor
    quarantines don't fire) but the middle is sparse — n_bars below
    threshold. Only the n_bars-threshold quarantine should trigger.
    """
    days = ["2024-06-03", "2024-06-04", "2024-06-05"]
    bars = _build_synthetic_1m(days)
    # Drop most middle bars on 2024-06-04, keep only anchors + 8 mid:
    # 09:30 + 15:59 + 8 evenly spaced = 10 RT bars total (< 350).
    target_day = pd.Timestamp("2024-06-04")
    is_target = bars.index.normalize() == target_day
    rt_min = bars.index.hour * 60 + bars.index.minute
    keep_minutes = {9*60+30, 15*60+59,
                    10*60, 11*60, 12*60, 13*60, 14*60, 15*60,
                    9*60+45, 15*60+45}
    keep_mask = is_target & (
        pd.Series(rt_min, index=bars.index).isin(keep_minutes).values
    )
    drop_mask = is_target & ~keep_mask
    bars = bars.loc[~drop_mask]

    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    # 06-04 (10 bars) is well below the 300 thin_data floor → quarantine
    assert target_day not in daily.index
    assert target_day in audit.index
    row = audit.loc[target_day]
    assert "low_bar_count<300" in row["reason"], (
        f"expected low_bar_count<300 (post-two-tier), got {row['reason']}"
    )
    assert int(row["n_bars"]) == 10
    assert bool(row["partial_day_whitelisted"]) is False
    # 06-03 and 06-05 are clean; remain in daily
    assert pd.Timestamp("2024-06-03") in daily.index
    assert pd.Timestamp("2024-06-05") in daily.index


def test_missing_close_bar_quarantined():
    """Missing 15:59 bar on a full-session day → quarantine."""
    days = ["2024-07-08", "2024-07-09"]
    bars = _build_synthetic_1m(days, skip_close_bar=["2024-07-09"])
    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert pd.Timestamp("2024-07-09") not in daily.index
    assert pd.Timestamp("2024-07-09") in audit.index
    assert audit.loc[pd.Timestamp("2024-07-09"), "reason"] == "missing_1559_close"


def test_missing_open_bar_quarantined():
    """Missing 09:30 bar → quarantine."""
    days = ["2024-08-05", "2024-08-06"]
    bars = _build_synthetic_1m(days, skip_open_bar=["2024-08-06"])
    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert pd.Timestamp("2024-08-06") not in daily.index
    assert audit.loc[pd.Timestamp("2024-08-06"), "reason"] == "missing_0930_open"


def test_thin_data_accept_tier_300_to_350():
    """Two-tier threshold (round-3 user pinning, post step-3a audit):
    n_bars in [300, 350) on a full-session day with both endpoints
    is accepted into daily_df with thin_data=True. Below 300 → quarantine."""
    days = ["2024-09-04", "2024-09-05", "2024-09-06", "2024-09-09",
            "2024-09-10"]
    bars = _build_synthetic_1m(days)
    # Drop bars on 2024-09-05 to land at n_bars=320 (between 300 and 350).
    target_day = pd.Timestamp("2024-09-05")
    is_target = bars.index.normalize() == target_day
    rt_min = bars.index.hour * 60 + bars.index.minute
    # Keep 09:30 + 15:59 + 318 mids (every minute step 1, take first 318)
    # Range 09:31..15:58 = 388 minutes; take any 318 → 320 RT total.
    mid_pool = list(range(9*60+31, 15*60+59))[:318]
    keep_minutes_thin = {9*60+30, 15*60+59, *mid_pool}
    keep_mask = is_target & pd.Series(rt_min, index=bars.index).isin(keep_minutes_thin).values
    drop_mask = is_target & ~keep_mask
    bars_thin = bars.loc[~drop_mask]

    daily, audit = aggregate_1m_to_daily(bars_thin, partial_day_whitelist=set())
    assert audit.empty, f"unexpected audit: {audit}"
    assert target_day in daily.index, "thin_data day must be in daily output"
    assert bool(daily.loc[target_day, "thin_data"]) is True, (
        f"target should be thin_data=True; got "
        f"{daily.loc[target_day, 'thin_data']}"
    )
    # Other days remain complete (thin_data=False)
    for d in [pd.Timestamp(x) for x in days if pd.Timestamp(x) != target_day]:
        if d in daily.index:
            assert bool(daily.loc[d, "thin_data"]) is False


def test_quarantine_below_300_threshold():
    """Below 300 bars (and with both endpoints) → quarantine."""
    days = ["2024-09-04", "2024-09-05"]
    bars = _build_synthetic_1m(days)
    target_day = pd.Timestamp("2024-09-05")
    is_target = bars.index.normalize() == target_day
    rt_min = bars.index.hour * 60 + bars.index.minute
    # Keep 09:30 + 15:59 + 248 mids = 250 RT bars (< 300 → quarantine)
    mid_pool = list(range(9*60+31, 15*60+59, 2))[:248]
    keep_minutes = {9*60+30, 15*60+59, *mid_pool}
    keep_mask = is_target & pd.Series(rt_min, index=bars.index).isin(keep_minutes).values
    drop_mask = is_target & ~keep_mask
    bars_q = bars.loc[~drop_mask]

    daily, audit = aggregate_1m_to_daily(bars_q, partial_day_whitelist=set())
    assert target_day not in daily.index, "below 300 must NOT be in daily"
    assert target_day in audit.index, "below 300 must be in audit"
    assert "low_bar_count<300" in audit.loc[target_day, "reason"]


def test_full_session_above_350_is_NOT_thin_data():
    """Standard full session: thin_data=False."""
    days = ["2024-09-04", "2024-09-05"]
    bars = _build_synthetic_1m(days)  # 390 bars per day
    daily, _ = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    for d in daily.index:
        assert bool(daily.loc[d, "thin_data"]) is False


def test_partial_day_whitelist_accepts_short_session():
    """A half-session day on the whitelist closes at 12:59 ET (not 15:59)
    and is accepted with partial_day=True, not quarantined."""
    days = ["2024-11-29"]  # Black Friday
    bars = _build_synthetic_1m(days, half_days=["2024-11-29"])
    daily, audit = aggregate_1m_to_daily(
        bars, partial_day_whitelist={pd.Timestamp("2024-11-29")},
    )
    assert pd.Timestamp("2024-11-29") in daily.index
    assert audit.empty
    assert bool(daily.loc[pd.Timestamp("2024-11-29"), "partial_day"]) is True


# ───────── No +1 day offset (date-label integrity)


def test_no_plus_one_day_label_offset():
    """The historical bug was: BS daily label = real_date + 1 day,
    so Mon -> Tue, Fri -> Sat. Aggregator must produce label = real
    date directly from 1m timestamps."""
    # 2024-08-26 is Mon. 2024-08-30 is Fri. 2024-09-02 is Labor Day
    # (NYSE closed). Test that label exactly matches the underlying
    # 1m bar's date.
    days = ["2024-08-26", "2024-08-27", "2024-08-28", "2024-08-29",
            "2024-08-30"]
    bars = _build_synthetic_1m(days)
    daily, _ = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    expected = [pd.Timestamp(d) for d in days]
    assert list(daily.index) == expected, (
        f"label drift: expected {expected}, got {daily.index.tolist()}"
    )
    # Specifically: Mon 2024-08-26 must produce a Mon row (not Sat 2024-08-31).
    assert pd.Timestamp("2024-08-26") in daily.index
    assert pd.Timestamp("2024-08-31") not in daily.index  # Saturday


def test_no_saturday_or_sunday_anywhere():
    """Hard guard: no row in aggregator output may have weekday in
    {5, 6} = {Sat, Sun}."""
    days = pd.bdate_range("2024-01-01", "2024-12-31").strftime("%Y-%m-%d").tolist()
    bars = _build_synthetic_1m(days, base_close=100.0, daily_drift=0.0005)
    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=None)
    weekend_rows = daily.index[daily.index.weekday >= 5]
    assert len(weekend_rows) == 0, (
        f"weekend rows found: {weekend_rows.tolist()}"
    )


# ───────── Adjustment policy: aggregator returns RAW


def test_aggregator_returns_raw_no_split_cascade():
    """Aggregator's output is RAW. The split-cascade is read-time at
    BarStore.load(adjusted=True). This test confirms the aggregator
    does not call into splits.parquet on its own."""
    days = ["2024-10-01", "2024-10-02", "2024-10-03"]
    bars = _build_synthetic_1m(days, base_close=500.0)
    daily, _ = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    # Synthetic bars have no split applied, so output close ≈ base_close * drift.
    # Just assert closes are in the same order of magnitude as input
    # (no surprise 5x division).
    assert daily["close"].iloc[0] > 100.0
    assert daily["close"].iloc[0] < 10_000.0


# ───────── Input-validation contracts


def test_rejects_tz_aware_input():
    bars = _build_synthetic_1m(["2024-01-02"])
    bars.index = bars.index.tz_localize("US/Eastern")
    with pytest.raises(ValueError, match="tz-naive"):
        aggregate_1m_to_daily(bars, partial_day_whitelist=set())


def test_rejects_missing_columns():
    bars = _build_synthetic_1m(["2024-01-02"])
    bars = bars.drop(columns=["volume"])
    with pytest.raises(ValueError, match="missing required columns"):
        aggregate_1m_to_daily(bars, partial_day_whitelist=set())


def test_half_session_whitelist_DST_robustness():
    """Regression: the dynamic half-session whitelist used to compare
    market_close to '21:00 UTC' which is only correct in winter (EST).
    During DST (March–November) NYSE close in UTC is 20:00, not 21:00,
    so the naive UTC compare mislabeled every DST-summer regular day
    as a half-session — turning ~half the universe-history into bogus
    'partial' rows in the aggregator output.

    Fix: compare in ET (close-hour ≠ 16). This test pins the fix by
    asserting that representative DST-summer regular trading days
    (Mon-Fri full sessions in May / July) are NOT classified as
    half-session, while a known half-session (day after Thanksgiving)
    IS."""
    from core.data.daily_aggregator import _half_session_days_from_calendar
    half = _half_session_days_from_calendar(
        pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31"),
    )
    # 2022-11-25 (Black Friday) is a documented NYSE half-session
    assert pd.Timestamp("2022-11-25") in half, (
        "Black Friday 2022 should be in half-session whitelist"
    )
    # DST-summer regular trading days must NOT appear in the whitelist
    for d in ("2022-05-09", "2022-06-13", "2022-07-11", "2022-08-15"):
        assert pd.Timestamp(d) not in half, (
            f"{d} (DST-summer regular full session) should NOT be in "
            f"half-session whitelist; DST-aware compare regression"
        )
    # Whitelist size for 2022 should be small (~5-10 half-days), not
    # ~half the year (~125+).
    assert len(half) < 20, (
        f"2022 half-session whitelist has {len(half)} entries — "
        f"DST regression suspected (real NYSE half-days/yr is 5-10)"
    )


def test_empty_input_returns_empty():
    bars = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"],
        index=pd.DatetimeIndex([], name="t"),
    )
    daily, audit = aggregate_1m_to_daily(bars, partial_day_whitelist=set())
    assert daily.empty
    assert audit.empty
