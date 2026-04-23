#!/bin/bash
# Start the 50-round deep mining ralph-loop.
#
# Reference PRD: docs/20260421-prd_deep_mining_50round.md
# Lineage pattern: post-2026-04-22-deep-R<NN>
# Max iterations: 50
# Completion promise: DEEPDONE (must be GENUINELY true)
#
# USAGE:
#   bash scripts/start_deep_mining_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/20260421-prd_deep_mining_50round.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD not found at $PRD_PATH" >&2
    echo "       Run this from repo root." >&2
    exit 1
fi

# Single-line ASCII-only prompt.
# AUTONOMOUS MODE: user pre-authorized all decisions per PRD section 11
# Autonomous Decision Rules (2026-04-22). Do NOT pause to ask questions.
# Follow section 11 rules exactly; halt only on section 11.8 stop conditions.
PROMPT='Execute one round per docs/20260421-prd_deep_mining_50round.md section 2 track menu. lineage_tag=post-2026-04-22-deep-R<NN>. AUTONOMOUS MODE: follow section 11 Autonomous Decision Rules pre-authorized by user; DO NOT pause to ask any questions. Halt only on section 11.8 stop conditions. Do not modify PRODUCTION_FACTORS or config/universe.yaml outside authorized rounds per section 11. Write per-round 11-part Chinese report to chat and docs/20260420-ralph_loop_log.md.'

cat <<EOF
================================================================================
Deep Mining Phase — 50-Round Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
Lineage pattern:     post-2026-04-22-deep-R<NN>
Max iterations:      50
Completion promise:  DEEPDONE

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. Current git status is clean:
       git status
2. Regenerate baseline snapshot:
       python scripts/build_research_baseline_snapshot.py
       jq '.tests, .git.dirty, .archive.total_trials' data/baseline/latest.json
3. Data freshness (daily data should be within last 3 days):
       python -c "from core.data.market_data_store import MarketDataStore; import pandas as pd; s=MarketDataStore(data_dir='data'); print(s.read('SPY','1d').index[-1])"
   If stale:
       python scripts/fetch_data.py --daily-only
4. Alignment check on current artifact:
       python -c "from core.alignment import check_alignment; from pathlib import Path; print(check_alignment(Path('.')).summary_line())"
5. (Optional intraday refresh, only needed before Track B rounds R16-R25):
       python scripts/fetch_data.py --intraday-only

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE:
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 50 --completion-promise DEEPDONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report to docs/20260420-ralph_loop_log.md
- User DECISION POINTS (see PRD §11): promote / universe.yaml / new factors
  / new DSL funcs / XGBoost decision / final promote
- To pause mid-loop:
      rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
EOF
