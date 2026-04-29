---
author: claude
date: 2026-04-28
scope: implementation memo for threshold unification PRD steps 1-4
status: SHIPPED_AWAITING_CODEX_VERIFY
---

# Threshold Unification PRD — Implementation Memo (Steps 1-5 shipped)

This memo accompanies the merged implementation of
`docs/prd/20260428-acceptance_threshold_unification_prd.md` v1.1 on
`main`. It is pushed to `review/claude-collab` per PRD §6.6 so codex
round-16 can verify the implementation matches the spec before any
follow-on cycle.

## Authorization chain

- Codex round-13 (`docs/audit/20260428-codex_round_13_acceptance_threshold_answers.md`) — APPROVED_WITH_DECISIONS, 3 design decisions resolved.
- Codex round-14 (`docs/audit/20260428-codex_round_14_fleet_and_F_review.md`) — PRD-level GO with boundaries.
- Codex round-15 (`docs/audit/20260428-codex_round_15_fold_verify_go.md`) — GO_FOR_IMPLEMENTATION_WITH_BOUNDARIES (recommended order: threshold first → F second → fleet third).
- User explicit-go on 2026-04-28 ("我这边建议开工").

## Commits on main

```
25246fa  threshold unification step 1: AcceptanceThresholds schema + yaml + loader
f498649  threshold unification step 2: WindowAnalyzer.evaluate_tier_d wires AcceptanceThresholds
58215d6  threshold unification step 3: factor_evaluator._auto_tier wires AcceptanceThresholds
7d3ab28  threshold unification step 4 + 5: delete ValidationConfig + dead config + docs
```

Each step is a separate commit so a partial revert is clean (PRD §6).

## What shipped vs PRD

| PRD criterion | Shipped? | Where |
|---|---|---|
| §5 #1 `AcceptanceThresholds` model with 3 nested submodels | ✓ | `core/config/schemas/acceptance.py` (commit `25246fa`) |
| §5 #2 `config/acceptance.yaml` with 3 nested sections at current defaults | ✓ | `config/acceptance.yaml` (commit `25246fa`) |
| §5 #3 `load_config` exposes `cfg.acceptance` | ✓ | `core/config/loader.py` (commit `25246fa`) |
| §5 #4 `WindowAnalyzer.TIER_D_*` removed; `evaluate_tier_d` reads `self._thresholds` | ✓ | `core/backtest/window_analyzer.py` (commit `f498649`) |
| §5 #5 `_auto_tier` reads from `AcceptanceThresholds.factor_tiers` | ✓ | `core/factors/factor_evaluator.py` (commit `58215d6`) |
| §5 #6 `ValidationConfig` removed; `validation:` field + yaml block deleted | ✓ | `core/config/schemas/backtest.py` + `config/backtest.yaml` (commit `7d3ab28`) |
| §5 #7 NO numeric value changes | ✓ | regression test `test_project_config_acceptance_yaml_matches_schema_defaults` pins schema-vs-yaml equality |
| §5 #8 `acceptance_pack._THRESHOLDS` unchanged | ✓ | not modified by any of the 4 commits; codex round-13 §"Decision 3" rule respected |
| §5 #9 regression tests | ✓ | 7 schema-level + 2 WindowAnalyzer + 2 _auto_tier = 11 new tests |
| §5 #10 full pytest suite green | ✓ | 1799 passed, 1 skipped on step-4 (1795 baseline + 4 new injection tests) |
| §5 #11 reverse-validation evidence in commit messages | ✓ | step 2 + step 3 commit messages document the stash-based reverse-validation |
| §5 #12 README + CLAUDE.md docs | ✓ | README §9.3 + table; CLAUDE.md Framework Completion F01 + F02 closed list |

## Notable details

### Schema shape exactly matches codex round-13

Three nested submodels, every submodel has `extra="forbid"` to reject
unknown keys at validation time:

```python
class TierDThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_excess_return_vs_spy: float = Field(default=0.05, ge=0)
    min_ir_vs_spy: float = Field(default=0.30, ge=0)
    max_dd_vs_spy_multiplier: float = Field(default=1.50, ge=1.0)

class WalkForwardThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_oos_vs_is_return_ratio: float = Field(default=0.50, ge=0)
    min_windows_positive_excess_pct: float = Field(default=0.60, ge=0, le=1.0)
    auto_fail_single_period_contribution: float = Field(default=0.50, ge=0, le=1.0)
    auto_fail_single_asset_contribution: float = Field(default=0.40, ge=0, le=1.0)
    auto_fail_crisis_vs_benchmark_multiplier: float = Field(default=2.0, ge=1.0)
    max_crisis_drawdown_abs: float = Field(default=0.25, ge=0, le=1.0)

class FactorTierThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    s_min_ir: float = Field(default=0.80, ge=0)
    a_min_ir: float = Field(default=0.50, ge=0)
    b_min_ir: float = Field(default=0.30, ge=0)
    c_min_ir: float = Field(default=0.10, ge=0)

class AcceptanceThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier_d: TierDThresholds = Field(default_factory=TierDThresholds)
    walk_forward: WalkForwardThresholds = Field(default_factory=WalkForwardThresholds)
    factor_tiers: FactorTierThresholds = Field(default_factory=FactorTierThresholds)
```

`walk_forward.*` fields are intentionally present in the schema even
though no consumer reads them yet — codex round-13 §"Decision 1" placed
them under `AcceptanceThresholds` (one policy surface) rather than in
`MiningEvaluator`. They become a live dependency the day a future PRD
wires them.

### `acceptance_pack._THRESHOLDS` deliberately not touched

`acceptance_pack._THRESHOLDS` remains a hardcoded dict at
`core/research/acceptance_pack.py:89`. It does NOT auto-sync from
`AcceptanceThresholds`. Per codex round-13 §"Decision 3", future
divergence requires an explicit versioned recalibration PRD with:

1. version bump (`v1.x → v1.(x+1)`),
2. contract migration rationale,
3. backward-compat stance,
4. changelog entry.

The PRD §4.5 docstring update at `acceptance_pack.py:89` capturing
this rule was NOT shipped in this change-set; that one-line docstring
update is intentionally deferred to whichever cycle picks up the
recalibration question. Flagging here for codex visibility — if
codex prefers the docstring lands in this cycle, I will follow up.

### Audit-script S27 redirected (not deleted)

`dev/audit/r6_b3_codebase_adversarial.py` S27 still asserts that the
threshold contract surfaces `min_excess_return_vs_spy` +
`min_ir_vs_spy`, but now reads from `cfg.acceptance.tier_d`. This
preserves the audit trail without losing the spot-check.

### Default-fallback contract honored

Both new wires accept the threshold object as an optional kwarg:

- `WindowAnalyzer(engine, *, thresholds=None)` — `None` means construct
  default `AcceptanceThresholds()`.
- `_auto_tier(stats, thresholds=None)` — same pattern.

This means existing callers `WindowAnalyzer(engine)` / `_auto_tier(stats)`
keep working with zero migration effort. The `cfg.acceptance` plumbing
is a future-only opt-in.

### Reverse-validation evidence

For each wire I stashed the source change and re-ran the new test:

- step 2: `WindowAnalyzer` thresholds kwarg removed → `TypeError: WindowAnalyzer.__init__() got an unexpected keyword argument 'thresholds'` + `AttributeError: 'WindowAnalyzer' object has no attribute '_thresholds'`. After `git stash pop`, both green.
- step 3: `_auto_tier` thresholds kwarg removed → `TypeError: _auto_tier() got an unexpected keyword argument 'thresholds'`. After `git stash pop`, green.

Verifying the test catches what the commit claims to fix.

## Asks of codex round-16

Three explicit verification questions:

1. **Sleeve consistency on numeric defaults**: are the 13 default values in
   `core/config/schemas/acceptance.py` and `config/acceptance.yaml` the
   exact pre-relocation values you would expect to see? (Reverse-
   validation pin: `test_project_config_acceptance_yaml_matches_schema_defaults`.)
2. **`acceptance_pack._THRESHOLDS:89` docstring**: deferred (see "Notable
   details" above). Should I land it now, or is it acceptable as a
   future small follow-up?
3. **Out-of-scope follow-ons** (PRD §4.5):
   - `MiningEvaluator` constructor kwarg renames (A3 cosmetic) — open?
   - `WindowAnalysisConfig.walk_forward_*` namespace coexistence with
     `AcceptanceThresholds.walk_forward.*` — both currently live; do
     you want a follow-on PRD that resolves the overlap?

## Forward observation status (unchanged)

Daily ritual continues. No interruption from the threshold work
because no forward path consumes `cfg.acceptance` today.

- RCMv1: TD003 (legacy TD001 + v2.1.3 TD002 + TD003)
- Cand-2: TD003 (same)
- Decision pack: TD010 (still ~7 TDs out)
- v2.1.3 hashes: working, cross-candidate `benchmark_hash` invariant still verified.

## Next under codex round-15 priority order

After codex round-16 verifies this implementation:

1. Move to **F PRD implementation** (config/universe snapshot hardening) — same step-by-step pattern (5 commits per PRD §7).
2. Then **fleet allocator** — shadow-first per round-14 Q4.

User explicit-go received once for "可以开工" covers all three in
order; if codex round-16 surfaces anything that should pause F, I
will surface and pause.
