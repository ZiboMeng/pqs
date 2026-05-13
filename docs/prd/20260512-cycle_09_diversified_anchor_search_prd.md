# PRD — cycle #09 diversified-anchor search (cycle04-08 sibling escape)

**Date**: 2026-05-12
**Status**: DRAFT — pre-register immutable criteria; ready to fire when authorized
**Lineage**: `track-c-cycle-2026-XX-XX-09`
**Independence**: This cycle is INDEPENDENT of Trial 9 forward verdict. Per
[[feedback_parallel_alpha_mining_default]], alpha mining is a base activity.
Trial 9 verdict only decides fleet composition; cycle #09 produces standalone
candidate regardless.

---

## §1 Background

cycle04-08 produced 0 nominees with a clear sibling-by-NAV pattern:
- drawup_from_252d_low + amihud_20d anchored construction
- monthly rebalance + global top-N over 78-stock universe
- Pooled raw NAV Pearson 0.66-0.95 vs RCMv1/Cand-2/Cycle03-top

Banning `drawup` + `amihud` factors (cycle05) didn't break the sibling
geometry — construction collapse is the binding constraint, not factors.

**PRD 20260512 expansion ships 95 new factors across 10 new families
(G through Q)** — providing genuinely diverse anchor candidates that
were unreachable in cycle04-08:
- Bucket A T1 (24 OHLCV): higher moments, calendar, BAB, anchor
- Bucket B (41 fundamental from SEC EDGAR): Piotroski / Magic /
  Beneish / Altman / Ohlson / FCF / capital return / growth
- Bucket C (5 sector-relative)
- Macro (6 FRED)
- Event window (4 FOMC/CPI/NFP)
- Signal-confirmation multi-bar (5)

**Z1 cross-IC diagnostic STRICT train years 2009-2017+2020+2022+2024
(no validation/sealed touched, per `20260512-z1_factor_diagnostics_synthesis_strict.md`)** identifies high-IR anchor candidates:
- `beneish_aqi` IR -5.83 (use reverse direction = good asset quality)
- `sales_acceleration` IR -5.16 (use reverse = growth deceleration → up)
- `rd_intensity_ttm` IR +4.64 (R&D intensity → up)
- `sector_dispersion_std_20d` IR +4.03 (sector dispersion → up)
- `mom_126d` IR +4.38 (legacy momentum)
NOTE: IR > 5 may be spurious from sparse train sample — recommend
combining 3 factors in IR ∈ [3, 5] range for robustness.

---

## §2 Design — break sibling geometry by REQUIRING new-family anchors

**Single-axis diff vs cycle04-08**: cycle #09 yaml SHALL require
composite candidates to draw ≥ 1 anchor factor from families G/I/K/L/M/N/O/P
(new factor library), AND drop legacy anchor candidates drawup_from_252d_low
+ amihud_20d.

This is the cycle04 stop-rule pivot direction: "strategy type changes" =
new factor sources, not new factor names of same construction.

---

## §3 Pre-registered immutable criteria (yaml-locked)

To be saved at:
`data/research_candidates/track-c-cycle-2026-05-XX-09_promotion_criteria.yaml`

```yaml
cycle_id: track-c-cycle-2026-05-XX-09
lineage_tag: track-c-cycle-2026-05-XX-09
created_at: 2026-05-12
purpose: |
  cycle04-08 sibling escape via 95-factor library expansion. Search
  for archetype that simultaneously:
    (a) passes Track A acceptance per temporal_split_v2.yaml
    (b) has raw NAV Pearson < 0.85 vs RCMv1 / Cand-2 / Trial 9
        (3-way constraint)
    (c) anchors ≥ 1 factor from new families G-P

factor_registry_pool: RESEARCH_FACTORS  # full 162 reachable

mining_config:
  n_trials: 200
  cardinality: 3
  min_families: 3
  max_per_family: 2
  composite_weighting: tpe_normalized
  sampler: tpe
  horizon: 21
  lag: 1
  # Anchor bans (cycle04-08 sibling escape):
  explicit_exclusions:
    - drawup_from_252d_low  # cycle04-08 anchor
    - amihud_20d            # cycle04-08 anchor
    # 3 intraday factors require 60m bars (data-dependency)
    - intraday_autocorr_21d
    - intraday_vol_ratio_21d
    - realized_vol_60m_21d

construction:
  cap_aware: true
  cluster_cap: 0.20
  max_single: 0.10
  top_n: 10
  rebalance: monthly  # also test weekly variant
  asset_class_caps:
    equities: 0.70
    bonds:    0.40
    commodities: 0.20
    cash_anchor: 0.30

acceptance_gates:
  # Track A acceptance per temporal_split_v2 (CLAUDE.md unchanged)
  G1_per_validation_year_vs_spy: hard  # 2018/19/21/23/25
  G2_2025_holdout_vs_spy: hard
  G3_stress_slice_maxdd: hard           # ≤ -25%
  G4_per_year_maxdd: hard               # ≤ -20%
  G5_bull_beta_to_spy: hard             # ≤ 0.85
  G6_full_calmar_vs_spy: hard
  G7_full_maxdd: hard                   # ≤ -20%
  G8_concentration: hard                # M12 top1≤0.40 top3≤0.70

  # NEW for cycle #09:
  G_anti_sibling_nav:
    type: hard
    pairwise_raw_pearson_max: 0.85
    pairs:
      - rcm_v1_defensive_composite_01
      - candidate_2_orthogonal_01
      - trial9_diversifier_001
    window: 2009-2024 (train years only)

  G_new_family_anchor:
    type: hard
    description: |
      composite_spec.features MUST include ≥1 factor from new families
      G/I/K/L/M/N/O/P. The pre-Z1 list:
      [obv_norm_20d, chaikin_money_flow_20d, up_vol_ratio_20d,
       coskew_60d_spy, bab_score_60d, nearness_to_52w_high,
       piotroski_f_score, magic_formula_rank_composite,
       fcf_to_assets_ttm, ohlson_o_score, beneish_m_score,
       altman_z_score, revenue_growth_yoy, sector_rel_mom_20d,
       yield_curve_10y_2y, vix_zscore_60d, ...]
      (full list = union of FAMILY_G..Q.factors).

immutability_contract:
  yaml_sha256_locked_at: <to-fill-at-creation>
  no_retroactive_softening: true
  stop_rule_post_cycle:
    if_0_nominee: |
      analyze WHICH new-family anchor candidates produced highest IR;
      decide whether to (a) reweight objective toward those,
      (b) fundamentally pivot to alt-archetype (Z3 PRDs),
      (c) declare 162-factor library exhausted at this construction
      and need cross-asset / intraday / different rebalance cadence.

evidence_pack:
  - z1_factor_diagnostics_memo
  - track_a_acceptance_score
  - anti_sibling_nav_correlation_table
  - factor_overlap_per_role_table

sealed_panel_one_shot: |
  This cycle consumes one mining of train + validation panel via
  Track A acceptance. Sealed 2026 panel NOT TOUCHED (Track A's
  validation years are 2018/19/21/23/25; sealed is 2026 single-shot
  per CLAUDE.md).
```

---

## §4 Why this is independent of Trial 9 verdict

| Trial 9 verdict | cycle #09 next-step |
|---|---|
| GREEN (TD60 ~2026-08-06) | cycle #09 nominee + trial 9 → 2-candidate fleet (if both pass G_anti_sibling vs each other) |
| YELLOW | cycle #09 nominee (if any) holds; continue trial 9 to TD90 |
| RED | cycle #09 nominee (if any) becomes the standalone candidate; trial 9 retires |

In ALL 3 cases, **cycle #09 produces standalone evidence**. Trial 9 verdict
shifts only the fleet construction logic, not the cycle #09 work.

---

## §5 Fire timing

cycle #09 can fire as soon as:
1. Z1 cross-IC diagnostic complete (parallel run today, results inform §3
   archetype but don't block PRD lock-in)
2. PRD yaml committed + sha256-locked
3. User explicit-go (governance gate)

**Recommend**: fire immediately after Z1 results land. No wait for Trial 9.

---

## §6 Reversibility

If cycle #09 also 0 nominee:
- this is the SECOND consecutive 0-nominee with broad factor library
- triggers harder pivot: alt-archetype PRDs (Z3) — intraday reversal /
  event-driven / news-sentiment / cross-asset rebalance
- does NOT trigger PQS shutdown; mining base activity continues
