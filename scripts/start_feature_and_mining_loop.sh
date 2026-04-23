#!/bin/bash
# Start the Feature Engineering + Expanded Universe Re-Mining ralph-loop.
#
# Reference PRD: docs/20260423-prd_research_feature_engineering_and_expanded_mining.md
# Lineage pattern: post-2026-04-23-feat-v1-expanded (all rounds share this tag)
# Max iterations: 15 (per PRD §15.1 recommendation; includes buffer)
# Completion promise: FEATV1DONE
#
# USAGE:
#   bash scripts/start_feature_and_mining_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/20260423-prd_research_feature_engineering_and_expanded_mining.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD not found at $PRD_PATH" >&2
    echo "       Run this from repo root." >&2
    exit 1
fi

# Single-line ASCII-only prompt.
# AUTONOMOUS MODE: user pre-authorized all decisions per PRD section 15.4
# Autonomous Decision Boundaries. Do NOT pause to ask questions.
# Follow section 12 (7-step execution order) exactly; halt only on section 15.3
# stop conditions. FORBIDDEN: modifying PRODUCTION_FACTORS, config/universe.yaml,
# or config/production_strategy.yaml; auto-promote via scripts/promote_strategy.py;
# Transformer main-line sweep; new data sources.
PROMPT='Execute one round per docs/20260423-prd_research_feature_engineering_and_expanded_mining.md section 12 step order. lineage_tag=post-2026-04-23-feat-v1-expanded for all archived trials / mining artifacts. AUTONOMOUS MODE: follow section 15.4 decision boundaries; do NOT pause to ask questions. Halt only on section 15.3 halt conditions. Do NOT modify PRODUCTION_FACTORS, config/universe.yaml, or config/production_strategy.yaml. Do NOT auto-promote any spec. Per-round 11-part Chinese report appended to docs/20260420-ralph_loop_log.md as R-feat-v1-round-NN.'

cat <<EOF
================================================================================
Feature Engineering + Expanded Universe Re-Mining — Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
Lineage tag:         post-2026-04-23-feat-v1-expanded
Max iterations:      15
Completion promise:  FEATV1DONE

EXECUTION ORDER (PRD section 12, loop will sequence these):
  Step 1  — Feature engineering: new research factors + label mode extension
            + per-date masks + 15+ unit tests (est. 3-4 rounds)
  Step 2  — Panel build + sanity check for 79-symbol expanded universe (1 round)
  Step 3  — R39 fresh-baseline mining (fresh Optuna study + fresh archive, via
            C+ backup-and-reset pattern from pre-PRD 2026-04-22; 1-2 rounds)
  Step 4  — R39 top-K structural analysis: factor-family distribution,
            Stage-1+2 symbol alpha contribution, pseudo-improvement detection
            (1 round)
  Step 5  — Conditional on Step 4 direction: R40 regime-stratified validation
            + R41 acceptance pack v2 (2-3 rounds)
  Step 6  — DSL fast-exit ablation (A/B backtest on R39 top spec) (1 round)
  Step 7  — LLM sidecar: pick 3-6 from existing 97 candidates, expanded-
            universe-aware directions only (1-2 rounds)
  Buffer  — Bug fix / diagnostic / re-run slack (2-3 rounds)

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. Current git status is clean:
       git status
2. Regenerate baseline snapshot:
       python scripts/build_research_baseline_snapshot.py
       jq '.tests, .git.dirty, .archive.total_trials' data/baseline/latest.json
3. Confirm R39 archive state (should have previous lineage post-2026-04-22-
   deep-R38-stage12 from pre-PRD; safe to keep for comparison):
       python -c "from core.mining.archive import MiningArchive; a=MiningArchive('data/mining/archive.db'); print(a.lineage_summary())"
4. Data freshness (daily data should be within last 3 days):
       python -c "from core.data.market_data_store import MarketDataStore; s=MarketDataStore(data_dir='data'); print(s.read('SPY','1d').index[-1])"
   If stale:
       python scripts/fetch_data.py --daily-only
5. Alignment check on current artifact:
       python -c "from core.alignment import check_alignment; from pathlib import Path; print(check_alignment(Path('.')).summary_line())"

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE:
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 15 --completion-promise FEATV1DONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to docs/20260420-ralph_loop_log.md
  (section header: "R-feat-v1-round-NN")
- USER DECISION POINTS (see PRD §15.4 — loop will halt + surface these):
  * Modifying PRODUCTION_FACTORS
  * Modifying config/universe.yaml (Stage 3 or symbol removal)
  * Modifying config/production_strategy.yaml (auto-promote)
  * Any data-source / pipeline change
  * Transformer main-line sweep (only very-small-confirmation allowed autonomously)
- HALT CONDITIONS (see PRD §15.3):
  * pytest regression > 5 tests
  * core/ import failure
  * disk < 10GB
  * unauthorized config edits
  * archive integrity check fail
  * 3rd --force promote attempt
  * Step 3 R39 produces 0 OOS pass AND all OOS IR < 0 (blocker doc + stop)
- To pause mid-loop:
      rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- Final round writes:
      docs/YYYYMMDD-feat_v1_expanded_final_report.md
  (loop stops when this doc lands OR FEATV1DONE promise issued OR
   max-iterations reached OR halt condition triggered)
EOF
