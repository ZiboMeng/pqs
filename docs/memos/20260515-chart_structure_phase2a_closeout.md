# Chart-structure 输入表征层 —— Phase 2A closeout

**日期**: 2026-05-15
**Lineage**: `chart-structure-input-repr-2026-05-15`
**execution PRD**: `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md` §5
**loop log**: `docs/memos/20260515-chart_structure_loop_log.md`(P2A·R1/R2)
**termination promise**: `CHARTSTRUCT-P2A-DONE`

---

## §1 Phase 2A 做了什么(大白话)

Phase 2A 回答一个问题:**Phase 1 造的 12 个 swing 段结构特征(family T),
加进 ML 输入后,到底有没有让模型多预测对一点?**

做法 —— 配对实验:
- **对照组**:101 个现有因子(RESEARCH_FACTORS 去掉 12 个 swing 特征)。
- **实验组**:101 个 + 12 个 swing 特征 = 113 个。
- 两组喂同一个 ML 模型(Phase 1.6 的 rank:ndcg XGBoost)、同样的
  时间切分、同样的随机种子 —— **唯一区别就是那 12 列**。
- 量度:每年的 OOS Rank IC(模型打分和真实未来收益的横截面相关性)。
- 对 17 年的「实验组 IC − 对照组 IC」做配对 t 检验。
- swing 窗口长度 K 扫了 {6, 8, 12} 三个值。

## §2 结果 —— 没有显著增量(诚实交代)

| K | 平均 ΔIC | p 值 | 95% CI | 裁决 |
|---|---|---|---|---|
| 6 | **+0.0075** | 0.078 | [−0.0010, +0.0160] | 不显著(最接近)|
| 8 | +0.0029 | 0.54 | [−0.0070, +0.0129] | 不显著 |
| 12 | +0.0030 | 0.38 | [−0.0041, +0.0102] | 不显著 |

**三个 K 全部 p > 0.05** —— family T 这 12 个特征,在当前构造下,**没有
给模型带来统计显著的增量预测力**。

注意:三个 K 的平均 ΔIC **都是正的**(没有变差),K=6 接近显著
(p=0.078)。所以不是「结构信息完全没用」,而是「这一版 12 特征 + 这个
模型 config + 21 天 horizon,增量信号弱到统计上分不出来」。

## §3 root-cause(为什么弱)—— 操作员分析

**最可能的原因:family T 与对照组里已有的因子高度冗余。** 对照组那 101
个因子里**已经包含** Family R(图形形态:Donchian 突破、均线交叉、连涨
等)+ Family D(趋势质量)+ 各种动量因子。swing 段结构(段长比、斜率比、
趋势成熟度…)本质上和「趋势 / 形态」是同一类信息 —— 模型从那 101 个因子
里已经把大部分趋势结构信号学到了,再加 12 个 swing 特征,**能贡献的「新」
信息所剩不多**。

次要观察:
- K=6(更短窗口、更近的结构)最接近显著 —— 说明结构信息faint 地存在,
  且偏短周期。
- `tol` / `maturity_cap` 是 PLACEHOLDER(无标定)—— 特征本身可能带噪声。
- 21 天 horizon —— 主 PRD §10 q1 早已标注 horizon 是变量。

## §4 这不终止 loop(D2 + execution PRD §2.2)

负结果的 experiment round **仍 PASS**(实验跑了、报告产出、verdict
config-scoped 记录)。verdict **严格 config-scoped**:写的是「这一版
12 特征 + rank:ndcg + 21d horizon 无显著增量」,**不是**「结构信息没用」
的 blanket verdict(D2 禁此)。

按 execution PRD §2.2:Phase 2B(bridge + embedding)是**独立的表示轴**,
照常 fire —— MiniROCKET / shapelet / TS2Vec embedding 是和「手工 swing
段特征」不同的结构表示方式,Phase 2A 的负结果不预判它们。

**family T 未被废弃** —— 模块、因子、注册全部保留(留在 RESEARCH_FACTORS
由漏斗长期裁判)。未来可迭代方向(非本 loop 阻塞项):换 horizon、
标定 tol/maturity_cap、或重设计与现有趋势因子**不冗余**的结构特征。

## §5 Acceptance —— P2A

| AC | 判据 | 结果 |
|---|---|---|
| P2-A1 | 配对检验报 mean/std/p/CI + treatment 仅差 12 列 | ✅ 报告 4 字段齐全;`col_diff_is_family_t=true`(B3)|
| P2-A2 | 结论 config-scoped | ✅ `verdict_scope=config_scoped` + verdict 措辞 config-scoped |

报告:`data/audit/chart_structure/phase2a_incremental_ic.json`。
schema 校验:`tests/unit/chart_structure/test_phase2a_report.py`。

## §6 下一步

`CHARTSTRUCT-P2A-DONE`。Phase 2B fire(bridge 表示层 + 自监督 embedding)。

**`CHARTSTRUCT-P2A-DONE`**.
