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
- All files under `core/`, `scripts/`, `dev/scripts/`, `tests/`
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
`docs/20260420-ralph_loop_log.md` under section `R-audit-v2-round-NN`.

### Round 1: Core library audit
Focus: `core/factors/`, `core/mining/`, `core/signals/`, `core/backtest/`,
`core/research/` (Phase E governance layer).
- Run every public-API module at least once (import + a call)
- Unit test suite: full run, any failure is a bug
- Check for: dead imports, unreachable branches, wrong type hints,
  shadowed built-ins, silent exceptions
- RUN: `python -m pytest tests/unit -q`, plus smoke run of:
  - `python scripts/run_factor_screen.py --help`
  - `python scripts/run_research_miner.py --help`
  - `python scripts/run_xgb_importance.py --help`
  - `python -c "from core.research.candidate_registry import CandidateRegistry; print('registry OK')"`
  - `python -c "from core.research.frozen_spec import FrozenStrategySpec; print('frozen_spec OK')"`
  - `python -c "from core.research.drift_metrics import DriftThresholds; print('drift_metrics OK')"`
  - `python -c "import core.research.paper_artifacts, core.research.acceptance_helpers; print('paper_artifacts + acceptance_helpers OK')"`
- Fix bugs found; update inline docstrings if wrong
- Output: bug list + fixes + test-count delta

### Round 2: Scripts + I/O audit
Focus: all `scripts/*.py` (quant ops) + `dev/scripts/**/*.py` (dev tooling)
+ `core/data/` + `core/paper_trading/` + `core/reporting/`.
- Each script gets a `--help` smoke test to catch arg-parse regressions.
  Cover BOTH quant ops (`scripts/`) AND dev tooling (`dev/scripts/`) —
  the X-1 migration moved 7 Python files to 3-deep nested locations, so
  `Path(__file__).parent.parent` depth regressions are a real risk
- Data store: read a known symbol, verify expected shape
- Backtest entry: run `run_backtest.py` on a tiny window
- Paper trading: instantiate `PaperTradingEngine`, dry-init
- Paper runner: `python scripts/run_paper_candidate.py --help` +
  `python scripts/paper_drift_report.py --help` +
  `python scripts/paper_enter.py --help` (Phase E-2 paper layer)
- Reporting: generate 1 master report artifact
- Fix: broken paths (especially ROOT path depth after X-1 migration),
  wrong default arg values, bit-rotted CLI flags
- Output: script inventory with status {OK / bug-fixed / dead}

### Round 3: Tests + docs sync + baseline rebuild
Focus: `tests/integration/`, README.md, baseline snapshot.
- Full integration test run (ignore outright if infra-blocked)
- README.md: scan every script reference, every data path, every
  feature count; FIX any claim that no longer matches code
- `data/baseline/latest.json`: regenerate via
  `python dev/scripts/baseline/build_research_baseline_snapshot.py`
  (moved to `dev/` in X-1 migration)
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

Append each round's report as `## R-audit-v2-round-NN` to
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
