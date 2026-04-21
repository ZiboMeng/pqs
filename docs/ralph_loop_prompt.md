# Ralph-Loop Prompt — Intraday Mining Phase

You are executing one round of the ralph-loop defined in
`docs/prd_intraday_mining_loop.md`. Read that PRD first every time.
Do not skip it.

## Execution contract for THIS round

Follow every step in order. Do not skip ahead. Do not combine topics.

### Step 1 — Pre-round audit (≤5 min)

1. `git log --oneline -15` — note the last round's commit subject.
2. `git status` — must be clean. If not, stop and ask the user.
3. Read the **Appendix A round log** in the PRD. Identify the next
   pending round number and expected topic.
4. Run `pytest tests/ -q` with a 3-min timeout. Must be green. If
   not, stop and fix BEFORE picking a topic.
5. Inspect `data/mining/archive.db` for silent failure signals
   (count of `score=-999` rows, distinct `lineage_tag` values,
   trials without `lineage_tag`). If anything looks wrong, the
   round's topic becomes "fix this" instead of the menu topic.

### Step 2 — Topic pick

Pick exactly ONE topic from the PRD's §3 menu (A-L), prioritizing
§3.1 items while any remain open. Post a 中文 round plan with:

- 当前阶段 (Round N / Topic X)
- 本轮目标 (one sentence)
- 为什么选它 (1-2 sentences tied to PRD §3 priority or pre-round
  audit finding)
- 计划的 lineage_tag (bump only if methodology changes — see PRD §2.3)

### Step 3 — Implementation

One main goal only. Small steps. Prefer focused edits over large
rewrites. Add focused tests for every new behavior.

### Step 4 — Pipeline run

Mandatory before committing:

- `pytest tests/ -q` — must be green
- If the round touches mining: one smoke run with the round's
  lineage_tag (start with `--trials 20 --budget 300`; escalate to
  `--trials 80 --budget 1800` only when the topic explicitly calls
  for it, e.g. Topic A)
- If the round touches timing: run `scripts/validate_timing_value.py
  --symbols SPY QQQ AAPL NVDA MSFT --start-date 2024-01-01` and
  verify it still produces a verdict

### Step 5 — Post-round audit (≤5 min)

- Scan new warnings in the smoke/validation log
- Query archive by this round's lineage_tag; any `score=-999` rows?
  any crashes? any unexpected NaN propagation?
- If a new silent failure appeared, the round is NOT DONE until it's
  fixed in the same round.

### Step 6 — CLAUDE.md update

Only facts, not plans. Record what was actually completed. Update
the Constraint-completion / closeout table if this round closes a
listed item.

### Step 7 — Commit

- `git add` the specific files (never `-A`)
- Commit subject: `Round N (Topic X): <short description>`
- Body: 11-part 中文 report format (当前阶段 / 本轮目标 / 为什么先做它 /
  做了什么 / 修改了哪些文件 / 跑了哪些测试 / 当前结果 / 剩余风险 /
  下一轮建议 / TODO checklist)
- Include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

### Step 8 — PRD round log update

Edit `docs/prd_intraday_mining_loop.md` Appendix A: add a row for
this round with date / topic / lineage_tag / one-line outcome.
Commit this as a small doc-only commit (`docs: update round log for
Round N`).

## Hard rules (violate any → stop and ask user)

- No changes to CLAUDE.md "Invariant Constraints" section
- No `apply_extra_shift=True` in production paths
- No `fillna(20)` / constant-VIX fallbacks in live
- No archive writes that skip `save_eval` or `promote`
- No path that bypasses `passed_qqq_gate` check for promotion
- No round that combines two topics from §3 menu
- No round that uses `--trials > 200` without explicit user sign-off
- If `pytest tests/` drops below 1009 passing, STOP and fix before
  doing anything else

## Exit this round early if

- Any hard rule above was about to be violated
- A blocker requires user design input (new schema, new config
  section, new external dependency)
- The topic turns out to be dependent on a not-yet-done topic (pick
  a different one)

## Deliverables per round

1. Minimum one focused test added OR one focused validation script
   output captured
2. One main commit + one PRD-log commit
3. CLAUDE.md updated if a listed closeout item was affected
4. 11-part 中文 report in the commit body

## Current state reference (as of 2026-04-20)

- Tests passing: 1009
- Latest lineage_tag: `post-2026-04-20-closeout`
- Rounds completed: 0 (smoke + audit + NaN blocker fix)
- Next expected topic: **A** (full-budget smoke so QQQ gate actually
  fires at Stage 6)

When in doubt, re-read the PRD. When still in doubt, stop and ask
the user — never guess on methodology decisions.
