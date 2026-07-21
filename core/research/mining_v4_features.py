"""Causal numeric features for the governed semantic/ML mining program."""

from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd


def _validate_panel(panel: Mapping[str, pd.DataFrame]) -> None:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(panel)
    if missing:
        raise ValueError(f"price panel lacks fields: {sorted(missing)}")
    close = panel["close"]
    if not isinstance(close.index, pd.DatetimeIndex):
        raise TypeError("price panel must use a DatetimeIndex")
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        raise ValueError("price panel index must be sorted and unique")
    for name in required - {"close"}:
        frame = panel[name]
        if not frame.index.equals(close.index) or not frame.columns.equals(close.columns):
            raise ValueError(f"panel[{name!r}] is not aligned with close")


def month_end_decision_dates(
    index: pd.DatetimeIndex,
    market_close: pd.Series,
) -> pd.DatetimeIndex:
    """Return the last available benchmark session in each calendar month."""

    if not index.equals(market_close.index):
        raise ValueError("market_close must align exactly with the panel index")
    available = index[market_close.notna().to_numpy()]
    if len(available) == 0:
        return pd.DatetimeIndex([])
    dates = pd.Series(available, index=available)
    return pd.DatetimeIndex(
        dates.groupby([available.year, available.month]).last().to_numpy())


def build_causal_numeric_features(
    panel: Mapping[str, pd.DataFrame],
    market_close: pd.Series,
) -> dict[str, pd.DataFrame]:
    """Build trailing-only stationary features known at decision close T."""

    _validate_panel(panel)
    close = panel["close"].astype(float)
    open_ = panel["open"].astype(float)
    high = panel["high"].astype(float)
    low = panel["low"].astype(float)
    volume = panel["volume"].astype(float)
    market = market_close.reindex(close.index).astype(float)
    returns = close.pct_change(fill_method=None)
    market_returns = market.pct_change(fill_method=None)
    dollar_volume = close * volume

    features: dict[str, pd.DataFrame] = {}
    for window in (5, 21, 63, 126, 252):
        features[f"mom_{window}"] = close.div(close.shift(window)) - 1.0
    for window in (21, 63, 126):
        features[f"rs_spy_{window}"] = features[f"mom_{window}"].sub(
            market.div(market.shift(window)).sub(1.0), axis=0)
    for window in (21, 63, 126):
        features[f"vol_{window}"] = returns.rolling(
            window, min_periods=window).std(ddof=1) * np.sqrt(252.0)
    downside = returns.clip(upper=0.0)
    features["downside_vol_63"] = downside.rolling(
        63, min_periods=63).std(ddof=1) * np.sqrt(252.0)
    features["return_skew_63"] = returns.rolling(
        63, min_periods=63).skew()

    for window in (63, 126, 252):
        rolling_high = close.rolling(window, min_periods=window).max()
        rolling_low = close.rolling(window, min_periods=window).min()
        width = rolling_high - rolling_low
        features[f"close_pos_{window}"] = (close - rolling_low).div(
            width.where(width > 0))
    features["drawdown_126"] = close.div(
        close.rolling(126, min_periods=126).max()) - 1.0

    path_length = returns.abs().rolling(63, min_periods=63).sum()
    features["trend_efficiency_63"] = features["mom_63"].div(
        path_length.where(path_length > 0))
    features["reversal_5"] = -features["mom_5"]

    market_var_63 = market_returns.rolling(63, min_periods=63).var()
    beta_63 = returns.rolling(63, min_periods=63).cov(market_returns).div(
        market_var_63, axis=0)
    features["beta_63"] = beta_63
    features["corr_spy_63"] = returns.rolling(
        63, min_periods=63).corr(market_returns)
    residual = returns.sub(beta_63.mul(market_returns, axis=0))
    features["idio_vol_63"] = residual.rolling(
        63, min_periods=63).std(ddof=1) * np.sqrt(252.0)

    volume_mean = volume.rolling(20, min_periods=20).mean()
    volume_std = volume.rolling(20, min_periods=20).std(ddof=1)
    features["volume_z_20"] = (volume - volume_mean).div(
        volume_std.where(volume_std > 0))
    dv20 = dollar_volume.rolling(20, min_periods=20).median()
    dv63 = dollar_volume.rolling(63, min_periods=63).median()
    features["dollar_volume_trend_20_63"] = dv20.div(dv63) - 1.0
    features["amihud_illiquidity_63"] = (
        returns.abs().div(dollar_volume.where(dollar_volume > 0))
        .rolling(63, min_periods=63).mean() * 1_000_000_000.0
    )

    previous_close = close.shift(1)
    features["overnight_gap_mean_5"] = (
        open_.div(previous_close).sub(1.0)
        .rolling(5, min_periods=5).mean()
    )
    features["intraday_return_mean_5"] = (
        close.div(open_.where(open_ > 0)).sub(1.0)
        .rolling(5, min_periods=5).mean()
    )
    true_range = pd.DataFrame(
        np.maximum.reduce([
            (high - low).to_numpy(),
            (high - previous_close).abs().to_numpy(),
            (low - previous_close).abs().to_numpy(),
        ]),
        index=close.index,
        columns=close.columns,
    )
    features["atr_ratio_21"] = true_range.rolling(
        21, min_periods=21).mean().div(close)

    return {
        name: frame.replace([np.inf, -np.inf], np.nan)
        for name, frame in sorted(features.items())
    }


__all__ = ["build_causal_numeric_features", "month_end_decision_dates"]
