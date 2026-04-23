# PRD：Research Composite Miner v1 + Orthogonal Feature Expansion

**Date**: 2026-04-24 (starts)
**Status**: ACCEPTED — supersedes feat-v1 PRD after its ralph-loop exited
**Connects to**:
  - `docs/20260423-prd_research_feature_engineering_and_expanded_mining.md` (feat-v1 predecessor)
  - `docs/20260423-feat_v1_expanded_final_report.md` (feat-v1 closure)
  - `docs/20260423-feat_v1_r39_blocker.md` (blocker that motivates this PRD)
  - `docs/20260423-feature_data_tier_classification.md` (Appendix A — data tier reference)
**Lineage tag (all rounds)**: `post-2026-04-24-rcm-v1`
**Execution mode**: ralph-loop (see §13)
**Completion promise**: `RCMV1DONE`

---

## 1. Executive Summary

本 PRD 的目标不是继续在当前 production-linked MultiFactorSpace 上做补丁式扩容，也不是立即推进 production promote。

本 PRD 的目标是建立下一阶段研究主线：

1. **把 research search space 从 production sampler 中解耦**，建立一个 **research-only composite miner**。
2. **补一批真正能增加 signal diversity 的 feature**，但只收 **当前代码与数据层可落地的子集**，不新开重数据工程。
3. **把 feat-v1 的 plumbing 从"可观测"推进到"真正被下游消费"**，避免再次出现"feature 已实现，但不进入研究 panel / miner / gate"的失败模式。
4. **统一 sample definition**：research mask 必须从 observability 升级为 panel、miner、acceptance 共用的硬约束。
5. **给 ralph-loop 一个可执行的硬边界**：包括迭代上限、halt 条件、artifact 路径、autonomy 边界与完成承诺。

本 PRD 明确不以"本轮直接找到 production strategy"为目标，而以"建立可持续发现 robust alpha 候选的研究能力"为目标。

---

## 2. 背景与问题定义

上一轮 feat-v1 的工作已经证明三件事：

1. **Research plumbing 已经显著改善**：feature / label / mask / panel 合同都比之前完整。
2. **Expanded universe 本身不是当前主瓶颈**：79-symbol 已足够支撑下一阶段研究；继续加 Stage 3 不是当前第一优先级。
3. **真正瓶颈是 research feature 没有进入真实搜索空间**：production-linked sampler 仍被旧的 PRODUCTION_FACTORS 和窄搜索空间锁死。

因此，当前问题不是"要不要再多跑一点 trial"，而是：

> 如何建立一个能真正消费 research feature、并在更正交的 signal family 上做组合搜索的研究搜索器？

同时，当前 feature pool 的问题也不只是"数量少"，而是：

> **feature diversity 不足**。现有新增多数仍属于 daily price-derived transforms，同源性较高，难以形成真正多元的 alpha engine。

---

## 3. 本轮决策

### D1. 是否继续在现有 MultiFactorSpace 上补 research 因子

**决策：否。**

现有 MultiFactorSpace 仍然是 production-oriented：

* 因子集合过窄
* `pv_div` 吃 residual
* 权重粒度粗
* 预算结构不适合 research-scale exploration

继续在该空间上补因子，只会延续"新 feature 能算，但进不了真实搜索前沿"的问题。

### D2. 是否建立 Research Composite Miner v1

**决策：是。** 这是本 PRD 的主交付。

### D3. 是否继续优先扩 universe 到 Stage 3

**决策：暂缓。**

理由：

* 当前 79-symbol universe 已足够支撑下一阶段研究
* 当前主瓶颈是 search space 与 feature diversity，不是 universe size
* Stage 3 过早引入会放大 beta / 风格噪声，恶化归因

### D4. 是否把更多预算优先投到 Optuna trial 数

**决策：仅作 hedge，不作主线。** 因为多跑 trial 只能在旧空间里多采样，无法解决根因。

### D5. 是否在本轮引入新数据层（earnings / options / short interest / alt data）

**决策：否。** 本轮只做 **当前代码与数据层可落地的 feature 子集**，不新开重数据工程。

### D6. 本轮 backend 是否默认沿用 Optuna 基础设施

**决策：是。** v1 默认使用 **Optuna TPE + weighted-sum objective**，最大化复用现有搜索基础设施；pareto multi-objective 留作 v2 选项。

---

## 4. 本轮范围（In Scope）

本轮包含 4 条主线：

1. **12 个 feature 的 orthogonal 子集落地**
2. **3 项 plumbing 前置**
3. **research_mask 硬化**
4. **Research Composite Miner v1 本体**

同时，本轮 PRD 还包含 **loop execution spec**（§13），确保 ralph-loop 可以按边界自动推进，而不是再次依赖隐式约定。

---

## 5. Feature Scope：本轮只收"可落地子集"

### 5.1 Feature 选择原则

1. **只收当前 adjusted OHLCV + benchmark OHLCV 可落地的特征**
2. **优先增加经济维度，而不是继续堆同类 return/MA 变体**
3. **优先为 future composite miner 服务**
4. **不新开行业 point-in-time 分类、shares outstanding、earnings、options 等新数据层**

### 5.2 本轮 feature 清单（12 个）

#### A. Benchmark-relative / Residual / Risk Exposure

1. `rel_spy_20d`
2. `rel_qqq_20d`
3. `beta_spy_60d`
4. `residual_mom_spy_20d`

#### B. Position / Breakout / Path Shape

5. `range_pos_252d`
6. `days_since_52w_high`
7. `breakout_20d_strength`
   * 连续版本：相对过去 20d 高点的突破幅度
   * 不采用 boolean breakout 作为 standalone IC signal
8. `dist_from_new_high_252`
   * 连续版本：相对 252d 新高状态的距离/幅度表达
   * 明确与 `days_since_52w_high` 区分：前者是价格距离型，后者是时间距离型

#### C. Liquidity / Cost Proxy / Risk State

9. `amihud_20d`
10. `downside_vol_20d`
11. `vol_ratio_5_20`

#### D. Trend Quality

12. `trend_tstat_20d`

### 5.3 已讨论但本轮不纳入的项

* `sector_rel_20d`
* `sector_neutral_mom_20d`
* `industry_neutral_mom_20d`
* `sector_etf_rel_20d`
  * 说明：该项可视为 T2.5 transitional step，但仍需要 static `symbol -> sector ETF` 映射，本轮不做；下一轮在真正 PIT sector 数据前可作为过渡方案单独立项
* `turnover_20d`
* `days_to_earnings`
* `eps_surprise` / `rev_surprise`
* `options` / `short_interest` / `ownership` / `altdata`

原因：这些要么需要 point-in-time 分类，要么需要 shares outstanding / earnings / options / 另类数据等新增数据层，不适合和本轮 composite miner 一起推进。参见 Appendix A 的 T3/T4/T5/T6 分层。

---

## 6. 3 项 Plumbing 前置（必须与 feature 同轮完成）

这 3 项不是"顺手优化"，而是本轮 feature 想真正进入研究体系的必要条件。

### P1. Multi-benchmark factor generator

当前 `generate_all_factors(..., benchmark_col="SPY")` 不足以支撑：

* `rel_qqq_20d`
* `beta_spy_60d`
* `residual_mom_spy_20d`
* 未来 sector ETF / multi-benchmark residualization

**本轮要求：**

* 引入 `benchmark_map`（或等价结构）
* 至少支持 `SPY` 与 `QQQ`
* 为未来 sector ETF benchmark 扩展保留接口

### P2. Residualization helper

`residual_mom_spy_20d` 需要统一的 rolling residualization 路径。

**本轮要求：**

* 在 `core/factors/base_relative.py` 中提供 residualization helper
* 支持 rolling lookback
* 支持 future benchmark generalization
* 成为 residual momentum / idio-risk / future sector-neutral residual 的统一底层

### P3. 下游 8 个脚本升级到完整 panel contract

上一轮 audit 已确认 8 个脚本仍在使用不完整输入，只传 `price_df, vol_df`，导致新 OHLCV features 实际进不了 panel。

**本轮必须同步升级这些脚本：**

* `scripts/run_xgb_importance.py`
* `scripts/run_xgb_weight_model.py`
* `scripts/run_xgb_cv.py`
* `scripts/run_transformer_research.py`
* `scripts/run_model_comparison.py`
* `scripts/run_factor_interaction_mine.py`
* `scripts/llm_composite_backtest.py`
* `scripts/llm_candidate_orthogonalization.py`

**验收口径：**

* 上述 8 个脚本中，至少 **6 个** 能在**不改 CLI** 的前提下跑通新 feature + `benchmark_map` 接口
* 允许最多 2 个脚本延后到 v2 round，但必须记录 blocker 与迁移计划

如果这一步不做，本轮 feature 仍只会存在于 factor registry 中，而不会进入真实模型输入。

---

## 7. Research Mask 硬化（从 observability 升级到 sample definition）

上一轮 feat-v1 中，mask 已存在，但主要停留在 observability 层。本轮要求必须闭环：

### 7.1 Panel 层

* `fillna(0)` 不得继续作为关键路径默认行为
* 改为 `apply_research_mask()` 或等价机制
* 明确区分：
  * 真正中性值
  * warmup 缺失
  * 不可交易样本
  * 数据缺失样本

### 7.2 Miner 层

Research Composite Miner 的：

* cross-sectional IC
* benchmark-relative metric
* cost proxy
* OOS / holdout summary

都必须只在 `research_mask == True` 样本上计算。

### 7.3 Acceptance / diagnostics 层

未来 acceptance / report / diagnostics 也必须沿用相同 mask 逻辑，保证 sample 定义一致。

**结论：** 本轮的关键不是"再加一个 mask helper"，而是把 mask 真正升格为样本定义层。

---

## 8. Research Composite Miner v1：产品定义

### 8.1 定位

Research Composite Miner v1 是一个：

* 仅用于 research
* 不等于 production strategy
* 不直接触发 promotion
* 用于发现更稳、更正交、更值得后续蒸馏的 alpha 组合

### 8.2 设计原则

1. **research / production 解耦**
2. **family-aware sampling**
3. **mask-aware panel consumption**
4. **benchmark-relative objective**
5. **correlation / redundancy / turnover penalty 前置**
6. **输出是研究候选，不是直接生产候选**

### 8.3 输入

输入至少包括：

* 79-symbol research panel
* 受控 research feature 子集（本轮 12 个 + 已有少量稳定基底）
* complete OHLCV-derived factors
* `benchmark_map`
* `research_mask`
* label mode（默认主线用 `cc`）

### 8.4 候选 schema

每个 composite 候选应包括：

* feature list
* family buckets
* transform / standardization spec
* weighting scheme
* benchmark-relative metrics
* turnover / cost proxy
* regime summary

### 8.5 采样策略

不沿用旧的 residual-weight MultiFactorSpace。建议：

* family buckets 先采样，再在 bucket 内采 feature
* 每个 composite 由 3–6 个 family 驱动
* 防止 6 个几乎同类 feature 堆成一个伪多元组合
* 引入 correlation / redundancy penalty
* 引入 turnover / cost penalty

### 8.6 Backend 与 objective

v1 默认后端：

* **Optuna TPE**
* **single weighted-sum objective**

默认目标函数：

```
objective = w1 * OOS_IR
          - w2 * turnover_proxy
          - w3 * corr_concentration
          + w4 * benchmark_excess
          - w5 * regime_stddev
```

要求：

* 提供合理默认权重
* 允许 CLI 覆盖权重
* Pareto multi-objective 仅作为 v2 option，不纳入本轮主实现

### 8.7 输出

* top-K composites
* factor-family 组成
* benchmark-relative 结果
* risk / cost / turnover 摘要
* regime breakdown
* 与 baseline / old production-linked miner 的差异

---

## 9. Feature Family 分组（供 composite miner 使用）

### Family A：Benchmark-relative / Residual

* `rel_spy_20d`
* `rel_qqq_20d`
* `beta_spy_60d`
* `residual_mom_spy_20d`

### Family B：Path / Position / Breakout

* `range_pos_252d`
* `days_since_52w_high`
* `breakout_20d_strength`
* `dist_from_new_high_252`

### Family C：Liquidity / Cost / Risk State

* `amihud_20d`
* `downside_vol_20d`
* `vol_ratio_5_20`

### Family D：Trend Quality

* `trend_tstat_20d`

后续扩展时，新的 family 应优先来自不同经济维度，而不是该 family 的相似 lookback 变体。

---

## 10. Data Dependencies：本轮不新开重数据层

### 10.1 本轮可落地的数据依赖

本轮 feature 只允许依赖：

* adjusted OHLCV
* benchmark OHLCV（至少 SPY / QQQ）

### 10.2 本轮明确不依赖的新数据层

* point-in-time sector / industry classification
* shares outstanding / float
* earnings calendar / surprise / revisions
* short interest
* options surface / IV
* ownership / insider / altdata

### 10.3 数据分层引用

本 PRD 引用 `docs/20260423-feature_data_tier_classification.md` 作为
**Appendix A**。所有 feature 的 tier 归类、code prereq、数据 vendor 选
型以该文档为准。后续新 feature 要进 research registry 前，应先在
classification doc 找到其 tier，再决定是否属于本 PRD scope。

---

## 11. Success Criteria

### 11.1 Feature & Plumbing 成功标准

* 12 个 feature 全部进入 factor registry 且下游可消费
* `benchmark_map` 落地
* residualization helper 落地
* audit 点名的 8 个脚本中至少 **6 个** 升级到完整 panel contract 并可跑通
* research_mask 在 panel / miner / diagnostics 层全部生效

### 11.2 Composite Miner 成功标准

* 能稳定产出 top-K research composites
* top-K 明显比当前 production-linked miner 具有更高 family diversity
* 输出包含 benchmark-relative / turnover / correlation / regime 诊断
* 至少发现 1–3 个值得进入后续蒸馏 / 深验证的候选方向

### 11.3 宏观成功标准

即便本轮暂未产生可 promote 候选，只要满足以下任一，也视为成功：

* 研究搜索空间明显打开
* 新 feature families 真正进入 composite 前沿
* benchmark-relative 结果比旧 production-linked miner 更接近可用
* sample definition 明显更干净，研究结果可解释性更强

---

## 12. Artifact / Lineage / Storage Layout

### 12.1 Lineage tag

本轮统一 lineage tag：

* `post-2026-04-24-rcm-v1`

所有 miner trials / reports / diagnostics / acceptance artifacts 均应沿用该 lineage。

### 12.2 Artifact 路径

独立于现有 production mining 路径：

* `data/ml/research_miner/`
  * top-K outputs
  * factor-family stats
  * correlation heatmaps
  * benchmark-relative diagnostics
* `data/mining/rcm_archive.db`
  * research composite miner archive
  * 独立于现有 `archive.db`
* `data/mining/rcm_optuna.db`
  * research composite miner 的 Optuna study
  * 独立于现有 production mining Optuna DB

### 12.3 独立 DB 的理由

Research Composite Miner 的 schema 将包括：

* family buckets
* correlation penalty
* benchmark-relative objective
* mask-aware summaries

这些语义与现有 production-linked MiningArchive 不同；若强插到同一 DB，会重新引入 production-linked 耦合。

---

## 13. Ralph-Loop Execution Plan

### 13.1 Loop 目标

ralph-loop 的目标是：

* 完成本 PRD 的 4 条主线
* 在 hard budget 内完成 first workable v1
* 产出 top-K research composites 与完整诊断
* 不触碰 production promotion 路径

### 13.2 Max iterations

* **Hard ceiling：22 rounds**

说明：22 是 defensible ceiling，不是承诺一定跑满；若提前满足 halt 条件，应立即停止。

### 13.3 Halt conditions

任一满足即可 halt：

1. 12 个 feature + 3 项 plumbing + research_mask 全部完成，且 miner 已完成首轮运行与分析
2. Step 2 plumbing 失败且无法在 2 个 rounds 内修复，则 **不得进入 Step 5 miner**
3. multi-benchmark / residualize / panel contract 任一关键接口引发系统性回归，且修复成本超出本轮预算
4. research_mask 硬化后导致关键脚本无法形成有效 panel，且 blocker 指向新数据层需求
5. miner v1 首轮结果显示 search space 未打开，且 blocker 明确属于"本 PRD out-of-scope 数据层缺失"
6. 单测或关键 research scripts 出现连续失败，表明本轮已进入 bug-fix spiral
7. 已达到 22 rounds hard ceiling

### 13.4 Autonomous decision boundaries

**允许 autonomously 做的事：**

* 新 helper / refactor within scope
* 修改 factor generator signature
* 修改那 8 个脚本
* 新增 RESEARCH_FACTORS / research-only registry entries
* 跑 research composite miner 与诊断
* 新增/更新 docs 与 logs

**禁止 autonomously 做的事：**

* 修改 `PRODUCTION_FACTORS`
* 修改 `config/universe.yaml`
* 修改 `config/production_strategy.yaml`
* auto-promote / dry-run promote
* 引入新 vendor / 新重数据层
* 把 research miner 与 production miner archive 混库

### 13.5 Launch script

Launcher：

* `scripts/start_research_miner_loop.sh`

### 13.6 Logging / round reports

沿用既有约定：

* 11-part 中文 round report
* 写入 `docs/20260420-ralph_loop_log.md`（续写约定）
* Section header: `R-rcm-v1-round-NN`
* 每轮必须记录：完成项 / blocker / 下一轮计划 / 是否触发 halt 条件

### 13.7 Completion promise

完成承诺字符串：

* `RCMV1DONE`

---

## 14. 风险与对策

### 风险 1：feature 已落地，但下游仍未消费
**对策：** 本轮将 3 项 plumbing 列为硬前置，不允许 feature 独立结项。

### 风险 2：mask 逻辑仍停留在 observability
**对策：** 明确要求 panel / miner / diagnostics 共用 research_mask。

### 风险 3：composite miner 变成另一个过度复杂黑箱
**对策：** v1 只采受控 feature 子集，强调 family-aware 与可诊断性。

### 风险 4：feature 仍然同源性过高
**对策：** 只做 orthogonal 子集，不继续堆同类 return / MA 变体。

### 风险 5：过早把目标重新拉回 production promote
**对策：** 本 PRD 明确研究导向，输出是 research candidates，不直接 promote。

---

## 15. 推荐执行顺序

### Step 1
冻结 feat-v1 成果，不再在旧 PRD 上继续追加小修小补。

### Step 2
实现 3 项 plumbing 前置：

* multi-benchmark factor generator
* residualization helper
* 8 个脚本升级到完整 panel contract

### Step 3
落地本轮 12 个 feature，并补相应单测 / sanity checks。

### Step 4
硬化 research_mask：

* panel
* composite miner
* diagnostics / acceptance

### Step 5
定义并实现 Research Composite Miner v1：

* family-aware sampling
* benchmark-relative objective
* correlation / turnover penalty
* non-promotion output

### Step 6
运行第一轮 research-only composite mining，并输出 top-K 分析。

### Step 7
根据结果决定下一轮是否：

* 扩 feature family（而非单纯加 count）
* 接轻量新数据层（sector / earnings）
* 从 research candidate 中蒸馏 future production 路线

---

## 16. 一句话总结

**下一阶段的主任务不是继续扩 ticker，也不是继续在旧 production-linked MultiFactorSpace 里多跑，而是把 feat-v1 的 plumbing 真正接入下游，并基于一批可落地、更加正交的 feature 建立 Research Composite Miner v1，让系统开始具备发现新 alpha 前沿的能力。**

---

## Appendix A — Feature Data-Tier Classification

本 PRD 引用 `docs/20260423-feature_data_tier_classification.md` 作为
**Appendix A**。该文档提供 T1-T6 tier 分类、per-feature 归类、per-tier
code prereq、data vendor 建议与 future narrow-PRD 路径，作为本 PRD 与
所有后续 feature-expansion PRD 的单一参考。

*PRD v1.0 final. 等待 ralph-loop 启动。*
