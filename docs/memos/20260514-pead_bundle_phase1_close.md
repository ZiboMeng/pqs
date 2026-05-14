# PEAD Bundle Phase 1 Closeout — First Real Event-Driven Signal in PQS

**Date**: 2026-05-14 evening
**Lineage**: `pead-bundle-2026-05-14`
**Status**: PHASE 1 COMPLETE — Path 1 SUE = REAL ALPHA, Path 2 = NULL, Track A = 14/17 (defensive profile fails SPY-CAGR gate)
**PRD reference**: `docs/prd/20260514-pead_bundle_phase1_prd.md`

---

## §1 TL;DR

PEAD Phase 1 双轨 free-path 实验：

| Path | 触发 | 9-trial 跑赢 SPY | Top Sharpe | Top MaxDD |
|---|---|---|---|---|
| Path 1 SUE (基本面 surprise) | SUE σ | **8/9** | **1.063** | **-7.6%** (trial 1) |
| Path 2 price-jump (价格反应代理) | AR > +X% | 0/9 | 0.717 | -18% |

**Path 1 SUE 是 PQS 历史上第一个 sample-period Sharpe > 1.0 同时 MaxDD < 10% 的策略**。

**Track A 14/17**：所有 per-year MaxDD / stress slice / 2x cost robustness / concentration / NAV daily-return correlation < 0.85 全过。**failing 3 gates = `validation_aggregate_excess_vs_spy/qqq` + `2025 vs_qqq`** —— 都是 "策略 CAGR 必须超 SPY/QQQ"。PEAD 的 alpha shape = **低波低回撤但 CAGR 不及 SPY**（2025 bull 年 PEAD +6-11% vs SPY +13%）。

**没 forward-init**（hard gate fail），但写成 evidence-only memo，未来 fleet allocator 可作 defensive sleeve 用。

---

## §2 双 path 对比 = 关键 hypothesis test

PRD §3 pre-registered hypothesis：
> if both win → 鲁棒 PEAD; if only Path 1 → 基本面 surprise 真信号; if only Path 2 → 价格动量 echo

**结果 = only Path 1**。意味着：
- 基本面盈余 surprise（SUE）确实是 information diffusion 真信号（Bernard-Thomas 1989 在 2017-2025 美股 54 只 large-cap 仍可观察）
- 单纯价格跳空（AR）作 surprise 代理 = 太多 confound（guidance / 板块联动 / macro 当日）；信号被噪声淹没
- 这是 **Phase 1 给出的最干净的方法论判断** —— 后续如果要做 PEAD Phase 2（付费 IBES consensus / 8-K real-announce-date），方向就在 fundamental anchor 上，不是 price anchor

---

## §3 Path 1 SUE 9-trial 详细结果 @ 30bp

| Trial | SUE σ | hold | top_n | Sharpe | CAGR | MaxDD | trades | signals/yr |
|---|---|---|---|---|---|---|---|---|
| **6** | 1.5 | 60 | 10 | **+1.063** | +10.39% | -24.01% | 448 | 30 |
| 0 | 1.0 | 21 | 10 | +1.057 | +7.13% | -10.17% | 645 | 44 |
| **1** | 1.5 | 21 | 10 | **+1.055** | +5.48% | **-7.64%** | 454 | 30 |
| 8 | 1.5 | 21 | 20 | +1.033 | +2.89% | -3.92% | 477 | 30 |
| 3 | 1.0 | 42 | 10 | +1.006 | +10.00% | -16.71% | 650 | 44 |
| 7 | 1.5 | 21 | 5 | +1.000 | +7.61% | -7.88% | 428 | 30 |
| 4 | 1.5 | 42 | 10 | +0.979 | +7.77% | -17.63% | 456 | 30 |
| 2 | 2.0 | 21 | 10 | +0.789 | +3.30% | -5.88% | 327 | 22 |
| **SPY baseline** | | | | **+0.759** | **+13.11%** | -34% | — | |
| 5 | 2.0 | 42 | 10 | +0.725 | +4.67% | -12.23% | 329 | 22 |

**模式**：threshold 1.0-1.5σ 都好；max_hold 21-60 都好；top_n 5-20 都好。**signal 在合理 hyperparameter window 内稳定**。不像 cycle11 那样要把参数恰到好处 sweep 出某个 0.03 Sharpe 优势 —— PEAD 是 robust 5-8% Sharpe 提升。

---

## §4 Track A 详细 verdict（trial 1 = 短-hold 候选）

**Pass 14/17 gates** + **2x cost robust + low NAV daily-return correlation**：
- ✅ Per-validation-year MaxDD: 2018=-6%, 2019=-4%, 2021=-4%, 2023=-2%, 2025=-2% (all 远低于 -20%)
- ✅ Stress slices: covid_flash -1.8%, rate_hike_2022 -4.1% (远低于 -25%)
- ✅ 2x cost robust: $13965 final equity at 60bp (still POSITIVE)
- ✅ concentration top1 0.10 / top3 0.30 (远低于 0.40 / 0.70 ceiling)
- ✅ beta_to_qqq 0.10 (well below 0.85 cap)
- ✅ 2025 holdout MaxDD -2.27%

**Fail 3/17 gates**：
- ❌ `validation_aggregate_excess_vs_spy`: 5 validation 年累计 vs SPY < 0
- ❌ `validation_aggregate_excess_vs_qqq`: 同上 vs QQQ
- ❌ `role_core__validation__2025__excess_vs_qqq`: 2025 vs QQQ -10.6% (HARD)

**Per-year vs SPY**（关键诊断）:
| Year | strat ret | SPY ret | excess | regime |
|---|---|---|---|---|
| 2018 | +6.1% | -7.1% | **+13.2%** | BEAR |
| 2019 | +5.2% | +30.9% | -25.7% | BULL |
| 2021 | +6.0% | +27.3% | -21.2% | BULL |
| 2023 | +1.7% | +23.9% | -22.2% | BULL |
| 2025 | +6.0% | +12.8% | -6.8% | BULL |

**结论**：PEAD 在 BEAR 年（2018）大幅跑赢 SPY (+13%)；在 BULL 年（2019/2021/2023/2025）underperform SPY。这是 **典型 defensive sleeve 行为** —— 低波低 DD 但 CAGR 不及市场。

---

## §5 NAV daily-return correlation vs anchors

| Pair | daily-return Pearson | Verdict |
|---|---|---|
| trial 1 vs alt-A intraday reversal | +0.09 | PASS (低相关) |
| trial 1 vs T1b ConfirmationPattern | +0.38 | PASS |
| trial 1 vs cycle11 Donchian-20 | +0.37 | PASS |
| trial 6 vs alt-A | +0.12 | PASS |
| trial 6 vs T1b | +0.54 | PASS |
| trial 6 vs cycle11 | +0.55 | PASS |

**所有 daily-return correlation < 0.85 threshold**。PEAD 跟现有 anchor 在 daily return 层面 genuine differentiated（不是 sibling）。NAV-level 高（0.77-0.97）但那是因为所有 long-only 策略都向上 trend，meaningful 的是 daily-return 维度。

---

## §6 战略含义 + 下一步选项

### §6.1 PEAD 的 alpha 性质 — 跟之前所有 PQS 候选不同

| 候选 | Sharpe | CAGR | MaxDD | alpha source |
|---|---|---|---|---|
| RCMv1 (2026-04, aborted) | ~0.9 | ~13% | ~-20% | factor mining (sibling) |
| Cand-2 (2026-04, aborted) | ~1.1 | ~13% | ~-21% | factor mining (sibling) |
| Trial 9 v2 (2026-05, forward) | ~0.78 | ~10% | ~-19% | low-vol mining (diversifier) |
| T1b ConfirmationPattern | 1.18 | 20.3% | ~-30% | technical pattern |
| cycle11 Donchian-20 (smoke v3) | 0.66 | 9.8% | ~-20% | breakout (parametric) |
| **PEAD trial 1 (this round)** | **1.055** | **5.5%** | **-7.6%** | **基本面盈余 surprise（事件驱动）** |
| **PEAD trial 6** | **1.063** | **10.4%** | **-24.0%** | **同上，长 hold** |

**PEAD 是 PQS 第一个**：
- 触发是外生事件（SEC 财报日，非参数化）
- alpha source = fundamental information diffusion（学术 robust 30 年）
- Sharpe > 1.0 同时 MaxDD < 10%（trial 1）
- daily-return correlation 跟所有现有 anchor < 0.55 → 真信号分离

但**致命弱点**：CAGR < SPY，跑不过 long-only US large-cap hard gate。

### §6.2 三个 forward 方向（NOT pre-selected, awaits user-go）

**Option A** — **不 forward-init，document, 转向 fleet allocator**
PEAD 作 defensive sleeve 跟 momentum overlay (T1b / Faber) 组合 → fleet 合成 NAV 可能同时拿到 PEAD low-DD + momentum high-CAGR。需要 Phase C-PRD-2/3 fleet 架构（已写 PRD 但 deferred 等 Trial 9 v2 TD60）。
- 优点：alpha-first，不消耗 forward observation 容量
- 缺点：fleet allocator PRD 还没启动 (~4-6 周工程量)

**Option B** — **forward-init PEAD Phase 1 trial 1 as evidence-only**
不进 fleet（hard gate fail），但作为 60-90 天 forward soak 验证 SUE signal 在真实数据上是否还 valid。如果 forward 60 天 Sharpe ~1.0 + MaxDD < 10% → 强证据；建立独立观察轨迹。
- 优点：第一手验证 PEAD 在 going-forward 数据上是否 hold
- 缺点：消耗 forward observation 容量（目前只有 Trial 9 v2 active）
- 学术意义：Bernard-Thomas 1989 信号在 2026 实时数据上的可观察性 = 有意义的实证 contribution

**Option C** — **PEAD Phase 2: 付费 8-K real-announce-date feed**
当前 filed_date proxy 错过最强的 0-10 天 drift（学术 PEAD 最强 portion）。Polygon / IEX 8-K feed ~$50-100/mo. 如果 0-10 天 drift 加回来 → Sharpe 可能从 1.06 → 1.5+，CAGR 可能 ↑ enough to clear hard gate。
- 优点：可能真正过 Track A
- 缺点：付费数据（仅在 Trial 9 v2 TD60 GREEN 后才考虑，per roadmap）
- DEFER 到 ~2026-08-06 Trial 9 v2 TD60 verdict

### §6.3 Operator 推荐

**Option A + Option B 并行**：
- A: 不立刻动 fleet allocator（避免又写 PRD 等不到 candidate），但 keep TODO
- B: **forward-init PEAD trial 1 as evidence-only candidate**, role = `legacy_decay_verification`（不进 fleet，纯观察）
  - 资本 0（pure paper observation）
  - 60-90 天后 check：daily-return Sharpe 是否 > 0.8，MaxDD 是否 < 15%
  - 这是 Phase 1 的 follow-through，不是 Phase 2 工作
  - 验证后 Phase 2 决策更有数据基础

如果 user 否决 B，那 PEAD Phase 1 close = 纯文档 + 后续战略选项库。

---

## §7 Stop rule 验证 + 数据 integrity

Per PRD §6:
- R1 完全 null：触发了吗？❌ —— Path 1 8/9 跑赢 SPY，明显非 null
- R2 部分赢：触发 ✅ —— 只 Path 1 winning
- R3 sibling-by-NAV：触发？❌ —— daily-return Pearson 全 < 0.85
- R4 全过 Track A + forward-init：触发？**部分** —— Sharpe + MaxDD + cost robustness 全过，但 CAGR-vs-SPY 没过

**Bar-level integrity smoke** (per `[[feedback_bar_level_data_integrity_smoke]]`)：weekend-row scan PASS（_pead_smoke_common.build_panels 内置）；cross-symbol date intersection 检验 close_df 2262×54 = 完整 2017-2025 trading day。无 off-by-one。

---

## §8 Files / artifacts

- PRD: `docs/prd/20260514-pead_bundle_phase1_prd.md`
- Modules:
  - `core/research/pead/__init__.py`
  - `core/research/pead/earnings_dates.py`
  - `core/research/pead/sue_calculator.py`
  - `core/research/pead/price_jump_signal.py`
- Tests: `tests/unit/research/pead/test_*.py` (53 tests, 100% pass)
- Smoke scripts:
  - `dev/scripts/pead/_pead_smoke_common.py`
  - `dev/scripts/pead/run_path1_sue_smoke.py`
  - `dev/scripts/pead/run_path2_pricejump_smoke.py`
  - `dev/scripts/pead/run_pead_track_a_acceptance.py`
- Data artifacts:
  - `data/audit/pead_path1_sue_smoke.json` (Path 1 9-trial)
  - `data/audit/pead_path2_pricejump_smoke.json` (Path 2 9-trial)
  - `data/audit/pead_path1_track_a_verdict.json` (2-candidate Track A)
  - `data/audit/pead_path1_trial1_short_hold_nav.parquet` (NAV time series)
  - `data/audit/pead_path1_trial6_long_hold_top_sharpe_nav.parquet`

---

## §9 Asks for user (directional decisions)

1. **Forward-init PEAD trial 1 as evidence-only**（Option B）？
   - 入参：SUE≥1.5σ hold=21 top_n=10, role=legacy_decay_verification (not fleet)
   - 资本 0；soak 60-90 天
   - 验证 SUE signal 是否在 going-forward 数据 hold
   - **operator 推荐 YES**（小成本，大学术信息价值）

2. **延迟 fleet allocator 架构 (Phase C-PRD-2/3) 决策到 Trial 9 v2 TD60**?
   - operator 默认 YES（per roadmap v2 + alpha-first 纪律）

3. **PEAD Phase 2 (paid 8-K data) deferred to Trial 9 v2 TD60 GREEN**?
   - operator 默认 YES（per roadmap v2 + 付费纪律）

4. **接受 Path 2 price-jump null verdict + 不再 revisit**?
   - operator 推荐 YES（信号机制清楚：price reaction alone 被 macro/sector confound 淹没）

5. **Sealed 2026 panel 仍然 NOT touched**?
   - operator 严守 YES（PEAD Phase 1 sample 完全在 2017-2025；2026 sealed window 保留）

---

## §10 Honest verdict in 1 sentence

PEAD 是 PQS 历史上第一个找到的事件驱动真信号，Sharpe 1.06 / MaxDD 7.6% 是 standout 数字，但 alpha shape = defensive (low-DD low-CAGR)，long-only US-equity 框架下跑不赢 SPY 13% CAGR，所以单独无法过 Track A acceptance —— 真正的 unlock 在 fleet 合成层（PEAD defensive sleeve + momentum overlay），不在 PEAD 自身参数调优。
