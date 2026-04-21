# PRD: LLM-Assisted Factor Mining + XGBoost Cross-Signal Phase

Status: **DRAFT — awaiting current 12-round ralph-loop completion**
Author: user-specified 2026-04-20 pre-sleep
Trigger: if the current 12-round ralph-loop (based on
`docs/prd_intraday_mining_loop.md`) fails to produce a promoted
strategy (PRD §5 exit criterion 1), auto-launch this phase for
30 additional rounds.

---

## 1. 背景（按用户原文存档）

本 PRD 是在 Round 8 之后由用户指定的新阶段规划。核心驱动：

> 12 轮之后如果还不行 那就再自动启动 30 轮 mining 优化，增加一下 LLM 的
> feature mining，搭配 XGBoost，跨信号 mining。当前的信号因子全部都是
> predefined。

所以新阶段目标是：**从"人工枚举因子"跨入"LLM 辅助候选空间探索"**，
同时保留严格 funnel，避免"大模型幻想新因子"直接影响生产。

---

## 2. LLM 角色定位（硬约束，不得违反）

### 2.1 大模型可以做

- 候选因子生成器
- 假设扩展器
- 因子组合器
- 因子解释器
- 因子失效模式分析器
- 反向审查器

### 2.2 大模型不可以做

- 因子有效性的最终裁判
- 因子是否可上线的最终决定者

所有"是否保留"的判定都走现有 research funnel（IC / OOS / regime /
cost / QQQ hard gate / test suite），而不是 LLM 的评分。

---

## 3. 允许探索的因子方向

大模型应主动探索以下类型（非穷尽）：

- 非经典因子变体
- benchmark-relative 因子（vs SPY / vs sector ETF）
- regime-conditioned 因子（值 × regime 指示）
- 路径形态因子（shape of recent returns）
- 多周期组合因子（5d / 21d / 63d 组合）
- 因子交互项（factor_A × factor_B）
- 事件/政策辅助因子（earnings / Fed / index rebalance）
- universe-aware 因子（跨标的统计）
- 适合 interday 与 intraday 的差异化因子

---

## 4. 候选输出的结构化要求

每个 LLM 提出的候选因子必须尽量以如下 YAML 结构提交：

```yaml
factor_name: ""                      # 与现有注册表不冲突
hypothesis: ""                       # 为什么它应该预测未来回报
formula: ""                          # pseudocode 或 pandas expression
required_fields: []                  # 依赖的数据列 (close, open, 60m bars...)
suitable_horizon: []                 # 5d / 21d / 63d / intraday
suitable_universe: ""                # 例 "SPY + Mag7" / "全 universe" / "sector ETF 内"
suitable_regime: []                  # BULL / RISK_ON / NEUTRAL / CAUTIOUS / RISK_OFF / CRISIS
expected_edge: ""                    # annualized alpha 估计 / IC 估计
expected_risk: ""                    # 特征或常见 failure mode
possible_failure_modes: []           # list (e.g. high turnover, cost-sensitive, survivorship)
novelty_vs_existing_factors: ""      # 与 PRODUCTION_FACTORS / RESEARCH_FACTORS 的差异
```

---

## 5. 研究漏斗（强制执行，不可绕过）

任何 LLM 提出的候选因子必须走完下面所有步骤：

```
candidate
   ↓
research (dedup + leakage check + data availability check)
   ↓
validation (IC 筛 + OOS walk-forward + regime robustness)
   ↓
keep / reject / archive + 记录理由
```

不得因"大模型认为有道理"跳过任何步骤。

### 5.1 Dedup 检查

新候选 vs 现有 `RESEARCH_FACTORS` + `PRODUCTION_FACTORS`：
- rank correlation > 0.7 与任何现有因子 → 触发强制审查（不自动 reject）
- 候选需要证明增量价值（better regime robustness / 更低 turnover / 更稳 OOS）

### 5.2 Leakage 检查

- 每个候选的计算链必须至少包含 `shift(1)` 或等价 lag
- 候选不得使用 bar close time 之后的数据
- 候选必须通过现有 `tests/integration/test_multi_tf_time_consistency.py` 式 truncation test

### 5.3 严格验证

IC screen → OOS walk-forward → regime robustness → cost stress →
QQQ hard gate（通过 evaluator 路径）→ tier 评级。

### 5.4 反向审查（必做）

在 LLM 或规则系统对候选做反向审查，明确回答：

- [ ] 不是旧因子的改名
- [ ] 与任何 Keep 因子 rank correlation ≤ 0.7（或有明确增量价值）
- [ ] IC 在至少 3 out of 6 regimes 为正
- [ ] 不是单一时期效应（>60% IC 不能来自同一 quartile）
- [ ] 通过 2x cost stress 仍为正 alpha
- [ ] 不是 <5 标的过拟合
- [ ] 不是 timing bias / selection bias / survivorship bias / leakage 伪装

任一未通过 → reject（但仍记录到 archive 便于后续分析）。

---

## 6. XGBoost 跨信号挖掘

### 6.1 角色

作为特征重要性 / 组合工具，不替代已有线性 composite。参照现有
`scripts/run_xgb_importance.py` 扩展：

- 把 LLM-生成的候选因子喂给 XGBoost
- 做 permutation importance on OOS
- 仅输出"候选 ranking" + "cross-feature interactions"
- **不修改 MultiFactorStrategy 的线性 composite**

### 6.2 数据规则

- Train/test split 严格按时间（train=[0, T), test=[T, T+V)），**禁止**
  随机 shuffle
- Split 日期和随机种子必须保存到 `data/ml/xgb_config.json`
- 所有 hyperparams 保存到同一文件
- Permutation importance 在 test set 上计算（**不在 train set**）

### 6.3 输出

- `data/ml/xgb_importance.parquet` — LLM + classical factor 的 importance
- `data/ml/xgb_interactions.parquet` — top-K factor × factor interactions
- 每次 run 自动生成 `data/ml/xgb_run_summary.md` 摘要

---

## 7. Cross-Signal Mining

### 7.1 含义

对 LLM 生成的候选因子组合，做"多信号联合筛选"：

- 单因子 IC 不够强但**组合后**有显著 alpha 的情况
- 使用 XGBoost 捕获 nonlinear interactions
- 使用 orthogonalization 排除与已有 composite 的共线性

### 7.2 执行模式

每轮 cross-signal mining 应：

1. 从 LLM 生成 N 个候选因子（结构化输出）
2. 并入现有 factor_generator 产出（RESEARCH-only，不 promote）
3. 跑 IC screen + XGBoost importance + orthogonalization
4. 输出 top-K 候选组合
5. 对 top-K 每个组合做完整 mining funnel（evaluator.evaluate 流程）
6. QQQ hard gate 通过后才允许 promote 到 `PRODUCTION_FACTORS`

---

## 8. 启动条件

本 PRD **仅在以下任一条件满足时启动**：

1. 当前 12 轮 `docs/prd_intraday_mining_loop.md` 结束
2. 当前 12 轮结束后用户明确批准进入此阶段

### 8.1 Auto-launch（如果当前 12 轮未 promote）

用户原文："12 轮之后如果还不行 那就再自动启动 30 轮 mining 优化"。

所以：
- 如果 12 轮完成后 `passed_qqq_gate=1 AND tier in (A,B,C,S)` 的 archive 行数为 0
- **自动**启动本 PRD 的 30-round 循环
- 每轮按 §5 的 funnel 生成 LLM 候选 → 严格验证 → keep/reject

### 8.2 Lineage tag 策略

- 进入此阶段时立即 bump 到 `post-2026-04-20-llm-round-1`
- 每轮 `...-llm-round-N`（N = 1-30）
- **不允许**与 `post-2026-04-20-capital-100k` 的 archive 行混合比较

---

## 9. 30 轮 ralph-loop 主题菜单（此阶段）

按优先级粗略排序（具体由每轮 pre-audit 决定）：

| # | 主题 | Completion signal |
|---|---|---|
| LLM-1 | LLM 候选生成管线 scaffold | `scripts/llm_factor_propose.py` 产出 ≥5 个结构化候选 YAML |
| LLM-2 | Dedup + leakage 自动检查工具 | 每个候选自动跑 rank-corr + truncation test |
| LLM-3 | 第一批 intraday LLM 候选（3 个）| 通过 IC screen + OOS + regime，≥1 candidate enters keep |
| LLM-4 | 第一批 benchmark-relative LLM 候选 | 同上 |
| LLM-5 | XGBoost cross-signal import mining | `xgb_importance.parquet` 显示 LLM 候选在 top-20 |
| LLM-6 | Orthogonalization + collinearity gate | 自动 reject rank-corr > 0.7 的候选 |
| LLM-7 | Regime-conditioned factors | IC 在 ≥3 regime 为正 |
| LLM-8 | Factor interaction mining (pair × pair) | top-K 组合进入 archive |
| LLM-9 | Event / regime-based factors | earnings / Fed / rebalance 日期标记 |
| LLM-10 | Path-shape factors | 滚动形态识别 (W-bottom, breakout, etc.) |
| LLM-11 | Universe-aware / cross-sectional factors | cross-ticker 统计 |
| LLM-12 | 第一个 LLM 候选 promote funnel | ≥1 candidate passes evaluator → tier ≠ D |
| LLM-13..LLM-20 | 续研究 + 反向审查 + funnel 迭代 | — |
| LLM-21..LLM-25 | XGBoost vs ridge 模型对比（research only） | model comparison output |
| LLM-26..LLM-30 | mining scale-up 到全 universe + 全 regime | end-to-end verification |

---

## 10. 成功定义

本阶段成功当且仅当：

1. 至少 1 个 LLM-生成的候选因子通过完整 funnel 并被 promote
2. promote 的因子在 QQQ hard gate 下为 pass
3. archive 可追溯（`lineage_tag=post-2026-04-20-llm-round-N` + 每个候选的 LLM propose yaml 入档）

或：

4. 30 轮结束后明确证明"当前 universe + factor 空间不足以支撑新增 alpha"，产出一份 blocker 报告

---

## 11. 工作原则（用户原文）

> 目标不是让大模型"幻想新因子"，
> 而是让大模型帮助系统更快、更广、更有逻辑地探索候选空间，
> 同时通过严格验证把真正有增量价值的因子留下来。

---

## 12. Appendix — 待实现的基础设施

本 PRD 真正启动前，确认以下底座已就位（大部分在前 8 轮已完成）：

- [x] factor_registry + `PRODUCTION_FACTORS` + `RESEARCH_FACTORS`（Round 2 / 4 / 6）
- [x] lineage_tag 隔离（Round 2）
- [x] QQQ hard gate 在 evaluator + acceptance 一致（Closeout 4/4）
- [x] factor gate strict mode（Round 4）
- [x] shared helpers `core/factors/base_factors.py`（Round 6）
- [x] intraday factor family（Round 5）
- [x] cross-TF feature validation tool（Round 8）
- [ ] **LLM propose script**（LLM-1）
- [ ] **LLM candidate auto-validate**（LLM-2）
- [ ] **orthogonalization gate**（LLM-6）
- [ ] **XGBoost interaction mining**（LLM-5）

---

## 13. 风险与注意

### 13.1 主要风险

- **LLM 候选爆发式增长**：数百候选 × 30 轮 × OOS 计算 = mining 时间爆炸。
  必须每轮加上预算硬约束（`--trials` 上限 + budget）
- **Silent leakage in LLM proposals**：LLM 不知道 data availability 规则，
  可能提出用未来数据的 factor。必须由 dedup/leakage tool 把关
- **注意力分散**：30 轮后缺口仍可能在数据源 / 执行 realism / 外部事件，
  LLM 不能替代这些问题

### 13.2 自动化边界

自动化循环 **必须** 在以下情况停下问用户：

- 任一轮 pytest 降至 1067 passing 以下
- 任一候选 promote 到 `PRODUCTION_FACTORS`（涉及 hard change，必须签核）
- LLM 候选超过 200 个仍无 keep（搜索方向不对，需人介入）
- 任一 archive 行 `passed_qqq_gate=False` 但 `tier != 'D'`（系统 invariant 违反）

---

## 14. Change log

| 日期 | 变更 |
|---|---|
| 2026-04-20 | 初稿，由用户 Round 8 后指定 |
