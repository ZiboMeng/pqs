"""Unit tests for core/research/taa/regime_label_generator.py (PRD-E §4.4)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.taa.regime_label_generator import (
    daily_regime_labels,
    manual_regime_labels,
    monthly_regime_labels,
    regime_label_hamming_distance,
    regime_label_kl_divergence,
)


# ── monthly_regime_labels ────────────────────────────────────────────────────


def _make_daily(n_days: int = 60, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_days, freq="B")
    states = [s.value for s in RegimeState]
    return pd.Series(rng.choice(states, n_days), index=dates, dtype=str)


def test_monthly_resamples_daily_to_month_start():
    daily = _make_daily(n_days=120)  # ~6 months
    monthly = monthly_regime_labels(daily, cadence="MS")
    # 6 months → 6 entries
    assert 4 <= len(monthly) <= 7  # depends on month boundary alignment
    # Each value must be a valid RegimeState string
    valid = {s.value for s in RegimeState}
    assert set(monthly.unique()).issubset(valid)


def test_monthly_cadence_d_returns_daily_unchanged():
    daily = _make_daily(n_days=30)
    out = monthly_regime_labels(daily, cadence="D")
    pd.testing.assert_series_equal(out, daily)


def test_monthly_handles_empty_input():
    empty = pd.Series(dtype=str)
    out = monthly_regime_labels(empty)
    assert out.empty


def test_monthly_first_label_per_month():
    """Each month-start row should equal the FIRST trading day's label
    of that month (resample.first() invariant)."""
    dates = pd.date_range("2020-01-01", periods=20, freq="B")
    labels = pd.Series(
        ["BULL"] * 10 + ["CRISIS"] * 10, index=dates, dtype=str,
    )
    monthly = monthly_regime_labels(labels)
    # First Jan trading day = 2020-01-01 (BULL)
    assert monthly.iloc[0] == "BULL"


# ── manual_regime_labels ────────────────────────────────────────────────────


def test_manual_regime_labels_expands_year_tags():
    idx = pd.date_range("2020-01-01", "2020-12-31", freq="B")
    out = manual_regime_labels({2020: "CRISIS"}, idx)
    assert (out == "CRISIS").all()
    assert len(out) == len(idx)


def test_manual_regime_labels_unmapped_year_defaults_neutral():
    idx = pd.date_range("2018-01-01", "2018-12-31", freq="B")
    out = manual_regime_labels({}, idx)  # 2018 not in tags
    assert (out == "NEUTRAL").all()


def test_manual_regime_labels_invalid_value_raises():
    idx = pd.date_range("2020-01-01", periods=5, freq="B")
    with pytest.raises(ValueError, match="non-RegimeState values"):
        manual_regime_labels({2020: "TURBULENT"}, idx)


def test_manual_regime_labels_multi_year():
    idx = pd.date_range("2018-01-01", "2019-12-31", freq="B")
    out = manual_regime_labels({2018: "RISK_OFF", 2019: "BULL"}, idx)
    assert (out[out.index.year == 2018] == "RISK_OFF").all()
    assert (out[out.index.year == 2019] == "BULL").all()


# ── KL divergence ───────────────────────────────────────────────────────────


def test_kl_zero_when_distributions_identical():
    idx = pd.date_range("2020-01-01", periods=30, freq="B")
    s = pd.Series(["BULL"] * 15 + ["RISK_OFF"] * 15, index=idx, dtype=str)
    kl = regime_label_kl_divergence(s, s)
    assert kl < 0.001  # near zero


def test_kl_positive_when_distributions_differ():
    idx = pd.date_range("2020-01-01", periods=30, freq="B")
    s_a = pd.Series(["BULL"] * 30, index=idx, dtype=str)
    s_b = pd.Series(["CRISIS"] * 30, index=idx, dtype=str)
    kl = regime_label_kl_divergence(s_a, s_b)
    assert kl > 1.0  # very different


def test_kl_handles_empty():
    empty = pd.Series(dtype=str)
    s = pd.Series(["BULL"], dtype=str, index=[pd.Timestamp("2020-01-01")])
    assert math.isnan(regime_label_kl_divergence(empty, s))
    assert math.isnan(regime_label_kl_divergence(s, empty))


def test_kl_smoothing_avoids_log_zero():
    """If one series has a regime not present in the other, KL must
    still be finite (smoothing prevents log(0))."""
    idx_a = pd.date_range("2020-01-01", periods=5, freq="B")
    idx_b = pd.date_range("2020-01-01", periods=5, freq="B")
    s_a = pd.Series(["BULL"] * 5, index=idx_a, dtype=str)  # no CRISIS
    s_b = pd.Series(["BULL"] * 4 + ["CRISIS"], index=idx_b, dtype=str)
    kl = regime_label_kl_divergence(s_a, s_b)
    assert math.isfinite(kl)


# ── Hamming distance ────────────────────────────────────────────────────────


def test_hamming_zero_when_aligned_identical():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    s = pd.Series(["BULL"] * 10, index=idx, dtype=str)
    assert regime_label_hamming_distance(s, s) == 0.0


def test_hamming_one_when_completely_different():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    a = pd.Series(["BULL"] * 10, index=idx, dtype=str)
    b = pd.Series(["CRISIS"] * 10, index=idx, dtype=str)
    assert regime_label_hamming_distance(a, b) == 1.0


def test_hamming_partial_disagreement():
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    a = pd.Series(["BULL"] * 10, index=idx, dtype=str)
    b = pd.Series(["BULL"] * 7 + ["CRISIS"] * 3, index=idx, dtype=str)
    h = regime_label_hamming_distance(a, b)
    assert abs(h - 0.30) < 1e-9


def test_hamming_only_intersection_index():
    """Hamming computed only on joint index — partial overlap counts
    only shared days."""
    idx_a = pd.date_range("2020-01-01", periods=20, freq="B")
    idx_b = pd.date_range("2020-01-08", periods=20, freq="B")
    # idx_a[7:] overlaps idx_b[:13] (~13 shared days)
    a = pd.Series(["BULL"] * 20, index=idx_a, dtype=str)
    b = pd.Series(["BULL"] * 20, index=idx_b, dtype=str)
    h = regime_label_hamming_distance(a, b)
    assert math.isfinite(h)
    assert h == 0.0  # both BULL where they overlap


def test_hamming_empty_intersection_returns_nan():
    idx_a = pd.date_range("2020-01-01", periods=5, freq="B")
    idx_b = pd.date_range("2021-01-01", periods=5, freq="B")
    a = pd.Series(["BULL"] * 5, index=idx_a, dtype=str)
    b = pd.Series(["BULL"] * 5, index=idx_b, dtype=str)
    h = regime_label_hamming_distance(a, b)
    assert math.isnan(h)


# ── daily_regime_labels integration smoke (synthetic SPY/VIX) ───────────────


def test_daily_regime_labels_schema_with_real_detector():
    """Smoke test of RegimeDetector.classify_series schema (PRD-E I14
    verification): synthetic SPY (uptrend) + VIX (low) → classifier
    produces a valid pd.Series of RegimeState string values aligned
    to the joint index."""
    from core.config.loader import load_config
    from core.regime.regime_detector import RegimeDetector
    from pathlib import Path

    cfg = load_config(Path("config"))
    detector = RegimeDetector(config=cfg.regime)

    # 60 trading days of synthetic uptrend + low VIX
    idx = pd.date_range("2020-01-01", periods=60, freq="B")
    spy = pd.Series(np.linspace(300, 400, len(idx)), index=idx)
    vix = pd.Series(15.0, index=idx)
    out = daily_regime_labels(spy, vix, detector)
    assert isinstance(out, pd.Series)
    # Index aligned to the joint SPY/VIX index
    assert len(out) == len(idx)
    # Values are valid RegimeState strings
    valid = {s.value for s in RegimeState}
    assert set(out.unique()).issubset(valid)
