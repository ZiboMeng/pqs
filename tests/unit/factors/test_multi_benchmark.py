"""Unit tests for PRD 20260424 P1 multi-benchmark generator plumbing."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.factor_generator import (
    generate_all_factors,
    _resolve_benchmark_map,
    _trim_factors_to_caller_symbols,
)


@pytest.fixture
def panel_without_spy():
    """Panel of 3 stocks (no SPY, no QQQ)."""
    idx = pd.bdate_range("2023-01-02", periods=300)
    np.random.seed(0)
    return pd.DataFrame(
        100 + np.cumsum(np.random.randn(300, 3) * 0.5, axis=0),
        index=idx, columns=["AAPL", "MSFT", "NVDA"],
    )


@pytest.fixture
def spy_series():
    idx = pd.bdate_range("2023-01-02", periods=300)
    np.random.seed(1)
    return pd.Series(
        400 + np.cumsum(np.random.randn(300) * 1.0),
        index=idx, name="SPY",
    )


@pytest.fixture
def qqq_series():
    idx = pd.bdate_range("2023-01-02", periods=300)
    np.random.seed(2)
    return pd.Series(
        350 + np.cumsum(np.random.randn(300) * 1.5),
        index=idx, name="QQQ",
    )


# ── _resolve_benchmark_map ────────────────────────────────────────────────────

def test_resolve_benchmark_map_none_returns_original(panel_without_spy):
    """Backward compat: None → return original, no copy."""
    result = _resolve_benchmark_map(panel_without_spy, "SPY", None)
    assert result is panel_without_spy  # same object, no copy


def test_resolve_benchmark_map_empty_dict_returns_original(panel_without_spy):
    """Empty map also returns original (falsy check)."""
    result = _resolve_benchmark_map(panel_without_spy, "SPY", {})
    assert result is panel_without_spy


def test_resolve_benchmark_map_injects_named_benchmarks(
    panel_without_spy, spy_series, qqq_series,
):
    bench_map = {"SPY": spy_series, "QQQ": qqq_series}
    result = _resolve_benchmark_map(panel_without_spy, "SPY", bench_map)
    # New DataFrame, not the original
    assert result is not panel_without_spy
    # Both benchmarks injected as columns
    assert "SPY" in result.columns
    assert "QQQ" in result.columns
    # Original columns still present
    for c in ("AAPL", "MSFT", "NVDA"):
        assert c in result.columns
    # Original not mutated
    assert "SPY" not in panel_without_spy.columns


def test_resolve_benchmark_map_reindexes_to_price_df(panel_without_spy):
    """Benchmark series with extra dates gets reindexed to price_df."""
    # Short benchmark series (subset of dates)
    short_bench = pd.Series(
        [400, 401, 402],
        index=panel_without_spy.index[:3],
        name="SPY",
    )
    result = _resolve_benchmark_map(
        panel_without_spy, "SPY", {"SPY": short_bench},
    )
    # SPY column spans full index; missing dates become NaN
    assert len(result["SPY"]) == len(panel_without_spy)
    assert result["SPY"].iloc[:3].notna().all()
    assert result["SPY"].iloc[3:].isna().all()


# ── _trim_factors_to_caller_symbols ──────────────────────────────────────────

def test_trim_factors_removes_injected_benchmarks():
    """If factor output includes benchmark columns, trim them out."""
    idx = pd.bdate_range("2024-01-01", periods=10)
    cols_caller = pd.Index(["AAPL", "MSFT"])
    f = pd.DataFrame(
        np.random.randn(10, 3),
        index=idx,
        columns=["AAPL", "MSFT", "SPY"],  # SPY injected earlier
    )
    trimmed = _trim_factors_to_caller_symbols({"f1": f}, cols_caller)
    assert list(trimmed["f1"].columns) == ["AAPL", "MSFT"]


def test_trim_factors_passes_through_when_no_extras():
    idx = pd.bdate_range("2024-01-01", periods=5)
    cols = pd.Index(["A", "B"])
    f = pd.DataFrame(np.random.randn(5, 2), index=idx, columns=["A", "B"])
    trimmed = _trim_factors_to_caller_symbols({"f1": f}, cols)
    assert trimmed["f1"] is f  # no copy when no trim needed


# ── generate_all_factors end-to-end ──────────────────────────────────────────

def test_generate_all_factors_benchmark_col_backward_compat(
    panel_without_spy, spy_series,
):
    """Old-style: SPY column in price_df → backward compat works."""
    panel_with_spy = panel_without_spy.copy()
    panel_with_spy["SPY"] = spy_series.values
    factors = generate_all_factors(panel_with_spy, benchmark_col="SPY")
    assert len(factors) > 0
    # Caller's universe includes SPY → SPY should appear in factor outputs
    f = factors["mom_21d"]
    assert "SPY" in f.columns


def test_generate_all_factors_benchmark_map_injects_spy(
    panel_without_spy, spy_series,
):
    """New-style: SPY NOT in panel, supplied via benchmark_map."""
    # Use benchmark_map; caller's panel doesn't include SPY
    factors = generate_all_factors(
        panel_without_spy,
        benchmark_col="SPY",
        benchmark_map={"SPY": spy_series},
    )
    # relative-strength family should produce factors (SPY was available)
    assert "rs_vs_spy_63d" in factors
    # Caller didn't include SPY → SPY should be trimmed from factor outputs
    f = factors["mom_21d"]
    assert "SPY" not in f.columns
    assert set(f.columns) == set(panel_without_spy.columns)


def test_generate_all_factors_benchmark_map_multi_benchmark(
    panel_without_spy, spy_series, qqq_series,
):
    """SPY + QQQ both supplied via map. Both accessible inside generator."""
    factors = generate_all_factors(
        panel_without_spy,
        benchmark_col="SPY",
        benchmark_map={"SPY": spy_series, "QQQ": qqq_series},
    )
    # SPY-relative factors produced (primary benchmark path)
    assert "rs_vs_spy_63d" in factors
    # Both benchmarks trimmed from output (caller didn't include them)
    f = factors["mom_21d"]
    assert "SPY" not in f.columns
    assert "QQQ" not in f.columns
    assert set(f.columns) == set(panel_without_spy.columns)


def test_generate_all_factors_caller_panel_unchanged(
    panel_without_spy, spy_series,
):
    """benchmark_map injection must NOT mutate caller's price_df."""
    original_cols = list(panel_without_spy.columns)
    original_shape = panel_without_spy.shape
    _ = generate_all_factors(
        panel_without_spy,
        benchmark_map={"SPY": spy_series},
    )
    # Caller's panel unchanged
    assert list(panel_without_spy.columns) == original_cols
    assert panel_without_spy.shape == original_shape
    assert "SPY" not in panel_without_spy.columns
