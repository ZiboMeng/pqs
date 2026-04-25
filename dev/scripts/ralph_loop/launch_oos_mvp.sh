#!/usr/bin/env bash
# OOS MVP ralph-loop launcher
#
# Stages `.claude/ralph-loop.local.md` (the ralph-loop plugin's state file)
# with the prompt body extracted from `oos_mvp_launcher.md`. After staging,
# either:
#   - if invoked inside Claude Code via Bash tool: the loop activates as soon
#     as the assistant tries to Stop (the plugin's stop hook reads the file)
#   - if invoked from a plain terminal: open Claude Code in this dir and the
#     state will be picked up by the stop hook on the first assistant Stop
#
# This wrapper preserves the same state-file format the slash command uses
# (see ~/.claude/plugins/.../setup-ralph-loop.sh), so the plugin's stop hook
# treats the file identically.
#
# Usage:
#   bash dev/scripts/ralph_loop/launch_oos_mvp.sh [--check-only] [--force]
#
# Flags:
#   --check-only  Run preflight checks only; do not write the state file.
#   --force       Skip the working-tree-clean prompt.
#
# Exit codes:
#   0 = staged (or check-only passed)
#   1 = preflight failure / user bail

set -euo pipefail

# ---------- args ----------
CHECK_ONLY=false
FORCE=false
for arg in "$@"; do
  case "$arg" in
    --check-only) CHECK_ONLY=true ;;
    --force) FORCE=true ;;
    -h|--help)
      sed -n '1,30p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 1
      ;;
  esac
done

# ---------- repo root ----------
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  echo "✗ not in a git repo" >&2
  exit 1
fi
cd "$REPO_ROOT"

# ---------- config ----------
LAUNCHER_MD="dev/scripts/ralph_loop/oos_mvp_launcher.md"
EXEC_PRD="docs/prd/20260425-oos_mvp_ralph_loop_execution.md"
PRD_V3="docs/prd/20260425-oos_validation_framework_codex_v3.md"
UNFREEZE_MEMO="docs/memos/20260425-oos_framework_unfreeze.md"
BASELINE_JSON="data/baseline/latest.json"
STATE_DIR=".claude"
STATE_FILE="${STATE_DIR}/ralph-loop.local.md"

MAX_ITER=8
PROMISE="OOSMVPDONE"
LINEAGE_TAG="oos-mvp-2026-04-25"

# ---------- color helpers ----------
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

bold "═══ OOS MVP ralph-loop launcher ═══"
echo "  Repo:        $REPO_ROOT"
echo "  Lineage tag: $LINEAGE_TAG"
echo "  Promise:     $PROMISE"
echo "  Max iter:    $MAX_ITER (7 rounds + 1 retry buffer)"
echo

# ---------- preflight 1: required files ----------
bold "[1/5] required files"
ok=true
for f in "$LAUNCHER_MD" "$EXEC_PRD" "$PRD_V3" "$UNFREEZE_MEMO"; do
  if [[ -f "$f" ]]; then
    green "  ✓ $f"
  else
    red   "  ✗ MISSING: $f"
    ok=false
  fi
done
$ok || { red "preflight failed: required files missing"; exit 1; }
echo

# ---------- preflight 2: unfreeze authorization ----------
bold "[2/5] unfreeze authorization"
if grep -q "OOS-framework MVP" "$UNFREEZE_MEMO" 2>/dev/null; then
  green "  ✓ unfreeze memo present and references OOS-framework MVP scope"
else
  red "  ✗ unfreeze memo malformed or missing scope marker"
  exit 1
fi
echo

# ---------- preflight 3: working tree ----------
bold "[3/5] git working tree"
if [[ -n "$(git status --porcelain)" ]]; then
  yellow "  ⚠ uncommitted changes:"
  git status --short | sed 's/^/    /'
  if ! $FORCE; then
    echo
    read -r -p "  continue anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { red "  bail."; exit 1; }
  else
    yellow "  ⚠ --force given, continuing"
  fi
else
  green "  ✓ clean working tree"
fi
echo

# ---------- preflight 4: baseline tests ----------
bold "[4/5] baseline tests"
if [[ -f "$BASELINE_JSON" ]]; then
  if command -v jq >/dev/null 2>&1; then
    N_PASSED=$(jq -r '.tests.passed // "?"' "$BASELINE_JSON" 2>/dev/null || echo "?")
    N_COLLECTED=$(jq -r '.tests.collected // "?"' "$BASELINE_JSON" 2>/dev/null || echo "?")
    N_SKIPPED=$(jq -r '.tests.skipped // 0' "$BASELINE_JSON" 2>/dev/null || echo "0")
    N_XFAILED=$(jq -r '.tests.xfailed // 0' "$BASELINE_JSON" 2>/dev/null || echo "0")
    green "  ✓ baseline tuple: passed=${N_PASSED} skipped=${N_SKIPPED} xfailed=${N_XFAILED} (collected=${N_COLLECTED})"
  else
    yellow "  ⚠ jq not available; skipping baseline tuple parse"
    green "  ✓ baseline file exists at ${BASELINE_JSON}"
  fi
else
  yellow "  ⚠ no baseline JSON at ${BASELINE_JSON}"
  yellow "    loop will rely on fresh pytest tuple comparison"
fi
echo

# ---------- preflight 5: extract prompt body ----------
bold "[5/5] extract prompt body from launcher.md"
# Pull content between the first opening ``` line and its matching ``` close.
# `awk` toggles state at each fence; we capture text while inside the first
# fenced block.
PROMPT=$(awk '
  /^```$/ {
    if (inside == 0) { inside = 1; next }
    else { inside = 0; exit }
  }
  inside == 1 { print }
' "$LAUNCHER_MD")

if [[ -z "$PROMPT" ]]; then
  red "  ✗ failed to extract prompt body — check fence markers in $LAUNCHER_MD"
  exit 1
fi

PROMPT_LINES=$(printf "%s\n" "$PROMPT" | wc -l | tr -d ' ')
PROMPT_CHARS=$(printf "%s" "$PROMPT" | wc -c | tr -d ' ')
green "  ✓ prompt body: ${PROMPT_LINES} lines, ${PROMPT_CHARS} chars"
echo

if $CHECK_ONLY; then
  bold "═══ check-only mode: not writing state file ═══"
  exit 0
fi

# ---------- stage state file ----------
mkdir -p "$STATE_DIR"
if [[ -f "$STATE_FILE" ]]; then
  yellow "  ⚠ overwriting existing $STATE_FILE"
  if ! $FORCE; then
    read -r -p "  ok? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { red "  bail."; exit 1; }
  fi
fi

# Match exactly the format setup-ralph-loop.sh writes (frontmatter + prompt body)
{
  echo "---"
  echo "active: true"
  echo "iteration: 1"
  echo "session_id: ${CLAUDE_CODE_SESSION_ID:-}"
  echo "max_iterations: $MAX_ITER"
  echo "completion_promise: \"$PROMISE\""
  echo "started_at: \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
  echo "---"
  echo
  printf "%s\n" "$PROMPT"
} > "$STATE_FILE"

green "  ✓ wrote $STATE_FILE"
echo

# ---------- summary ----------
bold "═══ staged ═══"
cat <<MSG
  state file:        $STATE_FILE
  max iterations:    $MAX_ITER
  completion tag:    <promise>$PROMISE</promise>
  session_id:        ${CLAUDE_CODE_SESSION_ID:-<empty — any session in this dir will pick it up>}

next:
  • inside Claude Code: just send any first turn (e.g., 'begin oos mvp loop').
    The plugin's stop hook reads $STATE_FILE on the first assistant Stop
    and re-feeds the OOS MVP prompt for round 1.
  • from a terminal: cd $REPO_ROOT && claude  →  paste 'begin oos mvp loop'

monitor:
  head -10 $STATE_FILE
  tail -f .claude/ralph-loop.local.md_bak  # plugin keeps a rotating backup

halt:
  rm $STATE_FILE          # removes the stop-hook trigger
  # — or wait for emit of <promise>$PROMISE</promise> at top level

invariants (will halt loop on violation per execution PRD §2):
  • no edits to config/*.yaml, frozen specs, PRODUCTION_FACTORS,
    requirements*.txt / pyproject.toml, registry.db schema, candidate
    state-machine, data/daily/*.parquet, splits.parquet, tests deletions
  • pytest tuple drift not explained by regression tests added this round
  • single round runtime > 30 min
  • work outside R1-R7 scope
MSG
echo
green "Done."
