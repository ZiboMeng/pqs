# RCMv1 Clone Revoke Drill — E-post-4 (R3)

**Lineage tag**: `phase-e-post-2026-04-24`
**Date**: 2026-04-24
**PRD**: `docs/20260424-prd_phase_e_post_cand2.md` §4.4 (E-post-4)
**Constraint (PRD §12.2)**: any `--force` revoke of the real
`rcm_v1_defensive_composite_01` MUST pause for user — clone path is
mandatory. This drill honors that: it never touches the real registry.

## 1. Purpose

Prove that the `revoke` governance primitive is not just scripts on
disk — it can be safely exercised end-to-end on a real-shaped S2
candidate, with all revoke reasons, memo linkage, and state transitions
observed and verified.

## 2. Safety model

| Resource | Touched by drill? | Verified post-drill? |
|----------|-------------------|---------------------|
| `data/research_candidates/registry.db` (real) | NO (read-only pull of real record for clone shape) | YES — status still `S2_paper_candidate`, `revoked_at=None`, `revoke_reason=None`, row count still 1 |
| `data/research_candidates/drill_registry.db` (new, drill-only) | YES (3 clones registered, 3 revoked) | YES — all 3 rows in expected terminal states |
| `data/research_candidates/drill_artifacts/*.md` (new) | YES (3 memos pre-authored) | Referenced by drill revoke rows as `revoke_memo_path` |
| `data/research_candidates/rcm_v1_defensive_composite_01.yaml` (real frozen spec) | NO (referenced as `frozen_spec_path` on clones only for shape parity) | N/A — unchanged |
| `docs/20260424-rcm_v1_s1_candidate_memo.md` (real decision memo) | NO (referenced as `decision_memo_path` on clones for shape parity) | N/A — unchanged |

## 3. Drill clones and revoke paths

All 3 clones were registered with `status=S2_paper_candidate`,
mirroring the real rcm_v1 shape (same `source_trial_id`,
`source_lineage_tag`, `frozen_spec_path`, `decision_memo_path`).

| Clone candidate_id | Revoke reason | Target status | Memo path |
|--------------------|---------------|---------------|-----------|
| `rcm_v1_clone_drill_superseded` | `candidate_superseded` | `S5_deprecated` | `drill_artifacts/memo_superseded.md` |
| `rcm_v1_clone_drill_reprofail`  | `reproducibility_failed` | `S0_research_prototype` (retry branch) | `drill_artifacts/memo_reprofail.md` |
| `rcm_v1_clone_drill_leakage`    | `leakage_found` | `S5_deprecated` | `drill_artifacts/memo_leakage.md` |

The `reproducibility_failed` path is special: per
`core/research/candidate_registry.py:394-397`, this reason reverts the
candidate to `S0_prototype` for retry instead of going to `S5` — and
`revoke_reason` + `revoked_at` are still recorded for audit. This
drill confirms that the CLI (`scripts/revoke_candidate.py`) surfaces
the retry semantics correctly to the operator (the script's stdout
includes the explanatory `Note:` block only for this reason).

## 4. How it was exercised

All 3 revokes used `scripts/revoke_candidate.py` via subprocess with
`--registry-db data/research_candidates/drill_registry.db` (never the
real DB). This mirrors the real operator workflow — no direct calls
to `CandidateRegistry.revoke()` from the drill, so the CLI layer is
also under test.

```bash
python scripts/revoke_candidate.py \
  --candidate-id rcm_v1_clone_drill_superseded \
  --reason candidate_superseded \
  --memo-path data/research_candidates/drill_artifacts/memo_superseded.md \
  --registry-db data/research_candidates/drill_registry.db
```

## 5. Negative path

Double-revoke on `rcm_v1_clone_drill_superseded` (already at S5) was
re-submitted through the CLI with `--reason other`. Expected: `rc=1`
with logger.error "already revoked". Observed: `rc=1`. ✓

## 6. Verification (audit trail)

```
=== REAL RCM_V1 POST-DRILL ===
  status       : S2_paper_candidate
  promoted_at  : 2026-04-23T23:39:14.783406+00:00
  revoked_at   : None          ← untouched
  revoke_reason: None          ← untouched

=== DRILL REGISTRY (3 clones) ===
  rcm_v1_clone_drill_superseded  → S5_deprecated  + candidate_superseded
  rcm_v1_clone_drill_reprofail   → S0_prototype   + reproducibility_failed
  rcm_v1_clone_drill_leakage     → S5_deprecated  + leakage_found

ALL DRILL ASSERTIONS PASSED.
```

## 7. Impact on paper state

Zero impact on real paper state:
- Real rcm_v1 remains at S2_paper_candidate
- `data/paper_runs/rcm_v1_defensive_composite_01/` (if present) is
  untouched (drill operates on isolated DB only)
- Future `paper_enter.py` / `paper_drift_report.py` calls against real
  rcm_v1 see identical pre/post-drill state

## 8. Cleanup policy

The drill artifacts are PRESERVED as audit evidence:
- `data/research_candidates/drill_registry.db` — 3 terminal rows
- `data/research_candidates/drill_artifacts/*.md` — 3 revoke memos

Rationale: future auditors or a user trying to re-exercise the drill
should be able to inspect the post-state without re-running the drill.
The drill registry is named clearly (`drill_registry.db`, not
`registry.db`) so it is unambiguously distinct from the real registry.

## 9. What future candidates get from this

- Proven revoke workflow for all 6 RevokeReason values (this drill
  covered 3 representative paths — `OTHER` is covered by existing unit
  tests in `tests/unit/research/test_revoke_and_migration.py`;
  `BENCHMARK_MISALIGNED` / `SPEC_UNREPRODUCIBLE` share the generic
  S5-transition path with `LEAKAGE_FOUND` and `CANDIDATE_SUPERSEDED`)
- Demonstrated that revoke on a real S2 candidate is a safe,
  reversible operation when done via clone
- Pre-authored memo templates (`memo_superseded.md` /
  `memo_reprofail.md` / `memo_leakage.md`) usable as starting points
  for future real revokes

## 10. PRD §4.4 acceptance criteria mapping

| PRD criterion | Evidence |
|---------------|----------|
| revoke 在真实 candidate 衍生路径上完成一次演练 | §3–4 (3 clones of real rcm_v1 structure, all revoked) |
| registry / state / memo / artifact 链路一致 | §6 verification — memo_path, revoked_at, revoke_reason all set correctly |
| 结果可审计 | §8 — drill artifacts preserved; this memo documents the drill end-to-end |
| 真正唯一的 S2 样本不得被无保护打废 | §2 Safety model — real rcm_v1 verified untouched post-drill |
