/ralph-loop:ralph-loop Execute ONE round of the intraday mining phase defined in `docs/prd_intraday_mining_loop.md`. Read that PRD (and CLAUDE.md) BEFORE anything else every iteration — they are your source of truth.

## Protocol for this round (follow in order, do NOT skip)

### 1. Pre-round audit (≤5 min)
- `git log --oneline -15` — read last round's commit subject
- `git status` must be clean; else stop and ask the user
- Open PRD Appendix A round log; identify next pending round number + expected topic
- `pytest tests/ -q` with 3-min timeout; must be green; else fix FIRST
- Inspect `data/mining/archive.db`: count `score=-999` rows, distinct `lineage_tag` values, trials missing `lineage_tag`. If anomaly → this round's topic becomes "fix it" not the menu topic.

### 2. Topic pick
Pick ONE topic from PRD §3 menu (A–L), §3.1 items first while any remain open. Post a 中文 plan with:
- 当前阶段 (Round N / Topic X)
- 本轮目标 (one sentence)
- 为什么选它 (1-2 sentences tied to §3 priority OR pre-audit finding)
- 计划的 lineage_tag (bump only if methodology changes — see PRD §2.3)

### 3. Implementation
One main goal only. Small edits. Focused tests for every new behavior. No combining topics.

### 4. Pipeline run (mandatory before committing)
- `pytest tests/ -q` — must be green
- If the round touches mining: one smoke run with the round's lineage_tag (`--trials 20 --budget 300` default; escalate to `--trials 80 --budget 1800` ONLY when the topic calls for it, e.g. Topic A)
- If the round touches timing: run `scripts/validate_timing_value.py --symbols SPY QQQ AAPL NVDA MSFT --start-date 2024-01-01` and capture its verdict line

### 5. Post-round audit (≤5 min)
- Scan new warnings in smoke/validation log
- Query archive by THIS round's lineage_tag: any `score=-999`? any NaN crash? any QQQ-gate bypass?
- If a new silent failure appeared, round is NOT DONE until fixed in this same round

### 6. CLAUDE.md update
Facts only, no plans. Update the completion table if this round closed a listed item.

### 7. Commit
- `git add` specific files (NEVER `-A`)
- Subject: `Round N (Topic X): <short description>`
- Body: 11-part 中文 report (当前阶段 / 本轮目标 / 为什么先做它 / 做了什么 / 修改了哪些文件 / 跑了哪些测试 / 当前结果 / 剩余风险 / 下一轮建议 / TODO checklist)
- Include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

### 8. PRD round log update
Edit `docs/prd_intraday_mining_loop.md` Appendix A: add row for this round (date / topic / lineage_tag / one-line outcome). Commit as a small doc-only commit `docs: update round log for Round N`.

## Hard rules (violate any → stop and ask user)
- No changes to CLAUDE.md "Invariant Constraints" section
- No `apply_extra_shift=True` in production paths
- No `fillna(20)` / constant-VIX fallbacks in live path
- No archive writes skipping `save_eval` / `promote`
- No path bypasses `passed_qqq_gate` check for promotion
- No round combines two topics from §3 menu
- No round uses `--trials > 200` without explicit user sign-off
- If `pytest tests/` passing count drops below **1009**, STOP and fix before anything else
- No edits to `config/system.yaml::initial_capital_usd` (currently **$100,000**); this is the active experimental scale and changing it invalidates the lineage

## Exit this round early if
- Any hard rule above is about to be violated
- A blocker requires user design input (new schema / new config section / new external dep)
- The topic turns out to be blocked by a not-yet-done topic → pick a different one

## Current state (as of 2026-04-20)
- Tests passing: **1009**
- Latest lineage_tag: **`post-2026-04-20-capital-100k`** (bumped from `post-2026-04-20-closeout` after capital raised 10k → 100k)
- initial_capital_usd: **$100,000**
- Rounds completed: 0.5 (smoke + audit + NaN blocker fix `d562934` + capital bump)
- Next expected topic: **A** (full-budget smoke so QQQ gate actually fires at Stage 6, now at realistic $100k scale)

## Deliverables per round
1. At least one focused test added OR one focused validation script output captured
2. One main commit + one PRD-log commit
3. CLAUDE.md updated if any listed closeout item was affected
4. 11-part 中文 report in the main commit body

## Reference docs (must read every iteration)
- `docs/prd_intraday_mining_loop.md` — the phase PRD (topics A–L, exit criteria, risk watchlist)
- `CLAUDE.md` — system invariants, pricing semantics, factor pipeline contract, multi-TF timing contract

When in doubt, re-read the PRD. When still in doubt, stop and ask the user — never guess on methodology decisions.
