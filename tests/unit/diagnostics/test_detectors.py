"""Tests for diagnostic detectors."""

import numpy as np
import pandas as pd
import pytest

from core.diagnostics.detectors import (
    DiagnosticResult,
    FactorDecayDetector,
    CostDriftDetector,
    StrategyAlphaDetector,
    PaperBacktestDivergenceDetector,
    DiagnosticSuite,
)


def _make_ic_series(n=200, base_ic=0.05, decay_frac=0.0):
    np.random.seed(42)
    ic = np.random.randn(n) * 0.1 + base_ic
    if decay_frac > 0:
        decay_start = n // 2
        ic[decay_start:] *= (1 - decay_frac)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(ic, index=idx)


def _make_equity(n=200, cagr=0.15, seed=42):
    np.random.seed(seed)
    daily_ret = np.random.randn(n) * 0.01 + cagr / 252
    prices = 10000 * np.cumprod(1 + daily_ret)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(prices, index=idx)


class TestFactorDecayDetector:
    def test_no_decay(self):
        ic = _make_ic_series(200, base_ic=0.05, decay_frac=0.0)
        d = FactorDecayDetector(rolling_window=60, decay_threshold=0.50)
        r = d.check(ic)
        assert not r.triggered
        assert r.detector == "factor_decay"

    def test_severe_decay_triggers(self):
        ic = _make_ic_series(200, base_ic=0.05, decay_frac=0.8)
        d = FactorDecayDetector(rolling_window=60, decay_threshold=0.50)
        r = d.check(ic)
        assert r.triggered
        assert r.value > 0.50

    def test_insufficient_data(self):
        ic = _make_ic_series(50, base_ic=0.05)
        d = FactorDecayDetector(rolling_window=60)
        r = d.check(ic)
        assert not r.triggered
        assert "Insufficient" in r.description

    def test_zero_long_term_ic(self):
        ic = pd.Series(np.zeros(200), index=pd.date_range("2020-01-01", periods=200, freq="B"))
        d = FactorDecayDetector(rolling_window=60)
        r = d.check(ic)
        assert not r.triggered


class TestCostDriftDetector:
    def test_no_drift(self):
        idx = pd.date_range("2020-01-01", periods=50, freq="B")
        model = pd.Series(5.0, index=idx)
        actual = pd.Series(5.0, index=idx)
        d = CostDriftDetector(drift_threshold=2.0)
        r = d.check(model, actual)
        assert not r.triggered
        assert abs(r.value - 1.0) < 0.01

    def test_high_drift_triggers(self):
        idx = pd.date_range("2020-01-01", periods=50, freq="B")
        model = pd.Series(5.0, index=idx)
        actual = pd.Series(15.0, index=idx)
        d = CostDriftDetector(drift_threshold=2.0)
        r = d.check(model, actual)
        assert r.triggered
        assert r.value > 2.0

    def test_insufficient_data(self):
        idx = pd.date_range("2020-01-01", periods=5, freq="B")
        model = pd.Series(5.0, index=idx)
        actual = pd.Series(5.0, index=idx)
        d = CostDriftDetector()
        r = d.check(model, actual)
        assert not r.triggered
        assert "Insufficient" in r.description

    def test_critical_severity(self):
        idx = pd.date_range("2020-01-01", periods=50, freq="B")
        model = pd.Series(5.0, index=idx)
        actual = pd.Series(20.0, index=idx)
        d = CostDriftDetector(drift_threshold=2.0)
        r = d.check(model, actual)
        assert r.severity == "critical"


class TestStrategyAlphaDetector:
    def test_positive_alpha_ok(self):
        strat = _make_equity(200, cagr=0.20, seed=42)
        bench = _make_equity(200, cagr=0.10, seed=99)
        d = StrategyAlphaDetector(rolling_window=60, alpha_threshold=-0.05)
        r = d.check(strat, bench)
        assert not r.triggered

    def test_negative_alpha_triggers(self):
        idx = pd.date_range("2020-01-01", periods=200, freq="B")
        strat = pd.Series(10000 * np.cumprod(1 + np.full(200, -0.002)), index=idx)
        bench = pd.Series(10000 * np.cumprod(1 + np.full(200, 0.001)), index=idx)
        d = StrategyAlphaDetector(rolling_window=60, alpha_threshold=-0.05)
        r = d.check(strat, bench)
        assert r.triggered
        assert r.value < -0.05

    def test_insufficient_data(self):
        strat = _make_equity(30, seed=42)
        bench = _make_equity(30, seed=99)
        d = StrategyAlphaDetector(rolling_window=60)
        r = d.check(strat, bench)
        assert not r.triggered


class TestPaperBacktestDivergenceDetector:
    def test_no_divergence(self):
        eq = _make_equity(100, seed=42)
        d = PaperBacktestDivergenceDetector(rolling_window=20, divergence_threshold_bps=150)
        r = d.check(eq, eq)
        assert not r.triggered
        assert r.value < 1.0

    def test_large_divergence_triggers(self):
        bt = _make_equity(100, cagr=0.15, seed=42)
        pp = _make_equity(100, cagr=-0.10, seed=99)
        d = PaperBacktestDivergenceDetector(rolling_window=20, divergence_threshold_bps=50)
        r = d.check(bt, pp)
        assert r.triggered

    def test_insufficient_data(self):
        eq = _make_equity(10, seed=42)
        d = PaperBacktestDivergenceDetector(rolling_window=20)
        r = d.check(eq, eq)
        assert not r.triggered


class TestDiagnosticSuite:
    def test_run_all_no_data(self):
        suite = DiagnosticSuite()
        results = suite.run_all()
        assert results == []

    def test_run_all_with_ic(self):
        suite = DiagnosticSuite()
        ic = _make_ic_series(200)
        results = suite.run_all(ic_series=ic)
        assert len(results) == 1
        assert results[0].detector == "factor_decay"

    def test_any_triggered(self):
        suite = DiagnosticSuite()
        results = [
            DiagnosticResult("test", False, 0, 1, "ok"),
            DiagnosticResult("test2", True, 2, 1, "bad"),
        ]
        assert suite.any_triggered(results)

    def test_critical_triggered(self):
        suite = DiagnosticSuite()
        results = [
            DiagnosticResult("test", True, 2, 1, "bad", severity="warn"),
        ]
        assert not suite.critical_triggered(results)
        results.append(DiagnosticResult("test2", True, 5, 1, "very bad", severity="critical"))
        assert suite.critical_triggered(results)

    def test_str_representation(self):
        r = DiagnosticResult("test", True, 1.5, 1.0, "desc")
        assert "TRIGGERED" in str(r)
        r2 = DiagnosticResult("test", False, 0.5, 1.0, "desc")
        assert "OK" in str(r2)
