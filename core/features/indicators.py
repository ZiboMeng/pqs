"""
Technical indicator library for PQS.

Conventions:
- All functions accept pd.Series / pd.DataFrame with lowercase OHLCV columns.
- All return pd.Series (or tuples of pd.Series) aligned to the input index.
- No side-effects; no global state.
- ATR uses true range (high/low/prev_close), not close-only approximation.
- VWAP resets daily (groups by index.date).

Indicators provided
-------------------
Price / Trend
    ema(series, span) → Series
    sma(series, window) → Series
    macd(close, fast, slow, signal) → (macd, signal, hist)
    bollinger_bands(close, window, num_std) → (upper, lower, width_pct)

Momentum
    rsi(series, period) → Series
    rolling_return(series, window) → Series
    momentum_score(close, windows) → DataFrame

Volatility
    true_range(high, low, close) → Series
    atr(high, low, close, period) → Series
    atr_pct(high, low, close, period) → Series   # ATR / close
    hist_vol(close, window, annualization) → Series

Volume
    vwap(close, volume) → Series                 # daily-resetting
    volume_surge(volume, window) → Series        # vol / rolling_mean(vol)

Composite
    compute_daily_features(df) → DataFrame       # full daily feature set
    compute_intraday_features(df) → DataFrame    # full intraday feature set
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd


# ── Price / Trend ─────────────────────────────────────────────────────────────

def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window).mean()


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD indicator.

    Returns:
        (macd_line, signal_line, histogram)
    """
    macd_line   = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Returns:
        (upper, lower, width_pct)   where width_pct = (upper-lower)/middle
    """
    middle = close.rolling(window).mean()
    std    = close.rolling(window).std()
    upper  = middle + std * num_std
    lower  = middle - std * num_std
    width  = (upper - lower) / middle.replace(0, np.nan)
    return upper, lower, width


# ── Momentum ──────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder RSI (exponential smoothing, alpha = 1/period).
    Returns values in [0, 100].
    """
    delta    = series.diff()
    gain     = delta.clip(lower=0.0)
    loss     = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0.0, np.nan)
    result   = 100.0 - (100.0 / (1.0 + rs))
    # When avg_loss == 0 and avg_gain > 0: infinite RS → RSI = 100
    # When avg_loss == 0 and avg_gain == 0: no movement → RSI = 50
    no_loss = avg_loss == 0.0
    result   = result.where(~no_loss, other=np.where(avg_gain > 0, 100.0, 50.0))
    return result


def rolling_return(series: pd.Series, window: int) -> pd.Series:
    """Percentage return over a rolling window."""
    return series.pct_change(window)


def momentum_score(
    close: pd.Series,
    windows: List[int] = (20, 60, 120, 252),
) -> pd.DataFrame:
    """
    Multi-window momentum: percentage returns for each window.
    Returns a DataFrame with columns ret_{w}.
    """
    df = pd.DataFrame(index=close.index)
    for w in windows:
        df[f"ret_{w}"] = rolling_return(close, w)
    return df


# ── Volatility ────────────────────────────────────────────────────────────────

def true_range(
    high:  pd.Series,
    low:   pd.Series,
    close: pd.Series,
) -> pd.Series:
    """
    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    First bar uses high-low (no prev_close available).
    """
    prev_close = close.shift(1)
    hl  = high - low
    hpc = (high - prev_close).abs()
    lpc = (low  - prev_close).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return tr


def atr(
    high:   pd.Series,
    low:    pd.Series,
    close:  pd.Series,
    period: int = 14,
) -> pd.Series:
    """
    Average True Range (Wilder smoothing).
    Uses true range (high/low/prev_close), not close-only approximation.
    """
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def atr_pct(
    high:   pd.Series,
    low:    pd.Series,
    close:  pd.Series,
    period: int = 14,
) -> pd.Series:
    """ATR as a percentage of close price (normalised volatility)."""
    return atr(high, low, close, period) / close.replace(0.0, np.nan)


def hist_vol(
    close:          pd.Series,
    window:         int = 20,
    annualization:  int = 252,
) -> pd.Series:
    """Annualised historical volatility from log returns."""
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window).std() * np.sqrt(annualization)


# ── Volume ────────────────────────────────────────────────────────────────────

def vwap(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    Volume-weighted average price, reset daily.

    Requires a DatetimeIndex.  Returns NaN if index is not datetime.
    """
    if not isinstance(close.index, pd.DatetimeIndex):
        return pd.Series(np.nan, index=close.index, name="vwap")

    dates  = close.index.date
    pv     = close * volume
    cum_pv = pv.groupby(dates).cumsum()
    cum_v  = volume.groupby(dates).cumsum().replace(0.0, np.nan)
    result = cum_pv / cum_v
    result.name = "vwap"
    return result


def volume_surge(volume: pd.Series, window: int = 20) -> pd.Series:
    """
    Volume relative to its rolling mean: volume / SMA(volume, window).
    Values > 1 indicate above-average activity.
    """
    mean_vol = volume.rolling(window).mean().replace(0.0, np.nan)
    return volume / mean_vol


# ── Composite feature sets ────────────────────────────────────────────────────

def compute_daily_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the full daily feature set from an OHLCV DataFrame.

    Expected columns: open, high, low, close, volume
    Returns a new DataFrame with all features (no OHLCV columns included).
    """
    close  = df["close"]
    volume = df["volume"]
    high   = df["high"]
    low    = df["low"]

    out = pd.DataFrame(index=df.index)

    # Trend
    for span in (20, 50, 100, 200):
        out[f"ema{span}"] = ema(close, span)
    out["ema20_slope"] = out["ema20"].pct_change(5)   # 5-bar slope proxy

    # MACD
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(close)

    # Bollinger Bands
    out["bb_upper"], out["bb_lower"], out["bb_width"] = bollinger_bands(close)
    out["bb_pct"] = (close - out["bb_lower"]) / (
        (out["bb_upper"] - out["bb_lower"]).replace(0.0, np.nan)
    )

    # Momentum
    for w in (5, 20, 60, 120, 252):
        out[f"ret_{w}d"] = rolling_return(close, w)

    # RSI
    out["rsi14"] = rsi(close, 14)
    out["rsi28"] = rsi(close, 28)

    # Volatility
    out["atr14"]     = atr(high, low, close, 14)
    out["atr_pct14"] = atr_pct(high, low, close, 14)
    out["hv20"]      = hist_vol(close, 20)
    out["hv60"]      = hist_vol(close, 60)

    # Volume
    out["vol_avg20"]      = sma(volume, 20)
    out["volume_surge20"] = volume_surge(volume, 20)

    # Cross-sectional-style features (price vs own history)
    out["close_zscore20"] = (
        (close - sma(close, 20)) / close.rolling(20).std().replace(0.0, np.nan)
    )
    out["high_52w"]  = close.rolling(252).max()
    out["pct_from_52w_high"] = (close / out["high_52w"].replace(0.0, np.nan)) - 1.0

    return out


def compute_intraday_features(
    df:            pd.DataFrame,
    freq:          str = "60m",
    daily_df:      pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Compute the full intraday feature set from an OHLCV DataFrame.

    Args:
        df:       Intraday OHLCV DataFrame; index must be DatetimeIndex (ET tz-naive).
        freq:     Bar frequency string ('5m', '15m', '30m', '60m') — used to label
                  features and choose lookback windows.
        daily_df: Optional daily OHLCV DataFrame for cross-timeframe features
                  (e.g. daily ATR, daily RSI).  Pass None to skip.

    Returns:
        New DataFrame with all intraday features.
    """
    close  = df["close"]
    volume = df["volume"]
    high   = df["high"]
    low    = df["low"]

    out = pd.DataFrame(index=df.index)

    # Intraday trend EMAs (bar counts)
    for span in (9, 21, 55):
        out[f"ema{span}"] = ema(close, span)

    # MACD (standard periods work on bar count)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(close, 12, 26, 9)

    # RSI
    out["rsi14"] = rsi(close, 14)

    # ATR (true range based)
    out["atr14"]     = atr(high, low, close, 14)
    out["atr_pct14"] = atr_pct(high, low, close, 14)

    # VWAP (daily-resetting)
    out["vwap"]      = vwap(close, volume)
    out["vwap_dist"] = (close / out["vwap"].replace(0.0, np.nan)) - 1.0

    # Volume
    out["vol_avg20"]      = sma(volume, 20)
    out["volume_surge20"] = volume_surge(volume, 20)

    # Bollinger Bands
    out["bb_upper"], out["bb_lower"], out["bb_width"] = bollinger_bands(close, 20)
    out["bb_pct"] = (close - out["bb_lower"]) / (
        (out["bb_upper"] - out["bb_lower"]).replace(0.0, np.nan)
    )

    # ── Time-of-day features (requires DatetimeIndex) ──────────────────────────
    if isinstance(df.index, pd.DatetimeIndex):
        minutes_from_midnight = df.index.hour * 60 + df.index.minute
        open_min  = 9 * 60 + 30   # 570
        close_min = 16 * 60        # 960

        out["minutes_from_open"] = minutes_from_midnight - open_min
        out["minutes_to_close"]  = close_min - minutes_from_midnight

        # Session flags
        out["is_first_30m"] = (
            (out["minutes_from_open"] >= 0) & (out["minutes_from_open"] < 30)
        ).astype(np.int8)
        out["is_last_30m"] = (
            (out["minutes_to_close"] > 0) & (out["minutes_to_close"] <= 30)
        ).astype(np.int8)
        out["is_midday"] = (
            (out["minutes_from_open"] >= 120) & (out["minutes_to_close"] >= 120)
        ).astype(np.int8)

        # Intraday momentum (bars from session open on this day)
        first_close_of_day = close.groupby(df.index.date).transform("first")
        out["intraday_ret"] = (close / first_close_of_day.replace(0.0, np.nan)) - 1.0

    # ── Cross-timeframe: daily anchor features ──────────────────────────────────
    if daily_df is not None and not daily_df.empty:
        out = _merge_daily_anchors(out, daily_df, df.index)

    return out


def _merge_daily_anchors(
    intraday_out: pd.DataFrame,
    daily_df:     pd.DataFrame,
    intraday_idx: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Merge daily features into intraday by forward-filling on date.

    Aligns on date (strips time component from intraday index).
    Uses previous day's value so there is no look-ahead (today's daily
    bar is not available until after market close).
    """
    daily_feats = pd.DataFrame(index=daily_df.index)
    d_close = daily_df["close"]
    d_high  = daily_df["high"]
    d_low   = daily_df["low"]

    daily_feats["d_rsi14"]     = rsi(d_close, 14)
    daily_feats["d_atr_pct14"] = atr_pct(d_high, d_low, d_close, 14)
    daily_feats["d_hv20"]      = hist_vol(d_close, 20)
    daily_feats["d_ema50"]     = ema(d_close, 50)
    daily_feats["d_ema200"]    = ema(d_close, 200)
    daily_feats["d_trend"]     = (daily_feats["d_ema50"] > daily_feats["d_ema200"]).astype(np.int8)

    # Use previous day's values to avoid look-ahead
    daily_feats = daily_feats.shift(1)

    # Reindex to intraday by date (forward-fill)
    dates_idx = pd.DatetimeIndex(intraday_idx.date)
    daily_feats.index = pd.DatetimeIndex(daily_feats.index)
    aligned = daily_feats.reindex(dates_idx, method="ffill")
    aligned.index = intraday_idx

    return pd.concat([intraday_out, aligned], axis=1)
