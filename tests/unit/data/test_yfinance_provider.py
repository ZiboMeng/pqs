"""
Unit tests for YFinanceProvider.

All yfinance network calls are mocked — no internet required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.data.provider import OHLCV_COLS, OHLCVFrame
from core.data.yfinance_provider import YFinanceProvider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flat_df(symbol: str = "SPY", periods: int = 5) -> pd.DataFrame:
    """Single-symbol flat DataFrame (yfinance single-ticker format)."""
    idx = pd.bdate_range("2024-01-02", periods=periods, tz="UTC")
    df = pd.DataFrame(
        {
            "Open":   100.0,
            "High":   102.0,
            "Low":    99.0,
            "Close":  101.0,
            "Volume": 1_000_000.0,
        },
        index=idx,
    )
    return df


def _multi_df(symbols: list[str], periods: int = 5) -> pd.DataFrame:
    """Multi-symbol yfinance 0.2.x output (MultiIndex with Price × Ticker)."""
    idx        = pd.bdate_range("2024-01-02", periods=periods, tz="UTC")
    price_cols = ["Open", "High", "Low", "Close", "Volume"]
    mi         = pd.MultiIndex.from_product([price_cols, symbols], names=["Price", "Ticker"])
    return pd.DataFrame(100.0, index=idx, columns=mi)


# ── fetch_daily ───────────────────────────────────────────────────────────────

class TestFetchDaily:
    def test_single_symbol_returns_ohlcvframe(self):
        prov = YFinanceProvider()
        with patch.object(prov, "_download", return_value=_flat_df("SPY")):
            result = prov.fetch_daily(["SPY"], start="2024-01-02")
        assert "SPY" in result
        frame = result["SPY"]
        assert isinstance(frame, OHLCVFrame)
        assert list(frame.df.columns) == OHLCV_COLS

    def test_multi_symbol_returns_all(self):
        prov = YFinanceProvider()
        raw  = _multi_df(["SPY", "QQQ"])
        with patch.object(prov, "_download", return_value=raw):
            result = prov.fetch_daily(["SPY", "QQQ"], start="2024-01-02")
        assert "SPY" in result
        assert "QQQ" in result

    def test_daily_index_is_tz_naive(self):
        prov = YFinanceProvider()
        with patch.object(prov, "_download", return_value=_flat_df("SPY")):
            result = prov.fetch_daily(["SPY"], start="2024-01-02")
        assert result["SPY"].df.index.tz is None

    def test_missing_symbol_absent_from_result(self):
        """If yfinance returns empty for a symbol, it should be absent."""
        prov = YFinanceProvider()
        raw  = _multi_df(["SPY"])  # QQQ not in raw
        with patch.object(prov, "_download", return_value=raw):
            result = prov.fetch_daily(["SPY", "QQQ"], start="2024-01-02")
        # QQQ should not be in result (or empty)
        assert "QQQ" not in result or result["QQQ"].df.empty


# ── fetch_intraday ────────────────────────────────────────────────────────────

def _intraday_flat(periods: int = 20) -> pd.DataFrame:
    idx = pd.date_range("2024-01-02 09:30", periods=periods, freq="60min", tz="America/New_York")
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.5, "Close": 100.5, "Volume": 5e5},
        index=idx,
    )


class TestFetchIntraday:
    def test_fetch_60m_returns_ohlcvframe(self):
        prov = YFinanceProvider()
        with patch.object(prov, "_download", return_value=_intraday_flat()):
            result = prov.fetch_intraday(["SPY"], "60m", period="5d")
        assert "SPY" in result
        assert isinstance(result["SPY"], OHLCVFrame)

    def test_intraday_index_tz_naive(self):
        prov = YFinanceProvider()
        with patch.object(prov, "_download", return_value=_intraday_flat()):
            result = prov.fetch_intraday(["SPY"], "60m", period="5d")
        assert result["SPY"].df.index.tz is None

    def test_intraday_within_market_hours(self):
        prov = YFinanceProvider()
        with patch.object(prov, "_download", return_value=_intraday_flat()):
            result = prov.fetch_intraday(["SPY"], "60m", period="5d")
        idx = result["SPY"].df.index
        for ts in idx:
            hour_min = ts.hour * 60 + ts.minute
            assert 9 * 60 + 30 <= hour_min < 16 * 60, f"Bar at {ts} outside market hours"

    def test_unsupported_freq_raises(self):
        prov = YFinanceProvider()
        with pytest.raises(ValueError, match="Unsupported intraday freq"):
            prov.fetch_intraday(["SPY"], "2h", period="5d")

    def test_period_and_start_raises(self):
        prov = YFinanceProvider()
        with pytest.raises(ValueError, match="Specify either period OR start"):
            prov.fetch_intraday(["SPY"], "60m", start="2024-01-01", period="5d")

    def test_no_period_no_start_raises(self):
        prov = YFinanceProvider()
        with pytest.raises(ValueError, match="Must specify either period or start"):
            prov.fetch_intraday(["SPY"], "60m")


# ── _extract_symbol ───────────────────────────────────────────────────────────

class TestExtractSymbol:
    def test_single_symbol_flat(self):
        raw = _flat_df("SPY")
        out = YFinanceProvider._extract_symbol(raw, "SPY", ["SPY"])
        assert out is not None
        assert "close" in out.columns

    def test_multi_symbol_multiindex(self):
        raw = _multi_df(["SPY", "QQQ"])
        out = YFinanceProvider._extract_symbol(raw, "SPY", ["SPY", "QQQ"])
        assert out is not None
        assert "close" in out.columns

    def test_missing_symbol_returns_none(self):
        raw = _multi_df(["SPY"])
        out = YFinanceProvider._extract_symbol(raw, "GHOST", ["SPY", "GHOST"])
        assert out is None

    def test_none_raw_returns_none(self):
        out = YFinanceProvider._extract_symbol(None, "SPY", ["SPY"])
        assert out is None


# ── _download retries ─────────────────────────────────────────────────────────

class TestDownloadRetries:
    def test_retries_on_transient_failure(self):
        prov = YFinanceProvider()
        call_count = 0

        def fake_download(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient")
            return _flat_df()

        with patch("yfinance.download", side_effect=fake_download):
            with patch("time.sleep"):  # skip actual sleep
                raw = prov._download(["SPY"], interval="1d", start="2024-01-02")
        assert call_count == 3
        assert not raw.empty

    def test_raises_after_max_retries(self):
        prov = YFinanceProvider()

        with patch("yfinance.download", side_effect=RuntimeError("always fails")):
            with patch("time.sleep"):
                with pytest.raises(RuntimeError, match="yfinance download failed"):
                    prov._download(["SPY"], interval="1d", start="2024-01-02")
