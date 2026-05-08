---
date: 2026-05-07
operator: zibomeng (Claude Opus 4.7)
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: STRATEGIC_EVIDENCE_NOTE
type: red_verdict_no_forward_init
trial: 1e771580f486 (cycle07a Trial 3)
verdict: RED — sibling-by-NAV, not forward-observed
upstream:
  - docs/audit/20260507-beta_metric_path_bug_postmortem.md
  - docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md
  - data/audit/cycle07a_trial3_nav_correlation.json
status: IMMUTABLE_AUDIT_TRAIL
---

# cycle07a Trial 3 — Red verdict, evidence-only (no forward init)

## TL;DR

Trial 3 (`1e771580f486`, drawup_from_252d_low + mom_63d + ret_1d, monthly,
cap_aware) is the sole post-fix Track A nominee from the cycle06/07a/08
audit set (17/17 gates PASS, 17yr cum_ret +1016.75% vs SPY +231.94%). Per
locked NAV-correlation gate (x.txt 2026-05-07), forward-init authorization
required all 3 pairs (vs RCMv1 / Cand-2 / Trial 9) raw < 0.85 + residual
< 0.50. Actual:

| Pair | raw | residual_vs_spy | residual_vs_qqq |
|---|---|---|---|
| Trial 3 vs RCMv1 | **0.874** | 0.603 | 0.613 |
| Trial 3 vs Cand-2 | **0.892** | 0.688 | 0.699 |
| Trial 3 vs Trial 9 | 0.783 | 0.319 | 0.381 |

**Verdict: RED** (raw ≥ 0.85 violation in 2/3 pairs; residual ≥ 0.50
violation in 4/6 residual measurements). **Trial 3 not forward-init'd**;
this memo records the structural finding.

## What this proves about cycle04-08 sibling pattern

The cycle07-to-fleet master PRD R36 audit observed drawup-anchor
recurrence across cycle04/05/06/07a/08 top-1 trials but could not
distinguish "factor IC convergence" from "construction NAV convergence."
The Trial 3 NAV correlation gives the cleanest dis-aggregation to date:

**Finding 1: drawup_from_252d_low + monthly + top-N is the binding
sibling geometry**
- Trial 3 shares ONLY `drawup_from_252d_low` factor verbatim with RCMv1
  (1 of 4 factors). The other 3 RCMv1 factors (`beta_spy_60d`,
  `days_since_52w_high`, `amihud_20d`) are absent from Trial 3.
- Yet Trial 3 vs RCMv1 raw NAV Pearson is **0.874** — which means a
  single shared Family-B factor + identical construction (long-only,
  monthly rebalance, top_n=10, 78-stock universe) produces ~76% shared
  NAV variance.
- This refutes the "factor diversity → fleet additivity" theory
  underlying anchor exclusion (cycle05 banned drawup + amihud → 0
  nominee). Banning the FACTOR doesn't break the SIBLING pattern;
  banning the CONSTRUCTION does.

**Finding 2: Cand-2 sibling-by-NAV is even tighter than RCMv1**
- Trial 3 shares 0 of 3 factors with Cand-2 (`ret_5d` vs `ret_1d` is a
  distinct horizon; `rs_vs_spy_126d` and `hl_range` absent from Trial 3).
- Yet raw NAV Pearson is **0.892** (higher than vs RCMv1).
- Hypothesis: the MARKET-COVERAGE constraint of long-only top-10 over a
  78-stock universe is the binding NAV-similarity geometry. Two
  composites with disjoint factors but same construction can pick
  ~30-50% identical names month-to-month due to the universe's effective
  rank dimensionality.

**Finding 3: Trial 9 (max_dd_126d) is structurally distinct**
- Trial 9 shares `ret_1d` factor with Trial 3 (1 of 3) + uses
  `max_dd_126d` (close-to-floor) instead of Trial 3's
  `drawup_from_252d_low` (close-to-ceiling).
- Both use cap_aware construction, monthly rebalance, top_n=10.
- Raw NAV Pearson **0.783** (still high but below 0.85 reject) +
  residual 0.319-0.381 (well below 0.50 ceiling).
- Trial 9 is the FIRST cycle04-08 candidate with a Family-B anchor that
  produces NAV-distinct behavior under the same cap_aware construction.
  This is empirical confirmation that **drawup vs max_dd is a real
  sibling boundary**, not just a name change.

## Why Trial 3 is "standalone-valid but fleet-non-additive"

Trial 3 passes Track A acceptance — its 17yr cum_ret, sharpe, MaxDD,
2018 BEAR vs SPY, 2025 holdout vs SPY all clear hard gates. As a
single-candidate strategy it is not invalid.

But the fleet-allocator binding constraint (PRD §B at
`docs/prd/20260428-candidate_fleet_allocator_prd.md`, Step 5 correlation
budget = raw NAV pair Pearson < 0.85) is precisely what Trial 3 fails.
A fleet of {RCMv1, Cand-2, Trial 3} would offer no risk diversification
beyond {RCMv1, Cand-2} alone — Trial 3's NAV is 87-89% explained by
either anchor's NAV.

This is the FIRST cycle04-08 candidate where the binding gate switches
from **acceptance** (Track A 17 gates) to **additivity** (Step 5 NAV
correlation budget). Pre-2026-05-07 every cycle stalled at acceptance;
Trial 3 walks past acceptance and stops at additivity. The two gates
test orthogonal properties — acceptance asks "is this strategy real?",
additivity asks "does it add anything to the existing fleet?".

## Implications for D.0 fleet allocator gate

Master PRD `docs/prd/20260424-cycle07_to_fleet_master_prd.md` D.0 gate
requires:
- (a) ≥ 2 candidates passing Track A acceptance
- (b) Trial 9 forward TD60 GREEN (~2026-07-30)

Pre-2026-05-07 (a) was 0/3 cycles done. Post-fix (a) is 1/3 (Trial 3
alone). **But for D.0's underlying intent (build a fleet that materially
diversifies), (a) should be tightened to require both Track A acceptance
AND fleet-additivity (raw NAV pair Pearson < 0.85 vs all existing fleet
members)**. Under this tightening, Trial 3 does not unlock (a). The
gate logic of D.0 needs revision in a follow-up master PRD round to
reflect the additivity learning.

Provisional rule (proposed, not yet ratified):
- **D.0 (a) revised**: ≥ 2 candidates passing Track A acceptance AND
  pairwise raw NAV Pearson < 0.85 across all fleet members on
  cycle04-canonical 16-year extended panel.

This means Trial 3's status under this revised D.0 (a):
- counts toward Track A nominee total → still 1 of 2 needed
- does NOT count toward "additive fleet member" → vs RCMv1 raw 0.874,
  vs Cand-2 raw 0.892
- D.0 (a) requires a NEXT candidate that is BOTH Track A accept AND
  raw < 0.85 vs RCMv1, Cand-2, AND now Trial 3 (3-way constraint)

## Cycle direction implication

Cycle04-08 + Trial 3 collectively demonstrate that cap_aware monthly
top-10 over 78-stock universe **cannot break sibling geometry by factor
swap alone**. Future cycle direction options (NOT pre-registered, awaiting
user authorization):

1. **Construction DOF expansion**: weekly cadence (cycle07-fleet
   tested partially); cross-asset (cycle04 partially); long-short
   (violates `no-short` invariant); multi-horizon ensemble (untested);
   non-equity sleeve (Trial 9-direction proven distinct).
2. **Universe expansion**: 78 → 200+ stocks, OR add bonds/commodities
   permanently. Tested partially in cycle04 (53 stocks + 6 cross-asset
   ETFs); R41 Tier 2 sibling-by-NAV due to amihud factor coverage gap
   on bonds.
3. **Strategy-type pivot**: options sleeve (Phase 1 free-path
   COMPLETE, paper observation in progress); intraday reversal
   (untested under PQS forward); event-calendar (untested).
4. **Gate revision**: relax 78-stock universe constraint, OR relax
   long-only invariant (requires user explicit-go per CLAUDE.md
   invariants).

The Trial 9 forward observation (TD060 ~2026-07-30) remains the load-
bearing GREEN-decision input — if Trial 9 shows post-init residual NAV
corr stays < 0.40 + per-regime BULL vs_qqq 60d > -3% + portfolio combo
positive, it proves the max_dd_126d-anchor distinct-sleeve hypothesis
empirically and unlocks Phase C-PRD-2 sleeve abstraction.

## What was NOT done because of this verdict

(Per x.txt locked spec 2026-05-07, Red path = no forward init.)

- ❌ frozen spec yaml `cycle07a_trial3_core_alpha_001.yaml` — not written
- ❌ init script `dev/scripts/forward/init_trial3_cycle07a.py` — not written
- ❌ forward init via `python dev/scripts/forward/init_trial3_cycle07a.py`
- ❌ first observe TD001 = 2026-05-08 EOD
- ❌ candidate_registry add (would have been candidate #4 after RCMv1,
  Cand-2, Trial 9)

These artifacts CAN be revived via `git revert` of this memo + executing
the original `Green` path IF a future user-go authorizes a softer
correlation budget OR if D.0 gate revision deprioritizes additivity.

## What WAS done

- [x] P0 beta_to_qqq metric path wiring fix + 6 regression tests
- [x] cycle06/07a/08 retroactive Track A re-eval (3 cycles × 3 trials = 9 trials)
- [x] postmortem `docs/audit/20260507-beta_metric_path_bug_postmortem.md`
      with all TBD cells filled
- [x] amendment memo `docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md`
      consolidating verdict revision (cycle07a 0/3 → 1/3 PASS; cycle06+08
      verdict UNCHANGED with revised gate-attribution)
- [x] panel_max_date_at_freeze sanity check (cycle07a yaml line 50 =
      2024-12-31, freeze_date line 51 = 2026-05-07; both already recorded)
- [x] attention_check.py SPY total-return path verification
      (`core/research/forward/attention_report.py:458` already uses
      `adjusted=True, adjusted_total_return=True`; no patch needed)
- [x] NAV correlation harness `dev/scripts/cycle07a/trial3_nav_correlation.py`
      reusing cycle04 `_residual_pair_corr` + 16y extended panel; output
      `data/audit/cycle07a_trial3_nav_correlation.json`
- [x] this evidence-only memo (Red path)

## Self-audit (R1-R4)

### R1 — factual

- 9 of 9 trials' post-fix verdicts cross-checked vs original
  `RERUN_2026-05-07.json` JSONs (cf amendment memo §"Per-cycle re-eval
  verdicts").
- Trial 3 NAV correlation 3 pairs cross-checked vs
  `data/audit/cycle07a_trial3_nav_correlation.json`.
- panel_max_date_at_freeze line 50 of cycle07a yaml grep'd live
  ("2024-12-31").
- attention_report.py:458 grep'd live (`adjusted_total_return=True`).

### R2 — logical

- Verdict tier locked in x.txt 2026-05-07: raw 0.85 cap + residual 0.50
  cap; Trial 3 vs RCMv1 raw 0.874 + vs Cand-2 raw 0.892 + 4/6 residuals
  ≥ 0.50 → unambiguous Red.
- Trial 3 PASS at Track A but Red at additivity: orthogonal gate
  separation is the structural finding. Memo argument follows.

### R3 — actually-run

- `python dev/scripts/cycle07a/trial3_nav_correlation.py` ran live
  twice (first attempt: cluster_map missing kwarg → TypeError; second
  attempt with `STOCK_RISK_CLUSTER_MAP` import → exit 0, 2164 days
  pooled, all 4 NAVs computed end-to-end).
- Output JSON read back live; numbers transcribed verbatim into this
  memo.

### R4 — boundary

- **What if cycle07a Trial 3 vs Trial 9 raw was ≥ 0.85 too (cap_aware
  + cap_aware match)?** Actual is 0.783 (below cap). This means cap_aware
  construction itself is not the sibling source — drawup-anchor is.
  Self-audit: confirms Finding 1.
- **What if RCMv1's drawup weight (0.302) was the dominant raw-corr
  driver?** Cand-2 has NO drawup factor at all yet raw is 0.892 (higher
  than vs RCMv1's 0.874). So drawup-specific weight is NOT the only
  driver. Universe-rank coverage in long-only top-10 over 78 stocks is
  the binding geometry. Self-audit: confirms Finding 2.
- **What if 60-day overlap minimum was too low and pooled the wrong
  windows?** Actual n=2164 (~16y), well above 60d minimum. Sample size
  not a concern; sibling pattern is structural.
- **What if revised D.0 gate is too strict (3-way correlation budget
  unmeetable)?** That IS the finding — the geometry is binding under
  current universe + construction. The gate is correctly identifying
  infeasibility; the response is to expand DOF (Section 6 cycle
  direction options), not soften the gate. If the user explicit-go's a
  softer gate (e.g. 0.90 raw cap), this memo's Red verdict shifts to
  Yellow, and forward init becomes available.

### R5 — verdict

PASS. Findings 1-3 are robust to alternate explanations.

## Lineage

`cycle07-to-fleet-master-2026-05-06` final evidence note. Master PRD's
D.0 fleet allocator path gated on Trial 9 TD060 (~2026-07-30). Cycle
direction (next mining cycle vs. universe expansion vs. strategy-type
pivot) requires fresh user-go after Trial 9 TD060 result.
