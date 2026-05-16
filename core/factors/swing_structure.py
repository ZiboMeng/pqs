"""Swing-segment structure features (family T) — chart-structure input layer.

Per `docs/prd/20260515-chart_structure_input_representation_prd.md` Phase 1
and its ralph-loop execution PRD
(`docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md`).

**R1 scope (this commit)**: causal swing-sequence infrastructure only —
`SwingPoint` / `SwingStructureConfig`, `detect_raw_swings`,
`_collapse_alternating` (execution PRD §B-B2 rule), `confirmed_swings_asof`.
The 12 structure features land in R2.

Causality contract (PRD §3.4 / §2.2)
------------------------------------
`detect_swing_extrema` uses a ``[i-n, i+n]`` window, so a swing at bar ``i``
is only confirmable at bar ``i+n``. Each swing carries
``confirmation_idx = i + swing_n``.

The alternating-collapse (§B-B2: of two consecutive same-kind extrema keep
the more extreme) MUST run AFTER the as-of-t confirmation filter, not
before. Collapse-then-filter is non-causal: a future swing could be the
"more extreme" one and silently drop a past swing from the day-t read.
Hence the design is **filter-then-collapse**:
  - ``detect_raw_swings`` runs ``detect_swing_extrema`` ONCE and returns the
    raw (un-collapsed) extrema. Raw extrema are causal — a raw extremum at
    ``i`` depends only on bars in ``[i-n, i+n]``.
  - ``confirmed_swings_asof(raw, t)`` filters to ``confirmation_idx <= t``
    THEN collapses. Cheap per-t (extrema count << bar count); the expensive
    ``detect_swing_extrema`` is not re-run (execution PRD §B-B1).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.intraday.sr_swing import detect_swing_extrema

HIGH = "HIGH"
LOW = "LOW"


@dataclass(frozen=True)
class SwingPoint:
    """A swing extremum in a single symbol's bar sequence.

    idx               positional index into the bar sequence (0-based).
    price             swing price — bar ``high`` for HIGH, ``low`` for LOW.
    kind              ``HIGH`` or ``LOW``.
    confirmation_idx  ``idx + swing_n`` — first bar index at which this
                      swing is causally confirmable (PRD §3.4).
    """

    idx: int
    price: float
    kind: str
    confirmation_idx: int


@dataclass(frozen=True)
class SwingStructureConfig:
    """family T config.

    ``swing_n`` is a FACT default (= ``detect_swing_extrema`` ``n=5``).
    ``K`` / ``tol`` / ``maturity_cap`` are PLACEHOLDER values per PRD §C —
    they have NO evidence basis and must be calibrated in Phase 2A. Real
    runs load these from ``config/swing_structure.yaml`` (R2); the defaults
    here are only for unit tests / smoke use.
    """

    swing_n: int = 5
    K: int = 8
    tol: float = 0.15
    maturity_cap: int = 5


def detect_raw_swings(
    bars: pd.DataFrame, cfg: SwingStructureConfig
) -> list[SwingPoint]:
    """Raw (un-collapsed) swing extrema for one symbol, idx-ascending.

    Runs ``detect_swing_extrema`` ONCE (compute-once, execution PRD §B-B1).
    A bar flagged BOTH swing-high and swing-low (a degenerate bar that
    strictly engulfs its whole ``[i-n, i+n]`` window) is dropped — it is
    not a clean directional pivot.
    """
    ext = detect_swing_extrema(bars, n=cfg.swing_n)
    is_high = ext["is_swing_high"].to_numpy()
    is_low = ext["is_swing_low"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()

    out: list[SwingPoint] = []
    for i in range(len(bars)):
        h = bool(is_high[i])
        ll = bool(is_low[i])
        if h and ll:
            continue  # degenerate engulfing bar — drop
        if h:
            out.append(SwingPoint(i, float(high[i]), HIGH, i + cfg.swing_n))
        elif ll:
            out.append(SwingPoint(i, float(low[i]), LOW, i + cfg.swing_n))
    return out


def _collapse_alternating(raw_swings: list[SwingPoint]) -> list[SwingPoint]:
    """Collapse an idx-ordered extrema list into a STRICTLY alternating
    HIGH/LOW sequence (execution PRD §B-B2).

    Rule for consecutive same-kind extrema: keep the more extreme one
    (higher price for HIGH, lower for LOW); discard the other. Ties keep
    the earlier point (no replacement on equality).
    """
    out: list[SwingPoint] = []
    for s in raw_swings:
        if not out:
            out.append(s)
            continue
        last = out[-1]
        if s.kind != last.kind:
            out.append(s)
            continue
        # consecutive same kind — keep the more extreme
        more_extreme = (
            s.price > last.price if s.kind == HIGH else s.price < last.price
        )
        if more_extreme:
            out[-1] = s
    return out


def confirmed_swings_asof(
    raw_swings: list[SwingPoint], t_idx: int
) -> list[SwingPoint]:
    """Strictly-alternating swing sequence causally confirmed as of bar
    ``t_idx``.

    Filter-then-collapse (see module docstring): keep raw swings with
    ``confirmation_idx <= t_idx``, then collapse to alternating. Day-t
    family-T features must use only this subset.
    """
    confirmed = [s for s in raw_swings if s.confirmation_idx <= t_idx]
    return _collapse_alternating(confirmed)
