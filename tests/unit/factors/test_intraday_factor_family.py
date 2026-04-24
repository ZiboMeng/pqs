"""Round 5 Topic F (2026-04-20): first intraday factor family.

Adds `realized_vol_60m_21d`, `intraday_vol_ratio_21d`,
`intraday_autocorr_21d` to factor_generator — RESEARCH-only, not
promoted to PRODUCTION_FACTORS.

These factors use within-day 60m bar granularity which can't be
captured from daily OHLC alone.

Completion signal (PRD §3.2 Topic F): factor_generator produces the
new family with non-trivial values on synthetic data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.factors.factor_generator import (
    generate_all_factors, _intraday_factors,
)
from core.factors.factor_registry import RESEARCH_FACTORS, PRODUCTION_FACTORS


def _make_synthetic_bars(n_days: int = 60, base_price: float = 100.0,
                        bar_vol: float = 0.005) -> dict:
    """Build synthetic 60m RTH bars for 2 symbols over n_days trading days.
    Bars span 09:30, 10:30, ..., 16:00 ET (7 bars per day RTH)."""
    np.random.seed(42)
    all_bars = []
    base_day = pd.Timestamp("2024-01-02")
    for d in range(n_days):
        day = base_day + pd.Timedelta(days=d)
        # Skip weekends
        if day.weekday() >= 5:
            continue
        for hour_i, closing_time in enumerate(
            ["10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"]
        ):
            h, m = map(int, closing_time.split(":"))
            ts = day.replace(hour=h, minute=m)
            all_bars.append(ts)
    idx = pd.DatetimeIndex(all_bars)

    # Symbol A: positive drift + mean-reverting bar-to-bar
    # Symbol B: high-vol random walk
    frames = {}
    for sym, vol in [("SYM_A", bar_vol), ("SYM_B", bar_vol * 2)]:
        rets = np.random.normal(0.0, vol, len(idx))
        prices = base_price * np.exp(np.cumsum(rets))
        frames[sym] = pd.DataFrame({
            "open":  prices * (1 - vol / 4),
            "high":  prices * (1 + vol / 2),
            "low":   prices * (1 - vol / 2),
            "close": prices,
            "volume": np.random.randint(1e4, 1e5, len(idx)),
        }, index=idx)
    return frames


def _make_synthetic_daily(symbols, dates):
    """Daily price_df aligned with intraday dates."""
    np.random.seed(11)
    frames = {}
    for sym in symbols:
        ret = np.random.normal(0.0005, 0.01, len(dates))
        frames[sym] = 100 * np.exp(np.cumsum(ret))
    return pd.DataFrame(frames, index=dates)


class TestIntradayFactorsProduced:

    def test_all_three_factors_present(self):
        bars = _make_synthetic_bars(n_days=60)
        symbols = list(bars.keys())
        dates = pd.bdate_range("2024-01-02", periods=45)
        price_df = _make_synthetic_daily(symbols, dates)

        out = _intraday_factors(price_df, bars)
        assert "realized_vol_60m_21d" in out
        assert "intraday_vol_ratio_21d" in out
        assert "intraday_autocorr_21d" in out

    def test_output_shape_matches_price_df(self):
        bars = _make_synthetic_bars(n_days=60)
        symbols = list(bars.keys())
        dates = pd.bdate_range("2024-01-02", periods=45)
        price_df = _make_synthetic_daily(symbols, dates)

        out = _intraday_factors(price_df, bars)
        for fname, fdf in out.items():
            assert fdf.shape == price_df.shape, (
                f"{fname} shape {fdf.shape} != price_df {price_df.shape}"
            )
            assert list(fdf.columns) == symbols

    def test_non_trivial_values_after_warmup(self):
        """After the 21-day warmup, factors should produce non-NaN
        values with sensible magnitudes."""
        bars = _make_synthetic_bars(n_days=60)
        symbols = list(bars.keys())
        dates = pd.bdate_range("2024-01-02", periods=45)
        price_df = _make_synthetic_daily(symbols, dates)

        out = _intraday_factors(price_df, bars)

        # Realized vol: positive, annualized, typical range 5-50%
        rv = out["realized_vol_60m_21d"]
        tail = rv.iloc[-10:].dropna().values.flatten()
        assert len(tail) > 0
        assert np.all(tail > 0)
        assert np.all(tail < 2.0)  # annualized < 200%, very loose

        # Vol ratio: positive, typical close to 1
        vr = out["intraday_vol_ratio_21d"]
        tail_vr = vr.iloc[-10:].dropna().values.flatten()
        assert len(tail_vr) > 0
        assert np.all(tail_vr > 0)

        # Autocorrelation: bounded in [-1, 1]
        ac = out["intraday_autocorr_21d"]
        tail_ac = ac.iloc[-10:].dropna().values.flatten()
        assert len(tail_ac) > 0
        assert np.all(np.abs(tail_ac) <= 1.001)

    def test_warmup_period_is_nan(self):
        """First ~20 days should be NaN (rolling window can't compute)."""
        bars = _make_synthetic_bars(n_days=60)
        symbols = list(bars.keys())
        dates = pd.bdate_range("2024-01-02", periods=45)
        price_df = _make_synthetic_daily(symbols, dates)

        out = _intraday_factors(price_df, bars)
        rv = out["realized_vol_60m_21d"]
        # Earliest rows should be NaN due to rolling(21).mean warmup
        assert rv.iloc[:5].isna().all().all()


class TestRegistryIntegration:

    def test_intraday_names_in_RESEARCH_FACTORS(self):
        for name in ("realized_vol_60m_21d", "intraday_vol_ratio_21d",
                     "intraday_autocorr_21d"):
            assert name in RESEARCH_FACTORS

    def test_intraday_names_NOT_in_PRODUCTION_FACTORS(self):
        """Research-only — must not leak into production without
        going through the promotion funnel."""
        for name in ("realized_vol_60m_21d", "intraday_vol_ratio_21d",
                     "intraday_autocorr_21d"):
            assert name not in PRODUCTION_FACTORS


class TestGenerateAllFactorsIntegration:

    def test_default_call_does_not_include_intraday(self):
        """When intraday_bars_60m is not passed, no intraday factors
        appear — preserves back-compat for legacy callers."""
        dates = pd.bdate_range("2024-01-02", periods=60)
        syms = ["SPY", "AAPL"]
        price = pd.DataFrame(
            100 + np.cumsum(np.random.randn(60, 2) * 0.5, axis=0),
            index=dates, columns=syms,
        )
        out = generate_all_factors(price)
        assert "realized_vol_60m_21d" not in out
        assert "intraday_autocorr_21d" not in out

    def test_with_intraday_bars_includes_family(self):
        bars = _make_synthetic_bars(n_days=60)
        symbols = list(bars.keys())
        dates = pd.bdate_range("2024-01-02", periods=45)
        price_df = _make_synthetic_daily(symbols, dates)

        out = generate_all_factors(price_df, intraday_bars_60m=bars)
        assert "realized_vol_60m_21d" in out
        assert "intraday_vol_ratio_21d" in out
        assert "intraday_autocorr_21d" in out

    def test_empty_intraday_bars_dict_no_op(self):
        dates = pd.bdate_range("2024-01-02", periods=30)
        syms = ["SPY", "AAPL"]
        price = pd.DataFrame(
            100 + np.cumsum(np.random.randn(30, 2) * 0.5, axis=0),
            index=dates, columns=syms,
        )
        # Empty dict — _intraday_factors returns empty; no crash
        out = generate_all_factors(price, intraday_bars_60m={})
        assert "realized_vol_60m_21d" not in out


class TestDriftCheck:
    """Drift guard: if factor_generator adds a new factor, RESEARCH_FACTORS
    must include it (test already exists in test_factor_registry.py;
    here we re-assert the integration specifically for the intraday
    family to guard against this set of 3 names being accidentally
    removed from RESEARCH_FACTORS)."""

    def test_intraday_outputs_are_all_registered(self):
        bars = _make_synthetic_bars(n_days=60)
        symbols = list(bars.keys())
        dates = pd.bdate_range("2024-01-02", periods=45)
        price_df = _make_synthetic_daily(symbols, dates)
        out = _intraday_factors(price_df, bars)
        for name in out.keys():
            assert name in RESEARCH_FACTORS, (
                f"Intraday factor '{name}' not in RESEARCH_FACTORS — "
                "drift between factor_generator and registry"
            )
