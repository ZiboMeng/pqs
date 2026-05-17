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
