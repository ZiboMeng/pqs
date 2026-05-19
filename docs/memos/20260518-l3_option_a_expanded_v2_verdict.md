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

关联 [[project-backtest-robustness-ml-redo-2026-05]] [[project-grand-audit-2026-05-18-two-p0]];同源 `docs/memos/20260518-chart_native_architecture_literature_synthesis.md`(收敛⑤)、`docs/memos/20260518-s1_scale_falsification_verdict.md`。
