"""S/R-aware signal defer filter — productionized for forward runner.

Implements Path A from PRD 20260505 §S/R alpha-first plan: zeros out
target_wts cells where T-day's RTH-close 60m bar is hugging swing-based
resistance. Preserves T+1 open execution semantics throughout — the
filter operates ENTIRELY on target_wts before any execution engine sees
the signal.

Used by:
  - core.research.forward.runner.observe (when spec.execution_policy.
    filters.sr_defer.enabled is True)
  - dev/scripts/sr_validation/run_sr_backtest.py (Step 5b harness)

Design choices:
  * RTH-only: pre-market (< 09:30 ET) and post-market (>= 16:00 ET) bars
    are EXCLUDED before swing detection AND before "last bar of day"
    extraction. Step 5b v1 used the unfiltered last bar (often a 20:00
    or 21:00 post-market bar with thin liquidity) → noise-amplified
    SR signal. This module fixes that.
  * Per-symbol pre-compute: ``compute_nearest_sr`` runs ONCE per symbol
    on the full RTH 60m series; per-cell lookup is then O(1). Naive
    per-cell call to ``compute_sr_levels_at`` was O(L*lookback) ×
    O(cells) — the multi-billion-op trap that killed the first run at
    11min mark.
  * end-date truncation: 60m bars are trimmed to <= ``end`` BEFORE
    SR computation, so the filter cannot peek into the sealed window
    (CLAUDE.md discipline).
  * Asymmetric: only resistance-side ``defer`` (skip new entry).
    Support side is NOT used in v1 — long-only safety + symmetric
    defer at S would block re-entries near support which is the
    OPPOSITE of what we want.
  * Long-only: assumes positive target weights = long position.
    Short positions out of scope (system invariant).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Optional

import numpy as np
import pandas as pd

from core.intraday.sr_swing import compute_nearest_sr


@dataclass(frozen=True)
class SRDeferConfig:
    """Configuration for ``apply_sr_defer_filter``."""

    swing_n: int = 5
    """Half-width of swing-detection window (passed to compute_nearest_sr)."""

    lookback_bars: int = 20
    """Number of prior 60m RTH bars scanned for nearest swing high."""

    near_resistance_pct: float = 0.005
    """Trigger threshold: defer fires when (R - close)/close ≤ this.
    Default 0.5% (50 bps). Tighter = fewer defers; looser = more."""

    rth_start_time: time = field(default_factory=lambda: time(9, 30))
    """Inclusive lower bound for RTH bars (ET, naive)."""

    rth_end_time: time = field(default_factory=lambda: time(16, 0))
    """Exclusive upper bound for RTH bars. With start-of-bar timestamp
    convention, the 15:30 bar (covering 15:30–16:30 hour) is the last
    RTH-aligned bar; 16:00 onwards is post-market. We use ``< 16:00``
    so 15:30 included, 16:00+ excluded."""


@dataclass(frozen=True)
class SRDeferStats:
    """Diagnostics returned alongside the filtered target_wts."""

    n_defers: int
    """Number of (date, sym) cells zeroed out by the filter."""

    n_evaluated: int
    """Number of cells where we COULD evaluate (positive target weight,
    sym has 60m coverage, T-day has at least one RTH bar). The
    activation rate = n_defers / n_evaluated."""

    n_skipped_no_60m_coverage: int
    """Cells with positive target weight but symbol has no 60m bars
    in the input. Filter passes through unchanged."""

    n_skipped_short_history: int
    """Cells where T-day exists in 60m data but the cumulative RTH
    history before/at T-day is shorter than ``2*swing_n + 1`` bars
    (insufficient for swing detection). Filter passes through unchanged."""

    n_skipped_no_rth_bars_today: int
    """Cells where the symbol has 60m bars somewhere but no RTH bars
    on T-day specifically (e.g., suspended trading). Pass through."""


def _filter_rth(
    bars: pd.DataFrame,
    rth_start: time,
    rth_end: time,
) -> pd.DataFrame:
    """Restrict 60m bars to RTH window [rth_start, rth_end) by time-of-day.

    Pure-functional; returns a new DataFrame view. Index timestamps must
    be naive (interpreted as ET per project convention) — tz-aware
    indices would need an explicit tz_convert before this call.
    """
    if bars is None or bars.empty:
        return bars
    times = bars.index.time
    mask = (times >= rth_start) & (times < rth_end)
    return bars[mask]


def apply_sr_defer_filter(
    target_wts: pd.DataFrame,
    intraday_bars_60m: dict,
    config: Optional[SRDeferConfig] = None,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> tuple[pd.DataFrame, SRDeferStats]:
    """Zero out target_wts cells where T-day's RTH-close 60m bar is
    hugging swing-based resistance.

    Parameters
    ----------
    target_wts : pd.DataFrame
        Daily target weights, index=date, columns=symbols, values ∈ [0, 1].
    intraday_bars_60m : dict[str, pd.DataFrame]
        ``{symbol: 60m OHLCV DataFrame}``. Each DataFrame must have a
        DatetimeIndex (tz-naive, ET) and ``'close'`` column. Index will
        be defensively sorted before processing.
    config : SRDeferConfig, optional
        Filter parameters. Defaults applied if None.
    start, end : pd.Timestamp, optional
        Restrict the filter loop to dates in [start, end] (inclusive on
        both ends). 60m data outside this range is also trimmed BEFORE
        SR computation to enforce the sealed-window discipline (no peek
        into ``end + 1`` bars).

    Returns
    -------
    (modified_target_wts, stats)
        ``modified_target_wts`` is a copy of ``target_wts`` with selected
        cells zeroed. ``stats`` reports activation counts.

    Notes
    -----
    Filter is symmetric in failure: any condition that prevents
    evaluation (no 60m, short history, no RTH bars today, NaN close)
    causes the cell to be PRESERVED unchanged. The filter never
    introduces NaN.
    """
    cfg = config or SRDeferConfig()

    out = target_wts.copy()
    n_defers = 0
    n_evaluated = 0
    n_skipped_no_60m = 0
    n_skipped_short = 0
    n_skipped_no_rth = 0

    # Pre-compute per-symbol: RTH-filtered bars + sorted index +
    # nearest_sr DataFrame + last-RTH-bar-by-date map.
    sym_sr_cache: dict[str, pd.DataFrame] = {}
    sym_close_cache: dict[str, pd.Series] = {}
    sym_last_rth_bar: dict[str, dict] = {}

    for sym, sym_60 in (intraday_bars_60m or {}).items():
        if sym_60 is None or sym_60.empty:
            continue
        # Defensive: sort by index (data IS sorted today but cheap insurance).
        if not sym_60.index.is_monotonic_increasing:
            sym_60 = sym_60.sort_index()
        # End-date truncation BEFORE RTH filter — keep the cheaper op last
        if end is not None:
            sym_60 = sym_60[sym_60.index <= end]
            if sym_60.empty:
                continue
        # RTH-only: drop pre-market (<09:30) and post-market (>=16:00) bars.
        sym_60_rth = _filter_rth(sym_60, cfg.rth_start_time, cfg.rth_end_time)
        if sym_60_rth.empty:
            continue
        # SR computation on RTH-only series. Short-history skip is at
        # cell evaluation time (per-cell history depends on T_date).
        sr_full = compute_nearest_sr(
            sym_60_rth,
            n=cfg.swing_n,
            lookback=cfg.lookback_bars,
        )
        sym_sr_cache[sym] = sr_full
        sym_close_cache[sym] = sym_60_rth["close"]
        last_idx_by_date: dict = {}
        for ts in sym_60_rth.index:
            last_idx_by_date[ts.date()] = ts
        sym_last_rth_bar[sym] = last_idx_by_date

    for date in target_wts.index:
        if start is not None and date < start:
            continue
        if end is not None and date > end:
            continue
        row = target_wts.loc[date]
        for sym, w in row.items():
            if w <= 0:
                continue
            if sym not in sym_sr_cache:
                n_skipped_no_60m += 1
                continue
            last_rth_ts = sym_last_rth_bar[sym].get(date.date())
            if last_rth_ts is None:
                n_skipped_no_rth += 1
                continue
            # Short-history check: how many RTH bars exist <= last_rth_ts?
            sr_at_ts = sym_sr_cache[sym]
            if last_rth_ts not in sr_at_ts.index:
                n_skipped_short += 1
                continue
            n_evaluated += 1
            R = sr_at_ts.at[last_rth_ts, "resistance"]
            if pd.isna(R):
                continue
            close = sym_close_cache[sym].at[last_rth_ts]
            if pd.isna(close) or close <= 0:
                continue
            close_f = float(close)
            R_f = float(R)
            if R_f <= close_f:
                continue
            gap_frac = (R_f - close_f) / close_f
            if 0 < gap_frac <= cfg.near_resistance_pct:
                out.at[date, sym] = 0.0
                n_defers += 1

    stats = SRDeferStats(
        n_defers=n_defers,
        n_evaluated=n_evaluated,
        n_skipped_no_60m_coverage=n_skipped_no_60m,
        n_skipped_short_history=n_skipped_short,
        n_skipped_no_rth_bars_today=n_skipped_no_rth,
    )
    return out, stats
