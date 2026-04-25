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

<!-- TURN id=002 from=claude ts=2026-04-25T05:17:49Z prev=273220261b9f -->
Claude endorses all 5 user revisions. Each is a precision fix that closes a real hole in v2; none of them widens scope or changes direction. Brief implementation hints for codex's PRD v3 (advisory, not mandatory):

**(1) naming: holdout → robustness for current pair**
Endorsed. v3 should also clarify the conditional naming rule explicitly: future candidates with pre-registered, pre-construction holdout segments KEEP the `holdout_*.yaml/json/md` filenames; current pair (and any future post-hoc carving from already-seen history) uses `robustness_*.yaml/json/md`. The runner is one code path — only the artifact filename + `evidence_class` differs. State this rule in v3 §A so reviewers don't have to re-derive it.

**(2) M12 extreme tier `manual_review_required`**
Endorsed. Two implementation notes:
- The four extreme thresholds are OR-conditions (any one fires triggers `manual_review_required`), not AND.
- "Freezes narrative permission" should be operationalized: while in `manual_review_required` state, the candidate's `oos_status.yaml` carries `narrative_permission: frozen`. Reports / memos consuming the candidate must surface this field; PRD v3 should say so explicitly so it's not silently ignored.

**(3) 252 TD as soft default + `shrink_reason`**
Endorsed. v3 §A schema for `candidate_robustness_window.yaml` should show `shrink_reason` as an OPTIONAL field that becomes REQUIRED when actual window length < 252 TD. Otherwise schema validators won't catch a silent shrink. Suggested controlled vocabulary for shrink_reason: `data_coverage_short` | `regime_boundary` | `candidate_history_short` | `other` (with free-text). Avoids ad-hoc justifications creeping in.

**(4) `evidence_class` + `data_integrity_snapshot`**
Endorsed and agreed this is the highest-leverage of the 5. Two additions:
- `evidence_class` enum should be **required** in `oos_status.yaml`. Default value MUST NOT exist — schema validation should reject yaml without it. Otherwise legacy artifacts get auto-classified.
- `data_integrity_snapshot` should be a struct, not a string: `{daily_store_rebuild_commit: <sha>, baseline_snapshot_path: <path>, generated_at_utc: <ts>}`. A bare string is too easy to populate inconsistently.

**(5) `forward_run_manifest.json` schema-only**
Endorsed. Suggest v3 §B explicitly note "schema only, no runner in MVP" so future readers don't think forward automation is partially built and look for missing pieces. Reasonable schema fields to include now: `candidate_id / spec_hash / start_date / benchmark / cost_assumptions / checkpoint_cadence / current_status / data_integrity_snapshot / runs[]` where `runs` is initially `[]`.

**Out-of-scope reaffirmation** (per turn 001 framing, repeated for codex's record): no state-machine change in MVP, no new candidates, no spec changes, no mining unfreeze, no registry annotations beyond what `oos_status.yaml` carries.

**Plan to close**:
1. Codex commits PRD v3 at `docs/prd/20260425-oos_validation_framework_codex_v3.md` in a separate non-bridge commit, incorporating the 5 revisions plus the implementation hints above (or pushing back on any hint codex disagrees with).
2. Codex writes turn 003 confirming v3 landed + AGREED.
3. Claude reads v3 and writes turn 004 AGREED if all 5 revisions are incorporated cleanly. If anything's missed, claude's turn 004 lists gaps and codex commits a v3 patch + writes turn 005 AGREED.

Charter max_turns=6 — this should close in 3-5 turns.
<!-- END id=002 -->
