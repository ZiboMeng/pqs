# PRD：Phase E — Research Governance + Paper Transition

> **Status**: Phase E charter PRD provided by user 2026-04-24.
>
> **Role**: this document is the **what/why** for Phase E. The companion
> **how/when** execution PRD is `docs/20260424-prd_phase_e_execution.md`
> (ralph-loop round-by-round plan).
>
> **Relation to other PRDs**:
> - `docs/20260424-prd_layered_quant_architecture.md` — long-term architecture
> - `docs/20260424-prd_research_to_paper_promote_standard.md` — promote rules
> - `docs/20260424-prd_research_composite_miner_v1.md` — RCMv1 feeder
> - this charter consolidates them into a Phase E plan, it does NOT replace them

## 1. 文档定位

这份 PRD 是当前阶段的**统一执行主文档**。

它不推翻已有 PRD，而是把此前已经形成的 3 份文档收敛为一个可执行的 Phase E 计划：

1. **Layered Quant Architecture PRD**
   作用：定义长期分层架构与状态机（Research / Shadow-Paper / Future Production）

2. **Research → Paper Promote Standard PRD**
   作用：定义从研究候选进入 paper/shadow 的门槛与治理标准

3. **Research Composite Miner v1 PRD**
   作用：定义 research-only composite miner 与 orthogonal feature 扩展方向

本 PRD 的作用不是重复以上内容，而是：

> **把"该先做什么、后做什么、哪些先不做"写成一个 Phase E 的统一实施蓝图。**

它是后续开发、审计、复盘以及新 PRD 撰写的基准文档。

---

## 2. 当前阶段的核心判断

经过最近一轮代码审计、研究复盘和开发建议汇总，当前系统的关键结论如下：

### 2.1 已经做对的部分

* Research plumbing 已经显著成熟
* research composite miner 已经具备雏形
* orthogonal feature expansion 的方向已经明确
* acceptance / memo / reports / loop artifacts 已经开始形成系统

### 2.2 当前最缺的不是更多研究功能

当前最缺的是：

* **candidate 生命周期治理**
* **Research → Paper 的冻结与 promote 机制**
* **revoke 工作流**
* **paper 层对 frozen candidate 的验证路径**

### 2.3 当前不该优先做的事

当前不应优先投入：

* 完整 Production Layer
* broker adapter / live execution
* 更复杂的 paper automation（daemon / scheduler / alerting）
* 新的大数据层（earnings / options / alt data）
* 新一轮大而全的 PRD 扩写

### 2.4 当前最重要的系统性风险

最大的风险不是"没想到新 feature"，而是：

> **research 结果还没有形成正式治理闭环，导致"看起来可以 promote 的候选"缺少冻结、撤销、过渡到 paper 的机制。**

最近一次由于 leakage audit 才识别出的虚假强信号，就是这个风险的典型案例。

---

## 3. Phase E 的总目标

Phase E 的目标不是"实现 production 交易系统"，而是：

### 总目标 A：把治理闭环补齐

让系统从"强研究项目"升级为"有候选生命周期治理的量化系统"。

### 总目标 B：建立最小可用的 Research → Paper 过渡层

让研究候选可以：

* 冻结
* 进入 paper
* 被撤销
* 被审计
* 被版本化管理

### 总目标 C：不破坏现有研究能力

Phase E 必须建立在已有 RCMv1、research acceptance、feature plumbing 的基础上，而不是重做一遍。

---

## 4. Phase E 的总体原则

### 原则 1：复用已有 PRD，不推倒重来

之前的 PRD 仍然有效，但角色不同：

* **Layered Architecture PRD**：继续作为长期架构原则文档
* **Research → Paper Promote Standard PRD**：继续作为 promote 规则文档
* **RCMv1 PRD**：继续作为 research search 空间建设文档
* **本 PRD**：作为当前阶段的统一执行路线图

### 原则 2：优先做治理原语，不优先做更大系统

现在最值得做的是：

* candidate registry
* status state machine
* revoke
* frozen paper package
* paper runner 读取 frozen candidate

而不是：

* 新 broker
* 真 production
* 自动化 paper orchestration

### 原则 3：Research / Paper / Production 语义必须彻底拆开

不得再用一个模糊的 `promote` 表示所有层级的推进。

### 原则 4：trial archive 与 candidate registry 必须分离

实验记录是实验记录，治理对象是治理对象。

---

## 5. 这份 PRD 与已有 PRD 的关系

## 5.1 可以直接复用的内容

### 来自 Layered Architecture PRD

复用：

* 三层架构定义
* S0 / S1 / S2 / S3 / S4 / S5 生命周期状态机
* 各层职责边界
* artifact 分层定义

### 来自 Research → Paper Promote Standard PRD

复用：

* Promote Input Package 思路
* promote / hold / reject 三种结论
* Frozen Paper Package 定义
* hard blocks / revoke 原则

### 来自 RCMv1 PRD

复用：

* research-only composite miner 的定位
* orthogonal feature 扩展方向
* benchmark-relative / mask-aware / family-aware 原则

## 5.2 这份 PRD 新增的内容

这份 PRD 新增的是：

* **Phase E 的分阶段执行顺序**
* **哪些现在做，哪些之后做**
* **哪些 PRD 内容进入 design-only 状态**
* **哪些组件要先代码化，哪些先不动**

---

## 6. 当前真实系统状态（审计视角）

### 已存在

* Research Composite Miner v1 雏形
* Research acceptance 逻辑
* RCM 独立 archive / study 方向
* 一批 feature engineering 与 plumbing 成果
* 部分 paper trading 基础设施

### 不足

* 没有独立的 `research_candidates` registry
* `promote_strategy.py` 仍然混淆 production promote 语义
* 没有正式 `Frozen Paper Package`
* 没有 `revoke_candidate()` 工作流
* paper runner 仍然倾向读取 production config，而不是 frozen candidate
* artifact 路径与命名未形成统一约束

### 结论

当前系统已经足够支撑 **Phase E-0 / E-1 / E-2**，但还远不到需要建设完整 production layer 的阶段。

---

## 7. Phase E 分阶段实施计划

# Phase E-0：Taxonomy + Candidate Governance Foundation

### 目标

先把"谁是什么"与"候选如何被治理"建立起来，不碰真正复杂的 live / execution 系统。

### 本阶段要做的事

#### E0-1. 建立 candidate registry

新增独立治理层，不把 candidate 生命周期直接塞进 trial archive。

建议新增：

* `research_candidates` table 或等价 registry

字段至少包括：

* `candidate_id`
* `source_trial_id`
* `status`
* `frozen_spec_path`
* `promoted_at`
* `revoked_at`
* `revoke_reason`
* `decision_memo_path`
* `created_at`
* `updated_at`

#### E0-2. 引入状态机字段

在 candidate registry 层支持：

* `S0 Research Prototype`
* `S1 Research Candidate`
* `S2 Shadow/Paper Candidate`
* `S3 Deployment Candidate`
* `S4 Production`
* `S5 Deprecated/Demoted`

本阶段只要求真正用到：

* S0
* S1
* S2
* S5

S3+ 保留为 design-only / placeholder。

#### E0-3. 规范 promote 语义

不要再让 `promote_strategy.py` 同时承担 research promote 与 production promote 的语义。

建议：

* 保留 `promote_strategy.py` 作为 **production-only promote** 工具
* 新增：

  * `freeze_research_candidate.py`
  * `research_promote.py`
  * `revoke_candidate.py`

#### E0-4. 引入 revoke workflow

这是 E0 的硬要求，不后置。

需要支持：

* 从 S1 / S2 撤销回 S0 或 S5
* 记录 `revoke_reason`
* 记录 `revoked_at`
* 关联 supporting memo / audit artifact

#### E0-5. 统一 candidate artifact 路径

建议新增：

* `data/research_candidates/`

用于存放：

* frozen candidate YAML
* decision memo link/reference
* candidate-level metadata

### E0-6. 解耦 paper layer 与 parquet / pyarrow 顶层依赖

这是一个与治理 taxonomy 同级的并行工程任务，不应延后到 E-1 / E-2。

当前问题：

* `core/data/__init__.py` 顶层 eager import `MarketDataStore`
* `MarketDataStore` 顶层依赖 `pyarrow`
* `scripts/run_paper.py` 顶层直接 import `MarketDataStore`

结果是：

* 轻量 paper-layer 单测被 parquet stack 拖死
* 与 paper governance 无关的测试，也会被 data persistence 层耦合阻断
* 不利于后续把 frozen candidate / paper runner 做成轻量、可测、可替换的数据消费路径

#### 本阶段要求

* 将 `core/data/__init__.py` 中的 eager import 改为 lazy import 或等价延迟加载模式
* `scripts/run_paper.py` 顶层不再直接 import `MarketDataStore`
* 通过 dependency injection、factory、或 lazy loader 方式，在真正需要 parquet store 时再加载数据后端

#### 验收目标

至少满足以下条件：

* `python -c "from core.paper_trading.paper_trading_engine import PaperTradingEngine"` 不触发 `pyarrow` 加载
* 轻量 paper-layer 单测可以在不初始化 parquet stack 的情况下运行
* paper runner 的核心逻辑与 data persistence backend 解耦

#### 设计原则

* paper 层依赖"数据访问接口"，而不是直接依赖具体存储实现
* persistence backend 应留在边界层，而不是通过顶层 import 污染核心 paper logic
* 不要求本阶段重构整个 data layer，只要求把 paper 路径从 eager parquet dependency 中解耦出来

### 本阶段不做

* paper 自动化运行
* drift daemon
* broker / execution
* production config 改写

### E-0 验收标准

* candidate registry 落地
* state machine 可写入/读取
* `research_promote` / `revoke_candidate` 基本流程可跑
* `promote_strategy.py` 语义不再混淆
* 至少 1 个真实 candidate 能完成 S0 -> S1 -> revoke 或 hold 的流程

---

# Phase E-1：Promote Standard Code-ification

### 目标

把 Research → Paper Promote Standard 变成代码化流程，而不是停留在文档约定。

### 本阶段要做的事

#### E1-1. 实现 Promote Input Package 代码接口

不要求第一版就填满所有字段，但必须形成结构化输入。

建议第一版强制字段至少包括：

* `candidate_id`
* `strategy_version`
* `source_trial_id`
* `feature_set`
* `benchmark_relative_summary`
* `oos_holdout_summary`
* `robustness_summary`
* `decision_memo`

其余字段可先 optional。

#### E1-2. `freeze_research_candidate.py`

功能：

* 从 RCM / research archive 读取 source trial
* 生成 frozen spec
* 写入 `data/research_candidates/<candidate_id>.yaml`
* 同时生成 metadata / reference

#### E1-3. `research_promote.py`

功能：

* 验证 frozen spec
* 校验 acceptance / hard blocks
* 生成 promote decision
* 状态迁移 `S0 -> S1`
* 不得改动任何 production config

#### E1-4. `revoke_candidate.py`

功能：

* 任何时点撤销一个 candidate
* 更新状态
* 写入 revoke reason
* 落盘 revoke memo

#### E1-5. 最小单测

至少覆盖：

* candidate 冻结
* candidate promote
* candidate revoke
* 状态迁移
* 缺失 artifact 阻断

### 关于 acceptance 逻辑的处理

短期不建议强行做一个"大一统 acceptance_pack v3"。

更稳的做法是：

* 抽共享 evaluator / helper
* 保留：

  * `research_acceptance`
  * `production_acceptance`

避免层级边界被抹平。

### 本阶段不做

* scheduled paper runs
* automated drift monitoring
* paper -> production promote

### E-1 验收标准

* 至少 1 个真实 candidate 完整跑通：

  * freeze
  * promote to S1
  * hold / revoke / approve for paper
* Promote Input Package 能结构化保存
* `Frozen Paper Package` 有初版 schema
* revoke 能在 research 层真实使用

---

# Phase E-2：Minimal Paper Layer v1

### 目标

建立一个**最小可用**的 paper/shadow 验证层。

关键原则：

* 不做重自动化
* 不做 scheduler / daemon
* 不做 production execution
* 只做"手动 daily run + frozen candidate 验证"

### 本阶段要做的事

#### E2-1. `run_paper_candidate.py`

功能：

* 读取 Frozen Paper Package
* 运行 paper_trading_engine 或等价 paper runner
* 生成每日 signal / target portfolio snapshot
* 记录 candidate-specific paper artifacts

#### E2-2. paper artifacts

至少产出：

* daily signals log
* target portfolio snapshots
* simulated PnL / NAV path
* benchmark-relative paper summary

#### E2-3. drift report（最小版）

不要求复杂监控，但至少要有：

* paper NAV vs same-period replay backtest 的 delta
* BPS-level 差异摘要
* 主要偏差来源说明

#### E2-4. Paper candidate status transition

支持：

* `S1 -> S2`
* `S2 -> hold`
* `S2 -> revoke`

`S2 -> S3` 暂时只保留 placeholder，不做真正 production transition。

### 本阶段不做

* cron / airflow
* 自动信号调度
* 监控告警
* live order routing
* broker adapter
* kill switch

### E-2 验收标准

* 至少 1 个 frozen candidate 能完成手动 paper run
* 能产生 paper artifacts
* 能输出最小 drift report
* paper 层读取的是 frozen candidate，而不是 production config

---

# Phase F（Future）：Production Layer

### 目标

保留为未来阶段，不纳入当前执行范围。

### 包含但暂不实现

* broker adapter
* live feed
* order execution
* kill switch
* monitoring / alerting
* production deployment / rollback

### 当前要求

只保留：

* 接口占位
* artifact schema 占位
* 状态机占位（S3 / S4）

---

## 8. 现在该做的 / 之后再做的

## 8.1 现在就该做的（Must Do Now）

### 治理层

* candidate registry
* 状态机 S0/S1/S2/S5
* `research_promote.py`
* `freeze_research_candidate.py`
* `revoke_candidate.py`
* Frozen Paper Package 初版 schema

### 最小 paper 层

* `run_paper_candidate.py`
* frozen candidate 输入路径
* manual paper artifacts
* minimal drift report

### 清理语义

* `promote_strategy.py` 留给 production-only 语义
* acceptance 逻辑明确 research / production 分层

## 8.2 紧接着做的（Should Do Next）

* paper validation report 模板
* more complete candidate metadata
* artifact 命名与目录统一
* acceptance evaluator 共享逻辑抽取
* `S2 -> S3` placeholder workflow

## 8.3 先不要做的（Do Later）

* scheduler / cron / daemon
* alerting / monitoring automation
* broker / execution
* real production deployment
* new data vendors
* full paper automation stack
* production rollback engine
* RCMv1 默认不自动 freeze trial 为 candidate（trial 与 candidate 仍保持 explicit 显式操作分离）

---

## 9. PRD 与优化路线的后续依据

这份 PRD 的另一个作用，是给后续优化和 PRD 撰写提供依据。

### 未来新 PRD 应该基于哪些问题再开

#### 未来 PRD A：Paper Validation Standard

当 E-2 跑通后，再单独立一份 PRD，专门定义：

* paper 层运行多长时间
* 看哪些 live-like 指标
* 什么情况下 hold / extend / reject / promote

#### 未来 PRD B：Production Readiness / Deployment Standard

当 paper 层稳定后，再定义：

* deployment candidate 的要求
* execution / risk / rollback / monitoring 的最低配置

#### 未来 PRD C：Data Tier Expansion

当治理与 paper 过渡稳定后，再开：

* sector / earnings / shares outstanding / options / alt data

#### 未来 PRD D：RCMv2 / Feature Diversity v2

当当前 orthogonal features 与 RCMv1 结果稳定后，再推进：

* 更复杂 family buckets
* more advanced objective
* sector-neutral / residual / microstructure-lite 深化

---

## 10. 风险与对策

### 风险 1：治理做成 bureaucracy theater

**对策：**
E-0 / E-1 只要求最小可用字段与最小闭环，不追求一上来就填满所有表单。

### 风险 2：把 candidate 生命周期硬塞进 archive

**对策：**
明确 candidate registry 独立于 trial archive。

### 风险 3：paper 层被过早复杂化

**对策：**
第一版 paper 只做手动 daily run，不做 scheduler / daemon。

### 风险 4：research acceptance 与 production acceptance 再次混淆

**对策：**
共享 evaluator 可以抽，顶层语义必须分开。

### 风险 5：production 层过早侵入当前阶段

**对策：**
S3 / S4 只保留 design placeholder，不做真部署实现。

---

## 11. 一句话总结

**之前的 PRD 可以复用，而且应该复用；但当前真正需要的是一份新的"Phase E 统一实施 PRD"，把治理闭环、Research→Paper 过渡、最小 paper 层和未来 production 的边界一次性收清楚。**
