#!/bin/bash
# Start the 3-round Code + Docs Audit ralph-loop.
#
# Patched variant of dev/scripts/loop/start_codebase_audit_loop.sh —
# different lineage, different PRD, stricter guardrails around README /
# CLAUDE.md trim, mandatory pytest-tuple tracking per round.
#
# Purpose:
#   R1 — code audit: hunt bugs / unused imports / silent failures;
#        behavior-affecting fixes require a regression test.
#   R2 — README trim: strip dev-process / ralph-loop content
#        (v1.x footers, commit hashes, launcher refs, per-round
#        breadcrumbs). Keep user-facing info only.
#   R3 — CLAUDE.md slim to < 600 lines + baseline rebuild +
#        final synthesis doc + emit DOCSAUDITDONE.
#
# Reference PRD: docs/20260424-prd_docs_audit_3round.md
#
# Lineage tag:        docs-audit-2026-04-24 (all 3 rounds share)
# Max iterations:     3 (hard ceiling, one focus per round)
# Completion promise: DOCSAUDITDONE
#
# USAGE:
#   bash dev/scripts/loop/start_docs_audit_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/20260424-prd_docs_audit_3round.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD missing at $PRD_PATH"
    echo ""
    echo "This launcher expects the PRD to be committed to the repo."
    echo "Unlike the audit-v2 launcher it does NOT auto-generate."
    echo "Restore the PRD from git history:"
    echo "  git log -- $PRD_PATH"
    echo "  git checkout <sha> -- $PRD_PATH"
    exit 1
fi

# Single-line ASCII-only prompt. AUTONOMOUS MODE per PRD section 4.
PROMPT='Execute one round per docs/20260424-prd_docs_audit_3round.md section 3. lineage_tag=docs-audit-2026-04-24 for all artifacts. Round 1 = code audit plus bug fixes. Round 2 = README trim of dev-process content. Round 3 = CLAUDE.md slim under 600 lines plus baseline rebuild plus final synthesis doc plus emit DOCSAUDITDONE. AUTONOMOUS MODE: follow section 4 Authorized autonomously; pause per section 4 Must pause for user; halt per section 4 Halt conditions. Record pytest tuple passed-skipped-xfailed at the start of every round and at the end of every round; any unexpected drift not explained by a regression test added this round MUST halt the loop. Do NOT modify PRODUCTION_FACTORS or any config yaml. Do NOT add new dependencies. Do NOT rename public functions. Do NOT migrate any SQLite schema. Do NOT delete tests. Do NOT add new features or new PRDs. Each round RUNS representative code paths not just reads them. Each round commits with message docs-audit R<N>: <scope>: <summary>. Each round appends 11-part Chinese report to docs/20260420-ralph_loop_log.md as R-docs-audit-round-NN. R2 README trim must remove all v1.x footer entries, all ralph-loop commit hashes, all launcher references, all lineage tag lists, and compress section 17 to a short intro plus one bullet per phase pointing at its synthesis doc. R3 CLAUDE.md slim must move reference sections (1m pipeline, trades backfill, provenance, factor contract, multi-TF, notify) to short summaries plus pointers to docs/20260424-claude_md_phase_e_history.md, and target under 600 lines. R3 must rebuild data/baseline/latest.json via dev/scripts/baseline/build_research_baseline_snapshot.py. R3 must produce docs/20260424-docs_audit_3round_final_synthesis.md with 10 sections and end with promise tag inside the doc. R3 final assistant-turn reply MUST ALSO emit the raw DOCSAUDITDONE promise tag at top level of the reply, not only inside the synthesis doc, because the harness detects promises in assistant-turn output not in committed markdown. Emit DOCSAUDITDONE only after 3 rounds complete and pytest tuple matches baseline or drift explained by regression tests and README cleaned and CLAUDE.md under 600 lines and baseline rebuilt and final synthesis exists.'

cat <<EOF
================================================================================
3-Round Code + Docs Audit — Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
Lineage tag:         docs-audit-2026-04-24
Max iterations:      3 (hard ceiling)
Completion promise:  DOCSAUDITDONE

ROUND STRUCTURE (one focus per round):
  R1 — Code audit + bug fixes
       core/ + scripts/ + dev/scripts/ + tests/
       Scan: unused imports, silent excepts, shadowed builtins,
       dead code, bad type hints, light perf bugs, docstring drift.
       Bug fixes allowed; add regression test for each behavior-
       affecting fix. pytest tuple tracked start+end.
  R2 — README.md dev-process trim
       Remove: v1.x footers, per-round commit hashes, launcher
       references, lineage tag lists, EPOST_CAND2_DONE / AUDIT3DONE
       mentions, ralph-loop internals.
       Compress section 17 to intro + one bullet per phase -> synthesis doc.
       Verify every remaining reference resolves.
  R3 — CLAUDE.md slim + baseline rebuild + final synthesis
       Target: CLAUDE.md < 600 lines (currently 770).
       Compress: 1m pipeline / trades backfill / provenance / factor
       contract / multi-TF / notify / phase-D-if-inactive — all go
       to short summaries + archive pointers (append detail to
       docs/20260424-claude_md_phase_e_history.md).
       Rebuild data/baseline/latest.json. Write
       docs/20260424-docs_audit_3round_final_synthesis.md. Emit
       DOCSAUDITDONE.

TEST-TUPLE DRIFT POLICY (PRD §2):
  Every round logs pre/post pytest tuple (passed-skipped-xfailed).
  Allowed drift: +N for new regression tests from this round only.
  Unexpected drift -> HALT and surface to user. No silent test
  count changes.

RULES:
  - Bug fixes / dead-code removal / unused-import removal: autonomous
  - README + CLAUDE.md edits: autonomous within PRD guardrails
  - Config yaml edits / dep changes / public API renames / test
    deletion: PAUSE for user
  - No new features / PRDs / vendors

HALT CONDITIONS:
  1. 3 rounds complete (ceiling) -> emit DOCSAUDITDONE if met
  2. Unexpected pytest tuple drift
  3. Core import breaks
  4. Disk < 10 GB
  5. Finding requires schema migration or new PRD
  6. Broken reference in README or CLAUDE.md after edit
  7. Bug fix requires user decision (behavior ambiguous)

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. git status is clean:
       git status
2. Pre-audit pytest baseline (record this tuple — R1 must preserve
   or justify every delta):
       /home/zibo/miniconda3/envs/pqs/bin/python -m pytest tests/ -q --tb=no | tail -3
3. Baseline readable:
       jq '.tests' data/baseline/latest.json 2>/dev/null || echo "baseline missing — R3 will rebuild"
4. Core smoke:
       /home/zibo/miniconda3/envs/pqs/bin/python -c "from core.research.candidate_registry import CandidateRegistry; from core.factors.factor_generator import generate_all_factors; print('core OK')"
5. Disk check:
       df -h .
6. CLAUDE.md current length (R3 target < 600):
       wc -l CLAUDE.md

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE (single line, starts with /ralph-loop:ralph-loop):
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 3 --completion-promise DOCSAUDITDONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to
  docs/20260420-ralph_loop_log.md (section header: "R-docs-audit-round-NN")
- Round commit message convention:
       docs-audit R1: code audit: <N> bugs fixed + <M> unused imports
       docs-audit R2: README trim: dev-process content removed
       docs-audit R3: CLAUDE.md slim + baseline rebuild: DOCSAUDITDONE
- To pause mid-loop:
       rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- Final round R3 must:
  * Emit <promise>DOCSAUDITDONE</promise>
  * Commit CLAUDE.md + README.md + docs/*
  * Rebuild data/baseline/latest.json
  * Append final summary to docs/20260420-ralph_loop_log.md

DELIBERATE DEVIATIONS FROM audit-v2 LAUNCHER:
  D1. No auto-generate PRD (PRD is 300+ lines and already committed).
  D2. Mandatory pytest tuple tracking per round (PRD §2 drift policy).
      audit-v2 only required "no regression > 10 tests"; this PRD is
      stricter: any unexpected drift is a halt signal.
  D3. Explicit R2 = README trim scope (audit-v2 R3 did README sync
      but allowed dev-process content; this PRD explicitly forbids
      v1.x footers / launcher refs / ralph-loop breadcrumbs in README).
  D4. Explicit CLAUDE.md < 600 lines target (audit-v2 had no slim
      target; Phase E-post R8 set 800 and hit 770; this loop pushes
      further).

EOF
