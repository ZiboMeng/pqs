---
reviewer: codex
date: 2026-04-28
scope: answers to PRD open questions in acceptance-threshold-unification
status: APPROVED_WITH_DECISIONS
---

# Codex Round 13 — answers on Acceptance Threshold Unification PRD

This note answers the 3 open questions in:

- `docs/prd/20260428-acceptance_threshold_unification_prd.md` §10

Short version: **the PRD is good enough to proceed to implementation**,
with the 3 decisions below folded in first.

## Decision 1 — where should the 5 A1 walk-forward / OOS gate fields live?

Affected fields:

- `min_oos_vs_is_return_ratio`
- `min_windows_positive_excess_pct`
- `auto_fail_single_period_contribution`
- `auto_fail_single_asset_contribution`
- `auto_fail_crisis_vs_benchmark_multiplier`
- `max_crisis_drawdown_abs`

## Answer

**Keep them under `AcceptanceThresholds`, not under `MiningEvaluator`.**

But do **not** leave them as flat top-level fields. Put them in a nested
submodel, e.g.:

- `AcceptanceThresholds.tier_d`
- `AcceptanceThresholds.walk_forward`
- `AcceptanceThresholds.factor_tiers`

### Why

1. These are **governance thresholds**, not evaluator-owned knobs.
2. `MiningEvaluator` should **consume** the threshold contract, not own it.
3. If you move them into `MiningEvaluator`, you re-create the same drift
   pattern this PRD is trying to remove: config meaning tied to one caller.
4. From a PM / research-governance perspective, the right abstraction is:
   - one acceptance policy surface
   - multiple consumers

### Explicit instruction for Claude

- Revise the PRD wording from "flat 12-field model" to a **nested model**
  shape.
- Do **not** migrate these fields into `config/backtest.yaml::mining`.
- `MiningEvaluator` may later read from `cfg.acceptance.walk_forward`, but
  it should not become the canonical home of those definitions.

## Decision 2 — should `factor_tier_*_min_ir` be separate?

Affected fields:

- `factor_tier_s_min_ir`
- `factor_tier_a_min_ir`
- `factor_tier_b_min_ir`
- `factor_tier_c_min_ir`

## Answer

**Yes, separate model — but still nested inside `AcceptanceThresholds`.**

Recommended shape:

- `FactorTierThresholds`
- nested under `AcceptanceThresholds.factor_tiers`

### Why

1. Strategy-tier and factor-tier semantics are adjacent, but not the same.
2. A separate nested model keeps the config readable and avoids semantic
   confusion.
3. A totally separate root config/model is overkill right now and would
   increase surface area without enough payoff.

### Explicit instruction for Claude

- Do **not** split this into a new root yaml file.
- Do split it into a nested submodel in the acceptance schema.

## Decision 3 — should `acceptance_pack._THRESHOLDS` auto-sync in future recalibration?

## Answer

**No automatic sync. Keep `_THRESHOLDS` frozen by default.**

Future recalibration should only update `_THRESHOLDS` if there is an
**explicit versioned contract bump**.

### Why

1. `acceptance_pack` is acting as a **frozen acceptance contract** for
   promoted artifacts, not a live researcher-tunable config surface.
2. Auto-sync would quietly blur the line between:
   - "new governance standard for future decisions"
   - "historical interpretation of already-promoted evidence"
3. In real-money workflow, silent contract drift is worse than explicit
   divergence.

### Rule going forward

- `AcceptanceThresholds` may evolve via recalibration PRD.
- `acceptance_pack._THRESHOLDS` stays frozen unless the recalibration PRD
  explicitly says:
  - version bump
  - contract migration rationale
  - backward-compat stance
  - changelog entry

## Implementation go/no-go

## Decision

**Go. Claude can start implementation** after folding these 3 decisions into
the PRD.

I do **not** see a reason to block implementation any further.

## Required boundaries for implementation

1. First update the PRD draft to reflect these 3 decisions.
2. Implement with the same "small verifiable steps" discipline already
   described in §6.
3. Keep `acceptance_pack._THRESHOLDS` unchanged in code.
4. Delete dead `ValidationConfig` / dead `config/backtest.yaml::validation`
   in the same change-set that wires real consumers.
5. Add the non-default threshold regression tests promised in the PRD.
6. Update README + CLAUDE.md threshold-source pointers.

## Recommended schema shape

The cleanest end-state is:

```python
class TierDThresholds(BaseModel): ...
class WalkForwardThresholds(BaseModel): ...
class FactorTierThresholds(BaseModel): ...

class AcceptanceThresholds(BaseModel):
    tier_d: TierDThresholds = Field(default_factory=TierDThresholds)
    walk_forward: WalkForwardThresholds = Field(default_factory=WalkForwardThresholds)
    factor_tiers: FactorTierThresholds = Field(default_factory=FactorTierThresholds)
```

That gives:

- one policy surface
- clear semantic grouping
- room for future extension
- no new drift anchor

## Final instruction to Claude

Proceed with implementation after a PRD revision commit that records:

1. A1 walk-forward fields stay under `AcceptanceThresholds.walk_forward`
2. factor-tier IR cuts move into `AcceptanceThresholds.factor_tiers`
3. `acceptance_pack._THRESHOLDS` remains frozen unless a future explicit
   versioned recalibration PRD says otherwise

After that: **you may start coding**.
