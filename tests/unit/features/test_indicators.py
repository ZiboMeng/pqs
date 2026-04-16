"""
Unit tests for core.features.indicators.

All tests use synthetic series — no external data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.features.indicators import (
    atr,
    atr_pct,
    bollinger_bands,
    compute_daily_features,
    compute_intraday_features,
    ema,
    hist_vol,
    macd,
    momentum_score,
    rsi,
    rolling_return,
    sma,
    true_range,
    volume_surge,
    vwap,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_series(n: int = 100, start: float = 100.0, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    vals = start + rng.normal(0, 0.5, n).cumsum()
    return pd.Series(np.maximum(vals, 1.0), name="close")


def _make_ohlcv(n: int = 200, start: str = "2023-01-03", seed: int = 42) -> pd.DataFrame:
    rng  = np.random.default_rng(seed)
    idx  = pd.bdate_range(start, periods=n)
    c    = 100.0 + rng.normal(0, 0.5, n).cumsum()
    c    = np.maximum(c, 1.0)
    df = pd.DataFrame(
        {
            "open":   c * (1 - rng.uniform(0, 0.003, n)),
            "high":   c * (1 + rng.uniform(0, 0.005, n)),
            "low":    c * (1 - rng.uniform(0, 0.005, n)),
            "close":  c,
            "volume": rng.integers(500_000, 2_000_000, n).astype(float),
        },
        index=idx,
    )
    df.index.name = "date"
    return df


def _make_intraday(n: int = 78, start: str = "2024-01-02") -> pd.DataFrame:
    """Build 1 week of 60m bars (6.5 h/day × 5 days ≈ 33 bars)."""
    idx = pd.date_range(start + " 09:30", periods=n, freq="60min")
    rng = np.random.default_rng(99)
    c   = 100.0 + rng.normal(0, 0.3, n).cumsum()
    c   = np.maximum(c, 1.0)
    df  = pd.DataFrame(
        {
            "open":   c * 0.999,
            "high":   c * 1.003,
            "low":    c * 0.997,
            "close":  c,
            "volume": rng.integers(100_000, 500_000, n).astype(float),
        },
        index=idx,
    )
    df.index.name = "datetime"
    return df


# ── EMA / SMA ─────────────────────────────────────────────────────────────────

class TestEmaSmA:
    def test_ema_length(self):
        s = _make_series(100)
        out = ema(s, 20)
        assert len(out) == 100

    def test_ema_first_value_close_to_first_input(self):
        # EMA(span=1) == original series
        s   = _make_series(50)
        out = ema(s, 1)
        pd.testing.assert_series_equal(out, s, check_names=False)

    def test_sma_window_produces_nans_at_start(self):
        s   = _make_series(50)
        out = sma(s, 10)
        assert out.iloc[:9].isna().all()
        assert out.iloc[9:].notna().all()

    def test_sma_constant_series(self):
        s   = pd.Series([5.0] * 30)
        out = sma(s, 10)
        assert (out.dropna() == 5.0).all()


# ── RSI ───────────────────────────────────────────────────────────────────────

class TestRSI:
    def test_rsi_range(self):
        s   = _make_series(200)
        out = rsi(s, 14)
        valid = out.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_all_gains_is_100(self):
        # All gains → avg_loss == 0 → RSI should be exactly 100
        s   = pd.Series(np.arange(1, 51, dtype=float))
        out = rsi(s, 14)
        assert out.iloc[-1] == 100.0

    def test_rsi_all_losses_approaches_0(self):
        s   = pd.Series(np.arange(50, 0, -1, dtype=float))
        out = rsi(s, 14)
        assert out.iloc[-1] < 10


# ── MACD ──────────────────────────────────────────────────────────────────────

class TestMACD:
    def test_macd_returns_three_series(self):
        s    = _make_series(100)
        m, sig, hist = macd(s)
        assert len(m) == len(sig) == len(hist) == 100

    def test_histogram_equals_macd_minus_signal(self):
        s    = _make_series(100)
        m, sig, hist = macd(s)
        pd.testing.assert_series_equal(hist, m - sig, check_names=False)


# ── Bollinger Bands ───────────────────────────────────────────────────────────

class TestBollingerBands:
    def test_upper_gt_lower(self):
        s          = _make_series(100)
        upper, lower, _ = bollinger_bands(s, 20)
        valid = (upper - lower).dropna()
        assert (valid > 0).all()

    def test_width_non_negative(self):
        s = _make_series(100)
        _, _, width = bollinger_bands(s, 20)
        assert (width.dropna() > 0).all()


# ── True Range / ATR ──────────────────────────────────────────────────────────

class TestTrueRangeATR:
    def test_true_range_ge_hl(self):
        df = _make_ohlcv(50)
        tr = true_range(df["high"], df["low"], df["close"])
        hl = df["high"] - df["low"]
        assert (tr >= hl - 1e-9).all(), "TR must be >= H-L"

    def test_atr_positive(self):
        df  = _make_ohlcv(100)
        out = atr(df["high"], df["low"], df["close"], 14)
        assert (out.dropna() > 0).all()

    def test_atr_pct_between_0_and_1(self):
        df  = _make_ohlcv(100)
        out = atr_pct(df["high"], df["low"], df["close"], 14)
        valid = out.dropna()
        assert (valid > 0).all() and (valid < 1).all()


# ── Historical Volatility ─────────────────────────────────────────────────────

class TestHistVol:
    def test_hist_vol_positive(self):
        s   = _make_series(100)
        out = hist_vol(s, 20, 252)
        assert (out.dropna() > 0).all()

    def test_hist_vol_flat_series_near_zero(self):
        s   = pd.Series([100.0] * 50)
        out = hist_vol(s, 20, 252)
        assert (out.dropna().abs() < 1e-10).all()


# ── VWAP ──────────────────────────────────────────────────────────────────────

class TestVWAP:
    def test_vwap_with_datetime_index(self):
        df  = _make_intraday(40)
        out = vwap(df["close"], df["volume"])
        assert len(out) == 40
        assert out.notna().any()

    def test_vwap_resets_daily(self):
        df   = _make_intraday(20)
        out  = vwap(df["close"], df["volume"])
        # First bar of a day: VWAP == close (only one observation)
        dates = df.index.date
        for date in set(dates):
            mask  = dates == date
            first_bar = out[mask].iloc[0]
            first_close = df["close"][mask].iloc[0]
            assert abs(first_bar - first_close) < 1e-6

    def test_vwap_non_datetime_index_returns_nan(self):
        s = pd.Series([100.0, 101.0, 102.0])
        v = pd.Series([1e6, 1e6, 1e6])
        out = vwap(s, v)
        assert out.isna().all()


# ── Volume Surge ──────────────────────────────────────────────────────────────

class TestVolumeSurge:
    def test_constant_volume_surge_equals_one(self):
        v   = pd.Series([1e6] * 50)
        out = volume_surge(v, 20)
        assert (out.dropna().round(6) == 1.0).all()

    def test_high_volume_spike_surge(self):
        # 50 bars at 1M then a single 10M bar; rolling mean of last 20
        # ≈ (19×1M + 10M)/20 = 1.45M  → surge ≈ 6.9, clearly > 3
        v   = pd.Series([1e6] * 50 + [10e6])
        out = volume_surge(v, 20)
        assert out.iloc[-1] > 3.0


# ── Rolling Return / Momentum ─────────────────────────────────────────────────

class TestMomentum:
    def test_rolling_return_length(self):
        s   = _make_series(100)
        out = rolling_return(s, 20)
        assert len(out) == 100

    def test_momentum_score_columns(self):
        s   = _make_series(300)
        df  = momentum_score(s, windows=[20, 60, 120])
        assert set(df.columns) == {"ret_20", "ret_60", "ret_120"}


# ── compute_daily_features ────────────────────────────────────────────────────

class TestComputeDailyFeatures:
    def test_returns_dataframe(self):
        df  = _make_ohlcv(300)
        out = compute_daily_features(df)
        assert isinstance(out, pd.DataFrame)

    def test_expected_columns_present(self):
        df   = _make_ohlcv(300)
        out  = compute_daily_features(df)
        for col in ["ema20", "ema50", "rsi14", "atr14", "macd", "bb_upper", "hv20"]:
            assert col in out.columns, f"Missing column: {col}"

    def test_index_aligned_to_input(self):
        df  = _make_ohlcv(300)
        out = compute_daily_features(df)
        pd.testing.assert_index_equal(out.index, df.index)

    def test_no_ohlcv_cols_in_output(self):
        df  = _make_ohlcv(300)
        out = compute_daily_features(df)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col not in out.columns


# ── compute_intraday_features ─────────────────────────────────────────────────

class TestComputeIntradayFeatures:
    def test_returns_dataframe(self):
        df  = _make_intraday(78)
        out = compute_intraday_features(df, "60m")
        assert isinstance(out, pd.DataFrame)

    def test_time_features_present(self):
        df  = _make_intraday(78)
        out = compute_intraday_features(df, "60m")
        for col in ["minutes_from_open", "minutes_to_close",
                    "is_first_30m", "is_last_30m", "vwap"]:
            assert col in out.columns, f"Missing column: {col}"

    def test_with_daily_anchors(self):
        df_intra = _make_intraday(78)
        df_daily = _make_ohlcv(252)
        out      = compute_intraday_features(df_intra, "60m", daily_df=df_daily)
        assert "d_rsi14" in out.columns

    def test_index_aligned_to_input(self):
        df  = _make_intraday(78)
        out = compute_intraday_features(df, "60m")
        pd.testing.assert_index_equal(out.index, df.index)
