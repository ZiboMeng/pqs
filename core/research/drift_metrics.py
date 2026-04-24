"""Drift metric helpers (Phase E-2 R10).

Pure functions for computing drift between two paper runs (or a paper
run and a fresh replay). Reader side of the paper artifact schema.

Drift semantics: "paper run at time T was recorded with NAV series A.
A fresh replay of the same frozen spec on the same window now
produces NAV series B. Any meaningful |A - B| > 0 indicates either:
  - code/factor logic changed since the paper run
  - data store updated (new bars backfilled, delisting handled)
  - non-determinism in the pipeline (should not exist per invariant)
  - true paper/live-execution divergence (future when real broker
    is wired)

The R10 drift report is INFORMATIONAL only per auditor fix: a 50 bps
mean drift or 2% any-single-day drift surfaces a manual-review flag,
but does NOT auto-demote / auto-revoke / auto-anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


__all__ = [
    "DriftThresholds",
    "compute_nav_drift",
    "compute_position_drift",
    "worst_drift_day",
]


@dataclass(frozen=True)
class DriftThresholds:
    """Informational thresholds per PRD E2-R10. Not enforced; only
    reported."""

    mean_drift_bps: float = 50.0        # mean |delta| > 50 bps -> review
    worst_day_fraction: float = 0.02    # any single day > 2% -> review


# ── NAV drift ────────────────────────────────────────────────────────────────


def compute_nav_drift(
    paper_nav: pd.Series,
    replay_nav: pd.Series,
) -> pd.DataFrame:
    """Compute per-day NAV drift in bps.

    Both series align on their date index. Missing dates on either side
    are dropped (common-intersection semantics).

    Returns DataFrame with columns:
      date        : index
      paper_nav   : from the paper artifact
      replay_nav  : from fresh replay
      delta_abs   : (replay - paper)
      delta_bps   : (replay - paper) / paper * 10000

    An empty common index produces an empty DataFrame (shape (0, 4)).
    """
    if not isinstance(paper_nav, pd.Series) or not isinstance(replay_nav, pd.Series):
        raise TypeError("paper_nav and replay_nav must be pd.Series")
    common = paper_nav.index.intersection(replay_nav.index)
    if len(common) == 0:
        return pd.DataFrame(columns=["paper_nav", "replay_nav",
                                     "delta_abs", "delta_bps"])
    p = paper_nav.reindex(common)
    r = replay_nav.reindex(common)
    delta = r - p
    # Protect against div-by-zero/NaN
    with np.errstate(divide="ignore", invalid="ignore"):
        delta_bps = delta / p * 10_000.0
        delta_bps = delta_bps.where(np.isfinite(delta_bps), 0.0)
    return pd.DataFrame({
        "paper_nav": p,
        "replay_nav": r,
        "delta_abs": delta,
        "delta_bps": delta_bps,
    })


def worst_drift_day(drift: pd.DataFrame) -> Optional[dict]:
    """Return the (date, delta_bps) of the worst absolute drift day.

    None if `drift` is empty.
    """
    if drift.empty or "delta_bps" not in drift.columns:
        return None
    absolute = drift["delta_bps"].abs()
    if absolute.empty or not np.isfinite(absolute).any():
        return None
    idx = absolute.idxmax()
    return {
        "date": str(idx.date() if hasattr(idx, "date") else idx),
        "delta_bps": float(drift.loc[idx, "delta_bps"]),
        "paper_nav": float(drift.loc[idx, "paper_nav"]),
        "replay_nav": float(drift.loc[idx, "replay_nav"]),
    }


# ── Position drift ──────────────────────────────────────────────────────────


def compute_position_drift(
    paper_targets: pd.DataFrame,
    replay_targets: pd.DataFrame,
) -> pd.DataFrame:
    """Per-day position-set drift.

    Returns DataFrame with columns:
      date                 : index
      n_paper              : count of non-zero positions in paper
      n_replay             : count of non-zero positions in replay
      n_symbol_diff        : count of symbols where (paper>0) XOR (replay>0)
      weight_l1_diff       : sum |w_paper - w_replay|
      weight_l1_diff_half  : weight_l1_diff / 2 (standard turnover-style)

    Handles different symbol universes by reindexing to union.
    """
    if not isinstance(paper_targets, pd.DataFrame) or not isinstance(replay_targets, pd.DataFrame):
        raise TypeError("paper_targets and replay_targets must be DataFrames")
    common_idx = paper_targets.index.intersection(replay_targets.index)
    if len(common_idx) == 0:
        return pd.DataFrame(columns=[
            "n_paper", "n_replay", "n_symbol_diff",
            "weight_l1_diff", "weight_l1_diff_half",
        ])
    all_syms = sorted(set(paper_targets.columns) | set(replay_targets.columns))
    p = paper_targets.reindex(index=common_idx, columns=all_syms).fillna(0.0)
    r = replay_targets.reindex(index=common_idx, columns=all_syms).fillna(0.0)
    n_paper = (p != 0).sum(axis=1)
    n_replay = (r != 0).sum(axis=1)
    held_paper = p != 0
    held_replay = r != 0
    symbol_diff = (held_paper ^ held_replay).sum(axis=1)
    l1 = (p - r).abs().sum(axis=1)
    return pd.DataFrame({
        "n_paper": n_paper.astype(int),
        "n_replay": n_replay.astype(int),
        "n_symbol_diff": symbol_diff.astype(int),
        "weight_l1_diff": l1,
        "weight_l1_diff_half": l1 / 2.0,
    })
