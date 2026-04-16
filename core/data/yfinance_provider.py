"""
YFinance implementation of DataProvider.

Handles:
- Multi-symbol downloads (MultiIndex → per-symbol split)
- yfinance 0.2.x API compatibility
- Retry on transient failures
- Timezone normalisation via calendar module
"""

from __future__ import annotations

import time
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from core.data.calendar import align_daily_index, align_intraday_index, filter_to_market_hours
from core.data.provider import DataProvider, OHLCVFrame, OHLCV_COLS
from core.logging_setup import get_logger

logger = get_logger(__name__)

# yfinance interval string mapping
_FREQ_MAP = {
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "1h":  "60m",
    "1d":  "1d",
}

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds


class YFinanceProvider(DataProvider):
    """
    DataProvider backed by yfinance.

    Notes on yfinance intraday history limits (as of 2024):
        5m  → max 60 days
        15m → max 60 days
        30m → max 60 days
        60m → max 730 days (~2 years)
        1d  → unlimited
    """

    def __init__(self, auto_adjust: bool = True, progress: bool = False):
        self.auto_adjust = auto_adjust
        self.progress    = progress

    # ── Public interface ──────────────────────────────────────────────────────

    def fetch_daily(
        self,
        symbols: List[str],
        start:   str | date | pd.Timestamp,
        end:     Optional[str | date | pd.Timestamp] = None,
    ) -> Dict[str, OHLCVFrame]:
        """Download daily OHLCV and return normalised frames."""
        raw = self._download(
            symbols=symbols,
            interval="1d",
            start=str(pd.Timestamp(start).date()),
            end=str(pd.Timestamp(end).date()) if end else None,
        )
        result: Dict[str, OHLCVFrame] = {}
        for symbol in symbols:
            df = self._extract_symbol(raw, symbol, symbols)
            if df is None or df.empty:
                logger.warning("[%s] No daily data returned", symbol)
                continue
            df = align_daily_index(df)
            df = df[~df.index.duplicated(keep="last")]
            result[symbol] = OHLCVFrame(df, symbol=symbol, freq="1d")
        return result

    def fetch_intraday(
        self,
        symbols: List[str],
        freq:    str,
        start:   Optional[str | date | pd.Timestamp] = None,
        end:     Optional[str | date | pd.Timestamp] = None,
        period:  Optional[str] = None,
    ) -> Dict[str, OHLCVFrame]:
        """Download intraday OHLCV and return normalised frames."""
        yf_interval = _FREQ_MAP.get(freq)
        if yf_interval is None:
            raise ValueError(f"Unsupported intraday freq: {freq!r}. Supported: {list(_FREQ_MAP)}")

        if period and (start or end):
            raise ValueError("Specify either period OR start/end, not both.")
        if not period and not start:
            raise ValueError("Must specify either period or start.")

        kwargs: dict = dict(interval=yf_interval)
        if period:
            kwargs["period"] = period
        else:
            kwargs["start"] = str(pd.Timestamp(start).date())
            if end:
                kwargs["end"] = str(pd.Timestamp(end).date())

        raw = self._download(symbols=symbols, **kwargs)

        result: Dict[str, OHLCVFrame] = {}
        for symbol in symbols:
            df = self._extract_symbol(raw, symbol, symbols)
            if df is None or df.empty:
                logger.warning("[%s] No intraday data returned for freq=%s", symbol, freq)
                continue
            df = align_intraday_index(df)
            df = filter_to_market_hours(df)
            df = df[~df.index.duplicated(keep="last")]
            if df.empty:
                logger.warning("[%s] No data after market-hours filter (freq=%s)", symbol, freq)
                continue
            result[symbol] = OHLCVFrame(df, symbol=symbol, freq=freq)
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _download(self, symbols: List[str], **kwargs) -> pd.DataFrame:
        """Call yf.download() with retries."""
        import yfinance as yf

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                raw = yf.download(
                    tickers=symbols,
                    auto_adjust=self.auto_adjust,
                    progress=self.progress,
                    **kwargs,
                )
                if not isinstance(raw, pd.DataFrame) or raw.empty:
                    raise ValueError("yfinance returned empty DataFrame")
                return raw
            except Exception as exc:
                if attempt == _MAX_RETRIES:
                    raise RuntimeError(
                        f"yfinance download failed after {_MAX_RETRIES} attempts: {exc}"
                    ) from exc
                logger.warning(
                    "yfinance download attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt, _MAX_RETRIES, exc, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)

    @staticmethod
    def _extract_symbol(
        raw: pd.DataFrame,
        symbol: str,
        all_symbols: List[str],
    ) -> Optional[pd.DataFrame]:
        """
        Extract a single symbol's OHLCV from a yfinance download result.

        yfinance 0.2.x returns different shapes depending on number of symbols:
          single symbol  → flat DataFrame, columns = [Open, High, Low, Close, Volume, ...]
          multi symbols  → MultiIndex columns = (Price, Ticker) or (Ticker, Price)
        """
        if raw is None or raw.empty:
            return None

        if isinstance(raw.columns, pd.MultiIndex):
            return YFinanceProvider._extract_from_multiindex(raw, symbol)

        # Single-symbol flat DataFrame
        if len(all_symbols) == 1:
            df = raw.copy()
            df.columns = [c.lower() for c in df.columns]
            needed = [c for c in OHLCV_COLS if c in df.columns]
            return df[needed] if needed else None

        return None

    @staticmethod
    def _extract_from_multiindex(raw: pd.DataFrame, symbol: str) -> Optional[pd.DataFrame]:
        """Handle yfinance MultiIndex output for multiple tickers."""
        levels = raw.columns.names  # e.g. ['Price', 'Ticker'] or ['Ticker', 'Price']

        # Determine which level holds the ticker name
        # yfinance 0.2.x: levels = ('Price', 'Ticker')
        # yfinance 0.1.x: levels = ('Ticker', 'Price') — older format
        try:
            ticker_level = levels.index("Ticker")
        except (ValueError, AttributeError):
            ticker_level = 0  # fallback

        price_level = 1 - ticker_level  # the other level

        try:
            if ticker_level == 1:
                # MultiIndex: (Price, Ticker) — yfinance 0.2.x default
                df = raw.xs(symbol, axis=1, level="Ticker")
            else:
                # MultiIndex: (Ticker, Price)
                df = raw[symbol]
        except KeyError:
            return None

        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        return df
