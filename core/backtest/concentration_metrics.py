"""M12 backtest concentration metrics + opt-in validator.

Per codex Round-5 audit and CLAUDE.md Framework Completion §M12.

Two responsibilities — kept deliberately separate:

1. ``compute_concentration_metrics`` — pure metric extractor over a
   weight DataFrame. Always cheap; safe to call on every
   ``BacktestEngine.run()`` and merge into ``BacktestResult.metrics``.
   Has no thresholds and no side effects.

2. ``validate_concentration`` — opt-in policy check. Compares observed
   top-1 / top-3 maxima against configurable ceilings (defaults match
   ``core.research.concentration.report.WARNING_TOP1`` / ``WARNING_TOP3``
   so the two subsystems agree on the boundary). Used by the
   acceptance-pack Gate 7 / candidate research validation paths;
   NOT a default in ``BacktestEngine`` so single-asset and diagnostic
   backtests are not forced to pass it.

Why opt-in (codex Round-5 scope correction): the repo has unit tests
and utility scripts that intentionally run single-asset or otherwise
concentrated backtests. A default raise would force unrelated test
rewrites without buying any safety. Opt-in lets research / acceptance
flows enforce the gate while leaving diagnostic paths free to inspect
concentrated weight matrices intentionally.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd


# Default thresholds — match the warning band in
# core.research.concentration.report (WARNING_TOP1 / WARNING_TOP3).
# Both subsystems use the same numbers; both compute top-N max from
# absolute weights; the two differ only in the *policy* applied to
# the values — research/concentration uses tiered classification
# (warning ↔ extreme); the backtest validator here uses these as hard
# reject thresholds when invoked from acceptance flows.
DEFAULT_TOP1_CEILING = 0.40
DEFAULT_TOP3_CEILING = 0.70


def compute_concentration_metrics(weights_df: pd.DataFrame) -> dict:
    """Compute per-date top-1 / top-3 weight concentrations.

    Returns a dict of metric values suitable for merging into
    ``BacktestResult.metrics``:

        {
          "m12_top1_weight_max": float,
          "m12_top3_weight_max": float,
          "m12_n_dates_with_weights": int,
        }

    Uses absolute weights so a long-only or long-short matrix produces
    the same metric meaning ("how much capital is in the largest 1 or
    3 names by absolute exposure").

    Empty input (None / 0 rows / 0 columns) returns
    ``{m12_top1_weight_max: 0.0, m12_top3_weight_max: 0.0,
    m12_n_dates_with_weights: 0}`` — deterministic so callers do not
    need to special-case missing weights.
    """
    if weights_df is None or len(weights_df) == 0 or weights_df.shape[1] == 0:
        return {
            "m12_top1_weight_max": 0.0,
            "m12_top3_weight_max": 0.0,
            "m12_n_dates_with_weights": 0,
        }
    abs_w = weights_df.abs()
    per_date_top1 = abs_w.apply(
        lambda r: r.nlargest(min(1, len(r))).sum() if len(r) else 0.0,
        axis=1,
    )
    per_date_top3 = abs_w.apply(
        lambda r: r.nlargest(min(3, len(r))).sum() if len(r) else 0.0,
        axis=1,
    )
    return {
        "m12_top1_weight_max": float(per_date_top1.max()) if len(per_date_top1) else 0.0,
        "m12_top3_weight_max": float(per_date_top3.max()) if len(per_date_top3) else 0.0,
        "m12_n_dates_with_weights": int(len(per_date_top1)),
    }


def validate_concentration(
    *,
    top1_observed: float,
    top3_observed: float,
    top1_ceiling: float = DEFAULT_TOP1_CEILING,
    top3_ceiling: float = DEFAULT_TOP3_CEILING,
) -> Tuple[bool, List[str]]:
    """Check observed top-N maxima against ceilings.

    Returns ``(passed, breach_reasons)``:
      - ``passed`` is True iff both observed values are at or below
        their respective ceilings (strictly ``>`` is a breach; equal
        passes).
      - ``breach_reasons`` is a list of short human-readable strings
        documenting each breach. Empty when ``passed=True``.

    The function does NOT mutate, clamp, or redistribute weights. M12
    is reject / flag only (codex Round-5 §"Implementation Bar #5").
    """
    breaches: List[str] = []
    if top1_observed > top1_ceiling:
        breaches.append(
            f"top1_weight_max={top1_observed:.4f} > ceiling={top1_ceiling:.2f}"
        )
    if top3_observed > top3_ceiling:
        breaches.append(
            f"top3_weight_max={top3_observed:.4f} > ceiling={top3_ceiling:.2f}"
        )
    return (not breaches, breaches)
