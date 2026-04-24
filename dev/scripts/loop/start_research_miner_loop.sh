#!/bin/bash
# Start the Research Composite Miner v1 + Orthogonal Feature Expansion
# ralph-loop.
#
# Reference PRD: docs/20260424-prd_research_composite_miner_v1.md
# Lineage tag: post-2026-04-24-rcm-v1 (all rounds share this tag)
# Max iterations: 22 (per PRD §13.2 — hard ceiling; earlier halt on §13.3)
# Completion promise: RCMV1DONE
#
# USAGE:
#   bash scripts/start_research_miner_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/20260424-prd_research_composite_miner_v1.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD not found at $PRD_PATH" >&2
    echo "       Run this from repo root." >&2
    exit 1
fi

# Single-line ASCII-only prompt.
# AUTONOMOUS MODE: user pre-authorized all decisions per PRD §13.4
# Autonomous Decision Boundaries. Do NOT pause to ask questions.
# FORBIDDEN: modifying PRODUCTION_FACTORS, config/universe.yaml, or
# config/production_strategy.yaml; auto-promote via scripts/promote_strategy.py;
# introducing new vendor / new heavy data layer; mixing rcm_archive with
# production archive.
PROMPT='Execute one round per docs/20260424-prd_research_composite_miner_v1.md section 15 step order. lineage_tag=post-2026-04-24-rcm-v1 for all research composite miner trials / research artifacts / reports. AUTONOMOUS MODE: follow section 13.4 decision boundaries; do NOT pause to ask questions. Halt only on section 13.3 halt conditions. Do NOT modify PRODUCTION_FACTORS, config/universe.yaml, or config/production_strategy.yaml. Do NOT auto-promote any spec. Do NOT introduce new vendor / new heavy data layer. Per-round 11-part Chinese report appended to docs/20260420-ralph_loop_log.md as R-rcm-v1-round-NN. Reference Appendix A docs/20260423-feature_data_tier_classification.md for any new-feature tier question.'

cat <<EOF
================================================================================
Research Composite Miner v1 + Orthogonal Feature Expansion — Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
Lineage tag:         post-2026-04-24-rcm-v1
Max iterations:      22
Completion promise:  RCMV1DONE

EXECUTION ORDER (PRD section 15 — loop will sequence these):
  Step 1  — Freeze feat-v1. No further tweaks on prior PRD.
  Step 2  — 3 plumbing prereqs: multi-benchmark generator + residualize
            helper + 8 downstream scripts upgraded to full panel contract
            (est. 4-6 rounds)
  Step 3  — 12 new features (Family A 4 / B 4 / C 3 / D 1) with unit tests
            + IC sanity on 79-symbol panel (est. 5-7 rounds)
  Step 4  — research_mask hardening: panel / miner / diagnostics layer
            (est. 2-3 rounds)
  Step 5  — Research Composite Miner v1: family-aware sampling + weighted-
            sum objective (PRD §8.6 formula) + Optuna TPE backend +
            rcm_archive.db + rcm_optuna.db. Non-promoting output.
            (est. 3-5 rounds)
  Step 6  — First research-only composite mining run + top-K analysis +
            factor-family diversity / correlation / regime diagnostics
            (est. 2 rounds)
  Step 7  — Decide next PRD direction from Step 6 output.
  Buffer  — Bug fix / diagnostic / re-run (est. 3-4 rounds)

Total budget: 22 rounds. Earlier halt if any PRD §13.3 condition triggers.

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. Current git status is clean:
       git status
2. Regenerate baseline snapshot:
       python dev/scripts/baseline/build_research_baseline_snapshot.py
       jq '.tests, .git.dirty, .archive.total_trials' data/baseline/latest.json
3. Confirm feat-v1 final state is committed (pre-condition for Step 1):
       git log --oneline | grep -E "feat-v1 R[0-9]+" | head -5
4. Confirm tier-classification doc is in place (Appendix A reference):
       test -f docs/20260423-feature_data_tier_classification.md && echo "OK"
5. Data freshness:
       python -c "from core.data.market_data_store import MarketDataStore; s=MarketDataStore(data_dir='data'); print(s.read('SPY','1d').index[-1])"
   If stale:
       python scripts/fetch_data.py --daily-only
6. Disk check (PRD §13.3 condition 6 trip threshold is 10GB):
       df -h .

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE:
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 22 --completion-promise RCMV1DONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to docs/20260420-ralph_loop_log.md
  (section header: "R-rcm-v1-round-NN")
- USER DECISION POINTS (see PRD §13.4 — loop will halt + surface these):
  * Modifying PRODUCTION_FACTORS
  * Modifying config/universe.yaml (Stage 3 expansion or symbol removal)
  * Modifying config/production_strategy.yaml (auto-promote)
  * Any new-vendor / heavy-data-layer decision (sector PIT / shares / earnings
    / options / short interest / alt data)
  * Pareto multi-objective miner upgrade (v2 scope)
- HALT CONDITIONS (see PRD §13.3):
  1. All 4 PRD main lines done + miner first-run analysis landed
  2. Step 2 plumbing blocked > 2 rounds → MUST NOT enter Step 5 miner
  3. Key interface causes systemic regression beyond budget
  4. research_mask hardening blocks panel construction (data-layer blocker)
  5. Miner v1 first-run shows search space not opened (out-of-PRD blocker)
  6. Bug-fix spiral (repeated test/script failures)
  7. Max-iterations 22 reached
- To pause mid-loop:
      rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- Final round should write:
      docs/YYYYMMDD-rcm_v1_final_report.md
  and issue <promise>RCMV1DONE</promise>
EOF
