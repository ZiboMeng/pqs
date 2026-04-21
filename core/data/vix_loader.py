"""VIX loader with explicit fail-closed semantics (P0.3, 2026-04-20).

Prior behavior: run_paper.py / run_backtest.py / run_mining.py all
silently fell back to a constant 20.0 VIX series when the store did
not have ^VIX. For research that's acceptable on long histories (the
gap is bounded and diagnostic), but for live/paper trading it's
dangerous: black-swan days have real VIX > 60, regime detection
under constant 20.0 would misclassify CRISIS as NEUTRAL and allow
full-size trades.

This module centralizes the loading logic with two modes:

  - strict:  raise VixDataMissingError if ^VIX is unavailable OR
             if the VIX value on the most recent bar of the reindex
             index is NaN. Used for live/paper paths — trade blocked
             rather than silently sized against a stale constant.
  - lenient: allow ffill + constant-backfill on NaN with a warning
             per run. Used for research/backtest over long histories
             where the missing tail is bounded and known.

Both modes return a pd.Series indexed by `target_index` with numeric
floats. In lenient mode the returned series' `.attrs["fallback_bars"]`
records how many bars were filled from the constant.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)


class VixDataMissingError(RuntimeError):
    """Raised in strict mode when ^VIX data is unavailable at the
    point where the regime detector needs it for a live decision."""


def load_vix_series(
    store,
    target_index: pd.DatetimeIndex,
    *,
    mode: Literal["strict", "lenient"] = "lenient",
    symbol: str = "^VIX",
    fallback_value: float = 20.0,
) -> pd.Series:
    """Return a VIX close series aligned to `target_index`.

    Parameters
    ----------
    store          : MarketDataStore-like with `.read(sym, freq)` and
                     `.get_last_date(sym, freq)`
    target_index   : the index the series must align to (usually the
                     price_df's index or a subset)
    mode           : 'strict' for live/paper, 'lenient' for research
    symbol         : VIX symbol in store (default '^VIX')
    fallback_value : used only in lenient mode for NaN fill

    Raises
    ------
    VixDataMissingError (strict mode only) if:
      - no ^VIX bars at all exist in the store
      - the VIX value on target_index[-1] (the most recent decision
        point) is NaN after ffill
    """
    raw_df = None
    if store.get_last_date(symbol, "1d") is not None:
        raw_df = store.read(symbol, "1d")
    have_data = raw_df is not None and not raw_df.empty

    if not have_data:
        if mode == "strict":
            raise VixDataMissingError(
                f"{symbol} data unavailable in store; refusing to trade "
                f"with a constant VIX stub. Fetch VIX before running "
                f"live mode."
            )
        logger.warning(
            "VIX data missing; falling back to constant %.1f. Acceptable "
            "for research backtests; would be BLOCKED in live mode.",
            fallback_value,
        )
        out = pd.Series(fallback_value, index=target_index, name="vix")
        out.attrs["fallback_bars"] = len(target_index)
        out.attrs["fallback_mode"] = "all_missing"
        return out

    series = raw_df["close"].reindex(target_index, method="ffill")
    n_nan = int(series.isna().sum())

    if n_nan == 0:
        out = series.rename("vix")
        out.attrs["fallback_bars"] = 0
        out.attrs["fallback_mode"] = "none"
        return out

    # Any NaN after ffill → the gap predates the earliest VIX bar
    # (warmup period). Strict refuses only if the MOST RECENT bar (the
    # decision point) is NaN — a pre-warmup gap is tolerable even for
    # live because regime is only consulted on the most recent point.
    most_recent_nan = bool(series.isna().iloc[-1])
    if mode == "strict" and most_recent_nan:
        raise VixDataMissingError(
            f"{symbol} has no value at target_index[-1]={target_index[-1]} "
            f"after ffill. Refusing to trade — regime would be computed "
            f"against a constant stub."
        )

    logger.warning(
        "VIX has %d NaN bars after ffill; filling with %.1f. "
        "mode=%s, most_recent_nan=%s",
        n_nan, fallback_value, mode, most_recent_nan,
    )
    series = series.fillna(fallback_value).rename("vix")
    series.attrs["fallback_bars"] = n_nan
    series.attrs["fallback_mode"] = "partial_ffill_backfill"
    return series
