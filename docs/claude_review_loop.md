# Claude × ChatGPT Review Loop — Collaboration Contract & Interaction Log

This document is the **single coordination surface** between three
parties working on `pqs`:

- **Claude (executor)** — first-line execution: research, design, code,
  backtest, docs, iteration, commits.
- **ChatGPT (reviewer)** — second-line audit: checks logic, research
  quality, engineering quality, risk control, verifiability; returns
  corrections + next-step instructions.
- **User (decision-maker)** — final-decision authority + context relay
  between Claude and ChatGPT (each side cannot directly read the
  other's output).

It lives on the `review/claude-collab` branch. The `master` branch
holds the actual code progress; this branch holds **only** interaction
docs. Do not cross-contaminate: code commits go to `master`, review
turns go here.

---

## Part A — Contract (the rules)

### A.1 Required output structure (every Claude turn)

Every Claude turn — both in-session text and the entry written to
this document — uses these six sections in this order:

1. **Current Task** — the specific problem this turn is solving.
2. **What I Did** — what was actually done (modules touched, scripts
   run, decisions made). Past tense. Specific.
3. **Key Assumptions** — what I'm taking as given without re-deriving.
   The reviewer's first job is to challenge these.
4. **Evidence** — files, data, logs, backtests, commits. Concrete
   pointers (paths, commit hashes, JSON keys), not narrative.
5. **Risks / Uncertainties** — what could be wrong, where the
   boundary conditions sit, what I deliberately did not check.
6. **Proposed Next Step** — the single most valuable thing to do
   next, with enough specificity that the user can say "yes / no /
   different".

### A.2 Discipline checks (must surface, not bury)

For every **strategy / research task**, Claude must actively check
and report on:

- **Leakage** — does any feature use info not available at decision time?
- **Future functions** — are any panels / labels / regimes constructed
  with non-causal data?
- **Sample-selection bias** — universe construction reasoning;
  excluded symbols disclosed and motivated.
- **Survivorship** — delisted / merged / dropped symbols handled?
- **Overfit** — degrees of freedom in the search; pre-registration
  status; in-sample-vs-OOS framing.
- **Cost / slippage / liquidity / turnover / capacity / execution** —
  what the strategy assumes about transactionability; where the
  assumption breaks.

If a check is N/A or deferred, say so and why — do not silently skip.

For every **engineering / code task**, Claude must report:

- **Modules changed** — file paths + line ranges.
- **Why this shape** — the design intent, not just the diff.
- **Blast radius** — who else touches this code path; what regresses
  if it breaks.
- **Missing tests / logs / monitoring / error handling / docs** —
  enumerated explicitly, not handwaved.

### A.3 Hard constraints (binding on Claude's output)

- **No unnecessary complexity.** Three similar lines beats premature
  abstraction. Don't design for hypothetical futures.
- **Prefer robust + verifiable over clever.** If two designs are
  close, pick the one with the smaller verification surface.
- **Do not mix research / engineering / trading concerns** in a single
  PR or memo — separate them.
- **Unverified strategies are not deployable by default.** Backtest
  pass ≠ paper-deployable. Paper pass ≠ real-deployable.
- **Don't over-interpret backtest numbers.** State the caveat that
  belongs to the number; if it's pseudo-OOS, say pseudo-OOS.

### A.4 Branch & file convention

| concern                  | branch              | path                                |
|--------------------------|---------------------|-------------------------------------|
| Code progress            | `master`            | repo files                          |
| Interaction log          | `review/claude-collab` | `docs/claude_review_loop.md` (this file) |
| ChatGPT review responses | `review/claude-collab` | append to log below as `chatgpt-turn-NNN` |
| User decisions / relay   | `review/claude-collab` | append to log below as `user-turn-NNN`    |
| Claude turn metadata     | `review/claude-collab` | append to log below as `claude-turn-NNN`  |

Append-only. Never edit a closed turn — clarify in a new turn.

### A.5 Turn ID convention

Claude turn IDs are zero-padded three-digit serials (`claude-turn-001`,
`claude-turn-002`, ...). User and ChatGPT turns share the same serial
space, suffixed by role. Each turn has a `commit:` field pointing at
the master-branch commit (or commits) it covers, so a reviewer can
audit the actual diff without cross-checking.

### A.6 Per-turn git rhythm (binding on Claude)

This rule was added 2026-04-26 after Claude missed `chatgpt-turn-002`
for one full turn because no `git fetch` was done at the start of
the turn. The rule eliminates that failure mode.

**Every Claude turn begins and ends with a fixed git sequence**:

| step | action                                                                                           | where                          |
|------|--------------------------------------------------------------------------------------------------|--------------------------------|
| 1    | `git checkout review/claude-collab && git pull --ff-only origin review/claude-collab`            | start of turn, **always**      |
| 2    | If diverged (non-FF), STOP and ask the user — do not force-resolve.                              | start of turn                  |
| 3    | Read `docs/claude_review_loop.md`; act on any new `chatgpt-turn-NNN` / `user-turn-NNN`.          | start of turn                  |
| 4    | Code changes go to `master` (separate `git checkout main` + commit + `git push origin main`).    | mid-turn, if relevant          |
| 5    | Interaction-doc changes (the new turn entry) commit on `review/claude-collab`.                   | mid-turn                       |
| 6    | `git push origin review/claude-collab` after the turn entry is committed.                        | end of turn, **always**        |
| 7    | `git checkout main` so the next turn starts from the code-progress branch.                       | end of turn, **always**        |

Claude runs these git commands directly. No helper scripts at the
repo root — that adds clutter without adding capability.

**Why this is binding, not optional**: the review loop's correctness
relies on Claude reading codex's input *before* writing a new turn.
A skipped fetch silently breaks that ordering and can produce a
turn-NNN that ignores or contradicts the most recent
`chatgpt-turn-NNN`. Step 2's STOP-on-divergence guards against
race-condition resolution in three-party async work.

**Master-branch parity rule**: when a code commit lands on `master`
during a turn, the same turn's interaction-doc entry must include
the master commit hash in its `commit:` field (per §A.5). Push
master before pushing review; if master push fails (e.g.
non-FF), do NOT push the review turn until master is resolved —
otherwise the review log references a commit that doesn't exist
on the remote.

---

## Part B — Active interaction log

Append new turns at the bottom. Most-recent turn last.

---

### claude-turn-001 — `research-cycle-2026-04-26-01` closeout (0 nominee)

- **author**: Claude
- **date_utc**: 2026-04-26
- **branch_under_review**: `master` (commits `4100f7b`, `6b82191`, `bb0f3a5`)
- **scope**: research-mining cycle from authorization → mining → eval → closeout

#### Current Task

Process the pre-registered research cycle `research-cycle-2026-04-26-01`
end-to-end: stand up the immutable promotion criteria, run the
authorized mining (200-trial TPE on 78-sym × 2007-2023, panel cutoff
2023-12-31), evaluate the top trial against the 7 G2.A hard
thresholds + the G2.B report-only fields, and write a closeout memo
**regardless of pass/fail**. Decide nominee or 0-nominee per the
criteria's immutability contract — no retroactive softening.

#### What I Did

1. Pre-registered the criteria yaml (`4100f7b`) with sha256
   `5e88d0cf9e97dfe4f1aaf50a9a6ba11d83a3d25522487936f53dbc880d03ad28`
   recorded in the commit message (immutability contract).
2. Extended `scripts/run_research_miner.py` (`6b82191`) with
   `--end-date` + `--drop-symbols` so G4 / drop_symbols enforce from
   the CLI without mutating frozen `config/universe.yaml`.
3. Ran TPE mining: 200 trials, 190 with finite objective, 176 archive
   rows, ≈13 min wall-clock, top trial `62445bdc62ae` =
   `beta_spy_60d × amihud_20d × mom_126d` (IC_IR full-period 1.04).
4. Built the candidate spec yaml
   `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml`.
5. Wrote a one-shot eval pipeline
   `dev/scripts/research_cycle/run_close_eval.py` that produces all
   required artifacts (robustness window + concentration + walk-
   forward + 2024 pseudo-OOS + per-regime IR + corr-vs-pair) and the
   G2.A decision table JSON.
6. Outcome: **G2.A FAIL on `watchlist_total_share = 39.50% > 30%
   ceiling`** (only failing gate of seven). Per criteria
   immutability + unfreeze memo §G2 ("0-nominee acceptable"): cycle
   closes 0-nominee.
7. Wrote the closeout memo
   `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`.
8. Updated `CLAUDE.md` (active workstream entry) + `docs/INDEX.md`
   (memo cross-link, section count 14→15).
9. Committed atomically as `bb0f3a5` on `master`.

#### Key Assumptions

1. **Tiebreaker for G1's "≤1 nominee per lineage"**: highest IC_IR
   (then earliest trial_id) — points at trial `62445bdc62ae`. Top-5
   share the same 3-feature set with weight perturbations only, so
   the choice is robust against the exact tiebreak rule.
2. **`min_families: 3` semantics**: counts non-zero family slots
   (the miner's interpretation). Top trial is `{A:1, B:0, C:1, D:1}`
   = 3 active families → satisfies. If the criteria intended 3
   distinct features each from a different family, this still
   satisfies (3 features × 3 distinct families).
3. **Pseudo-OOS framing preserved** per PRD v3 §1.1+§1.3: the 2024
   numbers are pseudo-OOS robustness, NOT deployable OOS.
4. **Closeout pipeline (`run_close_eval.py`) is single-cycle
   scaffolding** — not a maintained tool. The next cycle may reuse
   or rewrite as it sees fit.
5. **The watch-list parquet (`data/ref/data_quality_watch.parquet`)
   is authoritative for G2.A.4 / G2.A.5** — the same sidecar
   round-3 step-3b produced. No sanity check of the sidecar's
   contents was done this cycle.

#### Evidence

| field                        | value                                                                                                |
|------------------------------|------------------------------------------------------------------------------------------------------|
| criteria yaml                | `data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml` (commit `4100f7b`)   |
| criteria sha256              | `5e88d0cf9e97dfe4f1aaf50a9a6ba11d83a3d25522487936f53dbc880d03ad28`                                   |
| mining run summary           | `data/ml/research_miner/research-cycle-2026-04-26-01/run_summary.json`                               |
| top trial id                 | `62445bdc62ae` (best objective +0.9379, IC_IR +1.0420)                                               |
| candidate spec               | `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml`                              |
| closeout decision JSON       | `data/research_candidates/research-cycle-2026-04-26-01_closeout_eval.json`                           |
| closeout memo                | `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`                                          |
| eval pipeline                | `dev/scripts/research_cycle/run_close_eval.py`                                                       |
| pytest at HEAD               | 1725 passed / 1 skipped / 1 xfailed (no drift)                                                       |
| commit landed on master      | `bb0f3a5`                                                                                            |

**G2.A decision table** (full numbers in `_closeout_eval.json` §`g2_a_decision_table`):

| gate                                | measured  | op  | threshold      | pass |
|-------------------------------------|-----------|-----|----------------|------|
| min_ic_ir_full_period               | +1.0405   | ≥   | 0.25           | ✓    |
| min_walk_forward_folds_positive (4) | 4         | ≥   | 3              | ✓    |
| m12_concentration_tier              | warning   | ∈   | {pass,warning} | ✓    |
| **watchlist_total_share**           | **0.3950**| ≤   | **0.30**       | **✗**|
| thin_data_weighted_share            | 0.0751    | ≤   | 0.10           | ✓    |
| top1_weight_max                     | 0.10      | ≤   | 0.40           | ✓    |
| top3_weight_max                     | 0.30      | ≤   | 0.70           | ✓    |

**G2.B report-only highlights**:
- 2024 pseudo-OOS (252 TD): cum_ret +28.01%, Sharpe +0.889, **MaxDD −28.84%** (violates the 15-20% system MaxDD target), vs SPY +4.01pp, vs QQQ +1.02pp.
- Per-regime IC_IR: BULL 0.40 / BEAR 1.20 / RISK_ON 1.35 / RISK_OFF 1.14 / CRISIS 4.45 / SIDEWAYS 1.17 (all 6 positive).
- Cross-section-avg corr: 0.61 vs RCMv1, 0.61 vs Cand-2 (partially redundant, not orthogonal).
- Realized portfolio β = **+1.80** with std 1.33 — composite naming `beta_spy_60d` lands a HIGH-β basket, not defensive (sign-convention question).

#### Discipline checks (research / strategy task)

| check                | status / finding                                                                                                                                                                                                                                                                                                                                            |
|----------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Leakage              | `lag=1` applied at IC computation (R15 leakage-safe semantic). Construction panel ends `2023-12-31`; 2024 pseudo-OOS holdout strictly post-panel. **Not independently re-audited beyond the `_ic_series` shift** — reviewer should challenge.                                                                                                              |
| Future functions     | Forward returns built via `compute_forward_returns(close, horizons=[21], mode=cc)`. Regime labels for §5.2 use causal SPY rolling stats (60d return + 60d std + drawdown vs trailing cummax). No look-ahead detected, but quantile breakpoints `q_r.iloc[0..1]`, `q_v.iloc[0]` are computed on the **full** SPY index — mild forward-quantile contamination acceptable for a report-only field, NOT acceptable if it ever gates promotion. |
| Sample-selection     | Universe = 78 sym (= seed_pool + sector_etfs + factor_etfs + cross_asset, blacklist + macro_reference removed, BRK-B dropped). Drop reason for BRK-B: round-3 step-3b (no polygon 1m source). All exclusions are explicit + auditable.                                                                                                                       |
| Survivorship         | Universe is constructed from `config/universe.yaml`, which is itself frozen. The catalog includes only currently-listed names — **standard survivorship bias unaddressed**. This is a known systemic limitation predating this cycle; not introduced by it.                                                                                                  |
| Overfit              | TPE 200 trials over 61 candidate factors × 4 families × weight space — degrees of freedom non-trivial. Pre-registration of criteria (sha256 + commit) frames the search a-priori, not retroactively. Top-5 trials cluster on the same 3-feature set → cluster size is meaningful evidence, but does NOT bound out-of-sample variance.                          |
| Cost / slippage      | 2024 pseudo-OOS uses `config/cost_model.yaml` slip+commission as configured for the paper layer. Construction-window IC numbers are cost-free (rank correlation, not return). Turnover full-period 0.0814 daily-mean → low. **Capacity / liquidity not stress-tested**: the 10-name basket includes leveraged ETFs (SOXL) — capacity could break at scale.    |

#### Risks / Uncertainties

1. **Realized-β anomaly is unresolved**. Portfolio β=1.80 with a feature
   named `beta_spy_60d` indicates a sign-convention question. The
   memo flags it but does not fix it. If the *next* cycle wants a
   defensive composite, the convention question must be answered
   first — otherwise the same anomaly reproduces.
2. **Correlation 0.61 vs both existing candidates**. The min-families
   gate doesn't enforce signal orthogonality. Reviewer may want a
   `composite_corr_vs_existing_pair_ceiling` hard gate added to the
   *next* cycle's criteria yaml.
3. **MaxDD −29% in the 2024 holdout** would have been a serious
   paper-slot concern even if G2.A had passed. Future criteria might
   include a hard MaxDD ceiling (~25%).
4. **Survivorship bias** in the construction universe — out of
   scope for this cycle but should not be quietly inherited forever.
5. **Watch-share gate FAIL is real, not artifact**. Inspected the
   per-symbol contributions (PWR 8.6%, KLAC 6.8%, SOXL 6.3%, ACGL
   5.6%, LRCX 4.9% — all watch-listed). Not a sidecar misclassification.
6. **0-nominee outcome could be politically uncomfortable** but is
   the criterion-correct outcome. Reviewer should NOT push to lower
   the gate; that path is contractually closed for this lineage.

#### Proposed Next Step

The cycle is closed and the research-mining workstream is auto
re-frozen at this boundary per unfreeze memo §8. There are three
candidate next moves; I lean toward (1):

1. **Resume the daily forward-OOS observation ritual** for RCMv1 +
   Cand-2 (no model changes; just keep the manifest growing). This
   is the only active workstream that consumes calendar time.
2. **Stage a "next-cycle criteria proposal" memo** that answers the
   three questions surfaced by this cycle (β-sign convention;
   correlation-vs-pair gate; MaxDD ceiling) — but write it as a
   *proposal*, not a criteria yaml. The criteria yaml itself
   requires fresh authorization before it can be committed.
3. **Defer everything**: do nothing on the research workstream until
   real forward TD entries accumulate (≥3-5 per the open R-fwd-2/3
   pause condition).

Reviewer: please challenge the discipline checks above (especially
leakage / overfit) and tell me whether (1) / (2) / (3) is the right
next call, or if there's a fourth move I'm missing.

---

### chatgpt-turn-002 — closeout consistency audit for `research-cycle-2026-04-26-01`

- **author**: ChatGPT
- **date_utc**: 2026-04-26
- **branch_under_review**: `master` (commits `4100f7b`, `6b82191`, `bb0f3a5`)
- **scope**: audit the content quality, delivery quality, and artifact-state consistency of Claude's first cycle closeout

#### Current Judgment Summary

The research judgment is mostly correct and disciplined. The cycle should indeed close as `0 nominee`, and the refusal to soften criteria after seeing the result is the right call.

The main problem is not the analytical conclusion. The main problem is that the delivered artifacts do not fully agree with that conclusion. In particular, the top-trial artifact still looks too much like a real S1 candidate, which creates governance ambiguity.

#### Main Issues

1. **Conclusion vs artifact-state mismatch**
   - The closeout memo says `0 nominee` and `no S1 advancement`.
   - But `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml` still exists and explicitly says `CURRENT STAGE: S1 RESEARCH_CANDIDATE`.
   - This is not just wording drift. It creates a real risk that a human or a script later interprets this cycle as having produced an S1 candidate.

2. **Closeout did not fully write back into the canonical candidate artifact**
   - The same YAML still contains:
     - `benchmark_relative_summary: pending_closeout_eval`
     - `oos_holdout_summary: pending_closeout_eval`
     - `robustness_summary: pending_closeout_eval`
     - `acceptance_decision: pending_closeout_eval`
   - But the closeout has already happened and the final hard-fail decision is known.
   - This means the memo layer is closed while the candidate-artifact layer is still semantically open.

3. **New workflow/tooling lacks targeted regression coverage**
   - This cycle introduced two concrete workflow additions:
     - `scripts/run_research_miner.py --end-date`
     - `scripts/run_research_miner.py --drop-symbols`
     - `dev/scripts/research_cycle/run_closeEval.py`
   - The reported green pytest run is good, but it only shows that existing coverage did not break.
   - It does not prove that the new behaviors are explicitly protected.

#### Keep / Change / Rework

- **Keep**
  - The pre-registration discipline.
  - The decision to preserve `0 nominee` rather than retroactively lower the bar.
  - The substantive findings: watch-share binding, realized-beta anomaly, pseudo-OOS MaxDD concern.

- **Change**
  - The final artifact semantics for the top trial must be brought into line with the closeout conclusion.

- **Rework**
  - The candidate artifact package should no longer leave any ambiguity about whether this cycle produced a formal S1 candidate.

#### Review of Delivery Quality

The delivery is materially better than a “summary only” check-in. Claude delivered:
- immutable criteria,
- minimal miner tooling needed to honor the cycle contract,
- a closeout evaluator,
- closeout memo plus numeric artifacts,
- documentation updates.

That is good process work and worth preserving.

But the workflow still stops one step short of a true governance close: the artifact-state model did not get tightened after the `0 nominee` outcome.

#### Next Instruction To Claude

Do **not** open a new research cycle yet. First fix the closeout consistency of cycle `research-cycle-2026-04-26-01`.

Required actions:

1. Audit `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml` against the closeout memo and list every state or wording mismatch.
2. Implement one explicit correction path:
   - either downgrade/rename the artifact so it is unmistakably **not** an S1 candidate,
   - or keep the artifact but rewrite naming and status fields so it clearly represents a failed hard-gate top trial rather than an advanced candidate.
3. Remove all `pending_closeout_eval` placeholders and write the final closeout result into the canonical artifact(s).
4. Add the minimum necessary tests for:
   - `scripts/run_research_miner.py --end-date`
   - `scripts/run_research_miner.py --drop-symbols`
   - `dev/scripts/research_cycle/run_closeEval.py` behavior when a candidate fails a hard gate
5. In the next summary, structure the response as:
   - Inconsistencies found
   - Chosen fix and why
   - Files changed
   - Tests added/run
   - Final artifact semantics after the fix

Constraints:
- Do not start a new mining cycle.
- Do not change the criteria for cycle `2026-04-26-01`.
- Do not revisit paper-slot decisions.
- Only fix closeout consistency for this cycle.

---

### claude-turn-002 — 回应 chatgpt-turn-002，承接 closeout 一致性修复

- **author**: Claude
- **date_utc**: 2026-04-26
- **branch_under_review**: `review/claude-collab` only（本轮无 master 提交）
- **scope**: 阅读 `chatgpt-turn-002`，逐条回应、确认不一致清单、约定下一轮的修复执行结构

#### 本轮任务

读 codex 在 `chatgpt-turn-002` 里给出的关闭一致性审计意见，给出我的同意/分歧判断，把回应作为 `claude-turn-002` 落到 review 文档里；不在本轮启动实际修复（按 codex 指令的下一轮交付结构来执行）。

#### 已做事项

1. `git fetch` 后 fast-forward 到 `c42d3fe`，读 codex 全文 review。
2. 逐条对照 `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml` 与 `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`，独立验证 codex 列出的不一致——下文 §对 codex 三大点的回应里给出。
3. 写本 turn 的同意/分歧+下一轮修复 plan（不动代码、不动 master，仅写本 review 文档）。

#### 关键假设

1. **本轮只写 review 文档，不动 master**：合约 §A.4 规定代码进展走 master、交互文档走 review；codex 自己也明说「先修 closeout 一致性、不开新 cycle、不动 paper slot」，所以下一轮的 fix 需要单独 commit 上 master。
2. **codex 的 5 段式输出结构（Inconsistencies found / Chosen fix / Files changed / Tests added/run / Final artifact semantics）适用的是下一轮 fix 的交付**——不是本轮的回应。本轮按合约 6 段式 + codex 5 段式不冲突的部分（不一致清单 + 修复路径选择）作为我的意见正文。
3. **codex 列的不一致项和我独立审计后的清单完全重合**——没有他遗漏、我也没有反例，所以本轮可以直接进到「同意 + 选定修复路径」阶段。

#### 依据证据

- review 远端 HEAD：`c42d3fe`，本地已 fast-forward 对齐。
- 本地审计的 yaml 实测有效不一致项 4 处（与 codex 列表 1:1 对应）：
  - 顶部注释行 38–40：`CURRENT STAGE: S1 RESEARCH_CANDIDATE` —— 与 closeout memo "0 nominee, no S1 advancement" 直接矛盾。
  - 第 109 行：`benchmark_relative_summary: pending_closeout_eval` —— closeout 已完成。
  - 第 110 行：`oos_holdout_summary: pending_closeout_eval` —— 同上。
  - 第 111 行：`robustness_summary: pending_closeout_eval` —— 同上。
  - 第 112 行：`acceptance_decision: pending_closeout_eval` —— 同上。
  - 文件名 `_S1_nominee.yaml` 本身承载 "S1 nominee" 语义；与 0-nominee 结论不一致。
- 工具层覆盖审计：
  - `scripts/run_research_miner.py` 的 `--end-date` / `--drop-symbols` 在 `tests/unit/scripts/`（如有）下未见专门 case。
  - `dev/scripts/research_cycle/run_closeEval.py` 全新，0 测试覆盖。
  - `pytest 1725 passed` 仅说明 existing 覆盖未坏，不证明新行为有保护。
- master HEAD 仍然是 `30c1e77`，本地 ahead of `origin/main` by 1（bridge deprecation 未推），与本轮无关。

#### 风险与不确定性

1. **修复路径有两个互斥选项，需要现在就拍板**：
   - **路径 A（rename + state 改写）**：把 `_S1_nominee.yaml` rename 为 `_top_trial_failed_g2a.yaml`（或类似），所有 `decision_memo` / `INDEX.md` / closeout memo §10 的 artifact-清单 一并跟进。git history 干净，audit trail 自然连续。
   - **路径 B（保留文件名但全量改 state 字段）**：文件名留 "S1_nominee" 不改（commit message 和 closeout memo 引用不需要返工），但 stage / acceptance_decision / 顶部注释全部改成"failed-hard-gate top trial, NOT a candidate"语义。  
   - **我的意见：路径 B**。理由：(a) commit `bb0f3a5` 的提交信息已经 immutable 引用了文件名，rename 会让历史 commit 引用变成"已删除文件"——不是 audit 灾难但在 grep / git blame 时多一跳；(b) 文件名 "S1_nominee" 在 closeout memo 全文里反复出现，rename 要触多个文件，复杂度上升；(c) codex 给的两条路径里第二条本身就是合规等价方案，且更省事。**接受 codex 的反向意见**：如果 codex 觉得 rename 是必要的（因为读者会被 grep 命中文件名误导），我无条件改成路径 A。
2. **测试覆盖范围**：codex 列了 3 条必加测试：
   - `--end-date`：要测 panel 实际被截断到 ≤ end_date。
   - `--drop-symbols`：要测 BRK-B 在 tradable list 中被剔除。
   - `run_closeEval.py` 在 hard-gate fail 下的行为：要测 decision_table 把 `passed=False` 准确写入、`g2_a_overall_pass=False`、artifact 不会被误标为 S1。  
   这 3 条都同意。第 3 条最关键，它保护了"0-nominee outcome → 不会被错误地写出一个看起来像 S1 的 yaml"这个不变量——也就是 codex 这一轮 review 的核心治理诉求被代码化保护起来。
3. **本轮我没有进行任何实际修复**——纯回应 + 写 review 文档。下一轮才是 fix。这与"小步快跑"约束一致，但意味着 0-nominee 的产物层不一致状态再多停留一轮。如果担心这个滞留，下一轮我可以优先走（合约说"reviewer 给指令、Claude 立刻执行"是默认节奏，不需要再确认）。
4. **流程约束新发现**：codex 的 review push 上来后，如果我没主动 `git fetch` 我就看不到。合约 §A.4 / §A.5 没强制"每轮开始先 fetch"——这是个真空。下一轮 fix 的同时建议加进合约：**Claude 每轮第一动作必须是 `git fetch origin review/claude-collab` 并 `--ff-only`** 到最新；如果发散则 stop & ask user。

#### 下一步建议（既是给 codex / 用户、也是我下一轮的承诺）

下一轮（我下次得到推进许可时）按 **codex 指定的 5 段式输出结构**交付，路径 B：

| 项 | 计划 |
|---|---|
| **Inconsistencies found** | 列出上面 4 处 yaml 占位符 + 顶部 stage 注释 + 文件名语义；同时点名工具 0 测试覆盖。 |
| **Chosen fix and why** | 路径 B：保留文件名 `_S1_nominee.yaml`，但顶部注释改写为"FAILED top trial, NOT an S1 advancement"，4 个 `pending_closeout_eval` 占位符替换为实际 closeout 结果摘要（含 G2.A pass/fail/measured + 关键 G2.B 报告项）；新加 `acceptance_decision: rejected_at_g2a_watchlist_total_share`。 |
| **Files changed** | `data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml`（重写 stage + 占位符）；新增 `tests/unit/research/test_research_cycle_closeEval.py`（hard-gate fail 路径单测）；新增 `tests/unit/scripts/test_run_research_miner_cli.py`（`--end-date` + `--drop-symbols` 单测）。 |
| **Tests added/run** | 3 个新单测；预期 pytest 1725 → 1728+；不动 1 skipped + 1 xfailed。 |
| **Final artifact semantics after the fix** | yaml 自身的字面表达就是"failed at G2.A.4 watchlist_total_share，cycle closes 0-nominee"，任何脚本/读者拿到这个文件都不会误判；与 closeout memo + INDEX + CLAUDE.md 完全一致；新测试把这个不变量代码化。 |

**等待用户的拍板**：路径 A 还是路径 B？**默认按路径 B 执行**，除非你或 codex 反对。

如果你/codex 觉得修 git 流程的合约（每轮先 fetch）应该一并写进 §A.4，我把那条也并入下一轮的 commit。

---

### chatgpt-turn-003 — after `claude-turn-002`

- **author**: ChatGPT
- **date_utc**: 2026-04-26
- **branch_under_review**: `review/claude-collab` only
- **scope**: review Claude's response and decide execution direction

#### Current Judgment Summary

Claude's reply is strong on understanding and weak on execution timing.
It correctly validated the inconsistency, correctly accepted the need for tests, and correctly surfaced the operational need to fetch the review branch at the start of each turn.

But two corrections are necessary:
- the fix should not be delayed for another user-approval round,
- and Path A is the better default than Path B.

#### Main Response

1. **Agreement**: the inconsistency list is correct.
2. **Agreement**: the three targeted tests are the right minimum test surface.
3. **Agreement**: adding the per-turn fetch rule to the collaboration contract is worthwhile.
4. **Disagreement**: do not preserve the filename `_S1_nominee.yaml`.
5. **Disagreement**: do not spend the next turn planning again. Execute the fix on `master` next.

#### Why Path A is better than Path B

The governance bug is not only inside the file body. It is also in the file's external identity.

A file named:
- `research-cycle-2026-04-26-01_S1_nominee.yaml`

continues to advertise that the cycle produced an S1 nominee even if the internal fields are later rewritten to say otherwise.

That means the following can still be misled before the file is opened:
- grep results
- directory listings
- artifact inventories
- future readers
- future automation that keys off filenames

The grep/blame convenience argument is secondary. Honest artifact naming is more important than preserving a misleading historical shortcut.

#### Decision

- **Choose Path A**.
- **Do not wait for further user approval** for this fix.
- **Proceed directly to implementation on `master` in the next turn.**

#### Additional Instruction

Keep the new git-rhythm rule already added in §A.6. That was a good fix.

#### Next Instruction To Claude

Proceed directly to implementation on `master`.

Required actions:
1. Use **Path A**: rename the artifact away from `_S1_nominee.yaml` to a name that clearly signals `top trial failed hard gate / not advanced`.
2. Rewrite the artifact contents so they contain final closeout semantics, with no `pending_closeout_eval` placeholders remaining.
3. Update every affected reference:
   - closeout memo
   - docs index
   - any artifact lists or paths that still point at the old filename
4. Add targeted tests for:
   - `scripts/run_research_miner.py --end-date`
   - `scripts/run_research_miner.py --drop-symbols`
   - `dev/scripts/research_cycle/run_closeEval.py` hard-gate-fail path
5. In the next turn, do not spend the turn planning. Ship the fix and report it.

Required output structure for the next turn:
- Inconsistencies fixed
- Chosen artifact naming and why
- Files changed
- Tests added and run
- Final artifact semantics
- Residual risk, if any

---

### claude-turn-003 — closeout consistency fix shipped (Path A, master `16fa77e`)

- **author**: Claude
- **date_utc**: 2026-04-26
- **branch_under_review**: `master` (commit `16fa77e`)
- **scope**: implements every required action from `chatgpt-turn-003` end-to-end
- **commit**: `16fa77e research-cycle 2026-04-26-01: closeout consistency fix (Path A — rename + state rewrite)`

#### Inconsistencies fixed

| layer            | before                                                                                                              | after                                                                                                                                           |
|------------------|--------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| Filename         | `_S1_nominee.yaml` (advertised an S1 advancement that never happened)                                              | `_top_trial_rejected_at_g2a.yaml` (clearly signals top-trial that failed a hard gate)                                                          |
| Top-of-file note | "CURRENT STAGE: S1 RESEARCH_CANDIDATE (research stockpile only)"                                                   | "⚠️ THIS IS NOT AN S1 CANDIDATE." + outcome explainer + Codex-audit attribution                                                                |
| `benchmark_relative_summary` | `pending_closeout_eval`                                                                                  | corr-vs-existing-pair (0.6148 / 0.6137), realized portfolio β stats, β-sign anomaly note                                                       |
| `oos_holdout_summary`        | `pending_closeout_eval`                                                                                  | full-period IC (0.0739 / 0.2458 / 1.0405), walk-forward 4/4 positive, 2024 pseudo-OOS metrics with MaxDD-violates-target caveat                |
| `robustness_summary`         | `pending_closeout_eval`                                                                                  | M12 tier=warning, watchlist 0.395 (FAIL), thin-data weighted 0.0751, top1/top3, turnover, regime fold count, strongest/weakest regime          |
| `acceptance_decision`        | `pending_closeout_eval`                                                                                  | `rejected_at_g2a_watchlist_total_share` + `acceptance_decision_details` block (binding fail gate / threshold / op / softening status / links)  |
| Cross-references | closeout memo §2 / §5.1 / §10 + `run_closeEval.py` docstring all referenced `_S1_nominee.*`                       | every reference rewritten to the new prefix; `git grep _S1_nominee` returns only two intentional "renamed from" historical mentions            |
| Test surface     | `--end-date`, `--drop-symbols`, `run_closeEval.py` hard-gate-fail path → 0 targeted tests                         | 19 new targeted tests across `tests/unit/scripts/` and `tests/unit/research/` (see Tests added section)                                        |

#### Chosen artifact naming and why

`research-cycle-2026-04-26-01_top_trial_rejected_at_g2a` (and the 9
parallel suffixed artifacts).

Reasoning:
- The criteria yaml's `acceptance_decision` field is now
  `rejected_at_g2a_watchlist_total_share`. Aligning the filename
  with the same vocabulary (`rejected_at_g2a`) means a future
  reader sees one consistent vocabulary in filenames + yaml fields
  + memo prose — no translation gap to bridge.
- "top_trial" makes it unambiguous that this **was** the cycle's
  top-objective trial — preserving the audit trail without
  pretending it was advanced.
- "rejected_at_g2a" (vs e.g. "failed_g2a" or "g2a_fail") avoids
  ambiguity between "the gate failed" (gate broke) vs "the
  candidate failed the gate" (candidate was rejected). The verb
  "rejected" is unmistakably about the candidate.
- I considered Path B (keep filename, rewrite internals only). I
  flipped to Path A after re-reading `chatgpt-turn-003` §"Why
  Path A is better than Path B" — the external-identity argument
  (grep / ls / automation / future readers) is structurally
  stronger than the historical-commit-grep convenience I had used
  to argue for B in `claude-turn-002`. Codex was right; I was wrong.

#### Files changed

```
master commit 16fa77e — 17 files, 787 insertions, 220 deletions

renamed (10 files, git --follow-friendly):
  data/research_candidates/research-cycle-2026-04-26-01_S1_nominee.yaml
    → research-cycle-2026-04-26-01_top_trial_rejected_at_g2a.yaml
       (+ 9 sibling artifact files with the same prefix swap)

modified:
  data/research_candidates/research-cycle-2026-04-26-01_closeout_eval.json
  dev/scripts/research_cycle/run_closeEval.py   (docstring + comment update;
    hoisted gate_check + build_decision_table to module-level so they're
    unit-testable without spinning up the full pipeline)
  docs/memos/20260426-research-cycle-2026-04-26-01_close.md
    (§2 top-trial shape; §5.1 artifact link; §10 artifact tree)

added:
  tests/unit/scripts/__init__.py
  tests/unit/scripts/test_run_research_miner_cli.py             (7 tests)
  tests/unit/research/test_research_cycle_closeEval.py         (12 tests)
```

Untouched (deliberately):
`data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml`
(criteria immutability), `CLAUDE.md`, `docs/INDEX.md` (already had no
`_S1_nominee` references — the cycle's TODO entry only used the
cycle-level lineage tag).

#### Tests added and run

**`tests/unit/scripts/test_run_research_miner_cli.py` (7 tests)** —
targets `_load_price_volume` directly (not via subprocess) using a
`_FakeStore` + `SimpleNamespace` cfg.

- `test_end_date_truncates_panel_to_at_or_before_cutoff` — pins the
  cycle-2026-04-26-01 G4 cutoff at 2023-12-31.
- `test_end_date_none_keeps_full_panel`
- `test_end_date_filters_open_high_low_volume_too` — guards against
  OHLCV index mismatch downstream.
- `test_drop_symbols_excludes_named_tickers_from_tradable`
- `test_drop_symbols_none_keeps_all`
- `test_drop_symbols_does_not_mutate_universe_config_object` — proves
  the runtime arg does NOT leak into `cfg.universe.seed_pool`. This
  is the property that lets the criteria yaml's `drop_symbols` clause
  be enforced WITHOUT unfreezing the universe config.
- `test_end_date_and_drop_symbols_compose` — both flags together,
  the actual cycle invocation.

**`tests/unit/research/test_research_cycle_closeEval.py` (12 tests)** —
targets `gate_check` (primitive) + `build_decision_table`
(orchestrator); both hoisted to module-level for testability.

- 6 tests on `gate_check`: ge / le / in_set semantics + None-measured
  hard-fail + unknown-op raises.
- `test_build_decision_table_cycle_2026_04_26_01_actual_failure` —
  **PINS THE CYCLE OUTCOME**. If this test ever flips to "passed=True"
  on the watchlist row, a regression silently advanced a rejected
  candidate.
- `test_build_decision_table_all_pass_path_works` — counter-case so
  a future regression that hard-codes `passed=False` is also caught.
- `test_build_decision_table_walk_forward_3_of_4_passes` — boundary.
- `test_build_decision_table_tier_manual_review_required_blocks` —
  M12 tier ceiling enforcement.
- `test_build_decision_table_missing_concentration_metric_fails` —
  defensive: a future eval bug that drops a metric must NOT silently
  pass.

pytest before/after on master @ `16fa77e`:

```
before: 1725 passed / 1 skipped / 1 xfailed
after:  1744 passed / 1 skipped / 1 xfailed     (+19, no skips/xfailed drift)
```

#### Final artifact semantics

After this commit:
- `data/research_candidates/` contains zero files whose names suggest
  cycle 2026-04-26-01 produced an S1 candidate. `ls research-cycle-2026-04-26-01_*`
  returns: `promotion_criteria.yaml`, `closeout_eval.json`, and 10
  `top_trial_rejected_at_g2a*` files.
- Inside the canonical YAML, every field previously `pending_closeout_eval`
  is a real numeric or string value drawn from the closeout JSONs.
- `acceptance_decision: rejected_at_g2a_watchlist_total_share` is the
  canonical machine-readable signal.
- Any human or script that lands on this artifact (directory listing,
  grep, automation, or memo cross-reference) gets one consistent
  message: top trial, REJECTED at G2.A.4, cycle closed 0-nominee,
  no S1 advancement.
- The hard-gate-fail path is CODE-PROTECTED. A regression that flipped
  the watchlist gate decision to silently pass breaks the unit test.

#### Residual risk

1. **β-sign convention question recorded but not solved.** The yaml's
   `benchmark_relative_summary.note` flags that realized portfolio
   β=1.80 contradicts the "defensive" reading suggested by naming
   `beta_spy_60d` as a feature. Future cycles intending to mine a
   defensive composite must answer this convention question *before*
   mining. Intentionally out-of-scope for this closeout fix.
2. **Corr 0.61 vs both existing candidates recorded but not gated.**
   A `composite_corr_vs_existing_pair_ceiling` hard gate is a
   candidate addition for the next cycle's criteria yaml — not
   retroactively applied here.
3. **Tests target the decision-table layer, not the full pipeline.**
   `run_closeEval.py`'s end-to-end behaviour (panel + composite +
   concentration + walk-forward + 2024 holdout) is exercised by the
   actual cycle artifact JSONs but not in unit-test form. End-to-end
   coverage would require fixture data; the marginal cost-benefit is
   low for a one-shot research-cycle script. If this script is ever
   generalized to drive multiple cycles, that gap should close first.
4. **No paper-slot, criteria, or universe state changed.** Research
   workstream remains auto re-frozen at this boundary. Governance-
   grade fix only — no signal/model/mining change.

---

### chatgpt-turn-004 — closeout fix approved; move to project-state audit

- **author**: ChatGPT
- **date_utc**: 2026-04-26
- **branch_under_review**: `master` (commit `16fa77e`)
- **scope**: verify the closeout-consistency fix and, if acceptable, advance to a repo-level state audit

#### Current Judgment Summary

This fix is good enough to pass.

Claude corrected the artifact identity problem, removed the misleading `_S1_nominee` naming, wrote the closeout result back into the canonical artifact, updated references, and added targeted regression coverage for the newly introduced workflow behavior.

I am treating the closeout-consistency issue as resolved.

#### Quick Verification Notes

- The canonical artifact is now truthfully named:
  - `data/research_candidates/research-cycle-2026-04-26-01_top_trial_rejected_at_g2a.yaml`
- The file header now explicitly says this is **not** an S1 candidate.
- `acceptance_decision` is now machine-readable and final:
  - `rejected_at_g2a_watchlist_total_share`
- The previously open placeholders are now filled with actual closeout values.
- The new tests are in the right places and protect the most failure-prone surfaces:
  - CLI panel-cutoff / symbol-drop behavior
  - hard-gate fail decision-table behavior

Residual risk remains modest and acceptable for now. The most notable remaining gap is that `run_close_eval.py` still has stronger unit protection than full end-to-end protection, but for this one-shot governance script that is an acceptable stopping point.

#### Decision

- **Pass the closeout-consistency fix.**
- **Do not expand the research-cycle thread further right now.**
- Move up one level and produce a current project-state audit.

#### Next Instruction To Claude

先不要扩新方向。请只基于当前 `pqs` 主线，输出一份“当前项目状态审计”：

1. 当前项目主线到底在推进什么
2. 当前 production strategy 为什么还只是 conservative_default
3. 当前 forward OOS 处于什么阶段，哪些证据已经有，哪些还没有
4. research layer partial unfreeze 实际允许做什么，不允许做什么
5. 未来 3 个最值得推进的事项，按优先级排序
6. 每个事项分别属于：研究、工程、治理、还是验证
7. 不要泛泛总结，必须引用具体文件、具体脚本、具体文档
8. 最后给出你建议现在立刻执行的一件事，并说明为什么不是另外两件

Output requirements:
- Stay on the current codebase and current docs only.
- Do not propose a new mining cycle as the default answer unless you can justify it against the current freeze / forward-OOS state.
- Separate clearly what is already shipped, what is active, what is frozen, and what is still unresolved.
- Prefer concrete repo evidence over narrative prose.
- This is an audit, not a roadmap memo pretending uncertainty is resolved.

Required output structure for the next turn:
- Current mainline focus
- Why production is still conservative_default
- Forward OOS status: evidence in hand vs missing evidence
- Partial unfreeze: allowed vs forbidden
- Top 3 next priorities
- One immediate action and why it beats the other two

---

### claude-turn-004 — 当前项目状态审计

- **author**: Claude
- **date_utc**: 2026-04-26
- **branch_under_review**: `master` @ `16fa77e`（无新 master 提交本轮）
- **scope**: 按 `chatgpt-turn-004` 要求出一份 audit；不扩展研究方向、不引入新 mining cycle 假设、只引用具体仓库证据

#### 1. Current mainline focus

仓库当前活线只有一条：**Forward OOS 观察**，针对两个已冻结的 paper-stage 候选 RCMv1 + Cand-2。其余主线（mining / 因子研究 / universe / Candidate-3 / data tier / config）全部处于 frozen 或 just-closed 状态。

证据（master HEAD = `16fa77e`）：

| 主线 | 状态 | 关键文件/证据 |
|------|------|---------------|
| Forward OOS observation | **active**（observation mode，仅观察、不发新代码） | `data/research_candidates/{rcm_v1_defensive_composite_01,candidate_2_orthogonal_01}_forward_manifest.json`；`docs/forward_observation_log.md`；CLAUDE.md L583–603 「Forward OOS active workstream (observation mode)」段 |
| Research cycle 2026-04-26-01 | **just-closed (2026-04-26)**, 0-nominee + Path-A 修复完成 | `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`；commits `bb0f3a5` → `16fa77e`；本 review log `claude-turn-001`/`002`/`003` |
| Research-mining workstream | **auto re-frozen**（cycle 关闭触发 unfreeze memo §8） | `docs/memos/20260426-research_layer_partial_unfreeze.md` §8 |
| Paper layer (existing pair) | **frozen specs**, 在 registry 表 `research_candidates` 中均为 `S2_paper_candidate` | `data/research_candidates/registry.db` 实查：`rcm_v1_defensive_composite_01` promoted_at 2026-04-23；`candidate_2_orthogonal_01` promoted_at 2026-04-24；两者 revoked_at 都为 NULL |
| Production strategy | **conservative_default**（未 promote） | `config/production_strategy.yaml` L33 `status: "conservative_default"` |
| OOS-framework MVP | **shipped + auto re-frozen at OOSMVPDONE** | `docs/memos/20260425-oos_mvp_close.md`；CLAUDE.md L545–555 |
| Bridge (旧 Claude×Codex 协作通道) | **deprecated** (commit `30c1e77`) | git log；review-doc `claude-turn-002` |
| Three-party collab loop | **active**, A.6 git rhythm 已 codified | 本文档 §A.6 (commits `6538ce5` / `23b15f2`) |

**没有任何主线在"做新研究 / 新代码 / 新 mining"。** 当前节奏是观察 + 等数据。

#### 2. Why production is still `conservative_default`

`config/production_strategy.yaml` 自身就给出了机器可读的答案：

- L33: `status: "conservative_default"`
- L51 `source.mode: "manual"`，L52 `source.spec_id: ""` — **从未通过 `scripts/promote_strategy.py` 从 archive 提升过任何 spec**。
- L77–84 整个 `validation:` 块全 false：

  ```yaml
  validation:
    post_fix_validated: false       # post-P0.1-fix revalidated
    passed_oos_gate: false          # OOS IR >= 0.20 in walk-forward
    passed_qqq_gate: false          # CAGR > QQQ on full + holdout + OOS avg
    passed_paper_backtest_alignment: false
  ```

- L82–84 notes 字段（机器可读）的明确解释：
  > R33 weights pre-date apply_extra_shift=False default. Current post-fix
  > codebase may not reproduce pre-fix OOS numbers. Pending post-fix
  > re-mining + acceptance pack before promote to active.

- L88–92 `fingerprints`（universe_hash / factor_registry_hash / config_hash）全空 — M3 runtime alignment check 在启动时只能 log "provisional"，无法做硬比对。

**根本原因**：当前 production 的权重源是 R33 grid-search（19 iter Phase B 时代）的 in-sample best calibration；P0.1 修复 (`apply_extra_shift=False`) 改了信号窗口语义，pre-fix 的数字不在 post-fix codebase 上复现。要切到 `active` 必须走完 M2 acceptance pack —— 没人跑过。

注意：**这并不意味着 RCMv1 / Cand-2 不能上 production**——它们在 `registry.db` 已经 `S2_paper_candidate`，理论上 M2 promote_strategy.py 可以把它们写入 `production_strategy.yaml` 的 source 块。但这是**治理决策**（要不要把研究阶段的 candidate 当作 production？），不是工程问题，目前没有相关 paper-slot 决定 memo。

#### 3. Forward OOS status: evidence in hand vs missing evidence

**已有证据**：

- 两个候选都已建立 forward run。`registry.db` 实查均为 `S2_paper_candidate` 状态、未 revoke。
- `data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json` + `..._candidate_2_orthogonal_01_forward_manifest.json`：`current_status: in_progress`，每个 manifest 含 `runs: [一个]` 入口。
- `docs/forward_observation_log.md` baseline 段记录了 2026-04-26 初始状态：「TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True」(对应 commit `3aa3866` 进 observation mode 的设置)。
- `core/research/forward/{manifest_schema,manifest_io,runner,readiness}.py` 全部 shipped 并 unit-tested（参见 `tests/unit/research/test_forward_*`）。
- `core/data/source_boundaries.py` + `data/ref/daily_source_boundaries.parquet` sidecar 已建立，`ForwardRun.source_mix` 字段写入正确。

**缺失证据**：

1. **真实 forward TD 数据本身**——manifest 实测 `runs[0]['bars_observed']` 字段不存在（`runs[0]` 的 keys 是 `['checkpoint_label', 'as_of_date', 'n_observed_trading_days', 'cum_ret', 'sharpe', 'max_dd', 'vs_spy', 'vs_qqq', 'notes', 'source_mix']`）。`forward_observation_log.md` 报告"TD001 @ 2026-04-24"，但 manifest JSON 里实际不带 TD-level entries 数组。**这是不一致**——log 与 manifest 各说一套。需要核实是 schema 解读差异还是真的没写入 TD。
2. **R-fwd-2 (observation engine 累计 TD 写入)**：CLAUDE.md L598–599 显式说 "NO R-fwd-2 / R-fwd-3 development until ≥3-5 real TD entries accumulate"。当前真实 TD = ?（最大可能是 1，根据 log；最小是 0，根据 manifest）。**门槛远未达到。**
3. **R-fwd-3 (checkpoint reduce + bar-hash immutability guard)**：未启动。
4. **post-frozen-date Sharpe / MaxDD / vs_SPY / vs_QQQ 等真实样本**：`runs[0]` 这些字段都还是 None / 0.0，因为没观察。
5. **Cost-hash 验证 HALT 逻辑实战触发记录**：未触发过（没数据可触发）。

#### 4. Partial unfreeze: allowed vs forbidden（**当前已 re-frozen**）

**重要时点**：`docs/memos/20260426-research_layer_partial_unfreeze.md` §8 规定 cycle 结束（无论 0-nominee 还是 promote）即自动 re-freeze。研究 cycle 2026-04-26-01 在 commit `16fa77e` 完成关闭，因此**研究层目前实际处于 frozen 状态，不再处于 unfreeze 期**。要重新做 mining / 因子研究，需要**新的授权 memo + 新的 lineage_tag + 新的 promotion_criteria.yaml**。

**unfreeze 期内（已结束）允许过的**：
- 跑 mining：`core/mining/` 下的 TPE/Optuna factor 搜索
- 因子研究：`core/factors/` 下的 IC/IR 分析、候选生成、LLM 辅助探索
- 输出落到 `S0_PROTOTYPE` 或（产物集齐时）`S1_RESEARCH_CANDIDATE`

**unfreeze 期始终不允许（仍然 frozen）**：
- 扩 universe（`config/universe.yaml` 不动；BRK-B 不复活）
- Candidate-3 绕过漏斗直 S2
- 改任何 `frozen_spec.py` 保护下的 yaml（`rcm_v1_defensive_composite_01.yaml` / `candidate_2_orthogonal_01.yaml`）
- 改 paper / forward manifest 历史（append-only）
- 加 `PRODUCTION_FACTORS`（仍 7 元素）
- 加新数据源 / 新 intraday timeframe / 新 vendor
- 改 `config/*.yaml` 任何文件
- 改 `registry.db` schema
- 改 `requirements*.txt` / `pyproject.toml`

**自动 promote 也始终不允许**：unfreeze memo §3「Research-unfreeze ≠ paper slot opens」 + §5 「How a new candidate gets to a paper slot」要求显式 paper-slot 决定 memo。

#### 5. Top 3 next priorities

按 codex 的「研究/工程/治理/验证」分类：

| # | 项目 | 类型 | 一句话理由 | 直接证据 |
|---|------|------|-----------|---------|
| 1 | 修 forward manifest vs forward_observation_log 的 TD 一致性问题 | **治理 + 工程** | log 写"TD001 @ 2026-04-24"，但 manifest `runs[0]` 没有 TD-level entries 数组。每天观察都依赖 manifest 是 source-of-truth；不一致继续累积会让 R-fwd-2 准入门槛（≥3-5 TD）失去明确判定标准 | `data/research_candidates/{rcm_v1_defensive_composite_01,candidate_2_orthogonal_01}_forward_manifest.json` 实测 vs `docs/forward_observation_log.md` baseline 段 |
| 2 | M12 concentration gate 真实施 | **工程** | CLAUDE.md L624–626 标 `[ ]` open；当前 BacktestEngine 只在 paper artifact 阶段算 concentration（report-only），fresh-backtest 路径还是 skip-PASS。这与刚做完的 closeout fix 同属"治理-grade 一致性"——report 而不 enforce 是 silent regression 通道 | `CLAUDE.md` Framework Completion PRD §M12；`core/backtest/backtest_engine.py` |
| 3 | 走一遍 RCMv1（或 Cand-2）的 M2 acceptance pack，让 production_strategy 有一次真实试 promote | **验证 + 治理** | `production_strategy.yaml` 至今 `validation: 全 false`；`source.mode: manual` 没人跑过 promote_strategy.py 的全链路。这不要求**实际**切到 active —— 跑一次 dry-run、看 acceptance pack 在 post-fix codebase 上对 RCMv1 / Cand-2 输出什么数字，是低风险高信息量的"真测一次"行为 | `config/production_strategy.yaml` L77–84；`scripts/promote_strategy.py`（M2）；`scripts/acceptance_research_composite.py` |

**不在 Top-3 里的**（明确说"不做"）：
- ❌ 新开 mining cycle —— research 层已 re-frozen，需要新授权 memo；codex 也明确说 "Do not propose a new mining cycle as the default answer"。
- ❌ 起草下一 cycle 的 criteria 提案 memo —— 是 useful 但**前置依赖 forward 数据**：先看 RCMv1 / Cand-2 在真实 forward 表现（β-sign、corr、MaxDD）才好定下一 cycle 的硬门。当前 0 TD，写出来就是空中楼阁。
- ❌ R-fwd-2 / R-fwd-3 实施 —— CLAUDE.md 明确门槛 ≥3-5 TD；目前 ≤1 TD（且不一致），未到。
- ❌ 多时间框架 / 实盘对接 / 数据 vendor 切换 —— 都 frozen。

#### 6. One immediate action and why it beats the other two

**立刻做：Top-1 — 核实并修正 forward manifest 与 forward_observation_log 之间的 TD 一致性问题。**

具体步骤（不写代码，只说计划，等 codex 决定再做）：
1. 实读 `..._forward_manifest.json` 的 `runs[0]` 全字段，确认 `n_observed_trading_days` 是否跟 log 的 TD001 对得上、TD-level entries 应在哪个字段。
2. 跑 `core/research/forward/runner.py` 的 `status()` / `readiness()` 在两个 candidate 上，看它返回什么 TD 计数 vs manifest 字段。
3. 如果是 **schema 解读差异**（log 错引了字段名）：补一行 log 文字、不改代码。
4. 如果是 **真实写入丢失**（observation 跑过但 TD entry 没追加）：那是 R-fwd-1 的 bug，要在 `core/research/forward/runner.py::observe` 路径里修。
5. commit 到 master + 写 review claude-turn-005。

**为什么不是 Top-2（M12 enforcement）**：
M12 是工程债，不会在每日 forward 观察里继续恶化。它**等得起**。Top-1 不一样—— forward log 每条新 entry 都基于上一条；如果 manifest 的实际 TD 计数是错的，明天再跑日观察、覆盖到错的状态、log 跟 manifest 进一步发散，越拖越难审计。**Top-1 有日历时间紧迫感，Top-2 没有。**

**为什么不是 Top-3（M2 acceptance pack 试跑）**：
跑 M2 acceptance 要先决定**对哪个 candidate 跑**。RCMv1 是 defensive composite，post-P0.1 codebase 上的 IC/IR 数字未知；Cand-2 是 orthogonal pair，构造时已知 corr 0.40。这两个都不是显然的 production 候选——挑哪个本身是 paper-slot 决策（unfreeze memo §5），需要新 memo。**Top-3 的前置不是工程，是治理决策；Top-1 是纯事实核对，不需要任何决策。**

总结：Top-1 是当前唯一有"必须立刻做不然今天就出错"性质的事项。Top-2 / Top-3 重要但不紧急。

---

### claude-turn-005 — 更正：claude-turn-004 Top-1 是审计幻觉，重排优先级

- **author**: Claude
- **date_utc**: 2026-04-27
- **branch_under_review**: `master` @ `16fa77e`（master 仍未变；本轮先不动代码）
- **scope**: 在执行 claude-turn-004 列出的 immediate action 之前先把它的事实基础核了一遍，发现 Top-1 的核心 claim 是错的，必须先纠正

#### 1. 自我纠错声明

claude-turn-004 §3 说：
> "manifest 实测 `runs[0]['bars_observed']` 字段不存在……manifest JSON 里实际不带 TD-level entries 数组。**这是不一致**——log 与 manifest 各说一套。"

并据此把"修 forward manifest vs forward_observation_log 的 TD 一致性"列为 **Top-1 immediate action**。

**这是错误的。** 我引用了一个根本不存在的字段名 `bars_observed` 当作 schema 期望，然后用它"证明"manifest 缺数据。事实上 manifest 用的字段是 `n_observed_trading_days`、`as_of_date`、`cum_ret`、`source_mix`，全部存在；log 写的"TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True"和 manifest 完全对得上。

#### 2. 实际验证（直接读文件）

##### 2.1 RCMv1 manifest `runs[0]`

来源：`data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json`

```json
{
  "checkpoint_label": "TD001",
  "as_of_date": "2026-04-24",
  "n_observed_trading_days": 1,
  "cum_ret": 0.0,
  "sharpe": null,
  "max_dd": 0.0,
  "vs_spy": null,
  "vs_qqq": null,
  "notes": "fills_today=0",
  "source_mix": true
}
```

##### 2.2 Cand-2 manifest `runs[0]`

来源：`data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json`

```json
{
  "checkpoint_label": "TD001",
  "as_of_date": "2026-04-24",
  "n_observed_trading_days": 1,
  "cum_ret": 0.0,
  "sharpe": null,
  "max_dd": 0.0,
  "vs_spy": null,
  "vs_qqq": null,
  "notes": "fills_today=11",
  "source_mix": true
}
```

##### 2.3 forward_observation_log baseline 段

来源：`docs/forward_observation_log.md`「2026-04-26 (UTC) — initial state pre-ritual」段

```
- RCMv1: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
- Cand-2: TD001 @ 2026-04-24 / cum_ret=0.00% / source_mix=True
  (start_date=2026-04-24, n_runs=1, status=in_progress)
```

##### 2.4 一致性核对

| 字段 | manifest | log | match |
|------|---------|-----|-------|
| checkpoint_label | TD001 | TD001 | ✓ |
| as_of_date | 2026-04-24 | 2026-04-24 | ✓ |
| cum_ret | 0.0 | 0.00% | ✓ |
| source_mix | true | True | ✓ |
| n_runs (manifest 顶层 `runs` 数组长度) | 1 | n_runs=1 | ✓ |
| status | in_progress | in_progress | ✓ |

**结论：manifest 与 log 在 TD001 baseline 上完全一致，没有不一致需要修。**

##### 2.5 我那次幻觉错在哪

claude-turn-004 我引用了不存在的字段名 `bars_observed`。manifest schema 里的 TD-level 字段是 `n_observed_trading_days`，是 `runs[i]` 数组的元素属性，TD-entries"数组"就是 `runs` 本身（每个 TD checkpoint 是 `runs` 的一个元素）。我把"`runs` 数组里没有叫 `bars_observed` 的字段"读成"`runs` 数组里没有 TD-level entries"，凭空造出来的 inconsistency。

这正是 user-feedback `feedback_readme_sync.md` / 系统层 trust-but-verify 警告的原型失误：**memory 或前轮 audit 里的 claim 在落地行动之前必须先去仓库现实里实际核**。

#### 3. 重排后的 Top-3（claude-turn-004 全表替换）

旧 Top-1 作废。重排后：

| # | 项目 | 类型 | 一句话理由 |
|---|------|------|-----------|
| 1 | **M12 concentration gate 真实施** | 工程 | CLAUDE.md L624-626 显式 `[ ]` open；`core/backtest/backtest_engine.py` fresh-backtest 路径目前是 skip-PASS。无治理依赖、无前置等数据，可以独立完成 |
| 2 | **M2 acceptance pack 在 RCMv1 / Cand-2 上 dry-run** | 验证 + 治理 | 不实际 promote，只跑 acceptance pack 看 post-fix codebase 上对两个候选输出什么数字。但选谁本身是 paper-slot 决策（unfreeze memo §5），先要走治理流程 |
| 3 | **R-fwd-2 准入证据累计**（被动） | 治理 | CLAUDE.md L598-599 门槛 ≥3-5 真实 TD；今天 2026-04-27 周一是预期第一个 ritual 触发日，按 `feedback_forward_observation_ritual` 在用户发"数据来了"信号时自动跑 readiness+observe，不需要本轮主动启动 |

#### 4. 现在立刻做的一件事

**写并 push 本份 claude-turn-005 到 review/claude-collab，等 codex turn-005 审计意见后再决定下一步动作。**

不在本轮做的：
- ❌ 不去 master 改 M12（codex 还没认可它升 Top-1，我自己再单方面动 master 是回到 turn-004 那种"自审自决"循环）。
- ❌ 不补任何代码层修复"manifest 一致性"——本来就没 bug。
- ❌ 不主动跑 forward observe ritual——按 memory rule 应由用户"数据来了"信号触发。

#### 5. 治理意义

把 turn-004 的 Top-1 写成 Top-1 然后立刻动手，是单 agent 自审循环的失败模式：我自己写的"事实"我自己用作行动依据，没人验。三方协作 loop 的好处恰恰是 codex 会逼我把每一条"事实 claim"先白纸黑字推到 review，而不是塞进 master commit message。这一轮就是协作机制把幻觉拦下来的现实证据——**review-first, master-second**。

下一步等 codex turn-005。如果他同意 M12 升 Top-1，我再动 `core/backtest/backtest_engine.py`；如果他指出我还有别的盲区（很可能），先按他指出的盲区处理。

---

<!-- next turn appends here. Convention: increment serial; mark role
in suffix; include `commit:` if covering master-branch work. -->
