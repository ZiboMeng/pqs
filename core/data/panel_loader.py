"""Shared panel / benchmark loaders with strict data validation.

Centralizes the "load close panel from MarketDataStore, then slice by
date" pattern that repeats across R20-R27 universe diagnostic tools.
Multiple scripts were constructing empty DataFrames when real data was
missing, then crashing on `price_df.index >= "2020-01-01"` because
pandas cannot compare RangeIndex (empty default) against a string.

This helper:
  - Validates panel is non-empty and has DatetimeIndex
  - Validates benchmark has required 'close' column
  - Fails fast with clear error (sys.exit(2) or pytest.skip) instead of
    propagating pandas internals
  - Returns typed, date-sliced frames ready to use

Use by (post-R28):
  - scripts/universe_alpha_diagnostic.py
  - scripts/universe_risk_labels.py
  - tests/integration/test_backtest_paper_consistency.py
  - future panel-consuming tools
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from core.data.market_data_store import MarketDataStore
from core.logging_setup import get_logger

logger = get_logger(__name__)


class PanelLoadError(RuntimeError):
    """Raised when panel / benchmark loading fails validation. Callers
    can catch this to decide between sys.exit(2) or pytest.skip()."""


def load_close_panel(
    store: MarketDataStore,
    symbols: Iterable[str],
    start: Optional[str] = None,
    min_symbols: int = 1,
    min_days: int = 2,
) -> pd.DataFrame:
    """Load close-price panel and validate shape + index type.

    Parameters
    ----------
    store     : MarketDataStore
    symbols   : symbols to load
    start     : optional ISO date string; rows before are dropped
    min_symbols : panel must have at least this many columns (else raise)
    min_days  : panel must have at least this many rows (else raise)

    Returns
    -------
    pd.DataFrame with DatetimeIndex, close prices only.

    Raises
    ------
    PanelLoadError if panel is empty, lacks DatetimeIndex, or fails
    min_symbols / min_days.
    """
    frames = {}
    for sym in symbols:
        df = store.read(sym, "1d")
        if df is None or df.empty or "close" not in df.columns:
            continue
        frames[sym] = df["close"]
    if not frames:
        raise PanelLoadError(
            f"no usable data for any of {list(symbols)[:5]}... "
            f"(check MarketDataStore path {store._data_dir if hasattr(store, '_data_dir') else ''})"
        )
    panel = pd.DataFrame(frames).sort_index()
    if not isinstance(panel.index, pd.DatetimeIndex):
        raise PanelLoadError(
            f"panel has non-DatetimeIndex ({type(panel.index).__name__}); "
            f"MarketDataStore output is malformed. n_cols={panel.shape[1]}"
        )
    if panel.shape[1] < min_symbols:
        raise PanelLoadError(
            f"panel has only {panel.shape[1]} symbols (need ≥ {min_symbols})"
        )
    if start:
        panel = panel.loc[panel.index >= start]
    if len(panel) < min_days:
        raise PanelLoadError(
            f"panel has only {len(panel)} days after start={start} "
            f"(need ≥ {min_days})"
        )
    return panel


def load_benchmark_close(
    store: MarketDataStore,
    symbol: str,
    start: Optional[str] = None,
    min_days: int = 252,
) -> pd.Series:
    """Load a single benchmark's close series with validation.

    Raises PanelLoadError if data is missing, has no 'close' column, or
    is too short after date slicing.
    """
    df = store.read(symbol, "1d")
    if df is None or df.empty:
        raise PanelLoadError(
            f"benchmark {symbol} data is missing or empty"
        )
    if "close" not in df.columns:
        raise PanelLoadError(
            f"benchmark {symbol} lacks 'close' column "
            f"(columns: {list(df.columns)})"
        )
    if not isinstance(df.index, pd.DatetimeIndex):
        raise PanelLoadError(
            f"benchmark {symbol} has non-DatetimeIndex "
            f"({type(df.index).__name__})"
        )
    series = df["close"]
    if start:
        series = series.loc[series.index >= start]
    if len(series) < min_days:
        raise PanelLoadError(
            f"benchmark {symbol} has only {len(series)} days after "
            f"start={start} (need ≥ {min_days})"
        )
    return series


def load_close_panel_or_exit(
    store: MarketDataStore,
    symbols: Iterable[str],
    start: Optional[str] = None,
    min_symbols: int = 1,
    min_days: int = 2,
    exit_code: int = 2,
) -> pd.DataFrame:
    """CLI-friendly wrapper: calls load_close_panel; on failure, logs
    clear error and sys.exit(exit_code). Use in scripts where graceful
    user messaging is preferred to stack traces."""
    try:
        return load_close_panel(store, symbols, start,
                                min_symbols=min_symbols, min_days=min_days)
    except PanelLoadError as exc:
        logger.error("Panel load failed: %s", exc)
        sys.exit(exit_code)


def load_benchmark_close_or_exit(
    store: MarketDataStore,
    symbol: str,
    start: Optional[str] = None,
    min_days: int = 252,
    exit_code: int = 2,
) -> pd.Series:
    """CLI-friendly wrapper: logs error and sys.exit on missing benchmark."""
    try:
        return load_benchmark_close(store, symbol, start, min_days=min_days)
    except PanelLoadError as exc:
        logger.error("Benchmark load failed: %s", exc)
        sys.exit(exit_code)


def load_close_panel_or_skip(
    store: MarketDataStore,
    symbols: Iterable[str],
    start: Optional[str] = None,
    min_symbols: int = 1,
    min_days: int = 2,
) -> pd.DataFrame:
    """pytest-friendly wrapper: calls pytest.skip() on failure. Use in
    integration test fixtures that require real data but should skip
    gracefully when data is missing."""
    try:
        return load_close_panel(store, symbols, start,
                                min_symbols=min_symbols, min_days=min_days)
    except PanelLoadError as exc:
        import pytest
        pytest.skip(f"Panel load failed: {exc}")
