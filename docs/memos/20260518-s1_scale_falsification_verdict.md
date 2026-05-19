# S1 scale falsification verdict — pretrain-rescue confirmed (with confound caveat)

**日期**: 2026-05-18 (run completed 2026-05-19 00:38 UTC)
**lineage**: `scaled-pretrain-checkpoint-2026-05-17`
**纪律**: `feedback_no_blanket_failure_verdict`(不下 blanket verdict)、
`feedback_audit_surfaces_not_thorough`(暴露 confound + fold 进文档)、
`feedback_promotion_only_falsification_evidence_gated`(证伪 attempt
未出 strategy-self 缺陷 ≠ 拒绝理由)、`feedback_self_audit_methodology`。

---

## §1 动机(falsification)

C3 landmark④ 先验:小 79 池曾是早期 chart-native NEGATIVE 的疑似 root
cause(JKX "needs large cross-section")。已 forward-init 的
`chart_native_s1_evidence_v1` = frozen ImageNet ResNet18 + train-only
ridge probe on executable-79。本 falsification:同一 S1 arm 在 ~1006
universe(`S1_UNIVERSE=expanded_v2`)重跑,问 edge 是 **pretrain-rescue
机制**(表征来自 ImageNet 非 79 → 放大不退化)还是 **79 小池 artifact**
(strategy-self 脆弱性,harness 关切)。

## §2 结果(train-only,sealed 未触)

| 指标 | executable-79 | expanded_v2 (~1006) |
|---|---|---|
| n_windows | 85,404 | 1,168,452 (~13.7×) |
| imagenet_probe_ic | 0.12172 | 0.10148 |
| momentum_baseline_ic | +0.03205 | **−0.00049** |
| **vs_momentum** | +0.08967 | **+0.10197** |
| dsr_honest_n | 1.0 | 1.0 (placeholder-N 天花板,非证据锚) |

artifact: `data/audit/w8_s1_imagenet_backbone_expanded_v2.json` /
`..._backbone.json` / `data/audit/ml_redo/s1_scale_falsification_expanded.log`。

## §3 判读

**Probe IC 在 ~14× cross-section 下同量级保住**(0.122→0.101);**关键
`vs_momentum` 反而走强**(+0.090→+0.102),因为动量基线在宽 universe
塌到 ~0 而 ImageNet 表征留 ~0.10 IC。

**Verdict: pretrain-rescue 机制 CONFIRMED;"79 小池 = strategy-self
脆弱" 怀疑未被证实(反被反驳)。** 按 harness 证伪框架:本次是
falsification ATTEMPT,**未产出 strategy 自身缺陷证据** → 不削弱
`chart_native_s1_evidence_v1` 的 evidence-grounded forward-init。

## §4 必须如实标的 confound(不 over-claim)

1k universe 双峰历史深度:~442 sym 2007+ 深史 vs ~380 sym 仅 2015+
(yfinance bulk 拉取地板,见 coverage audit `run1_artifact_note`)。
1k-vs-79 **同时混了 cross-section 放大 + 部分名字历史变浅** 两变量。
诚实方向:更浅历史只会加噪 → edge 在更噪/部分更浅 universe 仍
hold/走强 = **更强**结果;但 IC 绝对值对比(0.122 vs 0.101)部分反映
universe 变噪,**非纯 scale**。**不是干净受控 cross-section 实验。**

**Scope(无 over-claim)**:config-scoped / train-only / sealed 未触 /
**非可部署候选** / 标准 torchvision 预训练 backbone(非手搓)/ DSR=1.0
是 placeholder-N 天花板非证据锚,稳健信号 = vs_momentum IC 正。

## §5 工程旁注

expanded_v2 OOM 根因 = 全图张量主存物化(~35GB 数组/~69GB 峰值);
commit `7f22b85` 流式重构(峰值 O(batch),~4GB)修复 + executable-79
bit-identical 自验通过。本次 1.17M 窗 ~43min 无 OOM。详见该 commit。

关联 [[project-backtest-robustness-ml-redo-2026-05]]
[[project-grand-audit-2026-05-18-two-p0]]
[[feedback_websearch_fuzzy_to_primary_depth]]。
