"""Factor registry: single source of truth for which factors exist where.

Ends the dual-track (research vs execution) ambiguity that used to be
implicit — before this module, promoting a research factor into
`MultiFactorStrategy` required syncing its name, semantics, and weight
range manually across 3 places (factor_generator, multi_factor, mining
search space), and there was no automated way to detect a mismatch.

Three registries:

1. PRODUCTION_FACTORS
   Factors whose names are accepted by `MultiFactorStrategy(factor_weights=...)`
   and whose weight slot is tunable by `MultiFactorSpace.suggest()`. Every
   name here corresponds to an inline computation block in
   `core/signals/strategies/multi_factor.py::generate()`.

2. RESEARCH_FACTORS
   Factors produced by `core/factors/factor_generator.py::generate_all_factors`.
   Used for IC screening, XGBoost importance, and factor-funnel research.
   These may or may not map to a production factor (see RESEARCH_TO_PRODUCTION_MAP).

3. RESEARCH_TO_PRODUCTION_MAP
   For research factors whose economic intent is already represented by a
   production factor, document the mapping. Research factors not in this
   map are "research-only" and cannot be used as execution signal without
   being promoted first.

Promotion workflow
------------------
When research (IC screening / XGB / OOS) identifies a factor worth
deploying:

  1. Add the factor's inline computation to `MultiFactorStrategy.generate()`
     under a canonical production name.
  2. Add the name to `PRODUCTION_FACTORS` here.
  3. If it shadows a research factor, add an entry to
     `RESEARCH_TO_PRODUCTION_MAP`.
  4. Add the weight slot to `MultiFactorSpace.suggest()` so mining can
     tune it.
  5. Run the full test suite — `test_factor_registry.py` enforces
     consistency between registries and strategy code.

Contract check functions are used at runtime by MultiFactorStrategy and
MultiFactorSpace to fail fast on unregistered factor names.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

# ── Production factors (used by MultiFactorStrategy) ─────────────────────────
#
# Every name here MUST have a corresponding inline computation in
# `core/signals/strategies/multi_factor.py::generate()`. Adding a name
# here without implementing the factor is a contract violation.

PRODUCTION_FACTORS: FrozenSet[str] = frozenset({
    "low_vol",       # negative rolling vol of daily returns
    "momentum",      # long-lookback minus short-lookback return
    "quality",       # rolling annualized Sharpe proxy
    "pv_div",        # price-volume divergence (short-window correlation)
    "rel_strength",  # 63d excess return vs SPY
    "market_trend",  # SPY vs 200d MA (broadcast across symbols)
})


# ── Research factors (produced by factor_generator.generate_all_factors) ─────
#
# These 35 factor names are enumerated from the current factor_generator
# output. Keeping the list explicit lets us detect drift when new factor
# families are added to factor_generator (test_factor_registry catches it).

RESEARCH_FACTORS: FrozenSet[str] = frozenset({
    # Momentum family
    "mom_21d", "mom_63d", "mom_126d", "mom_252d", "mom_12_1",
    "risk_adj_mom_63d",
    # Mean reversion
    "reversal_5d", "reversal_10d", "reversal_21d",
    "mean_rev_sma20", "mean_rev_sma50",
    # Volatility
    "vol_21d", "vol_63d", "vol_regime",
    "drawdown_current", "max_dd_126d",
    # Volume
    "volume_surge_20d", "price_volume_div",
    # Quality
    "rolling_sharpe_126d", "return_per_risk_21d",
    # Relative strength
    "rs_vs_spy_21d", "rs_vs_spy_63d", "rs_vs_spy_126d",
    "rs_acceleration",
    # Sector rotation
    "rank_momentum_change",
    "xsection_rank_21d", "xsection_rank_63d",
    # Macro regime
    "spy_trend_200d", "market_vol_ratio", "market_drawdown",
    # Overnight
    "overnight_gap_5d", "overnight_gap_21d", "overnight_vs_intraday",
    # Breadth
    "cross_section_dispersion_21d", "advance_ratio_10d",
})


# ── Research → Production mapping (economic-intent equivalence) ──────────────
#
# Key = research factor name in factor_generator output
# Value = production factor name (in PRODUCTION_FACTORS) with the same
#         economic intent. None means research-only.
#
# Interpretation: a research factor with a non-None mapping is ALREADY
# represented in execution under the mapped production name — promoting
# it means replacing the inline computation with this research version,
# or accepting both coexist (research keeps the granular form, production
# keeps the stable form).

RESEARCH_TO_PRODUCTION_MAP: Dict[str, str] = {
    # Volatility → low_vol
    "vol_21d":                 "low_vol",
    "vol_63d":                 "low_vol",
    # Momentum → momentum (long minus short)
    "mom_252d":                "momentum",
    "mom_12_1":                "momentum",
    # Quality → rolling Sharpe
    "rolling_sharpe_126d":     "quality",
    "return_per_risk_21d":     "quality",
    # Price-volume divergence
    "price_volume_div":        "pv_div",
    # Relative strength vs SPY
    "rs_vs_spy_63d":           "rel_strength",
    # Market trend
    "spy_trend_200d":          "market_trend",
}


def research_only_factors() -> FrozenSet[str]:
    """Research factors with NO production counterpart — candidates for
    next promotion round."""
    return frozenset(
        n for n in RESEARCH_FACTORS
        if RESEARCH_TO_PRODUCTION_MAP.get(n) is None
    )


def check_execution_factor_names(factor_weights: Dict[str, float]) -> list[str]:
    """Return list of factor names present in `factor_weights` but NOT
    in PRODUCTION_FACTORS. Empty list = everything is registered.

    Callers: MultiFactorStrategy.__init__ (warn on unknown names —
    catches typos and research names sneaking into execution).
    """
    return [name for name in factor_weights if name not in PRODUCTION_FACTORS]


def production_factor_names() -> list[str]:
    """Stable ordered list of production factor names. Order matches
    MultiFactorStrategy._DEFAULT_WEIGHTS iteration intent."""
    return [
        "low_vol", "momentum", "quality", "pv_div",
        "rel_strength", "market_trend",
    ]
