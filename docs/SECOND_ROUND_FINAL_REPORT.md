# Phase-two final report

Date: 2026-07-17 (America/Los_Angeles)

Branch: `codex/strategy-research-and-paper-v2`

Rollback tag: `codex-pre-strategy-research-20260717`

## Outcome

The phase completed the audit, engine certification, bounded research funnel,
PAPER runtime and machine promotion workflow. One strategy,
`dual_index_growth_v1`, is formally `PAPER_APPROVED`; LIVE remains disabled.

The requested minimum of two PAPER strategies was not reached. This is reported
as an incomplete business target, not converted into a pass. A second strategy
cannot be supported from the current evidence without reusing an observed
holdout or expanding hypotheses post hoc.

## What was completed

- Preserved and pushed the pre-research rollback tag and isolated work branch.
- Audited dependency and evidence lineage before cleanup; deleted no tracked
  document/code because no candidate met the four-part safe-deletion test.
- Certified total-return pricing, splits/distributions, T+1 open execution,
  share-conserving gaps, walk-forward price timing and deterministic baselines.
- Closed PAPER accounting, batch-risk, atomicity, broker-authority, recovery,
  reconciliation and risk-reducing-liquidation defects.
- Registered every planned, failed, invalidated and completed experiment.
- Kept frozen development/validation/holdout boundaries and did not lower gates.
- Ran a regime ablation and rejected the harmful external risk-on-only gate.
- Produced full PAPER replay, restart/idempotence and fault-injection evidence.
- Added a fail-closed, idempotent promotion finalizer and recorded 28/28 passing gates.

## Strategy evidence

`dual_index_growth_v1` final holdout: 15.31% CAGR, 0.934 Sharpe, 1.281
Sortino, -9.43% MaxDD, 1.624 Calmar, 0.433 QQQ beta and 2.371x annual
turnover. Its 2023 PAPER replay ended at 112,281.55 from 100,000 before any
claim of LIVE applicability; operational evidence is deterministic across restart.

All other candidate families remain rejected or invalidated. The final
`crash_buffer_core_v1` search had four preregistered development cells; all
failed with only 2.13%–2.47% CAGR and negative Sharpe. It never accessed
validation or holdout.

## External evidence blocker for strategy two

The certified dataset ends 2026-07-17. Three distinct finalists have already
consumed hypothesis-scoped access to the 2024–2026 holdout, and the terminal J
family failed development. The repository, compute, runtime and data integrity
are sufficient to evaluate candidates; what is unavailable is another genuinely
unseen evidence interval for a new hypothesis after this search history.

Continuing on the same data would make family invention, parameter selection and
evaluation conditional on observed holdout behavior. That is exactly the
multiple-testing/overfitting path prohibited by the mandate. An unused fourth
access slot does not restore data novelty after the terminal plan.

Precise unlock conditions are either:

1. accumulate at least 252 completed market sessions strictly after 2026-07-17,
   preregister the candidate before reading that forward block, and freeze the
   new validation/holdout protocol before use; or
2. obtain user authorization and a disjoint, point-in-time dataset/protocol with
   auditable provenance, survivorship handling and a new sealed interval.

Lowering gates, renaming a failed strategy, buying more compute, or viewing the
same holdout again does not unlock the task.

## Safety status

- PAPER default: one approved strategy enabled.
- LIVE: disabled in configs, registry and promotion record.
- Open research-related P0/P1: none.
- Real broker credentials and capital authorization: absent by design.
- Pairwise complementarity promotion: not applicable until a second independent
  candidate passes its own full evidence chain.

Final verification: 4,213 passed, 23 skipped, 1 expected xfail, 0 failed and
43 warnings in 1,983.12 seconds. A phase-two consolidated subset separately
passed 858 tests with 1 expected xfail. Focused Ruff/mypy, PAPER evidence replay,
promotion idempotence, JSON/YAML validation and `pip check` also pass.
