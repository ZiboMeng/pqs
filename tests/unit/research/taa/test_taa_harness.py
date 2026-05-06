"""Unit tests for core/research/taa/taa_harness.py (PRD-E v1.1 §4.4)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core.regime.regime_detector import RegimeState
from core.research.taa.regime_rules import (
    DEFAULT_TAA_RULES_V0_MINIMAL,
    DEFAULT_TAA_RULES_V1,
)
from core.research.taa.taa_harness import (
    TaaBacktestResult,
    run_taa_backtest,
)


def _stub_lookup(sym: str) -> str:
    return {
        "AAPL": "equities", "MSFT": "equities",
        "TLT": "bonds", "IEF": "bonds",
        "GLD": "commodities",
        "BIL": "cash_anchor",
    }.get(sym, "equities")


def _build_panel(n_days: int = 504, seed: int = 0):
    """Build (panel, daily_regime_labels, spy_series) for end-to-end harness test.

    n_days = 504 ≈ 2 calendar years; 2 calendar years × 12 months = 24
    rebalance dates at monthly cadence — enough to exercise the
    full pipeline.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n_days, freq="B")
    syms = ["AAPL", "MSFT", "TLT", "IEF", "GLD", "BIL"]
    # Synthetic price paths
    close = pd.DataFrame(index=dates, columns=syms, dtype=float)
    open_ = pd.DataFrame(index=dates, columns=syms, dtype=float)
    for sym in syms:
        # Different drift per symbol for variety
        drift = {"AAPL": 0.0008, "MSFT": 0.0007, "TLT": 0.0001,
                 "IEF": 0.00005, "GLD": 0.0003, "BIL": 0.00002}.get(sym, 0.0)
        vol = {"AAPL": 0.015, "MSFT": 0.014, "TLT": 0.005,
               "IEF": 0.003, "GLD": 0.010, "BIL": 0.0005}.get(sym, 0.01)
        rets = rng.normal(drift, vol, size=n_days)
        prices = 100.0 * np.cumprod(1 + rets)
        close[sym] = prices
        open_[sym] = prices * (1 + rng.normal(0, 0.001, size=n_days))
    panel = {
        "close": close,
        "open": open_,
        "high": close, "low": close, "volume": pd.DataFrame(1e9, index=dates, columns=syms),
    }
    # Synthetic SPY series
    spy = pd.Series(
        300.0 * np.cumprod(1 + rng.normal(0.0006, 0.012, size=n_days)),
        index=dates, name="SPY",
    )
    # Daily regime labels — alternate between BULL and CRISIS by quarter
    # to exercise per-regime slicing
    labels = []
    for d in dates:
        q = (d.month - 1) // 3
        regime = ["BULL", "CAUTIOUS", "RISK_OFF", "BULL"][q]
        labels.append(regime)
    daily_labels = pd.Series(labels, index=dates, dtype=str)
    return panel, daily_labels, spy


def test_run_taa_backtest_v0_minimal_end_to_end():
    """End-to-end smoke: V0_MINIMAL on 2-year synthetic panel produces a
    TaaBacktestResult with non-empty NAV and per-regime metrics."""
    panel, daily_labels, spy = _build_panel(n_days=504)
    result = run_taa_backtest(
        panel,
        daily_labels,
        DEFAULT_TAA_RULES_V0_MINIMAL,
        universe=["AAPL", "MSFT", "TLT", "IEF"],
        cadence="MS",
        spy_series=spy,
        rule_set_name="v0_minimal",
        asset_class_lookup=_stub_lookup,
    )
    assert isinstance(result, TaaBacktestResult)
    assert len(result.nav) > 0
    assert len(result.weights) > 0
    assert "cum_ret" in result.metrics_full_period
    assert "sharpe" in result.metrics_full_period
    assert "max_dd" in result.metrics_full_period
    assert "calmar" in result.metrics_full_period
    # Per-regime metrics: should have entries for BULL / CAUTIOUS / RISK_OFF
    assert "BULL" in result.metrics_per_regime
    assert "CAUTIOUS" in result.metrics_per_regime
    assert "RISK_OFF" in result.metrics_per_regime
    # vs-SPY comparison populated
    assert "taa" in result.vs_spy_comparison
    assert "spy_buy_hold" in result.vs_spy_comparison


def test_run_taa_backtest_v1_full_4_classes():
    """V1 rule set with 4-class universe runs end-to-end."""
    panel, daily_labels, spy = _build_panel(n_days=504)
    result = run_taa_backtest(
        panel,
        daily_labels,
        DEFAULT_TAA_RULES_V1,
        universe=["AAPL", "MSFT", "TLT", "IEF", "GLD", "BIL"],
        cadence="MS",
        spy_series=spy,
        rule_set_name="v1",
        asset_class_lookup=_stub_lookup,
    )
    assert isinstance(result, TaaBacktestResult)
    assert result.rule_set_name == "v1"
    assert len(result.nav) > 0


def test_run_taa_backtest_per_year_metrics():
    """Per-validation-year metrics populated when years overlap."""
    panel, daily_labels, spy = _build_panel(n_days=504)
    result = run_taa_backtest(
        panel,
        daily_labels,
        DEFAULT_TAA_RULES_V0_MINIMAL,
        universe=["AAPL", "MSFT", "TLT"],
        spy_series=spy,
        validation_years=[2020, 2021],
        asset_class_lookup=_stub_lookup,
    )
    assert 2020 in result.metrics_per_validation_year
    assert 2021 in result.metrics_per_validation_year
    for y in (2020, 2021):
        m = result.metrics_per_validation_year[y]
        assert "cum_ret" in m
        assert "max_dd" in m
        assert "vs_spy" in m  # vs-SPY computed when spy_series provided


def test_run_taa_backtest_stress_slices():
    """Per-stress-slice metrics populated."""
    panel, daily_labels, spy = _build_panel(n_days=504)
    result = run_taa_backtest(
        panel,
        daily_labels,
        DEFAULT_TAA_RULES_V0_MINIMAL,
        universe=["AAPL", "MSFT", "TLT"],
        stress_slices={"q2_2020": ("2020-04-01", "2020-06-30")},
        asset_class_lookup=_stub_lookup,
    )
    assert "q2_2020" in result.metrics_per_stress_slice
    sm = result.metrics_per_stress_slice["q2_2020"]
    assert "max_dd" in sm


def test_run_taa_backtest_daily_cadence_variant():
    """I16 sensitivity: daily cadence variant runs (more rebalance dates,
    higher turnover; for synthetic 504-day panel it's 504 vs ~24)."""
    panel, daily_labels, spy = _build_panel(n_days=252)
    result_monthly = run_taa_backtest(
        panel, daily_labels, DEFAULT_TAA_RULES_V0_MINIMAL,
        universe=["AAPL", "MSFT", "TLT"], cadence="MS",
        asset_class_lookup=_stub_lookup,
    )
    result_daily = run_taa_backtest(
        panel, daily_labels, DEFAULT_TAA_RULES_V0_MINIMAL,
        universe=["AAPL", "MSFT", "TLT"], cadence="D",
        asset_class_lookup=_stub_lookup,
    )
    # Daily variant has way more rebalance dates
    assert len(result_daily.rebalance_dates) > len(result_monthly.rebalance_dates) * 5


def test_run_taa_backtest_calmar_finite():
    """Calmar = CAGR / |MaxDD| produces finite value when MaxDD > 0."""
    panel, daily_labels, spy = _build_panel(n_days=504)
    result = run_taa_backtest(
        panel, daily_labels, DEFAULT_TAA_RULES_V0_MINIMAL,
        universe=["AAPL", "MSFT", "TLT"],
        spy_series=spy, asset_class_lookup=_stub_lookup,
    )
    calmar = result.metrics_full_period.get("calmar")
    assert calmar is not None
    # Not NaN. May be inf if MaxDD ~ 0 on lucky synthetic path, but
    # typically finite on a 2-year random walk
    assert not math.isnan(calmar)


def test_run_taa_backtest_invalid_universe_raises():
    """Universe missing a class with non-zero allocation in the rule set
    raises (V1 requires commodities + cash_anchor)."""
    panel, daily_labels, _ = _build_panel(n_days=252)
    with pytest.raises(ValueError, match="no .* symbols"):
        run_taa_backtest(
            panel, daily_labels, DEFAULT_TAA_RULES_V1,
            universe=["AAPL", "TLT"],  # missing commodities + cash
            asset_class_lookup=_stub_lookup,
        )


def test_run_taa_backtest_empty_labels_raises():
    """Empty daily labels at the requested cadence raises."""
    panel, _, _ = _build_panel(n_days=10)
    empty_labels = pd.Series(dtype=str)
    with pytest.raises(ValueError, match="empty index"):
        run_taa_backtest(
            panel, empty_labels, DEFAULT_TAA_RULES_V0_MINIMAL,
            universe=["AAPL", "TLT"],
            asset_class_lookup=_stub_lookup,
        )
