"""PRD-X v2 Phase X3 — PartialRebalancePolicy (delta-to-trade).

True-new build phase: maps (current_weights, target_weights, ctx) →
list[ActionDecision] with precise ActionType routing via the
NoTradeBandCalculator gate. This is the "wire NoTradeBand into
rebalance delta" leg that R5e smoke surfaced as missing.

Routing matrix (PRD §6.3 4-action set + ActionType 9 routes):

  ┌──────────────────┬─────────────────────────────────────────┐
  │  state           │  ActionType                             │
  ├──────────────────┼─────────────────────────────────────────┤
  │ current=0, t>0   │  ENTER_PARTIAL if t<partial_threshold   │
  │                  │  ENTER_FULL    otherwise                │
  │ current>0, dt>0  │  ADD  if |dt|>add_band                  │
  │                  │  HOLD if |dt|≤add_band                  │
  │ current>0, dt<0  │  TRIM if |dt|>trim_band  and target>0   │
  │                  │  HOLD if |dt|≤trim_band                 │
  │ target=0,curr>0  │  EXIT                                   │
  │ current=0,t=0    │  NO_TRADE                               │
  └──────────────────┴─────────────────────────────────────────┘

bit-identical default (mode='off'): emits ENTER_FULL for each
non-zero target, no delta gating. Same R12/T0/sample_weight=None
precedent — legacy callers see exactly the target weight set with
no decision-layer rerouting.

§6.4 long-only invariant: target_weight<0 raises at ActionDecision
construction; EXIT routes to 0 only (never below).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from core.research.decision import (
    ActionDecision, ActionType, PositionState,
)
from core.research.decision.no_trade_band import (
    Bands, NoTradeBandCalculator,
)
from core.signals.signal_state import SignalStatus

__all__ = ["PartialRebalancePolicy"]


_VALID_MODES = ("off", "active")


class PartialRebalancePolicy:
    """Delta-to-trade rebalance kernel with NoTradeBand gating.

    Parameters
    ----------
    no_trade_band : NoTradeBandCalculator
        Required calculator that produces per-symbol Bands per ctx.
        (vol/regime-conditional widths per Leland 1999.)
    mode : 'off' (default, bit-identical) or 'active'
    partial_full_threshold : float
        Target-weight cutoff between ENTER_PARTIAL (target ≤
        threshold) and ENTER_FULL (target > threshold). Default
        0.05 (5%). Heuristic per §6.3 A3 (small targets are
        partial executions).
    """

    def __init__(
        self,
        no_trade_band: NoTradeBandCalculator,
        mode: str = "off",
        partial_full_threshold: float = 0.05,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"mode={mode!r} invalid; expected one of {_VALID_MODES}")
        if partial_full_threshold <= 0:
            raise ValueError(
                f"partial_full_threshold={partial_full_threshold} "
                f"must be > 0")
        self._band = no_trade_band
        self._mode = mode
        self._partial_th = float(partial_full_threshold)

    @property
    def mode(self) -> str:
        return self._mode

    # ── main API ────────────────────────────────────────────────────
    def compute_actions(
        self,
        target_weights: Dict[str, float],
        current_weights: Dict[str, float],
        ctx: Dict[str, Any],
    ) -> List[ActionDecision]:
        """Compute per-symbol ActionDecisions from (target, current)
        delta-to-trade and NoTradeBand gating.

        Args:
          target_weights: desired post-rebalance {symbol: weight}
          current_weights: pre-rebalance {symbol: weight}
          ctx: must include 'date' (pd.Timestamp); may include
                'regime' (RegimeState), 'realized_vol' (float).
                Per-symbol band widths computed via no_trade_band.

        Returns:
          List of ActionDecision (one per symbol that appears in
          either target or current).
        """
        if ctx is None:
            ctx = {}
        date = ctx.get("date", pd.Timestamp.now())
        symbols = set(target_weights.keys()) | set(current_weights.keys())
        out: List[ActionDecision] = []
        # mode='off' bit-identical: emit ENTER_FULL for each non-zero
        # target, ignore current. Legacy callers' weights pass through
        # 1:1 (R12/T0/sample_weight=None precedent).
        if self._mode == "off":
            for sym in sorted(target_weights.keys()):
                tw = float(target_weights[sym])
                if tw < 0:
                    raise ValueError(
                        f"target_weight={tw} < 0 for {sym} — "
                        f"long-only invariant (PRD §6.4)")
                action = (ActionType.ENTER_FULL if tw > 0
                          else ActionType.NO_TRADE)
                out.append(ActionDecision(
                    symbol=sym, date=date,
                    status=SignalStatus.CONFIRMED,
                    action=action,
                    position_state=PositionState.HOLD
                        if tw > 0 else PositionState.FLAT,
                    target_weight=tw,
                    reason="mode=off pass-through"))
            return out

        # active mode: per-symbol delta-to-trade + band gating
        for sym in sorted(symbols):
            tw = float(target_weights.get(sym, 0.0))
            cw = float(current_weights.get(sym, 0.0))
            if tw < 0:
                raise ValueError(
                    f"target_weight={tw} < 0 for {sym} — "
                    f"long-only invariant (PRD §6.4)")
            if cw < 0:
                # current weights also long-only (no-short invariant)
                raise ValueError(
                    f"current_weight={cw} < 0 for {sym} — "
                    f"long-only invariant (PRD §6.4)")
            delta = tw - cw
            bands = self._band.compute(sym, ctx)

            # Route to ActionType
            action, final_weight, reason = self._route(
                sym, tw, cw, delta, bands)
            pstate = (PositionState.FLAT
                      if final_weight == 0 and action in (
                          ActionType.NO_TRADE, ActionType.EXIT)
                      else PositionState.HOLD)
            out.append(ActionDecision(
                symbol=sym, date=date,
                status=SignalStatus.CONFIRMED,
                action=action, position_state=pstate,
                target_weight=final_weight, reason=reason))
        return out

    # ── routing logic ───────────────────────────────────────────────
    def _route(
        self, sym: str, target: float, current: float, delta: float,
        bands: Bands,
    ):
        """Returns (ActionType, final_weight, reason) per the
        routing matrix in the module docstring."""
        # case 1: both zero → NO_TRADE
        if target == 0.0 and current == 0.0:
            return (ActionType.NO_TRADE, 0.0,
                    "target=0, current=0")
        # case 2: target=0 + current>0 → EXIT (band-gated)
        if target == 0.0 and current > 0.0:
            if abs(delta) > bands.exit:
                return (ActionType.EXIT, 0.0,
                        f"target=0, |delta|={abs(delta):.4f} > "
                        f"exit_band={bands.exit:.4f}")
            # |delta| within exit_band → HOLD (don't churn out)
            return (ActionType.HOLD, current,
                    f"target=0, |delta|={abs(delta):.4f} ≤ "
                    f"exit_band={bands.exit:.4f} → HOLD")
        # case 3: current=0 + target>0 → ENTER_FULL or ENTER_PARTIAL
        if current == 0.0 and target > 0.0:
            if abs(delta) <= bands.enter:
                # delta below entry band → still NO_TRADE
                return (ActionType.NO_TRADE, 0.0,
                        f"target={target:.4f} ≤ enter_band="
                        f"{bands.enter:.4f}")
            if target <= self._partial_th:
                return (ActionType.ENTER_PARTIAL, target,
                        f"target={target:.4f} ≤ partial_threshold="
                        f"{self._partial_th:.4f} → ENTER_PARTIAL")
            return (ActionType.ENTER_FULL, target,
                    f"target={target:.4f} > partial_threshold="
                    f"{self._partial_th:.4f} → ENTER_FULL")
        # case 4: current>0 + target>0 → ADD / TRIM / HOLD
        if delta > 0:
            if delta > bands.add:
                return (ActionType.ADD, target,
                        f"current>0, delta={delta:.4f} > "
                        f"add_band={bands.add:.4f} → ADD")
            return (ActionType.HOLD, current,
                    f"current>0, delta={delta:.4f} ≤ add_band="
                    f"{bands.add:.4f} → HOLD")
        if delta < 0:
            if abs(delta) > bands.trim:
                return (ActionType.TRIM, target,
                        f"current>0, |delta|={abs(delta):.4f} > "
                        f"trim_band={bands.trim:.4f} → TRIM")
            return (ActionType.HOLD, current,
                    f"current>0, |delta|={abs(delta):.4f} ≤ "
                    f"trim_band={bands.trim:.4f} → HOLD")
        # delta == 0 exactly
        return (ActionType.HOLD, current,
                "target==current → HOLD")
