---
reviewer: codex
date: 2026-04-28
scope: fold-verify of Claude commit 589ccd1 on fleet + F PRDs
status: GO_FOR_IMPLEMENTATION_WITH_BOUNDARIES
---

# Codex Round 15 — fold-verify and implementation boundary

Reviewed on `review/claude-collab`:

- Claude commit `589ccd1` — `fleet PRD v1.1 + F PRD v1.1 for codex round-15 fold-verify`
- `docs/prd/20260428-candidate_fleet_allocator_prd.md`
- `docs/prd/20260428-config_universe_snapshot_hardening_prd.md`

## Bottom line

PASS. I do not see a blocking issue in Claude's PRD fold.

Claude correctly kept this as a PRD/documentation fold and did not sneak in implementation code. The round-14 decisions are now represented clearly enough that implementation can start under the boundaries below.

I interpret the user's current instruction — "没问题可以说可以开工" — as the missing explicit-go for implementation after this fold-verify. From Codex side: **可以开工**.

## What I verified

### Fleet allocator PRD

The v1.1 PRD now reflects the round-14 decisions:

- allocator is explicitly a portfolio decision layer, not a new alpha generator
- C4 is rewritten as aggregate core/satellite sleeve constraints, not per-candidate minimums
- C5 keeps the throttle absolute in v1
- `dd_vs_spy_60d` is evidence-only, not a control input
- cadence stays daily
- shadow mode is mandatory
- live capital routing requires at least 10 trading days of shadow soak plus later user explicit-go
- Q1-Q4 are marked resolved

This is the right PM framing. The sleeve-level C4 cleanup matters: it avoids nonsense constraints like requiring two core candidates to each hold 60% capital.

### Config / Universe Snapshot Hardening PRD

The v1.1 PRD now reflects the round-14 decisions:

- single `universe_hash` in v1
- single `risk_config_hash` in v1
- `system_config_hash` severity remains `warn`
- `config/regime.yaml` is out of scope for the current forward observe path, with the correct caveat
- drift-event streak throttle is out of scope in v1
- Q1-Q5 are marked resolved

The regime caveat is important and should stay visible during implementation: if Claude discovers that the implementation path actually consumes `cfg.regime` or `RegimeDetector(cfg.regime)`, stop and ask before proceeding.

## Implementation boundary

Claude can start implementation, but not as one giant all-in-one change. Use small, reviewable steps.

Recommended execution order:

1. Acceptance Threshold Unification first.
   - This is the smallest policy-surface cleanup and removes a governance drift anchor before the next layers consume thresholds.
   - Keep `acceptance_pack._THRESHOLDS` frozen unless a future explicit versioned recalibration PRD says otherwise.

2. Config / Universe Snapshot Hardening second.
   - This has higher immediate governance value than allocator complexity because it protects the forward evidence trail from config drift being mislabeled as data revision.
   - Do not retroactively recompute old TD entries. Existing entries get the legacy marker described in the PRD.

3. Candidate Fleet Allocator third.
   - Implement v1 as shadow-first.
   - Do not route live/paper capital from the fleet allocator until the 10-trading-day shadow soak is complete and the user gives a separate explicit-go for shadow-to-live.

If the user wants Claude to begin specifically with the two latest PRDs, start with F before Fleet. That is the cleaner dependency order because the fleet layer will rely on trustworthy manifest governance.

## Non-negotiable guardrails

- Keep the forward observe daily ritual running from `TD003 -> TD010`.
- Do not mutate historical forward entries to make new snapshot fields look retroactively present.
- Do not change numeric trading thresholds unless the relevant PRD explicitly authorizes it.
- Do not let Fleet v1 become a hidden optimizer. Equal-weight / manual overrides only.
- Do not promote SPY-relative drawdown into a live throttle in v1.
- Any fleet shadow-to-live transition is a separate decision, not bundled into implementation.

## Questions back to Claude

No blocking questions.

Only implementation watchpoint: if the code path contradicts the PRD assumption about `config/regime.yaml`, pause and bring that back to Codex/user before coding around it.

