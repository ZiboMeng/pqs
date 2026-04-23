# External LLM Handoff — Gemini / Codex / 任意 LLM 参与 Factor 提案

**PRD**: `docs/20260421-prd_framework_completion.md` §11 M15（reframed）
**日期**: 2026-04-21
**状态**: 半自动 —— 用户手动桥接，Claude funnel 自动拾取

---

## 为什么有这个文档

Phase 1 (M6) 定义了 **Claude-in-loop** 写 YAML 的规范。但用户还有 **Gemini / Codex** 等其他 LLM。希望：

1. 这些 LLM 也能被复用来生成 factor candidates
2. **不需要** 用 API key / 付费 Anthropic API 调用（M15 Phase 2 避开）
3. 手动桥接（用户把 context 贴给 LLM，拿到 YAML，放回 repo）
4. Claude 侧只需要**读 repo 里新增的 YAML** 并跑 funnel —— 对 Claude 透明

本文档定义：
- 喂给任何外部 LLM 的**标准化 context pack**（可复制粘贴）
- **放回 repo 的规则**（路径 / 命名 / 目录约定）
- Claude 侧怎么 **识别** 外部 candidates 并跑 funnel

---

## 整体流程

```
┌────────────────────────────────────────────────────────┐
│  Claude 侧（自动）：                                  │
│  1. 每轮 research 开始前，dump seed context            │
│     到 docs/llm_handoff_seed_<ts>.md                   │
│  2. 用户拷贝该文件内容，送入 Gemini / Codex            │
│  3. 外部 LLM 回复 YAML candidate(s)                   │
│  4. 用户手动粘贴 YAML 到:                              │
│     research/llm_candidates/round_<NN>/<name>.yaml     │
│     且在 compute_fns.py 里加 compute_fn 实现           │
│  5. 用户 commit 进 repo                                │
│  6. Claude 下次循环自动发现新 YAML（ls 扫描），       │
│     跑 funnel (`llm_factor_propose.py`)                │
│  7. 剩余 funnel steps 和 Phase 1 一致                  │
└────────────────────────────────────────────────────────┘
```

---

## 标准化 Context Pack（喂给外部 LLM 的模板）

用户把下面这整段**一字不差**粘给 Gemini / Codex，再加一句"请生成 N 个 factor candidates YAML"即可：

```
ROLE: You are a quantitative factor research candidate generator for the
PQS (Personal Quantitative System) framework. You are NOT the final
judge of factor validity. Your output will be fed into a rigorous
validation funnel (IC screening / OOS walk-forward / regime
robustness / cost stress / QQQ gate) — all gates must pass before any
human decides whether to promote to RESEARCH_FACTORS or
PRODUCTION_FACTORS.

HARD RULES (non-negotiable):
1. NEVER output verdict=KEEP. Your YAML does not have a verdict field;
   only the human decides after funnel artifacts are reviewed.
2. Every candidate must fill ALL fields in the YAML schema below.
3. No look-ahead: factor must not use data that would not be available
   at the signal_timestamp. If using rolling window, ensure the window
   excludes the current bar.
4. Long-only only. No factors that imply "short X when Y".
5. No external data beyond what the panel already contains: close,
   open, high, low, volume, regime label, benchmark series (SPY, QQQ).

REPO STATE (provided below so you don't reinvent existing factors):

--- PRODUCTION_FACTORS (currently executed in production strategy) ---
{{INSERT: list from core.factors.factor_registry.PRODUCTION_FACTORS}}

--- RESEARCH_FACTORS (available for research but not promoted) ---
{{INSERT: list from core.factors.factor_registry.RESEARCH_FACTORS}}

--- Recent REJECTED / ARCHIVED candidates (do NOT re-propose these) ---
{{INSERT: last 10 from research/llm_candidates/round_*/ with reasons}}

--- Current universe (53 tradable symbols; cross-sectional factor validity depends on panel width) ---
{{INSERT: seed_pool + sector_etfs + factor_etfs + cross_asset from config/universe.yaml}}

--- Recent regime distribution (last 252 trading days) ---
{{INSERT: regime.value_counts() from past year}}

EXPLORATION DIRECTIONS (pick ONE per candidate; explain your pick
in `hypothesis` field):

- benchmark-relative (vs SPY, QQQ, sector ETF, equal-weight)
- regime-conditioned (factor × regime indicator, multiplied not replaced)
- path-shape (drawup, distance-from-extrema, consolidation time)
- multi-horizon composite (5d + 21d + 63d signals)
- factor interaction (product, difference, ratio of two base factors)
- event-based (day-of-week, turn-of-month, earnings vicinity if data
  shows flag)
- cross-sectional (rank change, dispersion-adjusted, universe-aware)
- intraday-specific (overnight gap, first-bar vs last-bar, intraday
  vol ratio; only if 60m+ data available)

YAML OUTPUT SCHEMA (copy this exact structure):

```yaml
factor_name: "descriptive_lowercase_snake_case"
hypothesis: "One-line economic or behavioral rationale."
formula: |
  pseudocode or pandas expression; be specific about:
    - lag / shift(1) placement
    - rolling window sizes
    - normalization (z-score, percent rank, etc.)
compute_fn_path: "research.llm_candidates.round_NN.compute_fns:factor_name"
required_fields: ["close", "volume", ...]
suitable_horizon: [5, 21]
suitable_universe: "top_15_liquid" | "expanded_53" | "tech_heavy" | "diversifier_only"
suitable_regime: [BULL, NEUTRAL]  # or "all"
expected_edge: "Expected IC sign + rough magnitude, e.g. 'positive, IC 0.02-0.05'"
expected_risk: "What goes wrong if crowded / what it correlates with"
possible_failure_modes:
  - "Specific failure mode 1 (e.g. high-vol regime breakdown)"
  - "Specific failure mode 2"
novelty_vs_existing_factors: "Compare vs the PRODUCTION_FACTORS listed above; disclose correlation estimate if possible"
```

Also provide the compute_fn implementation in python, to be pasted
into research/llm_candidates/round_NN/compute_fns.py:

```python
def factor_name(price_df, vol_df=None, regime=None, **kwargs):
    # returns a DataFrame (date × symbol) with factor values
    ...
```

Deliver N candidates per request. Number them clearly. Do NOT include
verdict, score, or any pass/fail guess — just the candidate. The PQS
funnel handles validation.
```

---

## Claude 侧自动 dump 流程

Claude 每轮 research 开始前，应自动执行以下步骤来生成一个最新的 seed 包：

```bash
# 1. Dump current repo state to a timestamped markdown file
python scripts/dump_llm_handoff_context.py \
    --out docs/llm_handoff_seed_$(date +%Y%m%dT%H%M%S).md
```

（此脚本还没写；是 **推荐 future enhancement**，不是阻塞项。现阶段
Claude 可以用 `docs/20260421-llm_proposal_seed_context.md` 里的 5 条 shell 命令
手动 dump）

---

## 用户放回 repo 的规则

外部 LLM 产出的 YAML candidate，用户手动按如下规则 commit：

### 1. 目录结构

```
research/llm_candidates/
├── round_15/                  (previous round example)
├── round_16/                  (create new)
│   ├── compute_fns.py        (multiple fn definitions; one file per round)
│   └── <factor_name>.yaml    (one file per candidate)
│   └── <factor_name_2>.yaml
```

Round number: 递增自上次 round（看 `ls -d research/llm_candidates/round_*`）

### 2. 文件命名

- YAML: `<factor_name>.yaml`（必须和 YAML 里的 `factor_name` 字段完全一致）
- compute_fn: 在 round 目录的 `compute_fns.py` 里，函数名 == `factor_name`

### 3. compute_fn_path 写法

```yaml
compute_fn_path: "research.llm_candidates.round_16.compute_fns:my_factor"
```

路径就是 dotted Python import path + `:` + 函数名。

### 4. 标注外部 LLM 来源（可选但推荐）

在 YAML 顶部加一条 meta comment:

```yaml
# Source: Gemini 2.5 (external LLM handoff per PRD M15)
# Round: 16
# Submitted: 2026-04-22
factor_name: "..."
```

Claude funnel 不看这个 comment，但有助于未来分析"哪个 LLM 擅长生成什么类型的 factor"。

---

## Claude 侧自动识别

每次 Claude 开始新一轮 work 时，执行：

```bash
# 扫新增 candidate
ls research/llm_candidates/round_*/*.yaml 2>/dev/null | \
    while read f; do
        name=$(basename $f .yaml)
        verdict_file="data/ml/llm_candidates/$name/verdict.json"
        if [[ ! -f "$verdict_file" ]]; then
            echo "NEW candidate (no funnel verdict): $f"
        fi
    done
```

对每个 NEW candidate:
1. 跑 `python scripts/llm_factor_propose.py --input <yaml>`
2. 若 verdict=NEEDS_HUMAN_REVIEW，跑 deep_check
3. 跑 composite / orthogonalization / factor_backtest
4. 向用户汇报 findings

---

## Fallback: 如果外部 LLM 没动，Claude 继续生成

- 如果用户 **没有** 提供新 YAML（`ls research/llm_candidates/round_*/` 没新文件），Claude 按 M6 Phase 1 流程继续自己生成 candidates 到一个新 round
- 如果用户提供了，Claude 优先处理外部的 + 继续生成补充 candidates

**规则**: 每轮每个 LLM 来源 **无限制数量**。funnel 统一验证；只通过的才进 NEEDS_HUMAN_REVIEW；最终 promote 由用户审核。

---

## 为什么这是 **半自动** 而非全自动

- Claude 不接 Anthropic API（成本 + 可重复性）
- 外部 LLM 的响应依赖用户手动复制（不 brittle 但慢）
- **但** funnel 侧是完全自动的，用户只做"桥接者"

future:
- 如果用户 willing 把 Gemini / Codex response 自动化成 file watcher（e.g. 用户把 LLM 回复保存到某个 inbox 目录，Claude 监测到就 move 进 research/ 并跑 funnel）
- 此 workflow 相对 current 是 30 秒 vs 30 秒，value 有限，不推荐做

---

## 验收

此 M15 reframe 视为 DONE 当：
- [x] 本文档就位（`docs/20260421-llm_external_llm_handoff.md`）
- [x] 外部 LLM 可以消费 context pack 并输出符合 schema 的 YAML
- [x] 用户手动落盘的 YAML 会被 Claude funnel 识别 + 处理（已验证：`llm_factor_propose.py --input <yaml>` 已存在且 works）

```
"如果用户 manually 把 Gemini/Codex 的 YAML 放进 research/ 并 commit，
Claude 下次运行会自动发现并 funnel；如果没放，Claude 继续用自己的
对话式 YAML。两种情形都不阻塞。"
```

---

## 与 Phase 1 (M6) 的关系

| 维度 | M6 Phase 1 | M15 Multi-LLM Handoff |
|---|---|---|
| 谁生成 YAML | Claude (对话) | Gemini / Codex / 任意 LLM |
| 接入方式 | 直接对话 | 手动桥接（copy-paste） |
| Seed context | `docs/20260421-llm_proposal_seed_context.md` 里 5 shell 命令 | 本文档的 "标准化 Context Pack" |
| Funnel 侧 | 完全共享（`llm_factor_propose.py` 等） | 完全共享 |
| 输出路径 | `research/llm_candidates/round_NN/` | 相同 |
| 自动化程度 | 完全自动 | 半自动（copy-paste bridge） |

---

*Document v1.0 — 2026-04-21, author: Claude; reframes M15 from
"programmatic Anthropic API" to "multi-LLM manual bridge".*
