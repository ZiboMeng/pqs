"""Unit tests for core/research/taa/taa_acceptance.py (PRD-E §5.3)."""

from __future__ import annotations

import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.taa.taa_acceptance import (
    TaaAcceptanceResult,
    TaaGateResult,
    evaluate_taa_acceptance,
)
from core.research.taa.taa_harness import TaaBacktestResult


def _make_result(
    *, calmar=0.5, max_dd=-0.10, vs_2018=0.05, vs_2025=0.02,
    stress_dd=-0.15, year_dd=-0.10,
) -> TaaBacktestResult:
    """Synthesize a TaaBacktestResult satisfying all 7 gates by default."""
    idx = pd.date_range("2018-01-02", periods=200, freq="B")
    nav = pd.Series(range(100, 300), index=idx, dtype=float)
    daily_ret = nav.pct_change().fillna(0.0)
    return TaaBacktestResult(
        nav=nav, weights=pd.DataFrame(0.5, index=idx, columns=["A", "B"]),
        daily_returns=daily_ret,
        metrics_full_period={
            "cum_ret": 1.5, "cagr": 0.10, "sharpe": 1.5,
            "max_dd": max_dd, "calmar": calmar,
        },
        metrics_per_validation_year={
            2018: {"max_dd": year_dd, "vs_spy": vs_2018, "vs_qqq": 0.0,
                   "cum_ret": 0.05},
            2025: {"max_dd": year_dd, "vs_spy": vs_2025, "vs_qqq": 0.0,
                   "cum_ret": 0.02},
        },
        metrics_per_stress_slice={
            "covid_flash": {"max_dd": stress_dd, "cum_ret": -0.10, "sharpe": 0.0},
            "rate_hike_2022": {"max_dd": stress_dd, "cum_ret": -0.05, "sharpe": 0.0},
        },
        metrics_per_regime={},
        vs_spy_comparison={},
        rule_set_name="v1",
        cadence="MS",
        n_observed_days=200,
    )


def _spy_metrics(*, calmar=0.30, max_dd=-0.34) -> dict:
    return {"cum_ret": 1.0, "cagr": 0.08, "sharpe": 0.6,
            "max_dd": max_dd, "calmar": calmar}


def test_all_gates_pass_yields_overall_passed():
    res = _make_result()
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert out.overall_passed is True
    assert out.n_passed == out.n_total
    assert out.failed_gates == []


def test_g1_2018_negative_fails():
    """If 2018 vs SPY is negative, G1 fails (single BEAR year primary value)."""
    res = _make_result(vs_2018=-0.03)
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert "g1_2018_vs_spy_positive" in out.failed_gates
    assert out.overall_passed is False


def test_g2_2025_negative_fails():
    res = _make_result(vs_2025=-0.05)
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert "g2_2025_vs_spy_positive" in out.failed_gates


def test_g3_stress_slice_too_deep_fails():
    res = _make_result(stress_dd=-0.30)  # exceeds -25%
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert "g3_stress_slice_maxdd" in out.failed_gates


def test_g4_per_year_maxdd_too_deep_fails():
    res = _make_result(year_dd=-0.25)  # exceeds -20%
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert "g4_per_year_maxdd" in out.failed_gates


def test_g6_calmar_below_spy_fails():
    res = _make_result(calmar=0.10)  # SPY is 0.30
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert "g6_calmar_ge_spy" in out.failed_gates


def test_g7_full_period_maxdd_worse_than_spy_fails():
    """TAA MaxDD -40% deeper than SPY -34% → G7 fails."""
    res = _make_result(max_dd=-0.40)
    out = evaluate_taa_acceptance(
        res, spy_metrics_full_period=_spy_metrics(max_dd=-0.34),
    )
    assert "g7_full_period_maxdd_better_than_spy" in out.failed_gates


def test_g5_skipped_when_no_returns_provided():
    """G5 (beta-in-BULL) is skipped (PASS with note) when caller doesn't
    provide spy_daily_returns + daily_regime_labels."""
    res = _make_result()
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    g5 = next(g for g in out.gates if g.name == "g5_bull_beta_to_spy")
    assert g5.passed is True
    assert "SKIPPED" in g5.notes


def test_g5_computes_beta_when_inputs_provided():
    """G5 with synthetic SPY-correlated TAA returns: beta should be ~1.0
    in BULL → G5 fails (> 0.85 ceiling)."""
    import numpy as np
    res = _make_result()
    # Make TAA daily returns track SPY 1:1 (so BULL beta ~1.0)
    n = len(res.daily_returns)
    rng = np.random.default_rng(0)
    spy_ret = pd.Series(rng.normal(0.0005, 0.01, size=n), index=res.daily_returns.index)
    taa_ret = spy_ret * 1.0 + rng.normal(0, 0.001, size=n)
    res.daily_returns.loc[:] = taa_ret.values
    labels = pd.Series(["BULL"] * n, index=res.daily_returns.index, dtype=str)
    out = evaluate_taa_acceptance(
        res, spy_metrics_full_period=_spy_metrics(),
        spy_daily_returns=spy_ret,
        daily_regime_labels=labels,
    )
    g5 = next(g for g in out.gates if g.name == "g5_bull_beta_to_spy")
    # beta ~1.0 > 0.85 → fails
    assert g5.passed is False


def test_acceptance_result_summary_methods():
    res = _make_result()
    out = evaluate_taa_acceptance(res, spy_metrics_full_period=_spy_metrics())
    assert isinstance(out.gates, list)
    assert out.n_total == 7  # G1-G7
    assert out.rule_set_name == "v1"
    assert out.cadence == "MS"
