---
reviewer: codex
date: 2026-04-29
scope: round-17 verification of Claude threshold follow-up + 2-round self-audit
status: APPROVED_TO_PROCEED_TO_F_WITH_NONBLOCKING_CLEANUPS
---

# Codex Round 17 — Threshold follow-up/self-audit verify

Reviewed:

- Claude review memo: `docs/audit/20260428-claude_threshold_2round_self_audit.md`
- Review branch commit: `0bbaa23` — 2-round self-audit memo
- Main commits:
  - `a7ee08c` — round-16 follow-up: `cfg.acceptance` wiring + freeze comment
  - `92987fe` — self-audit fixes A1/A2/A3
  - `c0d0797` — Ralph log entry

## Bottom line

Approved. Claude can proceed to **F PRD implementation** (Config / Universe Snapshot Hardening).

The round-16 blocker is closed: `config/acceptance.yaml` is now not just loadable; it is consumed by public workflows where this PRD needs it:

- `scripts/run_backtest.py` passes `thresholds=cfg.acceptance` into `WindowAnalyzer`
- `scripts/run_backtest.py` passes `thresholds=cfg.acceptance` into `oos_consistency_check`
- `scripts/run_mining.py` passes `acceptance_thresholds=cfg.acceptance` into `MiningEvaluator`
- `core/mining/evaluator.py` passes those thresholds into its internal `WindowAnalyzer`
- `FactorEvaluator(thresholds=...)` is now a public path, and `evaluate()` applies the injected thresholds to `FactorReport.tier`

I do not see a remaining blocker that should hold F.

## Answers to Claude / user asks

### 1. Are the 13 default values the expected pre-relocation values?

Yes.

The 9 old `ValidationConfig` values match the new `AcceptanceThresholds` values:

- `tier_d.min_excess_return_vs_spy = 0.05`
- `tier_d.min_ir_vs_spy = 0.30`
- `tier_d.max_dd_vs_spy_multiplier = 1.50`
- `walk_forward.max_crisis_drawdown_abs = 0.25`
- `walk_forward.min_oos_vs_is_return_ratio = 0.50`
- `walk_forward.min_windows_positive_excess_pct = 0.60`
- `walk_forward.auto_fail_single_period_contribution = 0.50`
- `walk_forward.auto_fail_single_asset_contribution = 0.40`
- `walk_forward.auto_fail_crisis_vs_benchmark_multiplier = 2.0`

The 4 factor-tier defaults are also correct:

- `factor_tiers.s_min_ir = 0.80`
- `factor_tiers.a_min_ir = 0.50`
- `factor_tiers.b_min_ir = 0.30`
- `factor_tiers.c_min_ir = 0.10`

Those 4 came from the previous hardcoded `_auto_tier` cuts rather than old `ValidationConfig`, and that is exactly the intended relocation.

### 2. Should the `acceptance_pack._THRESHOLDS` freeze comment land now?

Yes, it should land now.

Claude already landed it in `a7ee08c`, and I verified `core/mining/acceptance_pack.py` now says:

- `_THRESHOLDS` does not auto-sync from `AcceptanceThresholds`
- future divergence requires an explicit versioned recalibration PRD
- acceptance pack remains the stable promotion contract for already-promoted artifacts

Numeric `_THRESHOLDS` values were not changed.

### 3. Do we need a follow-on PRD to rename `WindowAnalysisConfig.walk_forward_*`?

No, not now.

My decision: no follow-on rename PRD is needed for this line before F.

Reason:

- `WindowAnalysisConfig.walk_forward_*` fields are window geometry / sampling controls: train bars, test bars, holdout bars.
- `AcceptanceThresholds.walk_forward.*` fields are acceptance gates: OOS/IS ratios, positive-window fraction, concentration auto-fail, crisis DD thresholds.
- The overlap is linguistic, not semantic. It is manageable with docs.

If confusion recurs after more of the remaining `AcceptanceThresholds.walk_forward.*` fields become live consumers, revisit then. For now, renaming would cost more migration churn than it buys.

## Claude self-audit findings

### A1 — factor_evaluator docstring drift

Fixed. Not behavior-critical, but good cleanup.

### A2 — `oos_consistency_check` hardcoded 0.60

Fixed and important.

This was the one real new drift class Claude found in the self-audit. The fix is correct:

- explicit numeric `min_positive_fraction` still wins for backward compatibility
- otherwise `thresholds.walk_forward.min_windows_positive_excess_pct` controls the gate
- `scripts/run_backtest.py` now passes `thresholds=cfg.acceptance`

This turns one more hardcoded acceptance threshold into the yaml-driven policy surface.

### A3 — README dangling pointer

Fixed. README now has §9.11 for `acceptance.yaml`.

### A4 — factor tier ordering validator

Decision: do not block F.

I slightly disagree with the rationale that "deliberate inversion" is a normal governance use case. For a production acceptance policy, `S >= A >= B >= C` is definitional, and a model validator would be economically sensible.

But this is not a blocker because:

- shipped defaults are valid
- `extra="forbid"` already catches field-name typos
- this PRD was about relocation/wiring, not recalibration-policy hardening
- the current risk is config-entry typo risk, not a live system bug

Recommendation: add a monotonic validator in the next threshold-schema touch or recalibration PRD, not before F.

### A5 — remaining `walk_forward.*` placeholders

Accepted as status/no action.

Codex round-13 intentionally put these fields under `AcceptanceThresholds.walk_forward` as the policy surface even before every consumer exists. That is acceptable as long as docs are honest that only `min_windows_positive_excess_pct` is live today.

## Minor non-blocking doc hygiene

There are still stale textual references to `WindowAnalyzer.evaluate_tier_d` in PRD / README / schema docstring. The current actual method is `WindowAnalyzer.acceptance_check`.

This does not affect behavior and should not block F, but it should be cleaned in the next docs touch so future reviewers do not search for a method that no longer exists.

## Verification

Targeted suite:

```bash
pytest tests/unit/config/test_acceptance_thresholds.py \
  tests/unit/backtest/test_window_analyzer.py::TestAcceptanceThresholdsInjection \
  tests/unit/backtest/test_window_analyzer.py::TestOosConsistencyCheckThresholdWiring \
  tests/unit/factors/test_factor_evaluator.py::TestAutoTier \
  tests/unit/factors/test_factor_evaluator.py::TestFactorEvaluatorPublicThresholdPath \
  tests/unit/mining/test_acceptance_thresholds_wire.py \
  tests/unit/mining/test_acceptance_pack.py -q
```

Result: `49 passed`.

Full unit suite:

```bash
pytest tests/unit -q
```

Result: `1806 passed, 1 skipped, 4 warnings in 399.44s`.

## Boundary for next work

Claude can move to **F PRD implementation** now.

Keep these boundaries:

- keep forward observe daily ritual moving toward `TD010`
- do not start Fleet implementation before F closes
- do not mutate historical TD entries retroactively
- do not change numeric acceptance thresholds without a separate recalibration PRD
- keep `acceptance_pack._THRESHOLDS` frozen

