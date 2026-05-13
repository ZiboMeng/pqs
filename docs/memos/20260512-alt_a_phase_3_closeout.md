# alt-archetype A Phase 3 Closeout — Track A acceptance + anti-sibling verdict

**Date**: 2026-05-12
**Status**: Phase 3 COMPLETE; **FORWARD INIT NOT AUTHORIZED** (failing Track A as core_alpha; failing non_equity as diversifier)
**Lineage**: `alt-archetype-intraday-reversal-2026-05-12`
**Authority**: PRD `docs/prd/20260512-alt_archetype_intraday_reversal_prd.md`; Phase 2 closeout `docs/memos/20260512-alt_a_phase_2_closeout.md`

---

## §1 TL;DR — 人话版

**alt-A 跑完了 8 年（2018-2025）真实回测**：
- **核心 alpha 角色 (core_alpha)**：**❌ Track A 17 关 通过 14/17 但 3 个失败** —— 在 4 个牛市年（2019/21/23/25）大幅跑输 SPY。这个策略是"防御型零上行"profile。
- **diversifier 角色**：anti-sibling NAV 相关性 **✅ 大幅通过**（vs RCMv1 0.146 / vs Cand-2 0.183 / vs Trial 9 v2 0.162，全部远低于阈值 0.85）—— **PQS 历史上第一个真正不 sibling 的候选**。**但是** non_equity 占比 = 0（53-股全是股票，PRD §11 Q1 锁了）→ 不满足 diversifier role 的 cross-asset 要求。

**Verdict**: alt-A 在当前形式 **既不能当 core_alpha 也不能当 diversifier**。
**但是** intraday reversal 这个 alpha 来源是**真实存在的**（vs SPY 在 2018 BEAR 年 +3.2%；max DD 仅 -18% vs SPY -34%）。问题是太微弱不能 standalone。

---

## §2 完整 Track A 17 关 verdict

```
Overall passed: FALSE
Total gates: 17
Passed: 14/17

✓ role_core_eligibility
✓ validation_year_2018_maxdd          (-10.69%)
✓ validation_year_2019_maxdd          (-6.67%)
✓ validation_year_2021_maxdd          (-9.70%)
✓ validation_year_2023_maxdd          (-12.74%)
✓ validation_year_2025_maxdd          (-10.64%)
✗ validation_aggregate_excess_vs_spy   ← FAIL
✗ validation_aggregate_excess_vs_qqq   ← FAIL
✓ stress_slice_covid_flash_maxdd      (-10.04%)
✓ stress_slice_rate_hike_2022_maxdd   (-4.70%)
✗ role_core__validation__2025__excess_vs_qqq  ← FAIL
✓ role_core__validation__2025__maxdd  (-10.64%)
✓ concentration_top1
✓ concentration_top3
✓ concentration_no_leveraged_etf
✓ beta_to_qqq                          (0.07)
✓ cost_robustness_2x
```

---

## §3 Per-year alpha pattern

| Year | Regime | alt-A | SPY | vs SPY | Reading |
|---|---|---|---|---|---|
| 2018 | BEAR | +3.17% vs SPY | -4.4% (annual) | **+3.17%** | **alt-A 防御作用真实！** |
| 2019 | BULL | -29.07% vs SPY | +28.9% | -29.07% | 严重跑输（仓位太稀） |
| 2021 | BULL | -32.59% vs SPY | +26.9% | -32.59% | 同上 |
| 2023 | BULL | -13.13% vs SPY | +24.2% | -13.13% | 同上 |
| 2025 | BULL/recovery | -20.23% vs SPY | ~+24% | -20.23% | 同上 |
| 8-yr total | mixed | +25.3% | +155.8% | **-130.5%** | standalone 不够 |

**模式**: alt-A 在 1 个 BEAR 年（2018）真正展现防御能力（+3.2% vs SPY），但 4 个 BULL 年大幅跑输。原因：

- 策略只在 **316/2011 天（16%）** 有持仓 → **84% 时间持现金** → 牛市中现金拖累极严重
- 设置 quantile=0.05 (前 5%) + intraday confirmation predicate 极严格 → 触发太少

---

## §4 Anti-sibling NAV correlation — STRONG PASS

| Anchor | Raw Pearson | Residual vs SPY | n overlap | Verdict |
|---|---|---|---|---|
| RCMv1 | **0.146** | 0.142 | 1145 | ✅ PASS (5.8× margin under 0.85) |
| Cand-2 | **0.183** | 0.175 | 1145 | ✅ PASS (4.6× margin) |
| Trial 9 v2 | **0.162** | 0.154 | 1145 | ✅ PASS (5.2× margin) |
| **3-way overall** | — | — | — | **PASS** |

**Historic context**: PQS cycle04-08 + Trial 3 all had raw NAV Pearson 0.85-0.95 vs at least 2 of 3 anchors (sibling-by-construction). alt-A is the **FIRST** candidate ever to come in at 0.14-0.18 raw.

**结构验证**: PRD §1 假设 "intraday-driven alpha 在时间尺度上结构性不同于 daily monthly cap_aware top-N"。**这个假设由数据 confirmed**。

---

## §5 Diversifier role 检查 (per CLAUDE.md)

CLAUDE.md `Diversifier Role Additional Constraints`:

| 要求 | 检查 | 状态 |
|---|---|---|
| raw NAV corr < 0.70 vs all anchors | max 0.183 | ✅ PASS |
| residual NAV corr < 0.50 | max 0.175 | ✅ PASS |
| factor_overlap_with_active_core = 0 | alt-A uses weekly_reversal_signal_5d, not in RCMv1/Cand-2 | ✅ PASS |
| **non_equity_weight_avg ≥ 15%** | alt-A 53-股 全 equity = 0% | **❌ FAIL** |
| per_validation_year MaxDD ≤ 20% | max -12.74% | ✅ PASS |

→ **diversifier role: FAIL on non_equity requirement only**

---

## §6 战略 verdict & recommendation

按 [[feedback_quant_operator_role.md]] 资深 quant 视角不当 yes-man：

### 6.1 Phase 3 结论
- **alt-A core_alpha**: REJECTED — vs_spy aggregate fail，4/5 BULL 年大幅跑输
- **alt-A diversifier**: REJECTED — 非 cross-asset universe

### 6.2 但 alt-A 有真实价值
- **First-ever 真正 anti-sibling 候选**（0.14-0.18 raw vs 0.85-0.95 历史）
- **2018 BEAR 年 +3.2% vs SPY** — defensive 能力 real
- **8 年 +25% / -18% max DD** — 风险调整后 reasonable (Sharpe ≈ 0.15 还是低)
- **Intraday reversal 作为 alpha 来源 confirmed exists**

### 6.3 三条 path forward（user directional 决定）

#### Path 1: alt-A v2 with cross-asset universe (推荐短期)
- PRD §11 Q1 LOCKED 53-股 → 新 lineage alt-A-v2 with universe expansion
- 加 bonds (TLT/IEF) + commodities (GLD) 作为 cash-carry buffer
- 这是 diversifier role 通过 non_equity ≥ 15% 的唯一路径
- 工程量：~1 周（universe.yaml 扩 + bridge 适配 cross-asset + 重跑 Phase 3）
- **风险**：可能仍然 vs_spy 跑输（cross-asset 不能解决 BULL underperformance）

#### Path 2: alt-A v3 with cardinality 放宽 (alpha 增强)
- 当前 setup_quantile=0.05 (前 5%) → 改 0.20 (前 20%) → 更多触发
- holding_period=5d → 10d → 更长 hold 减少 cash drag
- 但破 PRD §11 Q2 LOCKED 5d cap → 需要 user explicit-go 改 lock
- 工程量：~1 天
- **风险**：alpha 可能稀释（quantile 太松找到的反转不真）

#### Path 3: 接受 alt-A "evidence only"，不 forward (推荐长期)
- 不 forward init
- 把 alt-A 当成 "intraday reversal 是真实 alpha 来源" 的 evidence
- 等 cycle #09 / Trial 9 v2 verdict + 其他 alt PRD (event-driven, cross-asset) 探索
- 工程量：0
- **战略意义**：节省工程时间到更高 ROI 方向

### 6.4 资深 quant 推荐
**短期: Path 3 (接受 evidence only)**
- alt-A 已经证明 PQS 因子库 + 数据基础设施 + bridge 工程链都能 work
- Strong anti-sibling 是历史性突破，但单独不构成可投资策略
- 工程 ROI 角度：投 1 周修 v2 / v3 的 50% 概率成功 vs 投 1 周修其他方向更有效

**中期: 等 cycle #09 重 fire (Option A 之后) + Trial 9 v2 TD60 (~2026-08-06)**
- 如果 cycle #09 / Trial 9 出 nominee → fleet 有了 core_alpha
- 此时 **alt-A 的 anti-sibling 价值才能体现** —— 在 fleet 中加 alt-A v2 (with cross-asset) 作为 diversifier
- 现在单独 forward init alt-A 是 dead-end investment

---

## §7 Phase 3 工程评估

| Step | 状态 | 时间 | Commit |
|---|---|---|---|
| A: 53-股 universe + 60m regen + daily restore | ✅ done | ~10 min eng | `be82f77` |
| B: 8-year backtest (real 60m data) | ✅ done | ~10 min compute | (data files) |
| C: Track A 17-gate eval | ✅ done | ~1 min compute | (after fix) |
| D: Anti-sibling correlation reconstruct | ✅ done | ~5 min compute | |
| E: Closeout memo (this file) | ✅ done | ~30 min eng | (this commit) |

**Phase 3 总耗时**: ~1 小时（vs 估的 3-4 小时）— Phase 2 基础设施已就位，Phase 3 mostly compute + verdict + interpretation.

---

## §8 R3 audit lessons learned

按 [[feedback_audit_per_round_methodology.md]] Phase 3 抓到的 bugs (R3 实际跑):

1. **Step B: 60m left-labeled bug** — universe-wide; regen 53 股 60m → daily blast radius → snapshot+restore
2. **Step C: stress_slice date type mismatch** — `datetime.date` vs `datetime64[ns]` 比较 → 用 `pd.Timestamp()` 转换
3. **Step D: hl_range 因子需要 high/low panel** — factor_generator 默认不算需要 high/low → 加 high/low 参数

每个都是 R3 实际跑才暴露，R1/R2 静态读看不见。

---

## §9 Pending user decisions

1. **同意 Phase 3 verdict = alt-A 在当前形式不 forward init?**
2. **战略 path 选哪个**: Path 1 (v2 cross-asset) / Path 2 (v3 relaxed) / Path 3 (evidence only)?
3. **cycle #09 用 Option A 重 fire 时机** — 现在 / 等 Trial 9 v2 TD60 / 不做?

不 directional 决定:
- 明天 EOD daily ritual 自动跑 Trial 9 v2 TD001 first observe + options paper + VRP scan

---

## §10 forensic data 一览

| File | 内容 |
|---|---|
| `data/audit/alt_a_phase3_nav.parquet` | 2011-bar alt-A NAV + cash curve |
| `data/audit/alt_a_phase3_summary.json` | Step B 摘要（+25.3% vs SPY +155.8%）|
| `data/audit/alt_a_phase3_track_a_verdict.json` | Step C 17-gate full verdict |
| `data/audit/alt_a_phase3_anti_sibling.json` | Step D 3-way correlation |
| `data/audit/alt_a_phase3_coverage_pre_aggregate.csv` | Step A 60m coverage report |
| `data/audit/alt_a_phase3_daily_diff.csv` | Step A daily bar regen diff |
| `data/audit/alt_a_phase3_backtest.log` | Step B 完整 log |

Phase 1 + Phase 2 + Phase 3 工程链全部 committed 到 main branch。

---

*End of Phase 3 closeout. Awaiting user directional decision on Path 1/2/3.*
