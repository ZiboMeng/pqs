# 审计 v2：每条结论都加上"前提范围"

**Date**: 2026-05-13
**Trigger**: 用户指出 v1 audit 过度泛化——"construction 单换没用"是基于 n=1 的实测，可能只能说明**那一种** construction 没用，不能说明**所有** construction 都没用。
**Method**: 对 v1 audit 的每条结论加 epistemic-rigor 限定词。

---

## §0 核心 mistake（v1 的）

v1 写："construction 单换没用——raw 只降 0.024"。

**真实情况**：我们**只测了一种** construction swap：
- **global_top_n**（取前 10 名按分数排序，等权）
- → **cap_aware**（取前 10 名，但单股 ≤10%、行业簇 ≤20%；本质还是 fixed-rank 选股 + 权重稍重排）

这两种**都是"按 composite score 排前 10 名"的 fixed-rank selection**，差别只在选完之后的权重再分配。

**没测的 construction**（清单见 §2）远多于测过的。

---

## §1 修正：每个 axis 结论的真实范围

### 1.1 Construction axis

| 测过的方法 | raw NAV 相关性结果 |
|---|---|
| global_top_n (RCMv1, Cand-2 baseline) | 0.898（基线） |
| cap_aware（cycle07a T3 vs RCMv1） | 0.874 (Δ −0.024) |
| cap_aware_risk_parity (C10-2-A 已 ship)** | **未实测 mining** |
| cap_aware_cross_asset（cycle04 Cluster A） | 0.66-0.70（但同时换 universe，混淆） |

**v1 错误结论**: "construction 没用"  
**v2 修正**: "fixed-rank top-N + 权重再分配 (cap_aware) 没用——只降 0.024。**risk-parity 权重 / Kelly / mean-variance / 因子正交权重 / active-share penalty 等其他 construction 方法均未实测**。"

### 1.2 Factor axis

| 测过的因子换法 | 结果 |
|---|---|
| RCMv1（4 因子，全 technical+market） vs Cand-2（3 因子，全 technical+momentum） | raw 0.898（**零共享因子**） |

**v1 错误结论**: "factor swap 没用"  
**v2 修正**: "**同族因子**（都是 technical/momentum/market-state，无 fundamental / sector / macro）的 swap 没用。**跨族因子组合**（fundamentals from Bucket B EDGAR / macro from FRED / sector rotation from Bucket C）**未实测**——cycle09 试图测时被 sampler architecture bug 阻断。"

### 1.3 Cadence axis

**v1 结论**: "inconclusive（cycle09b vs cycle08 = 0.02 但被 cycle08 失败污染）"  
**v2 维持**: 同 v1，结论本来就保守。**仍然 inconclusive**。

补充：**单独控制因子+construction 不变只换 cadence** 的实验 PQS 历史上**没做过**。这是个空白。

### 1.4 Universe axis

**v1 结论**: "inconclusive（cycle04 cross-asset 降到 0.66 但同时换 construction）"  
**v2 维持**: 同 v1。但加：**只换 universe（53→200+ 股，仍长仓 monthly top-10 cap_aware）**这种干净实验也没做过。multi-universe loader (C10-2-B) 刚 ship，但 200+ 股 universe yaml + 数据 backfill 还没做。

### 1.5 Selection-rule axis（**全新 axis，v1 漏掉**）

**v1 完全没把 selection rule 单独拎出来**。Selection rule = 怎么从 composite score 决定持仓权重，**不只是 top-N + weight scheme**。

| 测过 | 未测 |
|---|---|
| top-N=10 fixed-rank（所有 PQS 历史 cycle） | z-score 权重（持仓 = max(0, z_score × position_size)，没有 N 上限） |
|  | Kelly-style weighting |
|  | Hierarchical Risk Parity (HRP) |
|  | Equal-Risk-Contribution (ERC) |
|  | Sector-neutral construction |
|  | Beta-controlled construction (β=0.8 target) |
|  | Active-share penalty: argmax(composite − λ·overlap_with_RCMv1) |
|  | Black-Litterman with factor views |

**这些没测的 selection rule** 跟 cap_aware 是**根本不同**的——cap_aware 还是先排名再调权重，但 z-score / Kelly / HRP / active-share penalty 改变了"哪些股票进组合"本身。

### 1.6 Strategy-type axis（v1 提了但弱化）

alt-A 日内反转 raw 0.146 vs RCMv1。

**v1 模糊地说**: "整个 bundle 换才破"  
**v2 精确**: "**当 strategy-type 换到 entry/exit 机制完全不同**（日内反转：只在反转条件触发时持仓 → 持仓时间 16% vs 长仓 daily 持仓时间 100%），NAV 相关性破了。这**确认 strategy-type 可以破**，但**不能用作 'long-only-daily 内 construction 无解'的反证**——它跑出了 long-only-daily 框架本身。"

---

## §2 没测过的方法清单（凭这个去 WebSearch 才有意义）

### Construction 子方法（v1 误以为已经测过）
- **Risk-parity** (1/σ weighting)
- **Hierarchical Risk Parity (HRP)** (Lopez de Prado)
- **Equal-Risk-Contribution (ERC)**
- **Mean-variance optimized** (Markowitz + shrinkage covariance)
- **Black-Litterman** (factor-view-based)
- **Kelly criterion sizing**
- **Factor-orthogonalization weights** (使 portfolio 在某些 factor 上 exposure=0)

### Selection-rule（构成"挑哪些股"的根本规则）
- **Z-score continuous weighting**（不再 top-N，分数高就持仓权重大，分数低就 0）
- **Active-share penalty**（mining 目标函数加 −λ·overlap_with_anchor）
- **Cross-sectional rank with threshold**（只持 z > 1.5 的股票，可能 5 只可能 30 只）
- **Quintile long-short within long-only**（持 Q5 长仓，Q1 不持但不做空 → 实际等同 1/N over Q5）
- **Sector-neutral selection**（每个 GICS 行业内 top-K，强制行业暴露 = SPY 比重）
- **Tournament selection**（多轮淘汰，与单次排序不同）

### Cadence
- **Weekly** + 真有 alpha 的因子（cycle08 用过 weekly 但 factor 没 alpha，污染了证据）
- **Daily**
- **Quarterly**
- **Event-driven**（earnings / macro release）
- **Mixed-cadence**（核心月调仓 + 卫星周调仓）

### Universe
- **200+ 股扩大池**（C10-2-B loader 已 ship，universe yaml + data backfill 没做）
- **Factor-filtered subset**（只在 low-vol 股票里挑 / 只在 high-quality 股票里挑）
- **Sector-tilt subset**（去掉 tech 偏重 / 去掉金融）
- **Mid-cap 池**（避开 SPY 重权股）
- **Multi-asset 永久**（加债 / 大宗永久存在，不是 cycle04 那种 cross-asset 实验性）

---

## §3 修正后的 verdict（带前提）

| 假设 | 测过的实例 | 修正后的 verdict |
|---|---|---|
| **任何** construction 单换都不能破 sibling | 只测了 cap_aware（fixed-rank + 权重重分配） | **WEAKLY SUPPORTED** ──仅证明"权重重分配类"不破。risk-parity / HRP / Kelly / active-share / factor-orth 没测。 |
| **任何** factor swap 都不能破 sibling | 只测了 same-family swap | **WEAKLY SUPPORTED** ──仅证明同族 swap 不破。跨族（fundamental + macro + sector）没测。 |
| Cadence 单换能破 sibling | 没有干净证据 | **UNKNOWN** |
| Universe 单换能破 sibling | 没有干净证据 | **UNKNOWN** |
| **整个 bundle**（long-only daily + monthly + top-N=10 + 79 池 + fixed-rank）是绑死约束 | alt-A 换了全 bundle = 0.146；cycle04 换了部分 bundle = 0.66 | **CONDITIONALLY SUPPORTED** ──在 PQS 历史已测的子空间内 bundle 强相关；但**bundle 是否真的"绑死"，等价于"未测过的所有 construction / selection-rule / cadence / universe 方法都不能破"**——这是**强归纳**结论，证据不足以支撑。 |
| Strategy-type 换能破 | alt-A 日内反转 = 0.146 | **STRONGLY SUPPORTED**（但是 trivial：换了整个游戏） |

---

## §4 这次 audit 的诚实自我评估

### v1 的两个根本错误
1. **n=1 当 n=∞**：把 "cap_aware 没用" 等价成 "construction 没用"
2. **省略了 selection-rule 这个独立 axis**：v1 把 selection-rule 和 construction 混在一起谈

### 修正后对下一步的影响
- v1 推荐："WebSearch 3 个方向（construction / selection-rule / universe）"
- v2 修正：仍然推荐 WebSearch，但**关键词不能用"SOTA construction"**——要用"破长仓 top-N sibling"这个具体问题，因为：
  - 学术 literature 里 "SOTA construction" 一般讨论 risk-parity / HRP / Black-Litterman 在 institutional 设置下的表现
  - 我们的问题是 "long-only top-N daily 框架内如何 break NAV sibling"，更接近 "low-correlation long-only equity sleeves" 或 "active share maximization"
  - 选错关键词会拉回到泛 construction，错过真正相关的 literature（active-share / portfolio diversification under benchmark / α-orthogonalization）

### 还要不要做 WebSearch？
要，但**搜词列表先列**，避免又一次"埋头试错"。

---

## §5 修正后的下一步建议（不是决策）

WebSearch **3 组并行查询**：

**Query 1**: long-only equity portfolio diversification under fixed universe
- "low correlation long-only equity portfolios"
- "active share maximization construction"
- "portfolio diversification within benchmark universe"

**Query 2**: selection rule alternatives to top-N
- "continuous weight portfolio z-score equity"
- "long-only Kelly criterion stock selection"
- "hierarchical risk parity HRP long-only stock"

**Query 3**: alpha orthogonalization at NAV level
- "NAV correlation orthogonalization alpha sleeves"
- "factor neutralization portfolio construction"
- "correlation budget mining objective"

**WebSearch 完成后**: 把找到的方法逐个对照 §2 "没测过的方法清单"——看 literature 怎么说哪个有希望破 long-only top-N sibling。然后**才**决定要不要 cycle10 axis 选什么。

不预设答案。可能 literature 说 "active share + sector-neutral 能破"，也可能 literature 说 "long-only daily 框架内 sibling 无解，必须换 strategy-type"——两种结论我都接受。
