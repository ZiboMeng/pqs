"""
Multi-timescale data contract and signal alignment.

Provides:
- MultiTimescaleContext: holds aligned bars across 60m/30m/15m/5m
- align_timescales(): aligns bar data from multiple timeframes
- get_higher_tf_context(): extracts latest completed higher-TF bar for a given timestamp

Architecture (Phase D):
  60m = trend direction, regime context (formal validation)
  30m = structure confirmation, risk state (formal validation)
  15m = execution confirmation, signal strength (prototype — 60d data limit)
  5m  = precise entry/exit/stop timing (prototype — 60d data limit)

Rules:
  - Higher TF has VETO power over lower TF
  - Only CLOSED bars generate signals
  - No using incomplete higher-TF bars to guide lower-TF trades
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.logging_setup import get_logger

logger = get_logger(__name__)

# Bar close times (minutes from midnight ET) for each timeframe
_BAR_MINUTES = {"60m": 60, "30m": 30, "15m": 15, "5m": 5}


@dataclass
class TimescaleBar:
    """A single bar from one timeframe."""
    timestamp: pd.Timestamp
    freq: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_complete: bool = True


@dataclass
class MultiTimescaleContext:
    """
    Aligned context across timeframes at a given decision point.

    At any decision timestamp, this holds the latest COMPLETED bar
    from each available timeframe.
    """
    decision_time: pd.Timestamp
    bars: Dict[str, TimescaleBar] = field(default_factory=dict)

    def has(self, freq: str) -> bool:
        return freq in self.bars

    def get_close(self, freq: str) -> Optional[float]:
        b = self.bars.get(freq)
        return b.close if b else None

    def get_direction(self, freq: str) -> Optional[int]:
        """Simple direction: +1 if close > open, -1 if close < open, 0 if flat."""
        b = self.bars.get(freq)
        if b is None:
            return None
        if b.close > b.open * 1.001:
            return 1
        elif b.close < b.open * 0.999:
            return -1
        return 0

    def get_range_ratio(self, freq: str) -> Optional[float]:
        """Bar range as fraction of open price. Higher = more conviction."""
        b = self.bars.get(freq)
        if b is None or b.open < 1e-10:
            return None
        return (b.high - b.low) / b.open

    def get_bar_return(self, freq: str) -> Optional[float]:
        """Bar return: (close - open) / open."""
        b = self.bars.get(freq)
        if b is None or b.open < 1e-10:
            return None
        return (b.close - b.open) / b.open

    @property
    def available_freqs(self) -> List[str]:
        return list(self.bars.keys())


def load_multi_timescale_bars(
    store,
    symbols: List[str],
    freqs: List[str] = None,
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Load intraday bars: {freq → {symbol → DataFrame}}.

    Returns only timeframes with data available.
    """
    freqs = freqs or ["60m", "30m", "15m"]
    result: Dict[str, Dict[str, pd.DataFrame]] = {}

    for freq in freqs:
        sym_data = {}
        for sym in symbols:
            try:
                df = store.read(sym, freq)
                if df is not None and not df.empty:
                    sym_data[sym] = df
            except Exception:
                pass
        if sym_data:
            result[freq] = sym_data
            logger.info("Loaded %s: %d symbols", freq, len(sym_data))

    return result


def get_latest_completed_bar(
    bars_df: pd.DataFrame,
    as_of: pd.Timestamp,
) -> Optional[TimescaleBar]:
    """
    Get the latest COMPLETED bar at or before `as_of`.

    A bar is complete if its close timestamp <= as_of.
    """
    if bars_df is None or bars_df.empty:
        return None

    valid = bars_df[bars_df.index <= as_of]
    if valid.empty:
        return None

    last = valid.iloc[-1]
    return TimescaleBar(
        timestamp=valid.index[-1],
        freq="",  # caller sets this
        open=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        close=float(last["close"]),
        volume=float(last.get("volume", 0)),
        is_complete=True,
    )


def build_context(
    multi_bars: Dict[str, Dict[str, pd.DataFrame]],
    symbol: str,
    decision_time: pd.Timestamp,
) -> MultiTimescaleContext:
    """
    Build a MultiTimescaleContext for a symbol at a given time.

    For each available timeframe, finds the latest completed bar — i.e. the
    last bar whose **close timestamp** is <= decision_time. With the
    right-labeled aggregate convention (see aggregate_bars.py, 2026-04-20)
    `index` == bar close time, so `index <= decision_time` is the correct
    predicate.

    Defensive invariant (asserted before return): every bar in the returned
    context satisfies `bar.timestamp <= decision_time`. Any violation =
    lookahead bug.
    """
    ctx = MultiTimescaleContext(decision_time=decision_time)

    for freq, sym_data in multi_bars.items():
        if symbol not in sym_data:
            continue
        bar = get_latest_completed_bar(sym_data[symbol], decision_time)
        if bar:
            bar.freq = freq
            # Hard invariant: no bar with close time > decision_time.
            assert bar.timestamp <= decision_time, (
                f"lookahead violation in build_context({symbol}, "
                f"decision={decision_time}): {freq} bar close "
                f"{bar.timestamp} > decision_time"
            )
            ctx.bars[freq] = bar

    return ctx


def check_higher_tf_alignment(ctx: MultiTimescaleContext) -> Dict[str, bool]:
    """
    Check if higher timeframes agree on direction.

    Returns {freq: agrees_with_60m} for each available freq.
    """
    dir_60 = ctx.get_direction("60m")
    if dir_60 is None:
        return {}

    result = {}
    for freq in ["30m", "15m", "5m"]:
        d = ctx.get_direction(freq)
        if d is not None:
            result[freq] = (d == dir_60) or (d == 0)

    return result


# ── Signal Evaluation ────────────────────────────────────────────────────────

@dataclass
class CrossTFSignal:
    """Output of multi-timescale signal evaluation."""
    symbol: str
    decision_time: pd.Timestamp
    direction: int          # +1 long, -1 short (unused in long-only), 0 no trade
    strength: float         # 0.0 to 1.0
    higher_tf_dir: int      # 60m direction
    confirming_tf_dir: int  # 30m direction
    vetoed: bool            # True if cross-TF conflict → no trade
    reason: str             # human-readable explanation


def evaluate_cross_tf_signal(
    ctx: MultiTimescaleContext,
    symbol: str,
    base_weight: float = 0.0,
) -> CrossTFSignal:
    """
    Evaluate a multi-timescale signal for one symbol.

    Protocol:
      1. 60m provides trend direction (required)
      2. 30m confirms or vetoes (required for full strength)
      3. 15m adjusts strength (optional, prototype)
      4. If 60m and 30m conflict → veto (no trade)
      5. If 60m neutral → reduced strength
      6. Long-only: only +1 direction allowed

    Parameters
    ----------
    ctx         : MultiTimescaleContext at decision time
    symbol      : symbol being evaluated
    base_weight : strategy-level target weight (from daily MFS)
    """
    dir_60 = ctx.get_direction("60m")
    dir_30 = ctx.get_direction("30m")
    dir_15 = ctx.get_direction("15m") if ctx.has("15m") else None

    # No 60m context → cannot trade
    if dir_60 is None:
        return CrossTFSignal(symbol=symbol, decision_time=ctx.decision_time,
                             direction=0, strength=0.0, higher_tf_dir=0,
                             confirming_tf_dir=0, vetoed=True,
                             reason="no_60m_context")

    # C-mode: daily strategy decides direction, intraday adjusts sizing.
    # Note: per-bar IC is negative for direction (mean-reversion at bar level),
    # but momentum-based sizing works better at daily granularity because
    # trend-aligned sizing reduces whipsaw. (Validated iter 9: MR signal → -2.8% CAGR)
    if dir_60 == 1:
        strength = 1.0
    elif dir_60 == 0:
        strength = 0.8
    else:
        strength = 0.5

    # 30m confirmation (soft — reduces but does not veto)
    if dir_30 is not None:
        if dir_30 == -1 and dir_60 == 1:
            strength *= 0.4
        elif dir_30 == 1:
            strength *= 1.0
        elif dir_30 == 0:
            strength *= 0.7

    # 15m fine-tuning (prototype — does not veto, only adjusts)
    if dir_15 is not None:
        if dir_15 == 1:
            strength = min(strength * 1.1, 1.0)
        elif dir_15 == -1:
            strength *= 0.6

    direction = 1 if strength > 0.1 else 0

    return CrossTFSignal(
        symbol=symbol, decision_time=ctx.decision_time,
        direction=direction, strength=round(strength, 3),
        higher_tf_dir=dir_60, confirming_tf_dir=dir_30 or 0,
        vetoed=False, reason="signal_generated",
    )
