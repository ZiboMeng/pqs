#!/bin/bash
# Start the 30-round universe-expanded mining ralph-loop.
#
# Reference PRD: docs/prd_universe_expanded_mining.md
# Lineage pattern: post-2026-04-21-universe-mining-round-N
# Max iterations: 30
# Completion promise: RALPHDONE (must be GENUINELY true)
#
# USAGE (2 options):
#
# A. Print the /ralph-loop invocation to paste into Claude Code:
#       bash scripts/start_universe_mining_loop.sh
#
# B. (if you have claude code CLI) directly run via ``claude /ralph-loop ...``
#    (not auto-invoked here — copy the printed command manually to stay
#     in the foreground of your Claude Code session)
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters. Prior
# shell-parsing failures (LLM-phase R_pre_loop) showed Chinese punctuation
# + multi-line prompts break argparse. ASCII + one-line avoids that.

set -eo pipefail

PRD_PATH="docs/prd_universe_expanded_mining.md"

if [[ ! -f "$PRD_PATH" ]]; then
    echo "ERROR: PRD not found at $PRD_PATH" >&2
    echo "       Run this from repo root." >&2
    exit 1
fi

# Single-line ASCII-only prompt per prior lesson
# (escape-safe, no Chinese / em-dash / section marks)
PROMPT='Execute one round per docs/prd_universe_expanded_mining.md section 3 topic menu. lineage_tag=post-2026-04-21-universe-mining-round-N where N is the current round number. Do NOT modify config/universe.yaml or PRODUCTION_FACTORS without explicit user auth. Halt on any section 7 stop condition. Write per-round 11-part Chinese report to chat and docs/ralph_loop_log.md. Attempt send_round_summary.py notification at end of each round.'

cat <<EOF
================================================================================
Universe-Expanded Mining — Ralph-Loop Setup
================================================================================

PRD:            docs/prd_universe_expanded_mining.md
Max iterations: 30
Promise:        RALPHDONE
Lineage pattern: post-2026-04-21-universe-mining-round-N

--------------------------------------------------------------------------------
To start the loop, paste the following single command into Claude Code:
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "${PROMPT}" --max-iterations 30 --completion-promise RALPHDONE

--------------------------------------------------------------------------------
Pre-flight checklist (user to verify):
--------------------------------------------------------------------------------

1. Current git status is clean:
       git status
2. Tests are 1108 passed + 1 xfailed (expected post-R28):
       /home/zibo/miniconda3/envs/pqs/bin/python -m pytest -q | tail -3
3. Archive lineage pre-check (should be empty before R29):
       /home/zibo/miniconda3/envs/pqs/bin/python -c "import sqlite3; c = sqlite3.connect('data/mining/archive.db'); print(c.execute(\"SELECT COUNT(*) FROM trials WHERE lineage_tag LIKE 'post-2026-04-21-universe-mining%'\").fetchone())"

4. (Optional) WeChat webhook for per-round summaries:
       export PQS_WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXXX"

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

Monitor active loop state:
       head -10 .claude/ralph-loop.local.md

Cancel loop (if needed):
       rm .claude/ralph-loop.local.md

Leaderboard during/after:
       /home/zibo/miniconda3/envs/pqs/bin/python scripts/run_mining.py --leaderboard \\
           --lineage-filter 'post-2026-04-21%'

================================================================================
EOF
