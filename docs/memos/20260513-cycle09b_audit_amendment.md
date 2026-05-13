# cycle09b Closeout Amendment — §5.1 / §5.2 / §5.4 audit verdicts

**Date**: 2026-05-13
**Status**: §5.2 PASS · §5.1 mixed (yaml-strict eligible / cycle07a-locked RED) · §5.4 hypothesis overturned · §5.3 in progress (seed=123 ~37% complete)
**Parent**: `docs/memos/20260512-cycle09b_closeout.md` §5 (forward-init pre-conditions)
**Author**: PQS resident-quant operator
**Authority**: tactical operator scope per CLAUDE.md "Autonomous Decision Authority"

---

## §1 TL;DR — 人话版

cycle09b Trial 1 forward-init 4 道 audit 跑了 3 道，结论混合：

- **§5.2 PIT audit on `rd_intensity_ttm`: PASS** ✅ —— EDGAR companyfacts 用 `filed_date` 而不是 `fiscal_period_end` 做 PIT (point-in-time = 知道某天能用的数据)；AAPL Q4 FY2024 10-K filing anchor case + 5 个 random sample 全部正确。
- **§5.1 5-anchor extended NAV correlation: 混合**
  - yaml-only (raw-only threshold) 判断: Trial 1 = `warn_label_void`（max raw 0.810 < 0.85 阈值），core_alpha eligible 条件成立
  - cycle07a-locked (raw + residual) 判断: Trial 1 = **RED**（max residual_vs_spy 0.809 ≥ 0.50 在 4/5 anchors）
- **§5.4 NAV vs QQQ deep-dive: 闭包 memo 假设被推翻**
  - 闭包假设: rd_intensity_ttm 选 tech-heavy 大盘股 → 0.851 QQQ overlap
  - 实际: Trial 1 是 **29.2% non-equity defensive overlay**（bonds 14.5% + commodities 5.8% + cash 8.9%）+ 选择性 tech 持仓（28.8% QQQ-sector），不是 tech-heavy 选股
- **§5.3 seed=123 复现 mining: 后台执行中** (73/93 archived ≈ 37% of 200-trial budget)，预计 ~30min 完成；本备忘录后续追加

**Operator 战略判断**（tactical scope，未涉及 directional decision）：
Trial 1 forward-init 决策**应在 §5.3 完成后再定**。当前 §5.1+§5.4 信息表明，Trial 1 在 yaml-only 是 eligible，但在更严格 residual gate 下 RED；同时 §5.4 揭示真正结构是 defensive overlay sibling 而非 tech-heavy sibling —— 这影响后续 cycle10+ 设计 axis（防御构造 DOF 还是真正 cross-asset selector）。

---

## §2 §5.2 PIT audit — DETAIL

### §2.1 Audit design

R3 actually-run-code: 实测 `core/data/fundamentals_store.py::load_ttm` 在 daily PIT panel 上的行为，验证 EDGAR companyfacts 经 forward-fill 后的有效日期是 `filed` 而不是 `end`。

### §2.2 AAPL Q4 FY2024 anchor

- pre-10-K (2024-10-31): `rd_intensity_ttm.loc["2024-10-31", "AAPL"]` = **0.0780**
- post-10-K (2024-11-15): `rd_intensity_ttm.loc["2024-11-15", "AAPL"]` = **0.0666**
- AAPL FY2024 10-K filed_date: **2024-11-01**（介于 pre/post 之间）
- 数值确实因 filed_date 切换而变化（0.0780 → 0.0666）—— **PIT 语义生效** ✅

### §2.3 5 个 random audit points

| asof | ticker | pit_filed_date | pit_period_end | form | pit_filed ≤ asof | naive_end_would_leak | leak_gap_days |
|---|---|---|---|---|---|---|---|
| 2023-01-06 | META | 2022-10-27 | 2021-09-30 | 10-Q | True ✓ | True | 755 |
| 2018-03-13 | COP | 2018-02-20 | 2015-12-31 | 10-K | True ✓ | True | 979 |
| 2019-10-02 | NVDA | 2019-08-15 | 2018-07-29 | 10-Q | True ✓ | True | 513 |
| 2023-04-24 | COP | 2023-02-16 | 2020-12-31 | 10-K | True ✓ | True | 666 |
| 2022-04-12 | GOOGL | 2022-02-02 | 2019-12-31 | 10-K | True ✓ | True | 659 |

5/5 PIT 正确（filed_date ≤ asof）。5/5 confirm if 用 end_date 语义会泄露（即同 ticker 在 ≤ asof 时段内有 end_date but filed > asof 的 fact）。

### §2.4 R4 boundary note

`pit_period_end` 列显示的是某个 filing 报告的最旧 historical period（一个 10-K 里可能包含 multi-year comparative statements），不是 filing 自身对应的 fiscal period。例如 COP 2018-02-20 filed 的 10-K 是 FY2017 annual，但 `groupby("filed").last()` 取 sort 后最末 row 的 `end` —— 这恰好是 2015-12-31（一份 10-K 报告里 COP 的 rd_expense 跨多年 comparative 数据）。这是 EDGAR 输出的怪癖，不影响 PIT 正确性。

### §2.5 Verdict

§5.2 PIT audit **PASS**。`rd_intensity_ttm` 在 cycle09b panel 上是 PIT-clean。

**Forensic artifact**: `data/audit/cycle09b_pit_audit_rd_intensity.json`
**Script**: `dev/scripts/cycle09/cycle09b_pit_audit_rd_intensity.py`

---

## §3 §5.1 5-anchor NAV correlation — DETAIL

### §3.1 Test design

cycle09b Trial 1 (`5a99868072e6` = `rs_vs_spy_63d + cpi_yoy_pct + rd_intensity_ttm`, equal-weight, cap_aware_cross_asset, monthly, top10) 在 cycle09b selector partition (train + validation, ~16y, 4876 daily bars × 79 syms) 上重算 NAV；对每个 anchor 用其 **frozen construction** 重算 NAV，再做 pairwise pearson correlation (raw + residual vs SPY + residual vs QQQ)。

### §3.2 Results table

| Pair | raw | residual_vs_spy | residual_vs_qqq | yaml raw-only tier |
|---|---|---|---|---|
| Trial 1 vs RCMv1 | **0.810** | **0.809** | 0.410 | warn_label_void |
| Trial 1 vs Cand-2 | 0.781 | 0.778 | 0.284 | warn_label_void |
| Trial 1 vs Trial 9 v2 | 0.744 | 0.742 | 0.235 | warn_label_void |
| Trial 1 vs cycle07a Trial 3 | 0.788 | 0.788 | 0.384 | warn_label_void |
| Trial 1 vs cycle08 top-1 | 0.020 | 0.019 | 0.028 | true_diversifier |

n_overlap = 1583 daily bars per pair.

### §3.3 Yaml-strict (raw-only) verdict

Closeout memo §5.1 thresholds:
- raw < 0.50 → true_diversifier
- 0.50 - 0.70 → partial_diversifier
- 0.70 - 0.85 → warn_label_void
- ≥ 0.85 → reject_step5

Trial 1 max raw across 5 anchors = **0.810 < 0.85** → NOT reject_step5。Closeout §6 directive: "If extended NAV < 0.85 raw with at least 1 of (RCMv1, Cand-2, Trial9_v2) → core_alpha eligible" → all 3 satisfy → **`core_alpha eligible`** per yaml-strict reading.

### §3.4 cycle07a-locked (raw + residual) verdict

PQS 2026-05-07 x.txt locked thresholds（Trial 3 forward-init gate 时引入）:
- GREEN: all raw < 0.80 AND all residuals < 0.45
- YELLOW: 0.80 ≤ max raw < 0.85 AND max residual < 0.50
- **RED: any raw ≥ 0.85 OR any residual ≥ 0.50**

Trial 1: max raw 0.810 (between YELLOW threshold)，max residual_vs_spy 0.809 ≥ 0.50 → **RED**.

### §3.5 Critical structural finding

residual_vs_spy ≈ raw (0.81 → 0.81，差 ≤ 0.003) 在 4 个 defensive anchors 上 = **共享相关性几乎不被 SPY beta 解释**。residual_vs_qqq 下降到 0.24-0.41 = QQQ beta 解释了约 ~50% 的 raw 相关。

读取: 4 个 defensive anchors（RCMv1 / Cand-2 / Trial 9 / cycle07a Trial 3）作为一个 "defensive equity drift" 共享因子，Trial 1 加入这个簇；剥离 SPY 不破坏簇内相关，剥离 QQQ 部分破坏。

### §3.6 The two-verdict tension

PQS 历史上 cycle04+05 用 yaml-only (raw) 阈值；cycle07a 引入 cycle07a-locked (raw + residual)；cycle08+09b yaml 没明确选定哪套。这是 process gap。

**Operator strategic implication**: 两个判断都不无道理。yaml-strict 是 cycle04-05 时代的标准；cycle07a-locked 是 Trial 3 (close 时 cycle07a) 时 PQS 升级讨论后的产物。cycle09b yaml 既没 reference 又没 deprecate 后者，所以两套都 applicable。

Operator 推荐: forward-init 决策应 **conservative** —— Trial 1 现在不 forward-init as core_alpha，等 §5.3 完成后再做 final 决策。理由:
1. 0.810 raw + 0.809 residual_vs_spy 在 YELLOW-RED 边界
2. cycle04-09 sibling-by-defensive-construction 是 PQS empirically known root cause
3. cycle10 mining 设计应避开 sibling root cause（construction DOF expansion，不是 factor DOF）

**Forensic artifact**: `data/audit/cycle09b_trial1_extended_nav_correlation.json`
**Script**: `dev/scripts/cycle09/cycle09b_trial1_extended_nav_correlation.py`

---

## §4 §5.4 QQQ deep-dive — HYPOTHESIS OVERTURN

### §4.1 Closeout hypothesis

> "raw_pearson_vs_qqq = 0.851 high — explained by `rd_intensity_ttm` selecting tech-heavy names (NVDA / AAPL / MSFT / GOOGL / AMD) which are QQQ-weighted."

### §4.2 Empirical findings

cycle09b Trial 1 在 selector panel 上 daily weights 复算，n_held_dates = 4389 / 4876（90% 持仓覆盖率）。

**Asset-class avg weight (held dates only)**:

| Asset class | mean weight | max weight |
|---|---|---|
| equities | 41.0% | 90.6% |
| bonds | 14.5% | 33.2% |
| commodities | 5.8% | 12.2% |
| cash_anchor | 8.9% | 21.6% |
| **non-equity total** | **29.2%** | — |

29.2% non-equity 显著超过 CLAUDE.md diversifier role 的 15% 门槛。

**Top-10 holdings by weight-day product**:

| Rank | Symbol | Sector | frac_held_dates | avg_weight |
|---|---|---|---|---|
| 1 | GLD | etf (gold) | 73.1% | 7.95% |
| 2 | IEF | etf (treasury 7-10y) | 66.3% | 8.38% |
| 3 | SHV | etf (treasury 1-3mo) | 79.0% | 6.64% |
| 4 | TLT | etf (treasury 20+y) | 55.3% | 9.17% |
| 5 | LLY | health_care | 44.9% | 8.78% |
| 6 | SHY | etf (treasury 1-3y) | 48.1% | 8.04% |
| 7 | BIL | etf (1-3mo cash) | 66.9% | 5.51% |
| 8 | AVGO | technology (semis) | 51.1% | 7.01% |
| 9 | KLAC | technology (semi-equip) | 37.2% | 9.45% |
| 10 | NVDA | technology (semis) | 36.7% | 9.54% |

前 7 大 = 6 个 bond/cash ETF + GLD（gold ETF）+ LLY（pharma）= **defensive overlay 主体**。前 10 中只有 3 个 tech（AVGO/KLAC/NVDA）排 8/9/10 位。

**Sector breakdown (held dates only)**:

| Sector | avg weight |
|---|---|
| technology | 19.6% |
| health_care | 8.6% |
| communication | 5.9% |
| etf (bonds/commodities) | 5.8% (consolidated) |
| consumer_discretionary | 3.3% |
| financials | 1.4% |
| energy | 0.9% |
| consumer_staples | 0.7% |
| industrials | 0.4% |
| (cluster_map etf-by-asset-class above counts separately) | — |

**QQQ-sector overlap** (tech + communication + consumer_discretionary):

平均权重 = **28.8%** 在 QQQ-style 行业。

### §4.3 Reading

Closeout 假设 "tech-heavy 选股 → QQQ 重合" **错**。实际:

- Trial 1 是 **defensive overlay + 选择性 tech 加成**
- 真正 QQQ 0.851 相关性来源 = (a) 28.8% 的 QQQ-sector tech 持仓 + (b) bonds/cash safe-haven 在 tech 涨跌时反向作为 hedge → 整体相关性向 defensive 偏移

`rd_intensity_ttm` 选 high-RD-intensity 股票，确实倾向 tech (NVDA/AVGO/KLAC RD/Sales 高)，但 cap_aware_cross_asset 约束 + cluster_cap 0.20 强制 portfolio 不能全压 tech；剩余预算被 bonds + commodities 吸收。

### §4.4 Implication for forward-init

Trial 1 实际上**符合 diversifier role 的 non-equity utilization 要求** (29.2% >> 15%)。

但 diversifier role 还需要 `anti_sibling_nav_corr_raw < 0.70`（CLAUDE.md "Diversifier-specific STRICTER rules"），Trial 1 max raw 0.810 → **不满足 diversifier role NAV 标准**.

冲突结果：
- Cross-asset utilization ✓ (29.2%)
- Factor overlap = 0 vs 5 anchors ✓
- 2025 MaxDD -18.26% (edge for diversifier 18% soft-warn) ⚠
- **Anti-sibling NAV raw < 0.70 ✗ (max 0.810)**

→ Trial 1 cannot claim diversifier role under current rules.

只能 candidate as `core_alpha` 或 `legacy_decay_verification`。yaml-strict 说 core_alpha eligible；cycle07a-strict 说 reject。两边都对一半。

**Forensic artifact**: `data/audit/cycle09b_trial1_qqq_deepdive.json`
**Script**: `dev/scripts/cycle09/cycle09b_qqq_deepdive.py`

---

## §5 §5.3 seed=123 replication — STATUS

### §5.1 Setup

Same yaml sha256 (`b0b9e181…`), same Optuna TPE sampler, same full 200-trial budget；唯一改 SEED=42 → SEED=123；lineage `track-c-cycle-2026-05-12-09b-seed123` 不污染原 archive。

### §5.2 Status (2026-05-13 09:06 ET)

~37% complete (73/93 archived of 200 budgeted). 仍在跑，预计 ~30 min 完成。本 amendment 完成后追加 results 节。

**Forensic artifact**: `data/audit/cycle09b_seed123_mining.log` (in progress)
**Script**: `dev/scripts/cycle09/run_cycle09b_seed123_replication.py`

### §5.3 Pre-committed verdict criteria (per closeout §5.3)

- NAV trajectory 偏离 ≤ 1pp → robust
- > 1pp → unstable

如果 seed=123 top-1 trial 的 spec ≈ seed=42 top-1（rs_vs_spy_63d + cpi_yoy_pct + rd_intensity_ttm 或 same family），则 mining 稳定。如果 top-1 spec 完全不同，则 mining 不稳定 → cycle09b 整体结论存在 sampler-dependence 风险，forward-init 直接 reject。

---

## §6 Pre-final forward-init verdict (subject to §5.3)

| Audit gate | Verdict | Source |
|---|---|---|
| §5.2 PIT | PASS ✅ | data/audit/cycle09b_pit_audit_rd_intensity.json |
| §5.1 yaml-only | core_alpha eligible (warn_label_void) | data/audit/cycle09b_trial1_extended_nav_correlation.json |
| §5.1 cycle07a-locked | RED (residual_vs_spy ≥ 0.50) | same |
| §5.4 QQQ deep-dive | hypothesis overturn; cross-asset cand actually | data/audit/cycle09b_trial1_qqq_deepdive.json |
| §5.3 seed=123 | IN PROGRESS | data/audit/cycle09b_seed123_mining.log |

**Operator strategic recommendation (NOT pre-locked, awaits §5.3 + user input)**:

1. **§5.3 robust + yaml-strict policy adopted**: forward-init Trial 1 as `core_alpha` + 严密 monitoring; document residual_vs_spy 风险 as known caveat; first 30 TDs 内任何 anchor 相关性飘升 → halt
2. **§5.3 robust + cycle07a-strict policy adopted**: do not forward-init; classify as `legacy_decay_verification`; pivot to cycle10 designed for break-from-defensive-overlay
3. **§5.3 unstable**: reject directly, no forward-init regardless of policy choice
4. **Hybrid (operator preferred)**: defer 决策 until §5.3 verdict in; if stable, then **defer 1 trading week** while we draft cycle10 mining yaml with single-axis diff = ban GLD/IEF/SHV/TLT/SHY/BIL holdings (force NON-bond non-equity); compare cycle10 candidate vs Trial 1 NAV correlation; the lower-correlated of the two is forward-inited

The hybrid option is operator-favoured because it tests the **construction-driven sibling root cause** hypothesis empirically before committing to forward-init.

---

## §7 Process audit (4-tier per CLAUDE.md)

**R1 factual**: §5.2 audit JSON + §5.1 audit JSON + §5.4 audit JSON all written; reproducible via the 3 scripts in `dev/scripts/cycle09/`. seed=123 mining 仍在跑，optuna db 验证 73/93 archived。

**R2 logical**: §5.4 QQQ deep-dive 翻转 closeout 假设的关键证据是 top-10 持仓中前 7 大是 bond/cash/gold ETF。Asset-class mean 累积只到 70.2% (vs 100%)，因为 cap_aware_cross_asset + 各类 cap 在某些日子绑定不 100% allocated → cash 余下 ~30% 未投资 → 与 closeout 假设 "tech-heavy" 完全相反。

**R3 actually-run-code**: 3 个 audit 脚本独立执行。§5.2 直接 query EDGAR cache + assert PIT semantics on AAPL real filing date。§5.1 + §5.4 都重新 build NAV from scratch（22-25s/NAV，5 anchors + 1 candidate = ~3min total per-script），不用 stale cached numbers。

**R4 boundary**:
- §5.1 cycle08 top-1 first run NAV=100000 stuck — root cause: 我误用 STOCK_RISK_CLUSTER_MAP 而 cycle08 yaml 明确 `construction.mode = cap_aware_cross_asset`。Fixed 后 cycle08 NAV = 117354.6（low signal candidate；raw vs Trial 1 = 0.020）。
- §5.1 verdict 两套阈值不一致 — process gap noted; cycle09b yaml 没明确 which 套；operator 选保守 = conservative interpretation （cycle07a-locked）。
- §5.4 mean asset_class 加和 0.702 ≠ 1.000 — cap_aware 不强制 100% allocation；保留 cash 余地合理。

---

## §8 Forensic artifacts inventory

```
# §5.2 PIT
data/audit/cycle09b_pit_audit_rd_intensity.json
dev/scripts/cycle09/cycle09b_pit_audit_rd_intensity.py

# §5.1 5-anchor NAV correlation
data/audit/cycle09b_trial1_extended_nav_correlation.json
dev/scripts/cycle09/cycle09b_trial1_extended_nav_correlation.py

# §5.4 QQQ deep-dive
data/audit/cycle09b_trial1_qqq_deepdive.json
dev/scripts/cycle09/cycle09b_qqq_deepdive.py

# §5.3 seed=123 replication (in progress)
data/audit/cycle09b_seed123_mining.log
dev/scripts/cycle09/run_cycle09b_seed123_replication.py
```

§5.3 完成后本 amendment 将追加 §9（seed=123 final results）+ §10（final forward-init verdict + 5 trading-day plan）。
