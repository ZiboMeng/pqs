# PQS Mining 流程 + Universe + 历史结果 通俗汇总

**Date**: 2026-05-14 evening
**Audience**: senior US-equity quant operator (用户)
**目的**: 把 PQS mining pipeline 从头到尾说清楚（包括术语翻译），把 cycle04-11 + PEAD 结果按时间线 + 结论梳理一遍

---

## §1 Universe（候选股池）= 选股范围

### §1.1 配置文件位置
`config/universe.yaml`，**单一来源**（single source of truth）。

### §1.2 两层 universe 架构

| 层 | 用途 | 内容 |
|---|---|---|
| **Execution universe**（执行池） | 这是 mining + backtest + paper trading **实际能拿的股票** | 包含 ETF（如 SPY/QQQ/TLT）+ 杠杆（如 TQQQ/SOXL）+ 普通股 |
| **Admission whitelist**（准入清单） | 用于"考虑要不要往 execution 池里加新股票"时的初筛 | 只允许普通股（reject ETF / 杠杆 / ADR） |

**关键概念**：两个不是同一个东西。执行池里可以有 SPY，但筛选新股时不允许"再加一个 SPY 类股票"。

### §1.3 执行池组成（2026-05-14 当前状态）

```
seed_pool (59 个 = mining 核心池):
  - 5 个 ETF: SPY, QQQ, GLD, TQQQ, SOXL
  - 54 个普通股: AAPL, MSFT, GOOGL, ..., LLY, ACGL (Mag7 + R28 v2 + R38 v3 expansion)

sector_etfs (11): XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC
factor_etfs (5): MTUM, QUAL, VLUE, USMV, SCHD
cross_asset (7): TLT, IEF, SHY, SLV, GLD, BIL, SHV
macro_reference (3 不可交易): ^VIX, ^TNX, DX-Y.NYB

blacklist: SQQQ, SOXS (反向 ETF 永久禁用，long-only 不变量)
```

**当前 mining 普遍用的 universe**：
- cycle04-10 用 78-股 (`seed_pool` 减去几个 EDGAR / CIK 缺的)
- cycle #04 cross-asset 用 53-股 + 6 cross-asset ETF = **59**
- cycle11 信号驱动用 54-股（不含 ETF）
- **PEAD 用 54-股**（EDGAR 财报数据覆盖的所有股）

### §1.4 数据约束

- **first_trade_dates**（首次交易日）：硬编码每只股票/ETF 的最早可用日期；symbol 必须有 `min_history_days=252` 才进 candidate pool —— 防止 survivorship bias = 幸存者偏差
- **liquidity 阈值**：`min_avg_volume_30d=1M shares`, `min_price_usd=5`, `min_history_days=252`
- **high_risk_symbols**（高风险标的）：TQQQ + SOXL 强制 `max_single_weight=10%, max_total_weight=12%, require_risk_on_regime=true`
- **max_selected_symbols=10**（默认 top-N=10）/ `min_selected_symbols=2`

---

## §2 Mining Pipeline = 因子挖掘 整个流程

### §2.1 输入

```
Universe yaml (谁可以买)
  +
Factor Registry (157 个 research factor + 7 个 production factor)
  +
Temporal Split yaml (训练/验证/sealed 时间窗口划分)
  +
Risk Cluster Map (53-stock + 5 cross-asset ETF 的 risk-cluster 分类)
  +
Cost Model (commission_bps + slippage_bps)
```

### §2.2 流程图（cycle04-10 monthly + top-N + long-only 经典版本）

```
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: PRELIGHT AUDIT 预审计                                    │
│  - Universe coverage check（每只 symbol 都有数据吗？）              │
│  - EDGAR 缓存检查（fundamentals 因子需要）                          │
│  - Weekend-row scan（防 2026-05-13 SPY off-by-one bug 复发）        │
│  - Temporal split sha256 lock                                      │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 2: FACTOR GENERATION 因子计算                                │
│  - 读 BarStore (adjusted=True split-adjusted 价格)                 │
│  - 算 143 个 research factor (按 family A-P 分组)                   │
│  - PIT 严格: 每日 factor value 只用截止当日的数据                    │
│  - mask: research_mask (price > $5, volume > $20M/day, etc.)       │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 3: TPE Optuna SAMPLING 复合因子采样                           │
│  - 200 trials per cycle (默认)                                      │
│  - 每个 trial 采样 1 个 composite spec:                              │
│      - 选 3-6 个 family (例如 A+B+F)                                │
│      - 每个 family 选 1-2 个 factor                                  │
│      - 给每个 factor 分配 weight (相加 = 1)                          │
│  - Sampling mode:                                                   │
│      - "independent" (cycle04-09 默认): 各 family 独立挑因子          │
│        → P(valid spec) ≈ 0.0005% at 17-family 配置 (cycle #09 死在这) │
│      - "family_first" (cycle #09+ 修复): 先选 k 个 family, 再每个挑   │
│        → P(valid spec) = 100% by 构造                                │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 4: COMPOSITE EVALUATION 复合因子评估                          │
│  对每个 trial 的 composite spec:                                     │
│    Composite(t) = sum(weight[i] * zscore_cs(factor[i](t)))           │
│  截面（cross-sectional）z-score 后按 weight 求和 → 单一 composite   │
│    panel: date × symbol                                              │
│                                                                      │
│  两种 evaluation mode:                                               │
│    - v1 IC-based (cycle04-09): 算 composite 跟 21d forward return    │
│      的 Information Coefficient (IC) IC_IR = IC_mean / IC_std        │
│      objective = IC_IR                                               │
│    - v2 NAV-based (cycle10+): 直接构造 portfolio, 算 NAV Sharpe       │
│      + SPY-residual sharpe, objective = mixture                      │
│      (PRD 20260505 §2.2)                                             │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 5: SELECTOR + RANKING (训练 → 验证 跨越)                       │
│  - Selector reads (train + validation) 时间窗口                       │
│  - 但 mining 本身只读 train (per access_rules)                       │
│  - Top archived trials (typically 30-60 of 200) saved to             │
│    data/mining/rcm_archive.db                                        │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 6: TRACK A 17-GATE ACCEPTANCE 17 道闸门                       │
│  Top-3 (或 top-N) candidate 跑 acceptance evaluator:                 │
│    - 5 个 validation year (2018/2019/2021/2023/2025) 每个 MaxDD ≤ 20%│
│    - 5 年 vs SPY/QQQ 累计 excess > 0                                 │
│    - 2 个 stress slice (covid_flash/rate_hike_2022) MaxDD ≤ 25%       │
│    - 2025 holdout vs SPY > 0 (HARD), vs QQQ > 0 (HARD)                │
│    - top1 weight ≤ 0.40, top3 ≤ 0.70                                  │
│    - beta_to_qqq ≤ 0.85                                               │
│    - cost robustness: 2x cost still POSITIVE                          │
│    - no leveraged ETF dependency                                      │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 7: NAV CORRELATION ANTI-SIBLING 反"兄弟策略"                   │
│  跟现有所有 anchor (RCMv1 / Cand-2 / Trial 9 / T1b / cycle11 / etc.)  │
│  比较 NAV daily-return Pearson:                                       │
│    < 0.50 = true_diversifier (真分散)                                 │
│    0.50-0.70 = partial_diversifier                                    │
│    0.70-0.85 = warn_label_void (不能 claim diversifier)               │
│    ≥ 0.85 = reject (sibling，跟现有策略本质同源)                       │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 8: FORWARD INIT (如果 Steps 6+7 都过)                          │
│  - Freeze spec to yaml (sha256 锁定)                                  │
│  - 初始化 forward manifest                                            │
│  - Daily ritual: post-NYSE-close observe(), 加 TD entry              │
│  - TD60 verdict ~3 个月后                                             │
└──────────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────────┐
│  Step 9: SEALED 2026 EVAL (single-shot, 只可执行一次/split)         │
│  - 整个 split_name 下，core role 只能跑一次 sealed eval              │
│  - Sealed ledger (parquet) 记 sha256 + git_sha + 时间戳              │
│  - 用过就锁 → 下次必须 bump split_name → v2                          │
│  - 目前 sealed 2026 panel 从未读过                                    │
└──────────────────────────────────────────────────────────────────┘
```

### §2.3 Temporal Split = 时间窗口分割（关键 anti-look-forward 设施）

参考 `config/temporal_split.yaml` (split_name=`alternating_regime_holdout_v1`, locked since 2026-04-29):

| 用途 | 年份 | 说明 |
|---|---|---|
| **Crisis reference** | 2007-2008 | 仅作 stress 参考，**不参与 alpha 挑选** |
| **Train**（训练） | 2009-2017 + 2020 + 2022 + 2024 | mining 只读这些（access_rules 锁定） |
| **Validation**（验证） | 2018 / 2019 / 2021 / 2023 / 2025 | 跨 5 个不同 regime（rate_hike_bear / normal_bull / liquidity_mania / ai_narrow / current_market） |
| **Stress slices**（压力切片） | 2020-02-15 → 04-30 (covid_flash), 2022-08-15 → 10-15 (rate_hike) | 仅 MaxDD sanity check |
| **Sealed test**（封存测试） | 2026 | **single-shot**，全 project 历史里从未读过 |

**关键纪律**：
- mining 自己 **只看 train 数据**（access_rules.miner_may_access=["train"]）
- selector 可看 train + validation
- factor warmup 可跨边界（rolling 252d momentum 看 2018 数据给 2019 信号 = rolling 因子语义，不是 leak）
- **fail_closed_if_2026_row_in_train_panel = true** 是 runtime fail-closed guard

---

## §3 Cycle04-11 + PEAD 历史结果时间线

### §3.1 cycle04-08 — 经典 mining 5 cycle，全 0 nominee + sibling-by-NAV 反复出现

| Cycle | 日期 | 单变量改动 | 结果 | 关键发现 |
|---|---|---|---|---|
| **#04 cross-asset** | 2026-05-01 | 加 6 cross-asset ETF (TLT/IEF/SHY/GLD/BIL/SHV) + cap_aware_cross_asset 模式 | **0 nominee, 10/10 Tier 2** | Cluster A (drawup+amihud 锚) 头次 raw NAV corr < 0.85，但 mining objective 收敛到 RCMv1 锚因子 → factor_overlap 否决 |
| **#05 anchor-sensitivity** | 2026-05-01 | ban `drawup_from_252d_low + amihud_20d`（cycle04 锚） | **0 nominee, 7/10 Tier 1** ‼️ | **首次出现 Tier 1 R41 verdict**。Trial 9 (`6c745c601a47`) 14/17 gates PASS 但失 CLAUDE.md HARD QQQ rule (OOS window-mean vs_qqq=-4.59% < 0)。**这就是 Trial 9 v2 forward 来源** |
| **#06 v2 NAV-based** | 2026-05-06 | switch from IC-based to NAV-based objective (PRD-AC v1.1) | **0 nominee** | H1: Spearman v2/v1=0.89 (IR 太重); H4 anchor_corr 100% < 0.50 (但太干净，怀疑) |
| **#07a 因子 reweight** | 2026-05-07 | drawup + 短动量 锚强化 | **0 nominee → 1 nominee (post-P0 fix)** | beta_metric_path bug！9 trials 全因 `metrics["beta_to_qqq"]` 路径不一致被 false-negative。修复后 Trial 3 `1e771580f486` 17/17 PASS → NAV correlation 0.874 vs RCMv1 → **RED, evidence-only** |
| **#08 regime-conditional** | 2026-05-08 | ObjectiveWeightsV3 BEAR-IC/NEUTRAL-IC/BULL-IC | **0 nominee (40-trial smoke)** | 40-trial 不是完整 200-trial，但锚相同 |

**核心结论 from #04-08**:
- **TC Ceiling (transfer coefficient ~0.45-0.55)** = Clarke-de Silva-Thorley 2002 理论上界
- **78-股 universe + monthly + top-N + long-only** = 结构性 binding；factor swap 不能突破 sibling 几何

### §3.2 cycle09 — INVALID（采样器架构 bug）

| Cycle | 日期 | 改动 | 结果 |
|---|---|---|---|
| **#09 162-factor 池** | 2026-05-12 | Bucket A/B/C/Macro 扩展 67→162 factor + 17 family | **INVALID — 100% sampler pruned** |

**原因**：`suggest_composite_spec` independent-family-sampling 在 17 family + 3-cardinality 配置下 P(valid spec)=0.0005% → 200 trials 全 prune，0 backtest 评估。

**修复**：
- Option A `sampling_mode: family_first` shipped (commit `f41c7e5`) → P(valid spec)=100% 构造保证
- Option C T1a alt-A intraday reversal skeleton shipped

### §3.3 cycle10 — 0 nominee, R7 fail-SPY stop rule 触发

cycle10 closed 0-nominee at 2026-05-13 (per Post-cycle10 strategic roadmap memo)。R7 fail-SPY 提前停。

### §3.4 cycle11 — 信号驱动 mini-smoke, close-fallback bug 引发 audit

**T2b cycle11 mini-smoke v1** (5bp cost) → Connors RSI(2) hold=3 Sharpe **3.54** ← INFLATED

**T2b cycle11 re-smoke v2** (30bp cost) → 15/20 trial 跑赢 SPY ← STILL inflated  
verdict: Donchian-20 hold=21 Sharpe 1.31, CAGR 21.24%

**Spot-check audit (operator-initiated)**：standalone Donchian-20 hold=21 跑出 Sharpe **0.66**（vs smoke v2 的 1.31，差 0.65 Sharpe）

**Root cause**：smoke v1/v2 没传 open_df，`BacktestEngine` fallback 用同日 close 作 fill price → 对 breakout 策略**系统性高估**（T+1 OPEN 通常 gap-up 高于 T close）

**Smoke v3 post-fix** (open_df 传入):
- 3/20 marginally 过 SPY (Sharpe 0.76)
- Top: **Faber hold=252 Sharpe 0.788** (= +0.029 over SPY = 4% 边际提升)
- 全部 Connors RSI(2) 变种**亏钱** (Sharpe -0.054 到 -0.657, MaxDD -33% 到 -61%)
- Verdict: **cycle11 informative null** — 78-股 universe + 30bp + 参数化 signal-driven mining **逃不出 TC ceiling**

### §3.5 PEAD Phase 1 — 今天 (2026-05-14) 完成

Dual-track free-path 实验：

| Path | 触发 | 9-trial 跑赢 SPY | Top Sharpe | Top MaxDD |
|---|---|---|---|---|
| **Path 1 SUE** (基本面 surprise) | SUE σ thresh | **8/9** ✅ | **1.063** | **-7.6%** |
| **Path 2 price-jump** (价格跳空 proxy) | AR > +X% | 0/9 ❌ | 0.717 | -18% |

**关键 hypothesis 验证**：pre-registered "if only Path 1 → fundamental-anchored real信号" 触发 ✅。**基本面 SUE 是 information diffusion 真信号；价格跳空作 surprise 代理 = 噪声占主导**。

**Track A 14/17 gates pass**（per-year MaxDD + stress + concentration + beta + 2x cost robust 全过）。Fail 3 gates 都是 vs SPY/QQQ CAGR aggregate → PEAD alpha shape = defensive (low DD low CAGR)。

**Forward-init evidence-only**: `pead_sue_trial1_evidence_v1`, start_date 2026-05-15, TD60 verdict ~2026-08-13。

---

## §4 当前 Active Forward State（2026-05-14）

3 个 forward observation candidates 并行 soak 中：

| Candidate | Role | Start | TD60 verdict | Path | Note |
|---|---|---|---|---|---|
| `trial9_diversifier_002` | diversifier | 2026-05-13 | ~2026-08-06 | 主 forward runner (`core/research/forward`) | 从 cycle #05 来的真 diversifier 候选 |
| `pead_sue_trial1_evidence_v1` | evidence_only | 2026-05-15 | ~2026-08-13 | 独立 PEAD track (`dev/scripts/pead/observe_*`) | **今天新启动** |
| `spy_8otm_bull_put_v1` (options) | options sleeve | 2026-05-04 | ~2026-07-30 | options paper (`dev/scripts/options/observe_*`) | Phase 1 free-path soak 中 |

**3 个 TD60 verdict 集中在 2026-07-30 / 08-06 / 08-13 ~2 周窗口** —— 同时期得到 3 个独立 forward soak 数据，可整体评估 PQS 框架是否 produces 任何可放进 fleet 的 alpha source。

---

## §5 当前最强候选 + 局限

| 候选 | Sharpe | CAGR | MaxDD | Track A 状态 | 局限 |
|---|---|---|---|---|---|
| **T1b ConfirmationPattern** (Track C-外) | **1.18** | **20.3%** | ~-30% | year-inconsistent → FAIL | 是 PQS 历史 sharpe + CAGR 最高，但 year MaxDD 不过 |
| **PEAD Path 1 SUE trial 1** (today) | 1.055 | 5.5% | **-7.6%** | 14/17 FAIL (CAGR < SPY) | 第一个事件驱动真信号；CAGR < SPY |
| RCMv1 / Cand-2 (legacy) | ~0.9 / ~1.1 | ~13% / ~13% | ~-20% / ~-21% | aborted 2026-04-30 | 数据 revision drift |
| Trial 9 v2 (active) | ~0.78 | ~10% | ~-19% | diversifier role; TD60 待验 | low-vol mining diversifier |
| cycle11 Donchian-20 (smoke v3 honest) | 0.66 | 9.8% | ~-20% | 13/17 FAIL | 信号驱动参数化 still TC-ceiling-bound |

---

## §6 战略含义 + 长期判断

### §6.1 cycle04-11 集体证明了什么

**5 cycles + cycle11 informative null + Track C audit 集体证明**：
- **factor-mining 在 78-股 + monthly + top-N + long-only + 30bp 框架下找不到 SPY-beating alpha**
- 这不是因为因子库太小（已扩到 143 个），不是因为参数没调好，**是 TC ceiling 的结构性约束**
- 真正的 unlock 在以下方向（不在 factor zoo expansion）：
  1. **Horizon change** = intraday execution (T1a alt-A)
  2. **Cadence change** = event-driven signal (PEAD 今天证实是真的！)
  3. **Universe expansion** = 200+ stocks OR add bonds/commodities (cycle #04 cross-asset 部分尝试)
  4. **Strategy-type pivot** = options sleeve (已在 paper soak)
  5. **Relax long-only** = 要 user explicit-go (out of scope 当前)

### §6.2 今天 (2026-05-14) PEAD 的意义

**PEAD 是 PQS 历史上第一个事件驱动 + 非参数化触发的真 alpha 信号**。

- Sharpe 1.055 + MaxDD -7.6% 的组合**在 PQS 5 cycle + 11 cycle + T1a + T1b 所有候选里都是最干净的"信号质量"组合**
- 但 alpha shape = defensive low-vol → 单独 deploy 跑不赢 SPY
- 真正的价值在 **fleet 合成**：PEAD (low DD low CAGR) + T1b ConfirmationPattern (high CAGR but year-inconsistent) → 组合 NAV 可能同时拿到两个属性

但 fleet allocator (Phase C-PRD-2) 还没启动 → **当前 PEAD 唯一可执行 action = forward-init evidence-only 等 60 天数据**。

### §6.3 PQS 下一步关键 decision point

**~2026-07-30 到 08-13 三个 TD60 verdict 集中到来时**：
- 如果 PEAD + Trial 9 v2 + options 至少 1 个 GREEN → 触发 Phase C-PRD-2 fleet allocator 启动 + 付费数据决策
- 如果全 RED → strategic reassessment (objective / data freq / strategy type 大改, per cycle04 stop rule)
- 如果中间 (YELLOW) → 继续到 TD90

**Sealed 2026 panel 仍然 NOT touched** —— 留作最后的 single-shot test，无论那时是 PEAD 还是 fleet candidate 还是 something 新的。

---

## §7 用户最容易记错/忘的 3 件事

1. **78-股 universe ≠ 54-股 PEAD universe**：cycle04-10 用 78-股（含一些 EDGAR 缺的）；PEAD 用 54-股 EDGAR-covered；cycle11 也用 54-股。**universe 不同时直接比 Sharpe 没意义**。
2. **TC ceiling 是理论上界，不是 implementation bug**：cycle04-10 0 nominee 不是 mining 写错了，是 long-only top-N 在 78-股大盘股 universe + 30bp 真实成本下，alpha 上限就是 ~0.45-0.55 transfer coefficient，没办法靠 factor swap 突破。
3. **sealed 2026 panel single-shot 纪律**：哪怕 PEAD 看起来 ready，sealed eval 也只能跑一次/split。提前用掉就再没机会了。当前 PEAD 是 evidence-only，**不触发** sealed eval。
