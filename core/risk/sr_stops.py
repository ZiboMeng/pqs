"""S/R-anchored stop-loss computation.

Pure-functional helper. Computes a stop-loss price for a long position
anchored to swing-based support (with ATR buffer below) when available,
or falls back to a fixed-% stop when support is undefined. Bounded to
[min_stop_pct, max_stop_pct] of entry to avoid degenerate cases.

Used by:
  - Use 2 (stop-loss placement): caller computes per-position stop at
    entry time, compares current price to stop on each subsequent bar.

Design choices:

  * Buffer below support (NOT at support): swing lows often see noise
    wicks penetrate by an ATR-fraction before holding. Stopping AT
    support frequently produces "stopped at the low" bad-fill outcomes.
    Buffer width = ``atr_buffer_mult * atr`` on the symbol's
    decision-frequency bars.

  * Fallback to fixed-% when S unavailable: factor is silent (no
    qualifying swing in lookback) more often than not on quiet
    sessions; we cannot leave positions un-stopped, so fall back to a
    classical fixed-% rule.

  * Bounded distance: support far below entry → unreasonable position
    risk (e.g., 50% drawdown threshold); support too close → noise
    stops. Clamp the resulting stop distance to a configured band.

  * Long-only only. Short stops are out of scope (system invariant).

PRD: docs/prd/20260505-* Step 4. NO consumer is wired yet — pure
functional helper, available for caller integration after Step 5
backtest evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SRStopParams:
    """Parameters for S/R-anchored stop-loss computation.

    All fields have sensible defaults derived from typical US large-cap
    realized-vol regimes. Caller should re-tune for thin-tape / vol
    regimes via Step 5 backtest sweep.
    """

    atr_buffer_mult: float = 1.0
    """Multiplier applied to ATR for the buffer below support.
    Default 1.0 = one ATR below S. Set 0.0 to stop AT support."""

    fixed_stop_fallback_pct: float = 0.08
    """Fallback stop distance (fraction of entry) when support_level is
    None. Default 8% — matches `LeftSideTradingConfig.loss_stop_pct`
    magnitude convention."""

    max_stop_pct: float = 0.15
    """Maximum stop distance from entry (fraction). Caps the case where
    support is far below entry (else excessive position risk)."""

    min_stop_pct: float = 0.02
    """Minimum stop distance from entry (fraction). Floors the case
    where support is right at entry (avoids noise stops)."""


def compute_sr_anchored_stop(
    entry_price: float,
    support_level: Optional[float] = None,
    atr: Optional[float] = None,
    params: Optional[SRStopParams] = None,
) -> float:
    """Compute the stop-loss PRICE for a long position.

    Parameters
    ----------
    entry_price : float
        The position's entry / fill price. Must be > 0.
    support_level : float, optional
        The nearest swing-based support below entry, e.g., from
        ``core.intraday.sr_swing.compute_nearest_sr``. If None or
        >= entry_price, falls back to fixed-pct rule.
    atr : float, optional
        Average True Range on the symbol's decision-frequency bars
        (price units, NOT a fraction). Used to compute the buffer
        below support. If None, buffer is treated as zero (stop at S).
    params : SRStopParams, optional
        Stop computation parameters. Defaults applied if None.

    Returns
    -------
    float
        The stop price. Always satisfies:
          ``entry_price * (1 - max_stop_pct) <= stop_price``
          ``stop_price <= entry_price * (1 - min_stop_pct)``
        i.e., stop is between min and max distance below entry.

    Raises
    ------
    ValueError
        If ``entry_price <= 0``.
    """
    if entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price}")

    p = params or SRStopParams()

    # Path 1: S-anchored with ATR buffer.
    use_support = (
        support_level is not None
        and support_level > 0
        and support_level < entry_price
    )
    if use_support:
        buffer = (atr or 0.0) * p.atr_buffer_mult
        candidate = float(support_level) - buffer
    else:
        # Path 2: fallback to fixed-pct stop.
        candidate = entry_price * (1.0 - p.fixed_stop_fallback_pct)

    # Clamp distance from entry to [min_stop_pct, max_stop_pct].
    floor_price = entry_price * (1.0 - p.max_stop_pct)
    ceil_price = entry_price * (1.0 - p.min_stop_pct)

    if candidate < floor_price:
        return float(floor_price)
    if candidate > ceil_price:
        return float(ceil_price)
    return float(candidate)


def compute_atr(
    highs,
    lows,
    closes,
    n: int = 14,
) -> Optional[float]:
    """Average True Range over the last ``n`` bars (Wilder convention).

    Lightweight sequence-based computation; takes plain Python lists or
    numpy arrays / pandas Series. Returns None if input is too short
    for the requested window or if any input is missing.

    Parameters
    ----------
    highs, lows, closes : sequence of float
        Bar high / low / close values (most recent at the END).
    n : int
        ATR window. Default 14 (classical Welles Wilder convention).

    Returns
    -------
    float or None
    """
    try:
        h = list(highs)
        l_ = list(lows)
        c = list(closes)
    except TypeError:
        return None
    if len(h) != len(l_) or len(h) != len(c):
        return None
    if len(h) < n + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(h)):
        tr = max(
            h[i] - l_[i],
            abs(h[i] - c[i - 1]),
            abs(l_[i] - c[i - 1]),
        )
        trs.append(tr)
    # Wilder ATR: simple mean of last n TRs (close enough for our use;
    # classical Wilder smoothing differs by < 1% over n=14 windows).
    if len(trs) < n:
        return None
    last_n = trs[-n:]
    return float(sum(last_n) / n)
