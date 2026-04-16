"""
Stage 3 Acceptance Test: Data Layer End-to-End

Checks:
1. YFinanceProvider downloads SPY/QQQ daily data
2. MarketDataStore persists and reads back correctly
3. DataValidator passes the downloaded data
4. FeaturePipeline computes features without errors
5. 60m intraday download + validation (smoke test)

Run with:
    pytest tests/integration/test_stage3_acceptance.py -v -s

Requires internet access.  Skipped automatically in CI if yfinance is unavailable
or the network is unreachable.
"""

from __future__ import annotations

import pytest
import pandas as pd

# Skip the whole module if there's no network (CI without internet)
pytest.importorskip("yfinance")


from core.data.yfinance_provider import YFinanceProvider
from core.data.market_data_store import MarketDataStore
from core.data.validator import DataValidator
from core.features.feature_pipeline import FeaturePipeline


SYMBOLS   = ["SPY", "QQQ"]
START     = "2022-01-01"   # ~2.5 years of daily data → well above 252-bar minimum
INTRADAY_PERIOD = "5d"


@pytest.fixture(scope="module")
def daily_frames(tmp_path_factory):
    """Download daily OHLCV for SYMBOLS — one fixture for the whole module."""
    provider = YFinanceProvider()
    try:
        return provider.fetch_daily(SYMBOLS, start=START)
    except Exception as exc:
        pytest.skip(f"Could not fetch daily data (network?): {exc}")


@pytest.fixture(scope="module")
def intraday_frames(tmp_path_factory):
    """Download 60m OHLCV — may fail for non-US symbols; skip if so."""
    provider = YFinanceProvider()
    try:
        return provider.fetch_intraday(SYMBOLS, freq="60m", period=INTRADAY_PERIOD)
    except Exception as exc:
        pytest.skip(f"Could not fetch intraday data: {exc}")


# ── 1. Download ────────────────────────────────────────────────────────────────

class TestDownload:
    def test_daily_returns_both_symbols(self, daily_frames):
        assert "SPY" in daily_frames
        assert "QQQ" in daily_frames

    def test_daily_has_enough_bars(self, daily_frames):
        for sym, frame in daily_frames.items():
            assert len(frame.df) >= 252, f"{sym} has only {len(frame.df)} daily bars"

    def test_daily_columns_correct(self, daily_frames):
        for sym, frame in daily_frames.items():
            assert list(frame.df.columns) == ["open", "high", "low", "close", "volume"]

    def test_daily_index_tz_naive(self, daily_frames):
        for sym, frame in daily_frames.items():
            assert frame.df.index.tz is None, f"{sym} index has tz: {frame.df.index.tz}"

    def test_intraday_returns_symbols(self, intraday_frames):
        assert len(intraday_frames) > 0

    def test_intraday_within_market_hours(self, intraday_frames):
        for sym, frame in intraday_frames.items():
            idx = frame.df.index
            for ts in idx:
                hm = ts.hour * 60 + ts.minute
                assert 9 * 60 + 30 <= hm < 16 * 60, (
                    f"{sym}: bar at {ts} is outside market hours"
                )


# ── 2. Persistence ─────────────────────────────────────────────────────────────

class TestPersistence:
    def test_write_and_read_roundtrip(self, tmp_path, daily_frames):
        store = MarketDataStore(tmp_path)
        for sym, frame in daily_frames.items():
            store.write(sym, "1d", frame.df)

        for sym in daily_frames:
            out = store.read(sym, "1d")
            original = daily_frames[sym].df
            assert len(out) == len(original), f"{sym}: length mismatch after roundtrip"

    def test_append_is_idempotent(self, tmp_path, daily_frames):
        store = MarketDataStore(tmp_path)
        sym   = "SPY"
        df    = daily_frames[sym].df

        store.write(sym, "1d", df)
        n_before = len(store.read(sym, "1d"))

        store.append(sym, "1d", df)  # re-append same data
        n_after = len(store.read(sym, "1d"))

        assert n_before == n_after, "Re-appending same data should not add rows"

    def test_get_last_date_correct(self, tmp_path, daily_frames):
        store = MarketDataStore(tmp_path)
        sym   = "SPY"
        df    = daily_frames[sym].df
        store.write(sym, "1d", df)
        last = store.get_last_date(sym, "1d")
        assert last == df.index[-1]


# ── 3. Validation ─────────────────────────────────────────────────────────────

class TestValidation:
    def test_daily_data_passes_validation(self, daily_frames):
        validator = DataValidator(min_bars=252)
        for sym, frame in daily_frames.items():
            result = validator.validate(frame.df, symbol=sym, freq="1d")
            # Issues (not warnings) should be empty for clean yfinance data
            assert result.issues == [], (
                f"{sym} failed validation: {result.issues}"
            )

    def test_intraday_data_passes_validation(self, intraday_frames):
        validator = DataValidator(min_bars=10)
        for sym, frame in intraday_frames.items():
            result = validator.validate(frame.df, symbol=sym, freq="60m")
            assert result.issues == [], (
                f"{sym}/60m failed validation: {result.issues}"
            )


# ── 4. Feature Pipeline ───────────────────────────────────────────────────────

class TestFeaturePipeline:
    def test_daily_features_no_error(self, daily_frames):
        pipe = FeaturePipeline()
        for sym, frame in daily_frames.items():
            feat = pipe.compute_daily(frame.df, symbol=sym)
            assert not feat.empty, f"{sym}: daily features empty"
            assert len(feat) == len(frame.df)

    def test_daily_key_features_present(self, daily_frames):
        pipe = FeaturePipeline()
        sym  = "SPY"
        feat = pipe.compute_daily(daily_frames[sym].df, symbol=sym)
        for col in ["ema20", "ema50", "rsi14", "atr14", "macd", "bb_upper", "hv20",
                    "volume_surge20", "close_zscore20"]:
            assert col in feat.columns, f"Missing daily feature: {col}"

    def test_intraday_features_no_error(self, daily_frames, intraday_frames):
        pipe = FeaturePipeline()
        sym  = "SPY"
        if sym not in intraday_frames:
            pytest.skip(f"{sym} not in intraday_frames")

        result = pipe.compute_intraday(
            primary_df = intraday_frames[sym].df,
            freq       = "60m",
            daily_df   = daily_frames[sym].df,
            symbol     = sym,
        )
        assert result.n_bars > 0
        assert not result.primary_features.empty
        assert "vwap" in result.primary_features.columns
        assert "d_rsi14" in result.primary_features.columns

    def test_confluence_score_in_range(self, daily_frames, intraday_frames):
        pipe = FeaturePipeline()
        sym  = "SPY"
        if sym not in intraday_frames:
            pytest.skip(f"{sym} not in intraday_frames")

        result = pipe.compute_intraday(
            primary_df = intraday_frames[sym].df,
            freq       = "60m",
            daily_df   = daily_frames[sym].df,
            symbol     = sym,
        )
        score = result.confluence_score
        assert (score >= 0.0).all() and (score <= 1.0).all(), (
            "Confluence score must be in [0, 1]"
        )

    def test_graceful_degradation_no_aux(self, daily_frames):
        """Pipeline should work fine even with no aux timeframes."""
        pipe = FeaturePipeline(graceful_degradation=True)
        sym  = "SPY"
        df_daily = daily_frames[sym].df

        # Use daily data as "intraday" to avoid network call
        result = pipe.compute_intraday(
            primary_df = df_daily,
            freq       = "1d",
            aux_frames = {},
            symbol     = sym,
        )
        assert result.n_bars > 0
        assert result.aux_available == {}
