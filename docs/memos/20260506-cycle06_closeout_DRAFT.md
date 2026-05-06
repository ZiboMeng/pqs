# Track C Cycle #06 Closeout — PRD-AC v1.1 Phase 4 Dry-Run Mining

**Status**: DRAFT — mining in progress (background task `bxxp067eh`,
estimated 65-min wall-clock). Numerical results section will be filled
in once mining + `cycle06_closeout_analysis.py` complete.

**Date**: 2026-05-06
**Operator**: zibomeng (Claude Opus 4.7)
**Authority**: PRD-AC v1.1 + user explicit-go 2026-05-06 ("收掉之后进 3 4")
**Lineage**: `track-c-cycle-2026-05-06-01`
**Yaml sha256**: `7b3e20dd8485900c0307c0ef89adc0228ccfb42964d54447550a52184a1bc1df`

## TL;DR

PRD-AC v1.1 Phase 4 dry-run cycle #06: first v2_nav_based mining run.
200-trial TPE on partition_for_role(role="miner") panel + cap_aware_
cross_asset construction (cycle #04 config retained for direct
comparison). Single-axis differential vs cycle #04: NAV-based objective
+ holding_freq search dim. Results inform whether v2 changes mining
selection meaningfully (H1) and whether SPY-residual anchor is viable
for cycle07+ (H4).

[FILL IN POST-MINING] Verdict: ___ nominee.

## Pre-mining preflight (this section is final)

### Phase 2 round 2 wall-clock benchmark
5 archived cycle04 specs replayed via evaluate_composite NAV path on
partition_for_role(miner) panel:
- median 19.36s/trial (p95 19.86s)
- 200-trial smoke estimate: ~64.5 min wall-clock
- Verdict PASS (≤ 20s PRD §6 Phase 2 target)

Source: `data/audit/wall_clock_benchmark_track-c-cycle-2026-05-01-04.json`

### Phase 2 round 2 I9 boundary verification
Cycle04 top-1 trial `ddc2896f9d8e` revealed +10.36% NAV jump at
2022-12-31 → 2024-01-02 boundary (positions held across 2023
validation gap). Fixed via `mask_train_boundary_returns` + masked-
metric recompute in `core/mining/nav_objective.py`. Pre-fix sharpe=
1.0083 → post-fix sharpe=0.9740 (the +0.034 contribution from the gap-
day was correctly excluded).

Source: `docs/memos/20260506-i9_boundary_artifact_finding.md`

### Phase 4 wiring smoke (20-trial smoke yaml)
3/20 trials archived with finite nav_* metrics:
- Top trial nav_sharpe=0.66, nav_max_dd=-25.6%, nav_corr_anchor=0.21,
  nav_vs_qqq_excess=+1.90
- Validates yaml→runner→ResearchMiner→evaluate_composite NAV gate→
  archive end-to-end

Source: `data/research_candidates/track-c-cycle-2026-05-06-smoke_promotion_criteria.yaml`

## Hypothesis tests (filled post-mining)

### H1 — v2 vs v1 ranking materially differs

[FILL IN] Spearman rank correlation top-10 v2 vs v1: ___
[FILL IN] # trials in v2 top-10 NOT in v1 top-10: ___
[FILL IN] PRD §5.2 acceptance: Spearman < 0.7 AND ≥ 3 not-in-v1
[FILL IN] Verdict: PASS / FAIL

### H2 — TPE distributes 200 trials across 3 holding_freq cells

[FILL IN] holding_freq counts: monthly=__, weekly=__, daily=__
[FILL IN] PRD §5.2 acceptance: ≥ 30 per cell
[FILL IN] Verdict: PASS / FAIL

### H3 — v2 top-1 nav_sharpe ≥ v1 top-1 nav_sharpe (Pareto check)

[FILL IN] v2 top-1 nav_sharpe: ___
[FILL IN] v1 top-1 nav_sharpe: ___
[FILL IN] Verdict: PASS / FAIL

### H4 — Anchor orthogonality calibration

[FILL IN] anchor_corr distribution (n_finite=__):
  p25=__  p50=__  p75=__  p95=__
[FILL IN] # trials below 0.50: ___ (__%)
[FILL IN] Decision rule:
  ≥30% below 0.50 → Option β viable; enable w_nav_orthogonality in cycle07+
  <10% below 0.50 → Option γ fallback; skip orthogonality term cycle07+
  10-30% → directional; user decision
[FILL IN] H4 decision: ___

## Track A acceptance (PRD §5.3 gate 1) — top-N v2 trials

For each of the top-10 v2 trials, evaluate against
`config/temporal_split.yaml::alternating_regime_holdout_v1`:

[FILL IN per trial]
- Per-validation-year vs SPY positive ≥ 4/5 (HARD)
- Per-validation-year MaxDD ≤ 20% (HARD)
- 2025 vs SPY positive (HARD per CLAUDE.md core role gate)
- Stress slice MaxDD ≤ 25% (covid_flash + rate_hike_2022)
- Cost robustness 2x multiplier (HARD)
- Concentration top1 ≤ 0.40 + top3 ≤ 0.70 (HARD)
- Beta to QQQ ≤ 0.85 (HARD)

## Phase 4 smoke deliverables (PRD §5.3 gate 2)

[FILL IN]
- v2 NAV-Sharpe ≥ v1 top-1 NAV-Sharpe (H3 verdict)
- v2 NAV-vs-qqq excess > 0 (full period)
- Validation years vs_qqq window-mean > 0 (per CLAUDE.md QQQ rule)

## R41 informational sibling-by-NAV (PRD §5.3 + I18 fix)

[FILL IN per top trial]
- Pooled raw Pearson vs RCMv1: ___
- Pooled raw Pearson vs Cand-2: ___
- R41 verdict: Tier 1 / Tier 1-conditional / Tier 2 (sibling-by-NAV) /
  Tier 5
- I18 decision: Tier 2 STILL counts as nominee; closeout surfaces
  R41 informational, user decides Track D promotion downstream.

## Final verdict + nominee status

[FILL IN]
- Track A acceptance: __ of __ top-10 trials pass all hard gates
- Phase 4 smoke: __ of those pass H3 (v2 ≥ v1) AND H4 calibration consistent
- Final nominee count: ___

## Cycle stop rule outcome

Per cycle #04 close memo pre-committed stop rule:
- 0 nominee in cycle #06 → strategic pivot per PRD-E (TAA) or beyond
- 1+ nominee → forward observation freeze candidate (separate decision)

[FILL IN] Stop rule verdict: ___

## Authorship + audit trail

- PRD-AC v1.1: `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md`
- Critique log: `docs/memos/20260505-prd_ac_e_critique_log.md`
- I9 boundary fix: `docs/memos/20260506-i9_boundary_artifact_finding.md`
- Cycle #06 yaml (immutable): `data/research_candidates/track-c-cycle-2026-05-06-01_promotion_criteria.yaml`
- Mining artifacts: `data/ml/research_miner/track-c-cycle-2026-05-06-01/`
- Closeout analysis JSON: `data/audit/cycle06_closeout_analysis_track-c-cycle-2026-05-06-01.json`
- Phase 1 commit: `f2b6059`
- Phase 2 round 1 commit: `cbf4a49`
- Phase 2 round 2 commit: `38f5320`
- Phase 3 round 1 commit: `cb1e3dd`
- Phase 4 prep commit: `0fd22a6`

## Reversibility

If cycle #06 produces 0 nominee or fails Track A acceptance widely:
- v2_nav_based code path is opt-in (objective_version yaml field);
  cycle04/05 v1_legacy mining unaffected
- Mining-objective design can be re-tuned via cycle07 yaml without
  touching cycle #06 archive (immutable per yaml hash)
- Phase 3 round 2 (SR-defer integration) authorization decision
  factors in cycle #06 evidence
