---
reviewer: codex
date: 2026-04-28
scope: round-14 review of fleet allocator PRD + config/universe snapshot hardening PRD
status: APPROVED_AT_PRD_LEVEL_WITH_BOUNDARIES
---

# Codex Round 14 — Fleet + F PRD review

This note reviews:

- `docs/prd/20260428-candidate_fleet_allocator_prd.md`
- `docs/prd/20260428-config_universe_snapshot_hardening_prd.md`

and answers their open questions with explicit decisions.

## Bottom line

Both PRDs are **good enough at the design level** to move forward.

But the implementation boundary is equally explicit:

- **No implementation starts yet**
- first fold the round-14 decisions below into the PRDs
- then wait for **user explicit-go**
- meanwhile keep the **forward observe daily ritual** running from
  `TD003 -> TD010`

That boundary is intentional and matches the user's latest instruction.

## Part I — Fleet allocator PRD

## Overall judgment

This PRD is directionally right and it is the correct next macro layer.

The biggest thing it gets right is: it treats the allocator as a
**portfolio decision layer**, not as a new alpha generator. That is the
correct PM framing.

But I want one meaningful semantic cleanup before coding:

- the current `core_min_capital_pct` language should be reframed as an
  **aggregate core sleeve floor**, not as a per-core-candidate floor

That resolves Q1 cleanly and avoids awkward per-candidate math.

## Fleet Q1 — core role cap consistency under `N_core >= 2`

### Decision

**Neither Option A nor raw Option B as written.**

Use this rule instead:

- `core_min_capital_pct` applies to the **aggregate core sleeve**
- within the core sleeve, capital is split by the configured split rule

### Why

If you have 2 core candidates and `core_min_capital_pct=0.60`, the
meaningful constraint is:

- total capital allocated to all core candidates together >= 60%

not:

- each core candidate individually must have >= 60%

That per-candidate interpretation is not economically coherent once
`N_core > 1`.

### Required PRD edit

Rewrite C4 so that:

- `core_min_capital_pct` = minimum aggregate capital assigned to the
  set of `role=core` candidates
- `satellite_max_capital_pct` = maximum aggregate capital assigned to
  the set of `role=satellite` candidates
- per-candidate weights are then computed inside each sleeve by
  `split_policy`

That makes today's `0.5 / 0.5` on two core candidates perfectly valid.

## Fleet Q2 — benchmark-relative DD throttle vs absolute

### Decision

**Keep v1 throttle absolute. Do not add benchmark-relative throttle to the control path yet.**

But:

- record fleet drawdown vs SPY alongside absolute drawdown
- expose it in manifest / evidence
- reserve benchmark-relative throttle as a v2 upgrade

### Why

For v1, simplicity wins:

- absolute DD throttles are easy to reason about
- your global portfolio rule already has an absolute MaxDD target
- adding benchmark-relative throttle now increases complexity exactly
  where we still have no live allocator evidence

I do agree that "not worse than SPY in crisis" matters, but for v1 it
should be a **reported governance metric**, not a live throttle input.

## Fleet Q3 — manifest cadence daily or weekly

### Decision

**Daily.**

### Why

1. Candidate forward observation is daily.
2. There are only 2 candidates right now, so manifest growth is trivial.
3. Weekly aggregation would hide exactly the short-horizon composition
   drift we want to observe early.

If the fleet layer later grows to many candidates or intraday cadence,
revisit. Not now.

## Fleet Q4 — shadow mode?

### Decision

**Yes. Mandatory for v1.**

### Rule

- allocator v1 first runs in `shadow=True`
- minimum shadow soak = **10 trading days**
- only after that should it be allowed to drive live paper / forward
  portfolio decisions

### Why

This is the right bridge between:

- "we have allocator logic"
- and
- "we trust allocator decisions with actual capital routing"

Without shadow mode, you would be taking a brand-new composition layer
live before seeing its behavior under real candidate drift.

## Fleet PRD modifications required before code

1. Reframe C4 as **aggregate core/satellite sleeve constraints**
2. Keep C5 throttle **absolute**
3. Add "report relative DD vs SPY" as evidence, not as control logic
4. Make `shadow=True` **mandatory** in v1 first-live run

## Part II — Config / Universe Snapshot Hardening PRD

## Overall judgment

This PRD is also directionally right.

The key idea is correct:

- config drift and data revision must not be collapsed into the same event class

That is an important governance improvement, and it is exactly the right
"P1 first step" before any bigger PIT data expansion.

## F Q1 — split `universe_hash` and `blacklist_hash`?

### Decision

**No split in v1. Keep a single `universe_hash`.**

### Why

- blacklist edits are edits to `config/universe.yaml`
- the semantic consequence is the same class of drift: tradable /
  held-eligible universe changed
- splitting adds labeling granularity but not decision value

This is the kind of detail that can wait for v1.1 if real usage proves
the added granularity is worth it.

## F Q2 — split `risk_config_hash` by subsection?

### Decision

**No split in v1. Keep a single `risk_config_hash`.**

### Why

Same logic as Q1:

- better to ship one clean config-drift mechanism first
- if frequent edits later show that kill-switch vs position-limit drift
  needs separate labels, split in v1.1

Do not overfit the first contract.

## F Q3 — severity policy on `system_config_hash`

### Decision

**Keep it as `warn`, not `halt`, in v1.**

### Why

For current forward research mode:

- capital scaling changes are governance-significant
- but they are not the same class of comparability break as universe /
  factor-registry / risk-envelope changes

So the right behavior is:

- record it
- warn loudly
- continue

If later the fleet layer or production paper workflow starts treating
capital path as a hard contract, upgrade in v1.1/v2.

## F Q4 — is `config/regime.yaml` safe to omit?

### Decision

**Yes, safe to omit in v1 for the current forward-manifest hardening scope.**

### Why

I checked the relevant code path:

- `core/research/forward/runner.py::observe` does **not** route through
  `RegimeDetector(cfg.regime)`
- current forward observe logic computes candidate forward metrics from
  the panel / frozen spec path, not from the runtime regime yaml

So for the current forward-manifest contract, omitting `config/regime.yaml`
is justified.

### Important caveat

If the future forward path is refactored to consume:

- `RegimeDetector(cfg.regime)` directly, or
- any strategy path whose live decisions depend on `cfg.regime`

then `regime.yaml` should be pulled into snapshot scope in v1.1.

## F Q5 — do we need `config_drift_event_streak` throttle?

### Decision

**No. Out of scope for v1.**

### Why

Daily observe cadence already gives you a natural debounce.

Do not design for hypothetical multi-intraday config churn before that
workflow even exists.

## F PRD modifications required before code

1. Keep single `universe_hash`
2. Keep single `risk_config_hash`
3. Keep `system_config_hash` severity = `warn`
4. Explicitly record that `regime.yaml` omission is justified by the
   current forward observe code path
5. Leave drift-event streak throttling out of v1

## Implementation boundary

Here is the explicit boundary I want Claude to follow:

### Allowed now

1. Revise the two PRDs to fold in the round-14 decisions above
2. Keep threshold PRD / fleet PRD / F PRD aligned at the documentation level
3. Continue the **forward observe daily ritual**
4. Append evidence / notes as TDs accumulate toward `TD010`

### Not allowed yet

1. **No implementation** of fleet allocator
2. **No implementation** of config/universe snapshot hardening
3. **No implementation** of threshold-unification PRD

until:

- codex round-14 review is complete
- and the user gives **explicit-go**

## Operational instruction to Claude

Priority order from this point:

1. fold round-14 decisions into fleet PRD
2. fold round-14 decisions into F PRD
3. keep forward observe moving from `TD003 -> TD010`
4. wait for user explicit-go before any implementation

## Final decision

- **PRD level**: approved with the modifications above
- **Implementation level**: not yet authorized

That is the clean boundary.
