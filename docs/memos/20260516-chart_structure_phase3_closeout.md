# Chart-structure 输入表征层 —— Phase 3 closeout

**日期**: 2026-05-16
**Lineage**: `chart-structure-input-repr-2026-05-15`
**主 PRD**: `docs/prd/20260515-chart_structure_input_representation_prd.md` §5
**execution PRD**: `docs/prd/20260515-chart_structure_ralph_loop_execution_prd.md` §7
**loop log**: `docs/memos/20260515-chart_structure_loop_log.md`(P3·R1-R5)
**termination promise**: `CHARTSTRUCT-P3-DONE`

---

## §1 Phase 3 做了什么(大白话)

Phase 1/2A 证明手工 swing 特征对模型没有显著增量;Phase 2B 把表征轴
做厚(MiniROCKET / TS2Vec)。Phase 3 是**最后一问**:抛开因子表格,直接
让模型「看图」—— 三个 chart-native 模型,在裁判(同一 within-train
fit/OOS 协议 + 126d 动量基线 + 配对 t 检验 + 真实成本/换手)下,看能否
打过「最简单的一个表格因子」。

5 个 round:3 个 build(建模型)+ 2 个 experiment(真跑 attempt):

- **P3·R1** build —— 3B `StructureSequenceEncoder`(swing 段序列 →
  SmallEncoder)。
- **P3·R2** experiment —— 3B attempt:OOS IC 0.0153,**显著低于**动量
  0.0847(p≈0)。
- **P3·R3** build —— 3A `ChartCNN`(GASF+GADF 图 → CNN)。
- **P3·R4** experiment —— 3A attempt:第一次跑抓到 ChartCNN
  undersizing bug(4977 参数,train loss 几乎不降),**扩容到 ~58k 参数
  后真拟合了 train(loss 1.00→0.35)**;OOS IC 0.0319,**显著低于**
  动量 0.0918(p=0.012)。
- **P3·R5** build + closeout —— 3C `FusionModel`(3B 段序列分支 + 3A
  GAF 图分支,late-fusion MLP)+ 本 closeout。3C attempt:OOS IC
  0.0415,**与动量 0.0856 无显著差异**(p=0.069)。

## §2 三个 chart-native attempt —— 都跑了,都诚实记录

| attempt | 模型 | 表征 | verdict | scope |
|---|---|---|---|---|
| `3b_001` | StructureSequenceEncoder | family-T swing 段序列 | `underperforms_tabular_baseline` | config_scoped |
| `3a_001` | ChartCNN(58k,扩容后)| GASF+GADF 图像 | `underperforms_tabular_baseline` | config_scoped |
| `3c_001` | FusionModel(late 3B+3A)| 段序列 + GAF 图融合 | `no_significant_increment` | config_scoped |

每个 attempt 一份 `data/audit/chart_structure/phase3_attempt_<id>.json`,
schema 校验过,失败 attempt 带 substantive `root_cause`,verdict_scope
恒为 `config_scoped`(`global` 被 schema 硬禁)。

## §3 vs tabular baseline 数值块(P3-A4)

裁判:within-train fit/OOS **年块**切分 + **P3-A3 fit→OOS 年边界 purge
embargo**(fit = train 年去掉 OOS;OOS = 2017+2024,validation
2018/19/21/23/25 + sealed 2026 **从未读**)。指标:每个 OOS 日截面
Spearman rank-IC vs 21d close-to-close 远期收益;配对 t 检验(同 OOS
日,模型 IC − 动量 IC)。成本:30bp/side,换手单独报。

> **数值已 P3-A3 purged 重跑(2026-05-16 audit)**。原始非 purged 数值
> (3B 0.0153 / 3A 0.0319 / 3C 0.0415)见本 commit 历史;purge 后:

| 模型 | OOS rank-IC | 基线 mom_126d IC | vs baseline | paired t | p | 换手 / 成本拖累 | n_OOS_dates | train loss |
|---|---|---|---|---|---|---|---|---|
| 3B `3b_001` | **0.0091** | 0.0847 | **−0.0756** | −5.72 | ≈0.000 | 0.560 / ~2.02%/yr | 503 | 0.996→0.65 |
| 3A `3a_001` | **0.0219** | 0.0918 | **−0.0700** | −2.82 | 0.005 | 0.570 / ~2.05%/yr | 167 | 1.002→0.37 |
| 3C `3c_001` | **0.0517** | 0.0856 | **−0.0339** | −1.35 | 0.177 | 0.768 / ~2.76%/yr | 167 | 0.999→0.81 |

**purge 后负结论全部 robust**:3C(0.0517)> 3A(0.0219)> 3B(0.0091)
—— late fusion 仍是三者里 IC 最高的 chart-native 表征,但三个都没打过
**单个**动量表格因子(0.085-0.092)。3A/3B 的负 verdict 在 purge 后
**更强**(IC 进一步下降:泄漏本在抬高输家,去掉后掉下来——印证
audit §5.2);3C 仍 `no_significant_increment`(p=0.177,比非 purged
的 0.069 更不显著,即 purge 后 3C 离基线**更远**,绝无「接近基线」可
言)。注:三次 run 的基线 IC 略有差异(0.085-0.092)是样本装配不同
(3B 不抽样;3A/3C date_stride=3;3C 还需 seg+img 同时有效),每行用
各自 run 的基线做配对,比较自洽。

**underfit 诚实交代**:3A train MSE 1.00→0.37、3B 1.00→0.65(均真
拟合 train);**3C purged 这次 train MSE 0.999→0.808**,刚过 0.80
underfit 阈值 —— FusionModel 两分支端到端训练对 seed/init 敏感,本次
拟合不充分,attempt JSON 已带 underfit confound note(诚实记录)。但
跨「非 purged 拟合好(IC 0.041 p 0.069)」与「purged 拟合不足(IC
0.052 p 0.177)」两次,3C verdict 稳定为 `no_significant_increment`
/ 不打过动量 —— 负结论对 purge **和** 训练充分度都 robust。

## §4 root cause —— 为什么 chart-native 没赢(无 blanket verdict)

三个负/平结果指向**同一根因**,且与 Phase 2A family-T 冗余发现一致:

> swing 段序列(3B)、GAF 图(3A)、以及两者的 late fusion(3C),都是
> **同一段价格窗口的确定性再编码**。动量因子(126d trailing return)已经
>把这段窗口的趋势信息压缩好了;chart-native 模型在更高维空间重新表达同一
> 信息,没有引入动量未捕获的正交截面 rank 信号。3C late fusion 只是把两个
> 已被动量主导的分支分数重新加权,无正交信号可融。

这是 **config-scoped** 结论,**不是** blanket「CNN/chart-native 不行」
(D2 纪律 + 个人记忆 `feedback_no_blanket_failure_verdict`)。明确记录
本轮用了什么、没试什么:
- **试过**:79-universe(ex-SPY/QQQ)、within-train fit/OOS、21d horizon、
  GASF+GADF window=63、段序列 max_segments=16、late-fusion 端到端训练、
  80 epoch。
- **没试(下一轮 evidence-gated 候选,非本 loop scope)**:328 expanded
  universe(Phase 4 已 ship,IC 检验未在其上重做)、更深 CNN / 更长训练、
  early fusion(branch feature 级而非 score 级)、frozen-branch + 只训
  fusion MLP、用 chart-native 当 ensemble 成员(主 PRD §5.2:目的是
  ensemble 候选而非单独打败动量)、TS2Vec 预训练 embedding 作分支。
- 3A·R4 抓到并修正的 sizing bug 是本 Phase 方法论收益:experiment round
  的负结果先排除 underfit confound 才能 root-cause(D2)。

## §5 Acceptance —— Phase 3

| AC | 判据 | 结果 |
|---|---|---|
| P3-A1 | 每 attempt 有 `phase3_attempt_<id>.json` 字段完整 + schema 单测 | ✅ 3 份 JSON;`test_phase3_attempt.py` 11 单测(含字面命名 `test_phase3_attempt_schema` + 3b/3a/3c 各 1)green |
| P3-A2 | 失败 attempt 有 root_cause;closeout 无 blanket verdict | ✅ schema 强制(`_negative_needs_root_cause`);本 closeout §4 config-scoped,人工复核无 blanket |
| P3-A3 | eval 走 purged + 真实成本 + 换手惩罚;eval 函数有 purge 单测 | ✅ **(audit 2026-05-16 收口)** `core/ml/phase3_eval.purged_fit_mask` 年边界 embargo + `test_phase3_eval.py` 3 单测 green;3 attempt 全 purged 重跑;每 JSON `eval_method`/`cost_model`/`turnover_penalty` 必填 |
| P3-A4 | chart-native vs tabular baseline 数值块报出 | ✅ 本 closeout §3 三模型 IC + 基线 + paired t/p + 换手/成本表 |
| P3-A5 | 3B 训练数据用因果 swing 段序列 | ✅ `segment_sequence_asof` 走 `confirmed_swings_asof`;`test_phase3b_uses_confirmed_swings` 硬验 |

模块:`core/ml/{structure_sequence_encoder,chart_cnn,fusion_model}.py`。
runner:`dev/scripts/chart_structure/phase3_run_{3b,3a,3c}_attempt.py`。
artifact:`data/audit/chart_structure/phase3_attempt_{3b,3a,3c}_001.json`。
单测:fusion 3 + phase3_attempt schema 10 + chart_cnn 6 + structure_seq
encoder 因果测 = 全量套件 green(§2.3 G1)。

## §6 已知 caveat

- IC 检验在 **79-universe** 上做,Phase 4 已 ship 的 328 expanded
  universe 上**未重做**。Phase 2A 负结果根因之一就是「票池小 + 老因子
  吃饱趋势信息」;在 expanded universe 重做 chart-native IC 检验是
  evidence-gated 后续任务(算力 + 用户授权),不是本 loop scope。
- 评估是 within-train **年块** fit/OOS(fit 年 vs 不相交 OOS 年
  2017/2024)+ **P3-A3 fit→OOS 年边界 purge embargo**(2026-05-16
  audit 收口:`purged_fit_mask` 去掉 21d label 越界进 OOS 年的 fit
  样本;3 attempt 全 purged 重跑,负结论 robust)。仍非**滚动** purged
  WF —— 滚动 WF 是更重的后续 scope,当前年块+边界 embargo 已消除已识别
  的 train→OOS 泄漏路径。
- chart-native 的主 PRD 定位是 **ensemble 候选**(§5.2),不是要求单独
  打败动量;「未单独打败动量」**不否决** ensemble 用途。是否进 ensemble
  是后续独立决策,需用户授权,不在本 loop。
- 3C 换手 0.893 / 成本拖累 ~3.21%/yr 高于 3B/3A —— 即便 IC 追平基线,
  净成本后也不占优。这是把 chart-native 当独立信号的额外不利证据
  (当 ensemble 成员时换手可被组合层平滑,另议)。

## §7 下一步

Phase 3 = 本 chart-structure ralph-loop **最后一个 Phase**。P1 / P2A /
P2B / P4 closeout 均已发(`docs/memos/20260515-chart_structure_phase{1,
2a,2b,4}_closeout.md`);本 closeout 发 `CHARTSTRUCT-P3-DONE` 后,
4 个 Phase 全 closeout → 发 `CHARTSTRUCTUREDONE`。

战略读数(诚实):chart-structure 输入表征层从 swing 手工特征 → 自监督
表示 → chart-native 端到端模型,**三层都没在 79-universe 上对动量基线
产生显著正交增量**,根因一致(价格窗口再编码冗余)。这是一个**有价值
的负结果**:它把「chart 图能否给 ML mining 上游补 alpha」这个问题在
当前 universe/protocol 下证伪到 config-scoped 程度,并明确了唯一未被
证伪的开口 = expanded-universe 重检 + ensemble 角色,二者均 evidence-
gated + 需用户授权,不在本 loop 自动展开。

**`CHARTSTRUCT-P3-DONE`**.

**`CHARTSTRUCTUREDONE`** —— 4 Phase 全 closeout,chart-structure
输入表征层 ralph-loop 终止。
