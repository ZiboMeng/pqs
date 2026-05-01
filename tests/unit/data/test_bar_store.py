"""
Unit tests for BarStore.

Uses tmp_path fixtures — never touches the real data dir.
yfinance calls are stubbed by monkey-patching `yfinance.download`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.data.bar_store import BarStore, _safe_symbol


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_1m_frame(start: str, periods: int, price: float = 100.0, vol: int = 1000) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="1min", name="timestamp")
    return pd.DataFrame({
        "open":   pd.Series(price,    index=idx, dtype="float32"),
        "high":   pd.Series(price+0.5, index=idx, dtype="float32"),
        "low":    pd.Series(price-0.5, index=idx, dtype="float32"),
        "close":  pd.Series(price+0.1, index=idx, dtype="float32"),
        "volume": pd.Series(vol,      index=idx, dtype="int64"),
        "amount": pd.Series(np.nan,    index=idx, dtype="float64"),
    })


def _write_bars(root: Path, symbol: str, freq: str, df: pd.DataFrame) -> None:
    out_dir = root / ("daily" if freq in ("daily", "1d") else f"intraday/{freq}")
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / f"{_safe_symbol(symbol)}.parquet", compression="snappy")


def _write_splits(root: Path, rows: list[dict]) -> None:
    ref = root / "ref"
    ref.mkdir(parents=True, exist_ok=True)
    if rows:
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
    else:
        df = pd.DataFrame({"symbol": pd.Series(dtype="string"),
                           "date": pd.Series(dtype="datetime64[ns]"),
                           "from": pd.Series(dtype="int64"),
                           "to": pd.Series(dtype="int64")})
    df.to_parquet(ref / "splits.parquet", compression="snappy", index=False)


# ── core load ─────────────────────────────────────────────────────────────────

class TestLoadLocal:
    def test_missing_file_returns_empty(self, tmp_path):
        store = BarStore(tmp_path)
        df = store.load("NOPE", freq="1m", fallback="local")
        assert df.empty

    def test_basic_roundtrip(self, tmp_path):
        raw = _make_1m_frame("2020-06-01 09:30", 5, price=100.0)
        _write_bars(tmp_path, "SPY", "1m", raw)
        _write_splits(tmp_path, [])  # no splits
        store = BarStore(tmp_path)

        df = store.load("SPY", freq="1m", fallback="local")
        assert len(df) == 5
        assert df.index.name == "timestamp"
        assert set(df.columns) == {"open", "high", "low", "close", "volume", "amount"}
        # No splits → adjusted == raw
        assert df["close"].iloc[0] == pytest.approx(100.1, abs=1e-4)

    def test_start_end_filters(self, tmp_path):
        raw = _make_1m_frame("2020-06-01 09:30", 10, price=100.0)
        _write_bars(tmp_path, "SPY", "1m", raw)
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)

        df = store.load("SPY", freq="1m",
                        start="2020-06-01 09:33", end="2020-06-01 09:36",
                        fallback="local")
        assert len(df) == 4
        assert df.index.min() == pd.Timestamp("2020-06-01 09:33")
        assert df.index.max() == pd.Timestamp("2020-06-01 09:36")


# ── forward split adjustment ─────────────────────────────────────────────────

class TestSplitAdjustment:
    def test_no_splits_is_identity(self, tmp_path):
        raw = _make_1m_frame("2020-06-01 09:30", 3, price=200.0)
        _write_bars(tmp_path, "SPY", "1m", raw)
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)

        adj = store.load("SPY", freq="1m", adjusted=True, fallback="local")
        raw_loaded = store.load("SPY", freq="1m", adjusted=False, fallback="local")
        pd.testing.assert_frame_equal(adj, raw_loaded)

    def test_single_future_split(self, tmp_path):
        # Bar on 2020-06-01 BEFORE 2020-08-31 (1→4) → factor 0.25
        raw = _make_1m_frame("2020-06-01 09:30", 2, price=400.0)
        _write_bars(tmp_path, "AAPL", "1m", raw)
        _write_splits(tmp_path, [
            {"symbol": "AAPL", "date": "2020-08-31", "from": 1, "to": 4},
        ])
        store = BarStore(tmp_path, )

        # Override "today" to after the split so it's applied
        adj = store.load("AAPL", freq="1m", adjusted=True,
                         as_of=pd.Timestamp("2025-01-01"), fallback="local")
        assert adj["close"].iloc[0] == pytest.approx(400.1 * 0.25, rel=1e-4)
        # Volume scales inverse: raw 1000 / 0.25 = 4000
        assert adj["volume"].iloc[0] == 4000

    def test_multiple_future_splits_compound(self, tmp_path):
        # NVDA-like: 2 splits — 1:4 in 2021, 1:10 in 2024. Bar in 2020 → factor 1/40.
        raw = _make_1m_frame("2020-01-01 09:30", 1, price=400.0)
        _write_bars(tmp_path, "NVDA", "1m", raw)
        _write_splits(tmp_path, [
            {"symbol": "NVDA", "date": "2021-07-20", "from": 1, "to": 4},
            {"symbol": "NVDA", "date": "2024-06-10", "from": 1, "to": 10},
        ])
        store = BarStore(tmp_path)

        adj = store.load("NVDA", freq="1m", adjusted=True,
                         as_of=pd.Timestamp("2026-01-01"), fallback="local")
        assert adj["close"].iloc[0] == pytest.approx(400.1 / 40.0, rel=1e-4)
        assert adj["volume"].iloc[0] == 40000

    def test_split_on_same_date_as_bar_treated_as_post(self, tmp_path):
        # Bar AT 09:30 on split date → treated as post-split (factor excludes this split)
        raw = _make_1m_frame("2020-08-31 09:30", 2, price=100.0)
        _write_bars(tmp_path, "AAPL", "1m", raw)
        _write_splits(tmp_path, [
            {"symbol": "AAPL", "date": "2020-08-31", "from": 1, "to": 4},
        ])
        store = BarStore(tmp_path)

        adj = store.load("AAPL", freq="1m", adjusted=True,
                         as_of=pd.Timestamp("2025-01-01"), fallback="local")
        # Split date bars → post-split basis → factor = 1 → unchanged
        assert adj["close"].iloc[0] == pytest.approx(100.1, abs=1e-4)

    def test_future_split_excluded_by_as_of(self, tmp_path):
        # Split hasn't happened yet from as_of perspective
        raw = _make_1m_frame("2020-06-01 09:30", 1, price=400.0)
        _write_bars(tmp_path, "AAPL", "1m", raw)
        _write_splits(tmp_path, [
            {"symbol": "AAPL", "date": "2020-08-31", "from": 1, "to": 4},
        ])
        store = BarStore(tmp_path)

        # Viewing from 2020-07-01 — split hasn't happened yet → factor 1.0
        adj = store.load("AAPL", freq="1m", adjusted=True,
                         as_of=pd.Timestamp("2020-07-01"), fallback="local")
        assert adj["close"].iloc[0] == pytest.approx(400.1, abs=1e-4)

    def test_volume_adjustment_is_inverse(self, tmp_path):
        raw = _make_1m_frame("2020-06-01 09:30", 1, price=100.0, vol=500)
        _write_bars(tmp_path, "X", "1m", raw)
        _write_splits(tmp_path, [
            {"symbol": "X", "date": "2020-08-01", "from": 1, "to": 2},
        ])
        store = BarStore(tmp_path)

        adj = store.load("X", freq="1m", adjusted=True,
                         as_of=pd.Timestamp("2025-01-01"), fallback="local")
        # price halved, volume doubled
        assert adj["close"].iloc[0] == pytest.approx(100.1 * 0.5, abs=1e-4)
        assert adj["volume"].iloc[0] == 1000


# ── reverse-split (to < from) ────────────────────────────────────────────────

class TestReverseSplit:
    def test_reverse_split_raises_price(self, tmp_path):
        # 5-to-1 reverse split: from=5, to=1 → ratio 5.0 → price multiplies by 5 historically
        raw = _make_1m_frame("2020-06-01 09:30", 1, price=1.0, vol=10000)
        _write_bars(tmp_path, "X", "1m", raw)
        _write_splits(tmp_path, [
            {"symbol": "X", "date": "2020-08-01", "from": 5, "to": 1},
        ])
        store = BarStore(tmp_path)

        adj = store.load("X", freq="1m", adjusted=True,
                         as_of=pd.Timestamp("2025-01-01"), fallback="local")
        # factor = from/to = 5
        assert adj["close"].iloc[0] == pytest.approx(1.1 * 5.0, abs=1e-3)
        assert adj["volume"].iloc[0] == 2000  # 10000 / 5


# ── distribution back-adjustment (cycle #04 cross-asset preflight) ───────────


def _write_distributions(tmp_path: Path, rows: list[dict]) -> None:
    """Helper: write tmp distributions.parquet."""
    ref = tmp_path / "ref"
    ref.mkdir(parents=True, exist_ok=True)
    if rows:
        df = pd.DataFrame(rows)
        df["ex_date"] = pd.to_datetime(df["ex_date"])
    else:
        df = pd.DataFrame({
            "symbol": pd.Series(dtype="string"),
            "ex_date": pd.Series(dtype="datetime64[ns]"),
            "cash_amount": pd.Series(dtype="float64"),
            "ref_close_pre_ex": pd.Series(dtype="float64"),
            "factor": pd.Series(dtype="float64"),
            "source": pd.Series(dtype="string"),
            "pulled_at": pd.Series(dtype="string"),
            "splits_table_sha": pd.Series(dtype="string"),
        })
    df.to_parquet(ref / "distributions.parquet", compression="snappy", index=False)


class TestDistributionAdjustment:
    def test_no_distributions_is_identity(self, tmp_path):
        """Symbols not in sidecar pass through unchanged when
        adjusted_total_return=True."""
        idx = pd.DatetimeIndex(["2020-06-01", "2020-06-02"], name="timestamp")
        raw = pd.DataFrame({
            "open":  pd.Series(100.0, index=idx, dtype="float32"),
            "high":  pd.Series(100.5, index=idx, dtype="float32"),
            "low":   pd.Series(99.5,  index=idx, dtype="float32"),
            "close": pd.Series(100.1, index=idx, dtype="float32"),
            "volume": pd.Series(1000, index=idx, dtype="int64"),
        })
        _write_bars(tmp_path, "GLD", "daily", raw)
        _write_splits(tmp_path, [])
        _write_distributions(tmp_path, [])  # empty sidecar
        store = BarStore(tmp_path)

        tr = store.load("GLD", freq="daily", adjusted=True,
                        adjusted_total_return=True, fallback="local")
        sa = store.load("GLD", freq="daily", adjusted=True,
                        adjusted_total_return=False, fallback="local")
        pd.testing.assert_frame_equal(tr, sa)

    def test_single_future_distribution(self, tmp_path):
        """One ex-div in the future: pre-ex bar gets factor (1 - X/ref)."""
        idx = pd.DatetimeIndex(["2020-06-01", "2020-08-01"], name="timestamp")
        raw = pd.DataFrame({
            "open":  pd.Series(100.0, index=idx, dtype="float32"),
            "high":  pd.Series(100.5, index=idx, dtype="float32"),
            "low":   pd.Series(99.5,  index=idx, dtype="float32"),
            "close": pd.Series(100.0, index=idx, dtype="float32"),
            "volume": pd.Series(1000, index=idx, dtype="int64"),
        })
        _write_bars(tmp_path, "TLT", "daily", raw)
        _write_splits(tmp_path, [])
        # One $1 div on 2020-07-01, ref close = $100 → factor = 0.99
        _write_distributions(tmp_path, [{
            "symbol": "TLT", "ex_date": "2020-07-01",
            "cash_amount": 1.0, "ref_close_pre_ex": 100.0, "factor": 0.99,
            "source": "test", "pulled_at": "2026-05-01T00:00:00Z",
            "splits_table_sha": "no_splits_table",
        }])
        store = BarStore(tmp_path)

        tr = store.load("TLT", freq="daily", adjusted=True,
                        adjusted_total_return=True, fallback="local",
                        as_of=pd.Timestamp("2025-01-01"))
        # 2020-06-01 (pre-ex): factor = 0.99 → adj_close = 100 × 0.99 = 99.0
        # 2020-08-01 (post-ex): factor = 1 → adj_close = 100.0
        assert tr["close"].iloc[0] == pytest.approx(99.0, abs=1e-3)
        assert tr["close"].iloc[1] == pytest.approx(100.0, abs=1e-3)
        # Volume unchanged by distributions
        assert tr["volume"].iloc[0] == 1000
        assert tr["volume"].iloc[1] == 1000

    def test_multiple_distributions_compound(self, tmp_path):
        """Multiple ex-divs: factor on pre-event bar = product of factors."""
        idx = pd.DatetimeIndex(["2020-01-01"], name="timestamp")
        raw = pd.DataFrame({
            "open":  pd.Series(100.0, index=idx, dtype="float32"),
            "high":  pd.Series(100.5, index=idx, dtype="float32"),
            "low":   pd.Series(99.5,  index=idx, dtype="float32"),
            "close": pd.Series(100.0, index=idx, dtype="float32"),
            "volume": pd.Series(1000, index=idx, dtype="int64"),
        })
        _write_bars(tmp_path, "TLT", "daily", raw)
        _write_splits(tmp_path, [])
        _write_distributions(tmp_path, [
            {"symbol": "TLT", "ex_date": "2020-06-01", "cash_amount": 1.0,
             "ref_close_pre_ex": 100.0, "factor": 0.99,
             "source": "test", "pulled_at": "2026-05-01T00:00:00Z",
             "splits_table_sha": "no_splits_table"},
            {"symbol": "TLT", "ex_date": "2020-12-01", "cash_amount": 0.50,
             "ref_close_pre_ex": 100.0, "factor": 0.995,
             "source": "test", "pulled_at": "2026-05-01T00:00:00Z",
             "splits_table_sha": "no_splits_table"},
        ])
        store = BarStore(tmp_path)

        tr = store.load("TLT", freq="daily", adjusted=True,
                        adjusted_total_return=True, fallback="local",
                        as_of=pd.Timestamp("2025-01-01"))
        # cumulative factor = 0.99 × 0.995 = 0.98505
        assert tr["close"].iloc[0] == pytest.approx(100.0 * 0.99 * 0.995, abs=1e-3)

    def test_bar_on_ex_date_is_post_distribution(self, tmp_path):
        """Bar AT ex_date → post-distribution basis (factor for that
        event excluded; close on ex_date is already post-drop)."""
        idx = pd.DatetimeIndex(["2020-07-01"], name="timestamp")
        raw = pd.DataFrame({
            "open":  pd.Series(100.0, index=idx, dtype="float32"),
            "high":  pd.Series(100.5, index=idx, dtype="float32"),
            "low":   pd.Series(99.5,  index=idx, dtype="float32"),
            "close": pd.Series(99.0,  index=idx, dtype="float32"),
            "volume": pd.Series(1000, index=idx, dtype="int64"),
        })
        _write_bars(tmp_path, "TLT", "daily", raw)
        _write_splits(tmp_path, [])
        _write_distributions(tmp_path, [{
            "symbol": "TLT", "ex_date": "2020-07-01",
            "cash_amount": 1.0, "ref_close_pre_ex": 100.0, "factor": 0.99,
            "source": "test", "pulled_at": "2026-05-01T00:00:00Z",
            "splits_table_sha": "no_splits_table",
        }])
        store = BarStore(tmp_path)

        tr = store.load("TLT", freq="daily", adjusted=True,
                        adjusted_total_return=True, fallback="local",
                        as_of=pd.Timestamp("2025-01-01"))
        # Bar AT ex_date → factor=1 → close stays at 99.0 (post-drop)
        assert tr["close"].iloc[0] == pytest.approx(99.0, abs=1e-3)

    def test_future_distribution_excluded_by_as_of(self, tmp_path):
        """as_of < ex_date → distribution not yet visible → factor=1."""
        idx = pd.DatetimeIndex(["2020-01-01"], name="timestamp")
        raw = pd.DataFrame({
            "open":  pd.Series(100.0, index=idx, dtype="float32"),
            "high":  pd.Series(100.5, index=idx, dtype="float32"),
            "low":   pd.Series(99.5,  index=idx, dtype="float32"),
            "close": pd.Series(100.0, index=idx, dtype="float32"),
            "volume": pd.Series(1000, index=idx, dtype="int64"),
        })
        _write_bars(tmp_path, "TLT", "daily", raw)
        _write_splits(tmp_path, [])
        _write_distributions(tmp_path, [{
            "symbol": "TLT", "ex_date": "2020-07-01",
            "cash_amount": 1.0, "ref_close_pre_ex": 100.0, "factor": 0.99,
            "source": "test", "pulled_at": "2026-05-01T00:00:00Z",
            "splits_table_sha": "no_splits_table",
        }])
        store = BarStore(tmp_path)

        # Viewing from 2020-03-01 — div hasn't happened yet → factor 1.0
        tr = store.load("TLT", freq="daily", adjusted=True,
                        adjusted_total_return=True, fallback="local",
                        as_of=pd.Timestamp("2020-03-01"))
        assert tr["close"].iloc[0] == pytest.approx(100.0, abs=1e-3)

    def test_volume_unchanged_by_distributions(self, tmp_path):
        """Distributions affect price but not volume."""
        idx = pd.DatetimeIndex(["2020-01-01"], name="timestamp")
        raw = pd.DataFrame({
            "open":  pd.Series(100.0, index=idx, dtype="float32"),
            "high":  pd.Series(100.5, index=idx, dtype="float32"),
            "low":   pd.Series(99.5,  index=idx, dtype="float32"),
            "close": pd.Series(100.0, index=idx, dtype="float32"),
            "volume": pd.Series(5000, index=idx, dtype="int64"),
        })
        _write_bars(tmp_path, "TLT", "daily", raw)
        _write_splits(tmp_path, [])
        _write_distributions(tmp_path, [{
            "symbol": "TLT", "ex_date": "2020-06-01",
            "cash_amount": 5.0, "ref_close_pre_ex": 100.0, "factor": 0.95,
            "source": "test", "pulled_at": "2026-05-01T00:00:00Z",
            "splits_table_sha": "no_splits_table",
        }])
        store = BarStore(tmp_path)

        tr = store.load("TLT", freq="daily", adjusted=True,
                        adjusted_total_return=True, fallback="local",
                        as_of=pd.Timestamp("2025-01-01"))
        # Price reduced by factor 0.95
        assert tr["close"].iloc[0] == pytest.approx(95.0, abs=1e-3)
        # Volume unchanged
        assert tr["volume"].iloc[0] == 5000

    def test_adjusted_total_return_requires_adjusted_true(self, tmp_path):
        """adjusted=False + adjusted_total_return=True must raise."""
        store = BarStore(tmp_path)
        with pytest.raises(ValueError, match="requires adjusted=True"):
            store.load("TLT", freq="daily", adjusted=False,
                       adjusted_total_return=True, fallback="local")

    def test_default_path_unchanged_when_atr_false(self, tmp_path):
        """Default load(adjusted=True) byte-identical to
        load(adjusted=True, adjusted_total_return=False) — regression
        guard for stocks not in the distribution sidecar."""
        raw = _make_1m_frame("2020-06-01 09:30", 3, price=100.0)
        _write_bars(tmp_path, "AAPL", "1m", raw)
        _write_splits(tmp_path, [])
        # no distributions sidecar at all
        store = BarStore(tmp_path)

        default = store.load("AAPL", freq="1m", adjusted=True, fallback="local")
        explicit = store.load("AAPL", freq="1m", adjusted=True,
                              adjusted_total_return=False, fallback="local")
        pd.testing.assert_frame_equal(default, explicit)


# ── yfinance fallback (mocked) ───────────────────────────────────────────────

class FakeYF:
    """Stub that returns a synthetic OHLCV frame yfinance-shape."""
    def __init__(self, start: str, periods: int, price: float = 500.0):
        self.start = start
        self.periods = periods
        self.price = price

    def download(self, symbol, start, end, interval, auto_adjust, progress, threads):
        idx = pd.date_range(self.start, periods=self.periods,
                            freq="1min" if interval == "1m" else
                                 ("60min" if interval == "60m" else "1D"),
                            name="Date" if interval == "1d" else "Datetime",
                            tz=None if interval == "1d" else "America/New_York")
        df = pd.DataFrame({
            "Open":      self.price,
            "High":      self.price + 0.5,
            "Low":       self.price - 0.5,
            "Close":     self.price + 0.1,
            "Adj Close": self.price + 0.05,
            "Volume":    1_000,
        }, index=idx)
        return df


class TestYFinanceFallback:
    def test_local_empty_triggers_yfinance(self, tmp_path, monkeypatch):
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)
        fake = FakeYF("2026-04-01", periods=3, price=500.0)
        import yfinance
        monkeypatch.setattr(yfinance, "download", fake.download)

        df = store.load("SPY", freq="daily", fallback="auto",
                        start="2026-04-01", end="2026-04-03")
        assert len(df) == 3
        assert df["open"].iloc[0] == pytest.approx(500.0, abs=1e-3)

    def test_local_only_ignores_yfinance(self, tmp_path, monkeypatch):
        raw = _make_1m_frame("2020-06-01 09:30", 3, price=100.0)
        _write_bars(tmp_path, "SPY", "1m", raw)
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)

        import yfinance
        def boom(*a, **k): raise AssertionError("yfinance should not be called in fallback=local")
        monkeypatch.setattr(yfinance, "download", boom)

        df = store.load("SPY", freq="1m", fallback="local")
        assert len(df) == 3

    def test_hybrid_tail_fill_merges(self, tmp_path, monkeypatch):
        # Local ends 2026-03-31. Request through today → yfinance fills tail.
        raw = _make_1m_frame("2026-03-31 09:30", 2, price=100.0)
        # daily frame (date index)
        daily = pd.DataFrame({
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000, "amount": np.nan,
        }, index=pd.DatetimeIndex([pd.Timestamp("2026-03-31")], name="date"))
        _write_bars(tmp_path, "SPY", "daily", daily)
        _write_splits(tmp_path, [])

        # Force yfinance to return 2 days post-2026-03-31
        import yfinance
        def fake_download(symbol, start, end, interval, auto_adjust, progress, threads):
            idx = pd.DatetimeIndex([pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-02")],
                                   name="Date")
            return pd.DataFrame({
                "Open": 200.0, "High": 201.0, "Low": 199.0, "Close": 200.5,
                "Adj Close": 200.3, "Volume": 2000,
            }, index=idx)
        monkeypatch.setattr(yfinance, "download", fake_download)

        store = BarStore(tmp_path)
        df = store.load("SPY", freq="daily", fallback="auto",
                        end="2026-04-02")
        assert len(df) == 3
        assert df.loc[pd.Timestamp("2026-03-31"), "close"] == pytest.approx(100.5, abs=1e-3)
        assert df.loc[pd.Timestamp("2026-04-01"), "close"] == pytest.approx(200.5, abs=1e-3)


# ── provenance sidecar (P0.2 fix regression tests) ───────────────────────────

class TestProvenanceFirstBarTs:
    """Tests for the yfinance_fallback provenance row's `first_bar_ts`.

    Pre-fix bug (2026-04-20 P0.2): the expression
        `out.index.max() if local_df.empty or local_df.empty else local_df.index.max()`
    contained a duplicated-condition typo (`local_df.empty or local_df.empty`,
    always True when empty) AND used `out.index.max()` for the empty
    branch — semantically wrong. first_bar_ts should point at where the
    yfinance data STARTS, not ends.
    """

    def test_local_empty_first_bar_is_yfinance_start(self, tmp_path, monkeypatch):
        """When local is empty, the yfinance row's first_bar_ts should be
        the EARLIEST bar yfinance provided (== out.index.min()), not
        the latest."""
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)
        fake = FakeYF("2026-04-01", periods=3, price=500.0)
        import yfinance
        monkeypatch.setattr(yfinance, "download", fake.download)

        df = store.load("SPY", freq="daily", fallback="auto",
                        start="2026-04-01", end="2026-04-03")
        prov = df.attrs.get("provenance", [])
        yf_rows = [r for r in prov if r["source_type"] == "yfinance_fallback"]
        assert len(yf_rows) == 1
        row = yf_rows[0]
        assert row["first_bar_ts"] == df.index.min(), (
            f"first_bar_ts {row['first_bar_ts']} != out.index.min() "
            f"{df.index.min()} — regression of P0.2 typo fix"
        )
        assert row["last_bar_ts"] == df.index.max()

    def test_hybrid_first_bar_is_first_after_local(self, tmp_path, monkeypatch):
        """When local + yfinance are merged, the yfinance row's
        first_bar_ts should be the FIRST bar in the combined output
        that lies strictly AFTER the local tail — i.e. where yfinance
        actually started contributing."""
        daily = pd.DataFrame({
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1000, "amount": np.nan,
        }, index=pd.DatetimeIndex([pd.Timestamp("2026-03-31")], name="date"))
        _write_bars(tmp_path, "SPY", "daily", daily)
        _write_splits(tmp_path, [])

        import yfinance
        def fake_download(symbol, start, end, interval, auto_adjust, progress, threads):
            idx = pd.DatetimeIndex(
                [pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-02")],
                name="Date",
            )
            return pd.DataFrame({
                "Open": 200.0, "High": 201.0, "Low": 199.0, "Close": 200.5,
                "Adj Close": 200.3, "Volume": 2000,
            }, index=idx)
        monkeypatch.setattr(yfinance, "download", fake_download)

        store = BarStore(tmp_path)
        df = store.load("SPY", freq="daily", fallback="auto", end="2026-04-02")
        prov = df.attrs.get("provenance", [])
        yf_rows = [r for r in prov if r["source_type"] == "yfinance_fallback"]
        assert len(yf_rows) == 1
        row = yf_rows[0]
        # Local ends 2026-03-31; yfinance starts 2026-04-01 in merged df
        assert row["first_bar_ts"] == pd.Timestamp("2026-04-01")
        assert row["last_bar_ts"] == pd.Timestamp("2026-04-02")

    def test_local_only_no_yfinance_row(self, tmp_path, monkeypatch):
        """fallback='local' must never add a yfinance_fallback
        provenance row, even if local is empty."""
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)
        import yfinance
        monkeypatch.setattr(yfinance, "download",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("must not call yfinance")))
        df = store.load("SPY", freq="daily", fallback="local",
                        start="2026-04-01", end="2026-04-03")
        prov = df.attrs.get("provenance", [])
        yf_rows = [r for r in prov if r["source_type"] == "yfinance_fallback"]
        assert len(yf_rows) == 0


# ── misc ──────────────────────────────────────────────────────────────────────

class TestMisc:
    def test_list_symbols(self, tmp_path):
        for s in ["AAA", "BBB", "CCC"]:
            _write_bars(tmp_path, s, "1m", _make_1m_frame("2020-01-01", 1))
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)
        assert store.list_symbols("1m") == ["AAA", "BBB", "CCC"]

    def test_safe_symbol_sanitization(self, tmp_path):
        raw = _make_1m_frame("2020-01-01 09:30", 1, price=10.0)
        _write_bars(tmp_path, "^VIX", "1m", raw)  # sanitized to _VIX.parquet
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)

        df = store.load("^VIX", freq="1m", fallback="local")
        assert not df.empty
        # File should exist under sanitized name
        assert (tmp_path / "intraday" / "1m" / "_VIX.parquet").exists()

    def test_unsupported_freq_raises(self, tmp_path):
        store = BarStore(tmp_path)
        with pytest.raises(ValueError):
            store.load("SPY", freq="90m", fallback="local")


# ── Provenance ────────────────────────────────────────────────────────────────

def _write_provenance(root: Path, rows: list[dict]) -> None:
    ref = root / "ref"
    ref.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(ref / "bar_provenance.parquet", index=False)


class TestProvenance:
    def test_get_provenance_missing_sidecar(self, tmp_path):
        store = BarStore(tmp_path)
        assert store.get_provenance("SPY", "1m") == []

    def test_get_provenance_empty_for_unknown_symbol(self, tmp_path):
        _write_provenance(tmp_path, [{
            "symbol": "SPY", "freq": "1m",
            "source_type": "trades_backfill", "rule_version": "v1",
            "first_bar_ts": pd.Timestamp("2024-01-02"),
            "last_bar_ts": pd.Timestamp("2024-12-31"),
        }])
        store = BarStore(tmp_path)
        assert store.get_provenance("NVDA", "1m") == []

    def test_get_provenance_returns_rows(self, tmp_path):
        _write_provenance(tmp_path, [{
            "symbol": "SPY", "freq": "1m",
            "source_type": "trades_backfill", "rule_version": "v1",
            "first_bar_ts": pd.Timestamp("2024-01-02"),
            "last_bar_ts": pd.Timestamp("2024-12-31"),
        }])
        store = BarStore(tmp_path)
        rows = store.get_provenance("SPY", "1m")
        assert len(rows) == 1
        assert rows[0]["source_type"] == "trades_backfill"

    def test_get_provenance_symbol_sanitization(self, tmp_path):
        """^VIX must match provenance rows stored under sanitized _VIX."""
        _write_provenance(tmp_path, [{
            "symbol": "_VIX", "freq": "daily",
            "source_type": "yfinance", "rule_version": "auto_adjust_false",
            "first_bar_ts": pd.Timestamp("2007-01-03"),
            "last_bar_ts": pd.Timestamp("2026-04-20"),
        }])
        store = BarStore(tmp_path)
        rows = store.get_provenance("^VIX", "daily")
        assert len(rows) == 1 and rows[0]["source_type"] == "yfinance"

    def test_load_attaches_provenance_attr(self, tmp_path):
        _write_bars(tmp_path, "SPY", "1m",
                    _make_1m_frame("2024-01-02 09:30", 3, price=100.0))
        _write_splits(tmp_path, [])
        _write_provenance(tmp_path, [{
            "symbol": "SPY", "freq": "1m",
            "source_type": "trades_backfill", "rule_version": "v1",
            "first_bar_ts": pd.Timestamp("2024-01-02"),
            "last_bar_ts": pd.Timestamp("2024-01-02"),
        }])
        store = BarStore(tmp_path)
        df = store.load("SPY", freq="1m", fallback="local")
        assert "provenance" in df.attrs
        assert df.attrs["symbol"] == "SPY"
        assert df.attrs["freq"] == "1m"
        assert df.attrs["provenance"][0]["source_type"] == "trades_backfill"

    def test_load_attaches_empty_provenance_when_sidecar_missing(self, tmp_path):
        _write_bars(tmp_path, "SPY", "1m",
                    _make_1m_frame("2024-01-02 09:30", 3))
        _write_splits(tmp_path, [])
        store = BarStore(tmp_path)
        df = store.load("SPY", freq="1m", fallback="local")
        assert df.attrs.get("provenance") == []

    def test_list_backfill_tickers_1m_direct(self, tmp_path):
        _write_provenance(tmp_path, [
            {"symbol": "SPY", "freq": "1m", "source_type": "trades_backfill",
             "rule_version": "v1",
             "first_bar_ts": pd.Timestamp("2024-01-02"),
             "last_bar_ts": pd.Timestamp("2024-12-31")},
            {"symbol": "AAPL", "freq": "1m", "source_type": "stocks_csv",
             "rule_version": "v1",
             "first_bar_ts": pd.Timestamp("2024-01-02"),
             "last_bar_ts": pd.Timestamp("2024-12-31")},
        ])
        store = BarStore(tmp_path)
        assert store.list_backfill_tickers("1m") == {"SPY"}

    def test_list_backfill_tickers_aggregated_inherits_1m(self, tmp_path):
        """Daily aggregated from 1m-backfill inherits backfill source even if
        no direct daily sidecar row exists."""
        _write_provenance(tmp_path, [
            {"symbol": "SPY", "freq": "1m", "source_type": "trades_backfill",
             "rule_version": "v1",
             "first_bar_ts": pd.Timestamp("2024-01-02"),
             "last_bar_ts": pd.Timestamp("2024-12-31")},
        ])
        store = BarStore(tmp_path)
        assert store.list_backfill_tickers("daily") == {"SPY"}
        assert store.list_backfill_tickers("60m") == {"SPY"}
        assert store.list_backfill_tickers("5m") == {"SPY"}

    def test_list_backfill_tickers_empty_when_no_sidecar(self, tmp_path):
        store = BarStore(tmp_path)
        assert store.list_backfill_tickers("1m") == set()
        assert store.list_backfill_tickers("daily") == set()
