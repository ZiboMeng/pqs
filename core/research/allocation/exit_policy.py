"""P3/S4 — exit policy enforcement (PRD 20260521 §4.9; supplement
20260522 S4).

Master §4.9: "rebalance every N days is NOT a complete exit policy."
`config/ml_allocation.yaml::exit_policy` declares five exit classes;
this module implements the two that are **contemporaneous and
non-whipsaw**:

  - signal_decay : exit a held name once its cross-sectional rank
                   decays below a threshold (the model's own current
                   view — not a lagging statistic, so it does not
                   whipsaw the way the trailing-edge min-edge proxy did,
                   S4 R12).
  - turnover_band: a no-trade band — skip per-name weight changes
                   smaller than the band, cutting churn.

The other three classes' status (honest, S4):
  - time_based   : auto-satisfied — a 21-day rebalance cadence fully
                   reconsiders every name each period, so a 21-day
                   max-holding never binds. (enforcement_status note.)
  - risk_off     : a drawdown-triggered exit is whipsaw-prone (exit at
                   the bottom, miss the recovery) — the same failure
                   class as S4 R12 min-edge; left roadmap pending a
                   non-whipsaw design.
  - reentry      : cooldown_days defaults to 0 → no-op; a >0 cooldown
                   is a roadmap item.
"""
from __future__ import annotations

import pandas as pd

__all__ = ["apply_signal_decay_exit", "apply_turnover_band"]


def apply_signal_decay_exit(
    weights: pd.DataFrame,
    rank_panel: pd.DataFrame,
    exit_threshold: float = 0.50,
) -> pd.DataFrame:
    """Exit a held name once its rank decays below ``exit_threshold``.

    Args:
        weights: (date × symbol) target weight panel.
        rank_panel: (date × symbol) cross-sectional rank ∈ [0, 1].
        exit_threshold: a held name with rank below this is exited
            (weight → 0; the freed weight becomes cash, the next
            rebalance re-picks).

    A held name with NO rank on a bar (NaN — not scored) is KEPT — an
    exit is not forced on a data gap; the rebalance will reconsider.
    """
    if weights.empty:
        return weights
    rank = rank_panel.reindex(index=weights.index, columns=weights.columns)
    keep = rank.isna() | (rank >= exit_threshold)
    return weights.where(keep, 0.0)


def apply_turnover_band(
    weights: pd.DataFrame,
    band: float,
) -> pd.DataFrame:
    """No-trade band — skip per-name weight changes smaller than ``band``.

    When ``|target_i - held_i| < band`` the held weight for name i is
    kept; only names whose delta exceeds the band are traded. Cuts
    turnover from churning tiny deltas.
    """
    if weights.empty or band <= 0:
        return weights
    cols = list(weights.columns)
    held = weights.iloc[0].fillna(0.0)
    rows = [held]
    for i in range(1, len(weights)):
        target = weights.iloc[i].fillna(0.0)
        delta = target - held
        traded = delta.where(delta.abs() >= band, 0.0)
        held = held + traded
        rows.append(held)
    return pd.DataFrame(rows, index=weights.index, columns=cols)
