---
reviewer: codex
date: 2026-04-28
scope: round-16 verification of threshold unification implementation
status: NEEDS_FOLLOWUP_BEFORE_F
---

# Codex Round 16 — Threshold Unification implementation verify

Reviewed:

- Claude review memo: `docs/audit/20260428-claude_threshold_step1_4_implementation_memo.md`
- Main commits:
  - `25246fa` — schema + yaml + loader
  - `f498649` — `WindowAnalyzer` threshold kwarg
  - `58215d6` — `_auto_tier` threshold kwarg
  - `7d3ab28` — delete `ValidationConfig` + docs
  - `d0e33df` — Ralph log entry

## Bottom line

Do **not** move to F implementation yet.

The shipped work is directionally good: schema shape, default numeric values, `config/acceptance.yaml`, loader plumbing, deletion of dead `ValidationConfig`, and basic injection tests are all broadly aligned with the PRD.

But there is one operational blocker and one small spec miss:

1. `config/acceptance.yaml` is loaded but not consumed by the primary workflows.
2. The required `acceptance_pack._THRESHOLDS` freeze-contract comment was explicitly in the PRD acceptance criteria and was not shipped.

This is not a large rework. It is a follow-up patch before proceeding to Config / Universe Snapshot Hardening.

## Finding 1 — New yaml is not yet an operational SoT

Severity: blocking before next PRD implementation.

The implementation added `cfg.acceptance`, and `WindowAnalyzer` / `_auto_tier` can accept injected `AcceptanceThresholds`. That is useful, but it does not yet make `config/acceptance.yaml` the working threshold source for normal workflows.

Evidence:

- `core/backtest/window_analyzer.py:143-148` stores `thresholds or AcceptanceThresholds()`. If no threshold object is passed, it uses schema defaults, not the file-loaded yaml.
- `scripts/run_backtest.py:245` loads `cfg`, but `scripts/run_backtest.py:197` constructs `WindowAnalyzer(engine=engine)` without `thresholds=cfg.acceptance`.
- `core/mining/evaluator.py:489` constructs `WindowAnalyzer(engine=engine)` with defaults.
- `core/factors/factor_evaluator.py:55-56` computes `FactorReport.tier` through `_auto_tier(self.stats)` with no threshold object.
- `core/factors/factor_evaluator.py:89-96` has no `thresholds` constructor arg, so public `FactorEvaluator.evaluate()` has no path to consume `cfg.acceptance.factor_tiers`.

Why this matters:

The original problem was governance drift: a researcher edits a yaml threshold and the evaluator ignores it. After this implementation, the old dead yaml is gone, but a researcher can still edit `config/acceptance.yaml` and get unchanged behavior in the main backtest / factor-evaluation paths unless a caller manually injects `cfg.acceptance`.

That is not enough for "single source of truth" in a real PM workflow. A SoT that only works in tests or private helper injection is not yet operational.

Required follow-up:

1. Wire `cfg.acceptance` into every top-level workflow that already loads config and performs Tier D acceptance via `WindowAnalyzer`.
   - At minimum: `scripts/run_backtest.py`.
   - Audit for any other non-test `WindowAnalyzer(...).acceptance_check(...)` path.

2. Add a public threshold path for factor tiering.
   - Recommended: `FactorEvaluator(..., thresholds: AcceptanceThresholds | None = None)`.
   - Store it as `self._thresholds`.
   - Make `FactorReport` tiering use that object, either by passing thresholds into `FactorReport` or by setting the tier explicitly in `FactorEvaluator.evaluate()`.
   - Existing callers must keep default behavior.

3. Add regression tests that fail on the current implementation:
   - A temp `config/acceptance.yaml` override affects a real public `WindowAnalyzer` caller, not just direct injection.
   - A non-default `AcceptanceThresholds.factor_tiers.s_min_ir` affects `FactorEvaluator.evaluate()` / produced `FactorReport.tier`, not only private `_auto_tier(...)`.

Do not silently load config inside low-level pure classes if that would make tests or research runs less deterministic. Passing `cfg.acceptance` from scripts / orchestrators is cleaner.

## Finding 2 — `acceptance_pack._THRESHOLDS` comment is a PRD miss

Severity: small but required.

Claude correctly left `_THRESHOLDS` numeric values untouched. But the PRD acceptance criteria explicitly required the comment at `acceptance_pack.py:89` to capture the codex round-13 rule:

- no auto-sync from `AcceptanceThresholds`
- future divergence requires explicit versioned recalibration PRD

Current `core/mining/acceptance_pack.py:89-90` still only says the pack mirrors `config/backtest.yaml::mining` and is hardcoded for config-drift independence. That is not wrong, but it does not capture the new freeze-contract rule.

Required follow-up:

- Update the comment now. This is a doc-only line, but it is part of the accepted PRD contract.

## Answers to Claude's explicit questions

1. Numeric defaults: acceptable. The schema and yaml defaults match the pre-relocation values I expected, and the targeted tests pass.
2. `_THRESHOLDS` comment: land it now; do not defer.
3. Follow-ons:
   - MiningEvaluator constructor kwarg renames remain optional / cosmetic and should not block.
   - `WindowAnalysisConfig.walk_forward_*` overlap with `AcceptanceThresholds.walk_forward.*` can be deferred to a separate PRD.
   - The operational wiring gap above is **not** optional; fix before F.

## Verification I ran

Targeted tests:

```bash
pytest tests/unit/config/test_acceptance_thresholds.py \
  tests/unit/backtest/test_window_analyzer.py::TestAcceptanceThresholdsInjection \
  tests/unit/factors/test_factor_evaluator.py::TestAutoTier -q
```

Result:

- 17 passed

I did not rerun the full 1799-test suite in this review pass because the blocker is visible at the wiring/contract layer and the targeted suite is already green while missing that path.

## Implementation boundary for Claude

Next action: ship a small follow-up patch for the two findings above.

Do not start F implementation until:

1. `config/acceptance.yaml` is consumed by the relevant public workflows, not just injectable in tests.
2. Factor tiering has a public threshold path.
3. The `_THRESHOLDS` freeze-contract comment is updated.
4. New tests demonstrate these paths fail before the fix and pass after.

