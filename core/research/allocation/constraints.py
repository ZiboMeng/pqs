"""P3/S4 — portfolio constraint enforcement (PRD 20260521 §4.8;
supplement 20260522 S4).

Audit finding D1: `config/ml_allocation.yaml` declared a `turnover_cap_
daily` (and other controls) that no code path enforced. This module is
the enforcing code for the turnover cap — a config-declared control is
no longer hollow.

`apply_turnover_cap` throttles each bar's turnover to the cap by
PARTIAL rebalancing: when the target weights require more turnover than
the cap allows, the book moves only `cap / turnover` of the way toward
the target, carrying the remainder into the next bar. This is the
standard turnover-budget / partial-rebalance mechanism.
"""
from __future__ import annotations

import pandas as pd

__all__ = ["apply_turnover_cap"]


def apply_turnover_cap(
    weights: pd.DataFrame,
    turnover_cap: float,
    *,
    throttle_initial_entry: bool = False,
) -> pd.DataFrame:
    """Throttle per-bar turnover to ``turnover_cap``.

    Args:
        weights: (date × symbol) target weight panel.
        turnover_cap: max per-bar turnover = sum |w_t - w_{t-1}|.
        throttle_initial_entry: if False (default) the first bar is the
            full initial entry (the cap governs ONGOING rebalancing, not
            the one-time book establishment); if True bar 0 is also
            throttled from an implicit all-cash book.

    Returns the realized weight panel. When a target needs more turnover
    than the cap, only `cap / turnover` of the move is taken; the book
    converges toward the target over subsequent bars.
    """
    if weights.empty or turnover_cap <= 0:
        return weights
    cols = list(weights.columns)
    rows: list[pd.Series] = []
    if throttle_initial_entry:
        held = pd.Series(0.0, index=cols)
        start = 0
    else:
        held = weights.iloc[0].fillna(0.0)
        rows.append(held)
        start = 1
    for i in range(start, len(weights)):
        target = weights.iloc[i].fillna(0.0)
        delta = target - held
        turnover = float(delta.abs().sum())
        if turnover > turnover_cap:
            held = held + delta * (turnover_cap / turnover)
        else:
            held = target
        rows.append(held)
    return pd.DataFrame(rows, index=weights.index, columns=cols)
