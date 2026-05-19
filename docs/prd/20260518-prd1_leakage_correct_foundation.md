# PRD-1 — Leakage-Correct 评估地基 + 在任候选诚实全重评

**日期**: 2026-05-18 · **lineage**: `leakage-correct-foundation-2026-05-18`
**性质**: 评估准则级修复(invariant-adjacent,用户 explicit-go 2026-05-18:全 retire 可接受、诚实压倒在任)。
**纪律**: `feedback_audit_surfaces_not_thorough`、`feedback_no_blanket_failure_verdict`、`feedback_promotion_only_falsification_evidence_gated`、`feedback_self_audit_methodology`、`feedback_temporal_split_discipline`。
**源证据**: `docs/memos/20260518-l3_deconfound_correctness_verdict.md`（run4 实测:leakage-naive → IC-on-59 +25% 虚高、forward 候选 Track-A PASS→FAIL）。

---

## §1 问题（已实测，非假设）

run4 证实：21d 重叠标签未做 average-uniqueness 降权 + score-生成的 probe-fit 级未做 purge（cpcv 只 purge fold，不 purge 生成分数的 β 拟合）→ IC 与 Track-A 系统性虚高（chart_native: IC-on-59 −25%，PASS→FAIL）。preflight 实查：`cpcv_acceptance.ic_sample_weighted` 是 **sample-SIZE** 加权（fold `len(te)`），代码注释明写"§3 唯一允许 size 加权"——**全项目无 overlapping-label uniqueness 加权**（`uniqueness` core 零命中）。这不是 chart_native 独有，是 factor-composite Track-A 通病。

## §2 Scope

**In**：
- P1.1 `core/research/` 加 canonical `average_uniqueness_weights(labels, horizon)`（López de Prado Ch.4 concurrency）+ `probe_fit_purge_mask`（train 行 label 窗跨进 validation 年则 purge + embargo），含单元测试。
- P1.2 接入：`temporal_split_acceptance` + 所有 probe-fit/score-生成路径（chart_native L3 已 default-on，本 PRD 把它提升为 core-level 契约）。新增 `acceptance.yaml` 开关 `leakage_correct: true`（default），`legacy_no_leakage_corr` 逃生口（forensic，bit-identical 复现旧数）。
  - **§3 契约调和（实现者必读,防错）**：average-uniqueness 是 **probe-fit loss 的 per-sample 训练权重 + label 构造偏差修正**,**只入样本/probe-fit 层**;**不得**改 `cpcv_acceptance` §3 的 fold-aggregation sample-SIZE 加权（§3 禁的是 fold 聚合层的自由裁量 recency/regime DOF；uniqueness 是原则性减偏,范畴不同,两层正交,§3 rationale 不适用）。purge/embargo 同理作用于 probe-fit 训练行,cpcv 的 fold-level purge 保持不动。
- P1.3 **诚实重评**（**SCOPE-CORRECTED 2026-05-18 loop R3,grounded —— 见 `docs/memos/20260518-prd1_p13_scope_correction_factor_composite_unaffected.md`**）：
  - 原 premise"cycle06/08 = factor-composite Track-A 通病须重评"**对 factor-composite 是错的**（诚实纠 overclaim）：R3 实读 `cycle06_track_a_eval.py` = `ResearchCompositeSpec`+`evaluate_composite_spec`,**无 ridge probe / 无 cpcv_inputs 重叠标签向量**;run4 leakage 是 **learned-probe-specific**(chart_native),对确定性 composite 无机械作用面 → cycle06/08 Track-A PASS 不因该机制虚高,**不重评、不 retire、主线不归零**（grounded,非护盘）。
  - 正确 scope:learned-probe（chart_native_s1）→ Option A caveat done;pead_sue → 单独小检查（事件驱动,evidence-only 非主线）;cycle06/08/options/simple_baseline → probe-fit leakage 无作用面。
  - "全 retire 可接受"（用户 2026-05-18）仍立,但 retirement 逐候选 evidence-gated；目前 grounded 证据 = 仅 chart_native 受影响（已 caveat）。
  - **✅ RATIFIED A + C-lite（用户 2026-05-19）**：grounded scope 接受 —— 仅 chart_native_s1 受 run4 probe-fit leakage（已 Option A caveat done）;cycle06/08 + pead（R4 grounded）+ options/simple_baseline **不受影响、不重评、不 retire,主线不归零**。C-lite = 后台对 cycle06/08 重评 empirical 背书（确认 P1.1/P1.2b leakage 机器未扰动其确定性 verdict;预期 bit-不变,偏差则 §1 grounded 分析错 → ROOT CAUSE）。B（未来 factor-composite cpcv-IC uniqueness）= §3 冻结契约修订,未触发,日后用户要管未来 cycle 才另起 mini-PRD。P1.3 在 C-lite 背书通过后即闭。
- P1.4 重评结论 fold 进各候选 manifest/memo + CLAUDE.md forward-state；被推翻者按 evidence retire，留 forensic。

**Out / Deferred**：不改 temporal_split partition/sealed_ledger（C4 lock）；不改 acceptance 阈值数值（仅加 leakage-correct 加权/purge，阈值不动）；新 mining 本身 = PRD-2。

## §3 关键依赖 / 后果（诚实摆，非 hand-wave）

- sealed 2026 单发已被 cycle08 消耗（sealed_ledger B1，split-level 锁）；**retire cycle06/08 不 un-consume**。新 mining 终极 gate = Track-A(leakage-correct) + Path-1 forward（`docs/memos/20260518-path1_forward_replaces_sealed_singleshot.md`），**不重开 2026 sealed**（除非单独 explicit-go bump split_name）。
- cycle06/08 若 retire → 主线 core_alpha forward 证据链归零 → 新 mining 从"可做"升"该做"（PRD-2 进场时机）。

## §4 验收

1. P1.1 helper 单测：concurrency 正确性 + purge/embargo 边界 + 空/退化兜底。
2. legacy 逃生口对 ≥1 历史候选 bit-identical 复现旧数（证 delta 隔离干净）。
3. cycle06/08 + ≥1 独立轨候选 leakage-correct 重评完成，对照表归档。
4. 全程 sealed 2026 未读；所有重评 config-scoped 留痕；被 retire 者有逐候选 evidence。

## §5 R1-R4 自审

- R1：preflight 实证 `ic_sample_weighted`=size 加权、core 无 uniqueness（grep 留痕）。
- R2：cpcv 有 fold-purge 但 β-fit 无 purge + 无 uniqueness 是两个独立缺口，逻辑分清。
- R3：run4 已实跑证机制真实（IC −25%、PASS→FAIL），非推测。
- R4：边界——不动 partition/sealed/阈值；retirement evidence-gated 非 blanket；sealed-consumed 后果显式摆。
