"""Tests for forward attention report compute functions.

Covers pure-compute primitives:
  - load_nav_series: cum_ret → NAV → daily_ret derivation
  - compute_combo_nav: weighted multi-candidate portfolio
  - compute_rolling_max_drawdown: 60d rolling MaxDD
  - compute_residual_corr: regress out benchmark beta then Pearson
  - compute_non_equity_exposure: held_today_weights → asset class buckets
  - classify_td60_verdict: PRD §7.1 GREEN/YELLOW/RED logic
  - generate_attention_report: graceful handling of empty/sparse manifests
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research.forward.attention_report import (
    AttentionReport,
    classify_td60_verdict,
    compute_combo_nav,
    compute_non_equity_exposure,
    compute_residual_corr,
    compute_rolling_max_drawdown,
    generate_attention_report,
    load_nav_series,
)
from core.research.forward.manifest_schema import (
    CandidateRole,
    CheckpointCadence,
    DataIntegritySnapshot,
    EvidenceClass,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
)


def _build_manifest(
    candidate_id: str,
    runs_data,
    soft_warn_flags=None,
):
    """Helper: minimal-spec manifest with synthetic runs.

    runs_data: list of (checkpoint_label, as_of_date, cum_ret, weights_dict|None)
    """
    runs = []
    for i, (label, dt, cum_ret, weights) in enumerate(runs_data):
        runs.append(ForwardRun(
            checkpoint_label=label,
            as_of_date=dt,
            n_observed_trading_days=i + 1,
            cum_ret=cum_ret,
            sharpe=None if cum_ret is None else 1.0,
            max_dd=None if cum_ret is None else min(0.0, cum_ret),
            vs_spy=None if cum_ret is None else cum_ret * 0.9,
            vs_qqq=None if cum_ret is None else cum_ret * 0.85,
            held_today_weights=weights,
        ))
    return ForwardRunManifest(
        schema_version="2.1",
        candidate_id=candidate_id,
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="a" * 64,
        start_date=date(2026, 5, 4),
        benchmark="SPY",
        secondary_benchmark="QQQ",
        cost_assumptions={
            "slippage_bps": 5.0,
            "commission_per_share": 0.005,
            "source": "test_fixture",
            "config_hash": "c" * 12,
        },
        checkpoint_cadence=CheckpointCadence(weekly=True, decision_days=[10, 20, 40, 60]),
        current_status=ForwardRunStatus.in_progress,
        data_integrity_snapshot=DataIntegritySnapshot(
            daily_store_rebuild_commit="b" * 40,
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime.now(timezone.utc),
        ),
        candidate_role=CandidateRole.diversifier,
        soft_warn_flags=soft_warn_flags or [],
        runs=runs,
    )


# ---------------------------------------------------------------------------
# load_nav_series
# ---------------------------------------------------------------------------


def test_load_nav_series_empty_manifest():
    m = _build_manifest("test", [])
    df = load_nav_series(m)
    assert df.empty
    assert list(df.columns) == ["cum_ret", "nav", "daily_ret"]


def test_load_nav_series_skips_decide_entries():
    m = _build_manifest("test", [
        ("TD001", date(2026, 5, 4), 0.0, None),
        ("TD002", date(2026, 5, 5), 0.01, None),
        ("DECIDE", date(2026, 5, 5), None, None),  # skip
    ])
    df = load_nav_series(m)
    assert len(df) == 2
    assert "DECIDE" not in df.index


def test_load_nav_series_skips_none_cum_ret():
    m = _build_manifest("test", [
        ("TD001", date(2026, 5, 4), 0.0, None),
        ("TD002", date(2026, 5, 5), None, None),  # incomplete
        ("TD003", date(2026, 5, 6), 0.02, None),
    ])
    df = load_nav_series(m)
    assert len(df) == 2


def test_load_nav_series_derives_nav_and_daily_ret():
    m = _build_manifest("test", [
        ("TD001", date(2026, 5, 4), 0.00, None),
        ("TD002", date(2026, 5, 5), 0.01, None),
        ("TD003", date(2026, 5, 6), 0.02, None),
    ])
    df = load_nav_series(m)
    assert df["nav"].tolist() == pytest.approx([1.0, 1.01, 1.02])
    # daily_ret[0] = NaN, [1] = 0.01/1.0 - 0 = 0.01, [2] ≈ 0.0099
    assert pd.isna(df["daily_ret"].iloc[0])
    assert df["daily_ret"].iloc[1] == pytest.approx(0.01, rel=1e-4)
    assert df["daily_ret"].iloc[2] == pytest.approx(0.00990099, rel=1e-4)


def test_load_nav_series_sorted_and_dedup():
    m = _build_manifest("test", [
        ("TD002", date(2026, 5, 5), 0.01, None),
        ("TD001", date(2026, 5, 4), 0.00, None),  # out of order
        ("TD002b", date(2026, 5, 5), 0.015, None),  # duplicate date
    ])
    df = load_nav_series(m)
    # Sorted ascending; duplicate date kept last (last entry on that date)
    assert df.index.is_monotonic_increasing
    assert df.loc[pd.Timestamp("2026-05-05"), "cum_ret"] == 0.015


# ---------------------------------------------------------------------------
# compute_combo_nav
# ---------------------------------------------------------------------------


def _nav_df(daily_returns, start_date=date(2026, 5, 4)):
    """Build NAV DataFrame from a daily returns list (skipping NaN-first convention)."""
    dates = [pd.Timestamp(start_date) + pd.Timedelta(days=i) for i in range(len(daily_returns))]
    nav = np.cumprod([1 + r for r in daily_returns])
    return pd.DataFrame({
        "cum_ret": nav - 1.0,
        "nav": nav,
        "daily_ret": [np.nan] + list(daily_returns[1:]),
    }, index=pd.DatetimeIndex(dates))


def test_compute_combo_nav_equal_weight_two_candidates():
    a = _nav_df([0.0, 0.01, 0.02])
    b = _nav_df([0.0, 0.03, 0.01])
    combo = compute_combo_nav({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
    # daily_ret[1] = 0.5 * 0.01 + 0.5 * 0.03 = 0.02
    # daily_ret[2] = 0.5 * 0.02 + 0.5 * 0.01 = 0.015
    assert combo["daily_ret"].iloc[0] == pytest.approx(0.02)
    assert combo["daily_ret"].iloc[1] == pytest.approx(0.015)


def test_compute_combo_nav_weight_sum_violation():
    a = _nav_df([0.0, 0.01])
    b = _nav_df([0.0, 0.02])
    with pytest.raises(ValueError, match="weights sum"):
        compute_combo_nav({"a": a, "b": b}, {"a": 0.6, "b": 0.5})


def test_compute_combo_nav_id_mismatch():
    a = _nav_df([0.0, 0.01])
    with pytest.raises(ValueError, match="differ"):
        compute_combo_nav({"a": a}, {"a": 0.5, "b": 0.5})


def test_compute_combo_nav_empty_intersection():
    """Two NAVs with no overlapping dates → empty combo."""
    a = pd.DataFrame({
        "daily_ret": [0.01],
        "nav": [1.01],
        "cum_ret": [0.01],
    }, index=pd.DatetimeIndex([pd.Timestamp("2026-01-01")]))
    b = pd.DataFrame({
        "daily_ret": [0.02],
        "nav": [1.02],
        "cum_ret": [0.02],
    }, index=pd.DatetimeIndex([pd.Timestamp("2026-12-01")]))
    combo = compute_combo_nav({"a": a, "b": b}, {"a": 0.5, "b": 0.5})
    # No overlapping non-NaN daily_ret → empty
    assert combo.empty


# ---------------------------------------------------------------------------
# compute_rolling_max_drawdown
# ---------------------------------------------------------------------------


def test_rolling_maxdd_simple_3_window():
    # NAV: 1.0, 1.1, 0.9, 1.0
    # window=3 from t=2: [1.0, 1.1, 0.9] → max=1.1 at idx 1, dd@idx2 = 0.9/1.1-1 = -0.1818
    # window=3 from t=3: [1.1, 0.9, 1.0] → max=1.1 at idx 0, dd@idx1 = 0.9/1.1-1 = -0.1818
    nav = pd.Series([1.0, 1.1, 0.9, 1.0])
    dd = compute_rolling_max_drawdown(nav, window=3)
    assert pd.isna(dd.iloc[0]) and pd.isna(dd.iloc[1])
    assert dd.iloc[2] == pytest.approx(-0.1818, abs=1e-3)
    assert dd.iloc[3] == pytest.approx(-0.1818, abs=1e-3)


def test_rolling_maxdd_no_drawdown_returns_zero():
    """Monotonically increasing NAV → max_dd = 0."""
    nav = pd.Series([1.0, 1.05, 1.1, 1.15])
    dd = compute_rolling_max_drawdown(nav, window=3)
    # Only the last 2 indices have full window
    assert dd.iloc[2] == pytest.approx(0.0)
    assert dd.iloc[3] == pytest.approx(0.0)


def test_rolling_maxdd_window_lt_2_raises():
    with pytest.raises(ValueError, match="window must be >= 2"):
        compute_rolling_max_drawdown(pd.Series([1.0, 1.1]), window=1)


# ---------------------------------------------------------------------------
# compute_residual_corr
# ---------------------------------------------------------------------------


def test_residual_corr_perfect_alignment_with_benchmark():
    """If candidate AND anchor are both pure benchmark → residuals = 0 → corr = NaN.

    Pearson of two zero-variance series is undefined. We expect NaN, which
    pandas .corr() returns for constant series.
    """
    rng = pd.date_range("2026-01-01", periods=20)
    bench = pd.Series(np.random.RandomState(0).normal(0.001, 0.01, 20), index=rng)
    cand = bench.copy()  # candidate = benchmark exactly
    anchor = bench.copy() * 1.5  # anchor = 1.5x benchmark, so beta=1.5; residual=0
    corr = compute_residual_corr(cand, anchor, bench)
    # Both residuals are essentially zero → Pearson is NaN, function returns float(nan)
    assert corr is None or pd.isna(corr) or abs(corr) < 1e-9 or pd.isna(corr)


def test_residual_corr_orthogonal_to_benchmark():
    """Construct cand + anchor with idiosyncratic noise → residual corr ~ corr of noise."""
    rng = np.random.RandomState(42)
    bench = pd.Series(rng.normal(0.001, 0.01, 100),
                      index=pd.date_range("2026-01-01", periods=100))
    noise_cand = pd.Series(rng.normal(0, 0.005, 100), index=bench.index)
    noise_anchor = pd.Series(rng.normal(0, 0.005, 100), index=bench.index)
    # cand = 0.5 * bench + noise_cand; anchor = 0.5 * bench + noise_anchor
    # noise_cand and noise_anchor are independent → residual corr ≈ 0
    cand = 0.5 * bench + noise_cand
    anchor = 0.5 * bench + noise_anchor
    corr = compute_residual_corr(cand, anchor, bench)
    assert corr is not None
    assert abs(corr) < 0.20  # within sampling noise of zero


def test_residual_corr_too_few_obs_returns_none():
    bench = pd.Series([0.01, 0.02], index=pd.date_range("2026-01-01", periods=2))
    cand = pd.Series([0.005, 0.015], index=bench.index)
    anchor = pd.Series([0.008, 0.018], index=bench.index)
    assert compute_residual_corr(cand, anchor, bench) is None


# ---------------------------------------------------------------------------
# compute_non_equity_exposure
# ---------------------------------------------------------------------------


def test_non_equity_exposure_pure_equity():
    """All-stock weights → non_equity = 0."""
    m = _build_manifest("test", [
        ("TD001", date(2026, 5, 4), 0.0, {"AAPL": 0.5, "MSFT": 0.5}),
    ])
    df = compute_non_equity_exposure(m)
    # AAPL/MSFT may not be in cluster map → unknown bucket; fail-safe is they go unknown
    # Either way non_equity_weight should be 0 (no bonds/commodities/cash)
    assert df.iloc[0]["non_equity_weight"] == 0.0


def test_non_equity_exposure_cross_asset():
    """Mix of stocks + bonds + commodities + cash."""
    m = _build_manifest("test", [
        ("TD001", date(2026, 5, 4), 0.0, {
            "CLX": 0.30,    # stock (staples_defensive)
            "TLT": 0.25,    # bond_long_duration
            "GLD": 0.20,    # commodity_metals
            "BIL": 0.25,    # cash_anchor
        }),
    ])
    df = compute_non_equity_exposure(m)
    row = df.iloc[0]
    assert row["equity_weight"] == pytest.approx(0.30)
    assert row["bond_weight"] == pytest.approx(0.25)
    assert row["commodity_weight"] == pytest.approx(0.20)
    assert row["cash_anchor_weight"] == pytest.approx(0.25)
    assert row["non_equity_weight"] == pytest.approx(0.70)
    assert row["unknown_weight"] == 0.0


def test_non_equity_exposure_unknown_symbol():
    """Symbol not in unified map → unknown bucket."""
    m = _build_manifest("test", [
        ("TD001", date(2026, 5, 4), 0.0, {"SOXL": 0.5, "CLX": 0.5}),
        # SOXL not in cluster map → unknown
    ])
    df = compute_non_equity_exposure(m)
    row = df.iloc[0]
    assert row["unknown_weight"] == pytest.approx(0.5)
    assert row["equity_weight"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# classify_td60_verdict
# ---------------------------------------------------------------------------


def test_verdict_insufficient_when_below_min_td():
    v = classify_td60_verdict(
        n_observed=20,
        residual_corr_max_vs_anchors=0.3,
        bull_vs_qqq_60d=-0.01,
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "INSUFFICIENT"
    assert "n_observed=20 < require_td_min=60" in v.reasons[0]


def test_verdict_insufficient_when_required_input_missing():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=None,  # missing
        bull_vs_qqq_60d=-0.01,
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "INSUFFICIENT"
    assert "missing inputs" in v.reasons[0]


def test_verdict_green_all_pass():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.30,  # < 0.4 pass
        bull_vs_qqq_60d=-0.01,              # > -0.03 pass
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "GREEN"


def test_verdict_yellow_when_residual_in_soft_band():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.50,  # in [0.4, 0.6] → soft_fail
        bull_vs_qqq_60d=-0.01,
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "YELLOW"
    assert v.triggers["residual_corr"] == "soft_fail"


def test_verdict_red_when_residual_above_hard_threshold():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.65,  # > 0.6 hard_fail
        bull_vs_qqq_60d=-0.01,
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "RED"


def test_verdict_red_when_combo_negative():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.30,
        bull_vs_qqq_60d=-0.01,
        portfolio_combo_positive=False,  # hard fail
        soft_warn_cleared=True,
    )
    assert v.label == "RED"
    assert v.triggers["portfolio_combo"] == "hard_fail"


def test_verdict_red_when_soft_warn_uncleared():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.30,
        bull_vs_qqq_60d=-0.01,
        portfolio_combo_positive=True,
        soft_warn_cleared=False,  # hard fail
    )
    assert v.label == "RED"
    assert v.triggers["soft_warn_cleared"] == "hard_fail"


def test_verdict_yellow_when_bull_vs_qqq_in_soft_band():
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.30,
        bull_vs_qqq_60d=-0.05,  # in [-0.10, -0.03] → soft_fail
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "YELLOW"
    assert v.triggers["bull_vs_qqq"] == "soft_fail"


def test_verdict_red_dominates_yellow():
    """Mixed soft + hard → RED wins."""
    v = classify_td60_verdict(
        n_observed=60,
        residual_corr_max_vs_anchors=0.50,  # soft
        bull_vs_qqq_60d=-0.15,              # hard
        portfolio_combo_positive=True,
        soft_warn_cleared=True,
    )
    assert v.label == "RED"


# ---------------------------------------------------------------------------
# generate_attention_report (integration / graceful degradation)
# ---------------------------------------------------------------------------


def test_generate_report_empty_candidate_manifest():
    """No runs at all → graceful empty report, no exception."""
    cand = _build_manifest("trial9", [])
    anchors = {"rcm": _build_manifest("rcm", [])}
    rep = generate_attention_report(
        candidate_manifest=cand,
        anchor_manifests=anchors,
    )
    assert isinstance(rep, AttentionReport)
    assert rep.candidate_id == "trial9"
    assert rep.n_observed == 0
    assert rep.td_label == "TD000"
    assert rep.candidate_metrics == {}


def test_generate_report_includes_soft_warn_flags():
    cand = _build_manifest(
        "trial9", [],
        soft_warn_flags=["diversifier_2025_maxdd_18_20pct"],
    )
    anchors = {"rcm": _build_manifest("rcm", [])}
    rep = generate_attention_report(
        candidate_manifest=cand,
        anchor_manifests=anchors,
    )
    assert "diversifier_2025_maxdd_18_20pct" in rep.soft_warn_status
    # n_observed=0 < window=60 → pending_insufficient_data
    assert rep.soft_warn_status["diversifier_2025_maxdd_18_20pct"] == \
        "pending_insufficient_data"


def test_generate_report_to_dict_roundtrip():
    """Report serializes to dict cleanly (no non-JSON types except date strs)."""
    cand = _build_manifest("trial9", [])
    rep = generate_attention_report(
        candidate_manifest=cand,
        anchor_manifests={},
    )
    d = rep.to_dict()
    import json
    s = json.dumps(d, default=str)
    assert "trial9" in s
    assert d["n_observed"] == 0


def test_generate_report_n_observed_reflects_real_runs():
    cand = _build_manifest("trial9", [
        ("TD001", date(2026, 5, 4), 0.0, None),
        ("TD002", date(2026, 5, 5), 0.01, None),
        ("DECIDE", date(2026, 5, 5), None, None),  # not counted
    ])
    rep = generate_attention_report(
        candidate_manifest=cand,
        anchor_manifests={},
    )
    assert rep.n_observed == 2
    assert rep.td_label == "TD002"
