# Claude <-> Codex bridge

Topic: OOS PRD v2 → v3 final review (5 small revisions before MVP open)
Started: 2026-04-25T05:15:00Z
Charter: max_turns=6 | escalate_to_user_when=any of the 5 revisions not converging in 2 round-trips, scope creep beyond the 5 named items, claude or codex writes ESCALATE | end_condition=codex commits PRD v3 in a separate non-bridge commit AND both sides AGREED

---

<!-- TURN id=001 from=user ts=2026-04-25T05:15:49Z prev=GENESIS -->
User reviewed `docs/prd/20260425-oos_validation_framework_codex_v2.md` and approves overall direction + scope. Five small revisions requested before MVP opens; codex to commit PRD v3 with these changes in a separate non-bridge commit.

**Revision 1 — naming: drop `holdout` for current pair, use `robustness / pseudo-OOS` instead**

The current pair's historical segment is not a strict-OOS holdout. PRD v2 §1.1 already labels it pseudo-OOS / narrative robustness segment, but file/artifact names still say `holdout`. Internal inconsistency. Rename for current pair only:

- `candidate_holdout_spec.yaml` → `candidate_robustness_window.yaml`
- `holdout_eval.json` → `robustness_eval.json`
- `holdout_eval.md` → `robustness_eval.md`

Reserve `holdout` naming for future candidates whose holdout segment is pre-registered before construction (true holdout). The MVP runner can support both via the same code path; only the artifact filename differs by `evidence_class`.

**Revision 2 — M12 not pure report-only: add a `manual_review_required` escalation tier for extreme values**

PRD v2 currently says MVP is report-only. Keep that for normal cases, but extreme concentration must not be silent. Add:

- top-1 > 50% OR
- top-3 > 80% OR
- thin-data exposure > 10% OR
- watch-list single-name weight-day share > 15%

→ classify as `manual_review_required`. This does NOT auto-block, but it DOES freeze narrative permission — the candidate cannot be written up as "strengthened by holdout / robustness eval" until user resolves the review. Distinct from (4) warning thresholds, which are softer.

**Revision 3 — `252 TD` is a default target, not a hard rule**

Keep the deterministic-segment principle (no hand-picking clean regimes). But:

- default target = 252 TD
- if data coverage / candidate history / valid-window constraints make 252 TD impossible, allow shorter window AND require a documented `shrink_reason` field in the robustness window spec
- avoids forced unnatural splicing to hit 252

**Revision 4 — `oos_status.yaml` adds two fields**

Both fields directly codify round-3 lessons:

- `evidence_class`: enum of `historical_replay | pseudo_oos_robustness | forward_oos`. Reports must consume this so a pseudo-OOS robustness number is never displayed as OOS evidence. This is the structural defense against "pseudo-OOS read as OOS" — the chronic trap PRD v2 §1.3 warns about.
- `data_integrity_snapshot`: pointer to the daily store rebuild version / baseline hash / snapshot timestamp at which the eval ran. After a future store rebuild, any artifact tied to this field anchors back to the data state used. Without this field, post-rebuild interpretation drifts silently.

**Revision 5 — `forward_run_manifest.json` schema defined now even though MVP doesn't run it**

MVP does not include forward automation, accepted. But pre-defining the schema for `forward_run_manifest.json` (fields: candidate_id / start_date / spec_hash / benchmark / cost_assumptions / checkpoint_cadence / current_status / data_integrity_snapshot / etc.) saves contract churn later when forward actually starts. Add to PRD v3 §B as "schema only, not yet wired".

**Out-of-scope for these 5**:
- No state-machine change (deferred to post-MVP per v2 §6 module E ruling)
- No new candidates / no Candidate-3 / no spec changes / no mining / no universe extension
- No registry annotations beyond what oos_status.yaml expresses

Codex to confirm acceptance / request adjustments. If accepted as-is, codex commits PRD v3 in a separate non-bridge commit (`docs/prd/20260425-oos_validation_framework_codex_v3.md`) and writes AGREED. Claude follows with AGREED if v3 incorporates the 5 revisions cleanly.
<!-- END id=001 -->
