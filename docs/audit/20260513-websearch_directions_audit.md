# 审计：哪些 WebSearch 方向值得做，哪些是浪费

**Date**: 2026-05-13
**Trigger**: 用户："先 audit 可以 WebSearch 的方向"
**Method**: 对每个候选方向打分（信息价值 / 实现成本 / PQS 适配度）

---

## §0 一句话

**真正值得搜的只有 2 个方向**，其他 4 个是浪费（信息已知 / 是工程问题不是知识问题 / 已经在路线图）。

---

## §1 评分框架

每个方向打 3 分：

1. **信息价值** ──这个 query 能不能给我**之前不知道**的 PQS-specific 答案？高 = 答案能改变 cycle10 axis 选择；低 = textbook 知识 / 已经在 CLAUDE.md。
2. **实现成本** ──搜到之后真做出来要多少 eng？低 = config 改动；高 = 多周数据/模块。
3. **PQS 适配度** ──这方法在 long-only + $10K + 79 股 + SPY-benchmark 环境下能用吗？

只搜「**信息价值高 + PQS 适配度高**」的方向。实现成本高的话，搜了至少先评估再决定做不做，不算白搜。

---

## §2 候选方向逐个审计

### A. ✅ **Active-share / overlap penalty 加进 mining objective**
- **什么意思（人话）**: mining 时不只优化 IC/IR，还在目标函数加一项 "−λ × 与 RCMv1+Cand-2+Trial 9 的持仓重叠率"，强迫挑出来的组合在选股层面就跟现有候选不一样。
- **信息价值**: **HIGH**——这是**最直接攻击 sibling 的方法**（在 selection 层就破，不靠权重重分配）。学术界 "active share" (Cremers-Petajisto 2009) + portfolio "diversification budget" 文献有具体公式。我**不知道**业界 long-only mining 是怎么把 active-share 写进目标函数的——这是真知识缺口。
- **实现成本**: **中**——`core/mining/composite_evaluator.py` 加一个 anchor-overlap 计算 + Optuna 目标函数加一项 penalty。1-2 天 eng。
- **PQS 适配度**: 完美——long-only top-N 选股就是 active-share 的 native frame。
- **verdict**: **搜**。最高优先级。

### B. ✅ **NAV-level alpha orthogonalization（事后正交化）**
- **什么意思（人话）**: 不在 mining 时求新的；mining 完之后把 trial 的 daily returns 对 RCMv1+Cand-2+Trial 9 做线性回归取残差，**残差** 才是新候选的"独立 alpha"。如果残差 Sharpe > 0 且年化 > SPY 残差，组合层叠加这个残差就能降低 fleet NAV 相关性。
- **信息价值**: **HIGH**——这是个我**完全没考虑过**的 axis。等于把"找新策略"换成"找现有策略的残差"。文献里有 alpha attribution / "neutralized portfolio" 相关方法。
- **实现成本**: **中**——eval pipeline 加一步 OLS 残差化，类似已经做的 `pooled_pearson_residual_vs_spy` 但目标变成"残差作 trade signal"。复杂在工程上 trade 残差需要重新构造持仓——可能需要先纸面研究是否可行。
- **PQS 适配度**: 注意——纯残差可能产生 long-short 净敞口，与 long-only invariant 冲突。要看文献怎么在 long-only 约束下做。**这个 caveat 决定方向是否可行**。
- **verdict**: **搜**。但 query 必须明确"long-only constraint preservation"。

### C. ⚠️ Sector-neutral construction
- **什么意思**: 强迫每个 GICS 行业的组合权重 = SPY 该行业权重，只在每行业内 top-K 挑股。
- **信息价值**: **MEDIUM-LOW**——已知方法，业界用了 20+ 年，文献早就明确。我能猜测它的效果（降低行业集中度导致的 SPY beta 部分，但 alpha 重叠不解决）。
- **实现成本**: 中——`core/data/sector_resolver.py` 已经 ship，加 sector-neutral selection mode 1 天 eng。
- **PQS 适配度**: 好。
- **verdict**: **不搜**（已知足够），但**可以直接 ship 试**作为 cycle10 一个 axis。

### D. ⚠️ Z-score continuous weighting（不再 top-N，分数高就权重大）
- **什么意思**: 把所有 79 股按 composite score z-score 排序，z > 0 的按 z 权重持仓，z ≤ 0 不持。可能持 5 只可能持 30 只。
- **信息价值**: **MEDIUM**——基础方法但 PQS 没试过。文献明确（factor-investing 教科书），但**在 long-only top-N 替代下的 NAV sibling 效果**没有特别可靠的 reference。
- **实现成本**: **低**——cycle yaml config-only 改动（construction_mode 新增）。
- **PQS 适配度**: 好。
- **verdict**: **不搜**（直接试），低成本不需要文献背书。

### E. ❌ Construction zoo (HRP / ERC / MV-opt / Black-Litterman / Kelly)
- **什么意思**: 各种 portfolio-level 权重优化算法。
- **信息价值**: **LOW**——cap_aware_risk_parity (1/σ) 已经 ship 测过 sibling-by-construction 假设（C10-2-A），权重再分配类方法降相关性 < 0.05。HRP/ERC 是同一类方法的更精细版，期望降幅相同量级。Black-Litterman 需要 forward expected return 输入，PQS 没有这个（我们做的是 lookback alpha）。
- **实现成本**: **高**——每个都 1-2 周 eng。
- **PQS 适配度**: HRP/ERC OK；Black-Litterman 不适配（forward view 缺失）；MV-opt 在 79 股上 covariance 估计噪声大，long-only 约束下 corner 解多。
- **verdict**: **不搜**。证据已经证明这一类方向是 dead end。

### F. ❌ Universe expansion (200+ 股)
- **什么意思**: 把 universe 从 79 股扩到 200+ 股。
- **信息价值**: **LOW**——math 显而易见：79 → 200 股，top-10 重叠率约 5/79 → 5/200 = 大幅下降。不需要文献。
- **实现成本**: **HIGH**——2-3 周数据 fetch + factor recompute（Task #16）。
- **PQS 适配度**: 好。
- **verdict**: **不搜**。数据工程问题，已经在 todo list (#16)，要做就 schedule 做，搜文献无信息增量。

### G. ❌ Factor family mix (fundamental + macro + sector)
- **什么意思**: cycle 用 Bucket B (EDGAR) + Macro (FRED) + Bucket C (sector) 因子做 mining。
- **信息价值**: **LOW**——Bucket A/B/C/Macro 已经 ship 143 因子，cycle09 试图用结果被 sampler architecture bug 阻断（CLAUDE.md commit `f41c7e5` 已 ship `family_first` 修复）。
- **实现成本**: **LOW**——sampler 已修，cycle09 重启即可。
- **verdict**: **不搜**。工程问题不是知识问题。重启 cycle09 即可看结果。

### H. ❌ Strategy-type swap (intraday / event-calendar / sector-rotation)
- **信息价值**: **LOW**——alt-A 已经在 Phase 3 跑出 NAV raw 0.146，证明可行；alt-B 已经在路线图等用户授权。
- **verdict**: **不搜**。已经在路线图。

### I. ⚠️ Long-only Kelly / variance-budget sizing
- **什么意思**: 不再 top-10 等权 / cap_aware；按 Kelly criterion（变种）给每个 long position 算最优 size。
- **信息价值**: **MEDIUM**——文献有 long-only Kelly 限制（Browne 1999, Cover 1991, growth-optimal portfolio under no-short）。**之前没考虑过这个轴**。
- **实现成本**: **中**——需要每个股票的 forward return 分布估计（用 lookback bootstrap 可以）。
- **PQS 适配度**: 注意——Kelly 在 79 股 long-only 容易把 portfolio 推到 corner solution（重仓 1-2 只）违反 CLAUDE.md M12 集中度 gate。需要 capped Kelly。
- **verdict**: **可选搜**。如果 A+B 搜完发现有空时间再搜；否则跳过。

---

## §3 Verdict 表

| 优先级 | 方向 | 信息价值 | PQS 适配 | 搜不搜 |
|---|---|---|---|---|
| **P1** | A. Active-share / overlap penalty | HIGH | HIGH | **搜** |
| **P1** | B. NAV-level orthogonalization (long-only constrained) | HIGH | 待验证 | **搜** |
| **P2** | I. Long-only Kelly / variance budget | MEDIUM | MEDIUM | 可选 |
| ❌ | C. Sector-neutral | LOW | HIGH | 不搜，直接试 |
| ❌ | D. Z-score continuous | LOW | HIGH | 不搜，直接试 |
| ❌ | E. Construction zoo (HRP/ERC/MV/BL/Kelly) | LOW | 混合 | 不搜（证据已 dead end） |
| ❌ | F. Universe expansion 200+ | LOW | HIGH | 不搜（数据工程问题） |
| ❌ | G. Factor family mix | LOW | HIGH | 不搜（工程 fix + cycle09 重启） |
| ❌ | H. Strategy-type | LOW | HIGH | 不搜（已在路线图） |

---

## §4 推荐 search 查询（精确，不泛搜）

### Query 1（方向 A — Active-share penalty）
1. "active share Cremers Petajisto long-only portfolio diversification anchor overlap"
2. "mining objective function portfolio overlap penalty quantitative"
3. "long-only equity factor portfolio construction with active share constraint"

### Query 2（方向 B — NAV-level orthogonalization）
1. "alpha orthogonalization long-only portfolio NAV residual"
2. "neutralized portfolio construction long-only constraint Frazzini"
3. "low correlation alpha sleeves long-only equity orthogonal returns"

### Query 3（方向 I — Kelly under long-only，**只在 1+2 完成后考虑**）
1. "long-only Kelly criterion stock selection growth-optimal no-short"
2. "capped Kelly portfolio variance budget long-only"

---

## §5 我的建议（不是决策）

**先搜 P1 两个方向**（A + B），并行。每个方向 5-10 分钟阅读。完成后再决定：

- 如果文献明确指向 "active-share penalty in mining objective" 是 attack vector → **直接进入 cycle10 PRD 设计**（这条路径事先就有 hunch）。
- 如果文献揭示 "long-only NAV-level orthogonalization 是可行新轴" → 这是**新工作流**，需要先小范围 POC 再决定要不要 commit cycle10 资源。
- 如果两个方向文献都模糊 → 跳过 P2 (Kelly)，直接试 §3 ❌ 类里的 **D (z-score continuous)** + **C (sector-neutral)** 作为 cycle10 axis（low-cost 直接 ship）。

**不要搜的 6 个方向（C-H）**：
- C/D：直接 ship 比读文献快
- E：证据已经证明 dead end
- F/G/H：工程问题或已在路线图

---

## §6 这次 audit 自身的诚实评估

### 我可能有的 bias
1. **A 方向的 hunch**：我直觉觉得 active-share penalty 应该有效。但**直觉不是证据**——文献里可能 active-share 主要用于评价（不是优化目标），加进 mining objective 可能有 well-known instability。
2. **B 方向的疑点**：long-only constraint 下做 NAV 残差化可能根本不可行——纯残差是 long-short 信号。文献可能告诉我"这一类方法不适用 long-only"。**这就是搜的价值**——确认它**不可行**也是有用结论。
3. **E (Construction zoo) 判 dead end 太硬**：我基于 cap_aware = 1-2 种 zoo 方法 + raw 只降 0.024 来归纳。但 HRP 在 institutional research 里有 5-10% diversification 数据。如果**A+B 都不可行**，回头试 HRP 也不能完全排除。
4. **不搜 cadence 的判断**：我假设 cadence "无干净证据" + "实测 cycle08 weekly 失败" 已经够。但**严格来说**，cycle08 weekly 失败是因为目标函数 / factor 选择，**不能**证明 weekly cadence 本身不行——所以单独搜"weekly long-only equity rebalance NAV correlation"或许有价值。**承认我可能漏了**。

### R4 boundary check 通过 if you accept
- 6 个不搜方向各自给了具体 dead end 理由（不是泛泛"不重要"）
- 2 个搜的方向各自给了具体 expected-info-value 表述（不是泛泛"有意思"）
- 搜完之后的决策路径都写明了

如果你同意 A+B 这两个方向，我现在就并行发 2 个 WebSearch。
