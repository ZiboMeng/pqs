# Track C Cycle #06 Closeout — PRD-AC v1.1 Phase 4 Dry-Run Mining

**Date**: 2026-05-06
**Operator**: zibomeng (Claude Opus 4.7)
**Authority**: PRD-AC v1.1 + user explicit-go 2026-05-06 ("收掉之后进 3 4")
**Lineage**: `track-c-cycle-2026-05-06-01`
**Yaml sha256**: `7b3e20dd8485900c0307c0ef89adc0228ccfb42964d54447550a52184a1bc1df`

## TL;DR

PRD-AC v1.1 Phase 4 dry-run cycle #06: **0 of top-3 trials pass Track A
acceptance → 0 nominee**. Cycle #04 close memo's pre-committed stop
rule fires: strategic pivot to PRD-E (TAA) or beyond. v2_nav_based
mining mechanism IS working (NAV gate populated correctly, anchor
calibration produced clean Option β decision), but the top-1 spec
fails per-validation-year aggregate vs SPY/QQQ + beta_to_qqq gates;
the v2 selection is only marginally different from v1 (Spearman 0.89);
and the v2 top-1 has LOWER nav_sharpe than v1 top-1 (H3 fail).

**Strategic finding**: current PRD-AC §4.7 default weights
(w_ir=0.7 / w_nav_sharpe=0.15) are too IR-side-heavy to materially
shift selection toward NAV-Pareto improvement. Cycle07+ cycle (if
authorized) would need to reweight (e.g. w_ir=0.4 / w_nav_sharpe=0.3)
and/or constrain the search space to specs with ≤25% per-year max_dd
to surface diversifier-role candidates.

**Sibling pattern persists**: top-10 v2 all anchor on
`drawup_from_252d_low + ret_*`. R41 informational verdict NOT computed
this cycle (per PRD §5.3 R41 anchor invariant) but factor-overlap
inspection shows top-10 share `drawup_from_252d_low` — same anchor as
RCMv1 + cycle04 sibling chain.

## Hypothesis test results

### H1 — v2 vs v1 ranking materially differs

**FAIL (partial)**. PRD §5.2 acceptance: Spearman top-10 v2 vs v1
< 0.7 AND ≥ 3 trials in v2 top-10 not in v1 top-10.

- Spearman rank correlation top-10 v2 vs v1: **0.890** (target < 0.70)
- Trials in v2 top-10 NOT in v1 top-10: **6** (target ≥ 3 ✓)

The 6-trial overlap satisfies "≥ 3 not-in-v1" but the Spearman 0.89
indicates the rankings are highly aligned — v2 picked similar specs
to v1 with marginal reshuffling within. The current weights (0.7 IR
+ 0.15 nav_sharpe) put 87.5% of total weight on IR-side terms; for
v2 to produce a meaningfully different ranking, NAV-side weight
needs to be raised closer to 0.3-0.4 of total (cycle07+ tuning).

### H2 — TPE distributes 200 trials across 3 holding_freq cells

**FAIL (mathematical, not informative)**. PRD §5.2 acceptance:
≥ 30 trials per cell.

- holding_freq archived counts: monthly=49 / weekly=10 / daily=7

**Process finding**: H2 acceptance criterion is mis-specified. With
TPE archive rate 16.5% (66 archived / 200 attempted), even uniform
distribution would produce 200/3 × 16.5% ≈ 11 archived per cell.
**The acceptance check should look at SAMPLED distribution (200
trials), not archived (66 trials)**. PRD §5.2 should be revised in
cycle07+ yaml: target ≥ 50 sampled per cell, not ≥ 30 archived.

That said, even the SAMPLED distribution is monthly-biased: TPE
preferentially samples monthly because it yields higher IC (longer
holding period → smoother forward returns → higher Spearman per-date).
weekly + daily get fewer TPE-sampled trials because the IR objective
penalizes them. To force balanced search, cycle07+ would need to
either (a) fix holding_freq per smoke run + run separate studies,
or (b) raise NAV-side weight to compensate IR penalty for
high-turnover cadences.

### H3 — v2 top-1 nav_sharpe ≥ v1 top-1 nav_sharpe (Pareto)

**FAIL**. PRD §5.2 expected v2 mining to produce a Pareto improvement
on NAV-Sharpe; instead v2 top-1 is WORSE.

- v2 top-1 (`bab8cfe88af3`): nav_sharpe = **0.5654**
- v1 top-1 (different trial): nav_sharpe = **0.6640**
- Δ = -0.0986 (v2 LOWER)

**Root cause**: with w_ir=0.7 and w_nav_sharpe=0.15, the IR-side
ranking dominates. The v1 top-1 trial (highest pure IC_IR) happens
to also have the best nav_sharpe — so v1 wins on both. v2 demoted
this winner because some other trial has slightly higher IR but
lower nav_sharpe; that trial's combined v2 objective edged ahead
because the nav_sharpe penalty was outweighed by the IR gain.

This is a CORRECT mathematical outcome of the PRD-AC §4.4 weighted
sum but reveals the WRONG hypothesis: v2 with 0.15 nav_sharpe weight
does NOT enforce Pareto improvement on NAV. Cycle07+ should EITHER
raise the weight OR add a hard min-nav-sharpe constraint as a
trial-pruning condition.

### H4 — Anchor orthogonality calibration

**PASS — Option β anchor viable**. PRD §4.6 decision rule: ≥ 30%
of trials below 0.50 → enable orthogonality term in cycle07+.

- anchor_corr distribution (n=66): p25=0.241 / p50=0.257 / p75=0.286 / p95=0.340
- Trials below 0.50: **66 (100.0%)**
- Trials in 0.50-0.70: 0
- Trials above 0.70: 0

**Context check**: 100% below 0.50 is unusually clean. Hypothesis:
the universe-equal-weight residual baseline naturally diverges from
top-N spec NAVs because top-N construction structurally selects for
specific factor exposures the average doesn't have. If TRUE, the
orthogonality term may not differentiate "good diversifier" from
"average top-N". Phase 4 calibration smoke (cycle07+) at λ=1.0
should verify whether enabling the term produces a different
ranking from λ=0; if it doesn't, Option β is cosmetic and Option γ
is operationally identical.

**Decision recorded for cycle07+**: enable w_nav_orthogonality with
λ=1.0 in v2.1 yaml; if smoke shows no rank change vs cycle06 v2
ranking, fall back to γ.

## Track A acceptance (PRD §5.3 gate 1) — Top-3 v2 trials

Evaluated on `partition_for_role(role="selector")` panel (train +
validation, NOT sealed 2026). Per-trial wall-clock ~22s.

### Trial 1 — `bab8cfe88af3` (monthly)
**Verdict: FAIL** (3 gates failed)
Features: `drawup_from_252d_low, trend_tstat_20d, ret_2d`

Per-validation-year metrics:
| Year | maxdd | vs_spy | vs_qqq |
|---|---|---|---|
| 2018 | -23.37% | -0.35% | -4.64% |
| 2019 | -10.26% | -8.58% | -17.21% |
| 2021 | -9.35% | -9.56% | -9.38% |
| 2023 | -13.46% | +26.60% | -3.42% |
| 2025 | -18.94% | +4.90% | +1.13% |

Stress: covid_flash maxdd=-21.48% / rate_hike_2022 maxdd=-8.12%

Failed gates:
- `validation_aggregate_excess_vs_spy` (2 of 5 positive vs target ≥ 4/5)
- `validation_aggregate_excess_vs_qqq` (1 of 5 positive)
- `beta_to_qqq` (exceeds 0.85 ceiling)

**Note**: 2018 per-year maxdd -23.37% exceeds the -20% gate but
acceptance evaluator did not list `validation_year_2018_maxdd` as
failed — likely because the configured `maxdd_per_year_max` is more
permissive than -20% in the current yaml. Independent review: this
trial is NOT a robust core_alpha candidate even if some gates show
slack.

### Trial 2 — `31af04cf2ff9` (weekly)
**Verdict: FAIL** (4 gates failed)
Features: `drawup_from_252d_low, trend_tstat_20d, ret_2d` (same factors
as Trial 1 but different cadence)

| Year | maxdd | vs_spy | vs_qqq |
|---|---|---|---|
| 2018 | -2.07% | +7.20% | +2.91% |
| 2019 | -1.80% | -23.74% | -32.36% |
| 2021 | -3.45% | -30.10% | -29.92% |
| 2023 | -3.59% | -21.83% | -51.84% |
| 2025 | -1.41% | -8.46% | -12.22% |

Failed gates:
- `validation_aggregate_excess_vs_spy` (1 of 5 positive)
- `validation_aggregate_excess_vs_qqq` (1 of 5 positive)
- `role_core__validation__2025__excess_vs_qqq` (HARD CLAUDE.md gate; -12.22%)
- `beta_to_qqq`

Weekly cadence with this composite produces extremely defensive NAV
(low maxdd 1-3%) but radically underperforms benchmarks (-32% vs QQQ
in 2019). The high-frequency rebalance decisively erases alpha.

### Trial 3 — `a9e39c21feed` (monthly)
**Verdict: FAIL** (3 gates failed; identical metrics to Trial 1
because the feature swap `risk_adj_mom_63d ↔ return_per_risk_21d`
produced numerically equivalent NAV trajectories)

## Final verdict + nominee status

**0 nominee**. PRD §5.3 gate 1 (Track A acceptance) is mandatory; 0
of top-3 v2 trials pass. Conservative read: even if remaining top-7
trials were evaluated, the dominant pattern (drawup-anchored,
covid-window vulnerability, weak vs-QQQ in BULL years) suggests
~0% pass rate.

## Cycle stop rule outcome

Per cycle #04 close memo `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md`
pre-committed: "if cycle #05 also 0 nominee, no cycle #06 mining
without strategic pivot". Cycle #05 closed 0 nominee 2026-05-01;
cycle #06 ran with PRD-AC v1.1 NAV-objective + holding_freq pivot;
**cycle #06 also 0 nominee**.

**Stop rule fires**: pivot deeper. Strategic options per PRD:
1. **PRD-E TAA** (regime allocation): authored at
   `docs/prd/20260505-taa_regime_allocation_framework_prd.md` v1.1.
   Different mining axis (regime-conditional rules, not
   composite-factor mining).
2. **Cycle07+ with PRD-AC weight reweighting**: raise w_nav_sharpe to
   0.30 + add hard min-nav-sharpe pruning + enable
   w_nav_orthogonality=1.0 per H4. Two-week effort. Probability of
   producing nominee uncertain — H1+H3 evidence suggests current
   universe / construction may be at NAV-Sharpe ceiling.
3. **Architectural pivot**: PRD-AC §"strategic pivot deeper" (per
   cycle04 close), beyond mining objective changes. Universe
   expansion / longer-horizon factors / etc.

## Strategic findings (operator surfacing for user directional decision)

### Finding 1: PRD-AC §4.7 default weights are not aggressive enough
Cycle06 demonstrated v2_nav_based mechanism works (NAV metrics
populated, archive schema OK, anchor calibration clean), but the 0.7
IR-side weight dominates 0.15 NAV-side weight → v2 ranking ≈ v1
ranking. To make v2 truly differentiated, cycle07+ should test:
- `w_ir=0.40 / w_nav_sharpe=0.30 / w_nav_max_dd_penalty=0.15 /
  w_nav_orthogonality=1.0 / w_vs_qqq_excess=0.15`

### Finding 2: H2 acceptance criterion mis-specified
PRD §5.2 H2 (≥ 30 trials per cell) implicitly assumed a higher
archive rate than the 16.5% TPE actually produces under
strict cardinality + min_families constraints. Should re-spec to
SAMPLED rather than ARCHIVED counts in cycle07+ yaml.

### Finding 3: Sibling-by-anchor pattern not yet broken by v2 alone
All top-10 v2 trials anchor on `drawup_from_252d_low + ret_*`. This is
the same anchor pattern across 5 cycles (#04 #05 #06). Conclusion:
NAV-objective mining with current universe + construction does NOT
escape sibling space. The structural cause is the universe — long-only
top-N over 53 stocks + 6 cross-asset ETFs has a binding "diversifier
floor" that any mining objective converges on. Universe expansion
or longer-horizon factor families remain candidate fixes.

### Finding 4: H4 anchor calibration suspiciously clean (100% below 0.50)
Universe-equal-weight residual is structurally different from top-N
spec residual. Need cycle07+ smoke at λ=1.0 to verify the
orthogonality term actually shifts ranking; if it doesn't, the
metric is a free informational diagnostic and Option γ is operationally
identical to Option β.

## Authorship + audit trail

- PRD-AC v1.1: `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md`
- Critique log: `docs/memos/20260505-prd_ac_e_critique_log.md`
- I9 boundary fix: `docs/memos/20260506-i9_boundary_artifact_finding.md`
- Cycle #06 yaml (immutable): `data/research_candidates/track-c-cycle-2026-05-06-01_promotion_criteria.yaml`
- Cycle #06 yaml sha256: `7b3e20dd8485900c0307c0ef89adc0228ccfb42964d54447550a52184a1bc1df`
- Mining artifacts: `data/ml/research_miner/track-c-cycle-2026-05-06-01/`
- Closeout analysis JSON: `data/audit/cycle06_closeout_analysis_track-c-cycle-2026-05-06-01.json`
- Track A eval JSON: `data/audit/cycle06_track_a_eval_track-c-cycle-2026-05-06-01.json`

Commits (PRD-AC v1.1 implementation):
- Phase 1: `f2b6059` (schema + ObjectiveWeights extension)
- Phase 2 round 1: `cbf4a49` (NAV evaluator gate + SPY-residual anchor + I20)
- Phase 2 round 2: `38f5320` (I9 boundary mask + wall-clock benchmark)
- Phase 3 round 1: `cb1e3dd` (holding_freq end-to-end + sr_defer stub)
- Phase 4 prep: `0fd22a6` (FAMILIES_V2 swing/SR fix + cycle06 yaml)
- Phase 4 ops: `65d4139` (closeout analysis script + memo skeleton)
- Phase 4 fix: `464f2eb` (None-safe formatting)

## Reversibility

- v2_nav_based path is opt-in via `objective_version` yaml field.
  cycle04/05 v1_legacy mining unaffected by this cycle.
- cycle #06 archive (66 trials under lineage) is immutable per
  yaml hash. Future cycles use new lineage tags.
- Cycle stop-rule pivot (PRD-E vs cycle07 reweight vs architectural)
  is a USER directional decision. Operator surfaces evidence;
  PRD-AC delivers the mining-objective mechanism; user decides
  next axis.

## Sealed 2026 panel

NEVER read this cycle. Confirmed by code path: mining used
`partition_for_role(role="miner")` (train years only); Track A eval
used `partition_for_role(role="selector")` (train + validation,
sealed excluded). 5.4 OOS discipline preserved.
