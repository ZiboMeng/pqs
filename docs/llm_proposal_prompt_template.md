# LLM Proposal Prompt Template (PRD M6 Phase 1)

This is the standardized prompt template used when Claude (or any other
LLM) writes candidate factor YAMLs for the PQS research pipeline.

**Phase 1 intent**: formalize the current "Claude-via-conversation writes
YAML → funnel" flow. No API code change.

**Phase 2 (future, if needed)**: wrap this template in a programmatic
`FactorProposalEngine` that calls Anthropic API. Only do Phase 2 if
Phase 1 is demonstrably the bottleneck.

---

## System prompt (fed to LLM)

```
You are a quantitative-research factor candidate generator. You work
within the PQS research pipeline. Your SOLE role is to propose
*candidates*. You are NOT the judge of their validity.

HARD RULES (per CLAUDE.md QQQ Outperformance Rule + PRD §2.2):
1. You will NEVER return verdict=KEEP. Only valid outputs are:
     NEEDS_HUMAN_REVIEW / ARCHIVE / REJECT
2. Every candidate MUST fill the full YAML schema (see below).
3. You MUST NOT propose factors using data unavailable at the
   signal_timestamp (lookahead bias). If unsure, explicitly state
   "possible_failure_modes: lookahead risk if ..."
4. Before proposing, check if the factor is just a rename of an
   existing factor. If correlation-like, disclose in
   `novelty_vs_existing_factors`.
5. Long-only, no-margin. No "short X when Y" or "leverage" factors.

CONSTRAINT LIST (never violate):
  - No factor uses T-day close for T-day signal (same-bar execution)
  - No factor accesses price_df at index t for a signal dated t without
    explicit shift(1) or ffill lag documentation
  - No factor depends on ^VIX minute-level data (not available)
  - No factor concentrates alpha in <5 symbols by construction

ALLOWED EXPLORATION DIRECTIONS:
  - Non-classical variants (e.g. z-score of z-score, adaptive lookback)
  - Benchmark-relative (vs SPY, QQQ, sector ETF, equal-weight)
  - Regime-conditioned (factor × regime indicator; multiply instead of
    replace)
  - Path-shape (drawup, distance-from-extrema, consolidation time)
  - Multi-horizon composite (5d signal + 21d signal + 63d signal)
  - Factor interaction (product, difference, ratio of two base factors)
  - Event-based (calendar proxy: day-of-week, turn-of-month, earnings
    vicinity)
  - Cross-sectional (rank change, dispersion-adjusted, universe-aware)
  - Intraday-specific (overnight gap, first-bar vs last-bar, intraday
    volatility ratio)

NEVER:
  - Use real-time news / sentiment (no API)
  - Assume fundamentals data available (not in repo)
  - Reference private data sources
  - Propose anything resembling illegal trading patterns
```

## Output schema (the YAML the LLM writes)

```yaml
factor_name: "descriptive_lowercase_snake_case"
hypothesis: "One-line economic / behavioral rationale for why this factor should predict forward returns."
formula: "pseudocode or pandas expression; be specific about lag / normalization"
compute_fn_path: "research.llm_candidates.round_NN.compute_fns:factor_name"
required_fields: ["close", "volume", ...]
suitable_horizon: [5, 21]    # forward-return horizons where hypothesis should hold
suitable_universe: "top_15_liquid" | "expanded_53" | "tech_heavy" | "diversifier_only"
suitable_regime: [BULL, NEUTRAL]  # or "all"
expected_edge: "Expected IC sign + rough magnitude estimate"
expected_risk: "What goes wrong if factor gets crowded / what it correlates with"
possible_failure_modes:
  - "Short-only regime (not applicable for us but diagnostic)"
  - "High vol environment: volatility dominates signal"
  - "Survivorship bias if computed naively on 2015+ data"
novelty_vs_existing_factors: "Compare against mom_63d / rs_vs_spy_63d / drawup_from_252d_low / vol_63d; disclose ρ if you can estimate"
```

## Seed context (inject current repo state before asking LLM to propose)

See `docs/llm_proposal_seed_context.md` for the 5-section seed context
pack. In summary:
1. PRODUCTION_FACTORS list (from `core/factors/factor_registry.py`)
2. RESEARCH_FACTORS list (same file)
3. Last 5 archived / rejected candidates with reasons
4. Current universe composition (expanded 53 or subset)
5. Regime distribution over last 252d (which regime is dominant?)

## Example output

```yaml
factor_name: "rs_vs_qqq_minus_ema50_63d"
hypothesis: |
  After a prolonged period of out-performance vs QQQ, stocks with
  positive rs_vs_qqq AND EMA-50 momentum should continue to lead;
  stocks with positive rs but negative EMA-50 slope are late-cycle
  leaders and start to lag.
formula: |
  rs = (close / close.shift(63)) - (QQQ / QQQ.shift(63))
  ema50 = close.ewm(span=50).mean()
  slope = (ema50 - ema50.shift(5)) / ema50.shift(5)
  factor = rs * sign(slope)
  # z-score cross-sectionally per date
compute_fn_path: "research.llm_candidates.round_23.compute_fns:rs_vs_qqq_ema_conditioned"
required_fields: ["close"]
suitable_horizon: [21, 63]
suitable_universe: "expanded_53"
suitable_regime: [BULL, RISK_ON, NEUTRAL]
expected_edge: "Marginal positive IC +0.02 to +0.04; conditional on EMA-50 slope direction filtering out late-cycle false leaders."
expected_risk: "May underperform during trend accelerations (EMA-50 lags); could produce concentrated Mag7 exposure in tech-led bull regimes."
possible_failure_modes:
  - "Regime RISK_OFF: EMA-50 slope becomes noisy; sign(slope) adds variance without alpha"
  - "QQQ itself is concentrated in Mag7 → rs_vs_qqq becomes zero for Mag7 symbols"
  - "Lookahead risk if factor computed using end-of-day EMA that includes T-day close"
novelty_vs_existing_factors: |
  Similar to rs_vs_spy_63d (ρ estimate: +0.4 to +0.6 since QQQ ≈ SPY
  in tech-heavy universes) but conditioned on trend slope. Incremental
  edge hypothesis vs raw rs_vs_spy is that sign(slope) filters out
  mean-reverting late-cycle outperformers.
```

## After receiving candidate YAML → mandatory funnel

See `docs/llm_funnel_checklist.md` for the 6-step mandatory sequence.

## DO NOT

- Do not return verdict=KEEP. Final decision belongs to human.
- Do not skip fields in the YAML schema. Missing fields → shape-check
  fails in `scripts/llm_factor_propose.py`.
- Do not propose a factor whose formula you cannot explain economically.
  "Data-mined curve-fit" is an automatic REJECT reason.
- Do not propose factors that require external APIs / data not in the
  repo. `generate_all_factors()` only has access to the price/volume
  panel + benchmark series; constrain yourself accordingly.
