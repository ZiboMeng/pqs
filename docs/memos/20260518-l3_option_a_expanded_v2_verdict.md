# L3 Option A verdict — 1k-trained probe FAILS production Track-A (construction-bound, not signal)

**日期**: 2026-05-18 (run completed 2026-05-19 ~01:xx UTC)
**纪律**: `feedback_no_blanket_failure_verdict`(只判这个 attempt,不下 chart-native 全线 blanket)、`feedback_audit_surfaces_not_thorough`、`feedback_self_audit_methodology`、`feedback_temporal_split_discipline`(partition_for_role selector,sealed 2026 未读)。

---

## §1 实验

L3 Option A:`CHART_L3_UNIVERSE=expanded_v2` —— frozen-ImageNet ridge probe 在 ~1006 截面训练(probe_fit 1,166,153 train rows),cap_aware Track-A 组合**仍受限 cluster_map ~59 名**(eligible_cols)。回答:"1k 训练的探针,喂进现有 59 名生产 Track-A 全套 gate,过不过?" streaming 重构生效,1,480,958 窗 ~51min,无 OOM。

## §2 结果(vs executable-79 canonical)

| | EXEC-79 | EXPANDED_V2(1k 训探针 / 59 名组合) |
|---|---|---|
| **Track-A** | **PASS**(0 fail) | **FAIL** |
| failed gates | — | `validation_year_2018_maxdd`, `validation_aggregate_excess_vs_spy`, `stress_slice_covid_flash_maxdd` |
| cum_ret | 20.42 | **6.50**(SPY 6.34) |
| sharpe | 1.589 | 1.088 |
| max_dd | -16.8% | **-26.8%** |
| vs_spy | **+14.09** | **+0.16**(勉强过 SPY) |
| vs_qqq | +15.46 | +1.53 |
| cpcv ic_sw | 0.147 | **0.105**(cpcv_gate 仍 PASS) |
| probe train rows | 86,785 | 1,166,153(~13×) |
| sealed_2026_read | False | False |
| pbo_red_flag | True | True(两边都 red — 全线既有 caveat,非本次新增) |

artifact: `data/audit/chart_native_l3_track_a_expanded_v2.json`、`data/audit/ml_redo/l3_track_a_expanded.log`。

## §3 判读(scoped,非 blanket)

1. **1k 训练的探针在可交易 59 名宇宙上 FAIL 生产 Track-A;79 训练的探针(= 实际 forward 候选 chart_native_s1_evidence_v1)仍 PASS,逐位不变。** 本次 FAIL 是 1k-arm 的判决,**不削弱、不改动已 forward-init 的 79-probe 候选**。
2. **失败定位 = 构建/已实现收益,不是信号 IC。** cpcv ic_sample_weighted 在 1k 仍 +0.105、cpcv_gate PASS —— **与 S1 scale falsification 一致(信号 scale 不退化)**。但同一信号经 long-only 月度 cap_aware top-N 构建出的组合 vs_spy 从 +14.09 塌到 +0.16、max_dd -16.8%→-26.8%、3 门 FAIL。**信号没问题,构建吃掉了它。**
3. **训练截面选择对已实现组合影响巨大,即便 IC 看着差不多。** 79→1k 训练把同一 59 名组合从"大幅跑赢"变成"勉强平 SPY + 更深回撤"。这是 IC ≠ realized-return 的又一直接证据。
4. **这再次坐实 construction-bound 诊断**(roadmap v2 TC 天花板 + sibling-by-construction + 4 路文献综合收敛⑤):binding constraint 不是信号表征、不是 universe 大小,**是 long-only 月度 cap_aware top-N 这个构建本身**。

## §4 决策含义(按用户预承诺的 sequencing)

用户预承诺:**L3-A PASS → 起 Path B / 多 arm PRD;FAIL → 先 root-cause,不盲建 1000 名基建。**

→ **L3-A FAIL ⇒ 不起 Path B(1000 名 cluster taxonomy / 优化器),不以"1k 帮信号"为前提建多 arm PRD。便宜 gate 已尽职:扩 probe 训练截面不改善可交易生产判决,反而恶化。**

**正确的下一步(不是 blanket 否定 chart-native,是按证据重定向)**:
- (a) **横切 correctness 缺口优先**:chart_native 评估链缺 López de Prado average-uniqueness 加权 + purged/embargo(21d 重叠标签)→ 现有所有 chart_native IC(含 79-PASS 的 0.147、forward TD000 baseline)**很可能虚高,须先确认影响幅度再信任任何判读**。这是 bug 类,优先级最高。
- (b) **攻 construction,不再攻信号/universe**:本实验 + S1 + cycle04-10 + 文献四方一致 —— 投资该投 roadmap v2 的真 lever(cadence/horizon/cross-asset done right),不是更大 universe / 更花哨表征。
- (c) 工程化特征 + XGBoost + stack frozen-probe 仍可作 signal-quality research arm(文献最强 ROI),但**带同样 construction caveat**,且必须先做 (a)。

## §5 Scope / 不 over-claim

- 仅判 "1k-trained-probe arm FAIL 生产 Track-A";**不下** "chart-native 线死 / 1k 无用 / 图像不行" 的 blanket(`feedback_no_blanket_failure_verdict`)。79-probe forward 候选未受影响。
- config-scoped / train-only / sealed 2026 未读;DSR=1.0 是 placeholder-N 天花板非证据锚,pbo_red_flag=True 两边都有(全线既有 caveat)。
- 失败是构建层,**不能 over-claim 成"信号没用"**——信号 IC 在 1k 仍正、仍胜动量(S1 已证)。

## §6 AMENDMENT 2026-05-18 — 自纠 over-claim:L3-A 是 train/trade 错配的污染实验

用户 2026-05-18 指出 §3.4 + §4 的框定 over-claim。更正:

**L3-A 不是 "1k vs 79" 的干净对照,是 train/trade 错配**:probe 在
1006 训练但**只在 59 名(cluster_map)交易**。79-PASS = 训练≈交易
(79⊃59,强针对性);1k-FAIL = 训练≫交易(1006 vs 59),ridge 系数
被往 1000 名(双峰:442 深史+380 浅 2015)平均结构拉,**那 59 个特有
的 predictive 结构被稀释**。因此**不能用 L3-A FAIL 推出"扩到 1k 无
改善"**——那是 `feedback_no_blanket_failure_verdict` 禁的 over-claim;
§3.4 "再次坐实 construction-bound" 低估了此 confound,在此更正。

**现有 ≥3 个互不排斥解释,L3-A 单独分不开**:(a) train/trade 稀释
(用户假设,机制成立,**未测**);(b) construction-bound(cycle04-10
独立成立,但不能用 L3-A 单独"坐实");(c) correctness 缺口(IC 本身
可疑)。关键空缺:**S1 的 +0.105 是 pooled 在 1000 名上量的,从未量
1k-probe 在那 59 个可交易名字上的 IC** → S1+L3-A 合起来仍分不开稀释
vs construction。

**决定性便宜实验(不需 Path B 基建)**:三点曲线 [59-train/59-trade,
79-train/59-trade(已 PASS),1k-train/59-trade(已 FAIL)] + 把
1k-probe IC 限制在 59 子集量(对比 79-probe 同 59)。IC-on-59 随
59→79→1k 单调降而 pooled 不变 → 稀释确认,L3-A FAIL 主因是错配非
construction,Path B 在 train/trade 对齐下需重估;若 59-train(最大
针对性)也 FAIL Track-A → construction-bound 占主导。

**对 §4 决策的影响**:Path B(1000 名基建)**仍不立即起**(稀释假设
未证、不是"1k-trade 已证好");但 §4 "L3-A 再次坐实 construction-
bound、攻 construction 非信号" 的确定性**下调**——须先跑上述去混淆
实验才能定 construction vs 稀释 何者主导。correctness 缺口 (a) 仍是
最高优先地基(IC 可疑则三点曲线也不可信)。

关联 [[project-backtest-robustness-ml-redo-2026-05]] [[project-grand-audit-2026-05-18-two-p0]];同源 `docs/memos/20260518-chart_native_architecture_literature_synthesis.md`(收敛⑤)、`docs/memos/20260518-s1_scale_falsification_verdict.md`。
