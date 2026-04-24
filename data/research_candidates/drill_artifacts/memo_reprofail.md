# Revoke memo — rcm_v1_clone_drill_reprofail

**Drill type**: E-post-4 revoke drill (clone only — never touches real rcm_v1)
**Reason**: `reproducibility_failed`
**Decided at**: 2026-04-24 (drill)

## Supporting artifacts
- Drill registry: `data/research_candidates/drill_registry.db`
- Clone of: `rcm_v1_defensive_composite_01` (real, untouched at S2_paper)
- PRD: `docs/20260424-prd_phase_e_post_cand2.md` §4.4

## Decision rationale
Exercises the special `reproducibility_failed` path. Per
`core/research/candidate_registry.py:394-397`, this reason reverts the
candidate to `S0_prototype` instead of going to `S5_deprecated` — the
"we failed to reproduce, back to prototype for retry" branch.

## Impact
- Candidate is NOT terminally dead; it returns to S0 for re-investigation
- `revoke_reason` + `revoke_memo_path` are still recorded for audit
- `revoked_at` is set; future promoters should consult it before re-promoting

## Follow-up
If a retry investigation clears the repro issue, a new promote should
re-advance the candidate from S0 through the normal gate pipeline. The
revoke row remains in the audit trail even after re-promotion.
