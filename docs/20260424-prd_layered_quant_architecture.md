# PRD：Layered Quant Architecture（Research → Shadow/Paper → Future Production）

> **Status**: Proposal (not yet in implementation). Drafted and provided by
> user on 2026-04-24. Captures the high-level structural direction for
> PQS's next architecture phase.
>
> **Companion PRD**: `docs/20260424-prd_research_to_paper_promote_standard.md`
> defines the concrete S0 → S1 → S2 promote gate.
>
> **Relation to existing PRDs**: supersedes the scattered paper/production
> references across `docs/20260421-prd_framework_completion.md` (M11, M12,
> M17). Those milestones should be folded into Phase E-0 / E-1 when
> implementation starts.

## 1. Executive Summary

当前系统已经具备较强的研究能力，但尚未形成真正意义上的生产交易系统。现状更准确的描述是：

* 已有较完整的 **Research / Discovery** 能力
* 尚缺正式的 **Shadow / Paper Validation** 层
* 尚未具备真正的 **Production Trading** 层

如果继续让 research candidate 直接面向 production promote，会带来三个系统性问题：

1. **Research 与部署目标混淆**：研究层为了发现 alpha，应该允许更宽的搜索空间；生产层为了稳定赚钱，必须更保守、更可控。
2. **缺少 live-like 验证层**：离线 OOS / holdout / acceptance 不能替代真实时间顺序下的信号生成、数据健康和执行约束验证。
3. **版本治理不清**：没有清晰的 promote / demote 状态机，就无法建立稳定的策略生命周期管理。

因此，本 PRD 的核心目标是：

> 建立一个清晰的三层架构：
> **Research Layer → Shadow/Paper Validation Layer → Future Production Layer**

同时定义：

* 每层的输入 / 输出
* promote criteria
* demote / disable criteria
* artifact 规范
* 职责边界
* 生命周期状态机

本 PRD 不要求立刻实现完整 production 下单系统，但要求从现在开始按 production-grade 的边界来设计 research 与 paper 层。

---

## 2. Why Now

当前项目已经暴露出一个关键架构问题：

* research plumbing 已经越来越完整
* feature pool 与 composite miner 正在扩展
* 但系统仍缺少"研究发现如何进入 live-like 验证，再进入未来生产"的中间层

这意味着当前系统更像：

> 强研究引擎 + 弱部署治理

如果不先把层级与状态边界建立起来，后续会出现：

* research candidate 与 production candidate 混淆
* acceptance 通过后就想上生产
* strategy version、live drift、回滚条件没有统一定义
* paper validation 变成"可有可无的附属测试"，而不是正式层

所以，这份 PRD 的价值不是为了"流程好看"，而是为了：

> 把一个研究项目，升级成一个有生命周期治理能力的量化系统。

---

## 3. Architecture Overview

本系统采用三层架构：

### Layer 1：Research / Discovery

回答的问题：

* 有没有 alpha？
* 是否有经济逻辑与研究证据支持？
* 是否值得进入更接近实盘的验证？

### Layer 2：Shadow / Paper Validation

回答的问题：

* 在真实时间顺序下，这个策略是否 still alive？
* 数据、信号、权重、调仓、成本假设在 live-like 条件下是否稳定？
* 是否具备部署准备度？

### Layer 3：Future Production

回答的问题：

* 是否可以稳定、可控、可回滚地实际运行与交易？
* 是否有足够的监控、风险控制、版本治理？

---

## 4. Lifecycle State Machine

建议从现在开始，将策略状态定义为以下生命周期：

### S0：Research Prototype

刚从 feature / factor / funnel / miner 中产出的原型。

### S1：Research Candidate

通过 research acceptance，具备进入 shadow/paper 的资格。

### S2：Shadow / Paper Candidate

冻结版本，进入准实时或模拟交易验证。

### S3：Deployment Candidate

通过 paper validation，具备进入未来 production 的条件，但尚未真正部署。

### S4：Production

真实部署中。

### S5：Deprecated / Demoted

被降级、回滚或下线。

### 状态迁移原则

* `S0 -> S1`：Research promote
* `S1 -> S2`：Enter paper validation
* `S2 -> S3`：Paper promote
* `S3 -> S4`：Production deploy
* 任意阶段均可进入 `S5`

本 PRD 的近期目标不是打通到 S4，而是：

> 把 **S0 / S1 / S2** 三个状态正式建立起来。

---

## 5. Layer 1：Research / Discovery

## 5.1 定位

Research Layer 的职责是：

* 发现 alpha
* 生成 candidate
* 累积证据
* 过滤明显不可靠的想法

它不是为了直接生产交易，而是为了：

> 以较高迭代速度发现值得进一步验证的策略原型。

## 5.2 输入

Research Layer 的输入包括：

* adjusted OHLCV / benchmark OHLCV
* research feature registry
* factor engineering outputs
* labels / masks / panel contract
* research composite miner / funnel / orthogonalization outputs
* offline backtest / OOS / holdout / regime diagnostics

## 5.3 输出

Research Layer 的输出不是 production strategy，而是：

* research candidates
* candidate YAML / spec
* acceptance pack
* benchmark-relative diagnostics
* regime report
* factor-family stats
* research decision memo
* promotion recommendation to paper layer

## 5.4 允许做的事情

* feature engineering
* factor generation
* LLM candidate generation
* research-only composite mining
* offline backtest / OOS / holdout / regime analysis
* research acceptance packs
* 研究级 promote 到 shadow/paper candidate

## 5.5 不允许做的事情

* 直接修改 production strategy config
* 直接用 research candidate 替代 live strategy
* 以 research score 单独作为 production 部署依据
* 用 production artifact 替代 research artifact

## 5.6 Promote Criteria（Research -> Paper）

Research Candidate 要进入 Shadow/Paper 层，至少应满足：

### A. 研究表现

* OOS / holdout 达到预设门槛
* benchmark-relative 不是纯 beta 幻觉
* full-period 不只是单段驱动
* regime 行为可解释

### B. 鲁棒性

* cost proxy 不明显脆弱
* stress / regime variation 不出现明显崩坏
* feature / composite 不依赖单个极端样本

### C. 可解释性与冻结性

* candidate spec 已冻结
* feature list 与 transforms 已冻结
* risk overlay / rebalance 规则已冻结
* 有清晰的经济逻辑说明

### D. 工程可运行性

* panel 可稳定生成
* mask / labels / benchmark 对齐稳定
* artifact 完整

满足以上条件后，状态从 `S0 -> S1`，并进入 `S2` paper 候选池。

## 5.7 Demote / Reject Criteria

Research Candidate 在以下情况下应被拒绝或降级：

* OOS / holdout 不达标
* benchmark-relative 明显只靠单一风格暴露
* cost proxy / turnover 过脆
* regime breakdown 显示明显单段幻觉
* 关键样本定义不稳定
* 经济解释薄弱，无法区分 alpha 与过拟合

## 5.8 Research Artifacts

Research Layer 应标准化保存以下 artifact：

* PRD / research plan
* candidate YAML / spec JSON
* factor registry snapshot
* acceptance pack JSON
* OOS / holdout report
* regime-stratified report
* benchmark-relative report
* loop log / round log
* research decision memo

这些 artifact 的用途：

* 可复查
* 可复现
* 可交接
* 可审计

## 5.9 职责边界

Research Layer 负责发现与筛选，但不负责真实部署。

它的终点不是 production，而是：

> **生成一个值得进入 Shadow/Paper 验证的冻结候选。**

---

## 6. Layer 2：Shadow / Paper Validation

## 6.1 定位

Shadow / Paper 层的目标不是再次"寻找 alpha"，而是：

> 在真实时间顺序、准实时、准部署条件下，验证一个冻结策略是否 still alive，是否具备部署准备度。

这层应当被视作独立层，而不是研究层的附属测试。

## 6.2 输入

Paper Layer 的输入应是已经冻结的 Research Candidate：

* frozen strategy spec
* frozen feature set
* frozen weighting / rebalance logic
* frozen benchmark / regime / overlay rules
* frozen cost model version
* daily / scheduled data feeds
* paper execution assumptions

## 6.3 输出

Paper Layer 的输出包括：

* daily signal snapshots
* daily target portfolio snapshots
* simulated fills / paper trades
* live-like PnL path
* benchmark-relative paper report
* drift / stability report
* deployment readiness memo
* promote / hold / reject decision

## 6.4 允许做的事情

* 定时生成信号
* 模拟交易 / 模拟成交
* 收集 live-like 运营指标
* 监控数据质量与信号稳定性
* 记录 drift / slippage / turnover 变化
* 输出 paper validation report

## 6.5 不允许做的事情

* paper 期间不断改 feature / alpha 逻辑
* 一边 paper 一边改变 rebalance 与权重逻辑
* 用"调整后版本"混淆原始 paper 结果
* 把 paper 当成继续探索 search space 的地方

## 6.6 Paper Promote Criteria（Paper -> Deployment Candidate）

进入 Deployment Candidate（`S2 -> S3`）至少要求：

### A. Live-like 路径稳定

* 信号按预定时点稳定生成
* 缺失 / stale / timing 问题可控
* live path 与 research expectation 偏差可解释

### B. 交易可行性

* turnover / concentration / capacity 在可接受范围内
* cost / slippage 假设没有被 live-like 结果明显打穿
* 模拟成交路径合理

### C. 风险与监控

* 暴露没有显著漂移
* kill-switch 事件不频繁
* 风险指标稳定
* benchmark-relative live performance 未明显失真

### D. 版本治理

* strategy version 完整冻结
* artifact 完整
* 可以一键回溯 paper 期间的任一时点状态

## 6.7 Paper Reject / Hold / Demote Criteria

策略在以下情况下应暂停、延长 paper 或降级：

* 信号生成不稳定
* 数据质量问题频繁
* live drift 与 research 偏差持续扩大且不可解释
* turnover / cost / concentration 明显劣化
* 准实时行为与研究结论相冲突
* paper 结果高度依赖单几日噪声

## 6.8 Paper Artifacts

Paper Layer 必须产出的 artifact 包括：

* frozen strategy spec snapshot
* daily signals log
* target portfolio snapshots
* paper fills / order simulation log
* live-like PnL report
* benchmark-relative paper report
* signal stability / missingness / stale-data log
* deployment readiness report
* go / no-go / extend-paper memo

## 6.9 职责边界

Paper Layer 负责：

* 验证部署可行性
* 验证 live-like 稳定性
* 验证真实时间顺序表现

它不负责：

* 大规模研究探索
* feature search
* strategy redesign

它的终点是：

> **把 research candidate 变成一个 deployment candidate，或证明它不值得进入 future production。**

---

## 7. Layer 3：Future Production

## 7.1 定位

Production Layer 是未来层，目前尚未真正实现。

它的目标不是做研究，而是：

> 在真实环境中稳定、可控、可监控、可回滚地运行策略。

## 7.2 输入

Production Layer 的输入应该是经过 paper promote 的 Deployment Candidate：

* frozen strategy version
* approved deployment package
* validated execution assumptions
* production risk controls
* monitoring / alerting configuration

## 7.3 输出

Production Layer 的输出包括：

* live orders / fills
* live portfolio state
* production performance reports
* benchmark-relative live reports
* risk exposure reports
* alerts / incident logs
* rollback / demotion records

## 7.4 Production 所需能力（未来建设目标）

真正的 Production Layer 至少需要：

* live data ingestion
* data health checks
* order routing / broker adapter
* portfolio construction
* risk controls
* kill switch
* monitoring / alerting
* strategy versioning
* post-trade attribution
* rollback / demotion workflow

## 7.5 Production Promote Criteria（Deployment -> Live）

进入真正 Production（`S3 -> S4`）至少要求：

* paper validation 通过
* 风险与监控配置完备
* data / execution / rollback 路径可用
* versioned deployment package 可审计
* 人工审批通过

## 7.6 Production Demote / Disable Criteria

Production 中出现以下情况，应触发降级、停用或回滚：

* 连续 live drift 显著偏离 research / paper expectation
* benchmark-relative 表现持续恶化
* turnover / slippage / concentration 超阈值
* 风险暴露异常
* 数据健康持续异常
* kill switch 频繁触发
* 新 regime 明显超出已验证范围

## 7.7 Production Artifacts

Production Layer 最终应保存：

* deployed strategy package
* config snapshot
* order / fill logs
* live PnL reports
* risk exposure reports
* incident / alert logs
* kill-switch logs
* rollback / demotion records

## 7.8 职责边界

Production Layer 负责：

* 真实部署
* 真实交易
* 真实风控
* 真实监控

它不负责：

* 研究探索
* alpha search
* 改策略逻辑

---

## 8. Promote / Demote Governance

## 8.1 三类 Promote

系统中应明确区分三种 promote：

1. **Research Promote**：`S0 -> S1`
   研究原型成为正式 Research Candidate

2. **Paper Promote**：`S1/S2 -> S3`
   通过 shadow/paper validation，成为 Deployment Candidate

3. **Production Promote**：`S3 -> S4`
   真正进入生产部署

不得再使用一个模糊的"promote"覆盖所有层级。

## 8.2 Demote / Disable 治理

同样应区分：

* research reject
* paper hold / reject
* production disable / rollback

每次 promote / demote 都必须有：

* decision memo
* supporting artifacts
* version reference
* responsible reviewer / approver

---

## 9. Artifact Policy

## 9.1 Artifact 定义

Artifact 是指：

> 某一层流程跑完后，留下来的"可复查、可复现、可交接、可审计"的正式输出物。

不是所有文件都算 artifact；只有具备明确决策用途与版本意义的输出，才算正式 artifact。

## 9.2 Artifact 原则

每层 artifact 都必须满足：

* 有清晰来源
* 有版本与时间标记
* 可与对应 strategy version 绑定
* 可被后续 promote / demote 决策引用
* 不因下游改动而 silently 失效

## 9.3 Artifact 分层要求

### Research artifacts

* 候选 spec
* acceptance pack
* regime report
* benchmark-relative report
* research memo

### Paper artifacts

* frozen paper spec
* daily signals / portfolio snapshots
* paper trade log
* drift / readiness report

### Production artifacts

* deployed package
* order / fill log
* risk / incident log
* rollback record

---

## 10. Immediate Build Priorities

考虑到当前系统还没有真正的 production 层，近期重点应放在：

### Priority 1：Research Layer 正式化

* Research Candidate schema
* Research acceptance 标准
* Research artifacts 标准化
* research composite miner 融入正式候选生命周期

### Priority 2：Shadow / Paper Layer 建设

* Frozen candidate concept
* Scheduled signal generation
* Paper portfolio snapshots
* Paper trade simulation
* Drift / readiness reports
* Paper promote criteria

### Priority 3：Future Production Layer 占位设计

* 先定义接口与 artifact 规范
* 不急于一次性实现完整 broker / execution stack

---

## 11. Success Criteria

本 PRD 的成功，不以"马上实盘"为标准，而以以下条件为标准：

### A. 架构成功

* 三层边界明确
* 生命周期状态明确
* promote / demote 语义清晰

### B. 治理成功

* 各层 artifact 定义清楚
* 候选从 research 进入 paper 有明确标准
* 不再混淆 research candidate 与 production candidate

### C. 系统成功

* 当前 research 结果能自然流入 paper 验证
* paper 层能作为未来 production 的前置门
* 未来 production 不需要推翻已有 research / paper 规范即可接上

---

## 12. Out of Scope

本 PRD 当前不要求：

* 立即接入真实 broker
* 立即实现完整 order execution engine
* 立即启动真钱生产部署
* 在本轮中确定所有 production 级风险规则细节

本 PRD 的核心是：

> **先把分层治理与 promote / demote 逻辑建立起来。**

---

## 13. Recommended Next Steps

### Step 1

将当前 research outputs 正式归档为：

* Research Prototype
* Research Candidate

### Step 2

定义一份 **Research -> Paper Promote Standard**

### Step 3

建立最小可行 Shadow / Paper pipeline：

* 冻结候选
* 定时生成信号
* 记录 target portfolio
* 产出 daily paper artifacts

### Step 4

定义 **Paper Validation Report** 模板

### Step 5

为 future production 预留：

* deployment package schema
* monitoring artifact schema
* rollback record schema

---

## 14. One-Sentence Summary

**要把当前系统从"强研究项目"升级为"可治理的量化系统"，必须正式分成 Research、Shadow/Paper、Future Production 三层，并为每层定义输入、输出、promote / demote 标准、artifact 和职责边界。**
