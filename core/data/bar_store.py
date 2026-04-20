"""
BarStore: parquet loader with read-time forward split adjustment + yfinance fallback.

Layout:
  pqs/data/
    intraday/1m/<SYMBOL>.parquet   (RAW, DatetimeIndex tz-naive ET)
    intraday/5m/<SYMBOL>.parquet
    intraday/15m/<SYMBOL>.parquet
    intraday/30m/<SYMBOL>.parquet
    intraday/60m/<SYMBOL>.parquet
    daily/<SYMBOL>.parquet          (RAW, date index)
    ref/splits.parquet              (symbol, date, from, to)
    .yf_cache/<HASH>.parquet        (yfinance fallback cache, 1-day TTL)

Forward adjustment (standard quant convention):
  adj_factor(t) = Π (from_i / to_i)  over splits i where date_i > t
  adj_price(t)  = raw_price(t) * adj_factor(t)
  adj_volume(t) = raw_volume(t) / adj_factor(t)
  adj_amount    = unchanged (dollar value is invariant to splits)

yfinance fallback (for ETF 2024+ gap in local data):
  fallback='auto' (default): if the requested range extends past what local
    parquet covers, fetch the missing tail from yfinance and merge in.
  fallback='local': no fallback, return only local data.
  fallback='yfinance': ignore local, fetch purely from yfinance.

yfinance coverage limits (as of Apr 2026):
  1m  → last 60 days
  5m/15m/30m/60m → last 730 days
  daily → full history (decades)

Usage:
  store = BarStore()
  spy_1m = store.load("SPY", freq="1m", adjusted=True)
  raw_   = store.load("SPY", freq="1m", adjusted=False)
  hybrid = store.load("SPY", freq="60m", start="2015", end="2026-04")  # auto-fills yfinance
"""
from __future__ import annotations

import hashlib
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_ROOT = Path(os.path.expanduser("~/Documents/projects/pqs/data"))

_VALID_FREQS = {"1m", "5m", "15m", "30m", "60m", "daily", "1d"}

# yfinance interval labels + coverage horizon (days back from today)
_YF_INTERVAL = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m",
    "daily": "1d", "1d": "1d",
}
_YF_MAX_DAYS = {
    "1m": 59, "5m": 720, "15m": 720, "30m": 720, "60m": 720,
    "daily": 365 * 50, "1d": 365 * 50,
}

_YF_CACHE_TTL_SEC = 86400  # 1 day


def _safe_symbol(sym: str) -> str:
    return sym.replace("^", "_").replace("-", "_")


class BarStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root)
        self._splits: Optional[pd.DataFrame] = None

    # ── paths ────────────────────────────────────────────────────────────────

    def _freq_dir(self, freq: str) -> Path:
        if freq in ("daily", "1d"):
            return self.root / "daily"
        return self.root / "intraday" / freq

    def _bar_path(self, symbol: str, freq: str) -> Path:
        return self._freq_dir(freq) / f"{_safe_symbol(symbol)}.parquet"

    def _splits_path(self) -> Path:
        return self.root / "ref" / "splits.parquet"

    # ── splits ref ───────────────────────────────────────────────────────────

    @property
    def splits(self) -> pd.DataFrame:
        """Cached canonical splits table."""
        if self._splits is None:
            p = self._splits_path()
            if not p.exists():
                self._splits = pd.DataFrame(
                    columns=["symbol", "date", "from", "to"]
                )
            else:
                self._splits = pd.read_parquet(p)
        return self._splits

    def _splits_for(self, symbol: str, as_of: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """Splits for one symbol, with future-dated (> as_of) removed.

        as_of defaults to today; pass pd.Timestamp.max to include future splits.
        """
        df = self.splits
        sub = df[df["symbol"] == symbol].copy()
        if sub.empty:
            return sub
        if as_of is None:
            as_of = pd.Timestamp.today().normalize()
        sub = sub[sub["date"] <= as_of]
        return sub.sort_values("date").reset_index(drop=True)

    # ── core load ────────────────────────────────────────────────────────────

    def load(
        self,
        symbol: str,
        freq: str = "1m",
        adjusted: bool = True,
        start: Optional[str | pd.Timestamp] = None,
        end: Optional[str | pd.Timestamp] = None,
        as_of: Optional[pd.Timestamp] = None,
        fallback: str = "auto",
    ) -> pd.DataFrame:
        """Load bars for (symbol, freq). Forward-adjusted by default.

        fallback:
          'auto'     — local + yfinance tail-fill (default)
          'local'    — local only
          'yfinance' — yfinance only (skip local)

        Provenance: every returned DataFrame carries data-source metadata on
        `.attrs["provenance"]` — list of dicts with keys
        ``{symbol, freq, source_type, rule_version, first_bar_ts, last_bar_ts}``.
        Callers can use this to filter out volume-sensitive factors on
        backfilled tickers, or to flag mixed-source results in reports.
        See `get_provenance()` for direct sidecar lookup.
        """
        if freq not in _VALID_FREQS:
            raise ValueError(f"unsupported freq: {freq}")
        if fallback not in ("auto", "local", "yfinance"):
            raise ValueError(f"unsupported fallback: {fallback}")

        local_df = self._load_local(symbol, freq, adjusted, start, end, as_of)

        if fallback == "local":
            out = local_df
        elif fallback == "yfinance":
            out = self._load_yfinance(symbol, freq, start, end)
        else:
            # 'auto': fill tail gap from yfinance if possible.
            yf_from = self._gap_start_for_yfinance(local_df, freq, end)
            if yf_from is None:
                out = local_df
            else:
                yf_end = pd.Timestamp(end) if end is not None else pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
                yf_df = self._load_yfinance(symbol, freq, start=yf_from, end=yf_end)
                if yf_df.empty:
                    out = local_df
                elif local_df.empty:
                    out = yf_df
                else:
                    combined = pd.concat([local_df, yf_df])
                    combined = combined[~combined.index.duplicated(keep="first")]
                    out = combined.sort_index()

        prov = self.get_provenance(symbol, freq)
        # Append yfinance span if auto fallback actually fetched
        if fallback != "local" and not out.empty:
            # heuristic: if tail came from yfinance (local didn't cover full
            # range and we fetched), add a yfinance row to provenance
            if fallback == "yfinance" or (fallback == "auto" and (
                local_df.empty or out.index.max() > local_df.index.max()
            )):
                prov = prov + [{
                    "symbol": _safe_symbol(symbol),
                    "freq": freq,
                    "source_type": "yfinance_fallback",
                    "rule_version": "yf_auto_adjust_false",
                    "first_bar_ts": out.index.max()
                        if local_df.empty or local_df.empty else local_df.index.max(),
                    "last_bar_ts": out.index.max(),
                }]
        try:
            out.attrs["provenance"] = prov
            out.attrs["symbol"] = _safe_symbol(symbol)
            out.attrs["freq"] = freq
        except Exception:
            pass
        return out

    # ── Provenance sidecar ────────────────────────────────────────────────────

    def get_provenance(self, symbol: str, freq: str) -> list[dict]:
        """Return list of provenance rows for (symbol, freq) from
        `data/ref/bar_provenance.parquet`. Each row: symbol, freq,
        source_type, rule_version, first_bar_ts, last_bar_ts, (maybe more).

        Returns empty list if sidecar missing or symbol not tracked.
        """
        sidecar = self.root / "ref" / "bar_provenance.parquet"
        if not sidecar.exists():
            return []
        try:
            df = pd.read_parquet(sidecar)
        except Exception:
            return []
        sym = _safe_symbol(symbol)
        sub = df[(df["symbol"] == sym) & (df["freq"] == freq)]
        if sub.empty:
            return []
        return sub.to_dict("records")

    def _load_local(self, symbol, freq, adjusted, start, end, as_of) -> pd.DataFrame:
        p = self._bar_path(symbol, freq)
        if not p.exists():
            return pd.DataFrame()
        df = pd.read_parquet(p)
        if "timestamp" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index(pd.DatetimeIndex(df["timestamp"], name="timestamp")).drop(columns=["timestamp"])
        df = df.sort_index()
        if start is not None:
            df = df.loc[df.index >= pd.Timestamp(start)]
        if end is not None:
            df = df.loc[df.index <= pd.Timestamp(end)]
        if adjusted and len(df) > 0:
            df = self._apply_forward_splits(df, symbol, as_of=as_of)
        return df

    def _gap_start_for_yfinance(
        self,
        local_df: pd.DataFrame,
        freq: str,
        end: Optional[str | pd.Timestamp],
    ) -> Optional[pd.Timestamp]:
        """Return yfinance fetch start if there's a tail gap that yfinance can fill, else None."""
        today = pd.Timestamp.today().normalize()
        target_end = pd.Timestamp(end) if end is not None else today
        yf_earliest = today - pd.Timedelta(days=_YF_MAX_DAYS[freq])
        if local_df.empty:
            return yf_earliest
        last_local = pd.Timestamp(local_df.index.max()).normalize()
        if last_local >= target_end:
            return None
        gap_start = last_local + pd.Timedelta(days=1)
        # yfinance can only serve >= yf_earliest
        return max(gap_start, yf_earliest)

    # ── yfinance fallback ────────────────────────────────────────────────────

    def _yf_cache_dir(self) -> Path:
        d = self.root / ".yf_cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _yf_cache_path(self, symbol: str, freq: str, start, end) -> Path:
        key = f"{symbol}|{freq}|{start}|{end}"
        h = hashlib.md5(key.encode()).hexdigest()[:12]
        return self._yf_cache_dir() / f"{_safe_symbol(symbol)}_{freq}_{h}.parquet"

    def _load_yfinance(self, symbol, freq, start, end) -> pd.DataFrame:
        """Fetch bars from yfinance with 1-day file cache. Returns SPLIT-ADJUSTED
        (yfinance auto_adjust=True gives split + div adj; we strip div adj back out
        is not possible, so for 'full' parity with our local split-only series,
        we use auto_adjust=False and take the OHLC columns which yfinance already
        split-adjusts internally — matching our local adjusted=True output)."""
        try:
            import yfinance as yf
        except ImportError:
            return pd.DataFrame()
        if freq not in _YF_INTERVAL:
            return pd.DataFrame()

        today = pd.Timestamp.today().normalize()
        start_ts = pd.Timestamp(start) if start else today - pd.Timedelta(days=_YF_MAX_DAYS[freq])
        end_ts = pd.Timestamp(end) if end else today + pd.Timedelta(days=1)
        # Clamp to yfinance coverage window
        earliest = today - pd.Timedelta(days=_YF_MAX_DAYS[freq])
        start_ts = max(start_ts, earliest)
        if start_ts >= end_ts:
            return pd.DataFrame()

        cache_path = self._yf_cache_path(symbol, freq, start_ts.date(), end_ts.date())
        if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < _YF_CACHE_TTL_SEC:
            return pd.read_parquet(cache_path)

        interval = _YF_INTERVAL[freq]
        try:
            raw = yf.download(
                symbol,
                start=str(start_ts.date()),
                end=str(end_ts.date()),
                interval=interval,
                auto_adjust=False,  # yfinance 'Close' is already split-adj (matches our adjusted=True)
                progress=False,
                threads=False,
            )
        except Exception:
            return pd.DataFrame()
        if raw is None or raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw.columns = [c.lower() for c in raw.columns]
        cols = [c for c in ("open", "high", "low", "close", "volume") if c in raw.columns]
        df = raw[cols].copy()
        # Normalize index: daily → date index (tz-naive); intraday → tz-naive ET
        if freq in ("daily", "1d"):
            df.index = pd.DatetimeIndex(df.index.date, name="date")
        else:
            if df.index.tz is not None:
                df.index = df.index.tz_convert("America/New_York").tz_localize(None)
            df.index.name = "timestamp"
        # Align dtypes with local parquet
        for c in ("open", "high", "low", "close"):
            if c in df:
                df[c] = df[c].astype("float32")
        if "volume" in df:
            df["volume"] = df["volume"].fillna(0).astype("int64")
        df["amount"] = np.nan  # yfinance doesn't expose dollar volume
        df.to_parquet(cache_path, compression="snappy")
        return df

    def list_symbols(self, freq: str = "1m") -> list[str]:
        d = self._freq_dir(freq)
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.parquet"))

    # ── adjustment math ──────────────────────────────────────────────────────

    def _apply_forward_splits(
        self,
        df: pd.DataFrame,
        symbol: str,
        as_of: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        splits = self._splits_for(symbol, as_of=as_of)
        if splits.empty:
            return df

        # For each bar timestamp t, factor = Π (from_i / to_i) over splits i with date_i > t.
        # Equivalently: sort splits desc by date; cumulatively build step-function factor(t).
        # Build piecewise constant factor series.
        splits_sorted = splits.sort_values("date").reset_index(drop=True)
        # factor on interval (-inf, s0.date]: Π_all = prod(from/to)
        # factor on (s_i.date, s_{i+1}.date]: Π remaining from i+1 onwards
        # factor on (s_last.date, +inf]: 1
        ratios = (splits_sorted["from"] / splits_sorted["to"]).astype("float64").values
        # cumulative factor FROM a given split index to the end
        # factor_at(t) where t ∈ (dates[i-1], dates[i]] → product of ratios[i:]
        # Build by scanning from right:
        suffix_prod = np.ones(len(ratios) + 1, dtype="float64")
        for i in range(len(ratios) - 1, -1, -1):
            suffix_prod[i] = suffix_prod[i + 1] * ratios[i]
        # suffix_prod[0] = full product; suffix_prod[N] = 1.0

        # For each bar timestamp, find index i = number of splits with date <= t
        # (searchsorted on dates, right-side gives count of dates <= t).
        # Note: if a split date is exactly t, convention: split takes effect that day's open.
        # Most splits are applied at market open of the ex-date, so bars AT that date
        # are already in new basis → factor for that date should be 1 for post-open bars.
        # For simplicity at 1m: treat date D splits as taking effect for bars with
        # t.normalize() >= D (post-split basis).
        #
        # We implement as: the bar at any time on the split date or later is POST-split.
        # i.e. for t >= D (any hour on D), the split at D has already happened → ratio excluded.
        # searchsorted with side='left' on dates array, matching t.normalize():
        idx_times = df.index.normalize().to_numpy(dtype="datetime64[ns]")
        split_dates = splits_sorted["date"].to_numpy(dtype="datetime64[ns]")
        # side='right': bar on split date → treated as post-split (factor excludes that split)
        i_arr = np.searchsorted(split_dates, idx_times, side="right")
        factors = suffix_prod[i_arr]

        df = df.copy()
        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df[col] = (df[col].astype("float64") * factors).astype("float32")
        if "volume" in df.columns:
            df["volume"] = (df["volume"].astype("float64") / factors).round().astype("int64")
        # amount (dollar volume) is invariant to splits
        return df


if __name__ == "__main__":
    # Quick smoke usage
    import sys
    store = BarStore()
    sym = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    freq = sys.argv[2] if len(sys.argv) > 2 else "1m"
    df = store.load(sym, freq)
    print(f"{sym} {freq}: {len(df)} bars, {df.index.min()} → {df.index.max()}")
    print(df.head(3))
    print(df.tail(3))
