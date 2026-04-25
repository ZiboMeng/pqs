# Claude <-> Codex bridge

Topic: Review codex's OOS Validation Framework PRD v1 (post-data-integrity round-3)
Started: 2026-04-25T05:00:00Z
Charter: max_turns=12 | escalate_to_user_when=any of {7 review points} not converging in 3 round-trips, spec/registry change scope creep, claude or codex writes ESCALATE, or either side has low confidence | end_condition=both sides AGREED on a revised PRD (codex commits the revision separately) OR user appends final=true OR escalation fires

---

<!-- TURN id=001 from=user ts=2026-04-25T05:04:02Z prev=GENESIS -->
User opens a new bridge conversation to review codex's OOS Validation Framework PRD v1 (full text saved at `docs/prd/20260425-oos_validation_framework_codex_v1.md`).

Context:
- round-3 data-integrity workstream is closed (`docs/memos/20260425-data_integrity_round3_close.md`)
- 2022 Cand-2 NAV honestly re-baselined +74.57% → +3.47%; the bigger lesson is that the old historical narrative was inflated by data bugs
- codex authored the PRD as the natural next step: build a real OOS framework before unfreezing universe/mining/Candidate-3 work

Claude has read the PRD and prepared a structured 7-point review which will appear in turn 002 from=claude. Codex's turn 003 should respond to claude's points (point-by-point or in a block, codex's choice) and either propose a revised PRD or push back on specific points.

Charter (already at the top of this file):
- max_turns=12
- escalate when any of the 7 points fails to converge after 3 round-trips, or when spec/registry change scope creep, or low confidence, or ESCALATE token
- end when both sides AGREED on a revised PRD (codex commits the revision in a separate commit, not inside the bridge)
<!-- END id=001 -->
