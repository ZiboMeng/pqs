"""Tests for FRED macro factors (Bucket Macro)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.data.fred_provider import FredProvider
from core.factors.factor_registry import RESEARCH_FACTORS
from core.factors.macro_factors import (
    MACRO_FACTOR_NAMES,
    compute_macro_factors,
)


@pytest.fixture
def fixture_macro_cache(tmp_path):
    """Synthesize a tiny FRED cache directory with CSV files for 6 series."""
    cache = tmp_path / "macro"
    cache.mkdir()
    idx = pd.bdate_range("2020-01-01", "2024-12-31")
    for sid, vals in [
        ("DGS10", np.linspace(2.0, 4.5, len(idx))),
        ("DGS2", np.linspace(1.5, 4.0, len(idx))),
        ("FEDFUNDS", np.linspace(0.25, 5.0, len(idx))),
        ("DTWEXBGS", 100.0 + np.cumsum(np.random.default_rng(0).normal(0, 0.1, len(idx)))),
        ("DCOILWTICO", 50.0 + np.cumsum(np.random.default_rng(1).normal(0, 0.5, len(idx)))),
        ("VIXCLS", 20.0 + np.abs(np.random.default_rng(2).normal(0, 5, len(idx)))),
        ("CPIAUCNS", 250.0 + np.cumsum(np.random.default_rng(3).normal(0, 0.02, len(idx)))),
        ("UNRATE", 4.0 + np.random.default_rng(4).normal(0, 0.5, len(idx))),
    ]:
        df = pd.DataFrame({"observation_date": idx, sid: vals})
        df.to_csv(cache / f"{sid}.csv", index=False)
    return cache


@pytest.fixture
def fred_provider(fixture_macro_cache):
    return FredProvider(cache_dir=fixture_macro_cache)


class TestRegistration:
    def test_all_in_research_factors(self):
        for name in MACRO_FACTOR_NAMES:
            assert name in RESEARCH_FACTORS


class TestFredProvider:
    def test_load_series(self, fred_provider):
        s = fred_provider.load_series("DGS10")
        assert len(s) > 0
        assert s.name == "DGS10"

    def test_load_series_missing(self, fred_provider):
        with pytest.raises(FileNotFoundError):
            fred_provider.load_series("NONEXISTENT_SID")

    def test_load_panel(self, fred_provider):
        panel = fred_provider.load_panel(["DGS10", "DGS2"])
        assert "DGS10" in panel.columns
        assert "DGS2" in panel.columns


class TestMacroFactors:
    def test_factors_computed(self, fred_provider):
        idx = pd.bdate_range("2022-01-01", "2024-12-31")
        out = compute_macro_factors(idx, ["AAPL", "MSFT"], provider=fred_provider)
        for name in MACRO_FACTOR_NAMES:
            assert name in out, f"{name} missing"
            assert out[name].shape == (len(idx), 2)

    def test_broadcast_identical_across_tickers(self, fred_provider):
        idx = pd.bdate_range("2023-01-01", "2024-12-31")
        out = compute_macro_factors(idx, ["AAPL", "MSFT", "JNJ"], provider=fred_provider)
        # Each macro factor should be identical across columns (same time series)
        for name in MACRO_FACTOR_NAMES:
            df = out[name].dropna()
            if df.empty:
                continue
            for col in df.columns[1:]:
                np.testing.assert_array_equal(
                    df[col].values, df[df.columns[0]].values,
                    err_msg=f"{name} not broadcast identically",
                )

    def test_yield_curve_dgs10_minus_dgs2(self, fred_provider):
        """Synthetic DGS10 monotonic up + DGS2 monotonic up — yc should
        be positive since slopes are equal but intercept higher for DGS10."""
        idx = pd.bdate_range("2023-01-01", "2024-12-31")
        out = compute_macro_factors(idx, ["X"], provider=fred_provider)
        yc = out["yield_curve_10y_2y"]["X"].dropna()
        # DGS10 starts at 2.0, DGS2 starts at 1.5 → yc starts at 0.5
        assert (yc > 0).all(), f"yc should be positive; min={yc.min()}"


class TestMissingSeriesGracefulDegrade:
    def test_missing_series_yields_nan_panel(self, tmp_path):
        """Empty cache → each factor gets NaN-only panel rather than crash."""
        cache = tmp_path / "empty_macro"
        cache.mkdir()
        provider = FredProvider(cache_dir=cache)
        idx = pd.bdate_range("2023-01-01", "2024-06-01")
        out = compute_macro_factors(idx, ["X"], provider=provider)
        for name in MACRO_FACTOR_NAMES:
            assert name in out
            assert out[name].isna().all().all()
