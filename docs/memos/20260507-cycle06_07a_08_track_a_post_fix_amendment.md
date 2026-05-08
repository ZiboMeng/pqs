---
date: 2026-05-07
operator: zibomeng (Claude Opus 4.7)
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: AUDIT_AMENDMENT
type: amendment_to_existing_closeouts
amends:
  - docs/memos/20260507-cycle07a_closeout.md
  - docs/memos/20260520-cycle08_closeout.md
  - docs/audit/20260506-cycle07_fleet_audit_final_2.md
upstream:
  - docs/audit/20260507-beta_metric_path_bug_postmortem.md
status: IMMUTABLE_AUDIT_TRAIL_AMENDMENT
---

# 2026-05-07 Post-fix Track A re-evaluation amendment

## Why this amendment exists

A P0 metric-path wiring bug in `dev/scripts/cycle{06,07a,08}/cycle*_track_a_eval.py`
was discovered + fixed 2026-05-07 (postmortem:
`docs/audit/20260507-beta_metric_path_bug_postmortem.md`). All
cycle06/07a/08 Track A acceptance verdicts produced before commit `5873653`
silently fail-closed the `beta_to_qqq` gate even when actual betas were
well below the 0.85 cap. **This amendment does not retract the upstream
closeout memos.** It records the post-fix re-evaluation results as an
audit-trail addendum so downstream readers can see:

1. Which cycle06/07a/08 verdicts changed (cycle07a Trial 3 only)
2. Which cycles' "0 nominee" verdict survived the fix unchanged
   (cycle06 + cycle08)
3. The revised binding-gate attribution (vs_spy aggregate, NOT
   beta/qqq mix)

## Three-line summary

1. **cycle06 + cycle08 0-nominee verdict UNCHANGED** — both still 0/3
   under post-fix Track A acceptance.
2. **Failed-gate attribution revised** — pre-fix verdicts blamed a mix
   of beta+qqq+spy gates; post-fix the binding gate is `validation_aggregate_excess_vs_spy`
   alone (with 1 trial each cycle additionally failing
   `role_core__validation__2025__excess_vs_spy`). beta_to_qqq is now
   correctly recorded; vs_qqq aggregate is diagnostic-only under v3
   dispatch (post-2026-05-02 QQQ deprecation).
3. **cycle07a Trial 3 (`1e771580f486`) is the sole post-fix survivor** —
   17/17 gates PASS; pre-fix verdict was a false-negative on the beta
   gate alone (actual beta_to_qqq=0.534, well below 0.85 cap).

## Per-cycle re-eval verdicts (post-fix)

| Cycle | Trial | Features | Pre-fix failed gates | Post-fix failed gates | Δ verdict |
|---|---|---|---|---|---|
| cycle06 | `bab8cfe88af3` | drawup + trend_tstat_20d + ret_2d (M) | spy_agg + qqq_agg + beta | spy_agg only | FAIL → FAIL |
| cycle06 | `31af04cf2ff9` | drawup + xsection_rank_63d + ret_5d (W) | spy_agg + qqq_agg + 2025_qqq + beta | spy_agg + 2025_spy | FAIL → FAIL |
| cycle06 | `a9e39c21feed` | drawup + return_per_risk_21d + ret_2d (M) | spy_agg + qqq_agg + beta | spy_agg only | FAIL → FAIL |
| cycle07a | `81cfb5f4c4f5` | drawup + xsection_rank_63d + ret_5d (W) | spy_agg + qqq_agg + 2025_qqq + beta | spy_agg + 2025_spy | FAIL → FAIL |
| cycle07a | `f133a18d1495` | drawup + mom_252d + ret_2d (M) | spy_agg + qqq_agg + beta | spy_agg only | FAIL → FAIL |
| cycle07a | **`1e771580f486`** | **drawup + mom_63d + ret_1d (M)** | **qqq_agg + beta** | **(none, 17/17 PASS)** | **FAIL → PASS** |
| cycle08 | `8ac6bccbeed1` | max_dd_126d + mom_252d + reversal_21d (W) | spy_agg + qqq_agg + 2025_qqq + beta | spy_agg + 2025_spy | FAIL → FAIL |
| cycle08 | `60998346d975` | max_dd_126d + mom_252d + ret_5d (W) | spy_agg + qqq_agg + 2025_qqq + beta | spy_agg + 2025_spy | FAIL → FAIL |
| cycle08 | `3f40e3f4ed1a` | max_dd_126d + xsection_rank_63d + ret_5d (M) | spy_agg + qqq_agg + beta | spy_agg only | FAIL → FAIL |

Source JSONs:
- `data/audit/cycle06_track_a_eval_track-c-cycle-2026-05-06-01_RERUN_2026-05-07.json`
- `data/audit/cycle07a_track_a_eval_track-c-cycle-2026-05-07-01_RERUN_2026-05-07.json`
- `data/audit/cycle08_track_a_eval_track-c-cycle-2026-05-08-01_RERUN_2026-05-07.json`

## Actual betas (all cap-compliant)

Pre-fix the beta gate was reading `_MISSING` (not the actual numeric
value). Post-fix the actual betas are recorded:

| Cycle | Trial | beta_to_qqq | < 0.85 cap? |
|---|---|---|---|
| cycle06 | `bab8cfe88af3` | +0.599 | ✓ |
| cycle06 | `31af04cf2ff9` | -0.009 | ✓ |
| cycle06 | `a9e39c21feed` | +0.599 | ✓ |
| cycle07a | `81cfb5f4c4f5` | -0.009 | ✓ |
| cycle07a | `f133a18d1495` | +0.566 | ✓ |
| cycle07a | `1e771580f486` | +0.534 | ✓ |
| cycle08 | `8ac6bccbeed1` | -0.00008 | ✓ |
| cycle08 | `60998346d975` | -0.00007 | ✓ |
| cycle08 | `3f40e3f4ed1a` | +0.368 | ✓ |

**No genuine high-beta rejection across cycle06/07a/08 to date.**
The bug only produced false negatives — no real risk-cap violations
were masked.

## What this changes for upstream memos

### `docs/memos/20260507-cycle07a_closeout.md`

- **Verdict change**: "Track A 0/3 PASS, 4 gates each fail" → "Track A
  1/3 PASS post-fix; Trial 3 `1e771580f486` is the surviving nominee
  (17/17 gates), pending forward-init authorization."
- **Cycle07a stop rule** (per cycle04 closeout pre-commit) does NOT
  fire — cycle07a now has a Track A nominee.

### `docs/memos/20260520-cycle08_closeout.md`

- **Verdict UNCHANGED**: still 0/3 PASS.
- **Failed-gate revision**: pre-fix "spy_agg + qqq_agg + 2025_qqq + beta"
  → post-fix "spy_agg only" (Trial 3 of cycle08) or "spy_agg + 2025_spy"
  (Trial 1+2). Revised attribution: vs_spy aggregate is the binding
  gate, NOT a beta + QQQ-deprecation mix.

### `docs/audit/20260506-cycle07_fleet_audit_final_2.md`

- R8 ("cycle08 closeout 0 nominee") **CONFIRMED status preserved** —
  cycle08 still 0/3 even after the fix. The verdict's letter is
  unchanged; only the spirit (which gates are binding) is revised.
- R9 ("cycle07a Track A 0/3") **CONFIRMED status RETRACTED** — replaced
  by post-fix 1/3 PASS verdict. The R12 audit's R9 line should be
  understood as historical pre-fix state.

## What this DOES NOT change

- The **drawup-anchor sibling pattern** across cycle04/05/06/07a/08
  remains a real structural drift (9/9 trials in this audit set use
  drawup_from_252d_low or max_dd_126d as Family-B anchor).
- The **cycle stop rule** that PRD-D.0 fleet allocator gate (a) requires
  ≥2 nominee Track A passes still applies — Trial 3 alone does not
  unlock fleet construction; it unlocks **half** the gate (1 nominee +
  Trial 9 forward observation).
- The **2026 sealed window** was NOT consumed by any of the post-fix
  re-evaluations (the rerun scripts only touch validation years).
- The **CLAUDE.md QQQ Outperformance Rule diversifier exception** (added
  2026-05-01 for Trial 9 / role=`diversifier` only) is unaffected — the
  bug was on `beta_to_qqq`, not on the per-role vs_qqq waiver.
- Forward observation of RCMv1 + Cand-2 + Trial 9 is unaffected (none
  use `temporal_split_acceptance.py` for ongoing observation; manifest
  hashing + revalidate live on a separate code path).

## Methodology note: what made this bug detectable

R12 audit's "actually-run-the-code" R3 layer (per
`docs/checkpoints/20260430-self_audit_methodology.md`) caught a
suspicious "16 of 17 gates correlated FAIL with beta=present" pattern
across all 9 trials — too consistent to be genuine. Tracing
`temporal_split_acceptance.py:_eval_beta_gate` to its `_resolve_metric`
call revealed the nested-vs-flat path mismatch. The 6-test
regression file (`tests/unit/research/test_beta_metric_path_canonical.py`)
pins canonical schema + v1/v3 dispatch + low/high beta verdict so this
class of silent contract violation cannot recur without test failure.

## Reversibility

This amendment is doc-only. To revert: delete this file. The
RERUN_2026-05-07.json artifacts in `data/audit/` preserve the
post-fix evaluations as immutable audit data; pre-fix evaluations
are preserved at the original (non-RERUN) JSON paths.

## Lineage

`cycle07-to-fleet-master-2026-05-06` audit follow-up. Triggered by
R12 audit final 2. Postmortem at
`docs/audit/20260507-beta_metric_path_bug_postmortem.md`. Trial 3
forward-init decision pending (gated on NAV correlation check vs
RCMv1 / Cand-2 / Trial 9 per x.txt locked spec 2026-05-07; results
will land at `data/audit/cycle07a_trial3_nav_correlation.json`).
