"""PRD-2 P2.3 R12 — multi-TF cascade construction overlay.

Wires the (already-existing, leakage-safe, R10-gated) multi-TF
cascade decision primitive ``core.intraday.multi_timescale.
decide_timing`` into the CONSTRUCTION path as a timing / sizing /
veto overlay on the daily strategy's target weights.

Honest scope (R4/R6/R7 pattern; the 15m-decision-input revision is
ratified per docs/memos/20260519-15m_decision_input_boundary_
revision.md): this overlay is **timing/sizing/veto on EXISTING
daily weights only — NOT intraday alpha mining**. It never
generates a new signal/factor, never flips sign (long-only
preserved), and never amplifies above the daily base weight
(``decide_timing`` only scales magnitude in [0,1] or defers). The
default ``mode="off"`` (and any symbol without a multi-TF context)
is a pure identity — the **60m-only baseline, bit-identical** to
pre-overlay construction (parallels the P2.1 R2-b T0
``apply_tier_overlay`` no-op contract).
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from core.intraday.multi_timescale import (
    MultiTimescaleContext,
    decide_timing,
)

__all__ = ["apply_cascade_overlay"]

_VALID_MODES = ("off", "cascade")


def apply_cascade_overlay(
    daily_weights: pd.Series,
    ctx_by_symbol: Optional[Dict[str, MultiTimescaleContext]] = None,
    mode: str = "off",
) -> pd.Series:
    """Apply the multi-TF cascade as a timing/sizing/veto overlay.

    Parameters
    ----------
    daily_weights : the daily strategy's per-symbol target weights
        (long-only, ``>= 0``).
    ctx_by_symbol : optional {symbol → MultiTimescaleContext} (each
        built leakage-safe via ``build_context`` — R10 gate). A
        symbol absent here is passed through unchanged (= 60m-only
        baseline for that symbol).
    mode : ``"off"`` (default) → identity, the bit-identical
        60m-only baseline. ``"cascade"`` → scale/defer/veto each
        weight by ``decide_timing``'s ``effective_weight`` ∈
        ``[0, base_weight]``.

    Returns
    -------
    overlaid weights, same index. Always ``0 <= out[s] <=
    daily_weights[s]`` (long-only preserved; timing only reduces or
    defers, never flips, never amplifies).
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"mode={mode!r} invalid; expected one of {_VALID_MODES}")

    # 60m-only baseline: pure identity (bit-identical no-op).
    if mode == "off" or not ctx_by_symbol:
        return daily_weights.copy()

    out = daily_weights.copy()
    for sym, w in daily_weights.items():
        wf = float(w)
        ctx = ctx_by_symbol.get(sym)
        # long-only: non-positive weight untouched; no context for
        # this symbol → 60m-only pass-through (baseline).
        if ctx is None or wf <= 0.0:
            continue
        d = decide_timing(ctx, sym, base_weight=wf)
        # effective_weight = base*timing_scale if execute else 0,
        # timing_scale ∈ [0,1] → 0 <= eff <= wf (sizing/veto only).
        out[sym] = d.effective_weight
    return out
