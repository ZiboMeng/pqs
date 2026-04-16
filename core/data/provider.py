"""
DataProvider abstraction layer.

All data access goes through this interface.
Concrete implementations: YFinanceProvider (current), future: Polygon, Alpaca, etc.

Each provider returns standardised DataFrames:
  - Daily:    columns [open, high, low, close, volume], tz-naive date index
  - Intraday: columns [open, high, low, close, volume], US/Eastern tz-naive datetime index
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

import pandas as pd


# ── Column name contract ──────────────────────────────────────────────────────

OHLCV_COLS = ["open", "high", "low", "close", "volume"]


class OHLCVFrame:
    """
    A validated, standardised OHLCV DataFrame for a single symbol.
    columns: open, high, low, close, volume (all lowercase)
    index:   DatetimeIndex (tz-naive)
    """

    def __init__(self, df: pd.DataFrame, symbol: str, freq: str):
        self.symbol = symbol
        self.freq   = freq
        self.df     = self._validate(df)

    def _validate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        for col in OHLCV_COLS:
            if col not in df.columns:
                if col == "volume":
                    df["volume"] = 0.0
                else:
                    raise ValueError(
                        f"[{self.symbol}] Missing required column: {col!r}. "
                        f"Got: {list(df.columns)}"
                    )
        return df[OHLCV_COLS].copy()

    @property
    def close(self) -> pd.Series:
        return self.df["close"]

    @property
    def volume(self) -> pd.Series:
        return self.df["volume"]

    def __len__(self) -> int:
        return len(self.df)

    def __repr__(self) -> str:
        if self.df.empty:
            return f"OHLCVFrame({self.symbol}, {self.freq}, empty)"
        return (
            f"OHLCVFrame({self.symbol}, {self.freq}, "
            f"rows={len(self.df)}, "
            f"{self.df.index[0].date()}→{self.df.index[-1].date()})"
        )


# ── Abstract base ─────────────────────────────────────────────────────────────

class DataProvider(ABC):
    """
    Abstract interface for market data access.

    Concrete implementations must implement:
      - fetch_daily()
      - fetch_intraday()
    """

    @abstractmethod
    def fetch_daily(
        self,
        symbols: List[str],
        start:   str | date | pd.Timestamp,
        end:     Optional[str | date | pd.Timestamp] = None,
    ) -> Dict[str, OHLCVFrame]:
        """
        Fetch daily OHLCV for one or more symbols.

        Returns:
            Dict[symbol → OHLCVFrame] with tz-naive date index.
            Missing symbols are absent from the dict (not raised).
        """
        ...

    @abstractmethod
    def fetch_intraday(
        self,
        symbols: List[str],
        freq:    str,
        start:   Optional[str | date | pd.Timestamp] = None,
        end:     Optional[str | date | pd.Timestamp] = None,
        period:  Optional[str] = None,
    ) -> Dict[str, OHLCVFrame]:
        """
        Fetch intraday OHLCV for one or more symbols.

        Args:
            symbols: list of ticker symbols
            freq:    bar frequency e.g. '5m', '15m', '30m', '60m'
            start/end: date range (cannot be used with period)
            period:  yfinance period string e.g. '60d' (cannot be used with start/end)

        Returns:
            Dict[symbol → OHLCVFrame] with US/Eastern tz-naive datetime index.
        """
        ...

    def fetch_auxiliary(
        self,
        symbol: str,
        start:  str | date | pd.Timestamp,
        end:    Optional[str | date | pd.Timestamp] = None,
    ) -> pd.Series:
        """
        Fetch a single auxiliary time series (e.g. VIX, TNX, DXY).
        Returns a pd.Series indexed by date/datetime.
        Default: delegates to fetch_daily() and returns 'close'.
        """
        frames = self.fetch_daily([symbol], start=start, end=end)
        if symbol not in frames:
            return pd.Series(dtype=float, name=symbol)
        return frames[symbol].close.rename(symbol)
