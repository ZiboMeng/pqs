# Revoke memo — rcm_v1_clone_drill_superseded

**Drill type**: E-post-4 revoke drill (clone only — never touches real rcm_v1)
**Reason**: `candidate_superseded`
**Decided at**: 2026-04-24 (drill)

## Supporting artifacts
- Drill registry: `data/research_candidates/drill_registry.db`
- Clone of: `rcm_v1_defensive_composite_01` (real, untouched at S2_paper)
- PRD: `docs/20260424-prd_phase_e_post_cand2.md` §4.4

## Decision rationale
Simulates the most common future revoke case — a newer candidate supersedes
the old one. Target state: `S5_deprecated`. No rollback / retry intended.

## Impact
- Paper artifacts retained (original frozen spec + memo on disk for audit)
- New promotions should point at the superseding candidate
- Registry search by status should exclude S5 by default

## Follow-up
None (terminal state).
