"""PRD #4 P4.3 — multi-TF + macro context feature bundles for ranking ML.

The 113-factor research panel already contains regime / drawdown / SPY-
relative / overnight features (see `core/factors/factor_generator.py`).
P4.3 defines named BUNDLES so the rank-model + sign-classifier pipelines
can opt into context features with deterministic provenance, instead
of hand-listing factor names per experiment.

Per PRD #4 P4.3 + auditor 2026-05-20:
  - "No specific TF combination is mandated" — bundles are research
    options not a fixed cadence
  - 15m→30m→60m cascade is NOT an established academic standard;
    PRD lets caller pick which bundle(s) to add
  - Acceptance = feature-ablation rank-IC delta, run in P4.5 acceptance
    experiment driver (not in this module)

Provided bundles (factor names verified against factor_registry RESEARCH_FACTORS):
  - ``regime_state``     : 3 regime-classifier factors (Family S, regime-ML)
  - ``drawdown_context`` : drawdown/drawup distance + market drawdown
  - ``relative_spy``     : multi-horizon SPY relative-strength
  - ``overnight``        : overnight gap/return signals
  - ``trend_macro``      : SPY trend + trend t-stat aggregates
  - ``all_context``      : union of all 5 above (for "full context" experiment)

§9.0 invariant:
  - This module is a thin factor-name selector; downstream classifier still
    produces discrete labels. No magnitude scaling introduced here.

PRD: docs/prd/20260520-prd_rank_first_ml_pipeline.md §P4.3
"""
from __future__ import annotations

from typing import Dict, Mapping, Tuple

import pandas as pd

__all__ = [
    "BUNDLES",
    "BUNDLE_NAMES",
    "extract_feature_bundle",
    "combine_feature_dicts",
    "bundle_size",
]


# Bundle definitions — keys verified against
# core.factors.factor_registry.RESEARCH_FACTORS snapshot 2026-05-20.
# Tests in test_context_features.py ensure every name in every bundle
# is in RESEARCH_FACTORS (drift-detect).
BUNDLES: Mapping[str, Tuple[str, ...]] = {
    "regime_state": (
        "regime_score_combined",
        "regime_transition_risk",
        "regime_persistence_score",
    ),
    "drawdown_context": (
        "drawdown_current",
        "drawup_from_252d_low",
        "market_drawdown",
        "sector_neutral_drawup_252d",
    ),
    "relative_spy": (
        "rel_spy_5d",
        "rel_spy_20d",
        "rs_vs_spy_21d",
        "rs_vs_spy_63d",
        "rs_vs_spy_126d",
        "residual_mom_spy_20d",
    ),
    "overnight": (
        "overnight_ret_1d",
        "overnight_gap_5d",
        "overnight_gap_21d",
        "overnight_vs_intraday",
    ),
    "trend_macro": (
        "spy_trend_200d",
        "spy_trend_gated_mom_63d",
        "trend_tstat_20d",
        "beta_spy_60d",
    ),
}

# Composite bundle = union of all named bundles (no dedup needed —
# bundle definitions above don't overlap; tests verify).
_ALL_CONTEXT = tuple(
    name for bundle in BUNDLES.values() for name in bundle
)
BUNDLES_FULL: Mapping[str, Tuple[str, ...]] = {
    **BUNDLES, "all_context": _ALL_CONTEXT,
}

BUNDLE_NAMES: Tuple[str, ...] = tuple(BUNDLES_FULL.keys())


class ContextFeatureError(KeyError):
    """Raised when a bundle name is unknown or a factor is missing from
    the supplied factor_panel."""


def extract_feature_bundle(
    factor_panel: Dict[str, pd.DataFrame], bundle_name: str,
) -> Dict[str, pd.DataFrame]:
    """Return a dict of just the named bundle's factor panels.

    Args:
        factor_panel: dict[factor_name, panel(date×symbol)] — typically
            the output of ``core.factors.factor_generator.generate_all_factors``
        bundle_name: one of BUNDLE_NAMES

    Raises:
        ContextFeatureError if bundle_name not registered OR if any
        factor in the bundle is missing from factor_panel (loud failure
        per `feedback_audit_surfaces_not_thorough` — better to fail
        cleanly than silently drop missing names).
    """
    if bundle_name not in BUNDLES_FULL:
        raise ContextFeatureError(
            f"unknown bundle_name={bundle_name!r}; valid: {BUNDLE_NAMES}")
    names = BUNDLES_FULL[bundle_name]
    missing = [n for n in names if n not in factor_panel]
    if missing:
        raise ContextFeatureError(
            f"bundle {bundle_name!r} requires factors {missing} which "
            f"are not in factor_panel. Verify factor_generator was run "
            f"with all required input data (volume_df / open_df / "
            f"intraday_60m / benchmark_map etc.).")
    return {n: factor_panel[n] for n in names}


def combine_feature_dicts(
    *feature_dicts: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """Merge multiple feature dicts; on name collision the LATEST wins.

    Useful for stacking base features (e.g. cycle06 3-factor) + a
    context bundle. Caller is responsible for ensuring panels are
    date/symbol-aligned (typically all come from the same
    factor_generator run).
    """
    out: Dict[str, pd.DataFrame] = {}
    for d in feature_dicts:
        out.update(d)
    return out


def bundle_size(bundle_name: str) -> int:
    """Return the number of factor names in a named bundle."""
    if bundle_name not in BUNDLES_FULL:
        raise ContextFeatureError(
            f"unknown bundle_name={bundle_name!r}; valid: {BUNDLE_NAMES}")
    return len(BUNDLES_FULL[bundle_name])
