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
    "drawup_from_252d_low",  # R15 promotion (user-auth 2026-04-21):
                     # distance from rolling 252d min; 4-method consensus
                     # (deep_check PASS, Ridge #1, XGB #7, factor_screen #2)
})


# ── Research factors (produced by factor_generator.generate_all_factors) ─────
#
# These 35 factor names are enumerated from the current factor_generator
# output. Keeping the list explicit lets us detect drift when new factor
# families are added to factor_generator (test_factor_registry catches it).

RESEARCH_FACTORS: FrozenSet[str] = frozenset({
    # Baseline returns family (PRD 20260423 Step 1 Round 1)
    # Raw close-to-close short-horizon returns + raw 1-bar gap/intraday.
    # Unsigned siblings of reversal_5d / overnight_gap_5d etc. Research-only.
    "ret_1d", "ret_2d",
    "overnight_ret_1d", "intraday_ret_1d",
    # Baseline volatility / range family (PRD 20260423 Step 1 Round 2)
    # hl_range = (H-L)/prev_close (normalized 1-bar true range lite).
    # dollar_vol_20d = 20d MA of close*volume (both feature & mask source).
    "hl_range", "dollar_vol_20d",
    # Baseline relative / position family (PRD 20260423 Step 1 Round 3)
    # ret_5d        = raw 5d close-to-close return (unsigned sibling of
    #                 reversal_5d)
    # dist_52w_high = close / rolling_max(close, 252) - 1 (per §D4)
    # rel_spy_5d    = short-horizon benchmark-relative return (sibling
    #                 of rs_vs_spy_21d/63d/126d)
    "ret_5d", "dist_52w_high", "rel_spy_5d",
    # PRD 20260424 Family A — benchmark-relative / residual / risk exposure
    # rel_spy_20d          : 20d stock ret - 20d SPY ret
    # rel_qqq_20d          : same vs QQQ (net-new: no rs_vs_qqq_* existed)
    # beta_spy_60d         : rolling 60d OLS beta of daily returns vs SPY
    # residual_mom_spy_20d : 20d sum of daily residuals after 60d beta remove
    # All 4 CONDITIONAL on benchmark availability (SPY or QQQ column / map).
    # Missing benchmark → feature silently omitted (not NaN-filled).
    "rel_spy_20d", "rel_qqq_20d", "beta_spy_60d", "residual_mom_spy_20d",
    # Research aliases (PRD §D3 / §3.1.C). Same DataFrame as canonical;
    # kept in registry so drift-check still passes and LLM / mining code
    # can query either name.
    "vol_20d",           # alias → vol_21d
    "volume_ratio_20d",  # alias → volume_surge_20d
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
    # Path shape (LLM-Round 10 promotion, 2026-04-21, user-authorized):
    # drawup_from_252d_low is the symmetric counterpart of max_dd_126d
    # (distance from rolling 252d LOW rather than 252d HIGH). Research-
    # only — passes §5.4 reverse review (OOS IR +0.386, 5/6 regimes) but
    # isolated-strategy MaxDD is -77% (Round 5). Use as composite
    # component inside a risk-managed strategy.
    "drawup_from_252d_low",
    # Relative strength
    "rs_vs_spy_21d", "rs_vs_spy_63d", "rs_vs_spy_126d",
    "rs_acceleration",
    # Sector rotation
    "rank_momentum_change",
    "xsection_rank_21d", "xsection_rank_63d",
    # Macro regime
    "spy_trend_200d", "market_vol_ratio", "market_drawdown",
    # Regime-gated (R7 deep-mining 2026-04-22). Deep check PASS (OOS IR
    # +0.332, 6/6 regimes correct sign). Dedup ρ=+0.87 vs mom_63d but
    # incremental IC +0.0458 in R5 interaction mine.
    "spy_trend_gated_mom_63d",
    # Weak-market conditional (R10 deep-mining 2026-04-22, Codex-seeded).
    # Deep check PASS (OOS IR -0.402 ABS, 6/6 regimes, quartile stable).
    # NEGATIVE direction: factor predicts LOW forward returns for
    # defensive/weak-market-outperformers; use with flipped sign.
    "weak_market_relative_strength_63d",
    # Overnight
    "overnight_gap_5d", "overnight_gap_21d", "overnight_vs_intraday",
    # Breadth
    "cross_section_dispersion_21d", "advance_ratio_10d",
    # Intraday (Round 5 Topic F, 2026-04-20). Research-only — computed
    # from 60m bars via generate_all_factors(intraday_bars_60m=...). NOT
    # promoted to PRODUCTION_FACTORS yet; awaiting IC/OOS/regime funnel.
    "realized_vol_60m_21d", "intraday_vol_ratio_21d",
    "intraday_autocorr_21d",
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
    # Volatility → low_vol. vol_63d was MERGED out of this map in
    # Round 6 Topic E (2026-04-20): vol_63d and low_vol now share a
    # single implementation via core/factors/base_factors.py::
    # low_vol_factor, so they are no longer a "shadow" pair.
    # vol_21d is kept because it's a distinct lookback (research-only).
    "vol_21d":                 "low_vol",
    # Momentum → momentum (long minus short)
    "mom_252d":                "momentum",
    "mom_12_1":                "momentum",
    # Quality → rolling Sharpe
    "rolling_sharpe_126d":     "quality",
    "return_per_risk_21d":     "quality",
    # Price-volume divergence
    "price_volume_div":        "pv_div",
    # Relative strength vs SPY: rs_vs_spy_63d MERGED out in Round 6
    # Topic E — shares implementation with `rel_strength` via
    # base_factors.rel_strength_factor. Other horizons (21/126) kept
    # as distinct research variants.
    # Market trend
    "spy_trend_200d":          "market_trend",
    # PRD 20260423 §D3 alias: `vol_20d` references the same DataFrame as
    # `vol_21d`, which in turn shadows `low_vol`. The 20d/21d difference
    # is deliberately not re-implemented (see PRD D3 rationale).
    # `volume_ratio_20d` also aliases `volume_surge_20d` (research-only),
    # so it stays out of this map and is detected as research-only by
    # research_only_factors().
    "vol_20d":                 "low_vol",
    # Note: drawup_from_252d_low is NOT in this map. It uses the SAME
    # name in both RESEARCH_FACTORS and PRODUCTION_FACTORS (not a
    # "shadow" — the research-facing and production-facing names are
    # identical). The two implementations (factor_generator.
    # _quality_factors and MultiFactorStrategy.generate) must stay
    # numerically identical; formula is documented in both sites:
    # `(close - close.rolling(252).min()) / close.rolling(252).min()`.
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


class UnregisteredFactorError(ValueError):
    """Raised when strict registry gate sees an unregistered factor name.

    Round 4 Topic D (2026-04-20). Strict mode turns the legacy WARN+drop
    silent-failure into a loud, CI-visible ValueError. Use in mining
    runs, pre-production sanity checks, or any context where silent
    factor-name drift is a research-integrity hazard.
    """


def enforce_execution_factor_names(
    factor_weights: Dict[str, float],
    *,
    strict: bool = False,
) -> Dict[str, float]:
    """Gate factor_weights against PRODUCTION_FACTORS.

    Parameters
    ----------
    factor_weights : dict of name → weight (input)
    strict         : False (default) = warn + drop unknown names, return
                     filtered dict. True = raise UnregisteredFactorError
                     on any unknown name.

    Returns filtered dict where every key is in PRODUCTION_FACTORS.
    Strict mode never returns — either raises or passes through unchanged.

    Unifies the old inline logic in MultiFactorStrategy.__init__ so both
    the default (warn) and strict paths route through a single code path
    that tests can exercise directly.
    """
    from core.logging_setup import get_logger as _get_logger
    unknown = check_execution_factor_names(factor_weights)
    if not unknown:
        return dict(factor_weights)
    if strict:
        raise UnregisteredFactorError(
            f"Unregistered factor name(s) in factor_weights: {unknown}. "
            f"Known production factors: {sorted(PRODUCTION_FACTORS)}. "
            f"To add a new factor, update core/factors/factor_registry.py "
            f"after passing the research funnel."
        )
    _get_logger("factor_registry").warning(
        "Dropping unregistered factor names: %s. Known production: %s. "
        "Add new factors via core/factors/factor_registry.py after the "
        "research funnel. (To upgrade this to a hard error set "
        "config/risk.yaml::factor_registry.strict_mode=true.)",
        unknown, sorted(PRODUCTION_FACTORS),
    )
    return {k: v for k, v in factor_weights.items() if k in PRODUCTION_FACTORS}


def production_factor_names() -> list[str]:
    """Stable ordered list of production factor names. Order matches
    MultiFactorStrategy._DEFAULT_WEIGHTS iteration intent."""
    return [
        "low_vol", "momentum", "quality", "pv_div",
        "rel_strength", "market_trend",
        "drawup_from_252d_low",  # R15 promotion
    ]
