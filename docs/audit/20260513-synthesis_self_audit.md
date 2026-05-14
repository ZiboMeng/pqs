# Audit-of-synthesis：找出我刚写的 §3 哪里过度承诺 / 数字虚高

**Date**: 2026-05-13
**Trigger**: 用户："在审计一遍 然后咱们做决策"
**Method**: 逐项对 Tier 1 + Tier 2 推荐做 R3（证据真的支撑结论吗？）

---

## §1 A1 NAV-residualized mining target —— **misattribution，证据没我说的那么实**

### 我之前的 claim
> "AlphaAgent (Hu et al. 2025) S&P 500 IR 1.05 / MaxDD -9.10% 验证了 NAV-residualized 路径"

### Audit 发现
**AlphaAgent ≠ NAV-residualization**：
- AlphaAgent 用的是 **AST-originality regularization**（抽象语法树相似度对 alpha-zoo 做正则化）——这是**因子公式语法层**的去重
- 我提的 NAV-residualized = **forward return 对 fleet 残差**（Kelly-Pruitt 3-pass regression 类）——是**收益层**的去重
- 两种**完全不同的方法**，AlphaAgent 的实证结果**不能转移**到 NAV-residualization

agent 自己的报告里也说："**No published US-equity backtest with exact (e) formulation found** — this is novel ground"

### 真实状态
- 理论基础有（Kelly-Pruitt 2013/2015）
- **但没有公开的实证 backtest** 直接验证 NAV-residualized mining objective 在 long-only US 股票上的效果
- **eng cost 修正**：1-2 周 + 真正的 research risk（不是工程任务，是 R&D 任务）
- **预期效果修正**：理论上 NAV 相关性可以 by-construction <0.50 但 **long-only convex projection 之后保留 30-50% 信号**（Clarke-Silva-Thorley TC）——所以实际 NAV 相关性下限是 0.6-0.75，不是 <0.50

### Verdict
A1 是**高 leverage 但高研究风险**的方向。不应作为 cycle10 baseline；应作为**独立 R&D PRD**，1-2 周设计 + POC，再决定要不要 commit cycle10 资源。

---

## §2 A2 Multi-family mining —— **Sharpe lift 期望值有 regime conditional 风险**

### 我之前的 claim
> "+0.1-0.3 Sharpe lift expected; quality+momentum long-only retail ~1.0-1.2"

### Audit 发现
- "1.55 Sharpe" 是 factorlab/Alpha Architect 的 **research-grade long-short with leverage**——不是 PQS 的 long-only retail
- "1.0-1.2 long-only retail" 是 agent 的**翻译估计**，不是发表数字
- Robeco 2010-2019 "Lost Decade" 报告：**Value 因子在 2010-2019 大幅 decay**；Quality 在 2017-2023 也表现不佳（被 Mag-7 momentum 压制）
- **PQS validation 窗口**包含 2017/2018/2019/2021/2023/2025——其中 **2025 是 SPY 大涨年**，**Quality 因子 2025 大概率跑不赢 SPY**
- 强 force `min_families ≥ 3` 可能产生 0 archived trials（quality 因子在 PQS 2025 holdout 上 IC 弱 → 复合 alpha collapse → 0 trials pass Track A）

### 真实状态
- eng 真的 5 分钟（yaml + launcher）
- 但**期望值更不确定**：可能 +0.1-0.3 Sharpe，也可能 **0 archived trials**（跟 cycle04-08 一样）
- **最坏情况**：cycle09 重启 0 nominee + 证明 quality 因子在 PQS 框架不工作——但这**也是有价值的信息**

### Verdict
A2 工程便宜，但不应**保证** Sharpe lift；应作为**信息收集**实验。"看看 quality 因子在 PQS 上有没有 OOS alpha" 本身就值得 5 分钟。

---

## §3 A3 Pre-FOMC drift sleeve —— **CAGR 我严重高估**

### 我之前的 claim
> "稳态额外 4-5% CAGR / fleet 加约 0.15 Sharpe"

### Audit 发现
- Pre-FOMC drift "CAGR 4%" 是 **整个 capital 在 SPY 上跑了一年的等价回报**
- 但**实际**：pre-FOMC 每年只交易 24 天，**其他 95% 时间资金闲置在 cash**
- 如果 sleeve 100% 资金做 pre-FOMC，**全年 capital 回报 ≈ 4%——远输 SPY ~10-15%/yr**——**违反 beat-SPY HARD invariant**
- 现实实现：pre-FOMC 必须是 **fleet 内一小部分 sleeve（5-20% 权重）**，其他 80-95% 还在主 strategy
- Blended CAGR 拉低：80% × main_CAGR + 20% × 4% < 100% × main_CAGR
- **真实贡献**：**diversification + DD-control**，不是 **CAGR booster**
- Fleet 加约 **0.10-0.15 Sharpe**（来自 ~零相关性），但**绝对 CAGR 不增**

### 真实状态
- A3 是个**有效但低权重的 sleeve**——加进 fleet 提升风险调整后回报，但不增 CAGR
- 跟 alt-A intraday 一样：用作 fleet diversifier，不用作主策略
- 还有个**容易漏的工程**：sleeve 权重怎么算？capital allocation rules？这不是 trivial

### Verdict
A3 不该说是 "real alpha increment"；应说是 "fleet Sharpe 增量"。eng 1-2 天 + **sleeve 权重 + capital allocation 设计 +1-2 天**——总 3-4 天。

---

## §4 B1 Top-N 调整 —— **可能 fail beat-SPY 但没说**

### 我之前的 claim
> "top-20 可能让 MaxDD 从 -20% → -14%（释放 G6 Calmar gate），CAGR 仅小幅下降"

### Audit 发现
- 文献支持 top-20-30 比 top-10 **MaxDD 更优** + **Sharpe 接近**
- 但 PQS 的 Track A 包含 **2025 holdout vs_spy > 0 HARD**
- top-20/79 = 25% 池子覆盖 vs top-10/79 = 13%——top-20 离 SPY 更近，**CAGR 拖到接近 SPY 但很难超过**
- **风险**: top-20 在 2025 holdout 可能**刚好等于 SPY** → 失败 HARD gate

### 真实状态
- 文献 generic 支持
- PQS-specific 风险**没量化**——cycle04-08 sibling-by-NAV 0.9+ 已经说明 top-10 跟 SPY 高相关，扩到 top-20 只会更高

### Verdict
B1 工程便宜（cycle yaml axis grid），但**预期值偏中性**——可能改善 MaxDD 但很可能 FAIL beat-SPY。

---

## §5 B2 Quality universe-tilt subset —— **工程比我说的大 + sibling 风险**

### 我之前的 claim
> "从现 79 股挑 Piotroski ≥ 6 + FCF-yield > median 子集 (~25-35 股)，eng cost ~1 天"

### Audit 发现
- **没有现成 Piotroski 筛选 list**——cycle04-08 没用过 Bucket B 因子
- 需要：(a) 对 79 股每个 ticker 跑 Piotroski 因子计算（Bucket B 2026-05-12 ship 但只 download 了 52/59 stocks 数据 + ETF skip），(b) PIT-aware 历史筛选 list，(c) 建 universe_v2_quality.yaml，(d) multi-universe init forward manifest
- **真实 eng**: 2-3 天，不是 1 天
- 更深的风险：MSCI QUAL 跟 USMV/SPLV **同一 cluster**（都偏 low-beta low-vol）——quality universe 内部可能产生**新一类 sibling**（quality cluster sibling）

### 真实状态
- 工程比说的大
- Empirical 风险：quality subset 25-35 股太小，top-10 选 = 30-40% 池覆盖 → 极高 sibling 概率
- 跟 cycle04 cross-asset 一样：**universe 换了但 NAV 还 sibling**

### Verdict
B2 工程低估了 + sibling 风险高估了。可做但**不是 quick win**。

---

## §6 B3 SMA200 risk-off overlay —— **设计决策非 trivial + 跟 Trial 9 forward 有冲突**

### 我之前的 claim
> "1-day eng no-regret"

### Audit 发现
**两个被我跳过的关键问题**：

1. **应用层级**：fleet-level（整体 risk-off）vs sleeve-level（每个 candidate 各自做 SMA200）？
   - Fleet-level: 简单 1-day eng，但**摧毁 Trial 9 diversifier 角色**（diversifier 在 risk-off 时本应该是上涨/抗跌——overlay 会把它强制平仓）
   - Sleeve-level: 每个 candidate 各自决定——但 Trial 9 v2 已经在 forward observation，**改 sleeve 行为会让 manifest config_snapshot drift**（today 已经发生 1 次类似问题）

2. **跟 PRD-E TAA 重复**：dormant TAA 模块（commit `4bc85ab`+`288c3c0`+`281729b`）就是这个机制。Phase 3 verdict：5/7 defensive gates PASS。**SMA200 不应该重写——应该是 reactivate TAA**。

### 真实状态
- 概念正确（Faber 数据扎实）
- 但 PQS-specific 实现需要：
  - 决定 fleet-level vs sleeve-level（directional 决策）
  - 兼容 active forward observation（Trial 9 v2）
  - 不要 reinvent PRD-E TAA wheel
- 真实 eng: 决定 + reactivate TAA 集成 = 3-5 天，**取决于设计决策**

### Verdict
B3 不是 1-day no-regret——是**3-5 天 with design decision**。应该叫 "reactivate PRD-E TAA on user-go"，不是 "新建 SMA200"。

---

## §7 我漏掉的几个重要 consideration

1. **2025 holdout vs SPY HARD gate**：2025 SPY 大涨 + Mag-7 dominate；任何**偏 quality / 偏 low-vol / 偏 small-cap** 的 tilt 在 2025 holdout 大概率 fail HARD gate
2. **Test surface**：A1 / B1 / B3 每个都需要单测 + 集成测试 + acceptance regression。我**没预算测试时间**
3. **Forward observation 兼容**：Trial 9 v2 在 forward TD007 of TD60。任何**修改 universe.yaml / RESEARCH_FACTORS / sleeve 行为**的轴都会让 manifest 漂移（今天上午已经发生过）
4. **Cycle stop rule**：cycle04 close memo committed "cycle 05 也 0 nominee 就停"——我们现在已经 9 个 cycle。**cycle10 mining 本身需要先 justify 为什么不停**
5. **资源 / 时间 budget**：用户运行 PQS 个人，时间是真稀缺资源。3-5 周做 A1 是真正的机会成本

---

## §8 修正后的真实 cycle10 选项

### **真低成本 + 真低风险**（"信息收集" 类，做就对）

| Axis | Real eng | Real expectation |
|---|---|---|
| **A2 cycle09 multi-family 重启** | 5 min | 可能 0 nominee 也可能 +0.1 Sharpe；**任一结果都有信息价值** |
| **A3 pre-FOMC sleeve** | 3-4 天（含 sleeve 权重设计）| Fleet +0.10-0.15 Sharpe，**不增 CAGR**；纯 diversifier |

### **中成本 + 中风险**（需用户 directional 决策）

| Axis | Real eng | 关键风险 |
|---|---|---|
| **B1 top-N 调整 grid** | 1 天 | 可能 fail 2025 beat-SPY HARD |
| **B2 quality universe-tilt** | 2-3 天 | quality cluster 内部 sibling 风险；2025 fail 风险 |
| **B3 reactivate PRD-E TAA** (不是新 SMA200) | 3-5 天（含 forward 兼容设计）| 跟 Trial 9 v2 active forward 兼容性 |

### **高成本 + 高风险**（真 R&D）

| Axis | Real eng | 关键风险 |
|---|---|---|
| **A1 NAV-residualized mining** | 1-2 周（含 POC）| **没有公开实证 backtest**；long-only TC 损失 30-50% 信号；可能比 active-share 强但不保证 |

---

## §9 修正后的决策矩阵

**最稳健 baseline（"做 will-not-regret 的事"）**：
- A2 立刻跑（5 min）→ 看 quality 因子有没有用
- A3 ship（3-4 天）→ 加纯 diversifier sleeve
- 等 A2 结果 → 决定要不要走 B1/B2/A1

**激进 + 真 R&D 路线**：
- A2 + A3 同时启动
- 并行 A1 PRD + POC（1-2 周，研究类）
- 不动 B1/B2/B3 直到 A1 POC 出结果

**保守 + 等 evidence 路线**：
- 只 A2（5 min）
- Wait Trial 9 v2 forward 跑出 TD30+ 数据再决定

---

## §10 我的真实建议（人话）

我之前写的 §3 用了**虚高的数字**（pre-FOMC CAGR / multi-family Sharpe lift / AlphaAgent IR）+ **低估了几个 eng cost**。修正后：

**真最优**: **A2 + A3 + 预算 A1 POC**
- **A2 (5 min)**: 不管结果如何都有信息——quality 因子的 IC 在 PQS 数据上**未知**，跑一下就知道
- **A3 (3-4 天)**: 纯增量 diversifier，工程小，风险小，跟 Trial 9 v2 不冲突
- **A1 POC 启动（1 周）**: 写 PRD + 设计 POC（不实施全 mining，只在历史数据上跑 1 个 trial 看 NAV 相关性是否真破）

**不立刻做**：
- B1（top-N）：等 cycle09 multi-family 重启结果再决定 top-N 是不是 cycle10 axis
- B2（quality universe）：sibling 风险 + 工程比想象大；不值得现在做
- B3（TAA 重启）：需要等 fleet 有 ≥2 NAV-distinct 候选；现在只 Trial 9 单候选

要不要按这个**修正后**的 baseline 走？或者你 prefer 别的组合？
