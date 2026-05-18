# Supplementary PRD redo —— 收口 + 最终 audit

**日期**: 2026-05-16
**lineage**: `ml-method-redo-2026-05-16`
**PRD**: `docs/prd/20260516-ml_methodology_supplementary_prd.md`
**SoT**: `docs/memos/20260516-ml_methodology_literature_review.md`
**触发**: 用户 explicit-go「执行 PRD,R0/R1/R-P4ext 并行起步,一直到完成
不停确认,做好之后 audit」。
**纪律**: `feedback_audit_surfaces_not_thorough`(audit=暴露没做透+纠正
overclaim)、`feedback_temporal_split_discipline`、
`feedback_no_blanket_failure_verdict`、`feedback_self_audit_methodology`。

---

## §0 一句话结论(大白话)

> ⚠️ **边界更正(2026-05-17,LIVE)**:本 memo 全文出现的 DSR
> (0.999 / 0.558 / 0.9999 等)`n_trials` 均为 placeholder(非真实
> 试验数)→ **DSR 系统性偏乐观,不得当"已排除运气/选择偏差"引用**。
> 各 landmark 的稳健依据是 **IC 符号+幅度 / R2.5 的 C1 block-bootstrap
> clean p=0.0004**,均不依赖 DSR,结论不变。单一 SoT + 真实-N 重算
> 计划见 `docs/memos/20260517-dsr_placeholder_n_boundary_memo.md`。

**方法论确实是关键。** 按 literature-proven 路径重做后:
- **地基问题(结构信息有没有用)→ YES**:R2.5 在 literature-grade 预处理
  下 family-T **显著正增量(ΔIC +0.006)**,**directionally 推翻 P2A
  原"无显著增量"** —— P2A 的负结论是方法论假阴性(正是用户怀疑的)。
- **chart-native 模型单挑单动量因子 → 仍 underperform**(R4,见 §3),
  但 literature 路径比 Phase 3 naive 强很多,且 config-scoped、非 blanket
  —— 与 literature §5.2「chart-native 是 ensemble 候选,不是单挑 oracle」
  一致。
- 全程 sealed 2026 未读、train-only、负/正结论均不 over-claim。

---

## §1 8 个 R-phase 交付 + 验收(machine-checkable)

| Phase | AC | 结果(真跑)|
|---|---|---|
| R0 数据准备 | R0-A1..A5 | ✅ 6 单测;feature_prep(rank-norm/winsorize/sector-neutral-PIT/vol-scale/numpy-ADF frac-diff)+ survivorship audit(n=79 stale=0 → 结构性 survivorship,`as_of_rebuild_required=True`)|
| R1 label | R1-A1..A3 | ✅ 4 单测;concurrency 加权 + triple-barrier + 裸 21d 对照 |
| R2 验证 | R2-A1..A4 | ✅ 4 单测;CPCV C(N,k)/φ + purge/embargo + Deflated Sharpe/PBO + train-only fail-closed |
| R-P4ext universe | RP4-A1/A2/A5 | ✅ 3 单测;扫 25344 → 数据驱动 **1000** 选中(by train-window dollar-vol);resolver+`--universe expanded_v2` 传播 9 入口;executable/v1 bit-identical |
| R3 SSL 全量预训练 | R3-A1..A4 | ✅ 4 单测;MAE segment-mask + TS-only 增广;FULL 461716 train-only 窗口/5000步/loss 0.063→0.015;`is_full_pretrain=True`、`sealed_seen=False`;**.pt checkpoint 持久化(audit-fix,见 §4)**|
| R2.5 P2 地基复检 | R2.5-A1..A4 | ✅ **landmark:推翻 P2A**(§2)|
| R4 chart-native redo | R4-A1..A5 | ✅ 4 单测;§3(REAL pretrained-weight 重跑)|
| R5 ensemble | R5-A1..A2 | ✅ 2 单测;stacking CPCV-OOF + Ridge meta + 弱正交边际贡献(代码+单测;真实 base 端到端 eval = §4 deferred)|

G1 全量(R0-R3+R5 批):**3326 passed / 0 failed**。R4/R2.5 收尾 G1 见 §5。

---

## §2 R2.5 landmark —— P2A 假阴性被推翻

| | P2A 原始 | R2.5 literature-grade |
|---|---|---|
| 预处理 | 仅 apply_rank + 边界 purge | + winsorize + sector-neutral-PIT + vol-scale(R0)|
| family-T 增量 | "no significant increment" | **mean ΔIC +0.00596,paired-t +4.90,DSR 0.999** |
| verdict | 无增量 | **`family_T_significant_positive_increment`** |

**诚实 caveat(对正结论也不 over-claim)**:t/DSR 在 per-date ΔIC(n≈1911,
21d label 重叠)上算,自相关使显著性**被高估**(有效 N << 1911);稳健的
是**符号+幅度**(+0.006 稳定),clean p 需 CPCV-fold/block-bootstrap
(§4 deferred)。config-scoped(D2):此因子集+此 prep+21d+selector
panel,**非**"结构永远有 alpha"。**过程 bug**:首跑 ΔIC=exact 0 →
family-T 没真加进(`_build_panel` 返回 baseline-minus-swing)→ 审计纪律
exact-zero red-flag → 修(`_family_t_at_k` 建 family-T)。

---

## §3 R4 chart-native redo(REAL pretrained-weight,§4 audit-fix 后)

REAL pretrained-weight 重跑(27383 train-only 样本,15 CPCV folds,
mom_126d 为判官):

| arm | OOS rank-IC | 动量基线 IC | vs_base | DSR |
|---|---|---|---|---|
| gaf_tree | −0.0184 | 0.0382 | **−0.0566** | 0.002 |
| **mae_probe (REAL pretrained)** | **+0.0505** | 0.0382 | **+0.0123** | **0.558** |
| best = mae_probe → **verdict = `beats_tabular_baseline`** | | | | |

> ⚠️ **claim 更正(2026-05-18,审计 review)**:token
> `beats_tabular_baseline` 是**误名**——`vs_base` 实际 = `pred_IC −
> 单动量IC`(非强 tabular/GBDT baseline)。诚实读法 =
> **`beats_single_momentum_factor under current config`**,**不是**
> 打过 production-grade baseline。frozen forensic 脚本不 retro-edit
> (同 DSR placeholder-N 先例),更正以此为准。三层 claim 分类 + 强
> tabular 锚待建,见
> `docs/memos/20260518-auditor_claim_discipline_response.md`。

**第二个 landmark**:用**真 R3 预训练权重**(load `pretrain_mae.pt`),
SSL pretrain→probe 的 chart 表征 **打过单动量因子**(IC 0.050 > 0.038,
vs_base +0.012,DSR 0.558)。对照 audit-fix 前 fresh-init 版本:
mae_probe IC +0.015 / vs −0.023 / **underperform** —— **load 真预训练
权重把 verdict 从"输"翻成"赢"**。证明:(a) literature pretrain→probe
路径在 Phase 3 naive from-scratch 失败处有效;(b) **审计纪律自查
(fresh-init=架空)是 load-bearing**,不修就是第三个方法论假阴性。

**诚实 caveat(对正结论不 over-claim)**:DSR 0.558 = 中等(非
0.99),per-CPCV-fold(15)IC 比 R2.5 per-date 自相关轻;但仍是
**research 信号质量(probe IC)结论,非可部署候选**——没跑 Track A /
sealed / forward(漏斗未走);config-scoped(executable-79 / train-only
CPCV / 21d / 此 MAE config),**非**"chart-native 永远赢";gaf_tree 这条
路仍输(config-scoped);from-scratch CNN + expanded_v2 ~1k 仍 deferred
(§4)。可复现性依赖持久化的 `pretrain_mae.pt`(`checkpoint_saved=True`
记录;.pt 二进制不入 git,`run_full_pretrain.py` 可重生)。

旧 Phase3 `3a/3b/3c_001.json` 已标 `superseded_by=ml-method-redo-2026-05-16`。

---

## §4 Audit cross-walk —— 「做出来 vs 做透 vs deferred」(诚实,不 hand-wave)

| 项 | 状态 | 诚实定性 |
|---|---|---|
| R0/R1/R2/R-P4ext/R3-code/R5-code + 单测 | ✅ 做透 | G1 3326/0,真跑验证 |
| R3 full-pretrain | ✅ 做透(audit-fix 后)| 初版只存 loss-traj JSON **没存 .pt** → R4 mae 用 fresh-init = 架空 pretrain→probe;**审计纪律自查抓出**,修=持久化 .pt + R4 load 真权重重跑(§3)|
| R2.5 landmark | ✅ 结论稳健 / ⚠️ 显著性 | 符号+幅度稳健;t/DSR 被 label 重叠高估,clean p = block-bootstrap **deferred** |
| R4 from-scratch CNN/transformer 全重训 | ⏸ **deferred-compute** | literature 路径(GAF+tree / pretrain-probe)已做;from-scratch 全重训 + expanded_v2 ~1k 上重跑 = GPU-hours,config-scoped 记录,**非 blanket**(D2)|
| R5 ensemble eval RUN | ⚠️ 代码+单测做透,**真实 base 端到端 eval 未跑** | stacking 模块/marginal-contribution 单测过;用真实 chart-native+动量 base 跑 OOF-stack 的 number 是 deferred(R4 REAL 完成后才有 base)|
| R-P4ext survivorship | ⚠️ flagged 未 resolve | PIT first-trade-date 防 look-ahead;无 as-of 历史成分重建 → expanded_v2 仍 current-constituents,残留 survivorship,**显式 caveat 记录**(诚实,未假装解决)|
| expanded_v2 ~1k 上重跑全 pipeline | ⏸ deferred | universe 已建+全链路可达;在其上重跑 R2.5/R4 = 后续算力任务 |

**operator 自查纠正留痕**:本轮纠正了自己的 overclaim —— (a)「Phase 2A
不重做」(R2.5 推翻);(b) R4 初版「pretrain→probe」实为 fresh-init
(已修真权重)。符合 `feedback_audit_surfaces_not_thorough`。

---

## §5 收尾

- 全 8 R-phase code + 单测做透;R2.5 + R4 两个 landmark(均推翻先前
  方法论假阴性);R3 .pt 持久化 audit-fix 后 R4 用真权重。
- G1 全量收尾(R4-A 4 单测 + 全 redo 测 + 无回归)= 本 commit gate。
- commit 链(本会话 supplementary-PRD 段):`2727da8`(R0-R3+R5 build)
  → `783a905`(R2.5 landmark)→ 本 closeout commit(R4-real audit-fix
  + R4-A 测 + 本 memo)。

**未做透/deferred 全部显式列于 §4(R5 真实-base 端到端 eval / from-
scratch 全重训 / expanded_v2 ~1k 重跑 / R2.5 block-bootstrap clean-p /
survivorship as-of 重建),无「假装完成」。** 这些是 deferred-compute
扩展,需用户 explicit-go 再展开。

**总结**:用户的核心质疑成立 —— Phase 2/3 的负结论很大程度是**方法论
假阴性**。按 literature-proven 路径重做后:结构信息**有**增量(R2.5),
SSL-pretrain 的 chart 表征**能打过单动量因子**(R4 real-weight),前提
是数据准备/预训练/验证按 literature 做。审计纪律两次抓出会致命的方法
artifact(P2A overclaim、R4 fresh-init 架空),均诚实纠正留痕。

---

## §6 收口 deferred 全做(C1-C5)+ 第三/四 landmark + 数据红旗

用户「收口的全部都做」→ C1-C5 全执行(真跑,不假装):

| C | 项 | 结果(诚实)|
|---|---|---|
| **C1** | R2.5 block-bootstrap clean p | **clean p(one-sided mean≤0)= 0.0004**,95%CI ΔIC [0.0025, 0.0094] 全 >0 → family-T 正增量在**抗自相关严格检验下仍显著**(不再只"符号稳健",是真显著)。强化 R2.5 landmark。|
| **C2** | R5 真实 base 端到端 ensemble | **landmark③**:stack IC **0.083 >> 单动量 0.045**;**marginal:mae_probe +0.011 / gaf_tree +0.019——两 chart-native 成员都 additive,即便 gaf_tree 单挑输(-0.06)**。实证确认主 PRD §5.2「chart-native = ensemble 候选」。|
| **C3** | expanded_v2 ~1k 重跑 | **landmark④**:1000-universe 上 gaf_tree IC **+0.128** / mae_probe +0.024(vs 动量 −0.037)→ vs_tab +0.165 / +0.061。**印证 literature「需大 cross-section」——Phase 2A 小 79-票池是负结论根因之一**。诚实 caveat:此 universe/stride-10 动量 IC 为负 + n=5977 偏小,config-scoped。|
| **C4** | from-scratch 对比 | from-scratch CNN IC −0.003 ≈ 噪声(vs 动量 −0.048)→ **确认 from-scratch 输 pretrain-probe**,在同一 literature pipeline+大 universe 上仍成立。|
| **C5** | survivorship as-of | **无 delisting/历史成分 DB → 真 as-of 重建结构不可行**;诚实记录受阻原因+已测 proxy+所需数据,**不假装**(`structurally_infeasible_honest_caveat`)。|

**数据红旗(用户后续指令的依据)**:C3C4 在 expanded_v2 暴露
**`core/data/bar_store.py:500` `_apply_forward_splits` NaN-volume
int64-cast bug**(1003 中 skip 1;79/328 curated 从未触发,1000 数据驱动
集触发)。**未隐藏**:skip 计数+记录,列为独立 fix item。→ 触发 D1-D3
(全 universe 数据清洁审计 + 修 bug + 补数据 + clean 重跑验证稳定)。

**四个 landmark 合起来回答用户最初质疑**:Phase 2/3 负结论是方法论
假阴性 —— 按 literature 重做后:结构作因子有增量(R2.5,clean p
0.0004)、SSL-pretrain chart 表征打过单动量(R4 real-weight)、作
ensemble 成员 additive(C2,stack 0.083)、大 universe 上大幅 beat
(C3)。**全 config-scoped、诚实 caveat、审计纪律多次自查抓出会致命的
方法/数据 artifact(P2A overclaim、R4 fresh-init、R2.5 exact-zero、
BarStore NaN bug)均纠正留痕,不 hand-wave。**

**D1-D3 待执行**(用户指令:数据 100% clean 检查 + 补 + 重跑验证)——
在此之前 §6 数值标 `pending_data_cleanliness_validation`。

---

## §7 D3 —— 干净数据重跑 C3/C4(landmark④ 复检,2026-05-17)

D1+D2 后 expanded_v2 100% 干净,重跑 `run_c3c4_expanded_fromscratch.py`
(脏数据结果保留为 `c3c4_expanded.dirtydata.json` 做基准)。

| 指标 | 脏数据(pre-D2)| 干净数据(D3)| 定性 |
|---|---|---|---|
| n_samples | 5,977 | **116,820** | **干净后样本 ~20×**,脏行(周末/NaN)被过滤掉前样本极薄 → 脏 IC 高方差不可信 |
| n_skipped (BarStore bug) | 1 | **0** | bug 修复生效,1004/1004 全 load |
| mae_probe IC | 0.02425 | **0.04782** | **升**;vs_tab +0.061 → **+0.058(稳)** |
| gaf_tree IC | 0.12806 | **0.04479** | **大幅缩水**;vs_tab +0.165 → **+0.055** |
| 动量基线 IC | −0.037 | −0.010 | 此票池/stride 动量仍弱负 |
| C4 from-scratch IC | −0.003 | +0.002 | ≈ 噪声(稳);**确认 from-scratch 输 pretrain-probe** |
| DSR mae/gaf | 0.97 / 0.99 | **0.9999 / 0.999** | 干净大样本 DSR 更高 |
| sealed 2026 read | — | **False** | train-only 纪律保持 |

**诚实结论(不 overclaim / 不 blanket)**:
- **landmark④ 方向成立、量级是脏数据夸大**:gaf_tree 头条 IC
  +0.128/+0.165 是 5977 薄样本(脏行过滤后)的高方差 artifact,干净
  116820 样本上缩到 +0.045/+0.055。**但两个 chart-native arm 在干净大
  票池上 vs 动量基线仍正(mae +0.058 / gaf +0.055,DSR≈1)**——
  "chart-native 在大 cross-section 上打过动量基线"这个**定性**结论
  在干净数据上**存活**,只是不再是当初那个夸张幅度。
- **审计纪律再次被验证 load-bearing**:closeout §6 的 "MUST re-validate"
  caveat 是对的;复检把信号缩小但没归零——这正是 audit=暴露没做透的
  价值(脏数据本会让我们 overclaim +0.128)。
- **其余 3 landmark 不受影响**:R2.5/R4/C2 跑在 100%-clean executable-79
  票池上,与 expanded_v2 数据问题无关,结论不变。
- **scope 不变**:config-scoped(此因子集/此 prep/21d/此票池/stride-10
  /from-scratch fit-once),research 信号质量结论,**非可部署候选**
  (Track A / sealed / forward 漏斗未走),sealed 2026 全程未读。

§6 数值 `pending_data_cleanliness_validation` 标记 **CLEAR**;landmark④
数值以本 §7 干净结果为准,脏数值作废(保留 `.dirtydata.json` 做审计
留痕)。ML-method-redo 线 D1-D3 全部执行完毕。

---

## §8 D4 —— from-scratch per-CPCV-fold 严格重训(C4 caveat 闭合,2026-05-18)

C4 是 from-scratch fit-once(固定块训一次,bounded approximation)。
D4 升级成 **15 折逐折从零重训**(同数据/票池/prep/temporal-split),
关掉 closeout §4 最后一个 "bounded approximation" caveat。真跑
21908s(6.1h;fold 7/14 因系统争用各有一次大耗时跳变,15 折全完成,
结果为 15 折均值)。

| 指标 | D3 clean fit-once (C4) | D4 per-fold | pretrain→probe (D3 clean) |
|---|---|---|---|
| from-scratch OOS IC | 0.0022 | **0.0102** | —— |
| vs 动量基线 | —— | **+0.0206**(动量本身 −0.010,低栏) | mae +0.058 / gaf +0.055 |
| pretrain→probe IC | —— | —— | **mae 0.048 / gaf 0.045** |
| DSR | —— | 0.938 ⚠️ | —— |

**判定:CONFIRM,不反转(预期内)**。严格 per-fold 后 from-scratch IC
从 fit-once 的 0.002 升到 0.010(略好但绝对值仍弱),**远低于
pretrain→probe 的 0.045-0.048(差 4-5 倍)**。"from-scratch 输
pretrain→probe" 在**最严格 per-CPCV-fold 协议下成立**——C4 的
fit-once 近似**确认没有藏一个反转**,这正是"做透 ≠ 做出来"的价值
(与 D4 启动前预先写死的预期一致,正反都不 over-claim)。from-scratch
名义上"打过动量"仅因本票池/stride 动量为负(低栏),非强信号。

**DSR 0.938 边界**:`run_d4.py:196` 的 `n_trials` 硬编码 3(placeholder)
→ **DSR 偏乐观,不得当"已排除运气"引用**;稳健依据是上表 IC 对比
(from-scratch << pretrain→probe)。单一 SoT + 真实-N 重算计划见
`docs/memos/20260517-dsr_placeholder_n_boundary_memo.md`(§2 表已含
run_d4 行;G1 实现时回填重算值)。

**scope 不变**:config-scoped(此 prep/21d/expanded_v2/stride-10/此
ChartCNN config),research 信号质量结论,非可部署;sealed 2026 全程
未读。closeout §4 "R4 from-scratch 全重训" deferred 项 **CLOSED**;
ML-method-redo 线 D1-D4 全部执行完毕。
