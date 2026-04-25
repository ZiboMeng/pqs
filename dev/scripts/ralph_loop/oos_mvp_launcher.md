# OOS MVP — Ralph-Loop Launcher Prompt

**How to use**: invoke the `ralph-loop` skill (`/ralph-loop` in
Claude Code, or via the Skill tool) and paste the prompt below as
the loop's body. The prompt contains the full execution contract;
the loop will repeat until completion promise is emitted.

**PRD source**: `docs/prd/20260425-oos_mvp_ralph_loop_execution.md`
**Lineage tag**: `oos-mvp-2026-04-25`
**Completion promise**: `OOSMVPDONE`
**Max iterations**: 8 (7 rounds + 1 retry buffer)

---

## Prompt to paste into ralph-loop skill

```
Execute one round per docs/prd/20260425-oos_mvp_ralph_loop_execution.md
section 3. lineage_tag=oos-mvp-2026-04-25 for all artifacts.

ROUNDS (each round = one ralph-loop iteration):

Round 1 = robustness window schema (core/research/robustness/window_spec.py)
          + runner skeleton (NotImplementedError stub) + schema validation
          tests. Acceptance: 5+ schema test cases pass; pytest no regression.

Round 2 = robustness_eval real runner implementation + run on RCMv1 +
          Cand-2; produces candidate_robustness_window.yaml + 
          robustness_eval.{json,md} per candidate; evidence_class set
          to pseudo_oos_robustness. Acceptance: both candidates have
          full artifact set; pytest no regression.

Round 3 = M12 concentration report module (warning + extreme tier per
          PRD v3 §C); integrated into R2 runner so robustness eval
          emits concentration_report.{json,md} alongside robustness
          eval. Report-only — NO hard block. Acceptance: 8+ tier
          classification tests; pytest no regression.

Round 4 = Watch exposure section integration into core/reporting/
          master_report.py + scripts/paper_drift_report.py. Top-table
          + prose format. Graceful degrade if watch sidecar missing.
          Acceptance: section appears in both report types for both
          candidates; pytest no regression.

Round 5 = Forward manifest SCHEMA-ONLY (core/research/forward/
          manifest_schema.py). No runner code. PRD v3 §B explicit:
          schema only no runner. Acceptance: schema validator works;
          NO forward execution code; pytest no regression.

Round 6 = Integration smoke (dev/scripts/oos_mvp/smoke.py) end-to-end
          on both candidates + negative-result simulation (deliberately
          set evidence_class=historical_replay and verify schema
          validator rejects). Acceptance: smoke passes both candidates;
          negative simulation correctly rejected; pytest no regression.

Round 7 = Docs sync (CLAUDE.md TODO entry, docs/INDEX.md,
          docs/memos/20260425-oos_mvp_close.md with pseudo-OOS framing
          NOT deployable-OOS framing) + baseline rebuild via
          dev/scripts/baseline/build_research_baseline_snapshot.py
          --run-tests. Acceptance: pytest tuple matches expected
          (1617 baseline + N new tests from R1-R6); baseline
          rebuilt; closeout memo correctly framed; emit
          <promise>OOSMVPDONE</promise> at top level of assistant
          reply (NOT only inside committed markdown — the harness
          detects promises in assistant-turn output).

AUTONOMOUS MODE per PRD §4:
- Authorized: code in core/research/{robustness,concentration,forward}/,
  tests/unit/research/, tests/unit/reporting/, tests/integration/,
  data/research_candidates/<id>_* artifacts, dev/scripts/oos_mvp/,
  edits to core/reporting/master_report.py and
  scripts/paper_drift_report.py (only the watch-exposure section
  hooks listed in R4), updates to CLAUDE.md / docs/INDEX.md / 
  docs/memos/, baseline JSON rebuild.
- Must Pause for user: any HARD invariant violation; same round
  retried twice; pytest drift not explained by this round's
  regression tests; round runs > 30 min; artifact size anomaly
  (single file > 10 MB or cumulative > 100 MB).
- Halt: HARD invariant violated, OR Must-Pause without user
  reauthorization, OR OOSMVPDONE successfully emitted.

HARD INVARIANTS (per PRD §2 — violation halts loop):
- Do NOT modify any config/*.yaml (incl. production_strategy.yaml)
- Do NOT modify core/factors/factor_registry.py::PRODUCTION_FACTORS
- Do NOT add new dependencies (requirements*.txt / pyproject.toml
  unchanged)
- Do NOT rename public functions
- Do NOT migrate SQLite schema (registry.db untouched)
- Do NOT delete tests
- Do NOT modify candidate_registry state-machine enum (S0/S1/S2/S5
  stays 4-state)
- Do NOT modify core/research/frozen_spec.py
- Do NOT modify any frozen candidate spec
  (data/research_candidates/*.yaml — only the new
  *_robustness_window.yaml are added)
- Do NOT rebuild data/daily/*.parquet (round-3 stable)
- Do NOT modify data/ref/splits.parquet
- Do NOT start work outside R1-R7 scope

PYTEST DRIFT RULE:
- Record pytest tuple (passed, skipped, xfailed) at start of every round.
- Record pytest tuple at end of every round.
- Any drift NOT explained by regression tests added during THIS round
  → MUST halt loop. Do not attempt to "fix" silently.

PER-ROUND COMMIT MESSAGE FORMAT:
  oos-mvp R<N>: <scope>: <summary>
Examples:
  oos-mvp R1: robustness window schema + runner skeleton
  oos-mvp R3: M12 concentration report module + integration
  oos-mvp R7: docs sync + baseline rebuild + closeout memo

PER-ROUND CHINESE REPORT (append to docs/20260420-ralph_loop_log.md
as R-oos-mvp-2026-04-25-round-NN):
1. 本轮目标
2. 做了什么 + 修改了哪些文件
3. 跑了哪些测试 + 当前结果 (pytest tuple before/after)
4. 剩余风险
5. 下一步
6. (其余 6 部分 per existing ralph_loop_log.md convention)

FRAMING RULE for R7 closeout memo:
- MUST frame R1-R6 results as "pseudo-OOS robustness eval done"
- MUST NOT frame as "OOS validated" or "deployable evidence"
- MUST link to PRD v3 §1.1 + §1.3 reasoning that real deployable
  OOS requires forward observation, NOT historical robustness.
- The chronic trap PRD v3 warns about (§1.3 "在更可信的数据上，
  重新做一轮更高级的 in-sample 叙事") — closeout memo must
  explicitly NOT do this.

EMIT OOSMVPDONE only when ALL of these are true:
- 7 rounds all committed with proper message format
- pytest 全 pass, all drift explained by regression tests added
  during this batch
- baseline data/baseline/latest.json rebuilt with --run-tests
- Both candidates have full artifact set:
  robustness_window.yaml + robustness_eval.{json,md} +
  concentration_report.{json,md}
- master_report.py and paper_drift_report.py both render watch
  exposure section
- forward manifest schema validator works but no runner code exists
- docs/memos/20260425-oos_mvp_close.md exists with pseudo-OOS framing
- CLAUDE.md "Current TODO" reflects OOS MVP done
- docs/INDEX.md reflects new PRD + memo
- The R7 assistant-turn reply emits the literal promise tag at top
  level: <promise>OOSMVPDONE</promise>

═══════════════════════════════════════════════════════════
CRITICAL - Ralph Loop Completion Promise
═══════════════════════════════════════════════════════════

To complete this loop, output this EXACT text:
  <promise>OOSMVPDONE</promise>

STRICT REQUIREMENTS:
  ✓ Use <promise> XML tags EXACTLY as shown above
  ✓ The statement MUST be completely and unequivocally TRUE
  ✓ Do NOT output false statements to exit the loop

If the loop should stop, the promise statement will become
true naturally. Do not force it by lying.
═══════════════════════════════════════════════════════════
```

---

## Notes for the user

- **Before launching**: confirm the OOS framework workstream is
  unfrozen per round-3 close memo (currently still frozen pending
  user explicit unfreeze). The ralph-loop will halt on HARD
  invariant if it tries to do anything outside R1-R7 scope.
- **During loop**: monitor `tail -f .claude/ralph-loop.local.md`
  per ralph-loop convention; or just let it run.
- **If loop halts mid-round**: read the round's last commit's
  Chinese report in `docs/20260420-ralph_loop_log.md`; decide
  whether to authorize continuation or revert and re-scope.
- **Expected duration**: 7 rounds × ~10-30 min each = 1-4 hours
  depending on complexity. Less if R1-R6 land cleanly first try
  (no Must-Pause).
- **Cost**: each round is one Claude session; ralph-loop self-
  triggers via the stop hook. Budget accordingly.

## How to invoke

### Option A — bash launcher (preferred)

```bash
bash dev/scripts/ralph_loop/launch_oos_mvp.sh
```

The launcher does five preflight checks (required files / unfreeze
authorization / clean working tree / baseline tests / prompt body
extraction) and then stages `.claude/ralph-loop.local.md` with the
prompt body extracted from this file's first ``` block. After the
launcher exits, just send any first turn in Claude Code (e.g.,
"begin oos mvp loop") — the plugin's stop hook reads the staged
state file on the assistant's first Stop and re-feeds the prompt
to start round 1.

Flags:
- `--check-only` — preflight only, do not write state file
- `--force` — skip the working-tree-clean prompt

Halt early: `rm .claude/ralph-loop.local.md`.

### Option B — slash command (manual)

Inside Claude Code:
```
/ralph-loop --max-iterations 8 --completion-promise OOSMVPDONE
```

Then paste the prompt block above (between the ``` markers) when
prompted. Or invoke via Skill tool with the same prompt content as
the `args` parameter.
