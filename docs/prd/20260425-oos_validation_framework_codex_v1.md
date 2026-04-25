# Post-Data-Integrity OOS Validation Framework — Codex PRD v1

**Author**: Codex
**Date**: 2026-04-25
**Version**: Draft v1
**Status**: under review (Claude + Codex via bridge)

---

## 背景

当前 data-integrity round-3 已完成。仓库已经完成：

- canonical daily store 重建
- 4 个 paper cells 在新数据上仍保持 drift = 0.00 bps
- baseline 与 headline 文档已刷新

但历史 NAV 被大幅重估，尤其 2022 Cand-2 从 +74.57% 重估到 +3.47%，
这说明旧的历史收益叙事曾被数据问题显著放大。

这带来一个很清楚的结论：

**现在最值得做的，不是继续扩研究空间，而是建立一个真正可信的 OOS
（out-of-sample）验证框架。**

---

## 1. 问题定义

当前仓库已经解决了两类大问题：

第一类是**数据完整性问题**。现在 daily 数据源已经统一，paper/replay
parity 也已经恢复到可审计状态。

第二类是**实现一致性问题**。M11/M14 后，4 个 canonical paper cells 的
drift 已经归零，说明当前历史 replay 的内部一致性已经成立。

但第三类问题仍然没有解决：

### 1.1 当前历史结果不是 OOS

当前 2022/2024 这两组 canonical paper windows，本质上仍然是：

- frozen spec 对 historically seen windows 的 replay
- 不是 forward OOS
- 也不是 candidate-specific holdout OOS

所以它们可以支持：候选画像 / 候选正交性 / baseline vs tactical 分工 /
实现一致性。

但**不能直接支持**：未来收益预期 / 可部署 alpha 大小 / production
ranking 结论。

### 1.2 候选治理缺少真正的 OOS gate

现在 candidate 的推进仍然缺少：candidate-level holdout / forward
OOS contract / concentration hard gate / watch-list/thin-data 暴露
的强制报告。

### 1.3 数据清干净后，最容易犯的错是"在更干净的数据上再过拟合一次"

如果现在直接解冻 universe extension / new mining / Candidate-3 /
new factor family，那么风险不是"找不到 alpha"，而是：**在更可信的
数据上，重新做一轮更高级的 in-sample 叙事。**

---

## 2. 目标

本 PRD 的目标不是提升回测收益，而是建立一个：

**能区分"历史上看起来不错"和"未来真钱里仍然有机会"的验证系统。**

具体目标 5 个：

- **G1**: 建立 candidate-level holdout OOS（不是 factor-level IC fold）
- **G2**: 建立真正的 forward OOS / forward paper 评估框架
- **G3**: 把 M12 concentration gate 从"注释"变成"硬门槛"
- **G4**: 把 watch-list / thin-data / quarantined exposure 并入主报告
- **G5**: 升级 candidate lifecycle，让 promote/stay/demote/revoke 与
  OOS 结果绑定

---

## 3. 非目标（明确不做）

universe extension / new mining round / Candidate-3 / new data tier /
frozen spec 改动 / new PRODUCTION_FACTORS / 重新定义当前两个 candidate
本身。

这些继续冻结。当前 round-3 close 里也明确写了：universe / mining /
Candidate-3 / new data tier / spec changes / new PRODUCTION_FACTORS /
OOS framework 原本都被冻结；现在的建议是只解冻 OOS framework，其余
继续冻结。

---

## 4. 设计原则

- **4.1 先验证，再研究**：先建立 OOS 框架，再考虑重新解冻研究面
- **4.2 以 candidate 为单位，不以单因子为单位**：walk-forward IC 不
  能替代 candidate-level NAV OOS
- **4.3 风险口径与收益口径并重**：同时回答赚多少 / 怎么赚 / 是否
  过度集中 / 是否依赖 thin-data / 是否有 implementability 问题
- **4.4 一切判断都要有 artifact**：可追溯到 spec / holdout manifest
  / forward manifest / checkpoint memo / concentration report /
  watch exposure report / promote/demote/revoke record

---

## 5. 当前前提（作为本 PRD 的输入）

- **5.1 数据层已足够稳定**：data/daily/*.parquet 重建，78 个写入，
  1 个 dropped (BRK-B)，0 个 Sat/Sun rows，two-level N_min coverage
- **5.2 实现一致性已足够稳定**：4 个 paper cells drift = 0.00 bps；
  M11 parity 在新数据上仍成立
- **5.3 旧收益叙事已被重估**：2022 Cand-2 +74.57% → +3.47%；
  2022 RCMv1 现在不低于 Cand-2；2024 Cand-2 +35.27% → +10.95%；
  2024 RCMv1 +9.83% → +4.44%

---

## 6. 方案范围

### 模块 A：Candidate-Level Holdout OOS

**目标**：对每个 frozen candidate，定义一段构建时明确不允许看的
holdout 历史窗口。

**问题**：当前 replay 的问题不是"算错了"，而是"看过了"。所以必须
新增 train_window / selection_window / holdout_window，并保证
holdout 不参与候选构建/调权/rule选择/rank ordering。

**交付物**：candidate_holdout_spec.yaml / holdout_eval.json /
holdout_eval.md

**最低要求**：第一批只对 rcm_v1_defensive_composite_01 +
candidate_2_orthogonal_01 建。

### 模块 B：Forward OOS / Forward Paper

**目标**：定义真正的 frozen-date 之后的 forward 验证。

**约束**：每个 candidate 进 forward 前必须冻结 spec / benchmark /
turnover/cost assumptions / promote/demote/revoke criteria /
checkpoint cadence。

**检查节奏**：10 TD operational sanity / 20 TD early behavior /
40 TD role stability / 60 TD first decision checkpoint。

**交付物**：forward_run_manifest.json / forward_checkpoint_{10,20,40,60}d.md

### 模块 C：M12 Concentration Gate 硬化

**目标**：从"未来再做"变成真正阻断或警告候选推进的规则。

**必须覆盖维度**：top-1/top-3/top-5 concentration / name-days
concentration / sector concentration / benchmark beta concentration /
watch-list names concentration / thin-data exposure concentration。

**结果类型**：pass / pass_with_warning / block / manual_review。

**交付物**：concentration_report.json / concentration_gate_result.md

### 模块 D：Watch-List / Thin-Data Exposure Integration

**目标**：让主报告直接显示 thin-data exposure / quarantined names
exposure / dropped names exposure / watch-list contribution。

**原因**：round-3 已建立 thin_data / quarantine / unsupported；
follow-up parking lot 提到 watch-list sidecar 集成。但这些信息还
没真正进入 master report / drift report / checkpoint summary /
acceptance pack。

**交付物**：watch_exposure_summary.json + 在上述 4 报告中加
section。

### 模块 E：Candidate Lifecycle 升级

**目标**：把当前 candidate 状态机升级到 OOS-ready 版本。

**建议状态**：S0_research_proto / S1_frozen_candidate /
S2_holdout_candidate / S3_forward_paper_candidate /
S4_oos_validated_candidate / S5_revoked。

**含义**：以后 candidate 不能只凭 research replay / factor IC /
narrative memo 就被当作"可部署结论"。它至少要经过 holdout /
forward paper / concentration gate / watch-quality 口径。

---

## 7. 推荐执行顺序

- **Step 1**: 先定义 contract — holdout schema / forward schema /
  checkpoint schema / registry 新状态
- **Step 2**: 先做 holdout runner — 最便宜、最快能落地
- **Step 3**: 同时做 M12 + watch-exposure integration — 收益解释
  升级为可部署解释的必要层
- **Step 4**: 做 forward runner + checkpoint pipeline — 最重，放
  后面
- **Step 5**: 升级 lifecycle / decision logic — 等 artifacts 都
  出来再硬接进去

---

## 8. 第一批接入对象

只接入 rcm_v1_defensive_composite_01 和 candidate_2_orthogonal_01。

---

## 9. 验收标准

### 9.1 框架级验收

- candidate 可以生成标准化 holdout / forward artifact
- M12 concentration gate 可执行
- watch-list / thin-data exposure 进入主报告
- registry 可表达新生命周期

### 9.2 治理级验收

- 所有 non-OOS historical replay 自动被标为 non-OOS
- 不允许把 historically seen window replay 写成 deployable evidence
- promote / demote / revoke 有标准输入

### 9.3 操作级验收

- RCMv1 和 Cand-2 两个候选都能完整跑通新流程
- 不破坏当前 registry / 不破坏 round-3 数据基线 / 不重新解冻
  mining / universe

---

## 10. 风险与注意事项

- **风险 1**: 做 OOS framework 时容易顺手改 spec — 本 PRD 禁止
- **风险 2**: 做 holdout 时容易把 factor-level fold 当成
  candidate-level OOS — 本 PRD 明确禁止
- **风险 3**: 做 forward runner 时容易跳过 concentration / watch-
  quality — 本 PRD 要求同步并入
- **风险 4**: 框架做好后，可能发现当前两个 candidate 的"可部署性"
  比想象弱 — **这不是失败，而是本 PRD 的价值所在**

---

## 11. 冻结与解冻规则

- **本 PRD 完成前**：universe extension / new mining / Candidate-3
  / new data tier / spec changes / new PRODUCTION_FACTORS 继续冻结
- **解冻条件**：OOS framework 已落地 / 至少一个 candidate 跑通
  holdout + concentration + watch-quality + first forward
  checkpoint / forward 反馈开始出现 / 报告口径已经从 replay
  narrative 升级为 OOS narrative

---

## 12. MVP（最小实现版本）

### MVP 范围

- candidate-level holdout schema
- holdout runner
- M12 concentration gate
- watch exposure section in reports
- registry 增加 S2_holdout_candidate

### 不在 MVP 内

- 完整 forward pipeline / 所有 checkpoint 自动化 / 完整
  demote/revoke 规则升级

也就是说，先把"不是 OOS 的东西，不能再被当 OOS 读"这件事彻底制度化。

---

## 拍板建议（codex）

如果你问我：从"最终在美股量化里实现长期盈利"这个目标看，round-3
之后最值得做的是什么？

我的答案不变：**不是继续研究 alpha，而是先建立一个 honest OOS
framework**。

因为你现在最缺的，不是新的策略想法，而是一个系统，让你能分得清：
什么是历史上看起来不错 / 什么才值得你未来真钱继续押。
