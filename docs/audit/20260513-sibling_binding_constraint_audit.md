# 审计：sibling-by-NAV 的真正"绑死约束"是什么

**Date**: 2026-05-13
**Trigger**: 用户问"是 construction 导致 sibling 吗？先 audit，再决定 websearch 什么"
**Method**: 4-tier (R1 fact / R2 logic / R3 actually-run-code / R4 boundary)

---

## §0 一句话结论（人话）

**单独的 construction 不是绑死约束。真正绑死的是一个组合："只做多 + 每月再平衡 + 取前 N=10 名 + 在 ~79 只股票池里挑"。把这 4 个一起换，相关性才掉得下来。**

只换其中一个（比如把 global_top_n 换成 cap_aware），raw NAV 相关性只从 ~0.92 降到 ~0.87，**远远不够**（阈值 0.85，目标 <0.70）。

证据见 §2-3。

---

## §1 关键数字（grep 自实际 audit JSON，不是回忆）

| 配对 | raw NAV Pearson | residual vs SPY | 4 件套异同 |
|---|---|---|---|
| RCMv1 ↔ Cand-2（forward 真实跑） | **0.898** | 0.609 | 同长仓+同月度+同 top-N+同 79 池；因子 **零重叠** |
| cycle07a T3 ↔ RCMv1（16y panel） | **0.874** | 0.603 | 同长仓+同月度+同 top-N+同池；construction **不同**（cap_aware vs global_top_n）；只共享 1 因子 `drawup_from_252d_low` |
| cycle07a T3 ↔ Cand-2 | **0.892** | 0.688 | 同 bundle；**零共享因子** |
| cycle07a T3 ↔ Trial 9 v1 | **0.783** | 0.319 | 同 bundle；共享 `beta_spy_60d`；T9 因子 `max_dd_126d` 替代 drawup |
| cycle09b T1 ↔ cycle08 top-1 | **0.020** | 0.019 | **不同 cadence**（monthly vs weekly）；**但** cycle08 是 Track-A-FAIL 即基本没信号，**这个对比有水分** |
| alt-A intraday ↔ RCMv1 | **0.146** | 0.142 | **完全不同 strategy-type**（日内反转）；只持仓 316/2011 天；**整个 bundle 换了** |
| cycle04 Cluster A（drawup+amihud+cross-asset 池） ↔ RCMv1 | **0.66-0.70** | n/a 在 SPY 单残差 | **改了 universe**（加债+黄金+现金）；construction 改 cap_aware_cross_asset |

---

## §2 单变量 A/B（控制其他变量）

### A. 只换 construction（cap_aware vs global_top_n），其他都不变
**cycle07a T3 vs RCMv1** = **raw 0.874**。Δ vs RCMv1↔Cand-2 (0.898) = **−0.024**。

→ 换 construction 子集逻辑（cap_aware = 单股 ≤ 10% + 行业簇 ≤ 20%）**几乎不动 NAV 相关性**。Top-10 重叠的股票池太小，cap 只是重排权重。

### B. 只换 cadence（monthly vs weekly），其他不变
**cycle09b T1 vs cycle08 top-1** = **raw 0.020**。

**但**：cycle08 Track A FAIL（vs_spy 不过 hard gate），可能根本没"信号"，0.020 是 random vs real 而不是 cadence 真的破除了相关性。**这个证据被 cycle08 失败污染了，不能用**。

### C. 只换 factor anchor，其他都不变（同 bundle 内）
**RCMv1 ↔ Cand-2** = **raw 0.898**，**零共享因子**。

→ 在同 bundle 里，**换因子根本不破 sibling**。因子只决定 top-10 的小幅重排。

### D. 换整个 bundle（strategy-type / universe / cadence 一起换）
**alt-A intraday vs RCMv1** = **raw 0.146**。整个 bundle 换：日内反转 + 持仓 16% 时间 + 53 股 universe。

**cycle04 Cluster A vs RCMv1** = **raw 0.66-0.70**。换了 universe（加债/金/现金）+ construction（cross_asset cap）。

→ **整 bundle 换才破。**

---

## §3 为什么 bundle 是绑死的（机制解释）

数学上：长仓 + monthly + top-10 + 79 股池，意味着每月从 79 只股票里挑 10 只持有。

- 两个完全不同的因子，因为都在挑"美股大盘里相对强势的 ~10 只"，重叠平均 **30-50%**。
- 没拿到的 ~60% 股票每天对两个组合贡献都是 **0**。共同持有的 ~5 只对两个组合都贡献正回报。
- 即使因子完全正交，**实际持仓的覆盖重叠**就够把 raw NAV Pearson 推到 0.85+。
- 加 SPY 共享 beta（两边都是长仓美股 → 都吃 SPY 的 ~0.5-0.6 β），再 stack 0.30 raw 上去。
- **总和**：bundle 决定 ~0.85 raw 下限，因子 + construction 在剩下 0.05-0.15 里抖。

**人话**：如果两个人都被要求"每月从 SPY 成份股里挑 10 只你最看好的长仓持有"，不管挑的逻辑多么不同，他们的月度持仓重叠率 + SPY 共有 beta 决定了两人 NAV 长得很像。这跟"construction 是什么"几乎无关。

---

## §4 4-tier 自审

### R1 事实
所有数字 grep 自实际 audit JSON 文件（cycle07a_trial3_nav_correlation.json / cycle09b_trial1_extended_nav_correlation.json / 20260430_rcmv1_cand2_realized_correlation.json / alt_a_phase3_anti_sibling.json）。没有引用记忆里"约 0.9 之类"的模糊数字。

### R2 逻辑
- 控制变量法：cycle07a T3 vs RCMv1 是最干净的单变量 construction 对比（同月度同 top-N 同池，只改 construction + 1 因子换 2 因子）→ raw 只降 0.024。这是 "construction 不绑死" 的核心证据。
- RCMv1 vs Cand-2 是最干净的"全因子换"对比 → 还是 0.898。这是 "因子不绑死" 的核心证据。
- alt-A vs RCMv1 是"全 bundle 换"对比 → 0.146。这是 "bundle 是绑死的" 的核心证据。

### R3 actually-run
所有 JSON 都已经被实际打开 + 数字 dump 过（见 §1 表）。不是回忆。

### R4 边界
- **cycle09b T1 vs cycle08 top-1 = 0.020 反例**：被 cycle08 Track-A-FAIL 污染，**不能**用作"cadence 单独破 sibling"的证据。
- **cycle04 Cluster A = 0.66-0.70**：但 universe + construction + factor anchor 都换了，三变量混合，不能归因到任何一个。
- **alt-A = 0.146**：但是 strategy-type 完全换了（intraday 不是 daily long-only），不在原 archetype 内，比较"是否 sibling"意义有限——它不是同类策略。
- **真正干净的"只换 cadence"对比**：**我们没有**。这是 audit 的一个盲点：weekly cadence 在 cycle08 失败、daily cadence 没单独 mining 过、quarterly 没试过。

---

## §5 verdict（基于证据）

| 假设 | 证据 | verdict |
|---|---|---|
| construction 单变量是绑死约束 | cycle07a T3 vs RCMv1 raw Δ = −0.024 | **WEAKLY SUPPORTED → 实际上 FALSE** |
| factor swap 单变量是绑死约束 | RCMv1 vs Cand-2 raw = 0.898（零共享） | **FALSE** |
| 整 bundle（long-only + monthly + top-N + 79 池）是绑死约束 | alt-A bundle 换 → 0.146；cycle04 部分换 → 0.66 | **STRONG SUPPORT** |
| cadence 单变量能破 | cycle09b vs cycle08 = 0.02 但 cycle08 FAIL 污染 | **INCONCLUSIVE — 需要单独验证** |
| universe 单变量能破 | cycle04 + alt-A 都换了 universe 但同时换了别的 | **INCONCLUSIVE — 需要单独验证** |

---

## §6 对下一步的含义

**直接 WebSearch "portfolio construction SOTA" 是错的方向**：因为单换 construction 解决不了。

**真正该问的问题**：

1. **literature 怎么破长仓 + top-N + 同池的 NAV sibling？** 关键词不是 "construction"，是：
   - "long-only portfolio diversification" + "active share"
   - "non-overlapping equity portfolios" + "low-correlation alpha sleeves"
   - "factor portfolio orthogonalization"（在 NAV 层，不是 IC 层）
   - "covariance-aware portfolio construction"

2. **单独 audit cadence / universe / selection-rule 的 SOTA 方法**：
   - cadence: weekly with proper signal / daily / quarterly / event-driven
   - universe: factor-tilt subset (e.g. low-vol only / high-momentum only) / sector-rotation / multi-asset
   - selection-rule: 不是 top-N 而是 z-score 长仓权重 / Kelly-style / 1/N over factor-filtered subset

3. **直接 WebSearch 三个独立方向**，不要假定 construction 一定是答案：
   - "How to build low-correlation long-only equity sleeves"
   - "Alpha orthogonalization at NAV level vs IC level"
   - "Active share + portfolio construction for diversification"

---

## §7 建议（不是决策，决策权用户）

不要直接埋头改 construction。先 WebSearch 3 个方向（construction / selection-rule / universe-tilt），看 literature 怎么破"长仓 + 同池 sibling"。

如果 literature 答案也是 "去碰 universe 或 strategy-type"，那 cycle10 的 axis 选择应当从"construction"换成更宏观的 axis。

如果 literature 提到 "active share" / "tracking error" / "tournament selection" 之类的 N=10 selection rule 改造，那是 construction 的子方向但比 weight-scheme 更深。
