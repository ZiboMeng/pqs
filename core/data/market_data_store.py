"""
MarketDataStore: Parquet-based incremental cache for OHLCV data.

Design principles:
- One parquet file per (symbol, freq): data/daily/SPY.parquet, data/intraday/60m/SPY.parquet
- Incremental append: load → concat new rows → dedup by index → sort → save
- Cache staleness: based on last data timestamp, NOT file mtime
- Thread-safe reads; single-writer append (no concurrent writes needed for MVP)

Usage:
    store = MarketDataStore(data_dir=Path("data"))
    store.write("SPY", "1d", df)
    df = store.read("SPY", "1d", start="2020-01-01")
    store.append("SPY", "60m", new_bars_today)
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# R2 (Phase E-0) — pyarrow lazily imported inside the methods that use
# it (`has_min_bars`, `_write_parquet`). This keeps `import
# core.data.market_data_store` cheap for callers that only need symbol-
# path helpers or the class itself (e.g. tests that pass a mocked
# store), and ensures modules that transit through `core/data/__init__`
# (notably core.paper_trading.paper_trading_engine) do not drag
# pyarrow into sys.modules.
from core.logging_setup import get_logger

logger = get_logger(__name__)


class MarketDataStore:
    """
    Parquet-based cache for market data (OHLCV).

    Directory layout:
        {data_dir}/
        ├── daily/
        │   ├── SPY.parquet
        │   ├── QQQ.parquet
        │   └── ...
        └── intraday/
            ├── 5m/
            │   ├── SPY.parquet
            │   └── ...
            ├── 15m/
            ├── 30m/
            └── 60m/
    """

    _INTRADAY_FREQS = {"5m", "15m", "30m", "60m", "1h"}

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def write(self, symbol: str, freq: str, df: pd.DataFrame) -> None:
        """
        Write (overwrite) data for a symbol/freq.
        Use append() for incremental updates.
        """
        if df.empty:
            return
        path = self._parquet_path(symbol, freq)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_parquet(df, path)
        logger.debug("[%s/%s] Written %d rows → %s", symbol, freq, len(df), path)

    def append(self, symbol: str, freq: str, new_df: pd.DataFrame) -> int:
        """
        Incrementally append new rows to existing parquet.
        Deduplicates on index; newer rows win on conflict.

        Returns:
            Number of new rows actually added.
        """
        if new_df.empty:
            return 0
        path = self._parquet_path(symbol, freq)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = _read_parquet(path)
            combined = pd.concat([existing, new_df]).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
        else:
            combined = new_df.copy().sort_index()

        prev_len = len(_read_parquet(path)) if path.exists() else 0
        _write_parquet(combined, path)
        new_count = len(combined) - prev_len
        logger.debug(
            "[%s/%s] Appended +%d rows (total %d)", symbol, freq, new_count, len(combined)
        )
        return new_count

    def read(
        self,
        symbol: str,
        freq:   str,
        start:  Optional[str | date | pd.Timestamp] = None,
        end:    Optional[str | date | pd.Timestamp] = None,
    ) -> pd.DataFrame:
        """
        Read data for a symbol/freq, optionally filtered to [start, end].
        Returns empty DataFrame if no data exists.
        """
        path = self._parquet_path(symbol, freq)
        if not path.exists():
            return pd.DataFrame()

        df = _read_parquet(path)
        if df.empty:
            return df

        if start is not None:
            start_ts = pd.Timestamp(start).tz_localize(None)
            df = df.loc[df.index >= start_ts]
        if end is not None:
            end_ts = pd.Timestamp(end).tz_localize(None)
            df = df.loc[df.index <= end_ts]
        return df

    def read_multi(
        self,
        symbols: List[str],
        freq:    str,
        start:   Optional[str | date | pd.Timestamp] = None,
        end:     Optional[str | date | pd.Timestamp] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Read data for multiple symbols at once."""
        return {
            sym: self.read(sym, freq, start=start, end=end)
            for sym in symbols
        }

    def get_last_date(self, symbol: str, freq: str) -> Optional[pd.Timestamp]:
        """
        Return the most recent index timestamp in the cache.
        Used for staleness checks based on DATA timestamp (not file mtime).
        """
        path = self._parquet_path(symbol, freq)
        if not path.exists():
            return None
        try:
            df = _read_parquet(path)
            if df.empty:
                return None
            return df.index[-1]
        except Exception:
            return None

    def is_stale(
        self,
        symbol:        str,
        freq:          str,
        max_age_hours: float = 20.0,
    ) -> bool:
        """
        Check if cached data is stale, based on the LAST DATA TIMESTAMP.
        (Not file mtime — avoids false "fresh" when cache file is recent but data is old.)

        Returns True if data is missing or the last bar is older than max_age_hours.
        """
        last = self.get_last_date(symbol, freq)
        if last is None:
            return True
        # For daily data: stale if last bar is > 1 trading day ago (rough check)
        now_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
        age = now_utc - last.tz_localize(None) if last.tzinfo else now_utc - last
        return age > timedelta(hours=max_age_hours)

    def has_min_bars(self, symbol: str, freq: str, min_bars: int) -> bool:
        """Return True if cached data has at least min_bars rows."""
        path = self._parquet_path(symbol, freq)
        if not path.exists():
            return False
        try:
            import pyarrow.parquet as pq  # R2: lazy
            pf = pq.read_metadata(path)
            return pf.num_rows >= min_bars
        except Exception:
            df = self.read(symbol, freq)
            return len(df) >= min_bars

    def list_symbols(self, freq: str) -> List[str]:
        """Return all symbols that have data for a given freq."""
        freq_dir = self._freq_dir(freq)
        if not freq_dir.exists():
            return []
        return sorted(p.stem for p in freq_dir.glob("*.parquet"))

    def delete(self, symbol: str, freq: str) -> bool:
        """Delete cached data for a symbol/freq. Returns True if file existed."""
        path = self._parquet_path(symbol, freq)
        if path.exists():
            path.unlink()
            return True
        return False

    # ── Path helpers ──────────────────────────────────────────────────────────

    def _freq_dir(self, freq: str) -> Path:
        if freq == "1d" or freq == "daily":
            return self.data_dir / "daily"
        return self.data_dir / "intraday" / freq

    def _parquet_path(self, symbol: str, freq: str) -> Path:
        safe_symbol = symbol.replace("^", "_").replace("-", "_")
        return self._freq_dir(freq) / f"{safe_symbol}.parquet"


# ── Parquet I/O helpers ───────────────────────────────────────────────────────

def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write DataFrame to parquet with consistent settings.

    R2 (Phase E-0) — pyarrow imported lazily; see module-level comment.
    """
    import pyarrow as pa                # R2: lazy
    import pyarrow.parquet as pq        # R2: lazy
    table = pa.Table.from_pandas(df, preserve_index=True)
    pq.write_table(
        table,
        path,
        compression="snappy",
        write_statistics=True,
    )


def _read_parquet(path: Path) -> pd.DataFrame:
    """Read parquet file to DataFrame."""
    df = pd.read_parquet(path)
    # Ensure tz-naive index for consistent comparisons
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index.name = df.index.name or "datetime"
    return df
