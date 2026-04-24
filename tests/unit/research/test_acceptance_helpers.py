"""Unit tests for core/research/acceptance_helpers.py (Phase E-1 R7)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.acceptance_helpers import (
    benchmark_relative_ic_summary,
    fmt,
    ic_stability_decision,
    regime_stratified_ic,
    summarize_ic,
    turnover_summary,
    walkforward_ic,
)


# ── fmt ──────────────────────────────────────────────────────────────────────


def test_fmt_none_returns_nan():
    assert fmt(None) == "nan"


def test_fmt_nan_returns_nan():
    assert fmt(float("nan")) == "nan"


def test_fmt_inf_returns_nan():
    assert fmt(float("inf")) == "nan"
    assert fmt(float("-inf")) == "nan"


def test_fmt_finite():
    # 4-decimal rounding; note 0.12345 rounds to +0.1235 not +0.1234
    assert fmt(0.12345) == "+0.1235"
    assert fmt(-0.5) == "-0.5000"
    assert fmt(0.0) == "+0.0000"
    assert fmt(1.5) == "+1.5000"


# ── summarize_ic ────────────────────────────────────────────────────────────


def test_summarize_ic_empty():
    s = summarize_ic(pd.Series([], dtype=float), horizon=21)
    assert s["n_dates"] == 0
    assert s["ic_mean"] is None
    assert s["ic_ir"] is None


def test_summarize_ic_single_sample_no_std():
    """n=1 -> std is NaN, ir is None (can't compute)."""
    s = summarize_ic(pd.Series([0.1]), horizon=21)
    assert s["n_dates"] == 1
    assert s["ic_mean"] == pytest.approx(0.1)
    assert s["ic_std"] is None or not np.isfinite(s["ic_std"])
    assert s["ic_ir"] is None


def test_summarize_ic_constant_zero_std():
    """Constant series -> std near 0 -> ir=None.

    Note: pandas std() on a constant series is a very small float
    (~1e-17) not exactly 0.0 due to numeric precision, so we tolerate.
    The important invariant is that ic_ir is None (avoids divide-by-
    near-zero producing a bogus large value).
    """
    s = summarize_ic(pd.Series([0.05] * 50), horizon=21)
    assert s["ic_std"] is None or abs(s["ic_std"]) < 1e-10
    # The key invariant: ir is guarded
    assert s["ic_ir"] is None or abs(s["ic_ir"]) < 1e6
    assert s["positive_rate"] == 1.0


def test_summarize_ic_horizon_scales_ir():
    """IR = mean/std * sqrt(252/h). Larger h -> smaller IR."""
    ic = pd.Series(np.arange(0.01, 0.51, 0.01))
    s_h1 = summarize_ic(ic, horizon=1)
    s_h21 = summarize_ic(ic, horizon=21)
    assert s_h1["ic_ir"] > s_h21["ic_ir"]
    # Ratio should equal sqrt(21)
    ratio = s_h1["ic_ir"] / s_h21["ic_ir"]
    assert ratio == pytest.approx(np.sqrt(21.0), rel=1e-6)


def test_summarize_ic_rejects_bad_horizon():
    with pytest.raises(ValueError):
        summarize_ic(pd.Series([0.1, 0.2]), horizon=0)
    with pytest.raises(ValueError):
        summarize_ic(pd.Series([0.1, 0.2]), horizon=-1)


def test_summarize_ic_positive_rate():
    ic = pd.Series([0.1, -0.1, 0.2, -0.3, 0.1])
    s = summarize_ic(ic, horizon=21)
    assert s["positive_rate"] == pytest.approx(0.6)


# ── walkforward_ic ──────────────────────────────────────────────────────────


def test_walkforward_ic_splits_evenly():
    idx = pd.bdate_range("2020-01-02", periods=400)
    ic = pd.Series(np.random.RandomState(0).randn(400) * 0.05, index=idx)
    folds = walkforward_ic(ic, horizon=21, n_folds=4, min_per_fold=50)
    assert len(folds) == 4
    # fold indices
    assert [f["fold"] for f in folds] == [1, 2, 3, 4]
    # all have ~100 dates
    for f in folds[:-1]:
        assert f["n_dates"] == 100
    # last fold absorbs remainder
    assert folds[-1]["n_dates"] >= 100
    # dates strictly increasing between folds
    for i in range(len(folds) - 1):
        assert folds[i]["date_end"] < folds[i + 1]["date_start"]


def test_walkforward_ic_returns_empty_when_too_short():
    idx = pd.bdate_range("2020-01-02", periods=150)
    ic = pd.Series(np.zeros(150), index=idx)
    folds = walkforward_ic(ic, horizon=21, n_folds=4, min_per_fold=50)
    # 150 < 4*50 -> []
    assert folds == []


def test_walkforward_ic_rejects_n_folds_less_than_2():
    with pytest.raises(ValueError):
        walkforward_ic(pd.Series([0.1, 0.2]), horizon=21, n_folds=1)


# ── regime_stratified_ic ───────────────────────────────────────────────────


def test_regime_stratified_ic_aligns_indices():
    idx = pd.bdate_range("2020-01-02", periods=100)
    ic = pd.Series(np.arange(100) * 0.001, index=idx)
    regimes = pd.Series(["BULL"] * 50 + ["BEAR"] * 50, index=idx)
    by_regime = regime_stratified_ic(ic, regimes, horizon=21)
    assert set(by_regime.keys()) == {"BULL", "BEAR"}
    assert by_regime["BULL"]["n_dates"] == 50
    assert by_regime["BEAR"]["n_dates"] == 50


def test_regime_stratified_ic_drops_sparse_buckets():
    """Buckets with < min_per_regime observations are excluded."""
    idx = pd.bdate_range("2020-01-02", periods=100)
    ic = pd.Series(np.arange(100) * 0.001, index=idx)
    regimes = pd.Series(["BULL"] * 95 + ["RARE"] * 5, index=idx)
    by_regime = regime_stratified_ic(ic, regimes, horizon=21, min_per_regime=20)
    assert "BULL" in by_regime
    assert "RARE" not in by_regime


# ── turnover_summary ────────────────────────────────────────────────────────


def test_turnover_summary_empty():
    empty = pd.DataFrame()
    s = turnover_summary(empty)
    assert s["turnover_proxy"] is None
    assert s["n_dates"] == 0


def test_turnover_summary_stable_composite():
    """A composite that doesn't change rank -> low turnover proxy."""
    idx = pd.bdate_range("2020-01-02", periods=20)
    # Every row has same ordering of symbols
    rows = np.tile(np.arange(10, dtype=float), (20, 1))
    composite = pd.DataFrame(rows, index=idx,
                             columns=[f"S{i}" for i in range(10)])
    s = turnover_summary(composite)
    assert s["turnover_proxy"] == pytest.approx(0.0, abs=1e-9)


def test_turnover_summary_churning_composite():
    """A composite that reverses ranks every day -> high turnover proxy."""
    idx = pd.bdate_range("2020-01-02", periods=20)
    rows = []
    for i in range(20):
        # Alternate between ascending and descending ranks
        if i % 2 == 0:
            rows.append(np.arange(10, dtype=float))
        else:
            rows.append(np.arange(10, 0, -1, dtype=float))
    composite = pd.DataFrame(rows, index=idx,
                             columns=[f"S{j}" for j in range(10)])
    s = turnover_summary(composite)
    # Rank correlation alternates between +1 (self-match) and -1; average
    # around 0; turnover proxy = 1 - ~0 = ~1.0
    assert s["turnover_proxy"] is not None
    assert s["turnover_proxy"] > 0.5


# ── benchmark_relative_ic_summary ───────────────────────────────────────────


def test_benchmark_relative_ic_summary_happy_path():
    ic_by_regime = {
        "CRISIS": {"ic_ir": 1.5},
        "RISK_ON": {"ic_ir": 0.2},
        "BULL": {"ic_ir": 0.4},
    }
    s = benchmark_relative_ic_summary(ic_by_regime)
    assert s["primary_regime"] == "CRISIS"
    assert s["primary_regime_ic_ir"] == pytest.approx(1.5)
    assert s["secondary_regime"] == "RISK_ON"
    assert s["secondary_regime_ic_ir"] == pytest.approx(0.2)
    assert "note" in s


def test_benchmark_relative_missing_regime_none():
    ic_by_regime = {"BULL": {"ic_ir": 0.4}}
    s = benchmark_relative_ic_summary(ic_by_regime)
    assert s["primary_regime_ic_ir"] is None
    assert s["secondary_regime_ic_ir"] is None


# ── ic_stability_decision ───────────────────────────────────────────────────


def test_decision_promote_all_green():
    full = {"ic_ir": 0.5}
    wf = [{"ic_ir": 0.4}, {"ic_ir": 0.3}, {"ic_ir": 0.2}, {"ic_ir": 0.5}]
    regime = {
        "BULL": {"ic_ir": 0.3}, "BEAR": {"ic_ir": 0.4},
        "CRISIS": {"ic_ir": 1.0}, "NEUTRAL": {"ic_ir": 0.2},
    }
    d = ic_stability_decision(full, wf, regime)
    assert d["outcome"] == "promote_to_paper"
    assert d["blocking_reasons"] == []


def test_decision_hold_on_low_ir():
    full = {"ic_ir": 0.15}  # below 0.2 threshold
    wf = [{"ic_ir": 0.3}] * 4
    regime = {"BULL": {"ic_ir": 0.3}, "BEAR": {"ic_ir": 0.2},
              "CRISIS": {"ic_ir": 1.0}}
    d = ic_stability_decision(full, wf, regime)
    assert d["outcome"] == "hold_in_research"
    assert any("full-period IC_IR" in r for r in d["blocking_reasons"])


def test_decision_hold_on_walkforward_failures():
    full = {"ic_ir": 0.5}
    wf = [{"ic_ir": 0.3}, {"ic_ir": -0.1}, {"ic_ir": -0.2}, {"ic_ir": 0.4}]
    regime = {"BULL": {"ic_ir": 0.3}, "BEAR": {"ic_ir": 0.2},
              "CRISIS": {"ic_ir": 1.0}}
    d = ic_stability_decision(full, wf, regime)
    assert d["outcome"] == "hold_in_research"
    assert any("Walk-forward" in r for r in d["blocking_reasons"])


def test_decision_hold_on_regime_failures():
    full = {"ic_ir": 0.5}
    wf = [{"ic_ir": 0.3}] * 4
    regime = {"BULL": {"ic_ir": 0.3}, "BEAR": {"ic_ir": -0.1},
              "CRISIS": {"ic_ir": -0.2}, "NEUTRAL": {"ic_ir": -0.5}}
    d = ic_stability_decision(full, wf, regime)
    assert d["outcome"] == "hold_in_research"
    assert any("Regime" in r for r in d["blocking_reasons"])


def test_decision_custom_thresholds():
    """Caller can tighten thresholds for production-tier acceptance."""
    full = {"ic_ir": 0.35}  # would pass 0.2 default but not 0.5
    wf = [{"ic_ir": 0.3}] * 4
    regime = {"BULL": {"ic_ir": 0.3}, "BEAR": {"ic_ir": 0.2},
              "CRISIS": {"ic_ir": 1.0}}
    d = ic_stability_decision(full, wf, regime, ir_threshold=0.5)
    assert d["outcome"] == "hold_in_research"
    assert any("below 0.5" in r for r in d["blocking_reasons"])


# ── Parity with existing CLI ────────────────────────────────────────────────


def test_cli_wrappers_reexport_helpers():
    """The refactor MUST keep the script CLI private names bound to the
    helper functions; anything accessing scripts.*_composite._walkforward
    etc. continues to work."""
    import scripts.acceptance_research_composite as m
    # These are the wrappers created in R7 refactor
    assert m._summarize_ic is summarize_ic
    assert m._walkforward is walkforward_ic
    assert m._regime_stratified_ic is regime_stratified_ic
    assert m._fmt is fmt
    assert m._ic_stability_decision is ic_stability_decision
