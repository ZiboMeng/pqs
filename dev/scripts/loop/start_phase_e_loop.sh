#!/bin/bash
# Start the Phase E — Research Governance + Paper Transition ralph-loop.
#
# Reference PRDs:
#   - docs/20260424-prd_phase_e_execution.md  (ralph-loop round plan)
#   - docs/20260424-prd_phase_e_governance_and_paper.md  (charter)
#   - docs/20260424-prd_research_to_paper_promote_standard.md  (promote rules)
#   - docs/20260424-prd_layered_quant_architecture.md  (lifecycle)
#
# Lineage tag: phase-e-governance-2026-04-24
# Max iterations: 14 (per execution PRD §0; earlier halt on §3 halt conditions)
# Completion promise: PHASEEDONE
#
# USAGE:
#   bash scripts/start_phase_e_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

EXEC_PRD="docs/20260424-prd_phase_e_execution.md"
CHARTER_PRD="docs/20260424-prd_phase_e_governance_and_paper.md"

for PRD in "$EXEC_PRD" "$CHARTER_PRD"; do
    if [[ ! -f "$PRD" ]]; then
        echo "ERROR: PRD not found at $PRD" >&2
        echo "       Run this from repo root." >&2
        exit 1
    fi
done

# Single-line ASCII-only prompt.
# AUTONOMOUS MODE: user pre-authorized all decisions per execution PRD §1.
# FORBIDDEN this phase:
#   - modifying PRODUCTION_FACTORS, config/universe.yaml, or
#     config/production_strategy.yaml
#   - auto-promote via scripts/promote_strategy.py
#   - broker / live feed / scheduler / daemon integration
#   - pyarrow removal (scope is decouple only)
#   - acceptance_pack v3 mega-merge
#   - auto-freezing RCMv1 trials as candidates
PROMPT='Execute one round per docs/20260424-prd_phase_e_execution.md section 2 sub-phase breakdown and section 5 round-by-round table. lineage_tag=phase-e-governance-2026-04-24 for all candidates and governance artifacts. Rounds 1-3 = Phase E-0 foundation. Rounds 4-7 = Phase E-1 promote standard code-ification. Rounds 8-11 = Phase E-2 minimal paper layer. Rounds 12-14 = buffer for bug fix and README sync and final synthesis. AUTONOMOUS MODE: follow section 1.1 Allowed autonomously rules; pause to surface per section 1.2 MUST pause for user rules. Halt per section 3 halt conditions. Do NOT modify PRODUCTION_FACTORS, config/universe.yaml, or config/production_strategy.yaml. Do NOT modify scripts/promote_strategy.py semantics. Do NOT touch core/mining/archive.db or core/mining/rcm_archive.db schema. Do NOT add new dependencies. Do NOT add broker or live feed or scheduler. Do NOT do acceptance_pack v3 mega-merge. Each round RUNS representative code paths with tests not just reads them. Each round commits with message phase-e R<N>: <sub-phase>: <summary>. Each round appends 11-part Chinese report to docs/20260420-ralph_loop_log.md as R-phase-e-round-NN. Emit PHASEEDONE only after rounds 1-11 complete and full test suite passes and RCMv1 candidate has completed S0 to S1 to S2 transitions and paper_drift_report.py produced a valid report and README plus CLAUDE.md synced and final synthesis doc exists.'

cat <<EOF
================================================================================
Phase E — Research Governance + Paper Transition — Ralph-Loop Setup
================================================================================

Execution PRD:       $EXEC_PRD
Charter PRD:         $CHARTER_PRD
Lineage tag:         phase-e-governance-2026-04-24
Max iterations:      14 (hard ceiling; earlier halt OK)
Completion promise:  PHASEEDONE

ROUND PLAN (from execution PRD §5):
  R1  — E-0  Candidate registry + S0/S1/S2/S5 state machine
              core/research/candidate_registry.py + registry.db
  R2  — E-0  Pyarrow decouple (MarketDataStore lazy, run_paper no top-level)
              Verify: PaperTradingEngine imports without pyarrow
  R3  — E-0  Revoke workflow + RCMv1 S1 memo migration as first candidate
              scripts/revoke_candidate.py
              ingest docs/20260424-rcm_v1_s1_candidate_memo.md -> registry

  R4  — E-1  FrozenStrategySpec schema (8 mandatory fields)
              core/research/frozen_spec.py
  R5  — E-1  scripts/freeze_research_candidate.py (trial -> frozen YAML)
  R6  — E-1  scripts/research_promote.py (S0 -> S1; NO production write)
  R7  — E-1  core/research/acceptance_helpers.py (shared evaluator)

  R8  — E-2  scripts/run_paper_candidate.py (reads frozen spec, NOT prod config)
  R9  — E-2  Paper artifacts schema + doc
  R10 — E-2  scripts/paper_drift_report.py (30-day window, informational)
  R11 — E-2  scripts/paper_enter.py (S1 -> S2) + S3 NotImplementedError

  R12-R14 — Buffer for bug fix / README sync / final synthesis / PHASEEDONE

SCOPE RULES (execution PRD §1):
  Allowed:       new modules / scripts / tests / README / log
  Pause-for-user schema migrations, dependency additions, public-API deletion,
                 any production config touch, broker/scheduler/daemon
  Forbidden:     production promote, auto-freeze RCMv1, acceptance v3 merge

HALT CONDITIONS (execution PRD §3):
  1. 14 rounds ceiling
  2. Test regression > 10 tests (baseline: 1386 pass)
  3. Core import break
  4. Disk < 10 GB
  5. Finding requires migrating existing rcm_archive.db schema
  6. Write to config/production_strategy.yaml detected
  7. User intervention requested for §1.2 pause-for-user action

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. Git status clean:
       git status
2. Baseline snapshot readable:
       jq '.tests' data/baseline/latest.json 2>/dev/null
3. Core + paper smoke:
       python -c "from core.mining.research_miner import ResearchMiner; from core.paper_trading.paper_trading_engine import PaperTradingEngine; print('OK')"
4. Disk check (need >= 10 GB):
       df -h .
5. RCMv1 S1 memo exists (R3 migration source):
       test -f docs/20260424-rcm_v1_s1_candidate_memo.md && echo "OK"
6. RCMv1 rcm_archive has converged spec row:
       python -c "
       import sqlite3
       c = sqlite3.connect('data/mining/rcm_archive.db').cursor()
       row = c.execute(
         \"SELECT trial_id FROM rcm_trials WHERE trial_id='f24aefecc91a'\"
       ).fetchone()
       assert row, 'RCMv1 converged trial f24aefecc91a missing'
       print('OK')
       "

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE (single line, starts with /ralph-loop:ralph-loop):
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 14 --completion-promise PHASEEDONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to
  docs/20260420-ralph_loop_log.md (section header: "R-phase-e-round-NN")
- Commit message format:
       phase-e R<N>: <sub-phase>: <short summary>
       (sub-phase in {E-0, E-1, E-2, buffer})
- To pause mid-loop:
       rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- PHASEEDONE is emitted only when (all simultaneously true):
  * Rounds 1-11 shipped
  * Full test suite passes (baseline 1386 + new tests, 0 regressions)
  * RCMv1 candidate completed S0 -> S1 -> S2 via new tooling
  * paper_drift_report.py produced >=1 real report on RCMv1 candidate
    with >=5 days of paper runs
  * README + CLAUDE.md updated
  * data/baseline/latest.json regenerated
  * Final synthesis doc docs/20260424-phase_e_final_synthesis.md exists
  * No config/production_strategy.yaml write occurred

EOF
