#!/bin/bash
# Start the 7-round OOS MVP ralph-loop.
#
# Implements PRD docs/prd/20260425-oos_mvp_ralph_loop_execution.md, which
# decomposes PRD v3 (docs/prd/20260425-oos_validation_framework_codex_v3.md)
# into a ralph-loop-friendly 7-round execution plan.
#
# Round structure:
#   R1 - robustness window schema + runner skeleton + 5+ schema tests
#   R2 - robustness_eval real run on RCMv1 + Cand-2 (artifacts per candidate)
#   R3 - M12 concentration report module (warning + extreme tier; report-only)
#   R4 - watch exposure section in master_report + paper_drift_report
#   R5 - forward manifest SCHEMA-ONLY (no runner)
#   R6 - integration smoke + negative-result simulation
#   R7 - docs sync + baseline rebuild + emit OOSMVPDONE
#
# Lineage tag:        oos-mvp-2026-04-25 (all 7 rounds share)
# Max iterations:     8 (7 rounds + 1 retry buffer)
# Completion promise: OOSMVPDONE
#
# USAGE:
#   bash dev/scripts/loop/start_oos_mvp_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/prd/20260425-oos_mvp_ralph_loop_execution.md"
PRD_V3_PATH="docs/prd/20260425-oos_validation_framework_codex_v3.md"
UNFREEZE_MEMO="docs/memos/20260425-oos_framework_unfreeze.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD missing at $PRD_PATH"
    exit 1
fi
if [[ ! -f "$PRD_V3_PATH" ]]; then
    echo "ERROR: PRD v3 missing at $PRD_V3_PATH"
    exit 1
fi
if [[ ! -f "$UNFREEZE_MEMO" ]]; then
    echo "ERROR: unfreeze memo missing at $UNFREEZE_MEMO -- OOS framework workstream is still frozen"
    exit 1
fi

# Single-line ASCII-only prompt. AUTONOMOUS MODE per PRD section 4.
PROMPT='Execute one round per docs/prd/20260425-oos_mvp_ralph_loop_execution.md section 3. lineage_tag=oos-mvp-2026-04-25 for all artifacts. Round 1 = robustness window schema (core/research/robustness/window_spec.py) + runner skeleton (NotImplementedError stub) + 5+ schema validation tests. Round 2 = robustness_eval real runner + run on RCMv1 + Cand-2; produces candidate_robustness_window.yaml + robustness_eval.{json,md} per candidate; evidence_class=pseudo_oos_robustness. Round 3 = M12 concentration report module (warning + extreme tier per PRD v3 sec C); integrated into R2 runner; report-only NO hard block; 8+ tier classification tests. Round 4 = Watch exposure section integration into core/reporting/master_report.py + scripts/paper_drift_report.py; top-table + prose; graceful degrade if watch sidecar missing. Round 5 = Forward manifest SCHEMA-ONLY (core/research/forward/manifest_schema.py); NO runner code per PRD v3 sec B. Round 6 = Integration smoke (dev/scripts/oos_mvp/smoke.py) end-to-end on both candidates + negative-result simulation (set evidence_class=historical_replay and verify schema validator rejects). Round 7 = Docs sync (CLAUDE.md TODO entry, docs/INDEX.md, docs/memos/20260425-oos_mvp_close.md with pseudo-OOS framing NOT deployable-OOS framing) + baseline rebuild via dev/scripts/baseline/build_research_baseline_snapshot.py --run-tests; emit OOSMVPDONE at top level of assistant reply. AUTONOMOUS MODE per PRD section 4: authorized in core/research/{robustness,concentration,forward}/, tests/unit/research/, tests/unit/reporting/, tests/integration/, data/research_candidates/, dev/scripts/oos_mvp/, R4 watch-exposure hooks in core/reporting/master_report.py and scripts/paper_drift_report.py, CLAUDE.md / docs/INDEX.md / docs/memos/, baseline JSON rebuild. Must Pause: HARD invariant violation; same round retried twice; pytest drift not explained by regression tests added this round; round runs over 30 min; artifact size anomaly. HARD INVARIANTS: do NOT modify config/*.yaml or PRODUCTION_FACTORS or requirements*.txt or pyproject.toml; do NOT rename public functions; do NOT migrate registry.db schema; do NOT delete tests; do NOT modify candidate_registry state-machine enum; do NOT modify core/research/frozen_spec.py; do NOT modify any frozen candidate spec; do NOT rebuild data/daily/*.parquet; do NOT modify data/ref/splits.parquet; do NOT start work outside R1-R7 scope. PYTEST DRIFT RULE: record pytest tuple (passed, skipped, xfailed) at start AND end of every round; any drift not explained by regression tests added this round MUST halt loop. PER-ROUND COMMIT MESSAGE FORMAT: oos-mvp R<N>: <scope>: <summary>. PER-ROUND CHINESE REPORT: append 11-part report to docs/20260420-ralph_loop_log.md as R-oos-mvp-2026-04-25-round-NN per existing convention. R7 closeout memo MUST frame R1-R6 results as pseudo-OOS robustness eval done; MUST NOT frame as OOS validated or deployable evidence; MUST link to PRD v3 sec 1.1 + sec 1.3. Emit OOSMVPDONE only when: 7 rounds committed; pytest no unexplained drift; baseline rebuilt with --run-tests; both candidates have full artifact set (robustness_window.yaml + robustness_eval.{json,md} + concentration_report.{json,md}); master_report.py and paper_drift_report.py both render watch exposure section; forward manifest schema validator works but no runner code; docs/memos/20260425-oos_mvp_close.md exists with pseudo-OOS framing; CLAUDE.md TODO updated; docs/INDEX.md updated; R7 reply emits literal promise tag at top level (not only inside committed markdown).'

cat <<EOF
================================================================================
7-Round OOS MVP -- Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
PRD v3:              $PRD_V3_PATH
Unfreeze memo:       $UNFREEZE_MEMO
Lineage tag:         oos-mvp-2026-04-25
Max iterations:      8 (7 rounds + 1 retry buffer)
Completion promise:  OOSMVPDONE

ROUND STRUCTURE (one focus per round; gate must pass before next round):
  R1 -- robustness window schema + runner skeleton (NotImplementedError stub)
        + 5+ schema validation tests in tests/unit/research/
  R2 -- robustness_eval real runner on RCMv1 + Cand-2
        artifacts: candidate_robustness_window.yaml + robustness_eval.{json,md}
        evidence_class = pseudo_oos_robustness (NOT deployable OOS)
  R3 -- M12 concentration report (warning + extreme tier, report-only no block)
        integrated into R2 runner; 8+ tier classification tests
  R4 -- watch exposure section in master_report.py + paper_drift_report.py
        top-table + prose, graceful degrade if watch sidecar missing
  R5 -- forward manifest SCHEMA-ONLY (core/research/forward/manifest_schema.py)
        explicitly NO runner code per PRD v3 sec B
  R6 -- integration smoke end-to-end on both candidates + negative simulation
        (evidence_class=historical_replay must be rejected)
  R7 -- docs sync (CLAUDE.md / INDEX.md / closeout memo) + baseline rebuild
        + emit <promise>OOSMVPDONE</promise> at top level of reply

PYTEST DRIFT RULE (PRD section 2):
  Every round logs pre/post pytest tuple (passed-skipped-xfailed).
  Allowed drift: +N for new regression tests from this round only.
  Unexpected drift -> HALT and surface to user. No silent test count changes.

HARD INVARIANTS (violation halts loop):
  - no edits to config/*.yaml, PRODUCTION_FACTORS, requirements*.txt,
    pyproject.toml, registry.db schema, candidate_registry state-machine,
    core/research/frozen_spec.py, frozen candidate spec yaml,
    data/daily/*.parquet, data/ref/splits.parquet
  - no public function renames
  - no test deletions
  - no work outside R1-R7 scope

HALT CONDITIONS:
  1. Any HARD invariant violated
  2. Same round retried twice
  3. Pytest drift not explained by this round's regression tests
  4. Single round runtime > 30 min
  5. Artifact size anomaly (single file > 10 MB or cumulative > 100 MB)
  6. OOSMVPDONE successfully emitted (clean exit)

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. git status is clean:
       git status
2. Pre-loop pytest baseline (record this tuple -- R1 must preserve
   or justify every delta via regression tests added this round):
       /home/zibo/miniconda3/envs/pqs/bin/python -m pytest tests/ -q --tb=no | tail -3
3. Baseline readable:
       jq '.tests' data/baseline/latest.json
4. Core smoke:
       /home/zibo/miniconda3/envs/pqs/bin/python -c "from core.research.candidate_registry import CandidateRegistry; print('core OK')"
5. Disk check:
       df -h .
6. Unfreeze memo present (workstream must be unfrozen before launch):
       test -f $UNFREEZE_MEMO && echo "OOS framework unfrozen" || echo "MISSING -- workstream still frozen"

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE (single line, starts with /ralph-loop:ralph-loop):
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "\$PROMPT" --max-iterations 8 --completion-promise OOSMVPDONE

EOF

# Print the slash command WITH the prompt expanded so user can copy in one shot.
echo "--------------------------------------------------------------------------------"
echo "Or expanded version (copy this whole line):"
echo "--------------------------------------------------------------------------------"
echo
echo "/ralph-loop:ralph-loop \"$PROMPT\" --max-iterations 8 --completion-promise OOSMVPDONE"
echo
cat <<EOF
--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to
  docs/20260420-ralph_loop_log.md (section header: "R-oos-mvp-2026-04-25-round-NN")
- Round commit message convention:
       oos-mvp R1: robustness window schema + runner skeleton
       oos-mvp R3: M12 concentration report module + integration
       oos-mvp R7: docs sync + baseline rebuild + closeout memo
- To halt mid-loop:
       rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- Final round R7 must:
  * Emit <promise>OOSMVPDONE</promise> at TOP LEVEL of assistant reply
    (not only inside committed markdown)
  * Commit closeout memo + CLAUDE.md TODO update + INDEX.md update
  * Rebuild data/baseline/latest.json via --run-tests
  * Verify both candidates have full artifact set:
    robustness_window.yaml + robustness_eval.{json,md} +
    concentration_report.{json,md}

EOF
