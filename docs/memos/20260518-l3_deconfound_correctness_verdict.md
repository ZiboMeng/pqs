# L3 de-confound + correctness suite — verdict (用户稀释假设确认 + forward 候选 PASS 不抗 leakage 修正)

**日期**: 2026-05-18
**纪律**: `feedback_no_blanket_failure_verdict`、`feedback_audit_surfaces_not_thorough`(主动暴露 + 纠自己 over-claim)、`feedback_self_audit_methodology`、`feedback_promotion_only_falsification_evidence_gated`、`feedback_temporal_split_discipline`(全 partition selector,sealed 2026 未读)。
**bit-identical**: run2(79 默认无 flag)gates vs canonical = **PASS,NONE differ** —— 仪表化 by construction 干净,确认。

---

## §1 四点结果

| run | train | n_fit | Track-A | failed | IC pooled | **IC on 59(可交易)** | cum_ret | vs_spy | max_dd |
|---|---|---|---|---|---|---|---|---|---|
| run1 59-train | 59 | 65,586 | FAIL | validation_aggregate_excess_vs_spy(1) | 0.0213 | **+0.0218** | 25.93 | +19.60 | -20.5% |
| run2 79-train | 79 | 86,785 | **PASS** | — | 0.0122 | **+0.0146** | 20.42 | +14.09 | -16.8% |
| run4 79+suniq+purge | 79 | 80,911 | FAIL | vs_spy_agg + 2025_vs_spy(2) | 0.0106 | **+0.0110** | 18.19 | +11.85 | -16.9% |
| run3 1k-train | 1006 | 1,166,153 | FAIL | 2018_maxdd + vs_spy_agg + covid(3) | 0.0223 | **−0.0125** | 6.50 | +0.16 | -26.8% |

---

## §2 发现①(load-bearing):honest frozen-OOS IC ≈ 0.01-0.02,不是 headline 的 0.10-0.15

本套件的 `oos_rank_ic` = 真·frozen-OOS(仅 validation 年)pooled rank-IC。**全部落在 0.01-0.02**,比 L3-A/S1 JSON 里 cpcv `ic_sample_weighted`=0.147(79)/0.105(1k)**小一个数量级**。原因:cpcv 那个数是 train+val pooled、fold-mean、加权的不同度量;**真实样本外 IC 是 ~0.01-0.02**。→ 这本身印证 collapse⑤ 的 correctness 关切:headline IC 不是诚实的 frozen-OOS IC。

## §3 发现②:用户的"稀释假设"——**数据确认**

IC-on-59(probe 在它实际交易的 59 个名字上的 IC)随训练截面扩大**单调退化**:

> **59-train +0.0218 → 79-train +0.0146 → 1k-train −0.0125(翻负)**

而 pooled IC(全训练宇宙上量)**不退化**(0.021→0.012→0.022,噪声级波动)。

**结论:用户 2026-05-18 的直觉成立。** 训练截面越偏离可交易的 59,probe 在那 59 上越差,1k 时**对它实际交易的名字 IC 翻负**——而 pooled IC 完全掩盖了这点(S1 +0.10 / L3-A pooled 都是 pooled,没量 on-59)。**L3-A FAIL 主因 = train/trade 错配稀释,不是 construction-bound。** 我上一轮 L3-A verdict §3.4「再次坐实 construction-bound」是 over-claim;§6 amendment 的谨慎方向正确,**现以数据最终更正:稀释是 1k-FAIL 的主驱动**。

## §4 发现③(不向反面 over-claim):construction gate 仍真,稀释非全部

**59-train(最大针对性、IC-on-59 最高 +0.0218、cum_ret 25.93、full vs_spy +19.60)仍 FAIL Track-A**——只 fail 1 门 `validation_aggregate_excess_vs_spy`(per-validation-年 mean excess vs SPY,不是 full-period)。即:full-period 暴打 SPY,但 5 个验证年的均值 excess 不达标(与 Trial 9 / cycle 候选同一 pattern)。→ **修掉稀释 ≠ 就能过**;targeting 帮很大但 long-only cap_aware 的 validation-aggregate vs-SPY 纪律 gate 仍 binding。两效应都真,稀释是 1k 问题的更大杠杆。

## §5 发现④(最重要):forward 候选的 Track-A PASS **不抗 leakage 修正**

run4 = 79-train + López de Prado average-uniqueness 加权 + purge/embargo:
- IC-on-59 **0.0146 → 0.0110(−25%)**
- Track-A **PASS → FAIL**(新增 fail `validation_aggregate_excess_vs_spy` + `role_core__validation__2025__excess_vs_spy`)
- cum_ret 20.42→18.19,vs_spy +14.09→+11.85

**含义(诚实,scoped,非 blanket)**:已 forward-init 的 `chart_native_s1_evidence_v1` 用的正是 79-train probe;它当初 Track-A "17 门全过" **部分是重叠标签膨胀 + 年边界 leakage 的产物**——做 leakage-correct 评估后**退化为 FAIL**(vs-SPY aggregate + 2025 vs-SPY)。不是"信号没用"(honest IC 仍小正 ~0.011、full-period cum_ret 仍大),是**它过不了 leakage-correct 的生产纪律 gate**。这是关于该候选自身的**证伪证据**(其 acceptance 是 leakage-inflated)。

## §6 决策含义

- **Path B(1000 名基建)**:稀释确认 ⇒ L3-A FAIL 不能用来否定"对齐的 1k";但也无正面证据对齐 1k 能过(最干净的 59-train 仍 fail construction gate)。**仍不立即起 Path B**,但更正理由 = binding 的是 validation-aggregate vs-SPY 纪律 + leakage-correct 后更弱,不是池子大小。
- **最高优先 = §5**:forward 候选 acceptance leakage-inflated、leakage-correct 后 FAIL。这是 directional 治理问题(继续作 evidence-only 观察但文档化此 caveat,还是按证伪证据 retire)——**用户拍**,operator 不单方面定;但必须强暴露不掩埋。
- **construction vs 稀释**:两者都真;后续若再投 chart_native,(a) 评估链必须先上 sample-uniqueness + purge/embargo(否则所有 IC/Track-A 不可信);(b) construction-DOF 仍是独立真问题(59-train 已证 even max-targeting 撞 validation-aggregate gate)。

## §7 Scope / 不 over-claim

- 不下 "chart-native 死 / 图像无用" blanket:honest IC 小但正(59-train +0.022),full-period 大幅赢;失败是 leakage-correct 生产纪律 + per-year-vs-SPY,非信号为零。
- 稀释确认是 IC-on-59 单调 + pooled 不退化 双证据,非单点。construction gate 仍 binding 是 59-train 仍 fail 的独立事实,不被稀释结论推翻。
- config-scoped / train-only / sealed 2026 未读;DSR/pbo caveat 同 L3-A。

关联 [[project-backtest-robustness-ml-redo-2026-05]] [[project-grand-audit-2026-05-18-two-p0]];前序 `docs/memos/20260518-l3_option_a_expanded_v2_verdict.md`(§3.4 over-claim 在此最终更正)、`docs/memos/20260518-chart_native_architecture_literature_synthesis.md`(收敛⑤ correctness 缺口在此实测确认)、`docs/memos/20260518-s1_scale_falsification_verdict.md`(pooled IC 掩盖 on-59 退化,在此暴露)。
