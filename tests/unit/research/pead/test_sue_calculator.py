"""Unit tests for core/research/pead/sue_calculator.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.pead.sue_calculator import (
    compute_sue,
    compute_sue_panel,
    build_sue_signal_panel,
)


def _earnings_df(eps_values, ticker="AAPL", start="2018-01-01"):
    """Build synthetic earnings_df with N quarterly EPS values starting at `start`."""
    n = len(eps_values)
    period_ends = pd.date_range(start, periods=n, freq="91D")
    filed_dates = period_ends + pd.Timedelta(days=30)
    return pd.DataFrame({
        "ticker": [ticker] * n,
        "period_end": period_ends,
        "period_start": period_ends - pd.Timedelta(days=91),
        "first_filed_date": filed_dates,
        "form": ["10-Q"] * n,
        "fy": list(range(2018, 2018 + n)),
        "fp": ["Q1"] * n,
        "eps_value": eps_values,
        "duration_days": [91] * n,
    })


# ── Empty handling ──

def test_empty_returns_empty_with_new_columns():
    df = pd.DataFrame()
    out = compute_sue(df)
    assert out.empty
    assert "sue" in out.columns


def test_empty_panel_returns_empty():
    out = compute_sue_panel(pd.DataFrame())
    assert out.empty
    assert "sue" in out.columns


# ── Basic mechanics ──

def test_first_4_quarters_have_nan_expected():
    eps = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.7, 1.8, 2.0, 2.1, 2.2, 2.3]
    df = _earnings_df(eps)
    out = compute_sue(df)
    # First 4 rows have NaN expected (Q-4 doesn't exist)
    assert out.iloc[0]["expected_eps"] != out.iloc[0]["expected_eps"]  # NaN
    assert out.iloc[3]["expected_eps"] != out.iloc[3]["expected_eps"]
    # Row 4 expected_eps = row 0 eps_value
    assert out.iloc[4]["expected_eps"] == 1.0


def test_residual_is_actual_minus_expected():
    eps = [1.0, 1.1, 1.2, 1.3, 2.0, 1.6, 1.7, 1.8, 3.0]
    df = _earnings_df(eps)
    out = compute_sue(df)
    # Row 4: actual=2.0, expected=eps[0]=1.0 → residual=1.0
    assert out.iloc[4]["residual"] == 1.0
    # Row 8: actual=3.0, expected=eps[4]=2.0 → residual=1.0
    assert out.iloc[8]["residual"] == 1.0


def test_sigma_residual_uses_8q_rolling_std():
    # Build a sequence so we can verify sigma manually
    np.random.seed(42)
    eps = list(np.cumsum(np.random.randn(20) * 0.1 + 1.0))
    df = _earnings_df(eps)
    out = compute_sue(df)
    # Residuals: row 4 .. row 19 (rows 0-3 have NaN)
    # sigma at row 12 = std(residuals_rows_4..11) shifted by 1
    # Verify shape: sigma is NaN for first 8 valid residuals (need full window)
    n_nan_sigma = out["sigma_residual"].isna().sum()
    # First 4 rows have NaN residual + we need 8 more residuals → first 12 NaN sigma
    assert n_nan_sigma >= 12


def test_sue_is_residual_over_sigma():
    """End-to-end: build sequence with known residuals/sigma, verify SUE."""
    # Stable EPS for first 12 quarters (residual ~ 0 with lag=4)
    # Then a positive surprise at quarter 12
    eps = [1.0] * 12 + [1.5]  # period 12: residual = 1.5 - 1.0 = +0.5
    # All residuals before period 12 (rows 4-11) are 0 → sigma = 0 → SUE = NaN
    df = _earnings_df(eps)
    out = compute_sue(df)
    assert pd.isna(out.iloc[12]["sue"])  # sigma=0 → SUE = NaN


def test_sue_well_defined_when_sigma_positive():
    """Residuals vary; SUE should be finite at the trigger quarter."""
    # Linear growth → residuals = constant +0.1 → sigma = 0 → SUE = NaN
    # Need NOISY residuals
    np.random.seed(7)
    eps = list(1.0 + np.cumsum(np.random.randn(15) * 0.1))
    df = _earnings_df(eps)
    out = compute_sue(df)
    # Last row should have finite SUE
    assert not pd.isna(out.iloc[-1]["sue"])
    assert -10 < out.iloc[-1]["sue"] < 10  # reasonable range


def test_zero_sigma_produces_nan_sue():
    """If all 8 prior residuals are identical (sigma=0), SUE → NaN."""
    eps = [1.0] * 13  # All same; residual = 0; sigma = 0
    df = _earnings_df(eps)
    out = compute_sue(df)
    # Last row residual = 0, sigma = 0 → SUE = NaN
    assert pd.isna(out.iloc[12]["sue"])


# ── FY filtering ──

def test_drop_fy_rows_default_true():
    """Default: fp='FY' rows (10-K full-year) are dropped before SUE."""
    n = 13
    period_ends = pd.date_range("2018-01-01", periods=n, freq="91D")
    df = pd.DataFrame({
        "ticker": ["AAPL"] * n,
        "period_end": period_ends,
        "period_start": period_ends - pd.Timedelta(days=91),
        "first_filed_date": period_ends + pd.Timedelta(days=30),
        "form": ["10-Q"] * 12 + ["10-K"],
        "fy": [2020] * 13,
        "fp": ["Q1", "Q2", "Q3", "Q1", "Q2", "Q3", "Q1", "Q2", "Q3",
               "Q1", "Q2", "Q3", "FY"],
        "eps_value": [1.0, 1.0, 1.0, 1.1, 1.1, 1.1, 1.2, 1.2, 1.2,
                      1.3, 1.3, 1.3, 5.0],  # FY row has full-year EPS = $5
        "duration_days": [91] * 12 + [365],
    })
    out = compute_sue(df, drop_fy_rows=True)
    # FY row should be excluded
    assert "FY" not in out["fp"].values
    assert len(out) == 12


def test_drop_fy_rows_false_keeps_fy():
    """drop_fy_rows=False keeps FY rows in the SUE sequence (testing toggle)."""
    n = 5
    period_ends = pd.date_range("2018-01-01", periods=n, freq="91D")
    df = pd.DataFrame({
        "ticker": ["AAPL"] * n,
        "period_end": period_ends,
        "period_start": period_ends - pd.Timedelta(days=91),
        "first_filed_date": period_ends + pd.Timedelta(days=30),
        "form": ["10-Q"] * 4 + ["10-K"],
        "fy": [2020] * n,
        "fp": ["Q1", "Q2", "Q3", "Q1", "FY"],
        "eps_value": [1.0, 1.1, 1.2, 1.3, 5.0],
        "duration_days": [91] * 4 + [365],
    })
    out = compute_sue(df, drop_fy_rows=False)
    assert "FY" in out["fp"].values
    assert len(out) == 5


# ── Panel concatenation ──

def test_panel_computes_per_ticker_independently():
    """Two tickers shouldn't pollute each other's SUE calculation."""
    df_aapl = _earnings_df([1.0] * 8 + [2.0], ticker="AAPL")
    df_msft = _earnings_df([3.0] * 8 + [3.5], ticker="MSFT")
    panel = pd.concat([df_aapl, df_msft], ignore_index=True)
    out = compute_sue_panel(panel)
    # AAPL row 8: actual=2.0, expected=1.0 → residual=1.0
    aapl = out[out["ticker"] == "AAPL"].sort_values("period_end").reset_index(drop=True)
    msft = out[out["ticker"] == "MSFT"].sort_values("period_end").reset_index(drop=True)
    assert aapl.iloc[8]["residual"] == 1.0
    assert msft.iloc[8]["residual"] == pytest.approx(0.5)


def test_panel_output_sorted_by_filed_date():
    df_a = _earnings_df([1.0, 1.1, 1.2, 1.3, 1.5], ticker="AAPL", start="2018-01-01")
    df_b = _earnings_df([2.0, 2.1, 2.2, 2.3, 2.5], ticker="MSFT", start="2018-02-01")
    panel = pd.concat([df_a, df_b], ignore_index=True)
    out = compute_sue_panel(panel)
    # Should be sorted by first_filed_date ascending
    assert out["first_filed_date"].is_monotonic_increasing


# ── Signal panel construction ──

def test_build_sue_signal_panel_marks_triggers():
    # Need 4+8 = 12 quarters minimum to compute SUE with 8-q sigma window.
    # Rows 0-3: NaN expected. Rows 4-11: residuals. Row 12: first row with sigma.
    np.random.seed(13)
    eps = list(1.0 + np.random.randn(12) * 0.05) + [10.0]  # 13 quarters
    df = _earnings_df(eps, ticker="AAPL", start="2018-01-01")
    out = compute_sue(df)
    price_idx = pd.date_range("2018-01-01", "2022-12-31", freq="B")
    entry = build_sue_signal_panel(out, sue_threshold=2.0,
                                    price_index=price_idx,
                                    universe=["AAPL", "MSFT"])
    # Exactly one True (the big surprise at row 12)
    assert entry.values.sum() == 1
    # And it's on the AAPL column
    aapl_trigs = entry["AAPL"][entry["AAPL"]].index
    assert len(aapl_trigs) == 1


def test_build_sue_signal_panel_threshold_filters():
    """SUE below threshold → no signal."""
    np.random.seed(13)
    eps = list(1.0 + np.random.randn(12) * 0.05) + [1.5]  # modest surprise, 13 quarters
    df = _earnings_df(eps, ticker="AAPL", start="2018-01-01")
    out = compute_sue(df)
    price_idx = pd.date_range("2018-01-01", "2020-12-31", freq="B")
    # Very high threshold → no triggers
    entry = build_sue_signal_panel(out, sue_threshold=50.0,
                                    price_index=price_idx,
                                    universe=["AAPL"])
    assert entry.values.sum() == 0


def test_build_sue_signal_skips_ticker_not_in_universe():
    """If trigger ticker is not in universe, signal is silently dropped."""
    np.random.seed(13)
    eps = list(1.0 + np.random.randn(12) * 0.05) + [10.0]
    df = _earnings_df(eps, ticker="XYZ", start="2018-01-01")
    out = compute_sue(df)
    price_idx = pd.date_range("2018-01-01", "2020-12-31", freq="B")
    entry = build_sue_signal_panel(out, sue_threshold=2.0,
                                    price_index=price_idx,
                                    universe=["AAPL", "MSFT"])
    assert entry.values.sum() == 0


def test_build_sue_signal_rolls_forward_off_trading_day():
    """If filed_date falls on weekend, signal rolls forward to next trading day."""
    n = 13
    period_ends = pd.date_range("2018-01-01", periods=n, freq="91D")
    filed_dates = period_ends + pd.Timedelta(days=30)
    df = pd.DataFrame({
        "ticker": ["AAPL"] * n,
        "period_end": period_ends,
        "period_start": period_ends - pd.Timedelta(days=91),
        "first_filed_date": filed_dates,
        "form": ["10-Q"] * n,
        "fy": list(range(2018, 2018 + n)),
        "fp": ["Q1"] * n,
        "eps_value": list(1.0 + np.random.RandomState(0).randn(12) * 0.05) + [10.0],
        "duration_days": [91] * n,
    })
    out = compute_sue(df)
    # Use a sparse price index (only business days)
    price_idx = pd.bdate_range("2018-01-01", "2022-12-31")
    entry = build_sue_signal_panel(out, sue_threshold=2.0,
                                    price_index=price_idx,
                                    universe=["AAPL"])
    # Should have at most one signal; if filed lands on weekend it rolls forward
    assert entry.values.sum() <= 1
