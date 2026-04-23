#!/bin/bash
# Start the 3-round Codebase Audit ralph-loop.
#
# Purpose: systematically audit the codebase for bugs + runtime issues
# across 3 focused rounds, actually RUN representative code paths, fix
# what's broken, and update README to reflect current truth.
#
# Reference PRD: docs/20260424-prd_codebase_audit_3round.md (created below
# by this script if missing).
#
# Lineage tag: audit-2026-04-24 (all 3 rounds share this tag)
# Max iterations: 3 (hard ceiling — one audit focus per round)
# Completion promise: AUDIT3DONE
#
# USAGE:
#   bash scripts/start_codebase_audit_loop.sh
#
# WARNING: keep the prompt SINGLE-LINE with ASCII-only characters per
# prior lesson (Chinese punctuation + multi-line prompts break argparse).

set -eo pipefail

PRD_PATH="docs/20260424-prd_codebase_audit_3round.md"

# Auto-generate the audit PRD if missing — keeps the launcher self-contained.
if [[ ! -f "$PRD_PATH" ]]; then
    echo "Audit PRD missing, generating at $PRD_PATH ..."
    cat > "$PRD_PATH" <<'PRD_EOF'
# PRD: 3-Round Codebase Audit

## 1. Purpose

Systematically audit the pqs codebase for bugs, runtime issues, stale
docs, and dead code across **3 focused rounds**. Each round actually
RUNS representative code paths (not just reads them), fixes what
breaks, and keeps README.md aligned with current truth.

This is a maintenance pass, not feature development. No new features.
No new PRDs beyond this one. No auto-promote. No config/universe /
production_strategy edits unless the audit finds a concrete bug there.

## 2. Scope

### In scope (all 3 rounds share)
- All files under `core/`, `scripts/`, `tests/`
- `README.md` + top-level `CLAUDE.md` accuracy
- `data/baseline/latest.json` regeneration
- Unit + integration test suite runs
- Representative runtime test of each major code path

### Out of scope
- New features / new PRDs / new vendors / new data layers
- Performance optimization (unless the audit finds a concrete
  perf-class bug like an O(n^2) in a hot path)
- Refactoring for style alone
- Modifying `PRODUCTION_FACTORS`, `config/universe.yaml`,
  `config/production_strategy.yaml` unless the audit finds a concrete
  bug AND the fix stays inside the file's documented schema

## 3. Round structure (per-round 11-part Chinese log)

Each round targets ONE focused surface. Report per PRD convention in
`docs/20260420-ralph_loop_log.md` under section `R-audit-round-NN`.

### Round 1: Core library audit
Focus: `core/factors/`, `core/mining/`, `core/signals/`, `core/backtest/`.
- Run every public-API module at least once (import + a call)
- Unit test suite: full run, any failure is a bug
- Check for: dead imports, unreachable branches, wrong type hints,
  shadowed built-ins, silent exceptions
- RUN: `python -m pytest tests/unit -q`, plus smoke run of:
  - `python scripts/run_factor_screen.py --help`
  - `python scripts/run_research_miner.py --help`
  - `python scripts/run_xgb_importance.py --help`
- Fix bugs found; update inline docstrings if wrong
- Output: bug list + fixes + test-count delta

### Round 2: Scripts + I/O audit
Focus: all `scripts/*.py` + `core/data/` + `core/paper_trading/` +
`core/reporting/`.
- Each script gets a `--help` smoke test to catch arg-parse regressions
- Data store: read a known symbol, verify expected shape
- Backtest entry: run `run_backtest.py` on a tiny window
- Paper trading: instantiate `PaperTradingEngine`, dry-init
- Reporting: generate 1 master report artifact
- Fix: broken paths, wrong default arg values, bit-rotted CLI flags
- Output: script inventory with status {OK / bug-fixed / dead}

### Round 3: Tests + docs sync + baseline rebuild
Focus: `tests/integration/`, README.md, baseline snapshot.
- Full integration test run (ignore outright if infra-blocked)
- README.md: scan every script reference, every data path, every
  feature count; FIX any claim that no longer matches code
- `data/baseline/latest.json`: regenerate via
  `python scripts/build_research_baseline_snapshot.py`
- CLAUDE.md: check "Current TODO Checklist" + "Confirmed Done" table
  for drift; fix stale rows
- Output: README diff summary + baseline snapshot commit + CLAUDE.md
  consistency check

## 4. Rules of engagement

### Authorized autonomously
- Bug fixes inside existing files (including tests)
- Docstring corrections
- Adding missing tests for discovered bugs (regression guards)
- README.md edits
- `data/baseline/latest.json` regeneration
- CLAUDE.md "Current TODO" / "Confirmed Done" row updates when the
  audit evidence is concrete

### Pause-for-user
- Any config file schema change
- Any deletion of a public function/class that is referenced elsewhere
- Any change to `PRODUCTION_FACTORS` / `config/universe.yaml` /
  `config/production_strategy.yaml`
- Any dependency added to `requirements.txt` / `pyproject.toml`
- Any migration of a SQLite schema

### Halt conditions (any one triggers halt)
1. 3 rounds completed (hard ceiling)
2. Systemic regression: test count drops by > 10 tests or a previously-
   passing integration test fails due to an audit-round change
3. Core import breaks (`python -c "from core.mining.research_miner
   import ResearchMiner"` fails)
4. Disk free space < 10 GB
5. A finding requires a schema migration or a new PRD to resolve —
   stop and surface to user

## 5. Per-round output format (11-part Chinese, per existing convention)

Append each round's report as `## R-audit-round-NN` to
`docs/20260420-ralph_loop_log.md` with:
1. 本轮主题 (round focus)
2. 本轮目标 (objectives)
3. 为什么这轮优先做它 (why this focus now)
4. 做了什么 (what was done)
5. 修改了哪些文件 (files changed)
6. 跑了哪些测试/实验 (tests/runs)
7. 结果如何 (results — bug list, fix list, runs OK/fail)
8. 当前发现的新问题/新机会 (new findings)
9. 剩余风险 (remaining risks)
10. 下一轮建议方向 (next-round direction)
11. Halt 条件检查 (halt-condition check)

## 6. Completion promise

`AUDIT3DONE` — emit only when all 3 rounds complete, test suite passes,
README is synced, and no new blocker has surfaced mid-audit. If audit
uncovers a gap that requires a separate PRD, emit `AUDIT3DONE` with a
flag noting the gap in the final round log — do NOT block the promise.

## 7. One-sentence summary

**Three focused rounds of bug-hunt + smoke-run + README sync, leaving
the codebase in a known-good state and docs pointing at current truth.**
PRD_EOF
    echo "Generated $PRD_PATH"
fi

# Single-line ASCII-only prompt.
# AUTONOMOUS MODE: autopilot per PRD §4 "Authorized autonomously".
# Halt conditions per PRD §4 "Halt conditions".
PROMPT='Execute one round per docs/20260424-prd_codebase_audit_3round.md section 3 round structure. lineage_tag=audit-2026-04-24 for all audit artifacts. Round 1 = core library audit. Round 2 = scripts and IO audit. Round 3 = tests and docs sync and baseline rebuild. AUTONOMOUS MODE: follow section 4 Authorized autonomously rules; pause to surface per section 4 Pause-for-user rules. Halt per section 4 Halt conditions. Do NOT add new features. Do NOT modify PRODUCTION_FACTORS, config/universe.yaml, or config/production_strategy.yaml except to fix a concrete bug. Do NOT auto-promote any spec. Do NOT add new vendor or heavy data layer. Each round RUNS representative code paths not just reads them. Each round produces 11-part Chinese report appended to docs/20260420-ralph_loop_log.md as R-audit-round-NN. Round 3 must also update README.md to reflect current truth and regenerate data/baseline/latest.json via scripts/build_research_baseline_snapshot.py. Emit AUDIT3DONE only after all 3 rounds complete and test suite passes and README is synced.'

cat <<EOF
================================================================================
3-Round Codebase Audit — Ralph-Loop Setup
================================================================================

PRD:                 $PRD_PATH
Lineage tag:         audit-2026-04-24
Max iterations:      3 (hard ceiling)
Completion promise:  AUDIT3DONE

ROUND STRUCTURE (one focus per round):
  Round 1 — Core library audit
            core/factors/ core/mining/ core/signals/ core/backtest/
            Run every public-API module at least once; fix bugs; update
            docstrings.
  Round 2 — Scripts + I/O audit
            scripts/*.py + core/data/ + core/paper_trading/ + core/reporting/
            --help smoke test each script; run backtest on tiny window;
            instantiate paper engine; generate 1 master report.
  Round 3 — Tests + docs sync + baseline rebuild
            tests/integration/ full run; README.md accuracy sweep;
            regenerate data/baseline/latest.json; CLAUDE.md drift fixes.

RULES:
  - Bug fixes inside existing files: autonomous
  - Docstring corrections: autonomous
  - README edits: autonomous
  - Schema changes / dependency additions / public-API deletions: PAUSE for user
  - No new features, no new PRDs, no new data layers

HALT CONDITIONS:
  1. 3 rounds completed (ceiling)
  2. Test count drops by > 10 tests
  3. Core import breaks
  4. Disk < 10 GB
  5. Finding requires schema migration or new PRD

PRE-FLIGHT CHECKLIST (run before pasting the command below):

1. Current git status is clean:
       git status
2. Baseline snapshot readable:
       jq '.tests' data/baseline/latest.json 2>/dev/null || echo "baseline missing — Round 3 will rebuild"
3. Core smoke:
       python -c "from core.mining.research_miner import ResearchMiner; from core.factors.factor_generator import generate_all_factors; print('core OK')"
4. Disk check:
       df -h .

--------------------------------------------------------------------------------
PASTE THIS INTO CLAUDE CODE (single line, starts with /ralph-loop:ralph-loop):
--------------------------------------------------------------------------------

/ralph-loop:ralph-loop "$PROMPT" --max-iterations 3 --completion-promise AUDIT3DONE

--------------------------------------------------------------------------------
During the loop (informational):
--------------------------------------------------------------------------------

- Per-round commit + 11-part Chinese report appended to
  docs/20260420-ralph_loop_log.md (section header: "R-audit-round-NN")
- Round commit message convention:
       audit R1: core library audit — N bugs fixed
       audit R2: scripts + IO audit — N bugs fixed
       audit R3: tests + docs sync + baseline rebuild
- To pause mid-loop:
       rm .claude/ralph-loop.local.md
  Or use /ralph-loop:cancel-ralph
- Final round should:
  * Emit <promise>AUDIT3DONE</promise>
  * Commit final README.md + data/baseline/latest.json
  * Append final summary to docs/20260420-ralph_loop_log.md

EOF
