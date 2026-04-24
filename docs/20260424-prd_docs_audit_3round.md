# PRD: 3-Round Code + Docs Audit

## 1. Purpose

Three focused rounds that:

1. **Code audit** — hunt bugs, dead code, silent failures, unused
   imports, shadowed builtins, light perf issues (O(n^2) in hot paths,
   obviously redundant work). Fix what you find. Bug fixes that CHANGE
   test outcomes are fine provided a regression test or a log entry
   justifies the delta.
2. **README trim** — remove dev-process / ralph-loop internals from
   the user-facing README. Things like `v1.x` footer entries, per-loop
   breadcrumbs, launcher references, `EPOST_CAND2_DONE` mentions, and
   per-round commit hashes belong in `docs/20260420-ralph_loop_log.md`
   and the phase-history docs — NOT in README.
3. **CLAUDE.md slim** — target < 600 lines (currently 770 after Phase
   E-post R8). Compress reference sections whose canonical home is
   under `docs/` or the repo itself.
4. **Baseline rebuild** at the end.

## 2. Scope

### In scope (all 3 rounds share)

- All files under `core/`, `scripts/`, `dev/scripts/`, `tests/` —
  **audit and fix**
- `README.md` — heavy editing (trim dev content)
- `CLAUDE.md` — heavy editing (further slim)
- `data/baseline/latest.json` regeneration
- Unit + integration test suite runs

### Out of scope

- New features / new PRDs / new vendors / new data layers
- Modifying `PRODUCTION_FACTORS` / `config/universe.yaml` /
  `config/production_strategy.yaml` / `config/research_mask.yaml` /
  `config/cross_ticker_rules.yaml` / any other `config/*.yaml` unless
  the audit finds a concrete bug AND the fix stays inside the file's
  documented schema
- Dependency add / remove / version bump
- SQLite schema migrations
- Refactoring for style alone (no mass `ruff --fix` or rename passes)
- Anything that requires a user decision mid-flight → pause for user

### Test-tuple drift policy

Record pre-audit pytest tuple. Every tuple change at every round must
be one of:

- **Expected +N**: a new regression test was added to lock in a bug
  fix. Log entry must name the test and the bug it guards.
- **Expected -N**: a test was deleted because it was a duplicate or
  covered a removed feature. Must be called out explicitly in round
  log; duplicate-test deletion requires user confirmation.
- **Unexpected drift**: halt condition.

## 3. Round structure (per-round 11-part Chinese log)

Each round appends to `docs/20260420-ralph_loop_log.md` under section
header `R-docs-audit-round-NN`.

### Round 1 — Code audit + bug fixes

Focus: the Python surface across `core/` + `scripts/` + `dev/scripts/`
+ `tests/`.

Scan for:
- Unused imports (excluding `__future__.annotations`)
- Silent `except: pass` — case-by-case legitimacy review; fix the
  illegitimate ones (e.g. swallowing `AttributeError` on a typed
  variable)
- Shadowed builtins (rename only if the shadow actually hides a real
  builtin usage in the same scope; otherwise flag and leave)
- Dead code (unreferenced functions, `if False:` branches, unreachable
  return paths)
- Obviously-wrong type hints
- Light perf bugs (e.g. O(n^2) in a tight loop where O(n) is a
  one-line fix)
- Docstring drift (paths that no longer exist, params removed from
  signature)

RUN:
- `pytest tests/ -q` at round start AND round end
- `--help` smoke on at least 15 scripts (both `scripts/` and
  `dev/scripts/`)
- Import sweep: `core/research`, `core/paper_trading`, `core/data`,
  `core/factors`, `core/mining`, `core/signals`, `core/backtest`,
  `core/portfolio`, `core/reporting`

Bug fixes allowed. Add a regression test for each behavior-affecting
fix. Update round log with bug list + fix list + test-count delta +
tuple before/after.

### Round 2 — README.md dev-content trim

Focus: `README.md` only. CLAUDE.md is R3.

Remove from README:
- All `v1.x` footer entries (e.g. `README v1.3 — ...`, `README v1.4
  — ...`). Keep only the final canonical header
- Per-round commit hashes (e.g. `R-epost-cand2-round-NN`, lineage tag
  lists)
- Launcher / ralph-loop mentions (`dev/scripts/loop/start_*_loop.sh`,
  `EPOST_CAND2_DONE`, `AUDIT3DONE`, `.claude/ralph-loop.local.md`)
- `docs/20260420-ralph_loop_log.md` references EXCEPT one sentence in
  §17 pointing at it as the full-history source
- §17 "研究历史摘要" — compress to a short intro paragraph + one
  bullet per completed phase pointing at that phase's synthesis doc

Keep in README:
- §1 project overview (§1.4 current-state bullets stay, but scrub
  out `v1.x footer` / `commit hashes` / `ralph-loop round count`)
- §2 invariant constraints
- §3 architecture
- §4 directory structure (`dev/` folds into a one-line appendix bullet)
- §5 env setup
- §6 quick-start
- §7 core workflows
- §8 scripts manual (quant ops only; `dev/scripts/` folds into a
  one-line pointer)
- §9-16 (features / testing / config / troubleshooting)
- §17 compressed (per above)
- §18 appendix — the "README 维护约定" block can be kept or trimmed
  at auditor's discretion

Verify every remaining script / path / feature number resolves
against current code. Test counts update from post-R3 baseline.

### Round 3 — CLAUDE.md slim + baseline rebuild + DOCSAUDITDONE

Focus: `CLAUDE.md` + `data/baseline/latest.json` + final synthesis.

CLAUDE.md target: **< 600 lines** (currently 770).

Compression candidates (in order of safe savings):
- "1m Bar Pipeline" block (~75 lines) → 10-line summary + pointer to
  `docs/20260424-claude_md_phase_e_history.md` (will append there)
- "Trades Backfill Pipeline" block (~75 lines) → 10-line summary
- "Data Provenance Sidecar" (~42 lines) → 5-line summary + pointer
- "Factor Pipeline Contract" (~40 lines) → 10-line summary
- "Multi-TF Timing Contract" (~65 lines) → 10-line summary
- "Notify Module" (~25 lines) → 5-line summary
- "Phase D: Iterative Optimization Loop" block — if Phase D is no
  longer the active driver, compress to a pointer
- "Key File Locations" — keep only top 10 entries users genuinely
  need; move the rest to the history doc

Keep in CLAUDE.md:
- Invariant Constraints
- QQQ Outperformance Rule
- Pricing and Valuation Semantics
- Confirmed Done (already compressed in R8; keep)
- Current TODO Checklist
- Autonomous Decision Authority
- Work Method
- Git Safety
- Environment (Python path, test baseline pointer)

Archived detail appends to
`docs/20260424-claude_md_phase_e_history.md` — do not lose content,
just move it.

Baseline rebuild:
- `python dev/scripts/baseline/build_research_baseline_snapshot.py`
- Verify `jq '.tests' data/baseline/latest.json` matches post-audit
  pytest tuple

Final synthesis:
- New doc `docs/20260424-docs_audit_3round_final_synthesis.md`
  covering: exec summary / round table / bug list across R1 / README
  diff summary / CLAUDE.md diff summary / pytest tuple stability
  / halt-condition summary / hard invariants preserved / follow-ups
  / cross-reference
- Concludes with `<promise>DOCSAUDITDONE</promise>`

## 4. Rules of engagement

### Authorized autonomously

- Bug fixes inside existing files (add regression test for each
  behavior-affecting fix)
- Unused-import removal (per-file test verification)
- Docstring / comment corrections
- Dead-code removal (verify unreferenced via grep before deletion)
- README.md trims within §3 R2 guardrails
- CLAUDE.md slim within §3 R3 guardrails
- Appending compressed content to
  `docs/20260424-claude_md_phase_e_history.md`
- `data/baseline/latest.json` regeneration
- New doc `docs/20260424-docs_audit_3round_final_synthesis.md`

### Must pause for user

- Any edit to `PRODUCTION_FACTORS` or any `config/*.yaml`
- Any dependency add / remove / version bump
- Any rename of a public function / class / module
- Any SQLite schema change
- Any deletion of a test (duplicate or otherwise)
- Any test-tuple drift that does NOT correspond to a new regression
  test from this loop

### Halt conditions (any one triggers halt)

1. 3 rounds completed (hard ceiling)
2. Unexpected pytest tuple drift (see §2 drift policy)
3. Core import breaks at any point
4. Disk free < 10 GB
5. A finding requires a schema migration or a new PRD
6. README or CLAUDE.md reference breaks (a referenced path fails
   to resolve)
7. Bug fix requires user decision (e.g. behavior was ambiguous;
   don't guess — pause)

## 5. Per-round output format (11-part Chinese)

1. 本轮主题
2. 本轮目标
3. 为什么这轮优先做它
4. 做了什么
5. 修改了哪些文件
6. 跑了哪些测试/实验 (include pytest tuple before/after)
7. 结果如何 (bug list + fix list + tuple delta)
8. 当前发现的新问题/新机会
9. 剩余风险
10. 下一轮建议方向
11. Halt 条件检查

## 6. Completion promise

`DOCSAUDITDONE` — emit only when:
- 3 rounds complete
- Pytest tuple matches pre-audit baseline OR drift is fully explained
  by regression tests added in R1
- README.md dev-process content removed
- CLAUDE.md < 600 lines
- `data/baseline/latest.json` regenerated
- Final synthesis doc exists

## 7. One-sentence summary

**Three focused rounds: fix bugs the audit surfaces, strip dev-process
content from README, slim CLAUDE.md below 600 lines — leaving the
codebase in a cleaner state with docs pointing at user-facing truth.**
