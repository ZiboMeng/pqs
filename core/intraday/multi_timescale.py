"""
Multi-timescale data contract and timing layer.

Role (formalized 约束 3, 2026-04-20):
  This module is NOT a standalone alpha system. Validation (iter #9/#10/
  #11, 2026-04-20 sprint) showed the naive bar-direction voting approach
  produces strictly lower Sharpe than a 60m-only baseline AND fails cost
  tests at even 0.1× base cost. The multi-timescale framework is
  repositioned here as a TIMING / EXECUTION / RISK layer on top of the
  daily MFS, never as a direction authority.

Timeframe roles (formal contract):
  60m / 30m  → CONTEXT: regime hint, direction check (consistent with
                daily MFS?), macro confirmation. These may VETO a daily
                target (force flat if their context strongly contradicts).
  15m / 5m   → TRIGGER: entry/exit timing, order splitting, risk flags.
                NEVER initiate a new direction against higher-TF context.
                May DEFER / SPLIT a trade, not change its direction.

Conflict resolution:
  - 60m conflict with daily target → soft veto (scale timing weight down
    toward 0, subject to min_timing_scale floor)
  - 30m conflict with 60m            → confidence penalty on timing_scale
  - 15m/5m conflict with 60m         → defer (execute=False for this bar,
                                       retry next bar) or reduce size
  - No TF (all absent)               → pass-through, execute as-is

Confirmation / Veto / Neutral semantics:
  - CONFIRM    : TF direction aligns with higher-level intent → full scale
  - CONTRADICT : TF direction opposes higher-level intent → scale down or veto
  - NEUTRAL    : TF is flat OR absent → no contribution (pass-through)

Entry points:
  - decide_timing(ctx, base_weight) → TimingDecision  [canonical]
  - evaluate_cross_tf_signal(...)   → CrossTFSignal   [legacy shim, kept
                                                      for back-compat]

Data contract (unchanged):
  - MultiTimescaleContext: holds aligned bars across 60m/30m/15m/5m
  - build_context(): returns latest COMPLETED bar ≤ decision_time per TF
  - Only closed/completed bars participate in decisions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

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
    """Output of multi-timescale signal evaluation.

    Per-TF attribution fields (populated by evaluate_cross_tf_signal):
    - base_strength: strength contributed by 60m alone
    - mult_30m / mult_15m: multiplicative contribution from 30m / 15m
      (1.0 when the TF is absent or fully aligned)
    - confirm_30m / confirm_15m: True = TF agrees with 60m, False = TF
      contradicts 60m, None = TF absent or neutral
    """
    symbol: str
    decision_time: pd.Timestamp
    direction: int          # +1 long, -1 short (unused in long-only), 0 no trade
    strength: float         # 0.0 to 1.0
    higher_tf_dir: int      # 60m direction
    confirming_tf_dir: int  # 30m direction
    vetoed: bool            # True if cross-TF conflict → no trade
    reason: str             # human-readable explanation
    base_strength: float = 0.0
    mult_30m: float = 1.0
    mult_15m: float = 1.0
    confirm_30m: Optional[bool] = None
    confirm_15m: Optional[bool] = None


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
        base_strength = 1.0
    elif dir_60 == 0:
        base_strength = 0.8
    else:
        base_strength = 0.5

    strength = base_strength

    # 30m confirmation (soft — reduces but does not veto)
    mult_30m = 1.0
    confirm_30m: Optional[bool] = None
    if dir_30 is not None:
        if dir_30 == -1 and dir_60 == 1:
            mult_30m = 0.4
            confirm_30m = False
        elif dir_30 == 1:
            mult_30m = 1.0
            confirm_30m = True if dir_60 == 1 else (False if dir_60 == -1 else None)
        elif dir_30 == 0:
            mult_30m = 0.7
            confirm_30m = None  # neutral — neither confirm nor contradict
        strength *= mult_30m

    # 15m fine-tuning (prototype — does not veto, only adjusts)
    mult_15m = 1.0
    confirm_15m: Optional[bool] = None
    if dir_15 is not None:
        if dir_15 == 1:
            new_strength = min(strength * 1.1, 1.0)
            mult_15m = new_strength / strength if strength > 1e-12 else 1.0
            strength = new_strength
            confirm_15m = (dir_60 == 1)
        elif dir_15 == -1:
            mult_15m = 0.6
            strength *= mult_15m
            confirm_15m = False
        else:
            confirm_15m = None  # neutral

    direction = 1 if strength > 0.1 else 0

    return CrossTFSignal(
        symbol=symbol, decision_time=ctx.decision_time,
        direction=direction, strength=round(strength, 3),
        higher_tf_dir=dir_60, confirming_tf_dir=dir_30 or 0,
        vetoed=False, reason="signal_generated",
        base_strength=round(base_strength, 3),
        mult_30m=round(mult_30m, 3),
        mult_15m=round(mult_15m, 3),
        confirm_30m=confirm_30m,
        confirm_15m=confirm_15m,
    )


# ── Timing contracts (约束 3: multi-TF as timing/execution layer) ────────────
#
# `TimingDecision` is the canonical output when using multi-TF on top of
# a daily strategy. It takes the daily base_weight and returns the
# execution-side timing adjustment. The direction is ALWAYS preserved
# from the daily strategy's intent — multi-TF never flips direction,
# only scales magnitude or defers execution.


@dataclass
class TimingDecision:
    """Canonical output of multi-TF timing evaluation.

    The daily MFS already decided that `symbol` should be held with
    `base_weight > 0` today. This decision answers: AT THIS BAR, do we
    execute toward that target at full size, reduced size, or defer
    until later?

    Fields
    ------
    symbol          : symbol being timed
    decision_time   : decision bar close time (tz-naive ET)
    base_weight     : daily strategy's target weight for this symbol
                      (unchanged by multi-TF; echoed here for caller
                      convenience)
    timing_scale    : ∈ [0.0, 1.0]. Multiplier applied to base_weight
                      for THIS bar. 0.0 = defer/veto, 1.0 = full target.
    execute         : bool. True = route orders this bar. False = hold
                      off (e.g. lower TF adverse, defer to next bar).
                      A False here does NOT flip the position — it only
                      pauses timing adjustments on this bar.
    higher_tf_vote  : dict {freq → "confirm" / "contradict" / "neutral"}
                      used by reports to attribute timing value per TF.
    reason          : short tag (e.g. "confirmed_bullish",
                      "30m_soft_contradict", "no_higher_context")
    """
    symbol:         str
    decision_time:  pd.Timestamp
    base_weight:    float
    timing_scale:   float
    execute:        bool
    higher_tf_vote: Dict[str, str] = field(default_factory=dict)
    reason:         str = ""

    @property
    def effective_weight(self) -> float:
        """base_weight × timing_scale if execute else 0."""
        return (self.base_weight * self.timing_scale) if self.execute else 0.0


@dataclass
class TimingThresholds:
    """Timing-layer thresholds. Mirrors
    `core.config.schemas.risk.IntradayTimingConfig` so decide_timing can
    be called from tests without loading the full Config tree.

    Defaults match the original hardcoded constants (pre-P1 closure) so
    callers that don't pass thresholds see no behavior change.
    """
    min_timing_scale:          float = 0.0
    execute_threshold:         float = 0.15
    scale_when_60m_contradict: float = 0.5
    scale_when_60m_neutral:    float = 0.8
    mult_30m_contradict:       float = 0.5
    mult_30m_neutral:          float = 0.8

    # ── S/R-aware timing modifier (PRD 20260505 Step 3, opt-in) ─────
    enable_sr_timing:              bool = False
    sr_near_resistance_pct:        float = 0.005
    sr_scale_when_near_resistance: float = 0.5
    sr_swing_n:                    int = 5
    sr_lookback_bars:              int = 20

    @classmethod
    def from_config(cls, cfg) -> "TimingThresholds":
        """Build from a `RiskConfig.intraday_timing` pydantic object."""
        return cls(
            min_timing_scale          = cfg.min_timing_scale,
            execute_threshold         = cfg.execute_threshold,
            scale_when_60m_contradict = cfg.scale_when_60m_contradict,
            scale_when_60m_neutral    = cfg.scale_when_60m_neutral,
            mult_30m_contradict       = cfg.mult_30m_contradict,
            mult_30m_neutral          = cfg.mult_30m_neutral,
            # PRD 20260505 Step 3 — fields default-False on legacy yaml
            # without these keys (lazy migration via pydantic defaults).
            enable_sr_timing              = getattr(cfg, "enable_sr_timing", False),
            sr_near_resistance_pct        = getattr(cfg, "sr_near_resistance_pct", 0.005),
            sr_scale_when_near_resistance = getattr(cfg, "sr_scale_when_near_resistance", 0.5),
            sr_swing_n                    = getattr(cfg, "sr_swing_n", 5),
            sr_lookback_bars              = getattr(cfg, "sr_lookback_bars", 20),
        )


@dataclass(frozen=True)
class SRLevels:
    """Per-frequency S/R reference snapshot at a decision time.

    Computed by ``compute_sr_levels_at`` from a symbol's bar history.
    Passed to ``decide_timing(..., sr_levels={"60m": SRLevels(...)})``
    when ``TimingThresholds.enable_sr_timing`` is True.

    PRD: docs/prd/20260505-* Step 3.
    """
    freq:          str
    decision_time: pd.Timestamp
    current_close: float
    resistance:    Optional[float] = None
    support:       Optional[float] = None


def compute_sr_levels_at(
    bars_df: pd.DataFrame,
    as_of: pd.Timestamp,
    freq: str,
    n: int = 5,
    lookback: int = 20,
) -> Optional[SRLevels]:
    """Compute swing-based S/R levels from `bars_df` history truncated
    at ``as_of`` (inclusive — must be a completed bar).

    Returns ``None`` when:
      - ``bars_df`` is None / empty
      - History up to ``as_of`` has fewer than 2n+1 bars (insufficient
        for swing detection)
      - The latest bar's close is NaN

    Otherwise returns an ``SRLevels`` snapshot for the latest bar at-or-
    before ``as_of``. ``resistance`` / ``support`` may individually be
    None when no qualifying swing is found in the lookback window.
    """
    if bars_df is None or bars_df.empty:
        return None
    valid = bars_df[bars_df.index <= as_of]
    if len(valid) < 2 * n + 1:
        return None
    if pd.isna(valid["close"].iloc[-1]):
        return None
    # Localized import: avoids module-load cycle on package init.
    from core.intraday.sr_swing import compute_nearest_sr
    sr = compute_nearest_sr(valid, n=n, lookback=lookback)
    last = sr.iloc[-1]
    return SRLevels(
        freq=freq,
        decision_time=valid.index[-1],
        current_close=float(valid["close"].iloc[-1]),
        resistance=(
            float(last["resistance"])
            if pd.notna(last["resistance"]) else None
        ),
        support=(
            float(last["support"])
            if pd.notna(last["support"]) else None
        ),
    )


_DEFAULT_THRESHOLDS = TimingThresholds()


def decide_timing(
    ctx:          MultiTimescaleContext,
    symbol:       str,
    base_weight:  float,
    daily_side:   int = 1,
    thresholds:   Optional[TimingThresholds] = None,
    sr_levels:    Optional[Dict[str, SRLevels]] = None,
) -> TimingDecision:
    """Canonical multi-TF timing API.

    Given the daily strategy's (side, base_weight) for one symbol,
    compute the bar-level timing adjustment using the contract:

      - 60m context provides the primary direction check
      - 30m confirms / reduces confidence
      - 15m / 5m are TRIGGERS only — may defer but cannot flip direction

    Parameters
    ----------
    ctx         : MultiTimescaleContext at this bar
    symbol      : symbol being timed
    base_weight : daily target weight (must be ≥ 0 under long-only)
    daily_side  : +1 (long) — retained for future short support; -1
                  currently rejected with execute=False since system is
                  long-only.
    thresholds  : TimingThresholds instance (defaults match legacy
                  hardcoded constants). Pass
                  `TimingThresholds.from_config(cfg.risk.intraday_timing)`
                  in production to enable config-driven tuning.
    sr_levels   : Optional ``{freq: SRLevels}`` — when provided AND
                  ``thresholds.enable_sr_timing=True``, the 60m entry
                  triggers an S/R-aware scale-down when current close
                  is hugging resistance. Long-only safety: only scales
                  DOWN, never UP. Default None → S/R logic skipped.
                  PRD 20260505 Step 3.
    """
    th = thresholds or _DEFAULT_THRESHOLDS

    if daily_side != 1:
        return TimingDecision(
            symbol=symbol, decision_time=ctx.decision_time,
            base_weight=base_weight, timing_scale=0.0, execute=False,
            reason="short_not_supported",
        )
    if base_weight <= 0:
        return TimingDecision(
            symbol=symbol, decision_time=ctx.decision_time,
            base_weight=base_weight, timing_scale=0.0, execute=False,
            reason="zero_base_weight",
        )

    dir_60 = ctx.get_direction("60m")
    dir_30 = ctx.get_direction("30m")
    dir_15 = ctx.get_direction("15m") if ctx.has("15m") else None
    dir_5  = ctx.get_direction("5m") if ctx.has("5m") else None

    votes: Dict[str, str] = {}

    # Baseline: no higher context → pass through (decision deferred to
    # daily strategy; timing adds nothing).
    if dir_60 is None:
        return TimingDecision(
            symbol=symbol, decision_time=ctx.decision_time,
            base_weight=base_weight, timing_scale=1.0, execute=True,
            higher_tf_vote={}, reason="no_higher_context_passthrough",
        )

    # 60m vote (primary context)
    if dir_60 == 1:
        votes["60m"] = "confirm"
        scale = 1.0
    elif dir_60 == -1:
        # 60m strongly disagrees with long daily target — soft veto
        votes["60m"] = "contradict"
        scale = max(th.scale_when_60m_contradict, th.min_timing_scale)
    else:  # dir_60 == 0
        votes["60m"] = "neutral"
        scale = th.scale_when_60m_neutral

    # 30m vote (secondary confirmation)
    if dir_30 is None:
        votes["30m"] = "absent"
    elif dir_30 == 1:
        votes["30m"] = "confirm"
    elif dir_30 == -1:
        votes["30m"] = "contradict"
        scale *= th.mult_30m_contradict
    else:
        votes["30m"] = "neutral"
        scale *= th.mult_30m_neutral

    # ── S/R-aware modifier (PRD 20260505 Step 3, opt-in) ─────────────
    # Applied AFTER 30m vote and BEFORE 15m/5m defer triggers, so a
    # near-resistance scale-down composes multiplicatively with prior
    # 60m + 30m scaling but does not interact with the 15m/5m execute
    # gate. Long-only safety: only scales DOWN.
    if (
        th.enable_sr_timing
        and sr_levels is not None
        and "60m" in sr_levels
    ):
        sr_60 = sr_levels["60m"]
        if (sr_60.resistance is not None
                and sr_60.current_close > 0
                and sr_60.resistance > sr_60.current_close):
            gap_frac = (
                (sr_60.resistance - sr_60.current_close)
                / sr_60.current_close
            )
            if gap_frac <= th.sr_near_resistance_pct:
                scale *= th.sr_scale_when_near_resistance
                votes["sr_60m"] = "near_resistance"

    # 15m trigger — defers but cannot flip.
    execute = True
    if dir_15 is not None:
        if dir_15 == -1:
            votes["15m"] = "contradict"
            # Defer THIS bar (execute=False); do not change timing_scale
            execute = False
        elif dir_15 == 1:
            votes["15m"] = "confirm"
        else:
            votes["15m"] = "neutral"

    # 5m trigger — finest defer granularity.
    if dir_5 is not None:
        if dir_5 == -1:
            votes["5m"] = "contradict"
            execute = False
        elif dir_5 == 1:
            votes["5m"] = "confirm"
        else:
            votes["5m"] = "neutral"

    # Final gate: if timing_scale is below execute threshold, defer
    if scale < th.execute_threshold:
        execute = False

    reason = (
        "confirmed" if scale >= 0.95 and execute
        else "soft_contradict" if scale < 0.95 and execute
        else "deferred"
    )

    return TimingDecision(
        symbol=symbol, decision_time=ctx.decision_time,
        base_weight=base_weight,
        timing_scale=round(scale, 3),
        execute=execute,
        higher_tf_vote=votes,
        reason=reason,
    )


def make_timing_target_provider(
    multi_bars:        Dict[str, Dict[str, pd.DataFrame]],
    daily_base_weights: Dict[str, float],
    thresholds:        Optional[TimingThresholds] = None,
) -> Callable[[pd.Timestamp, Dict[str, float], float], Dict[str, float]]:
    """Build a `target_wts_fn` closure suitable for
    `IntradayBacktestEngine.run_multi_day` / `PaperTradingEngine.
    run_day_intraday`.

    At each bar, the returned closure:
      1. Builds a multi-TF context for every symbol with a base weight
      2. Calls decide_timing to get per-symbol TimingDecision
      3. Returns {symbol: effective_weight} dict — ready as a target

    Symbols whose timing.execute is False are OMITTED from the returned
    dict (caller interprets missing symbols as "no new orders, hold
    current position"). Symbols with execute=True but effective_weight
    < base are included at the reduced level.
    """
    th = thresholds or _DEFAULT_THRESHOLDS

    def _build_sr_levels(sym: str, bar_ts: pd.Timestamp) -> Optional[Dict[str, SRLevels]]:
        """Compute per-freq S/R levels for a symbol at decision time.

        Returns None when feature disabled or no S/R-eligible bars
        available — decide_timing then skips the modifier.
        """
        if not th.enable_sr_timing:
            return None
        sr_per_freq: Dict[str, SRLevels] = {}
        # Currently we only consume 60m S/R inside decide_timing; if
        # 30m/15m are added in a future PRD round, expand this loop.
        for freq in ("60m",):
            sym_bars = (multi_bars.get(freq) or {}).get(sym)
            sr = compute_sr_levels_at(
                sym_bars, bar_ts, freq=freq,
                n=th.sr_swing_n,
                lookback=th.sr_lookback_bars,
            )
            if sr is not None:
                sr_per_freq[freq] = sr
        return sr_per_freq if sr_per_freq else None

    def _provider(
        bar_ts:    pd.Timestamp,
        positions: Dict[str, float],
        cash:      float,
    ) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for sym, bw in daily_base_weights.items():
            if bw <= 0:
                continue
            ctx = build_context(multi_bars, sym, bar_ts)
            sr_lvls = _build_sr_levels(sym, bar_ts)
            decision = decide_timing(
                ctx, sym, base_weight=float(bw),
                daily_side=1, thresholds=th,
                sr_levels=sr_lvls,
            )
            if decision.execute:
                out[sym] = decision.effective_weight
        return out

    return _provider


# ── Attribution aggregator ───────────────────────────────────────────────────

@dataclass
class AttributionSummary:
    """Aggregated per-TF contribution counts over a backtest run.

    Fields
    ------
    n_signals          : total CrossTFSignal records collected
    n_vetoed           : vetoed (no-60m-context) count
    n_active           : not-vetoed count = n_signals - n_vetoed
    confirm_30m        : (n_confirm, n_contradict, n_neutral_or_absent) triple
    confirm_15m        : same for 15m
    avg_base_strength  : mean of base_strength across active signals
    avg_mult_30m       : mean mult_30m across active signals
    avg_mult_15m       : mean mult_15m across active signals
    avg_final_strength : mean strength across active signals
    """
    n_signals: int = 0
    n_vetoed: int = 0
    confirm_30m_counts: Dict[str, int] = field(default_factory=lambda:
        {"confirm": 0, "contradict": 0, "neutral_or_absent": 0})
    confirm_15m_counts: Dict[str, int] = field(default_factory=lambda:
        {"confirm": 0, "contradict": 0, "neutral_or_absent": 0})
    avg_base_strength: float = 0.0
    avg_mult_30m: float = 1.0
    avg_mult_15m: float = 1.0
    avg_final_strength: float = 0.0

    @property
    def n_active(self) -> int:
        return self.n_signals - self.n_vetoed


class AttributionAggregator:
    """Collect CrossTFSignal records and produce a per-TF summary.

    Usage:
        agg = AttributionAggregator()
        for date in dates:
            for sym in targets:
                sig = evaluate_cross_tf_signal(ctx, sym)
                agg.add(sig)
        summary = agg.summary()
        print(agg.format_report())
    """

    def __init__(self) -> None:
        self._sigs: List[CrossTFSignal] = []

    def add(self, sig: CrossTFSignal) -> None:
        self._sigs.append(sig)

    def summary(self) -> AttributionSummary:
        s = AttributionSummary(n_signals=len(self._sigs))
        if not self._sigs:
            return s

        s.n_vetoed = sum(1 for x in self._sigs if x.vetoed)
        active = [x for x in self._sigs if not x.vetoed]

        def _bucket(x: Optional[bool]) -> str:
            if x is True:
                return "confirm"
            if x is False:
                return "contradict"
            return "neutral_or_absent"

        for x in active:
            s.confirm_30m_counts[_bucket(x.confirm_30m)] += 1
            s.confirm_15m_counts[_bucket(x.confirm_15m)] += 1

        if active:
            s.avg_base_strength = float(np.mean([x.base_strength for x in active]))
            s.avg_mult_30m = float(np.mean([x.mult_30m for x in active]))
            s.avg_mult_15m = float(np.mean([x.mult_15m for x in active]))
            s.avg_final_strength = float(np.mean([x.strength for x in active]))
        return s

    def format_report(self) -> str:
        s = self.summary()
        if s.n_signals == 0:
            return "AttributionAggregator: no signals collected"

        lines = []
        lines.append("=== Multi-TF Attribution Report ===")
        lines.append(f"Signals: {s.n_signals}  Vetoed: {s.n_vetoed}  "
                     f"Active: {s.n_active}")
        lines.append("")
        lines.append(f"{'TF':<6} {'Confirm':>8} {'Contradict':>11} "
                     f"{'Neutral':>9} {'AvgMult':>9}")

        def _row(name: str, c: Dict[str, int], mult: float) -> str:
            return (f"{name:<6} {c['confirm']:>8d} {c['contradict']:>11d} "
                    f"{c['neutral_or_absent']:>9d} {mult:>9.3f}")

        lines.append(_row("30m", s.confirm_30m_counts, s.avg_mult_30m))
        lines.append(_row("15m", s.confirm_15m_counts, s.avg_mult_15m))
        lines.append("")
        lines.append(f"Avg base (60m): {s.avg_base_strength:.3f}")
        lines.append(f"Avg final    : {s.avg_final_strength:.3f}")
        return "\n".join(lines)


# ── Timing aggregator (约束 3 / P1 闭环) ─────────────────────────────────────
#
# TimingDecision-flavored analogue of AttributionAggregator. Produces
# the timing-role metrics requested by CLAUDE.md: execute rate, defer
# rate, avg timing_scale, per-TF confirm/contradict/neutral counts.


@dataclass
class TimingSummary:
    """Aggregated counts over a series of TimingDecision records."""
    n_decisions:    int = 0
    n_executed:     int = 0
    n_deferred:     int = 0
    avg_scale:      float = 0.0
    avg_eff_weight: float = 0.0
    # per-TF vote counts, across ALL decisions (executed + deferred)
    votes_60m: Dict[str, int] = field(default_factory=lambda:
        {"confirm": 0, "contradict": 0, "neutral": 0, "absent": 0})
    votes_30m: Dict[str, int] = field(default_factory=lambda:
        {"confirm": 0, "contradict": 0, "neutral": 0, "absent": 0})
    votes_15m: Dict[str, int] = field(default_factory=lambda:
        {"confirm": 0, "contradict": 0, "neutral": 0, "absent": 0})
    votes_5m: Dict[str, int] = field(default_factory=lambda:
        {"confirm": 0, "contradict": 0, "neutral": 0, "absent": 0})
    reasons: Dict[str, int] = field(default_factory=dict)

    @property
    def execute_rate(self) -> float:
        if self.n_decisions == 0:
            return 0.0
        return self.n_executed / self.n_decisions

    @property
    def defer_rate(self) -> float:
        if self.n_decisions == 0:
            return 0.0
        return self.n_deferred / self.n_decisions


class TimingAggregator:
    """Collect TimingDecision records and emit a summary.

    Replaces AttributionAggregator for scripts migrated to decide_timing.
    AttributionAggregator is kept for legacy callers still using
    evaluate_cross_tf_signal.

    Usage:
        tagg = TimingAggregator()
        for bar_ts in bars:
            for sym, bw in base.items():
                d = decide_timing(build_context(...), sym, bw)
                tagg.add(d)
        print(tagg.format_report())
    """

    _VOTE_BUCKETS = ("confirm", "contradict", "neutral", "absent")

    def __init__(self) -> None:
        self._decisions: List[TimingDecision] = []

    def add(self, decision: TimingDecision) -> None:
        self._decisions.append(decision)

    def summary(self) -> TimingSummary:
        s = TimingSummary(n_decisions=len(self._decisions))
        if not self._decisions:
            return s

        s.n_executed = sum(1 for d in self._decisions if d.execute)
        s.n_deferred = s.n_decisions - s.n_executed

        scales = [d.timing_scale for d in self._decisions]
        effs = [d.effective_weight for d in self._decisions]
        s.avg_scale = float(np.mean(scales)) if scales else 0.0
        s.avg_eff_weight = float(np.mean(effs)) if effs else 0.0

        for d in self._decisions:
            for freq, bucket_map in (
                ("60m", s.votes_60m), ("30m", s.votes_30m),
                ("15m", s.votes_15m), ("5m", s.votes_5m),
            ):
                v = d.higher_tf_vote.get(freq, "absent")
                if v in self._VOTE_BUCKETS:
                    bucket_map[v] += 1
                else:
                    bucket_map["absent"] += 1
            s.reasons[d.reason] = s.reasons.get(d.reason, 0) + 1
        return s

    def format_report(self) -> str:
        s = self.summary()
        if s.n_decisions == 0:
            return "TimingAggregator: no decisions collected"

        lines = []
        lines.append("=== Multi-TF Timing Report ===")
        lines.append(f"Decisions: {s.n_decisions}  "
                     f"Executed: {s.n_executed} ({s.execute_rate:.1%})  "
                     f"Deferred: {s.n_deferred} ({s.defer_rate:.1%})")
        lines.append(f"Avg timing_scale : {s.avg_scale:.3f}")
        lines.append(f"Avg effective_wt : {s.avg_eff_weight:.4f}")
        lines.append("")
        lines.append(f"{'TF':<5} {'Confirm':>8} {'Contradict':>11} "
                     f"{'Neutral':>9} {'Absent':>8}")
        for freq, bm in (("60m", s.votes_60m), ("30m", s.votes_30m),
                         ("15m", s.votes_15m), ("5m",  s.votes_5m)):
            lines.append(f"{freq:<5} {bm['confirm']:>8d} {bm['contradict']:>11d} "
                         f"{bm['neutral']:>9d} {bm['absent']:>8d}")
        lines.append("")
        lines.append("Reasons: " + ", ".join(
            f"{k}={v}" for k, v in sorted(
                s.reasons.items(), key=lambda kv: -kv[1])))
        return "\n".join(lines)
