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
    # PRD 20260424 Family B — position / breakout / path-shape
    # range_pos_252d          : (close - min_252d) / (max_252d - min_252d) ∈ [0,1]
    # days_since_52w_high     : bars since 252d rolling max (0 = today is new high)
    # breakout_20d_strength   : close / shift(max_20d) - 1 (breakout magnitude)
    # dist_from_new_high_252  : close / shift(max_252d) - 1 (distance from prior
    #                            252d high; distinct from dist_52w_high which
    #                            uses same-bar max)
    "range_pos_252d", "days_since_52w_high",
    "breakout_20d_strength", "dist_from_new_high_252",
    # PRD 20260424 Family C — liquidity / cost / risk state
    # amihud_20d       : rolling 20d mean of |ret| / dollar_volume (requires
    #                    volume). CONDITIONAL: omitted when volume_df is None
    # downside_vol_20d : rolling 20d std of negative-only daily returns
    # vol_ratio_5_20   : 5d vol / 20d vol (term structure compression)
    "amihud_20d", "downside_vol_20d", "vol_ratio_5_20",
    # PRD 20260424 Family D — trend quality
    # trend_tstat_20d : OLS slope t-stat of rolling 20d log(close) vs time
    "trend_tstat_20d",
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
    # Bucket A T1 batch 1 (Volume microstructure) — PRD-driven 2026-05-12
    # `docs/memos/20260512-quant_factor_literature_synthesis_v2.md` §2.1 +
    # `docs/memos/20260512-bucket_abc_macro_mvp_schedule.md` §1 D1.
    # 6 factor — closes PQS volume-microstructure gap (cycle04-08 unmined).
    # obv_norm_20d              : OBV 20d slope / 20d ΔOBV std (close+vol)
    # vol_price_corr_20d        : rolling corr(daily ret, ΔVol) 20d
    # volume_surge_when_flat    : vol z-score × |ret_20d|<5% flag
    # chaikin_money_flow_20d    : classic CMF (CONDITIONAL on H+L)
    # accum_dist_line_zscore_60d: A/D line 60d z-score (CONDITIONAL on H+L)
    # klinger_oscillator        : simplified Klinger sign-of-trend × volume
    #                             EMA(34) - EMA(55) (CONDITIONAL on H+L;
    #                             see _volume_factors() docstring for why
    #                             simplified-vs-canonical Klinger).
    # All 6 are research-only; NOT in PRODUCTION_FACTORS. Mining
    # discovers IC sign + magnitude via run_research_miner.py.
    "obv_norm_20d", "vol_price_corr_20d", "volume_surge_when_flat",
    "chaikin_money_flow_20d", "accum_dist_line_zscore_60d",
    "klinger_oscillator",
    # Bucket A T1 batch 2 part 1 (4-quadrant volume) — PRD 2026-05-12
    "up_vol_ratio_20d", "down_vol_ratio_20d", "vol_weighted_ret_20d",
    # Bucket A T1 batch 2 part 2 (consolidation / box-pattern / breakout
    # precursor; new family _family_g_consolidation). Some CONDITIONAL on
    # H+L (atr_compression / adx_low_trend) or volume (pre_breakout decay).
    "bb_squeeze_20d", "range_position_pct_60d", "consolidation_days_count",
    "atr_compression_20d", "adx_low_trend_flag",
    "pre_breakout_volume_decay",
    # Bucket A T1 batch 3 (higher moments + anchor + BAB + calendar)
    # PRD 2026-05-12. Higher moments per Harvey-Siddique 2000 +
    # Bressan 2024; BAB simplified per Frazzini-Pedersen 2014; calendar
    # per 2024 review (turn-of-month 10bps + sell-in-May persist).
    "coskew_60d_spy", "cokurt_60d_spy", "idiosyncratic_skew_60d",
    "nearness_to_52w_high", "weekly_reversal_signal_5d", "bab_score_60d",
    "turn_of_month_flag", "sell_in_may_seasonal", "month_end_quarter_end",
    # Bucket B T5 batch 1 (Piotroski + Magic Formula). PRD 2026-05-12.
    # SEC EDGAR companyfacts cache via core/data/edgar_provider + PIT
    # store via core/data/fundamentals_store. NOT computed by
    # generate_all_factors (different code path); must be merged in
    # via compute_fundamental_factors_batch1() into a separate fundamental-
    # factor DataFrame dict before mining. Piotroski 9-boolean +
    # composite + 2 derived per Piotroski 2000; Schwartz-Hanauer Dec
    # 2024 NBER confirmed 1963-2022 persistent. Magic Formula per
    # Greenblatt 1999.
    "piotroski_net_income_positive",
    "piotroski_cfo_positive",
    "piotroski_roa_yoy_improving",
    "piotroski_cfo_greater_than_ni",
    "piotroski_leverage_yoy_decreasing",
    "piotroski_current_ratio_yoy_improving",
    "piotroski_no_dilution",
    "piotroski_gross_margin_yoy_improving",
    "piotroski_asset_turnover_yoy_improving",
    "piotroski_f_score",
    "piotroski_high_filter",
    "piotroski_low_warning",
    "magic_earnings_yield_ttm",
    "magic_roic_ttm",
    "magic_formula_rank_composite",
    # Bucket B T5 batch 2 (Beneish + Altman + capital return + growth)
    # PRD 2026-05-12. Beneish per 1999 paper + 2025 G7 + Borsa Istanbul
    # ML validations. Altman manufacturing-5 1968 (still valid 2025
    # per MDPI review). Capital return per S&P DJI 2024 $942.5B record
    # buyback annual; FCF profitability Sharpe 0.62 > FCFY 0.50
    # per LSEG 2025. Asset growth (FF5 CMA) per Robeco 2024 weakening
    # but still cross-sectional alpha. R&D per Goyal-Wahal April 2024
    # (note: capitalize-as-asset → alpha → 0; expense treatment matters).
    "beneish_dsri", "beneish_gmi", "beneish_aqi", "beneish_sgi",
    "beneish_depi", "beneish_sgai", "beneish_tata", "beneish_lvgi",
    "beneish_m_score",
    "altman_wc_to_assets", "altman_re_to_assets", "altman_ebit_to_assets",
    "altman_mveq_to_liab", "altman_sales_to_assets",
    "altman_z_score",
    "buyback_yield_ttm", "dividend_yield_ttm", "shareholder_yield_ttm",
    "fcf_yield_ttm", "fcf_to_assets_ttm",
    "revenue_growth_yoy", "gross_profit_growth_yoy", "sales_acceleration",
    "asset_growth_yoy", "dol_4q_window", "rd_intensity_ttm",
    # Bucket C T3 (sector-relative). PRD 2026-05-12. Manual GICS
    # mapping at config/sector_map.yaml with PIT reclassification
    # (META + GOOGL Tech → Communication Services 2018-09-28). 5 sector
    # factors via core/factors/sector_factors.py; computed separately
    # from generate_all_factors (callers wire price_df → SectorResolver).
    "sector_rel_mom_20d", "sector_neutral_drawup_252d",
    "sector_leader_rank_mom_12_1", "sector_breadth_pct_5d",
    "sector_dispersion_std_20d",
    # Bucket Macro (PRD-E TAA reactivation path). PRD 2026-05-12.
    # FRED CSV ingest via core/data/fred_provider.py (no API key).
    # 6 time-series factors broadcast across universe; each cell in
    # a given date row carries the same macro value. Useful as
    # regime / risk-conditioning input.
    "yield_curve_10y_2y", "fed_funds_yoy_change", "dxy_zscore_60d",
    "wti_yoy_pct", "vix_zscore_60d", "cpi_yoy_pct",
    # Bucket A T1 batch 3 — event-window factors (PRD 20260512 Round D).
    # NFP rule exact (first Friday of month); CPI heuristic (~2nd
    # Tuesday); FOMC heuristic (~8 meetings/year fixed weeks). User
    # can override via config/macro_event_calendar.yaml for precision.
    "pre_fomc_window_flag", "post_fomc_window_flag",
    "pre_cpi_window_flag", "pre_nfp_window_flag",
    # Quality
    "rolling_sharpe_126d", "return_per_risk_21d",
    # Path shape (LLM-Round 10 promotion, 2026-04-21, user-authorized):
    # drawup_from_252d_low is the symmetric counterpart of max_dd_126d
    # (distance from rolling 252d LOW rather than 252d HIGH). Research-
    # only — passes §5.4 reverse review (OOS IR +0.386, 5/6 regimes) but
    # isolated-strategy MaxDD is -77% (Round 5). Use as composite
    # component inside a risk-managed strategy.
    "drawup_from_252d_low",
    # Swing-extrema S/R family (PRD 20260505 Step 2). Daily-resolution
    # nearest-support / nearest-resistance via local swing highs/lows
    # (`core.intraday.sr_swing.distance_to_sr`, n=5 confirmation, 20-bar
    # lookback). All three factors are non-negative fractions when
    # defined; NaN when no qualifying swing in lookback. CONDITIONAL on
    # high_df + low_df availability (mirrors _volume_factors pattern).
    # Sign convention (long-only US large-cap): smaller dist_to_swing_low
    # signals proximity to support; smaller sr_range_compression signals
    # near-term range expansion. Mining discovers IC sign from history;
    # NOT promoted to PRODUCTION_FACTORS pending Step 5+ backtest evidence.
    "dist_to_swing_high_20d", "dist_to_swing_low_20d",
    "sr_range_compression_20d",
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
