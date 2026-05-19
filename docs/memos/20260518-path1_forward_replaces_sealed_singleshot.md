# 决策 memo —— 路 1:Forward 观察取代 sealed 历史单发(标准纪律变更)

**日期**: 2026-05-18
**授权**: 用户 explicit-go 2026-05-18 "按路1落实 Track-A 过的直接
promote forward"。
**性质**: 标准纪律变更(directional,用户拍板),前向生效。
**纪律**: `feedback_audit_surfaces_not_thorough`(决策 fold 进文档非
口头)、`feedback_no_blanket_failure_verdict`、`feedback_decision_
authority_operator_audit_split`(directional 由用户定)。

---

## §1 决策

**Track-A acceptance(train/validation)通过的候选 → 直接 promote 进
forward 实时观察**(走现有 v2.1.3 哈希 / fail-closed revalidate /
attention_report 有纪律记录通路)。**取消"sealed 历史单发"作为晋升
前置 gate**。

## §2 为什么(sealed 的目的 + 为何 forward 可替代)

sealed 历史窗 = 研究流程从没碰过的一段数据,最终候选**只跑一次**,
当"最不带偏差的真不真体检",防"研究过拟合假象"。**它是检验工具非
发现工具**,设计上一次性(`sealed_ledger` B1 强制),用过即烧。

forward 观察 = **同一思想、用真实时间**:候选冻结后每一天都是真正
没见过的样本外。**取之不尽**(无"用完")、**免疫偷看**(看不到
明天)、但**慢**(几个月交易日)。

`alternating_regime_holdout_v1` 的 2026 单发已被 cycle06/08 消耗。
与其纠结"bump 新 sealed 窗"(2026 用完、2027 无数据),**路 1 直接
用真实 forward 观察替代该步** → "sealed-split-bump"这一长期挂起的
directional 问题**自然 dissolve**。

## §3 代价与为何可接受

- 代价:最终裁决变慢(forward 几个月 vs sealed 即时)。
- 可接受:forward 观察阶段是**观察/纸面、未投真实资金**(真实资金
  在更后的 gate);sealed 近路的主要价值是"快",而 forward 观察期
  不冒资金风险,**"慢但干净 + 取之不尽 + 防偷看"划算**。
- 仍保留 forward 自身的纪律(v2.1.3 4-scope 哈希、fail-closed
  revalidate、TD GREEN/YELLOW/RED、attention_report)——不是"随便
  看",是有纪律的记录式 OOS。

## §4 前向生效细则

1. **新 cycle pre-registration 模板**:去掉 sealed 单发步骤;
   `stop_rule` / promotion 路径改为 "Track-A pass → forward init"。
2. **sealed_ledger / sealed eval 脚本**:保留(历史 forensic +
   B1 fail-closed 仍防误用),但**不再是晋升必经 gate**;不主动
   bump 新 split 做新单发,除非未来用户另有 explicit-go。
3. **不影响**已 forward 的 cycle06/08/pead/trial9(它们当年走 sealed
   是历史事实,留痕不改)。
4. **不影响** cycle13b(0/3 Track-A FAIL + W7c/d CPCV gate FAIL +
   PBO 0.76 红旗 → 干净淘汰,本就无可 promote;与本决策无关)。

## §5 cycle13b 收口(本决策的首个适用情境)

cycle13b 3 个 top composite:Track-A FAIL(vs-SPY + covid -34%)+
**W7c/d CPCV binding gate FAIL**(ic_sw≈-0.002 / DSR≈0.001 / PBO
0.74-0.76 红旗)。三条独立证据一致 → **过拟合垃圾,淘汰**。
**方法论验证目的达成**:W7a HAC + W7b DSR/MinBTL + W7c/d CPCV/PBO
首次在真实 cycle 上端到端跑通并正确拦截过拟合候选 —— P0-B 实战
验证完成。**不 over-claim 为新策略;按路 1 = 淘汰,不需 sealed。**

**关联**: [[project-grand-audit-2026-05-18-two-p0]]
[[project-backtest-robustness-ml-redo-2026-05]]
[[feedback_temporal_split_discipline]]。
