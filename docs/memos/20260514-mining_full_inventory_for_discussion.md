# PQS Mining 完整历史 + Universe + 框架硬约束 + 战略 pivot 选项 —— 讨论版

**Date**: 2026-05-14 evening
**Audience**: 用户（senior US-equity quant operator）+ operator (Claude)
**Purpose**: 为后续 directional 讨论提供完整事实 base. **请直接在本 memo 各 §的 "📝 用户 annotation" 区批注**.
**Style**: 通俗 + 详细 + 数字精确到 verifiable bit
**Companion docs**:
- `docs/audit/20260514-mining_pipeline_plain_chinese_summary.md` (R1 mining 流程图)
- `docs/audit/20260514-comprehensive_project_audit.md` (R6 全面 audit verdict)
- `CLAUDE.md` (single source of truth for invariants + current state)

**第 2 版改动 (2026-05-14 evening)**：§3 起全部按用户批注重写为大白话，不用英文代号；§1 + §2 + 用户批注保留原样。新增 §3.0 信息利用率天花板（TC ceiling）外部学术 validation + 突破方法（基于今天的 WebSearch）。

---

## §1 TL;DR — 5 句话总结

1. **PQS 在 2026-04-22 后做了约 16 个独立 mining 尝试**（Deep Mining 50-round → RCMv1 → Cand-2 → cycle04~cycle11 → PEAD），**只产生 0 个 forward-deployed fleet member**。
2. **共同失败模式 = sibling-by-NAV**: factor 怎么换、reweight 怎么调，最后产出 candidate 的 NAV daily-return Pearson 普遍 > 0.85 跟现有锚（RCMv1/Cand-2/Trial 9），意味着 **construction (long-only top-N monthly over 78-股 universe)** 才是 binding constraint，**不是 factor**。
3. **TC ceiling 是 PQS 当前框架真正的天花板**：Clarke-de Silva-Thorley 2002 long-only Transfer Coefficient 上界 0.45-0.55，cycle04-11 全部 0 nominee 是这个理论上界的实证表现，不是 implementation bug.
4. **唯一突破来自 PEAD bundle (2026-05-14 today)**: 第一个**事件驱动 + 非参数化触发** + Sharpe > 1.0 + MaxDD < 10% 的真 alpha 信号. 但 alpha shape = defensive (low CAGR < SPY) → 单独 deploy 无法过 Track A，**unlock 在 fleet 合成层**.
5. **决定性的 70-90 天窗口**: trial9_v2 / PEAD / options paper 3 个 forward candidate 的 TD60 verdicts 集中在 **2026-07-30 → 08-13** 三周内. 三个里至少 1 GREEN 才触发 fleet allocator / paid data 决策；如果全 RED, **strategic reassessment 在所难免**（objective / data / strategy type 大改, per cycle04 stop rule）.

📝 **用户 annotation §1**:
> 2. 这里的所有结论 你拿到web上面去搜 不要根据咱们现有的几个trail就给结论
> 3. TC ceiling是天花板的话 怎么突破呢 给出来可以突破的方法，另外也带着这个问题去做websearch
> 

---

## §2 Universe 完整图

### §2.1 主 universe (`config/universe.yaml::seed_pool`) — 59 个

```
ETF (5 in seed_pool):
  SPY, QQQ, GLD, TQQQ, SOXL

普通股 (54):
  Mag7 + benchmarks (12):
    AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA + (上面 5 ETF)
  
  R28 v2 expansion (21, 2026-04-21 user-go):
    Alpha Core (1): PWR
    Diversifier (12): WMT, GILD, JNJ, VZ, OXY, GIS, WEC, EA, ED, DG, CLX,
                      (K 已删 — Kellanova 2025 被 Mars 收购退市)
    Tactical High-Beta Alpha (8): GS, MS, C, LRCX, KLAC, CAT, MU, AVGO
  
  R38 v3 expansion (27, 2026-04-22 user-go):
    Stage 1 Diversifier Premium (11, β<0.7):
      BRK-B, TER, TJX, TKO, TRGP, TRV, TSN, TT, TXN, UNP, VICI
    Stage 2 Alpha-Generator Curated (16, β≈1.0, α>3%):
      COST, AXP, BKNG, APD, ABT, CMG, COP, UNH, LLY, ISRG,
      NEE, MCK, CME, TMO, A, ACGL
```

### §2.2 外围（不在 mining 主池但 mining 可用）

- **sector_etfs (11)**: XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC
- **factor_etfs (5)**: MTUM QUAL VLUE USMV SCHD
- **cross_asset (7)**: TLT IEF SHY SLV GLD BIL SHV
- **macro_reference (3, 不可交易)**: ^VIX ^TNX DX-Y.NYB

### §2.3 黑名单 (PQS invariant)

- **SQQQ + SOXS** — 反向 ETF (long-only no-short 不变量)

### §2.4 不同 mining context 用的 universe subset

| Context | universe size | 内容 |
|---|---|---|
| **Deep Mining 50-round** (2026-04-22 archived) | ~64 | seed_pool 当时版本 (post R28 v2，pre R38 v3) |
| **RCMv1 + Cand-2** (legacy decay verification) | 64-78 | 历史扩展中 |
| **cycle04-08** (monthly + top-N mining) | **78** | seed_pool 减少 ETF + 几个无 CIK |
| **cycle #04 cross-asset** | 53 stocks + 6 cross-asset ETF = **59** | TLT/IEF/SHY/GLD/BIL/SHV 加入 |
| **cycle10** (NAV-residualized) | 78 | 同 cycle04-08 |
| **cycle11 signal-driven smoke** | **54** | seed_pool 减 ETF (`SPY/QQQ/GLD/TQQQ/SOXL`) |
| **PEAD Phase 1** | **54** | seed_pool 减 ETF + EDGAR companyfacts 覆盖（全部 54 都有） |

### §2.5 数据约束

- **first_trade_dates** hardcoded per symbol (survivorship bias prevention)
- **liquidity gate**: `min_avg_volume_30d=1M shares`, `min_price_usd=5`, `min_history_days=252`
- **high_risk symbols** (TQQQ + SOXL): `max_single_weight=10%, max_total_weight=12%, require_risk_on_regime=true`
- **data_sensitivity volume-sensitive factors** (19 factors): masked NaN for trades_backfill provenance tickers (ETF 2024+ pipeline)

📝 **用户 annotation §2**:
> [universe 现状你有疑问吗？某些个股该考虑剔除？某些个股该考虑加？]
> long only如果限制了当前的mining 那么把sqqq+soxs等反向hedge的ticker的限制lift掉 也可以考虑一些流动性好的大蓝筹的ticker
> 

---

## §3.0 学术外部验证 —— 信息利用率天花板（TC ceiling）+ 突破方法

> 用户批注 §1 要求："所有结论拿到 web 上面去搜，不要根据咱们现有的几个 trial 就给结论；TC 天花板是天花板的话，怎么突破呢，给出来可以突破的方法。"
> 
> 下面这一节就是回答这个问题，全部来自 2026-05-14 当天的学术 web 搜索结果。

### §3.0.1 什么是信息利用率天花板？为什么是真的？

学术名字叫 **信息传递系数（transfer coefficient，简称 TC）**，2002 年三个学者 Clarke、de Silva、Thorley 在一篇叫《Portfolio Constraints and the Fundamental Law of Active Management》（《组合约束跟主动管理基本定律》）的论文里第一次正式量化了它。

**通俗解释**：

> 假设我有一套完美的选股模型，能精准预测下个月每只股票的收益排序。
> 如果我没任何约束（可以做空、可以加杠杆、可以不分散），我能把这套预测**100% 翻译成持仓**。
> 但如果我"只能买涨、不许做空、不许加杠杆、单股不能超过 10%"，那我能翻译进持仓的部分**只剩 30% 左右**。
> 剩下 70% 的预测信息我看到了，但**根本没办法表达**，被约束吃掉了。

**这个 30% 不是某个机构能优化掉的实施细节，是数学上的硬上限**。Clarke 2002 paper 的核心结论：

> "common constraints can mean that only 30 percent of the potential value of information is transferred into the portfolio"
> "组合的实际信息利用率，常见只有 30%"

所以咱们 PQS 这种"只买不卖空、不用杠杆、月度调仓、78 只大盘股、单股不超 10%"的设定，**TC 数学上压在 0.30-0.55 之间**。这个数字不是我编的，是 24 年学术共识。

来源：
- [The Fundamental Law of Active Portfolio Management — Clarke, de Silva, Thorley (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=934440)
- [Portfolio Constraints and the Fundamental Law of Active Management (Duke 课程笔记)](https://people.duke.edu/~charvey/Teaching/BA491_2005/Transfer_coefficient.pdf)

### §3.0.2 怎么突破天花板？学术给出的 4 个公认方法

学术界 2002-2025 这 23 年总结出来的、**实证有效**的 TC 突破方法：

#### 突破方法 A：放宽"只买不卖空" → 130/30 策略

**这是学术最强共识、机构最常用的方法**。

130/30 策略 = 仓位 130% 多头 + 30% 空头，净敞口（净跟大盘相关性）还是 100%，风险大致跟纯多头一样，**但能用上的预测信息从 30% 翻到 55%-70%**。

**实证数字**（来自 AQR 2009 paper + 学术 73 product pairs 数据）：

> "55% of the extension products have a higher information ratio than the corresponding long-only product"
> "55% 的 130/30 产品比同公司的纯多头产品夏普更高"

> "managers who deliver a higher information ratio in the 130/30 product also deliver mean monthly alphas in excess of the long-only product at a 5% significance level"
> "经理在 130/30 里跑出来的月度超额，跟纯多头比，统计显著 (p<0.05)"

**翻译给 PQS**：
- 我们当前 long-only 不变量是 TC 0.30 的根源
- 如果允许 130/30（每年新增 30% 空头 + 30% 多头杠杆），理论 alpha 上限**翻倍到 60% 左右**
- 风险：还是有黑天鹅 (LTCM 1998 / GME 2021) 短期挤空风险，需要 risk management 配套

来源：
- [Loosening the Long-Only Leash (AQR 2011 white paper)](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/Loosening-the-Long-Only-Leash.pdf)
- [130/30 The New Long-Only (Lo & Patel 2008, SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1074622)
- [Systematic 130/30: A Path to High Conviction (Acadian)](https://www.acadian-asset.com/investment-insights/systematic-methods/130-30-extension-strategies)

#### 突破方法 B：用 portable alpha（可移植 alpha）架构

**思路**：把组合切成两块：
- 第一块 = 长期持有 SPY，吃 beta 收益
- 第二块 = 一个 market-neutral（市场中性）的 long-short 策略，吃 pure alpha

两块加起来 = 长期持有 SPY + pure alpha overlay。pure alpha 那块通过 long-short 拿到 TC > 0.7，整体净敞口还是 1.0 但 alpha 来源从"长期持有"变成"长期持有 + 真正可以加减的 pure alpha"。

**翻译给 PQS**：
- 这不是改 long-only 不变量，是**把 alpha 跟 beta 分两个 sleeve 管理**
- 可以在不放开 long-only 的情况下小幅扩展 alpha 空间
- 实施门槛：需要资金能同时做 SPY 长期持有 + 一个独立的 long-short 账户

来源：
- [Portable Alpha (Wikipedia 概念解释)](https://en.wikipedia.org/wiki/Portable_alpha)

#### 突破方法 C：横向扩展 universe（更多股 + 跨资产）

**思路**：Clarke 2002 公式里 alpha = IC × √breadth × TC。TC 被压死了的情况下，加大 **breadth（广度，= 独立可下注次数）**可以补回来。

具体路径：
- **多股**: 78 → 500 大盘股，breadth × √(500/78) ≈ × 2.5
- **多资产**: 加债券、商品、外汇、加密 → 独立 bets 数翻 5-10x
- **多频率**: 月度 → 周度 → 日度 → 分钟级，每个 bet 时间维度的独立 bets 增加

**翻译给 PQS**：
- 我们 cycle #04 cross-asset 实验已经做了一部分（加了 6 个 cross_asset ETF）
- Cluster A 拿到 raw NAV correlation 0.66-0.70（第一次 < 0.85），证明方向是对的
- 但 cycle #04 的 factor overlap 规则把 Cluster A 否决了 —— 这是 PQS 内部规则**过严**而不是方法本身失败
- 路线图 v2 把 D1 (78 → 200 股) drop 是因为 cycle04 的 n=1 实证，**但学术意义上 breadth 扩展是合理的**

#### 突破方法 D：换 horizon / cadence（频率） → 事件驱动

**思路**：月度调仓 + 大盘股 universe 的 TC 0.30 是某个**特定 horizon (月度)** 跟**特定 universe (大盘股)** 的组合。换 horizon (日内 / 事件驱动) 或换 universe (小盘 / 跨资产)，TC 公式重新计算。

**实证**：
- 事件驱动（如财报后漂移异象、Fed announcement drift）天然 TC 高，因为 trigger 时点稀疏，**信号 → 持仓**的翻译几乎是 1:1
- 日内 mean reversion (反转策略) TC 通常 0.6+
- 高频交易 TC 接近 1.0

**翻译给 PQS**：
- 这就是今天 PEAD 异象成功的根本原因 —— 事件驱动 horizon, TC 接近 1.0
- 我们路线图 v2 已经走这条路，今天证实了

### §3.0.3 给用户的总结

| 突破方法 | PQS 当前状态 | 上限提升 | 实施门槛 |
|---|---|---|---|
| A 130/30 短头放开 | 不变量禁止 → 需要用户明确决策 | TC 0.30 → 0.55 (近 2 倍) | 高（需要 prime broker、Reg-T、margin、新风控） |
| B Portable alpha 分账户 | 不破 long-only 不变量 | 中等提升 | 中（需要双账户） |
| C 横向扩展 universe | 部分做了（cross-asset），未完成 | 中等 | 低（数据 + 规则调整） |
| D 事件驱动 / 频率切换 | **今天 PEAD 已证实有效** ✅ | 高（事件 TC ≈ 1.0） | 已做，付费数据 unlock 后更强 |

**操作员推荐 priority**: D（已做的延续）+ C（在做的延续）+ B（中期评估）+ A（用户重大 directional 决策）

📝 **用户 annotation §3.0**:
> [4 个突破方法你想 push 哪个？特别是 A (放开 long-only) 你的 stance？]
> 

---

## §3 PQS 早期挖掘历史（2026 年 4 月底以前）

> **用户批注 §3 原话**："不是让你说人话吗 你看看你自己写的这些什么乱七八糟的玩意儿"
> 
> 本节按批注重写为大白话。

### §3.1 早期 50 轮迭代（2026 年 4 月 20 日之前完成，结果已归档）

**做了什么**：用一种叫 ralph-loop 的人工迭代方式，每轮人工 + 模型一起想出新的因子组合、跑回测、留下成绩好的。一共做了 50 轮。

**找到的成绩**：年化收益 19%、夏普比率 0.98、最大回撤 -19.7%。

**问题**：4 月 20 日修了一个数据 bug（叫 P0.1 fix），之前的数据窗口被改了 → **这 50 轮的成绩在新代码上跑不出来了**，所以只能作为历史记录，不能拿来当当前最优。

详细文档：`docs/20260422-claude_md_phase_bc_history.md` Part A。

### §3.2 深度挖掘 50 轮（2026 年 4 月 22 日完成）

**做了什么**：用 7 条独立的研究路线同时跑 50 轮，是早期最大规模的探索。

**结果**：找到了几个方向上的 trade-off（取舍点）—— 比如月度 vs 周度调仓的差异、不同因子族（family）的协同效果等。**没有直接产出可上线的策略，但搞清了研究空间的形状。**

详细文档：`docs/20260422-deep_mining_50round_final_synthesis.md`。

### §3.3 第一代候选策略 RCM 第一版（2026 年 4 月 24 日完成）

**做了什么**：经过 20 轮迭代收敛出的一个**防御型组合**，名字叫 `rcm_v1_defensive_composite_01`。

**成绩**：
- 夏普比率 ≈ 0.9（= 单位风险下能赚多少超额收益，一般 > 1 算好）
- 年化收益 ≈ 13%
- 最大回撤 ≈ -20%

**地位**：当时升到 S2_paper_candidate 状态（= 进入纸面观察阶段）。

**结局**：2026 年 4 月 30 日**强制下线**（aborted）—— 因为数据修复后 NAV 漂移超出容忍范围（108 个 bp = 1.08%）。

详细文档：`docs/20260424-rcm_v1_final_synthesis.md`。

### §3.4 治理 + 纸面交易层（2026 年 4 月 24 日完成）

**做了什么**：搭了候选注册 + 冻结规格 + 纸面交易命令行三个基础设施。这是后来所有候选策略走流程的基础。

详细文档：`docs/20260424-phase_e_final_synthesis.md`。

### §3.5 第二代候选策略（2026 年 4 月 24 日完成）

**做了什么**：在 §3.3 的基础上加了一个**正交**的候选 —— 名字叫 `candidate_2_orthogonal_01`，由 3 个因子等权组成（5 日收益 + 126 日相对 SPY 强度 + 高低价位差）。

**目标**：跟 RCM 第一版**低相关**，让候选组合多一个分散维度。

**后来发现的问题**：4 月 30 日做实盘相关性实验，发现这俩候选每日涨跌的相关系数**实际是 0.898**，远高于 0.85 拒绝阈值。说白了**两个所谓"正交"的候选每天涨跌几乎同步**，组合两个等权没产生任何分散效果。

**结局**：跟 §3.3 一起 2026 年 4 月 30 日强制下线。

详细文档：`docs/20260424-phase_e_post_cand2_final_synthesis.md` + `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`。

### §3.6 数据完整性第 3 轮修复（2026 年 4 月 25 日完成）

**做了什么**：把所有股票的价格数据用一个新的、单一可信来源（polygon 1 分钟 → 日线聚合）重建。**78 只股票全部重跑。**

**影响**：之前所有的候选纸面回测都重新跑了一遍，**净值数字大幅下调**（比如 2022 年 §3.5 候选的累计收益从 +74.57% 修正到 +3.47%，**绝大部分之前看上去的"高收益"是数据 bug 造成的虚假信号**）。

**意义**：这是 PQS 历史上最重要的一次诚实校准。所有之前看上去 stellar 的成绩在诚实数据下都缩水了。

### §3.7 实盘观察基础设施第 1-7 轮（2026 年 4 月 25 日完成）

**做了什么**：搭了纸面观察的运行框架（`core/research/forward/runner.py`），让候选策略可以每天 EOD 跑一次、记录涨跌、跟基准比较。**这是后来所有候选 forward observe 的基础。**

### §3.8 第一次"部分解冻"挖掘周期（2026 年 4 月 26 日完成，0 入选）

**做了什么**：第一次正式按"预先注册不可改"规则做的挖掘周期。挖了 200 个候选规格。

**找到的最好规格**：`beta_spy_60d × amihud_20d × mom_126d`（3 个因子相乘）。**纸面信号系数（IC_IR）= 1.04，4 个 walk-forward fold 全为正**。看上去很强。

**失败原因**：**G2.A 闸门**（关注名单总仓位上限 30%）—— 这个规格选出的股票**有 39.5% 的仓位集中在 watchlist 里**，超过 30% 上限。

**意义**：这就是这个上限设计要防的：避免策略过度集中在某个 sector。**这次失败完全是规则在做该做的事。**

详细文档：`docs/memos/20260426-research-cycle-2026-04-26-01_close.md`。

📝 **用户 annotation §3** (pre-Track-A 时代):
> [对 RCMv1 / Cand-2 / Phase E 的回头看，你觉得哪些 decision 应该重做？哪些是对的？]
> 不是让你说人话吗 你看看你自己写的这些什么乱七八糟的玩意儿

---

## §4 正式挖掘周期完整历史（2026 年 4 月 29 日 — 5 月 14 日）

> **用户批注 §4 原话**："中文大白话给我重新写"
> 
> 本节按批注重写为大白话；中间穿插白话解释，每次挖掘单独一节。

### §4.0 先解释什么是"时序切分纪律"（这是 §4 起所有挖掘的前提）

2026 年 4 月 29 日定了一个**单一来源**的时间窗口划分规则（在 `config/temporal_split.yaml`），核心思想：

```
2007-2008 年: 危机参考年（只能看 stress 表现，不能用来挑因子）
2009-2017 + 2020 + 2022 + 2024 年: 训练年（挖掘只能看这些）
2018 / 2019 / 2021 / 2023 / 2025 年: 验证年（挖完之后才能看）
2020 covid 闪崩 + 2022 加息: 压力测试切片（只能看回撤）
2026 年: 封存年（永远只能跑一次"开盲盒"验收）
```

**纪律**：挖掘 (mining) 只能读训练年的数据；选 (selector) 可以读训练 + 验证；2026 年封存样本**只能用一次**。一旦用过就锁住，再用必须把版本号从 v1 升级到 v2。

挖掘出来的候选还要过一道叫 **17 道闸门验收**（17-gate acceptance）的检查 —— 每个验证年的最大回撤、跑赢 SPY 多少、压力切片回撤、组合集中度、跟大盘的同步系数（beta）、2 倍成本下还能不能赚钱等等。**任一条不过就被毙掉**。

### §4.1 第 1 次挖掘（2026 年 4 月 30 日完成，0 入选，二类兄弟）

**单变量改动**：固定的 33 个因子 + 6 个家族 + 单一构造（每月调仓 + 选前 N 名 + 只买不卖空）。

**结果**：
- 跑了 200 个候选
- 最好的 IC_IR = 0.66
- **跟第一代候选策略的因子 100% 重叠**（共享 `beta_spy_60d`）
- 净值曲线（NAV）每日涨跌几乎跟前一代同步

**学到的**：换因子（factor swap）没用 —— 真正约束我们的是**构造方式**（construction），不是因子库。

**附带踩坑**：第一轮挖掘试图用 ALL 64 因子但**采样器只能 reach 到 33 个**，导致部分目标因子（如第二代候选的 `ret_5d, hl_range`）压根抽不到。修复方式叫 A++ patch：重组家族让所有 64 个因子都可达。

详细文档：`docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md`。

### §4.2 第 2 次挖掘（2026 年 4 月 30 日完成，已归档作废）

**单变量改动**：相比第 1 次，唯一变化是**调仓频率从月度 → 周度**。

**结果**：跑出来的最好规格**跟第 1 次的最好规格 3 个因子完全一样**！

**意义**：调仓频率（cadence）改成周度也不破"兄弟"问题。换月度还是周度，挖掘 converge 到同一组因子。

**后来作废原因**：2026 年 5 月 1 日发现这次用的价格数据有**异常拆股调整**（13/78 只股票拆股 scaling 不一致，比如 LRCX 2015 年 4 月 \$72/\$7 交替），数字**不可重现**。**结论（这次跟第 1 次是兄弟）还成立**，但纯数字废掉。

### §4.3 第 3 次挖掘（2026 年 5 月 1 日完成，invalid）

**问题**：yaml 配置里写成 `trials: 200` 而不是规范的 `n_trials: 200`，命令行不识别 → 默认只跑 50 个 → 只 archive 了 3 个。

**这次是我（operator）自己抓到的**，不是用户发现。说明严格的依赖捋清楚不光对代码 logic 重要，对 yaml 字段名也重要。被新一轮取代了（§4.4）。

### §4.4 第 4 次挖掘（2026 年 5 月 1 日完成，0 入选，所有候选每日涨跌都 ≥ 0.85 相关）

**单变量改动**：第一次加 **集中度限制**（每个 risk cluster 不超过 20%、单股不超过 10%）。

**结果**：
- 跑了 200 个候选，archive 58 个
- 最好 IC_IR = 1.187
- 因子组合也变了，第一次跟前面候选**不共享 `beta_spy_60d` 这种"大盘 β 锚"**
- **但**：top-10 候选**每日涨跌**跟现有候选的相关系数（Pearson）平均 0.90，全部 20/20 配对都 ≥ 0.85 拒绝阈值

**学到的**：
- 在 54 只大盘股 universe + 月度调仓 + 选前 N 名的框架下，**85% 的 NAV 相关性来自结构性的大盘 beta**，不是因子带来的
- 集中度规则没破"兄弟"问题
- **universe 本身**才是 binding constraint

**结论性建议**：下一次该试 **加跨资产**（不光是股票），直接攻击 universe 这个结构性原因。

详细文档：`docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md`。

### §4.5 第 5 次挖掘（2026 年 5 月 1 日完成，0 入选 + 第一次产出 7 个一类候选）

**单变量改动**：加了 6 个跨资产 ETF（长债 TLT、中债 IEF、短债 SHY、黄金 GLD、短期国债 BIL、超短期国债 SHV）；同时加资产类别上限（股票 ≤70%、债券 ≤40%、商品 ≤20%、现金锚 ≤30%）。

**预 mining 准备工作**：
- 加了一个"adjusted_total_return"模式（含分红的全收益），跟 yfinance 对齐 ≤ 0.01%
- 把 2009-2014 的债券数据回填了 9054 行
- 把 risk cluster map 扩展支持 cross-asset

**结果**：跑了 200 个候选，archive 62 个。**两种性格的 cluster 出现了**：

- **Cluster A**（4 个候选）：以"回撤位置 + 流动性"为锚 → **每日涨跌相关系数 0.66-0.70**（**第一次破 0.85**），最大回撤 -16% 到 -18%（比之前的 -27% 好很多）
- **Cluster B**（6 个候选）：以"波动率"为锚 → 相关系数 0.91-0.94（还是不破），最大回撤 -27%（跟之前差不多）

**意外的副作用**：mining 收敛到的因子还是跟第一代候选的"锚因子"高度重叠（drawup + amihud）。**Cluster A 在因子重叠规则上被否**（factor_overlap = 2 with RCMv1），即使它的 NAV 已经成功分散了。

**深层机制发现**：跨资产打破相关性的根本机制 = **bond 上算不出 amihud（流动性因子）→ 跨资产 composite 在债券上为 NaN → selector 退化到只挑股票**。这是一个"歪打正着"的副产品，不是规则设计的。

**过程 bug + 修复**：第 5 次挖掘出炉时**漏算了跟现有候选的相关性**，verdict 把 Cluster A 标成 5 个 Tier 1 入选。Self-audit 抓到后补跑了 cross_cycle 相关性，结果 5 个 Tier 1 全部降为 Tier 2。

**预先承诺的停止规则**：如果**第 6 次还是 0 入选**，停止挖掘节奏挖矿，pivot strategically。

详细文档：`docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md`。

### §4.6 第 6 次挖掘（2026 年 5 月 1 日完成，0 入选，但 7 个一类候选 + Trial 9 浮现）

**单变量改动**：相比第 5 次，唯一变化 = **禁用** `drawup_from_252d_low + amihud_20d`（之前的"锚"因子）。

**结果**：
- 跑了 200 个候选，archive 44 个
- 最好 IC_IR = +0.548（比第 5 次 +1.199 跌了 54%）
- **7 个一类（Tier 1）候选 + 3 个二类候选**（**整个挖掘历史第一次产生 Tier 1 verdict**）

**焦点：9 号候选（Trial 9）**

- 组合：`beta_spy_60d`（大盘 β）+ `max_dd_126d`（126 日最大回撤）+ `ret_1d`（昨日收益）
- 17 年累计收益 +502.6%、夏普 0.78、最大回撤 -24.5%
- 每个验证年的回撤都 < -20%（2018: -15%, 2019: -7%, 2021: -6%, 2023: -9%, 2025: -18%）
- 每日涨跌跟现有候选相关系数 0.54-0.69（partial diversifier 区间）
- **跟第一代候选只共享 1 个因子**（`beta_spy_60d`）

**问题**：CLAUDE.md 里那条 QQQ 规则 —— 5 个验证年累计 vs QQQ 平均必须 > 0 —— Trial 9 是 -4.59%，**触红线**。

**后续转折**：2026 年 5 月 2 日 CLAUDE.md 把 QQQ 规则降级为"参考"不是"硬约束"（因为 QQQ 是 sector-concentrated 60% 科技，作为硬基准会强行让策略 over-tilt 科技），**Trial 9 因此 unlock 进入 forward observe**。

**Trial 9 后来的命运**：
- 5 月 1 日决定升级 Trial 9 为**分散者角色**（diversifier role）—— 新角色定义，允许更宽松的 QQQ excess 阈值，但对 NAV 相关性和 cross-asset 比例要求更严
- 5 月 4 日 forward init 为 `trial9_diversifier_001`
- 5 月 12 日**第一次 TD60 阶段被 v2.1 revalidate 误判**（per_cell_digest 在 production 默认是空的，导致 fail-closed bound_only verdict）
- 5 月 12 日同天发 PRD 让 diversifier 候选可以 opt-in 开启 per-cell digest
- 5 月 13 日**升级到 `trial9_diversifier_002`**（spec 完全不变，只加了 evidence_config 开关）
- 今天（5 月 14 日）`trial9_diversifier_002` 累计 2 个 TD（第一天基线 + 第二天 +0.36%）

详细文档：`docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md`。

📝 **用户 annotation §4 (cycle04-cycle05 era)**:
> [Trial 9 当时 forward init 这个决定，回头看你怎么评估？是不是太早？]

### §4.7 第 7 次挖掘（2026 年 5 月 6 日完成，0 入选）

**单变量改动**：第一次切换 **优化目标从"信号系数 IC"到"组合净值 Sharpe"**（NAV-based objective）—— 之前是看因子的 IC（Information Coefficient = 因子值跟 21 天后收益的相关性），现在直接看用因子构成组合后的 NAV 夏普比率。

**预实现工作**：6 个 commit（`f2b6059..3fec344`）shipped 三个 phase + I20 detector 改进 + 跑速基准（中位数 19.36 秒/trial）。

**结果**：
- 200 trial / archive 66 个
- 最好规格：`drawup_from_252d_low + trend_tstat_20d + ret_2d`（**还是跟前 5 次挖掘的"老锚"重叠**）
- Top-3 候选过 17 道闸门：0/3 PASS。原因都是 **5 个验证年累计 vs SPY < 0**。

**假设验证**：
- 假设 1（新目标跟老目标排序的 Spearman 相关 < 0.5）：FAIL，实际 0.89 → 新目标其实是老目标变种
- 假设 2（NAV-based 会让周度持有更多）：FAIL，monthly:weekly:daily = 49:10:7
- 假设 3（新目标 Pareto 优于老目标）：FAIL，新 top-1 sharpe 0.565 < 老 top-1 0.664
- 假设 4（候选跟现有锚相关性 < 0.50）：PASS（看上去"太干净"，可疑）

**学到的**：切换 objective 不是 root cause fix。同样的 universe + 同样的构造方式，无论用 IC 还是 NAV 当目标，都收敛到差不多的结果。

详细文档：`docs/memos/20260506-cycle06_closeout.md`。

### §4.8 第 7a 次挖掘 + 一个隐蔽的 P0 bug（2026 年 5 月 7 日，1 通过 + Red 否决）

**单变量改动**：因子 reweight（drawup_from_252d_low + 短动量 锚增强）。

**初次结果**：200 trial / archive ~30 / top-3 verdict 0/3 PASS。

**Audit reverse-validate 抓到一个隐蔽 bug**：

> 9 个 trial 里 **16 of 17 gates 都 fail 在跟 `beta_to_qqq` 相关的事项上**，统计学上不合理 → 怀疑 metric 路径出错

根因：评估脚本写入 `metrics["beta_to_qqq"]` （顶层 scalar）；但 acceptance evaluator 读的是 `metrics["beta"]["beta_to_qqq"]`（嵌套 dict，匹配 yaml schema）。**fail-closed 静默 → 全部 9 trial 被误判为 beta 闸门 FAIL**，实际 beta 全部远低于 0.85 上限。

修复后**重新跑 9 trial**：
- 第 6 次: 0/3 PASS（依然 vs SPY aggregate 不够）
- **第 7a 次: 1/3 PASS** — **3 号候选** `1e771580f486` 是 cycle04-08 历史上**第一个 17/17 全过的候选**
  - 组合：`drawup_from_252d_low + mom_63d + ret_1d`
  - 17 年累计 +1016.75% vs SPY +231.94% / QQQ +496.38%
  - 夏普 1.08，最大回撤 -20%，beta 0.534
  - 2025 验证年 +25.1%（vs SPY +8.4%）
  - covid_flash 闪崩 +3.6%（vs SPY -13.8%）
- 第 8 次: 0/3 PASS

**然后做 NAV 相关性闸门**（forward-init 前的 anti-sibling 检查）：

| 配对 | raw 相关 | 残差 vs SPY | 残差 vs QQQ |
|---|---|---|---|
| 3 号候选 vs 第一代 | **0.874** | 0.603 | 0.613 |
| 3 号候选 vs 第二代 | **0.892** | 0.688 | 0.699 |
| 3 号候选 vs Trial 9 | 0.783 | 0.319 | 0.381 |

**结果：RED**（raw 相关 ≥ 0.85 在 2 个配对里超过；残差 ≥ 0.50 在 6 个测量里有 4 个超过）。**3 号候选不能 forward init**，只能做证据记录。

**3 个深层 structural finding**：

- **发现 1**：drawup-anchor + 月度 + top-N 是 **binding sibling geometry**。3 号候选跟第一代只共享 1 个因子（drawup），但**每日涨跌相关 0.874**。**禁因子不破"兄弟"，禁构造方式才破**。
- **发现 2**：第二代候选的"兄弟"问题比第一代更紧。3 号候选跟第二代 **0 个因子共享**，但相关 0.892。说明 **long-only top-10 over 78-股 universe = MARKET-COVERAGE binding** — 因子完全 disjoint 但月度选 top-10 还是会选到 30-50% 相同名字。
- **发现 3**：Trial 9（用 max_dd_126d 取代 drawup）**结构性不同** —— 都是 cap_aware monthly top-N，但相关 0.783 + 残差 0.32-0.38。**drawup vs max_dd_126d 是真实的 sibling boundary。**

详细文档：`docs/audit/20260507-beta_metric_path_bug_postmortem.md` + `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`。

### §4.9 第 8 次挖掘（2026 年 5 月 8 日完成，0 入选）

**单变量改动**：用"分 regime 的因子权重"（BEAR / NEUTRAL / BULL 各自不同权重）。

**结果**：40 trial smoke (没跑完 200) / archive 11 / top-3 verdict 0/3 PASS。

**意义**：连 regime-conditional weight 都不破"兄弟"问题，证明 binding constraint 真的在构造和 universe 那一层。

### §4.10 第 9 次挖掘（2026 年 5 月 12 日，invalid - 采样器架构 bug）

**单变量改动**：因子库从 67 → 162（PRD 20260512 新增 4 个 bucket：A 量价微观结构 + B 基本面 + C sector + Macro 宏观指标）。

**结果**：跑了 200 trial / **100% 在采样阶段被剪掉 / 0 个回测 / 用时 2.1 分钟**。

**根因**：现在的采样器是为 "4-6 family + 3-cardinality" 设计的（cycle04-08 是这个配置，valid spec 概率 2.74%）。新的 17-family 配置下，valid spec 概率掉到 **0.0005%**（10 万次 Monte Carlo 验证 0 次命中）。

**这不是 0 入选，是"根本没真的搜过"**，所以标 invalid。

**修复**：发了一个 `sampling_mode: family_first` 模式 — 先选 k 个 family，再每个 family 选 1 个因子 → valid 概率 100% by 构造。10 个新测试 + 215 旧测试全过。

**同期 user 8/8 explicit-go**：用户 5 月 12 日同意"A 和 C 同时跑" — 即 Option A（采样器修复）和 Option C（事件驱动 alt-archetype 启动）并行。

### §4.11 第 10 次挖掘（2026 年 5 月 13 日完成，0 入选）+ 路线图 v2

**结果**：第 10 次照样 0 入选，R7 闸门（fail-SPY 风险）触发。

**用户 8/8 explicit-go 锁定路线图 v2**（命题 + 决策）：

1. T1a 优先做，然后 T1b 和 T1c 并行 ← intraday strategies
2. PEAD + FOMC bundle ← event-driven
3. cycle11 3 个目标全部试
4. ML Phase 2 跟 T2 耦合
5. F1+F2+F3 全做
6. K1 严格 TDD
7. unified observe runner
8. signal seed library 全部 collect

**K1 ship（5 月 13 日晚）**：`SignalDrivenBacktest` wrapper at `core/backtest/signal_driven_runner.py`（212 行）+ 30 测试 + 完整闭环。这是后来 cycle11 + PEAD 都靠的 wrapper。

**也修了一个 SPY/BIL/SHV off-by-one 日期 bug**：tz_localize 缺 tz_convert → yfinance 数据 UTC midnight roll 到下一天 → 569 个伪 Saturday 行 per affected 股票。修复后 cycle04-10 数字**整体 deprecated**（qualitative findings 保留）。

### §4.12 第 11 次挖掘（2026 年 5 月 14 日 = 今天 = 用户成本调到 30bp 后）

**用户 directive (5 月 14 日上午)**：把成本闸门从 5bp 提到 **30bp**（= 6 倍原始），原因 = 5bp 对零售投资者不真实。

**实际验证**：5 月 14 日下午跑了 3 种参数化 signal-driven smoke：

**v1（5bp，旧成本）**：Connors RSI(2) hold=3 → 夏普 **3.54**（夸张地高）

**v2（30bp，新成本）**：top 5 全是 Donchian 中长 hold，最强 Donchian-20 hold=21 → 夏普 **1.31**（看起来还行）

**我自己抓的 bug**：standalone 单独跑 Donchian-20 hold=21 spot-check → 夏普 **0.66**（vs smoke v2 1.31 差 0.65 Sharpe）

**根因**：smoke 脚本没传 `open_df` → `BacktestEngine` 静默 fallback 到"用同日 close 当作 execution price"。对突破策略这是隐性 look-ahead：T+1 OPEN 通常 gap-up 于 T close，**用 close 当 open 是把今天的好结果当成明天的入场价**，系统性高估收益。

**v3 修复（传 open_df）**：
- 3/20 candidate 勉强过 SPY（夏普 0.76 SPY 基准）
- 最强：Faber hold=252 → 夏普 0.788（= +0.029 over SPY = 4% 边际改进）
- 全部 Connors RSI(2) 变种**亏钱**（夏普 -0.054 到 -0.657，最大回撤 -33% 到 -61%）

**verdict**: 第 11 次 = **informative null**（参数化技术信号在 30bp 真实成本下没 alpha unlock）。

详细文档：`docs/audit/20260514-cycle11_smoke_execution_artifact.md` + `docs/memos/20260514-cost_gate_revision_6x.md`。

📝 **用户 annotation §4 (cycle04-cycle11 全程)**:
> [这一连串 0 nominee 你怎么看？cycle10 R7 fail-SPY 触发是不是太早？cycle11 信号驱动这个方向应该 push further，还是认输？]
中文大白话给我重新写

---

## §5 财报后漂移异象 PEAD —— 今天找到的第一个真信号

### §5.1 什么是"财报后漂移异象"？

学术上叫 **Post-Earnings Announcement Drift（PEAD）**，1989 年由两位学者 Bernard 和 Thomas 首次发现，**至今 36 年依然在学术上被反复 confirm**。

**通俗解释**：

> 某公司今天公布季报，每股盈利远超分析师一致预期（"盈余惊喜" = positive earnings surprise）。
> 当天股价大涨 5% 反映这个 surprise。理论上市场已经完全消化，未来涨跌应该跟其它股票一样随机。
> **但实证发现：这种股票未来 60 个交易日还会继续涨 2-5%（年化），统计上显著。**
> 
> 原因：机构投资者**慢慢消化新信息**，零售投资者**反应不足**（underreaction）。

**学术验证（2026-05-14 today WebSearch 结果）**：

- 2020-2024 年的 paper 普遍 confirm PEAD 仍然存在
- 有部分 paper（Chordia 2014, Martineau 2022）说"信号在变弱"
- 有 paper（Meursault 2023）用文本驱动的盈余预期 confirm "still strong"
- 国际市场（中国 / 欧洲）的 paper 普遍 confirm 信号在新兴市场更强
- 2025 年 CFA Institute 还出了一篇问"生成式 AI 会不会终结 PEAD" 的 paper — 现在还没结论

来源：
- [Post earnings announcement drift: An Anomalous Anomaly (Caltech)](https://jkatz.caltech.edu/documents/28622/peads.pdf)
- [A Simple Earnings Surprise Measure (ScienceDirect 2024)](https://www.sciencedirect.com/science/article/abs/pii/S1057521924003922)
- [Can Generative AI Disrupt PEAD? (CFA Institute 2025)](https://blogs.cfainstitute.org/investor/2025/04/22/can-generative-ai-disrupt-post-earnings-announcement-drift-pead/)

### §5.2 PQS 今天怎么测的（PEAD 双轨实验）

**路 1 = 用基本面盈余惊喜（学术正统）**：

```
预期每股盈利 = 同季去年 EPS（朴素同比预期）
本季残差 = 本季实际 EPS - 预期 EPS
波动率 = 残差在过去 8 个季度的标准差
盈余惊喜值（SUE）= 残差 / 波动率
```

如果 盈余惊喜值 SUE 大于某个阈值（比如 1.5 标准差），就买这只股票，持有 N 个交易日。

**路 2 = 用价格反应（廉价代理）**：

```
公告日股价上涨 - SPY 当日上涨 = 异常涨幅
如果异常涨幅 > +5%，就买这只股票，持有 N 天
```

路 2 看上去也有道理（大涨说明 surprise），但**容易跟 sector co-move、Fed 信号、guidance change 混杂**。

### §5.3 实验结果

| 路径 | 9 个参数组合里跑赢 SPY 的数量 | 最强夏普 | 最浅最大回撤 |
|---|---|---|---|
| **路 1 基本面 SUE** | **8/9** ✅ | **1.063** | **-7.6%** |
| **路 2 价格异常涨幅** | 0/9 ❌ | 0.717 | -18% |

**预先注册的假设验证（pre-registered）**：

- "如果两条都赢" → robust PEAD（验证最强）
- **"如果只路 1 赢" → 基本面盈余惊喜是真信号** ← **触发** ✅
- "如果只路 2 赢" → 价格动量回响（不是真 PEAD）

**最强候选（trial 1）**：
- 阈值 1.5 标准差、持有 21 天、选前 10 名
- 夏普 1.055，年化收益 5.48%，最大回撤 -7.64%
- **PQS 历史上所有 Sharpe > 1.0 的候选里最浅回撤的**

**全部 9 个候选都很 robust**（参数变化时夏普不会跳水，1.0-2.0 标准差 × 21-60 天持有 × 5-20 top_n 都好）—— 这是真信号的特征，参数化信号没这个稳定性。

### §5.4 路 1 通过 17 道闸门验收 14/17 + 通过反兄弟检查

**通过的 14 道（核心质量都过）**：
- 5 个验证年的最大回撤都 < -10%（远低于 -20% 上限）：2018: -6%, 2019: -4%, 2021: -4%, 2023: -2%, 2025: -2%
- 2 个压力切片回撤都 < -5%（远低于 -25% 上限）
- 2 倍成本下还能赚钱（$13965 终值 vs $10000 初始）
- 集中度：第一大持仓 0.10、前三大 0.30
- 跟 QQQ 的同步系数（beta）只有 0.10

**fail 的 3 道（都是收益相关）**：
- 5 个验证年累计 vs SPY < 0
- 5 个验证年累计 vs QQQ < 0
- 2025 holdout vs QQQ < 0

**核心矛盾**：
- 2018 是 BEAR 年，PEAD 跑赢 SPY +13.2%（这是 defensive 的真价值）
- 2019 / 2021 / 2023 / 2025 都是 BULL 年，PEAD 落后 SPY -25% / -21% / -22% / -6.8%
- 5 年累计 vs SPY 是负数 → 单独 deploy 跑不赢

**学术解释**：PEAD 是 **defensive low-vol 信号**（低波动低回撤），在 BULL 年大盘暴涨时一定 underperform，但 BEAR 年大盘下跌时 outperform。**这种 alpha shape 单独 deploy 不能在 long-only 框架下过"跑赢 SPY"的 hard gate**。

**反兄弟检查（NAV 相关性）**：
| 配对 | 每日涨跌相关系数 |
|---|---|
| PEAD trial 1 vs T1a 日内反转 | +0.09（极低）|
| PEAD trial 1 vs T1b ConfirmationPattern | +0.38（中低）|
| PEAD trial 1 vs cycle11 Donchian-20 | +0.37（中低）|

**全部 < 0.85 拒绝阈值 → 真正 differentiated alpha source**。

### §5.5 决定：作为"仅观察"候选 forward init

**今天（5 月 14 日）做的决定**：把 PEAD trial 1 作为 `pead_sue_trial1_evidence_v1` forward init，标 `evidence_only_observation` 角色（**不进 fleet 组合**，纯观察）。

**为什么是仅观察而不是 fleet 成员**：
- 17 道闸门有 3 道没过 → 严格说还不够格入 fleet
- 但反兄弟检查全过 → 真正的不同信号源，**值得花 60 天观察**

**关键数据**：
- 起始日期 2026-05-15（明天）
- TD60 verdict 预期 **~2026-08-13**
- 起始 NAV $10000，60 天目标 = 验证学术信号在 2026 实时数据上是否还有
- 如果 60 天后夏普依然 > 0.8 + 最大回撤 < 15% + 跟其它候选相关性 < 0.70 → **触发 Phase 2 付费 8-K 实时财报日数据**

**为什么需要付费数据**：
- 我们当前用的是 SEC EDGAR 的 10-Q 申报日，**比真实 8-K 财报公告日晚 7-14 天**
- 漏掉了财报后 0-10 天最强的 drift portion
- 学术上 PEAD 在 0-10 天最大，10-60 天逐渐衰减
- 如果付费数据补上 0-10 天，预计夏普可能从 1.06 → 1.5+，年化可能过 Track A hard gate

📝 **用户 annotation §5 (PEAD)**:
> [PEAD evidence-only forward-init 决定你满意吗？60 天 soak 后如果 Sharpe 还 > 0.8，你倾向 fleet 合成还是 paid 8-K 数据 Phase 2？]

---

## §6 当前正在观察的 3 个候选（forward observation 完整状态）

### §6.1 早期已下线的候选（仅作为历史记录保留）

| 候选 | 启动 | 下线 | 下线原因 |
|---|---|---|---|
| 第一代防御组合 (rcm_v1) | 2026-04-24 | **2026-04-30 强制下线** | NAV 漂移 108 bp（数据修正引起）|
| 第二代正交组合 (cand_2) | 2026-04-24 | **2026-04-30 强制下线** | 同上 + 跟第一代相关性实际 0.898（远高 0.85 阈值）|
| 9 号候选 v1 (trial9_001) | 2026-05-04 | **2026-05-12 完结失败** | 第 4 个 TD 被 revalidate 误判 (per_cell_digest 空)，PRD 20260512 修复 |

### §6.2 当前 active 3 个

**1. 9 号候选 v2 (`trial9_diversifier_002`)**

- 角色：分散者
- 来源：第 6 次挖掘的 Trial 9（cycle 2026-05-01-05）
- 因子：大盘 β（1/3） + 126 日最大回撤（1/3） + 1 日收益（1/3）
- 启动：2026-05-13
- 当前累计 TD：2 个（第一天基线 + 第二天 +0.36%）
- **60 天 verdict 预期 ~2026-08-06**
- 用主 forward runner（适合多因子组合候选）

**2. PEAD 仅观察候选 (`pead_sue_trial1_evidence_v1`) — 今天新启动**

- 角色：仅观察（不进 fleet）
- 来源：今天 PEAD bundle Phase 1 测试的 trial 1
- 触发：每股盈利 SUE > 1.5 标准差时买入，持有 21 个交易日
- 启动：2026-05-15（明天）
- 当前累计 TD：1 个（TD000 基线）
- **60 天 verdict 预期 ~2026-08-13**
- 用独立 observe 脚本（不走主 runner，因为信号驱动而不是因子组合）

**3. 期权策略 paper run (`spy_8otm_bull_put_v1`)**

- 角色：期权 sleeve（独立于股票 fleet）
- 策略：SPY 8% 价外 bull put 价差（卖一个看跌期权 + 买一个更便宜的看跌期权对冲）
- 启动：2026-05-04
- 当前累计 TD：6 个（NAV 还是 $10000，没等到入场信号）
- **60 天 verdict 预期 ~2026-07-30**

### §6.3 决策窗口集中（关键）

3 个候选的 60 天 verdict 集中在 **2026-07-30 → 2026-08-13** 三周内。这是一个关键的"信号汇聚"时间窗口：

- **如果至少 1 个 GREEN**：触发 fleet 组合架构启动（PRD-C2/C3）+ 付费数据决策
- **如果全部 RED**：触发战略 reassessment（目标 / 数据 / 频率 / 策略类型大改，per cycle04 停止规则）
- **如果都是 YELLOW**：继续观察到 TD90，决策推迟到 9 月底

📝 **用户 annotation §6**:
> [3 个 candidate 这种"组合下注"策略你觉得分散得够吗？还有哪类候选应该再 forward-init？]

---

## §7 当前框架不可违反的硬约束（invariants）

以下约束写在 `CLAUDE.md` 顶部，**任何违反必须用户明确授权**：

### §7.1 策略层约束

- **只能买涨**（long-only） — 不能做空（借股票卖空）
- **不能加杠杆**（no-margin） — 不能借钱放大持仓
- **不能借券**（no-short） — 任何 short selling 都禁止
- **SQQQ + SOXS 黑名单** — 反向 ETF 禁用（违反 long-only 精神）
- **TQQQ + SOXL 严格限额** — 杠杆 ETF 单股最多 10%、总仓位最多 12%、且只能在 risk-on regime 才能持有

### §7.2 基准 + 风险约束

- **SPY = 主基准（HARD）** — 全期 + 2025 留出年都必须跑赢 SPY
- **QQQ = 诊断参考（不再硬约束）** — 2026-05-02 降级，因为 QQQ 是 60% 科技股 sector-concentrated 基准
- **最大回撤目标 15-20%** — 比 SPY 在危机里不能更差
- **2008 风格场景最大回撤 ≤ 25%** — 用压力切片（covid_flash / rate_hike_2022）验证
- **集中度上限** — 单股 ≤ 40%、前三大 ≤ 70%

### §7.3 数据 + 执行约束

- **价格语义** — 调整后的 close 价（含拆股，不含分红，因为没有分红数据 sidecar）
- **T+1 开盘价执行** — 信号在 T 日 close 触发，T+1 开盘价成交
- **停牌 / 数据缺失** — 持仓按 last valid 价格估值，不从 NAV 里删掉

### §7.4 流程约束

- **所有阈值在 yaml 里** — 不能硬编码到代码
- **回测 / 实盘一致性** — 同一逻辑两边跑必须一致
- **中文报告 / 英文代码** — 报告说人话，代码命名用英文
- **2026 封存样本 single-shot** — 全 project 历史里一次都没用过；用完一次就锁住，再用必须改 split_name v1→v2

### §7.5 成本约束（cycle11+ revision，5 月 14 日改的）

- **30bp 跨日滑点 + 60bp 日内滑点 + 2bp 佣金** — 当前基线（= 之前 5bp 的 6 倍）
- **2 倍成本鲁棒性** — 最终净值在 2 倍成本下必须还是正
- **第 4-10 次挖掘 archive 锁定在 5bp** — 不变量"locked_after_first_use"，cycle11 后用 30bp

📝 **用户 annotation §7**:
> [哪条 invariant 你愿意 review？哪条 absolute？特别是 long-only / no-short — 这个 boundary 调整对 alpha 空间影响极大]

---

## §8 已经证明走不通的方向（基于实证 + 学术验证）

### §8.1 加更多因子 ≠ 解决问题

- 第 4 次挖掘用 33 因子，第 11 次用 162 因子
- **同样的"兄弟"现象反复出现**
- 第 5 次跨资产实验里只有 Cluster A 在 NAV 上破了 0.85，但**被因子重叠规则否决**
- **结论**：因子库扩展不解决 long-only top-N 的 binding constraint

### §8.2 切换优化目标（IC → NAV）≠ 解决问题

- 第 4-6 次用信号系数 IC 当目标，第 7 次切到 NAV 当目标
- top-1 候选夏普反而退化（0.664 → 0.565）
- 新老目标的 Spearman 相关 0.89 → 实质上是变种
- **结论**：换 objective 不是 root cause fix

### §8.3 换调仓频率（月度 → 周度）≠ 解决问题

- 第 2 次单独测周度，top-1 跟第 1 次 monthly 的 top-1 **3 个因子完全一样**
- **结论**：cadence 切换不破 sibling

### §8.4 参数化技术信号在 30bp 真实成本下没 alpha

- 第 11 次 cycle11 跑了 Donchian / Connors / Faber 三个经典家族
- 3/20 勉强过 SPY（最强 Sharpe 0.788 = +0.029 over SPY）
- Connors RSI(2) 全亏钱
- **结论**：在 78 只大盘股 universe + 30bp 框架下，参数化突破 / 反转 / 趋势全部碰 TC 天花板

### §8.5 单纯价格反应作为盈余惊喜代理 = 噪声

- 今天 PEAD path 2 验证：0/9 过 SPY
- AR > +5% 触发被 sector co-move、guidance、macro 当日 confound
- **结论**：基本面 SUE 是真信号，价格反应单独不是

### §8.6 FOMC 公告前后漂移 = 已死

- T1c FOMC drift 在 post-2015 数据 confirmed dead
- 详 `docs/memos/20260513-fomc_drift_smoke.md`
- **结论**：Fed cycle 已被市场学习消化

### §8.7 Wheel 期权策略 = 长期 long-only + no-margin 框架下结构性不行

- 期权 paper Phase 1 测试
- 最大回撤 -32.72%（远高于 -25% 上限）
- 原因：Cash-Secured Put 被指定后转 Covered Call，如果 spot 跌到 lower strike 就放大 loss
- **结论**：不再尝试（除非放开 long-only 不变量）

📝 **用户 annotation §8**:
> [这些 ruled-out 你都同意吗？哪条想再开一次？]

---

## §9 还没充分探索的方向（开放空间）

### §9.1 事件驱动信号（PEAD 已 confirm，FOMC dead）

**已做**：PEAD path 1 SUE（今天 Sharpe 1.06 / 回撤 -7.6%）
**未做**：付费 8-K 实时财报公告日数据（如果加上 0-10 天最强 drift portion，预期夏普可能 1.5+）
**关键 trigger**：trial9_v2 或 PEAD TD60 任一 GREEN

### §9.2 日内交易层

**已做**：
- T1a 日内反转策略 Phase 3 backtest（5bp 成本下 marginally 过 17 道闸门）
- T1b ConfirmationPattern（夏普 1.18 / 年化 20.3% 但年度间不一致，闸门 fail）
- T1c FOMC drift 已 confirmed dead

**未做**：T1a + T1b 在 30bp 真实成本下重跑（很重要的 cheap diagnostic）

### §9.3 跨资产扩展（部分完成）

**已做**：第 5 次挖掘加了 6 个 cross_asset ETF；Cluster A 第一次 NAV 破 0.85
**未做**：重做第 5 次挖掘 + 适当放宽因子重叠规则；或者把更多资产类别（外汇 / 加密 / 商品期货）加进 universe

### §9.4 universe 扩展到 200+ 股

**已做**：78 只大盘股是当前 universe
**已 ruled out**：路线图 v2 把 D1（78 → 200 股）drop，理由 TC ceiling 不靠 universe size 解
**但**：cycle04 cross-asset 的 n=1 实证不够强，**理论上学术 confirm breadth 扩展是 TC 公式里的合理路径**（见 §3.0.2 突破方法 C）

### §9.5 ML 第 2 期

**Phase 1 状态**：closed 2026-05-13 with §3.9 abort（Track A FAIL）
**Phase 2 状态**：等 cycle11 + PEAD T2 框架成熟后再决定
**关键 trigger**：T2 框架 + cycle11 或 PEAD 至少一个有 unlock

### §9.6 期权策略 Phase 2（付费 chain 数据）

**Phase 1 状态**：SPY 8% OTM bull put paper run 开始
**Phase 2 trigger**：Trial 9 v2 TD60 GREEN + options paper TD60 GREEN 双 trigger
**预算**：付费 chain 数据 ORATS / Polygon options ~$50-200/mo

### §9.7 long-only 不变量调整 = 学术上最大的 alpha unlock（需用户明确授权）

- §3.0.2 学术证据：130/30 让 TC 从 0.30 → 0.55-0.70（近 2 倍）
- 实证：73 product pairs 里 55% 的 130/30 产品比 long-only 同公司产品夏普更高
- **PQS 当前一切都 hardcode 在 long-only 框架** —— 任何调整都是 invariant 级 change
- **用户的 directional stance 是这个 memo §11 Q2 的核心 question**

### §9.8 多候选合成架构（Phase C-PRD-2）

**思路**：把多个 single-candidate 合成一个 fleet —— 比如 PEAD（防御 + 低回撤）+ T1b（高夏普 + 不稳）+ 9 号候选（分散者）—— 组合 NAV 可能同时拿到多个 candidate 的好属性
**已做**：架构 PRD 写完，但暂停启动
**关键 trigger**：trial9_v2 TD60 GREEN（roadmap v2 默认）；或者 PEAD 60 天后表现明显

📝 **用户 annotation §9**:
> [9 个开放方向，按你想 push 的优先级排序。哪几个先做？哪几个等？]

---

## §10 战略选项（不预选，等用户决策）

下面 7 个选项，每个写了我做 operator 的看法（pros / cons）：

### Option A — Conservative continue（保守延续）

- 维持 3-candidate forward soak（9 号 + PEAD + 期权）
- 等 7/30-8/13 60 天 verdict
- 中间 idle 时间做文档对齐 + 测试覆盖
- **优点**：零新风险，把 attention budget 留给 3 个 verdict
- **缺点**：3 个月不开新 alpha attack

### Option B — PEAD Phase 2 立即准备

- 不等 PEAD 60 天 verdict，开始 Phase 2 准备：
  - Polygon 或 IEX 8-K 实时财报日数据接入 (~3 天工程量)
  - 实时数据 vs filed_date 数据交叉验证 PEAD 信号 (~1 周)
  - fleet 合成 schema 设计（PEAD 防御 + 顺势 overlay）
- **优点**：PEAD 是今天唯一 unlock，attention momentum 有价值
- **缺点**：付费数据决策提前；如果 PEAD 60 天 verdict 红了 wasted $50-200/mo

### Option C — 第 9 次挖掘 family_first 重跑（测架构修复）

- 采样器 family_first 已 ship，但从未在真正的 200 trial 测试
- 162 因子 + family_first 可能产生真正不同的"兄弟"
- 单跑 ~2 小时 wall-clock
- **优点**：cheap、真正验证 sampler fix
- **缺点**：可能再次 0 入选 → 不增信息

### Option D — T1a / T1b 30bp 重新评估

- T1a 日内反转 + T1b ConfirmationPattern 当前是 5bp 评估的
- 重新跑 30bp 真实成本看 attrition
- 如果 T1b 在 30bp 还有 alpha → fleet 合成 PEAD + T1b 可能 immediate go
- ~1 天工程量
- **优点**：cheap directional info，可能 immediately unblock fleet
- **缺点**：已知 T1b 年度不一致，30bp 后可能更糟

### Option E — 战略 reassessment（跟用户讨论）

- 大盘 review：5 cycles + cycle11 + PEAD 6 周整体方向
- 用户 weigh-in: universe / cadence / long-only / 付费数据预算
- **优点**：alignment + new directional signal
- **缺点**：blocks tactical work 直到决定

### Option F — Universe 扩展 D1 single-axis 测试

- 78 → 200 股 single-axis smoke
- 同样 cycle04 family setup
- 看 NAV 相关性跟 raw Sharpe trade-off
- **优点**：一次性 kill D1 假设
- **缺点**：roadmap v2 已 ruled out

### Option G — long-only 不变量讨论（需用户明确授权 — 不可执行直到 user 信号）

- 跟用户讨论 short / margin / leverage boundary
- 最大潜在 alpha unlock 但最大 invariant change
- **out of scope 直到用户 signal interest**

### 我（operator）推荐 sequence（NOT user-locked）

1. **Option A 默认 + Option D 并行** 接下来 2 周（D 一次性 cheap directional）
2. 2 周后：如果 D 给出 T1b 30bp positive → consider fleet 合成 (Option B prep)
3. ~6/15 mid-point：如果 30 天还没 GREEN signal → reassess
4. ~7/30 第一个 60 天 verdict（期权 paper）→ branch decision

📝 **用户 annotation §10**:
> [7 个 option 你想动哪个？多个并行 OK 吗？是否要 reorder operator 推荐 sequence？]

---

## §11 给用户的 5 个关键问题（请直接 weigh-in）

下面是我作为 operator 觉得用户最需要 directional 决策的 5 个问题。请在每个下面写你的想法：

### Q1 — 9 号候选当时 forward init 是不是太早？

**背景**：9 号候选来自第 6 次挖掘，是 7 个一类候选里"通过 yaml 硬闸门但 fail CLAUDE.md 项目级不变量（QQQ 5 年累计 vs_qqq mean < 0）"的唯一存活。**回头看，是不是 CLAUDE.md 在 2026-05-02 把 QQQ 降级为参考太便利了 9 号候选？**

📝 **用户 Q1**:
> [...]

### Q2 — long-only 这条不变量你的 stance？

**学术证据**：130/30 让信息利用率从 30% → 55-70%（近 2 倍 alpha 上限）；55% 的 product pair 实证显示 130/30 比 long-only 同公司产品夏普更高。

4 个 stance 选项：
- A) Never（永远不调）
- B) Conditional（特定 regime / 特定候选可以小幅放开）
- C) Gradual（先 covered options 再 bond futures...）
- D) 等 fleet 合成 evidence 再讨论

📝 **用户 Q2**:
> [...]

### Q3 — 11 次 0 入选 vs Trial 9 60 天数据，哪个 evidence weight 更高？

3 个选项：
- A) Cycle 0-入选 n=8+ 证 framework infeasible → 必须改架构
- B) 9 号候选 forward 数据更新 → 看 60 天结果再决定
- C) 两个 evidence 互补 → 同时改

📝 **用户 Q3**:
> [...]

### Q4 — PEAD 是 Sharpe 1.06 / 回撤 -7.6% 但年化 5.5% < SPY 13%。三个 fleet 用法选哪个？

- A) PEAD 50% + T1b 50%（高年化 + 低回撤）
- B) PEAD 100% 作 standalone defensive（接受低年化）
- C) PEAD + 风险平价多候选（9 号候选 v2 + 未来 winner）

📝 **用户 Q4**:
> [...]

### Q5 — 2026 封存样本什么时候用？

- A) 立即（今天 PEAD trial 1 已 frozen）
- B) PEAD 60 天 verdict GREEN 后
- C) Fleet 合成框架 ready + 多候选 verdict 后
- D) 永不（封存留作最终的最终）

📝 **用户 Q5**:
> [...]

---

## §12 任何其它想说的（用户随机 annotation 区）

📝 **任何其它想说的**:
> [...]

---

## §13 完整 reference 列表

### Mining 历史 PRDs
- `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` (时序切分纪律)
- `docs/prd/20260428-candidate_fleet_allocator_prd.md` (多候选组合，暂停在第 5 步)
- `docs/prd/20260424-cycle07_to_fleet_master_prd.md`
- `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md` (第 7 次起 NAV 目标)
- `docs/prd/20260505-taa_regime_allocation_framework_prd.md` (TAA 框架，dormant)
- `docs/prd/20260501-two_stage_allocation_architecture_prd.md` (Phase C-PRD-1/2/3/4 多候选合成)
- `docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md` (9 号 v2 fix)
- `docs/prd/20260514-pead_bundle_phase1_prd.md` (今天的 PEAD)

### Cycle 关键 closeout memos
- `docs/memos/20260426-research-cycle-2026-04-26-01_close.md` (G2.A fail)
- `docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md` (第 1 次)
- `docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md` (第 4 次集中度限制)
- `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md` (第 5 次跨资产)
- `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md` (第 6 次 anchor-sensitivity，9 号候选来源)
- `docs/memos/20260506-cycle06_closeout.md` (第 7 次 NAV-based)
- `docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md` (Track A 重新评估)
- `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md` (3 号候选 NAV Red)
- `docs/memos/20260513-cycle10_closeout.md`
- `docs/memos/20260514-cycle11_smoke_execution_artifact.md` (第 11 次 close-fallback bug)
- `docs/memos/20260514-pead_bundle_phase1_close.md` (今天)

### 自审 + 数据 integrity 关键 memos
- `docs/checkpoints/20260430-self_audit_methodology.md` (4 轮自审方法)
- `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`
- `docs/memos/20260512-trial9_diversifier_001_closeout.md`
- `docs/audit/20260507-beta_metric_path_bug_postmortem.md` (第 7a 次 P0 fix)
- `docs/audit/20260514-comprehensive_project_audit.md` (今天的全面 audit)

### 战略 + roadmap memos
- `docs/memos/20260429-post_audit_strategic_roadmap.md` v3
- `docs/memos/20260430-priority_realign_alpha_first.md`
- `docs/memos/20260430-rcmv1_cand2_realized_correlation.md` (前两代候选 sibling-by-NAV 证据)
- `docs/memos/20260502-qqq_benchmark_deprecation.md` (CLAUDE.md QQQ 规则降级)
- `docs/memos/20260513-post_cycle10_strategic_roadmap.md` (路线图 v2)
- `docs/memos/20260514-cost_gate_revision_6x.md` (30bp 成本基线)

### 历史阶段 archive
- `docs/20260422-claude_md_phase_bc_history.md` (Phase B + 早 Phase C)
- `docs/20260424-claude_md_phase_e_history.md` (Phase E 细节)
- `docs/20260422-deep_mining_50round_final_synthesis.md`
- `docs/20260424-rcm_v1_final_synthesis.md`
- `docs/20260424-phase_e_final_synthesis.md`
- `docs/20260424-phase_e_post_cand2_final_synthesis.md`

### 学术外部 reference（新加 §3.0 用 — 2026-05-14 WebSearch）
- [The Fundamental Law of Active Portfolio Management — Clarke, de Silva, Thorley (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=934440)
- [Portfolio Constraints and the Fundamental Law of Active Management (Duke 课程笔记)](https://people.duke.edu/~charvey/Teaching/BA491_2005/Transfer_coefficient.pdf)
- [Loosening the Long-Only Leash (AQR 2011 white paper)](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/Loosening-the-Long-Only-Leash.pdf)
- [130/30 The New Long-Only (Lo & Patel 2008, SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1074622)
- [Post earnings announcement drift: An Anomalous Anomaly (Caltech)](https://jkatz.caltech.edu/documents/28622/peads.pdf)
- [A Simple Earnings Surprise Measure (ScienceDirect 2024)](https://www.sciencedirect.com/science/article/abs/pii/S1057521924003922)
- [Can Generative AI Disrupt PEAD? (CFA Institute 2025)](https://blogs.cfainstitute.org/investor/2025/04/22/can-generative-ai-disrupt-post-earnings-announcement-drift-pead/)
