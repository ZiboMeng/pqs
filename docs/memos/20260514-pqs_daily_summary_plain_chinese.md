# PQS 现状大白话总结 — 2026-05-14

**版本**: v1 (今日固化)
**作者**: operator (zibomeng@) + Claude Code assist
**用途**: 给未来回看的"PQS 系统在 2026-05-13 / 14 两天搞清楚了什么"的全景速查
**配套技术文档**:
- 战略路径: `docs/memos/20260513-post_cycle10_strategic_roadmap.md` v2
- SPY bug postmortem: `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`
- 各 candidate closeout: `docs/memos/2026051*-*_closeout.md`
- Cost gate: `docs/memos/20260514-cost_gate_revision_6x.md`

---

## 🎯 PQS 到底在干嘛（30 秒版）

PQS = **个人量化策略系统**。目标：**长期跑赢 SPY 标普 500**，最大回撤 ≤ 15-20%，黑天鹅 ≤ 25%。初始 $10K，5-10 年做到 $100K。

约束：**只能做多** (long-only)、**不加杠杆** (no-margin)、**不卖空** (no-short)、SQQQ 黑名单、本地跑（不上云）、Python+pandas+yfinance / Polygon 数据、Chinese 报告 / English 代码。

---

## 🔄 历史 mining cycle 都做了啥（cycle04 → cycle10）

> **Mining = 用电脑搜出来一个能赚钱的策略组合**。每个 cycle 换一个变量再搜一遍。

> **术语翻译**:
> - **Track A acceptance** = 17 个验收门（vs SPY 5 个 / vs QQQ 5 个 / 各年 MaxDD / stress slice / 集中度 / beta / 成本鲁棒性 / 2025 年硬门）
> - **sibling-by-NAV** = "兄弟收益曲线"，不同 mining trial 选出的股票组合 NAV 曲线 0.85-0.95 高度相似 → 说明 mining 没有真选出 differentiated 的 alpha
> - **0 nominee** = 0 个候选通过 Track A
> - **informative null** = 虽然没找到候选，但学到了"这个方向行不通"的信息

| Cycle | 日期 | 换了啥变量（人话） | 跑了啥 | 结果 | 学到啥 |
|---|---|---|---|---|---|
| **cycle04** | 2026-05-01 | 加入 6 个 cross-asset ETF（债 + 黄金 + cash 类） | 200 trial Optuna 挖矿 | 10/10 sibling-by-NAV，0 nominee | **第一次看到 sibling 现象** |
| **cycle05** | 2026-05-01 | 禁用最爆款的 2 个因子 `drawup_from_252d_low` + `amihud_20d` | 200 trial | 还是 sibling，IC_IR 下降 54% | 单换 factor 没用 |
| **cycle06** | 2026-05-06 | 把挖矿打分函数从 IC-based 换成 NAV-based（直接看回测净值表现） | 200 trial | 0 nominee，0/3 过 Track A | 换 objective 也救不了 |
| **cycle07a** | 2026-05-07 | factor 权重调整，更强调 drawup + 短期动量 | 200 trial | **第一次出 Trial 3 候选过 17/17 门**！BUT NAV 跟 RCMv1 raw correlation 0.874（sibling 警戒线 0.85）→ **Red verdict** | 过 Track A ≠ 真正 differentiated |
| **cycle08** | 2026-05-08 | 加 regime-conditional weights（牛市 / 熊市不同打分公式） | 40 trial smoke | 0 nominee | regime-aware 也不行 |
| **cycle09** | 2026-05-12 | factor 池从 64 个扩到 162 个 | 200 trial 但 sampler bug 全 prune | INVALID | 工程 bug，废 |
| **cycle09b** | 2026-05-12 | 修了 sampler bug | 0 nominee + 1 个 Trial 9 候选当 diversifier 角色 | first non-sibling | structural alternative 出现了 |
| **cycle10** | 2026-05-13 | mining objective 换成 NAV-residualized（净值扣掉 fleet beta 后再打分） | 200 trial | 0 nominee per Track A 0/3 | **NAV-residualized 也不行** |

**累计：5 个 mining cycle 总共 0 个能部署的 candidate。**

### 这背后的"真相"

5 个 cycle 之后用 Clarke-de Silva-Thorley 2002 公式分析：

```
IR ≈ IC × √breadth × TC
```

- **IC (Information Coefficient = 信号预测力)** ✓ 各 cycle 都能挖到 IC > 0 的 factor
- **breadth (有效独立股票数)** = N / (1 + (N-1)ρ)，N=78, ρ=0.4 → 实际只有 ~12
- **TC (Transfer Coefficient = 信号→实际仓位转化率)** = **0.45-0.55 (long-only 天花板)**

**结论**: cycle04-10 的"长仓 + 月度调仓 + top-N + 78 股票"这套组合，TC ceiling 是结构性天花板，不管换啥 factor / objective / weights / regime 都过不了。

**Sibling-by-NAV** = TC ceiling 在 NAV 上的体现：所有 trial 的组合都 ~30-50% 重叠（数学上必然 corr 0.85-0.95）。

---

## 🚀 今天（2026-05-14 + 13 两天）做了什么

### 1️⃣ K1 = 给"逃出 TC ceiling"打地基（2026-05-13）

**做了什么**: 写了新的回测引擎 wrapper `SignalDrivenBacktest`。

- **老引擎 (BacktestEngine)**: 接收每日"目标权重表"（"今天 AAPL 20%, MSFT 15%..."），按表执行
- **新 wrapper (SignalDrivenBacktest)**: 接收**入场信号** + **确认条件** + **离场信号**，引擎自己跑状态机：
  - "信号在 T 出现 → ARMED"
  - "等 T+1..T+TTL 内确认 → CONFIRMED"
  - "T+confirm+1 开盘建仓 → 持仓 N 天 → 离场"

**为啥要做**: cycle04-10 的 bundle binding 就是因为"月度调仓 / top-N 固定 / 长仓"是写死的。要逃 TC ceiling，需要换 **horizon (时间尺度)** 或 **cadence (节奏)**。

**结果**: 30 个 TDD 测试全绿 + 200+ 个 regression 不动 + 老引擎完全不动（M11a/M11b parity 保持）。

### 2️⃣ SPY 数据 +1 天 bug 发现 + 修复（2026-05-13）

**怎么发现**: K1 ship 后跑大范围 regression，有 3 个 `forward bar_hash` 测试失败 → 调试发现 `data/daily/SPY.parquet` 每条数据日期标签**都晚了 1 个日历日**（周一交易标周二，周五标周六）。

**影响范围**: SPY + BIL + SHV 三个 PQS-active 标的（yfinance fetch 路径）。**Stocks 自身数据 (AAPL/MSFT 等) 干净。**

**根因**: `core/data/calendar.py::align_daily_index` 函数 strip 时区前没转 ET（美东时区）。UTC 0 点 = 美东前一天 7 点，直接 strip → 跨了一天。

**修复 (Option A.1-A.7)**:
- 修 align_daily_index 用 `tz_convert("America/New_York").tz_localize(None)`
- 重 fetch SPY / BIL / SHV (4870 / 4769 / 4864 行干净数据)
- defense-in-depth 修了 3 个潜在同 pattern bug (market_data_store / rebuild_daily / observe_options_forward)
- 跑全量 audit (R1 grep 30 个 tz_localize 点 / R2 logic / R3 DST 边界 / R4 实跑)

**对历史结果影响**:
- ✅ cycle04-10 numerical 数字 deprecated（受影响 0.5-2pp/yr），qualitative 结论**加强了**（1 天 phase shift 会**稀释** Pearson correlation，所以真实 sibling 比测到的 0.85-0.95 **更高**）
- ✅ K1 ship 不受影响（synthetic 测试）
- ✅ simple_baseline_v1 不受影响（yfinance 直接 download，不走 BarStore）

### 3️⃣ T1 三个 alpha 探索 sleeve（2026-05-13 → 2026-05-14）

试了 3 个不同 horizon/cadence 的 alpha 来源，验证 TC ceiling 能否真的逃脱：

#### T1a alt-A intraday reversal

**策略人话版**: 找上周跌得多 + 今天早上 60 分钟 K 线放量 + 早盘上涨的股票 → 买入持 5 天。

**结果**:
- 2018-2025 (8 年) 总回报 +25.3% vs SPY +156% → **大输 -130pp**
- BUT NAV 跟 cycle04-08 candidates 相关性 **0.15** (vs cycle04-08 之间互相 0.85-0.95) → **第一次证实 horizon change 真的能逃 sibling**
- Track A 14/17 PASS, 3 个 vs SPY/QQQ 门 FAIL
- **结构性 informative null**: alpha 太薄（只在 ~3% 交易日有仓位，剩下 97% 持现金赚 0%）

#### T1b ConfirmationPatternStrategy

**策略人话版**: 股票创 20 天新高时进场 (breakout)，等 5 天内有 1% 跟进确认，持有最多 21 天。

**结果**:
- 2017-2025 (9 年) 总回报 **+428%** vs SPY +203% → **赢 +225pp, CAGR 20.3%**
- 但年度 vs SPY: 2018 +10%, 2019 **-17%**, 2021 +11%, 2023 +3%, 2025 **-15%** → 5 年中 2 年大输
- Track A FAIL on **year-consistency**（aggregate vs SPY 失败 + 2025 vs QQQ -23%）
- 跟 alt-A daily-return correlation **0.17** → fleet-complementary
- Beta to QQQ 0.43（vs alt-A 的 0.07）

**判定**: alpha 是真的（20% CAGR），失败在"年年都要赢"的纪律上 → 适合做 fleet 组件，不适合单独上。

#### T1c FOMC + PEAD event-calendar

**FOMC pre-announcement drift**:
- 学术 paper claim: FOMC 公告前 24h SPY +49bps (Lucca-Moench 2015)
- PQS 实测 2017-2025: mean **+8.8 bps**（1/5 强度）, 9 年累计 +5.81% = CAGR **0.64%**
- 验证 FRL 2021 paper 说的 "drift disappeared after 2015" → **dead signal**

**PEAD (财报漂移)**: 需要 per-symbol earnings 日期 ingest（SEC EDGAR），~1-2 周工作 → **defer 等 user explicit-go**

### 4️⃣ T2 cycle11 信号驱动 mining（2026-05-14 → 今天）

**cycle04-10 总结**: 在固定 monthly + top-N 框架下挖矿，TC ceiling 卡死。
**cycle11 新思路**: 挖 **信号 × 确认 × 离场 × 持仓天数** 的联合空间，不打分固定股票，而是按信号触发调仓。

**T2a**: cycle11 PRD（信号驱动 mining 框架），search space 包括 6 个 seed signal + 4 个 confirmation 类型 + 4 个 exit 类型 + 4 个 regime gate + cardinality。

**T2b mini-smoke**: 20 trial 在 3 个 seed (Faber / Donchian / Connors RSI(2)) × 7 个 config 组合上跑了一遍。

**Smoke @ 5bp 成本（不真实，太宽松）**:
- **20/20 trial 全部超过 SPY Sharpe**（0.76）
- Top: **Connors RSI(2) + hold 3 days → Sharpe +3.54, CAGR +56%, MaxDD -13.9%**
- 这是 PQS 史上**第一次**所有挖矿尝试都赢市场基准

**Cost sensitivity 一查**:
| 滑点 | Sharpe | CAGR | 评价 |
|---|---|---|---|
| 5bp | 3.54 | +56% | 太乐观 |
| 15bp | 2.43 | +35% | 还行 |
| **30bp（零售 at-market 实际）** | **0.67** | +8% | 不如 SPY |
| 50bp | -1.74 | -21% | 亏钱 |

**真相**: Connors RSI(2) 9 年要做 ~7000 笔交易 → 实际成本 30bp/leg × 7000 trades × 5 positions = 大约消灭 50%+ 的 backtest alpha。

**T2c ML Phase 2 架构草稿**: 用 ML 训练一个"哪些信号值得交易"的 cost-aware filter（不是 alpha 来源，是 cost-aware filter），放在 cycle11 信号之上。架构文档已写，待 cycle11 全 mining 跑出数据再 build。

### 5️⃣ Cost Gate Revision 6× (2026-05-14)

per 用户 directive: 把 Track A 成本鲁棒性门从 2× 改 6×（针对高换手策略）。

**实施**:
- cycle04-10 archive 不动（locked_after_first_use）
- cycle11+ 新 mining baseline 滑点 5bp → **30bp** (= 6× cycle04-10 标准)
- 计算: 现 Track A 的 `multiplier_2x_must_remain_positive` 在 30bp baseline 上 = 实际 60bp = 12× of cycle04-10 原始 5bp
- 文档: `docs/memos/20260514-cost_gate_revision_6x.md`

**cycle11 re-smoke at 30bp baseline**: 已启动后台运行（~10-15 min），结果待 commit。

---

## 📊 当前 active candidate 都是干啥的

| Candidate | 角色 | 在做啥 | 状态 | 关键数字 |
|---|---|---|---|---|
| **simple_baseline_v1** | wealth-vehicle baseline（你真钱投的方向） | 70% MTUM + 30% TQQQ + VIX 防御 + Faber 200-SMA risk-off gate | **Paper trading 中**（init 2026-05-13） | CAGR 14.9% vs SPY 10.5%, Sharpe 0.82, per-year MaxDD ≤25% |
| **trial9_diversifier_002** | research diversifier (不打 alpha，打"跟主流 NAV 不一样") | forward observe，clean SPY 数据重 init | Status not_started（下次 daily ritual 写 TD001） | TD60 verdict ~2026-08-06 |
| **spy_8otm_bull_put_v1** | options sleeve (卖 SPY 8% OTM 看跌价差) | options paper, TD005 | active | TD60 verdict ~2026-07-30 |
| **alt-A intraday reversal** | informative null | 关闭 / 文档 | 不部署 | 0.15 raw corr ✓ / -130pp alpha ✗ |
| **T1b ConfirmationPattern** | informative-positive | 关闭 / 文档 | 未来可能进 TAA fleet | 20.3% CAGR ✓ / year-inconsistent ✗ |
| **cycle11 Connors RSI(2)** | smoke evidence | 待 30bp baseline re-smoke | 暂停 | 5bp Sharpe 3.5 / 30bp Sharpe 0.67 |

---

## 🧩 PQS 现在的"战略地图"

```
长仓 + 月度 rebalance + 78 股 + top-N（cycle04-10 bundle）
  │
  │  5 个 mining cycle 全 0 nominee
  ↓
TC ceiling = 长仓 transfer coefficient 0.45-0.55 是结构性天花板
  │
  ↓ 3 个 legitimate 逃脱方向（roadmap v2 §2.2 论证）:
  │
  ├── horizon change（换时间尺度）
  │   └── alt-A intraday: 逃了 sibling (0.15 corr) ✓ 但 alpha 太薄 ✗
  │   └── T1b ConfirmationPattern: 逃了 sibling (0.17 corr) ✓ + 20% CAGR alpha ✓
  │       但 year-consistency 失败 ✗
  │
  ├── cadence change（信号驱动 不再日历驱动）
  │   └── cycle11 mini-smoke: 20/20 beat SPY @ 5bp ✓
  │       但 30bp realistic cost 杀掉 alpha ✗ → 需要 cost-aware filter
  │       Connors RSI(2) 是真信号；问题是 cost 控制
  │
  └── cross-asset done RIGHT（20+ ETF 真正 asset-class breadth）
      └── ⏸️ 未尝试（roadmap 里有，T1 之后才考虑）
```

---

## 📈 真实 backtest 结果汇总

> 注：cycle04-10 numerical 数字标 (deprecated)，是用 buggy SPY 算的 vs SPY 数字 0.5-2pp/yr 不准。但相对排序和 sibling 现象不受影响。

| 策略 | 窗口 | CAGR | vs SPY | Sharpe | MaxDD | 状态 |
|---|---|---|---|---|---|---|
| **simple_baseline_v1** | 2016-2024 train | +14.9% | +4.35pp/yr | 0.82 | per年≤25% | ✅ ship paper |
| **SPY 基准** | 2017-2025 | +13% | — | 0.76 | -34% | 基准 |
| T1a alt-A intraday | 2018-2025 | +2.9% | -16pp/yr | (low) | -18% | ❌ 关 |
| **T1b ConfirmationPattern** | 2017-2025 | **+20.3%** | **+7pp/yr** | (high) | -34% agg | 🟡 关（年度不稳） |
| T1c FOMC pre-drift | 2017-2025 | +0.6% | -12pp/yr | ~0 | (small) | ❌ 关（dead） |
| cycle11 Connors RSI(2) @ 5bp | 2017-2025 | +56% | +43pp/yr | **+3.54** | -14% | ⚠️ unrealistic cost |
| cycle11 Connors RSI(2) @ 30bp | 2017-2025 | +8% | -5pp/yr | 0.67 | -19% | 🟡 cost-fragile |
| Trial 9 v2 forward | TD001 未写 | — | — | — | — | 🆕 等 daily ritual |
| spy_8otm_bull_put_v1 paper | 2026-05-04 至今 | — | — | — | — | 🆕 paper TD005 |

---

## 🎯 honest verdict

1. **TC ceiling 是真的** — 5 个 mining cycle 验证过，sibling-by-NAV 是结构性天花板
2. **horizon/cadence change 真的能逃 TC ceiling** — 这是 PQS 史上第一次正面证据 (alt-A 0.15 / T1b 0.17 / cycle11 全 beat SPY)
3. **但 escape ≠ 自动赚钱**:
   - alt-A: alpha 太薄
   - T1b: alpha 真但 year-inconsistent
   - cycle11: alpha 真但 cost-fragile
4. **cycle11 + ML Phase 2 cost-aware filter 是最 hopeful 的方向**
5. **simple_baseline_v1 是你真钱方向的 default baseline**（CAGR 14.9% > SPY 10.5% on train window）

---

## ⏭️ 下一步路径

### 🔄 Autopilot（不需要决定）
- simple_baseline_v1 paper soak daily
- Trial 9 v2 forward observe daily（下次数据来时 写 TD001）
- options paper observe daily

### ⏳ 待 verdict
- Trial 9 v2 TD60 verdict ~2026-08-06
- options paper TD60 verdict ~2026-07-30

### 📋 待你 explicit-go
- cycle11 full 200-trial mining（~1 天 compute）— 等 30bp re-smoke 结果
- T2c ML Phase 2 cost-aware filter build（~2 周 eng）— 等 cycle11 full mining 输出
- PEAD ingest + 单独 sleeve（~1-2 周 eng）

### 🟢 In-progress
- cycle11 30bp re-smoke 后台运行中（~10-15 min）

---

## 🎓 PQS 现在学到的"东西"清单

1. **TC ceiling (Clarke-de Silva-Thorley 2002)** = long-only 量化策略的结构性 alpha 天花板
2. **Sibling-by-NAV** = TC ceiling 在 NAV 层的具体表现，0.85-0.95 是基础市场 beta 不可避免共享
3. **Mining cycle 数量不解决根本** = 5 个 cycle 不同变量都不行，5 个独立验证
4. **Horizon change + Cadence change** = 真的能逃 sibling，但 alpha 来源不一定够
5. **Cost is the new bottleneck** = 高换手 alpha 看起来漂亮，realistic 成本一上就崩
6. **Tests + data discipline** = 之前没有 weekend-row scan，SPY off-by-one bug 跨 5 个 cycle 没被 catch（已加 memory rule + audit）

---

## 📝 今天 (2026-05-14) 提交的 commit list

```
47f03b1 T2b cycle11 mini-mining smoke + T2c ML Phase 2 architecture
a8fe459 T2a cycle11 signal-driven mining PRD DRAFT
b8c1baa T1c FOMC drift smoke + closeout — FOMC dead, PEAD deferred
0728334 T1b ConfirmationPatternStrategy closeout — high-CAGR sleeve, Track A FAIL
e9a4776 T1a alt-A intraday reversal closeout — informative null
+ this commit: cost gate revision + re-smoke + this summary
```

加上 2026-05-13 的 K1 + SPY fix + T1a.2 + T1a.3 + audit，今天累计 ~17 commit。

---

**End of summary v1**. 本文档应该足够让未来的 you（或者 codex / 其他人）30 分钟内回看到 2026-05-14 PQS 系统状态。

---

## 🚀 2026-05-14 晚上 update — cycle11 re-smoke @ 30bp realistic cost

完整 closeout: `docs/memos/20260514-t2b_cycle11_resmoke_v2_realistic_cost.md`

**结果**: 20 trial mini-mining 在 30bp 现实成本下：

| 数字 | smoke v1 (5bp 太宽松) | smoke v2 (30bp realistic) |
|---|---|---|
| 超 SPY Sharpe (0.76) 的 trial 数 | 20/20 | **15/20** |
| Top winner | Connors RSI(2) hold=3 @ Sharpe 3.54 | **Donchian-20 hold=21 @ Sharpe 1.31** |
| Top winner CAGR | 56% (cost-fragile) | **21.24%** (robust) |
| Top winner MaxDD | -13.9% | -17.5% |
| Top winner n_trades | 7387 (高换手) | 3259 (中等换手) |

**Top-5 排名彻底翻转**:
- 5bp top-5: 4 个 Connors + 1 个 Donchian（高换手 mean-reversion 胜）
- 30bp top-5: **4 个 Donchian + 1 个 Connors**（中期 trend-following 胜）

**真相揭露**: smoke v1 的 Connors RSI(2) Sharpe 3.54 是 **cost-fragility 幻觉**。真正稳健的 alpha 来源是 **medium-hold Donchian breakout**。

**核心 verdict**:
- 🎉 **cycle11 alpha 在 realistic cost 下幸存** —— 这是 PQS 史上**第一次** mining 在现实成本下产出多个 SPY-beating trial
- 真实 alpha 排序：medium-hold trend > short-hold mean-reversion > Faber long-hold
- Faber 是最稳的（cost-robust）但 alpha 也最低
- 高换手 Connors 需要 T2c ML cost-aware filter 才能用

**下一步推荐**:
1. 快速 Track A spot-check on Donchian-20 hold=21（10 min）
2. 如果过 → full 200-trial cycle11 mining 授权（~1 天 compute）
3. T2c ML Phase 2 build 等 cycle11 输出再上

---

**真实 backtest 结果汇总更新版**：

| 策略 | 窗口 | CAGR | vs SPY | Sharpe | MaxDD | 状态 |
|---|---|---|---|---|---|---|
| **simple_baseline_v1** | 2016-2024 train | +14.9% | +4.35pp/yr | 0.82 | per年≤25% | ✅ ship paper |
| **🆕 cycle11 Donchian-20 hold=21 @ 30bp** | 2017-2025 | **+21.24%** | **+8pp/yr** | **+1.31** | **-17.5%** | 🟡 待 Track A spot-check |
| **SPY 基准** | 2017-2025 | +13% | — | 0.76 | -34% | 基准 |
| T1b ConfirmationPattern @ 5bp | 2017-2025 | +20.3% | +7pp/yr | (high) | -34% agg | 🟡 关（年度不稳） |
| cycle11 Donchian-100 hold=60 @ 30bp | 2017-2025 | +17.59% | +4pp/yr | +1.06 | -23% | 🟡 cycle11 alt |
| cycle11 Connors @ 5bp (illusion) | 2017-2025 | +56% | +43pp/yr | +3.54 | -14% | ⚠️ cost-fragile |
| cycle11 Connors @ 30bp (real) | 2017-2025 | +8% | -5pp/yr | 0.67 | -19% | ❌ cost-fragile |
| T1a alt-A intraday | 2018-2025 | +2.9% | -16pp/yr | (low) | -18% | ❌ 关 |
| T1c FOMC drift | 2017-2025 | +0.6% | -12pp/yr | ~0 | (small) | ❌ 关 |

**最强 candidate（cost-robust + alpha + low MaxDD）**: cycle11 **Donchian-20 hold=21**（Sharpe 1.31 / CAGR 21.24% / MaxDD -17.5%）—— 这是 PQS 史上第一个在 30bp realistic cost 下同时满足 alpha + cost robustness + low MaxDD 的 candidate。Track A 17-gate 是否过待验证。

**End of summary v2**.
