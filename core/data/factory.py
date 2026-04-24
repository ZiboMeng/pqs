"""Data-access factory — single entry point for paper/backtest scripts.

Phase E-post R4 (E-post-1): decouples paper path from a specific
backend class. Scripts should call ``create_default_store(cfg)`` and
depend on the ``PriceStore`` Protocol — not on ``MarketDataStore``
directly. This localizes the choice of backend to one module so that:

  - Future vendor swaps touch exactly one file
  - Paper / backtest scripts can be type-checked against a narrow
    interface rather than a concrete parquet implementation
  - Tests can inject a fake/mock PriceStore without importing
    MarketDataStore (and hence without any parquet code path)

Design constraints (PRD §4.1):
  - "paper 层逻辑依赖'数据访问边界'，而不是具体 parquet store 类"
  - "不要求整个 data layer 全量重构，只要求把 paper path 解耦出来"

The Protocol is intentionally minimal — only the ``read`` method is
required, because that is the only MarketDataStore method the paper
scripts actually use for their core loop. Other MarketDataStore
methods (write/append/get_last_date/etc.) are NOT part of this
boundary — callers that need them should continue to depend on
MarketDataStore directly, which is correct: those are ingestion-side
concerns, not paper-side concerns.

Usage:
    from core.data.factory import create_default_store, PriceStore

    store: PriceStore = create_default_store(cfg)
    df = store.read("SPY", "1d")
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class PriceStore(Protocol):
    """Narrow read-only interface the paper layer depends on."""

    def read(
        self, symbol: str, freq: str,
    ) -> Optional[pd.DataFrame]:
        """Return the OHLCV DataFrame for (symbol, freq), or None if
        not available. Callers must be tolerant of None / empty frames.
        """
        ...


def create_default_store(cfg) -> PriceStore:
    """Return the default PriceStore implementation for the given cfg.

    Today this returns a ``MarketDataStore`` pointed at
    ``cfg.system.paths.data_dir``. The import is deferred so that
    callers who only need the Protocol surface (e.g. tests with a fake
    store) do not drag in the concrete backend's dependencies.

    If we later add alternative backends (e.g. an in-memory store for
    testing, a BarStore wrapper, a SQL-backed cache) the choice should
    be plumbed through here — never through the caller.
    """
    from pathlib import Path
    from core.data.market_data_store import MarketDataStore

    return MarketDataStore(data_dir=Path(cfg.system.paths.data_dir))
