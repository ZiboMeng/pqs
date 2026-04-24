"""Tests for the VIX loader fail-closed semantics (P0.3, 2026-04-20).

Before this loader, run_paper.py silently fell back to a constant
20.0 VIX series when ^VIX was missing. On black-swan days (real VIX
>40) this misclassifies CRISIS → NEUTRAL and allows full-size trades.
These tests enforce:

  - strict mode raises when VIX unavailable or latest bar NaN
  - lenient mode warns + returns constant series, never raises
  - diagnostic attrs (fallback_bars, fallback_mode) are set correctly
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pandas as pd
import pytest

from core.data.vix_loader import load_vix_series, VixDataMissingError


def _make_store(vix_df):
    """Build a fake store with only the methods the loader uses."""
    store = MagicMock()
    if vix_df is None:
        store.get_last_date.return_value = None
        store.read.return_value = None
    else:
        store.get_last_date.return_value = vix_df.index[-1] if not vix_df.empty else None
        store.read.return_value = vix_df
    return store


def _vix_df(start, periods, value=20.0):
    idx = pd.date_range(start, periods=periods, freq="B")
    return pd.DataFrame({"close": [float(value)] * periods}, index=idx)


class TestStrictMode:
    def test_missing_store_raises(self):
        store = _make_store(None)
        idx = pd.date_range("2026-01-02", periods=3, freq="B")
        with pytest.raises(VixDataMissingError):
            load_vix_series(store, idx, mode="strict")

    def test_empty_dataframe_raises(self):
        store = _make_store(pd.DataFrame(columns=["close"]))
        store.get_last_date.return_value = None  # empty → no last date
        idx = pd.date_range("2026-01-02", periods=3, freq="B")
        with pytest.raises(VixDataMissingError):
            load_vix_series(store, idx, mode="strict")

    def test_latest_nan_raises(self):
        """VIX present but NaN at the most recent decision point →
        strict must refuse. This is the common live failure mode when
        today's VIX hasn't been ingested yet."""
        # VIX covers [2026-01-02 .. 2026-01-05], but request goes to
        # 2026-01-10 — after ffill the tail carries the last known
        # value, so not-NaN. To trigger: VIX older than target tail
        # yields NaN in reindex-ffill? Actually ffill would carry.
        # So to truly trigger: VIX whose last bar < target_index[0]
        # but ffill still carries, not NaN.
        # The real case: price_df_1d.index[0] < vix.index[0] — a
        # forward gap ffill can't fill. Use an index that STARTS
        # before VIX, then request spans past-only.
        vix = _vix_df("2026-01-02", periods=3, value=15.0)  # starts 2026-01-02
        store = _make_store(vix)
        # Target starts BEFORE vix and ends BEFORE vix too → no ffill carry
        idx = pd.date_range("2025-12-29", periods=3, freq="B")
        with pytest.raises(VixDataMissingError):
            load_vix_series(store, idx, mode="strict")

    def test_ok_path(self):
        vix = _vix_df("2026-01-02", periods=5, value=15.0)
        store = _make_store(vix)
        out = load_vix_series(store, vix.index, mode="strict")
        assert (out == 15.0).all()
        assert out.attrs["fallback_bars"] == 0


class TestLenientMode:
    def test_missing_store_falls_back(self, caplog):
        store = _make_store(None)
        idx = pd.date_range("2026-01-02", periods=3, freq="B")
        with caplog.at_level(logging.WARNING):
            out = load_vix_series(store, idx, mode="lenient",
                                  fallback_value=20.0)
        assert (out == 20.0).all()
        assert out.attrs["fallback_bars"] == 3
        assert out.attrs["fallback_mode"] == "all_missing"
        assert any("falling back to constant" in r.message
                   for r in caplog.records)

    def test_partial_nan_filled(self, caplog):
        """VIX starts after target_index[0] → early bars NaN after
        ffill → lenient fills with fallback."""
        vix = _vix_df("2026-01-05", periods=5, value=15.0)
        store = _make_store(vix)
        idx = pd.date_range("2026-01-01", periods=10, freq="B")
        with caplog.at_level(logging.WARNING):
            out = load_vix_series(store, idx, mode="lenient",
                                  fallback_value=25.0)
        # Pre-2026-01-05 bars filled with 25.0
        assert not out.isna().any()
        # Tail should be 15.0 (ffill from VIX), early should be 25.0
        assert out.iloc[-1] == 15.0
        assert out.iloc[0] == 25.0
        assert out.attrs["fallback_bars"] > 0

    def test_no_fallback_needed(self):
        vix = _vix_df("2026-01-02", periods=5, value=18.0)
        store = _make_store(vix)
        out = load_vix_series(store, vix.index, mode="lenient")
        assert out.attrs["fallback_bars"] == 0
        assert (out == 18.0).all()


class TestErrorMessageHelpful:
    def test_strict_error_names_symbol(self):
        store = _make_store(None)
        idx = pd.date_range("2026-01-02", periods=2, freq="B")
        with pytest.raises(VixDataMissingError, match="VIX"):
            load_vix_series(store, idx, mode="strict")
