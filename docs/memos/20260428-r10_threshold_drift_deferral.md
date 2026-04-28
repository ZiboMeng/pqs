# R10 deferral memo — F01 + F02 threshold drift

**Date**: 2026-04-28
**Round**: 10 (B7) — meta-audit + final consolidation
**Lineage**: ralph-audit-2026-04-28
**Decision**: defer F01 + F02 to a separate scoped change

## What's being deferred

**F01** (R4 finding): `core/backtest/window_analyzer.py:135-137` defines
class-level `TIER_D_*` constants (0.05 / 0.30 / 1.50) that are
"documented to be consistent with `BacktestConfig.ValidationConfig`"
but are NOT actually wired to the config. If a user overrides
`config/backtest.yaml::validation.min_excess_return_vs_spy`,
`WindowAnalyzer` ignores it.

**F02** (R4 finding): `core/mining/evaluator.py:146-170` exposes
quick-stage / oos-stage thresholds as constructor kwargs with
hardcoded defaults; not derived from any pydantic schema. Three
threshold "anchors" coexist (ValidationConfig vs WindowAnalyzer vs
MiningEvaluator) with no single source of truth.

## Why R10 doesn't fix in-round

1. **Scope is a real refactor.** Wiring all three threshold anchors
   into a single `ValidationConfig`-driven flow requires touching
   `WindowAnalyzer.evaluate_tier_d` + `MiningEvaluator` constructor +
   miner CLI plumbing + ~10 unit tests pinning the current
   constructor-arg behavior. The ralph-audit cycle's hard rule is
   "small verifiable patches over large rewrites" (CLAUDE.md). A
   threshold-config refactor properly belongs in its own PRD.

2. **No active drift in production paths.** Nothing in the current
   acceptance flow overrides `config/backtest.yaml::validation.*`
   away from the WindowAnalyzer constants — both happen to read 0.05
   / 0.30 / 1.50. The drift is **latent**: a future user who edits
   one would silently desync the others. Latent ≠ live regression.

3. **R7 cross-cutting invariant lens covered the live invariants.**
   What R7 verified (long-only / SPY+QQQ benchmark / strict_mode /
   adjustment / SQQQ blacklist / T+1 fill / kill-switch tier / etc.)
   are the user-visible safety properties. The acceptance threshold
   numerics are a research-config concern, not a safety-invariant
   concern.

## Recommended fix shape (for the future PRD)

- Single `AcceptanceThresholds` dataclass owned by
  `core/config/schemas/backtest.py`.
- `WindowAnalyzer.__init__(thresholds: AcceptanceThresholds)` injects
  it; class constants removed.
- `MiningEvaluator.__init__(thresholds: AcceptanceThresholds)` reads
  the same source; legacy kwargs become opt-in overrides for unit
  tests.
- `config/backtest.yaml::validation` is the canonical yaml site;
  miner CLI looks up via the same config loader.

Test fixture: a regression that constructs `BacktestConfig` with a
non-default `min_excess_return_vs_spy=0.07` and asserts that
`WindowAnalyzer.evaluate_tier_d` actually applies 0.07 (would FAIL
under current code).

## Open until

A new PRD `prd_acceptance_threshold_unification.md` is drafted and
landed. Until then, treat WindowAnalyzer / MiningEvaluator threshold
edits as requiring a manual sync-check across all three anchors.
