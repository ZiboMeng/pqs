# Track C controlled mining cycle #01 — plan

> **Renamed 2026-04-30 R2** (per external reviewer §7): originally
> "dry-run plan". 200 trials TPE + pre-registered immutable criteria
> + closeout discipline + no retroactive softening = formal cycle,
> not smoke test. Calling it "dry-run" understated the research-
> contamination risk of looking-back-after-results. If a true smoke
> test is needed first, do 30-50 trials in a separate cycle.

**Date:** 2026-04-30
**Status:** Plan only. Execution gated on (a) external-reviewer or
codex signoff on the corrected Track C evidence-pack template
(`docs/templates/track_c_evidence_pack_template.md`, post-R30 fixes
landed in `main 1a24033`) PLUS the §4.6 NAV-orthogonality + §4.7
economic-assumption-flag additions (E.MV per
`docs/memos/20260430-concerns_abE_proposed_solutions.md` — pending
separate ship) AND (b) NAV-orthogonality threshold consistency
patched in all three places (this plan §3, the correlation memo
§5 action items, the diagnostic script `classify()`) — tiered
0.50 / 0.70 / 0.85 per audit-R2 + reviewer §3.

**Owner:** Claude
**Lineage:** `track-c-cycle-2026-04-30-01` — first Track C cycle
under the new `alternating_regime_holdout_v1` temporal split.

---

## 0. Goal and falsifiability

**Goal.** Answer one question: *Under the current Track A temporal
split + the post-step3b honest data panel + the new acceptance
gates, does any composite pass acceptance?*

**Falsifiable outcome — action map** (per reviewer §8 2026-04-30:
prior priors are too weak to assign probabilities; pre-commit to
the action triggered by each outcome instead):

| Outcome | Action |
|---------|--------|
| 0 nominees | Cycle closes 0-nominee. Closeout memo records "gate calibration vs post-step3b panel" hypothesis AND "alpha source exhaustion on this universe" hypothesis. NEITHER conclusion is auto-correct from a single cycle; treat as evidence-collection. New PRD opens a new lineage if either hypothesis warrants follow-up. NO retroactive gate softening. |
| ≥ 1 nominee passes Track A acceptance (validation 5 years + stress + concentration + cost + role) | Each candidate runs the §3-prescribed NAV-correlation diagnostic vs RCMv1 + Cand-2 (raw Pearson + residual Pearson + drawdown overlap + holdings overlap). Each candidate also runs §4.7 economic-assumption flags. Until that completes, candidate is "candidate pending economic-invariant pack" — NOT yet a "nominee" (per reviewer §5.1). |
| Multiple candidates pass Track A acceptance | Run NAV-correlation matrix among candidates first. If ≥ 2 candidates show pooled raw Pearson ≥ 0.70 with each other or vs RCMv1 / Cand-2 → high probability of duplicate risk exposure; closeout memo flags this and constrains nomination to ≤ 1 per cluster. |
| Any candidate passes Track A acceptance + economic-flag pack clean + NAV-corr `true_diversifier` (raw < 0.50 AND residual < 0.50) vs every active candidate | Becomes "nominee". Evidence pack drafted. Forward init still gated on Concern B Tier 1 ship. |
| Any candidate passes acceptance + NAV-corr in `partial_diversifier` (0.50-0.70) range | Becomes "candidate" not "nominee" — needs reviewer judgment per criteria YAML. Evidence pack documents the partial-diversifier reason explicitly (e.g. residual-corr drop pattern from §2.7 of correlation memo). |
| Any candidate passes acceptance but NAV-corr ≥ 0.70 vs RCMv1 or Cand-2 | Cannot claim diversifier role. Could still be "core-additive" if raw < 0.85. ≥ 0.85 → not eligible at all (Step 5 reject). Closeout records this as evidence the new framework is finding alpha but not diversification. |

> **Hard constraint.** This cycle is **not** allowed to retroactively
> soften acceptance criteria based on observed results. If gates
> turn out wrong, the cycle closes under its original criteria and
> a fresh PRD opens a new lineage. The 2026-04-26 cycle close memo
> is the precedent.

---

## 1. Pre-conditions (verify before kick-off)

| # | Check | How | Required state |
|---|-------|-----|----------------|
| 1 | Template R30 fixes landed | `git log --oneline -5 main -- docs/templates/track_c_evidence_pack_template.md` | shows `1a24033` |
| 2 | External-reviewer / codex signoff on template | review log Round 32+ has explicit "template accepted for Track C use" | required before mining |
| 3 | `config/temporal_split.yaml` is `alternating_regime_holdout_v1` and immutable | `grep "split_name" config/temporal_split.yaml` | matches |
| 4 | RCM archive present and writable | `ls data/mining/rcm_archive.db` | exists |
| 5 | Pre-registered criteria YAML drafted and committed BEFORE first trial | `data/research_candidates/track-c-cycle-2026-04-30-01_promotion_criteria.yaml` | git-tracked |
| 6 | Concerns A/B/E concern memo merged | `git log --oneline -1 -- docs/memos/20260430-pre_track_c_strategic_concerns.md` | exists |
| 7 | NAV-correlation evidence committed | `git log --oneline -1 -- docs/memos/20260430-rcmv1_cand2_realized_correlation.md` | exists |
| 8 | RCMv1 + Cand-2 both flagged as legacy / NAV-failed-diversifier | `grep -l realized_nav_correlation_status data/research_candidates/` | both candidate yamls flagged |

---

## 2. Mining parameters

| Param | Value | Source |
|-------|-------|--------|
| Lineage tag | `track-c-cycle-2026-04-30-01` | this memo |
| Split name | `alternating_regime_holdout_v1` | `config/temporal_split.yaml` (immutable) |
| Train years | 2009-2017 + 2020 + 2022 + 2024 | Track A PRD §4 |
| Validation years | 2018, 2019, 2021, 2023, 2025 (2025 hard on `core` role) | Track A PRD §4 |
| Sealed (DO NOT TOUCH) | 2026 | Track A PRD §4 |
| Stress slices (borrowed for sanity only) | `covid_flash`, `rate_hike_2022` | Track A PRD §4 |
| Universe | post-step3b 78 symbols (BRK-B dropped per round-3 close) | `data/baseline/latest.json` panel |
| Optuna n_trials | 200 (TPE, deterministic seed) | matches 04-26 cycle for comparability |
| Composite cardinality | 3 factors equal-weight (matches Cand-2 pattern; PRD §5.5) | research_miner |
| Lag | 1 bar (round-15 leak-safe semantic) | Track A code |
| Forward horizon | 21d cc | Track A acceptance |
| Acceptance evaluator | `temporal_split_acceptance.evaluate(...)` 17 gates | `core/research/temporal_split_acceptance.py` |
| Roles to mine | `core` (run separately for `diversifier` only if `core` succeeds) | Track A PRD §C5 |
| Pre-registered criteria YAML | committed before first trial; SHA-256 frozen | mandatory |
| Mining commit | recorded in cycle-init commit | mandatory |
| Mining run script | `scripts/run_research_miner.py --temporal-split --role=core --lineage-tag=track-c-cycle-2026-04-30-01` | existing CLI |
| Result archive | `data/ml/research_miner/track-c-cycle-2026-04-30-01/` | new directory |

**Reverse-validation sentinel.** Pre-registered criteria YAML must
contain at least one criterion designed to FAIL (e.g.
`watchlist_total_share <= 0.30` — same as the gate that closed the
04-26 cycle). If the cycle's top trial fails it, the cycle closes
0-nominee under the immutability rule. Sentinel must be reverse-
validated post-fix to confirm it does fail when violated.

---

## 3. Pre-registered criteria YAML — draft for review

Path: `data/research_candidates/track-c-cycle-2026-04-30-01_promotion_criteria.yaml`

```yaml
lineage_tag: track-c-cycle-2026-04-30-01
authoring_date: 2026-04-30
split_name: alternating_regime_holdout_v1
role: core
authoring_commit: <git sha at first commit>
sealed_until: 2027-01-01

# All criteria below are immutable from the moment the first Optuna
# trial starts. Any edit starts a new lineage; the current cycle
# closes under its original criteria.

criteria:
  # All 17 Track A acceptance gates must pass
  track_a_acceptance:
    evaluator: core.research.temporal_split_acceptance.evaluate
    must_aggregate_pass: true

  # NAV-level orthogonality vs every active candidate (per
  # 20260430-rcmv1_cand2_realized_correlation.md §5 action #6 +
  # audit-Round-2 + reviewer §3 2026-04-30: tiered, NOT flat 0.40).
  #
  # Mirrors Step 5 fleet correlation budget tiers with one extra
  # gate at 0.50. Long-only US-equity NAV correlation has a market-
  # beta floor that makes flat 0.40 (factor-IC config) structurally
  # over-strict; this tiered scheme reflects realistic NAV regimes.
  #
  # Each tier raises a different action:
  #   < 0.50           → true_diversifier (proceed)
  #   0.50 - 0.70      → partial_diversifier (reviewer judgment;
  #                      pack must justify; OR diagnostic flag)
  #   0.70 - 0.85      → warn_label_void (cannot claim diversifier
  #                      role; can claim core-additive only)
  #   ≥ 0.85           → reject_step5 (Step 5 hard reject; not
  #                      eligible for fleet entry)
  #
  # Both raw NAV pearson and residual NAV pearson (beta-stripped vs
  # SPY/QQQ) must satisfy the tier — see correlation memo §2.7 for
  # the residual diagnostic and why both are needed.
  nav_orthogonality_vs_rcm_v1:
    method: pearson_on_realized_paper_nav_returns
    pooled_min_overlap_days: 60
    raw_pearson_tiers:
      true_diversifier:    "< 0.50"
      partial_diversifier: ">= 0.50 and < 0.70"
      warn_label_void:     ">= 0.70 and < 0.85"
      reject_step5:        ">= 0.85"
    residual_pearson_tiers:               # beta-stripped vs SPY (and vs QQQ)
      true_diversifier:    "< 0.50"
      partial_diversifier: ">= 0.50 and < 0.70"
      warn_label_void:     ">= 0.70 and < 0.85"
      reject_step5:        ">= 0.85"
    diversifier_eligibility:
      raw_pearson_must_be_in:      ["true_diversifier"]
      residual_pearson_must_be_in: ["true_diversifier"]

  nav_orthogonality_vs_cand_2:
    method: pearson_on_realized_paper_nav_returns
    pooled_min_overlap_days: 60
    raw_pearson_tiers:
      true_diversifier:    "< 0.50"
      partial_diversifier: ">= 0.50 and < 0.70"
      warn_label_void:     ">= 0.70 and < 0.85"
      reject_step5:        ">= 0.85"
    residual_pearson_tiers:
      true_diversifier:    "< 0.50"
      partial_diversifier: ">= 0.50 and < 0.70"
      warn_label_void:     ">= 0.70 and < 0.85"
      reject_step5:        ">= 0.85"
    diversifier_eligibility:
      raw_pearson_must_be_in:      ["true_diversifier"]
      residual_pearson_must_be_in: ["true_diversifier"]

  # Cost robustness sanity (already in Track A acceptance, but
  # restated here for nomination explicitness)
  cost_robustness_2x_must_remain_positive_cagr: true

  # Reverse-validation sentinel (designed to fail if violated)
  watchlist_total_share_max: 0.30   # same gate that closed 04-26 cycle

  # Concentration ceilings (M12)
  m12_top1_weight_max: 0.40
  m12_top3_weight_max: 0.70

  # No leveraged ETF dominance
  tqqq_share_max: 0.10
  soxl_share_max: 0.10

# Promotion-blocking conditions independent of acceptance
hard_blockers:
  - any_validation_year_maxdd_above_0_20
  - any_stress_slice_maxdd_above_0_25
  - validation_aggregate_excess_vs_qqq_le_0
  - 2025_role_hard_gate_failure
```

---

## 4. Run procedure

```
Step 1: commit criteria YAML + this plan in a single commit
  git commit -m "Track C cycle 2026-04-30-01 init: criteria YAML + plan"
  → record commit SHA as the "authoring_commit"

Step 2: run mining
  scripts/run_research_miner.py \
    --temporal-split --role=core \
    --lineage-tag=track-c-cycle-2026-04-30-01 \
    --n-trials=200 \
    --seed=42

Step 3: aggregate results
  Top-N=10 by composite IC_IR full-train + walk-forward fold
  agreement; Track A leak guard must pass on every trial.

Step 4: for each top-10 candidate, run Track A acceptance
  python -m core.research.temporal_split_acceptance \
    --candidate=<spec> --validate --stress

Step 5: for any candidate that passes Track A acceptance,
  run NAV-orthogonality diagnostic vs RCMv1 + Cand-2 (per
  pre-registered criteria YAML lines `nav_orthogonality_*`)

Step 6: for each remaining candidate, fill Track C evidence
  pack template (post-R30 corrected version) at
  docs/memos/<YYYY-MM-DD>-track_c_<nominee_id>_evidence_pack.md

Step 7: submit evidence pack to external review on
  review/claude-collab branch as Round 33+ entry
```

---

## 5. Exit conditions and reporting

| Condition | Action |
|-----------|--------|
| 0 nominees pass Track A acceptance | Cycle closes 0-nominee. Closeout memo at `docs/memos/<YYYY-MM-DD>-track-c-cycle-2026-04-30-01_close.md`. Drafts of "gate recalibration PRD" or "new factor family PRD" follow as separate work, NOT same cycle. |
| ≥ 1 nominee passes Track A acceptance but fails NAV orthogonality | Nominee logged as "alpha-positive but redundant"; not promoted to forward init; closeout memo records the position. |
| ≥ 1 nominee passes both | Evidence pack submitted; cycle pauses pending external review. No forward init until Concern A/B/E guards ship. |
| Any criterion in pre-registered YAML fails on the top trial | Cycle closes 0-nominee under immutability rule. NO retroactive softening. |
| Mining run crashes or leak guard raises | Cycle aborts, root-cause memo, no closeout-as-nominee path. |

---

## 6. What this plan does NOT cover

- Forward init for any nominee (gated on Concern B Tier 1 ship)
- 2026 sealed eval (gated on Concern A guard ship)
- Fleet wiring (gated on Concern B Tier 2 + invariant tests)
- Real-money deployment (gated on all three concerns + a separate
  go-live PRD)
- A second Track C cycle in parallel (one cycle at a time)

---

## 7. Estimated effort and timeline

| Phase | Effort | Wall time |
|-------|--------|-----------|
| Pre-conditions check + criteria YAML + plan commit | ~30 min | same day |
| External review (template + plan signoff) | ~1 day external | bottleneck |
| Mining run (200 trials TPE) | ~30-60 min compute | same day after signoff |
| Acceptance evaluation per top-10 | ~15 min compute | same day |
| Evidence pack drafting per nominee | ~1 hour each | same day |
| Closeout memo (0-nominee path) | ~30 min | same day |

Total: 1-2 working days post-signoff.

---

## 8. Open question for external reviewer

> Is the pre-registered criteria YAML above (especially the
> `nav_orthogonality_vs_rcm_v1 / vs_cand_2` lines and the
> `watchlist_total_share_max: 0.30` reverse-validation sentinel)
> sufficient, or should it include additional sentinels?

This is the only blocking question for kick-off. All other
parameters are derived from existing PRDs / configs.
