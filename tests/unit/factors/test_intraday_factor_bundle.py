"""T1a.3 unit tests for intraday_factor_bundle.

Verifies the 4-factor bundle compose correctly from synthetic daily +
synthetic 60m bars. Real-data integration is T1a.4+.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.factors.intraday_factor_bundle import build_intraday_reversal_factor_bundle


def _mk_dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(start="2024-01-02", periods=n)


def _mk_synthetic_daily(dates, symbols, seed=42):
    rng = np.random.default_rng(seed)
    n = len(dates)
    m = len(symbols)
    rets = rng.normal(0.0005, 0.01, size=(n, m))
    close = 100.0 * np.exp(np.cumsum(rets, axis=0))
    close_df = pd.DataFrame(close, index=dates, columns=symbols)
    # Open / High / Low approximated from close
    open_df = close_df.shift(1).bfill()
    high_df = pd.DataFrame(
        np.maximum(close, open_df.values) * (1 + rng.uniform(0, 0.005, size=(n, m))),
        index=dates, columns=symbols,
    )
    low_df = pd.DataFrame(
        np.minimum(close, open_df.values) * (1 - rng.uniform(0, 0.005, size=(n, m))),
        index=dates, columns=symbols,
    )
    # Volume positive integers
    volume_df = pd.DataFrame(
        rng.integers(1_000_000, 10_000_000, size=(n, m)),
        index=dates, columns=symbols, dtype=float,
    )
    return close_df, open_df, high_df, low_df, volume_df


def _mk_synthetic_60m_bars(dates, symbols, seed=99):
    """Build 60m bar DataFrames per symbol covering each daily date with
    one 09:30 ET regular-session bar (covers 9:30-10:30 hour).

    Returns dict[sym → DataFrame[OHLCV]] with index = timestamp at 09:30 ET
    each trading date.
    """
    rng = np.random.default_rng(seed)
    bars_by_sym = {}
    for sym in symbols:
        rows = []
        ts_list = []
        for d in dates:
            # 60m bar at 09:00 ET (covers 09:00-10:00; per alt_a_intraday_inputs
            # NYSE_FIRST_REGULAR_BAR_HOUR=9)
            ts = pd.Timestamp(d.date()) + pd.Timedelta(hours=9)
            ts_list.append(ts)
            o = 100.0 + rng.normal(0, 0.5)
            c = o * (1 + rng.normal(0, 0.005))
            h = max(o, c) + abs(rng.normal(0, 0.1))
            lo = min(o, c) - abs(rng.normal(0, 0.1))
            v = float(rng.integers(100_000, 1_000_000))
            rows.append({"open": o, "high": h, "low": lo, "close": c, "volume": v})
        df = pd.DataFrame(rows, index=pd.DatetimeIndex(ts_list))
        bars_by_sym[sym] = df
    return bars_by_sym


class TestBundle:
    def test_01_returns_four_factor_panels(self):
        """Test 01: returned dict has the 4 required keys."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB", "CCC"]
        close, open_, high, low, volume = _mk_synthetic_daily(dates, syms)
        bars_60m = _mk_synthetic_60m_bars(dates, syms)
        bundle = build_intraday_reversal_factor_bundle(
            price_df=close, volume_df=volume,
            bars_60m_by_symbol=bars_60m,
            open_df=open_, high_df=high, low_df=low,
        )
        assert set(bundle.keys()) == {
            "weekly_reversal_signal_5d",
            "vol_21d",
            "intraday_volume_60m_zscore",
            "early_session_return_pct",
        }

    def test_02_all_panels_share_index_and_columns(self):
        """Test 02: all 4 panels have same index/columns as price_df."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB"]
        close, open_, high, low, volume = _mk_synthetic_daily(dates, syms)
        bars_60m = _mk_synthetic_60m_bars(dates, syms)
        bundle = build_intraday_reversal_factor_bundle(
            price_df=close, volume_df=volume,
            bars_60m_by_symbol=bars_60m,
            open_df=open_, high_df=high, low_df=low,
        )
        for name, df in bundle.items():
            assert df.index.equals(close.index), f"{name} index mismatch"
            assert set(df.columns) == set(syms), f"{name} column mismatch"

    def test_03_weekly_reversal_non_null_after_warmup(self):
        """Test 03: weekly_reversal_signal_5d non-null after volume-zscore
        60-day rolling warmup."""
        # weekly_reversal_signal_5d = -ret_5d * volume_zscore_5d. The volume
        # z-score uses 60d rolling mean/std (factor_generator.py:809-811),
        # so warmup requires >60 days of data
        dates = _mk_dates(80)
        syms = ["AAA", "BBB"]
        close, open_, high, low, volume = _mk_synthetic_daily(dates, syms)
        bars_60m = _mk_synthetic_60m_bars(dates, syms)
        bundle = build_intraday_reversal_factor_bundle(
            price_df=close, volume_df=volume,
            bars_60m_by_symbol=bars_60m,
            open_df=open_, high_df=high, low_df=low,
        )
        wr = bundle["weekly_reversal_signal_5d"]
        # After day 65 (past 60d rolling + 5d return + buffer), values non-null
        late_df = wr.iloc[65:]
        assert late_df.notna().any().any()

    def test_04_intraday_zscore_non_null_after_rolling_window(self):
        """Test 04: intraday_volume_60m_zscore non-null after 20d warmup."""
        dates = _mk_dates(40)
        syms = ["AAA"]
        close, open_, high, low, volume = _mk_synthetic_daily(dates, syms)
        bars_60m = _mk_synthetic_60m_bars(dates, syms)
        bundle = build_intraday_reversal_factor_bundle(
            price_df=close, volume_df=volume,
            bars_60m_by_symbol=bars_60m,
            rolling_window_days=20,
        )
        iv = bundle["intraday_volume_60m_zscore"]
        # After bar 25 (warmup + buffer), values non-null
        assert iv.iloc[25:].notna().any().any()

    def test_05_early_session_return_in_reasonable_range(self):
        """Test 05: early_session_return_pct values within ±0.05 (synthetic)."""
        dates = _mk_dates(30)
        syms = ["AAA", "BBB"]
        close, open_, high, low, volume = _mk_synthetic_daily(dates, syms)
        bars_60m = _mk_synthetic_60m_bars(dates, syms)
        bundle = build_intraday_reversal_factor_bundle(
            price_df=close, volume_df=volume,
            bars_60m_by_symbol=bars_60m,
        )
        er = bundle["early_session_return_pct"]
        # All non-null values should be in [-0.05, +0.05] given synthetic data
        # has std=0.005 ⇒ 99%+ within ±3 std = ±0.015
        non_null = er.stack().dropna()
        if len(non_null) > 0:
            assert (non_null.abs() < 0.05).all()


class TestEndToEndWithRunner:
    def test_06_bundle_consumable_by_IntradayReversalRunner(self):
        """Test 06: bundle output spreads correctly into IntradayReversalRunner."""
        from core.backtest.intraday_reversal_runner import IntradayReversalRunner
        from core.signals.strategies.intraday_reversal import (
            IntradayReversalStrategy, IntradayReversalConfig,
        )
        dates = _mk_dates(60)
        syms = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        close, open_, high, low, volume = _mk_synthetic_daily(dates, syms)
        bars_60m = _mk_synthetic_60m_bars(dates, syms)
        bundle = build_intraday_reversal_factor_bundle(
            price_df=close, volume_df=volume,
            bars_60m_by_symbol=bars_60m,
            open_df=open_, high_df=high, low_df=low,
        )
        strat = IntradayReversalStrategy(IntradayReversalConfig(
            setup_quantile_threshold=0.20,
            vol_filter_min_pct=0.0,
            confirmation_ttl_bars=1,
            volume_surge_at_open_60m_min=1.5,
            holding_period_max_days=5,
            top_n=5,
        ))
        runner = IntradayReversalRunner(
            strategy=strat,
            price_df=close,
            **bundle,
        )
        result = runner.run()
        # End-to-end smoke runs without error and produces a result
        assert result is not None
