---
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: D.0 + D.1
round: R10
status: D.1 PRD DRAFT SHIPPED — D.2-D.4 GATED on master PRD §4.4 D.0
date: 2026-05-08
operator: zibomeng (Claude Opus 4.7)
---

# Phase D.0 gate check + Phase D.1 fleet allocator PRD draft

## TL;DR

Per master PRD `docs/prd/20260506-cycle07_to_fleet_master_prd.md` v1.1
§4.4 Phase D.0 gate prerequisites:

| Gate | Status as of 2026-05-08 |
|---|---|
| (a) ≥1 nominee from R2 (cycle07a) OR R8 (cycle08) passes Track A | **NOT MET** — cycle07a 0 nominee per R5; cycle08 mining smoke-level (40 trials) still in progress |
| (b) Trial9 forward TD60 GREEN per CLAUDE.md ~2026-07-30 | **NOT MET** — Trial9 at TD003 (~57 TD remaining to TD60) |

→ **D.2-D.4 implementation STAYS PAUSED**. Per master PRD §4.4 D.0
exception ("If neither (a) nor (b) holds at week 5, Phase D.1 PRD writing
STILL can start"), this round ships **D.1 PRD draft only** at
`docs/prd/20260508-fleet_allocator_prd_draft.md`.

## D.1 PRD draft contents

Architectural reference for fleet allocator implementation when D.0
prerequisites are satisfied:

1. **Sleeve definition**: `Sleeve` dataclass + `SleeveRole` enum
   (ALPHA / DEFENSIVE / FORWARD_OBSERVATION)
2. **FleetAllocator class**: regime-driven sleeve weight blending
   with EMA(20) smoothing
3. **Default 3-sleeve fleet**: alpha (cycle07a/cycle08-style) +
   defensive (TAA V1) + forward observation (Trial9 post-TD60)
4. **Regime allocation table**: BULL 70/20/10 → CRISIS 10/70/20
5. **Acceptance criteria**: sleeve-level + fleet-level Track A +
   pair-correlation < 0.85 + sealed 2026 final
6. **Cost model**: existing per-sleeve + 1bp inter-sleeve transition
7. **Reversibility**: pure new module, deletion = revoke

## Next-step trigger logic (when D.0 satisfied)

D.0 gate (a) earliest: cycle08 (R8/R9) produces a nominee passing
Track A. Or future cycle09+ (post-universe-expansion if Phase E
authorized).

D.0 gate (b) earliest: ~2026-07-30 (Trial9 TD60 milestone).

D.4 smoke earliest: ~2026-08-15 (assuming D.0 satisfied by 2026-07-30
+ D.2-D.3 ~2 weeks).

## Self-Audit (R1/R2/R3/R4)

### R1 — factual

- D.1 PRD draft committed at `docs/prd/20260508-fleet_allocator_prd_draft.md`
  (~250 lines)
- D.0 gate (a) status verified: cycle07a 0 nominee (R5 commit `98ead2c`);
  cycle08 mining smoke-level in progress at PRD writing
- D.0 gate (b) status verified: Trial9 at TD003 per CLAUDE.md
- Master PRD §4.4 D.0 exception ("D.1 can start at week 5 even if gates
  not met") allows this PRD writing

### R2 — logical

- Both D.0 gates NOT MET → D.2-D.4 cannot start (per master PRD §4.4)
- D.1 PRD writing IS allowed (per §4.4 exception clause)
- This memo accurately reflects gate status; PRD draft scopes future
  implementation when gates satisfy
- No CLAUDE.md invariant change; no production config touch

### R3 — actually-run

- D.1 PRD draft written + saved to `docs/prd/`
- This memo written + saved to `docs/memos/`
- No code changes; no pytest needed

### R4 — boundary

- **What if cycle08 R8 produces a nominee?** Gate (a) satisfies →
  partial gate satisfaction. Still need (b) by 2026-07-30. D.2 stays
  paused until BOTH satisfy.
- **What if Trial9 hits TD60 RED (~2026-07-30)?** Gate (b) NOT MET →
  D.2-D.4 remain paused. Fleet design needs new forward observation
  candidate.
- **What if cycle08 also 0 nominee + Trial9 RED?** Strategic pivot per
  master PRD §6 Risks Phase E options (universe expansion / longer
  horizon / cross-cycle ensemble) — out of master PRD ralph-loop scope.

### Self-audit verdict

PASS. D.0 gate status accurately reported; D.1 PRD draft shipped per
master PRD authorized scope.

## Reversibility

D.1 PRD is a doc-only artifact. No code changes. Future revocation =
delete `docs/prd/20260508-fleet_allocator_prd_draft.md` + revert this
memo + revert log entry.

## Lineage

`cycle07-to-fleet-master-2026-05-06` round 10 of 13. R10 ships
this round. Next: R11 + R12 + R13 audits.
