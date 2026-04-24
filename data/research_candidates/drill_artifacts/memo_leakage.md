# Revoke memo — rcm_v1_clone_drill_leakage

**Drill type**: E-post-4 revoke drill (clone only — never touches real rcm_v1)
**Reason**: `leakage_found`
**Decided at**: 2026-04-24 (drill)

## Supporting artifacts
- Drill registry: `data/research_candidates/drill_registry.db`
- Clone of: `rcm_v1_defensive_composite_01` (real, untouched at S2_paper)
- PRD: `docs/20260424-prd_phase_e_post_cand2.md` §4.4
- Real-world analogue: R15 RCMv1 lag fix (pre-lag IC_IR was +4.77, true IC
  with `lag=1` was +0.50 — had we failed to catch it, this would have
  required exactly this revoke path in production)

## Decision rationale
Simulates the most dangerous revoke scenario — post-promote structural
leakage detected. Target state: `S5_deprecated`. A leaky candidate
cannot be retried; it must be explicitly excluded from future searches
and marked in the registry so lineage audits can reconstruct what
happened.

## Impact
- Paper runs halted (in real flow, `paper_drift_report.py` would flag
  divergence first)
- All downstream strategies referencing this candidate must be audited
- New candidates in the same feature family should carry a
  leakage-aware reviewer checklist
- Any production deploy referencing the leaky candidate must be rolled
  back (none in Phase E — production wiring deferred to post-PRD)

## Follow-up
- Add regression test for the specific leakage pattern
- Update leakage-detector heuristics in the acceptance pack
- File lineage tag for the leakage finding so future candidates are
  checked against it
