"""
Unit tests for MarketDataStore.

Uses a tmp_path fixture so tests never touch the real filesystem.
"""

import pandas as pd

from core.data.market_data_store import MarketDataStore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ohlcv(start: str, periods: int, freq: str = "D") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame."""
    idx = pd.date_range(start, periods=periods, freq=freq)
    df = pd.DataFrame(
        {
            "open":   100.0,
            "high":   102.0,
            "low":    99.0,
            "close":  101.0,
            "volume": 1_000_000.0,
        },
        index=idx,
    )
    df.index.name = "date"
    return df


# ── write + read ──────────────────────────────────────────────────────────────

class TestWriteRead:
    def test_roundtrip_daily(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 10)
        store.write("SPY", "1d", df)

        out = store.read("SPY", "1d")
        assert len(out) == 10
        assert list(out.columns) == ["open", "high", "low", "close", "volume"]

    def test_read_missing_returns_empty(self, tmp_path):
        store = MarketDataStore(tmp_path)
        out = store.read("MISSING", "1d")
        assert out.empty

    def test_write_empty_df_noop(self, tmp_path):
        store = MarketDataStore(tmp_path)
        store.write("SPY", "1d", pd.DataFrame())
        assert not (tmp_path / "daily" / "SPY.parquet").exists()

    def test_read_with_start_filter(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 10)
        store.write("SPY", "1d", df)

        out = store.read("SPY", "1d", start="2024-01-08")
        assert len(out) > 0
        assert out.index.min() >= pd.Timestamp("2024-01-08")

    def test_read_with_end_filter(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 10)
        store.write("SPY", "1d", df)

        out = store.read("SPY", "1d", end="2024-01-05")
        assert len(out) > 0
        assert out.index.max() <= pd.Timestamp("2024-01-05")

    def test_symbol_with_caret_sanitised(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 5)
        store.write("^VIX", "1d", df)

        out = store.read("^VIX", "1d")
        assert len(out) == 5


# ── append ────────────────────────────────────────────────────────────────────

class TestAppend:
    def test_append_new_file(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 5)
        n = store.append("SPY", "1d", df)
        assert n == 5

    def test_append_extends_existing(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df1 = _make_ohlcv("2024-01-02", 5)
        df2 = _make_ohlcv("2024-01-09", 3)
        store.write("SPY", "1d", df1)
        n = store.append("SPY", "1d", df2)
        assert n == 3

        out = store.read("SPY", "1d")
        assert len(out) == 8

    def test_append_deduplicates(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df1 = _make_ohlcv("2024-01-02", 5)
        store.write("SPY", "1d", df1)

        # Overlap: last 2 days of df1 + 3 new days
        overlap = _make_ohlcv("2024-01-06", 5)
        store.append("SPY", "1d", overlap)

        out = store.read("SPY", "1d")
        # Should have 5 original + 5 new but 2 overlap → 8 unique
        assert len(out) == len(out.index.drop_duplicates())

    def test_append_empty_noop(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 5)
        store.write("SPY", "1d", df)
        n = store.append("SPY", "1d", pd.DataFrame())
        assert n == 0

    def test_append_newer_wins_on_conflict(self, tmp_path):
        """Newer row should overwrite on same index."""
        store = MarketDataStore(tmp_path)
        idx = pd.date_range("2024-01-02", periods=1)
        df1 = pd.DataFrame({"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1e6}, index=idx)
        df2 = pd.DataFrame({"open": 200, "high": 202, "low": 199, "close": 201, "volume": 2e6}, index=idx)
        store.write("SPY", "1d", df1)
        store.append("SPY", "1d", df2)

        out = store.read("SPY", "1d")
        assert out["close"].iloc[0] == 201.0


# ── get_last_date / is_stale ──────────────────────────────────────────────────

class TestStaleness:
    def test_get_last_date_returns_none_if_missing(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.get_last_date("SPY", "1d") is None

    def test_get_last_date_correct(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 5)
        store.write("SPY", "1d", df)
        last = store.get_last_date("SPY", "1d")
        assert last == df.index[-1]

    def test_is_stale_missing_data(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.is_stale("SPY", "1d") is True

    def test_is_stale_old_data(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2020-01-02", 5)  # very old data
        store.write("SPY", "1d", df)
        assert store.is_stale("SPY", "1d", max_age_hours=20.0) is True

    def test_is_stale_fresh_data(self, tmp_path):
        """Data timestamped to today should not be stale."""
        store = MarketDataStore(tmp_path)
        today = pd.Timestamp.now().normalize()
        idx = pd.DatetimeIndex([today])
        df = pd.DataFrame(
            {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}, index=idx
        )
        store.write("SPY", "1d", df)
        assert store.is_stale("SPY", "1d", max_age_hours=48.0) is False


# ── has_min_bars ──────────────────────────────────────────────────────────────

class TestHasMinBars:
    def test_sufficient_bars(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 10)
        store.write("SPY", "1d", df)
        assert store.has_min_bars("SPY", "1d", 5) is True

    def test_insufficient_bars(self, tmp_path):
        store = MarketDataStore(tmp_path)
        df = _make_ohlcv("2024-01-02", 3)
        store.write("SPY", "1d", df)
        assert store.has_min_bars("SPY", "1d", 10) is False

    def test_missing_file(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.has_min_bars("SPY", "1d", 1) is False


# ── list_symbols / delete ─────────────────────────────────────────────────────

class TestListDelete:
    def test_list_symbols_empty(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.list_symbols("1d") == []

    def test_list_symbols_after_write(self, tmp_path):
        store = MarketDataStore(tmp_path)
        for sym in ["SPY", "QQQ", "IWM"]:
            store.write(sym, "1d", _make_ohlcv("2024-01-02", 3))
        syms = store.list_symbols("1d")
        assert set(syms) == {"SPY", "QQQ", "IWM"}

    def test_delete_existing(self, tmp_path):
        store = MarketDataStore(tmp_path)
        store.write("SPY", "1d", _make_ohlcv("2024-01-02", 3))
        assert store.delete("SPY", "1d") is True
        assert store.read("SPY", "1d").empty

    def test_delete_missing(self, tmp_path):
        store = MarketDataStore(tmp_path)
        assert store.delete("GHOST", "1d") is False


# ── read_multi ────────────────────────────────────────────────────────────────

class TestReadMulti:
    def test_read_multi_returns_dict(self, tmp_path):
        store = MarketDataStore(tmp_path)
        for sym in ["SPY", "QQQ"]:
            store.write(sym, "1d", _make_ohlcv("2024-01-02", 5))
        result = store.read_multi(["SPY", "QQQ", "MISSING"], "1d")
        assert set(result.keys()) == {"SPY", "QQQ", "MISSING"}
        assert not result["SPY"].empty
        assert result["MISSING"].empty
