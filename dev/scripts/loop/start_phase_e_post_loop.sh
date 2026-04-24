#!/bin/bash
# Start the 8-round Phase E-post + Candidate-2 ralph-loop.
#
# Purpose: collect the 5 real Phase E remaining gaps (E-post-1..5),
# construct a 3-factor equally-weighted orthogonal Candidate-2 purely
# from existing RESEARCH_FACTORS, traverse S0->S1->S2 for it, run it
# in paper alongside RCMv1 as a comparison reference frame, then do
# an exhaustive R7 audit + R8 docs slimming.
#
# Reference PRD: docs/20260424-prd_phase_e_post_cand2.md
#
# Lineage tag:        phase-e-post-2026-04-24 (all 8 rounds share)
# Target rounds:      8 (one focus per round)
# Max iterations:     10 (8 + 2 buffer)
# Completion promise: EPOST_CAND2_DONE
#
# USAGE:
#   bash dev/scripts/loop/start_phase_e_post_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/20260424-prd_phase_e_post_cand2.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD missing at $PRD_PATH"
    echo ""
    echo "This launcher expects the PRD to be committed to the repo."
    echo "Unlike the audit launcher it does NOT auto-generate (too long)."
    echo "Restore the PRD from git history:"
    echo "  git log -- $PRD_PATH"
    echo "  git checkout <sha> -- $PRD_PATH"
    exit 1
fi

# Single-line ASCII-only prompt. AUTONOMOUS MODE per PRD section 12.
PROMPT='Execute one round per docs/20260424-prd_phase_e_post_cand2.md section 10.3 Round map. lineage_tag=phase-e-post-2026-04-24 for all artifacts. Round 1 = E-post-3 deps. Round 2 = E-post-5A migration hermetic. Round 3 = E-post-4 revoke drill on rcm_v1 clone only never real S2. Round 4 = E-post-1 paper path decouple MarketDataStore. Round 5 = E-post-2 research mask unification AND invariant diff verify on post-2026-04-24-rcm-v1-lag1 eligibility set MUST be bit for bit identical. Round 6 = Candidate-2 construction 3 factors equally weighted 1 over 3 each NO TPE NO Optuna NO grid search plus full S0 to S1 to S2 traversal via freeze_research_candidate.py then research_promote.py then paper_enter.py and kick off paper run. Round 7 = exhaustive code audit on all R1 to R6 touched files AST scan for unused imports silent excepts shadowed builtins plus full pytest plus --help smoke sweep plus core/research and core/paper_trading and core/data full import sweep. Round 8 = docs sync README.md v1.4 footer plus CLAUDE.md slim to under 800 lines by archiving completed phase tables to docs/20260424-claude_md_phase_e_history.md plus final synthesis doc docs/20260424-phase_e_post_cand2_final_synthesis.md then emit EPOST_CAND2_DONE. AUTONOMOUS MODE: follow section 12.1 Authorized autonomously; pause per section 12.2 MUST pause for user. Halt per section 12.3. Do NOT modify PRODUCTION_FACTORS or config/production_strategy.yaml. Do NOT modify scripts/promote_strategy.py semantics. Do NOT mutate archive.db or rcm_archive.db schema. Do NOT force revoke real rcm_v1_defensive_composite_01 use clone path only. Do NOT add new vendor or data layer or broker. Do NOT extend universe. Do NOT open new factor mining. Do NOT do heavy model research. Each round RUNS representative code paths with tests not just reads them. Each round commits with message phase-e-post R<N>: <scope>: <summary>. Each round appends 11-part Chinese report to docs/20260420-ralph_loop_log.md as R-epost-cand2-round-NN. Emit EPOST_CAND2_DONE only after all 8 rounds complete and full test suite passes and Candidate-2 registry state is S2 or rejection memo exists and paper run artifacts exist and README plus CLAUDE.md synced and final synthesis doc exists.'

cat <<EOF
================================================================================
Phase E-post + Candidate-2 8-Round Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
Lineage tag:         phase-e-post-2026-04-24
Target rounds:       8
Max iterations:      10 (8 + 2 buffer)
Completion promise:  EPOST_CAND2_DONE

ROUND MAP (one focus per round):
  R1 — E-post-3  deps audit + requirements.txt refresh
                 (~0.5d, lowest risk, fastest green light)
  R2 — E-post-5A migration hermetic (inject archive path)
                 (~0.5d, small bug, easy to verify)
  R3 — E-post-4  revoke drill on rcm_v1 CLONE (never real S2)
                 (~0.5d, pure governance exercise)
  R4 — E-post-1  paper path decouple from MarketDataStore
                 (~1-1.5d, medium refactor)
  R5 — E-post-2  research mask unification + invariant diff=0
                 on post-2026-04-24-rcm-v1-lag1 eligibility set
                 (~1.5-2d, highest risk, last)
  R6 — Candidate-2: 3 factors equally-weighted (1/3 each)
                 from existing RESEARCH_FACTORS only; NO mining;
                 orthogonality checks (corr<0.5, turnover-diff>=20%);
                 full S0->S1->S2 pipeline; paper run kicked off
  R7 — Exhaustive code audit on R1-R6 touched files
                 (AST scan: unused imports, silent excepts, shadowed
                 builtins; pytest full suite; --help sweep;
                 core/research + core/paper_trading + core/data
                 import sweep)
  R8 — Docs sync + CLAUDE.md slim + final synthesis
                 (README v1.4 footer; CLAUDE.md -> <800 lines by
                 archiving completed-phase tables to new history doc;
                 docs/20260424-phase_e_post_cand2_final_synthesis.md;
                 emit EPOST_CAND2_DONE)

HARD CONSTRAINTS (PRD section 5.5 + 5.6):
  - Candidate-2 MUST be 3 factors, equally-weighted (1/3 each)
  - NO TPE / Optuna / grid search / any weight tuning
  - Each factor: Spearman IC p<0.05 in rcm-v1-lag1 window AND
                 positive IC in >=3 of 6 regimes
  - Candidate-2 composite vs RCMv1 composite correlation < 0.5
  - Candidate-2 turnover profile differs from RCMv1 by >= 20%
  - If Candidate-2 is rejected by research_promote.py or
    paper_enter.py, produce rejection_memo.md (still a success)

RULES OF ENGAGEMENT:
  - Autonomous: bug fixes, docstrings, missing tests, README/CLAUDE
    edits, requirements.txt ADDITIONS (per R1 only), registry
    updates via official CLIs, unified mask config file
  - PAUSE for user: production_strategy.yaml / PRODUCTION_FACTORS
    changes; promote_strategy.py semantics; archive.db or
    rcm_archive.db schema mutation; new vendor/data-layer/broker;
    any --force revoke on REAL rcm_v1_defensive_composite_01
    (clone path only)

HALT CONDITIONS:
  1. 8 rounds completed (ceiling) -> emit EPOST_CAND2_DONE if met
  2. Test count drops by > 10 tests
  3. Core import breaks
  4. Disk < 10 GB
  5. Finding requires schema migration or new PRD
  6. R7 audit detects > 5 real functional bugs in R1-R6 changes
     (rollback signal, surface to user)

DELIBERATE DEVIATIONS FROM audit-v2 LAUNCHER (PRD section 10.6):
  D1. No auto-generate PRD:
      - audit-v2 launcher embeds full PRD in heredoc as fallback
      - this launcher does NOT (PRD 714 lines is too big). Missing PRD
        -> hard exit 1 with git restore instructions
  D2. Stricter PAUSE rule: any --force revoke on real
      rcm_v1_defensive_composite_01 MUST pause for user. Clone-path
      drill is mandatory in R3 to protect the only real S2 sample.
  D3. Extra halt condition (#6): if R7 finds > 5 real functional bugs
      in R1-R6, loop halts and surfaces instead of force-finishing.
      R7 is for VERIFICATION not REMEDIATION.
  R8 final synthesis doc MUST reprint these 3 deviations for the
  auditor's post-run review (per PRD section 10.5 R8 scope).

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. git status is clean:
       git status
2. Baseline readable:
       jq '.tests' data/baseline/latest.json
3. Phase E core import smoke:
       python -c "from core.research.candidate_registry import CandidateRegistry; from core.research.frozen_spec import FrozenStrategySpec; print('phase E core OK')"
4. RCMv1 candidate is at S2 (should be, per memory):
       python -c "from core.research.candidate_registry import CandidateRegistry; r = CandidateRegistry().get('rcm_v1_defensive_composite_01'); print(r.status.value)"
5. Disk check:
       df -h .

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE (single line, starts with /ralph-loop:ralph-loop):
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 10 --completion-promise EPOST_CAND2_DONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to
  docs/20260420-ralph_loop_log.md (section header: "R-epost-cand2-round-NN")
- Round commit message convention:
       phase-e-post R1: deps: <summary>
       phase-e-post R2: migration hermetic: <summary>
       phase-e-post R3: revoke drill: <summary>
       phase-e-post R4: paper decouple: <summary>
       phase-e-post R5: research mask unify: <summary>
       phase-e-post R6: Candidate-2 S0->S1->S2: <summary>
       phase-e-post R7: exhaustive audit: <summary>
       phase-e-post R8: docs sync + slim: EPOST_CAND2_DONE
- To pause mid-loop:
       rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- Final round R8 should:
  * Emit <promise>EPOST_CAND2_DONE</promise>
  * Commit README v1.4 + CLAUDE.md slim + claude_md_phase_e_history.md
    + phase_e_post_cand2_final_synthesis.md
  * Append final summary to docs/20260420-ralph_loop_log.md

EOF
