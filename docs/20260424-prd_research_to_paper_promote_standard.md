# PRD：Research → Paper Promote Standard

> **Status**: Proposal (not yet in implementation). Drafted and provided by
> user on 2026-04-24 as companion to `docs/20260424-prd_layered_quant_architecture.md`.
>
> **Scope**: defines the S0 → S1 → S2 promote gate (the most-immediate
> piece to implement per Layered Architecture PRD §13 Step 2 / §10
> Priority 1).
>
> **First real example**: the RCMv1 S1 promotion memo
> `docs/20260424-rcm_v1_s1_candidate_memo.md` was written against an
> early form of this standard and demonstrates the Promote Input Package
> structure in practice.

## 1. Executive Summary

本 PRD 定义从 **Research Layer** 进入 **Shadow / Paper Validation Layer** 的标准化 promote 流程。

目标不是证明某个策略已经可以上线，而是回答一个更具体的问题：

> 这个研究候选，是否已经足够成熟，值得进入更昂贵、更接近真实部署环境的 paper/shadow 验证？

因此，Research → Paper promote 的门槛应当：

* **明显高于一般 research prototype**
* **明显低于最终 production deploy 标准**
* 强调 **冻结性、可解释性、鲁棒性、可运行性**
* 避免把"有趣的研究发现"过早推进到 live-like 验证

本 PRD 定义：

* promote 的适用对象
* 必要输入与 artifact
* 通过标准
* reject / hold 标准
* 审批流程
* promote 后 paper 层的冻结要求

---

## 2. Scope

本 PRD 只覆盖：

* `S0 Research Prototype -> S1 Research Candidate`
* `S1 Research Candidate -> S2 Shadow/Paper Candidate`

更准确地说，本 PRD重点定义的是：

> **Research Candidate 是否可以进入 Shadow/Paper Validation**

本 PRD 不覆盖：

* Paper -> Production promote
* 真实下单与 broker 接口
* Production rollback / disable

---

## 3. 状态定义

### S0：Research Prototype

尚处于探索状态的研究原型。

特点：

* 可能只是单个 factor / candidate / composite idea
* 可能仍在迭代 feature / transform / sampling 逻辑
* 结果可以有亮点，但还不具备冻结条件

### S1：Research Candidate

通过 research acceptance 的正式研究候选。

特点：

* spec 冻结
* artifact 完整
* 具备进入 shadow/paper 的资格

### S2：Shadow / Paper Candidate

进入 paper/shadow 验证的冻结候选。

特点：

* 不再继续改 alpha 逻辑
* 使用固定版本、固定规则、固定配置
* 开始接受 live-like 路径验证

---

## 4. Promote Philosophy

Research → Paper promote 的核心哲学：

### 4.1 Promote 的对象不是"最会回测的策略"

而是：

> **最值得在真实时间顺序下继续验证的冻结候选。**

### 4.2 Promote 不奖励复杂度

高复杂度、低可解释性、弱鲁棒性的候选，即使离线结果好看，也不应优先进入 paper。

### 4.3 Promote 不等于上线准备完成

进入 paper 只是说明：

* 值得花 live-like 验证成本
* 不是已经 ready for production

### 4.4 Promote 的本质是资源分配

paper validation 比 research 更昂贵、更慢、更强调稳定运行，因此进入 paper 的数量必须受控。

---

## 5. Promote Eligibility

只有满足以下前提，Research Prototype 才能申请进入 promote 评估：

### 5.1 候选类型

允许申请 promote 的候选包括：

* single-factor strategy candidate
* research composite candidate
* tactical sleeve candidate
* overlay-aware candidate

不允许直接申请的对象：

* 仍在大幅改动中的 prototype
* 仅有单次回测亮点、缺少完整证据链的想法
* 缺少明确 spec / config / artifact 的临时实验结果

### 5.2 版本冻结前提

必须存在明确、冻结的：

* feature list
* transforms / normalization rules
* labels / mask convention
* weighting logic
* rebalance schedule
* benchmark definition
* cost model version
* overlay / risk rules

如果这些仍在变动，则不得进入 promote 评估。

---

## 6. 必备输入（Promote Input Package）

每个申请进入 paper 的候选，必须提交完整的 Promote Input Package。

### 6.1 Strategy Spec

* candidate id
* strategy version
* feature set
* transforms
* weighting / ranking rules
* rebalance frequency
* benchmark definition
* universe definition
* risk / overlay configuration

### 6.2 Research Evidence

* in-sample / OOS / holdout summary
* benchmark-relative summary
* regime-stratified report
* turnover / cost proxy summary
* concentration / exposure summary
* robustness summary

### 6.3 Engineering Readiness

* panel generation status
* data dependency list
* mask behavior summary
* known assumptions / known limitations
* reproducibility check

### 6.4 Decision Memo

* candidate 的经济逻辑
* 为什么值得进入 paper
* 当前最大风险点是什么
* 哪些问题需要 paper 层验证，而不是继续留在 research

---

## 7. Promote Criteria

要从 Research Candidate 进入 Paper Candidate，至少需要同时满足以下四类标准。

## 7.1 表现标准（Performance Criteria）

### A. OOS / Holdout

* OOS 指标达到预设下限
* holdout 不得完全失真
* 结果不能只依赖单一时间窗

### B. Benchmark-relative

* 对 SPY / QQQ 的超额收益或风险调整后表现具备基本说服力
* 不得只是 beta 放大带来的表面胜利

### C. Full-period consistency

* full-period 表现不得与 OOS/holdout 严重背离
* 不允许出现"只有 holdout 好看，但全周期非常薄"的候选直接进入 paper

---

## 7.2 鲁棒性标准（Robustness Criteria）

### A. Cost / Turnover

* cost proxy 不得明显失控
* turnover 不得高到使 paper 验证失去现实意义

### B. Regime behavior

* 在 bull / bear / crash / recovery 等关键 regime 下行为可解释
* 不得出现明显"只在单一 regime 有效"的伪 alpha

### C. Parameter sensitivity

* 小范围参数变化不应导致结果完全翻转
* 候选不应依赖脆弱的单点调参

### D. Concentration

* 不得由极少数 symbol / 极少数日期完全驱动
* concentration 风险必须可量化、可解释

---

## 7.3 可解释性标准（Interpretability Criteria）

### A. Economic logic

必须能够说明：

* 该信号背后的市场行为逻辑
* 为什么它可能在未来仍然有效
* 为什么它不是纯粹数据挖掘产物

### B. Role clarity

必须明确：

* 它属于 slow core / fast tactical / overlay 哪一层
* 它是在替代现有策略，还是作为新 sleeve / supplement

### C. Failure mode clarity

必须明确：

* 它最可能在哪些环境失效
* 进入 paper 后最应该观察哪些 live-like 指标

---

## 7.4 工程可运行性标准（Operational Readiness Criteria）

### A. Reproducibility

* 候选结果可以复现
* spec 与 artifact 一致
* 数据输入与版本明确

### B. Data stability

* panel 稳定可生成
* mask / label / benchmark 对齐稳定
* 不依赖人工临时修补

### C. Freezeability

* 能够冻结成一个固定版本进入 paper
* 不需要边跑 paper 边继续改 alpha 逻辑

### D. Artifact completeness

* 所需 artifact 完整存在
* 可供 reviewer 独立检查

---

## 8. Hard Blocks（直接阻断条件）

满足以下任一条件，直接不得 promote 到 paper：

1. OOS / holdout 明显不过线
2. benchmark-relative 表现仅靠风险暴露放大
3. cost_robust / stress / regime 行为明显失败
4. spec 尚未冻结
5. 缺少关键 artifact
6. panel / data / mask / benchmark 对齐不稳定
7. 结果主要来自单段时间、单一 symbol、单一事件窗口
8. 候选逻辑本身仍在频繁改动

---

## 9. Decision Outcomes

Promote 评审不只有 pass / fail 两种结果，而应有三种。

### Outcome A：Promote to Paper

满足进入 shadow/paper 的要求。

结果：

* `S1 -> S2`
* 生成 frozen paper candidate package
* 进入 paper 队列

### Outcome B：Hold in Research

候选有价值，但还不足以进入 paper。

适用情形：

* 还有一两个关键 blocker 可在 research 内解决
* 结果有潜力，但 spec 尚未完全冻结
* robustness 还需补证据

结果：

* 维持在 `S1`
* 列出必须补的 research items

### Outcome C：Reject / Demote

当前不值得继续投入 paper 资源。

结果：

* 回到 `S0` 或进入 `S5`
* 记录 reject 原因
* 不进入 paper 队列

---

## 10. Promote Review Process

### Step 1：提交 Promote Input Package

候选 owner 提交完整 artifact 与 decision memo。

### Step 2：Research Review

检查：

* spec 是否冻结
* artifact 是否完整
* benchmark-relative / robustness 是否达标

### Step 3：Promote Decision

输出：

* Promote / Hold / Reject
* supporting reasons
* next actions

### Step 4：若 Promote，通过 Frozen Package 进入 Paper

生成：

* frozen strategy package
* paper candidate id
* paper validation checklist

---

## 11. Frozen Paper Package Definition

一旦 promote 成功，必须生成 Frozen Paper Package。

内容至少包括：

* strategy version
* feature list
* transforms
* mask rules
* benchmark rules
* rebalance rules
* weighting rules
* risk / overlay rules
* cost model version
* promote decision memo
* linked research artifacts

Frozen Paper Package 的含义是：

> 进入 paper 后，不再修改 alpha 逻辑本体；paper 层只验证，不继续研究搜索。

---

## 12. Demote / Revoke Before Paper

即使已经成为 Research Candidate，在真正进入 paper 前，如果发现以下问题，也应撤销 promote 资格：

* 新发现数据对齐问题
* candidate 无法稳定复现
* benchmark-relative 结论被修订
* cost / stress 结论被修订
* spec 冻结后发现逻辑不可运行

这类情况应记录为：

* `promote_revoked`
* 原因
* 影响范围
* 后续处理建议

---

## 13. Required Artifacts

Research → Paper promote 至少需要以下 artifact：

### Core artifacts

* candidate spec / YAML / JSON
* research acceptance pack
* OOS / holdout report
* benchmark-relative report
* regime-stratified report
* cost / turnover summary
* concentration / exposure summary
* decision memo

### Optional but recommended

* feature-family contribution summary
* orthogonalization report
* failure mode memo
* reviewer notes

---

## 14. Governance Principles

### 14.1 Promote 不是自动化默认动作

即使满足阈值，也不建议完全自动 promote 到 paper。

### 14.2 数量必须受控

进入 paper 的 candidate 应该少而精。

### 14.3 候选必须可审计

没有 artifact 的 candidate，不得进入 paper。

### 14.4 不允许"边 paper 边重写策略"

paper 是验证层，不是继续 search 的地方。

---

## 15. Success Criteria

这份标准落地成功，意味着：

1. Research Candidate 与一般 prototype 被清楚区分
2. 进入 paper 的门槛明确，不再靠主观感觉
3. 每个 paper candidate 都有冻结版本与完整 artifact
4. paper 层的资源可以集中在真正值得验证的候选上

---

## 16. One-Sentence Summary

**Research → Paper promote 的本质，不是"奖励一个好回测"，而是挑出那些已经冻结、可解释、较鲁棒、且值得花 live-like 成本继续验证的研究候选。**
