# cycle09b Closeout Amendment — §5.1 / §5.2 / §5.4 audit verdicts

**Date**: 2026-05-13 (REVISED post-self-audit 2026-05-13 per `docs/memos/20260513-cycle09b_audit_amendment_self_audit.md`)
**Status**: §5.2 PASS · §5.1 REJECT per yaml G3 orthogonality_gate · §5.4 hypothesis overturned · §5.3 in progress (seed=123 ≈ 75% complete, informational only)
**Parent**: `docs/memos/20260512-cycle09b_closeout.md` §5 (forward-init pre-conditions)
**Self-audit**: `docs/memos/20260513-cycle09b_audit_amendment_self_audit.md` (4 holes in original interpretation; this revision incorporates fixes)
**Author**: PQS resident-quant operator
**Authority**: tactical operator scope per CLAUDE.md "Autonomous Decision Authority"

---

## §1 TL;DR — 人话版（REVISED）

cycle09b Trial 1 forward-init audit 已经够下 verdict：**REJECT** per cycle09b yaml's OWN G3 orthogonality_gate（yaml-ratified，无需 invoke 外部 provisional standard）。

- **§5.2 PIT audit on `rd_intensity_ttm`: PASS** ✅ —— EDGAR companyfacts 用 `filed_date` 而不是 `fiscal_period_end` 做 PIT (point-in-time = 知道某天能用的数据)；AAPL Q4 FY2024 10-K filing anchor case + 5 个 random sample 全部正确。
- **§5.1 5-anchor extended NAV correlation: REJECT per yaml G3**
  - yaml G3 orthogonality_gate (line 262-271): raw < 0.70 AND residual < 0.50, required_top_k_under_threshold: 1
  - Trial 1 vs all 3 yaml-listed anchors (RCMv1 / Cand-2 / Trial9_v2): 0/3 anchors satisfy BOTH sub-gates
  - vs RCMv1: raw 0.810 / res_spy 0.809 → FAIL both
  - vs Cand-2: raw 0.781 / res_spy 0.778 → FAIL both
  - vs Trial9_v2: raw 0.744 / res_spy 0.742 → FAIL both
  - → **G3 FAIL → REJECT forward-init**
- **§5.4 NAV vs QQQ deep-dive: 闭包 memo 假设被推翻**
  - 闭包假设: rd_intensity_ttm 选 tech-heavy 大盘股 → 0.851 QQQ overlap
  - 实际: Trial 1 是 **29.2% non-equity defensive overlay**（bonds 14.5% + commodities 5.8% + cash 8.9%）+ 选择性 tech 持仓（28.8% QQQ-sector），不是 tech-heavy 选股
- **§5.3 seed=123 复现 mining: 后台执行中** (~75% complete)；降级为 informational only —— mining stability 信息，不左右已下定的 G3 REJECT verdict

**Operator 战略判断**（修订后）：
Trial 1 = **`legacy_decay_verification` only**（不进 fleet，不 forward init）。无 yaml-strict / cycle07a-locked tension —— cycle09b yaml's OWN G3 gate 给出唯一 ratified verdict。Strategic 下一步 deferred 到 ML Phase 1.5 (~1-2 day) OR Trial 9 v2 TD60 evidence (~2026-08-06)，由 whichever 先出 evidence 决定 cycle10 axis。

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

### §3.3 cycle09b yaml 的 3-gate NAV verdict（REVISED post-self-audit）

cycle09b yaml `data/research_candidates/track-c-cycle-2026-05-12-09b_promotion_criteria.yaml` 自己 ratified 了 **3 个** NAV-related gates。原 amendment 仅引用了其中 1 个（r41_informational raw-only tier）是 R1 fact-checking 漏洞 —— 见 self-audit memo §2。

**完整 yaml gates**:

| Gate | Yaml location | Trigger | Threshold |
|---|---|---|---|
| G_anti_sibling_nav | line 227-243 | Mining-time gate (cycle09b accepted Trial 1 because anchor_pearson 0.821 < 0.85 on 3-way pool) | raw < 0.85 pairwise |
| r41_informational | line 248-257 | Informational only (NOT blocking) | raw-only tier: <0.50/0.50-0.70/0.70-0.85/≥0.85 |
| **G3 orthogonality_gate** | line 262-271 | **Forward-readiness gate** | raw < 0.70 AND residual < 0.50, `required_top_k_under_threshold: 1` |

### §3.4 Per-gate verdict on Trial 1

| Gate | Verdict | Detail |
|---|---|---|
| G_anti_sibling_nav | **PASS** ✓ | All 5 pairwise raw < 0.85 (max 0.810 vs RCMv1) |
| r41_informational | warn_label_void | Trial 1 sits in 0.70-0.85 raw band per max raw 0.810; **informational only, not blocking** |
| **G3 orthogonality_gate** | **FAIL** ✗ | **0/3 yaml-anchored pairs clear BOTH raw<0.70 AND residual<0.50 simultaneously** |

**G3 sub-gate breakdown** (yaml's 3 blend_anchors: RCMv1 / Cand-2 / Trial9_v2):

| Pair | raw | res_spy | G3 raw < 0.70 | G3 res < 0.50 | G3 anchor pass? |
|---|---|---|---|---|---|
| vs RCMv1 | 0.810 | 0.809 | FAIL | FAIL | No |
| vs Cand-2 | 0.781 | 0.778 | FAIL | FAIL | No |
| vs Trial9_v2 | 0.744 | 0.742 | FAIL | FAIL | No |

`required_top_k_under_threshold: 1` = ≥ 1 of 3 anchors must clear both sub-gates. **0/3 satisfy**.

→ **G3 orthogonality_gate FAIL → cycle09b yaml's OWN forward-init verdict: REJECT**.

### §3.5 Critical structural finding (preserved from original)

residual_vs_spy ≈ raw (0.81 → 0.81，差 ≤ 0.003) 在 4 个 defensive anchors 上 = **共享相关性几乎不被 SPY beta 解释**。residual_vs_qqq 下降到 0.24-0.41 = QQQ beta 解释了约 ~50% 的 raw 相关。

读取: 4 个 defensive anchors（RCMv1 / Cand-2 / Trial 9 / cycle07a Trial 3）作为一个 "defensive equity drift" 共享因子，Trial 1 加入这个簇；剥离 SPY 不破坏簇内相关，剥离 QQQ 部分破坏。这跟 §5.4 deep-dive 揭示的 29.2% non-equity defensive overlay 是同一 structural finding 的不同角度。

### §3.6 (DEPRECATED) "Two-verdict tension"

**原 amendment §3.6 描述的 "yaml-only vs cycle07a-locked tension" 是 strawman**：cycle09b yaml 自己就有 G3 (residual gate)，不需要 invoke cycle07a-locked 外部 provisional standard。Self-audit hole #1 见 `20260513-cycle09b_audit_amendment_self_audit.md` §2.

cycle07a-locked thresholds 在 `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md` 自承"D.0 fleet allocator gate revision proposal (**provisional, NOT ratified**)" —— 仅 Trial 3 case-by-case ad-hoc tightening + 后续 fleet allocator proposal but not ratified. 不适用作 cycle09b binding standard.

cycle09b yaml 自己 ratified G3 是 sufficient — verdict 单一 clear：REJECT.

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

### §4.4 Implication for forward-init（REVISED）

Trial 1 实际上**符合 diversifier role 的 non-equity utilization 要求** (29.2% >> 15%)。

但 diversifier role 还需要 `anti_sibling_nav_corr_raw < 0.70`（CLAUDE.md "Diversifier-specific STRICTER rules"），Trial 1 max raw 0.810 → **不满足 diversifier role NAV 标准**.

冲突结果：
- Cross-asset utilization ✓ (29.2%)
- Factor overlap = 0 vs 5 anchors ✓
- 2025 MaxDD -18.26% (edge for diversifier 18% soft-warn) ⚠
- **Anti-sibling NAV raw < 0.70 ✗ (max 0.810)**

→ Trial 1 cannot claim diversifier role under current rules.

同时 yaml G3 (raw < 0.70 AND residual < 0.50) **also FAIL** → cannot claim core_alpha either (§3.4).

**Verdict**: Trial 1 classifies as `legacy_decay_verification` only — neither diversifier nor core_alpha eligible per cycle09b yaml's own ratified gates.

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

## §6 Final forward-init verdict (REVISED post-self-audit)

| Audit gate | Verdict | Source |
|---|---|---|
| §5.2 PIT | PASS ✅ | data/audit/cycle09b_pit_audit_rd_intensity.json |
| §5.1 G_anti_sibling (mining-time) | PASS ✓ | data/audit/cycle09b_trial1_extended_nav_correlation.json |
| §5.1 r41_informational tier | warn_label_void (informational, not blocking) | same |
| **§5.1 G3 orthogonality_gate (forward-readiness)** | **FAIL ✗** | same |
| §5.4 QQQ deep-dive | hypothesis overturn; defensive cross-asset overlay (not tech-heavy) | data/audit/cycle09b_trial1_qqq_deepdive.json |
| §5.3 seed=123 stability | IN PROGRESS (informational only, ~75% complete) | data/audit/cycle09b_seed123_mining.log |

### §6.1 Verdict

**REJECT forward-init per cycle09b yaml's OWN G3 orthogonality_gate**.

cycle09b yaml ratified G3 (raw < 0.70 AND residual < 0.50, required_top_k_under_threshold: 1) is sufficient — no need to invoke cycle07a-provisional thresholds (self-audit hole #2). 0/3 yaml-anchored pairs satisfy G3.

### §6.2 Classification

Trial 1 → **`legacy_decay_verification`** in candidate_registry. Not forward init; not entering fleet.

### §6.3 §5.3 seed=123 role (REVISED)

§5.3 seed=123 stability test = **informational only**:
- Regardless of seed=123 outcome (top-1 reproducible vs not), forward-init verdict above does NOT change
- Stability finding logged for future cycle10 design reference (e.g. "cycle09b mining is/is-not seed-stable on Optuna TPE")
- §5.3 results will append as §9 when complete

### §6.4 Strategic next-step (REVISED)

Per self-audit memo §6.3:

1. **Trial 1 closes as `legacy_decay_verification`** in candidate_registry (this verdict)
2. **Trial 9 v2 forward observation continues** (independent workstream; TD60 verdict ~2026-08-06)
3. **ML Phase 1.5 hyperparameter sweep proceeds in parallel** (user authorized 2026-05-13; closeout `docs/memos/20260513-ml_phase_1_5_design.md`)
4. **cycle10 design DEFERRED** until either (a) Trial 9 v2 TD60 verdict OR (b) ML Phase 1.5 results land first; pick cycle10 axis informed by that evidence
5. **cycle10 axis candidates** (revised; old (b)/(c)/(d) deprecated per self-audit §4-5):
   - (i) factor-pool refinement (mining-time G3-aware objective; minimize NAV residual_vs_spy as part of composite score)
   - (ii) construction-mode 新维度 (risk-parity or equal-vol weight scheme — distinct from cap_aware_cross_asset)
   - (iii) universe expansion (78 → 200+ stocks; data + screening pipeline; non-trivial eng)

---

## §7 Process audit (4-tier per CLAUDE.md)

**R1 factual**: §5.2 audit JSON + §5.1 audit JSON + §5.4 audit JSON all written; reproducible via the 3 scripts in `dev/scripts/cycle09/`. seed=123 mining 仍在跑，optuna db 验证 73/93 archived。

**R2 logical**: §5.4 QQQ deep-dive 翻转 closeout 假设的关键证据是 top-10 持仓中前 7 大是 bond/cash/gold ETF。Asset-class mean 累积只到 70.2% (vs 100%)，因为 cap_aware_cross_asset + 各类 cap 在某些日子绑定不 100% allocated → cash 余下 ~30% 未投资 → 与 closeout 假设 "tech-heavy" 完全相反。

**R3 actually-run-code**: 3 个 audit 脚本独立执行。§5.2 直接 query EDGAR cache + assert PIT semantics on AAPL real filing date。§5.1 + §5.4 都重新 build NAV from scratch（22-25s/NAV，5 anchors + 1 candidate = ~3min total per-script），不用 stale cached numbers。

**R4 boundary**:
- §5.1 cycle08 top-1 first run NAV=100000 stuck — root cause: 我误用 STOCK_RISK_CLUSTER_MAP 而 cycle08 yaml 明确 `construction.mode = cap_aware_cross_asset`。Fixed 后 cycle08 NAV = 117354.6（low signal candidate；raw vs Trial 1 = 0.020）。
- §5.1 "verdict 两套阈值不一致" 是 R1 fact-checking 漏洞 — cycle09b yaml 自己有 G3 orthogonality_gate (raw<0.70 AND residual<0.50), 不需要 invoke cycle07a-provisional。Self-audit hole #1 见 `20260513-cycle09b_audit_amendment_self_audit.md` §2。修订后单一 yaml-G3 verdict = REJECT.
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

§5.3 完成后本 amendment 将追加 §9（seed=123 final results, informational only — does not change G3 REJECT verdict above）。

---

## §9 §5.3 seed=123 replication final results (appended 2026-05-13)

### §9.1 Mining outcome

Mining log: `data/audit/cycle09b_seed123_mining.log`

| Metric | seed=42 (cycle09b canonical) | seed=123 (this audit) |
|---|---|---|
| n_trials | 200 | 200 |
| n_finite | 159 | 161 |
| n_archived | 108 | (108 reported in log fragment) |
| wall_clock | 48.4 min | 52.2 min |
| Top-1 spec | `rs_vs_spy_63d + cpi_yoy_pct + rd_intensity_ttm` | `mom_126d + coskew_60d_spy + atr_compression_20d` |
| Top-1 IC_IR | +0.773 | +0.612 |
| Top-1 objective | +1.122 | +1.151 |
| Top-1 families | A / P / N | A / I / I |
| **Factor overlap** | — | **0/3 shared with seed=42** |

### §9.2 Within-cycle stability (seed=42 top-1 NAV vs seed=123 top-1 NAV)

| Metric | Value | Reading |
|---|---|---|
| raw_pearson | **0.761** | High raw NAV correlation despite 0% factor overlap |
| residual_pearson_vs_spy | 0.759 | Almost equal to raw → minimal SPY beta share |
| residual_pearson_vs_qqq | 0.388 | QQQ beta explains ~50% of correlation |
| n_overlap_days | 1583 | — |

### §9.3 G3 orthogonality_gate check on seed=123 top-1

vs 3 yaml-listed blend_anchors (RCMv1 / Cand-2 / Trial9_v2):

| Pair | raw | res_spy | res_qqq | G3 raw<0.70 | G3 res<0.50 | Pass both? |
|---|---|---|---|---|---|---|
| vs RCMv1 | **0.868** | 0.868 | 0.691 | FAIL | FAIL | No (also: raw ≥ 0.85 = reject_step5) |
| vs Cand-2 | 0.811 | 0.811 | 0.542 | FAIL | FAIL | No |
| vs Trial9 v2 | 0.654 | 0.652 | 0.184 | PASS | FAIL (res_spy 0.65) | No |

**0/3 anchors clear both G3 sub-gates** → seed=123 top-1 **also FAILS G3**.

### §9.4 Strategic finding — Construction-driven sibling root cause CONFIRMED

This is the deepest empirical confirmation of the cycle04-09b sibling-by-construction phenomenon:

1. **Factor-level instability**: seed=42 and seed=123 winners use **completely disjoint factor sets** (rs_vs_spy_63d/cpi_yoy_pct/rd_intensity_ttm vs mom_126d/coskew_60d_spy/atr_compression_20d). Mining has multiple local optima.
2. **NAV-level structural stability**: despite 0% factor overlap, both top-1 NAVs have **raw 0.761 pairwise correlation** → produce sibling NAV trajectories
3. **G3 fails regardless of seed**: Both seeds' winners fail cycle09b yaml's own G3 orthogonality_gate against the 3 yaml-anchored references → REJECT is construction-driven, not factor-driven

### §9.5 Implication for cycle10 design

- cycle10 axis (i) "factor-pool refinement with mining-time G3-aware residual minimization" is **necessary but likely insufficient** —— factor swap doesn't break NAV sibling correlation (proven empirically here)
- cycle10 axis (ii) "construction-mode 新维度 (risk-parity, equal-vol weight, etc.)" is **likely the binding axis** —— sibling root cause is cap_aware_cross_asset + monthly + top10 + 79-sym universe
- cycle10 axis (iii) "universe expansion" is **also viable** —— expanding 79 → 200+ stocks may break the universe-binding correlation floor

This trio of evidence (seed-instability at factor level + NAV stability + G3 fail regardless of seed) provides the strongest empirical case yet for **construction-DOF expansion over factor-DOF expansion** in cycle10.

### §9.6 G3 REJECT verdict on Trial 1 CONFIRMED

§9 evidence does NOT change §6 G3 REJECT verdict. In fact, §9.4 strengthens the verdict: even running the same yaml + same construction + different seed produces another equally-rejectable candidate. Trial 1 = **`legacy_decay_verification`** stands.

### §9.7 Forensic artifacts (§9)

- Mining log: `data/audit/cycle09b_seed123_mining.log`
- Stability + G3 analysis: `data/audit/cycle09b_seed_stability_analysis.json`
- Analysis script: `dev/scripts/cycle09/cycle09b_seed_stability_analysis.py`
- Mining script: `dev/scripts/cycle09/run_cycle09b_seed123_replication.py`
- Optuna study: `data/mining/rcm_optuna.db::cycle09b-2026-05-12-seed123` (200 trials)
- Archive lineage: `track-c-cycle-2026-05-12-09b-seed123` (108 trials archived in `data/mining/rcm_archive.db`)

### §9.8 Self-audit (§9 4-tier per CLAUDE.md)

**R1**: top-1 specs read directly from mining log (line "#1 obj=+1.151 IR=+0.612 n_feat=3 feats=mom_126d,coskew_60d_spy,atr_compression_20d"). seed=42 top-1 from prior cycle09b_track_a_eval JSON. All NAV correlations from script run.

**R2**: 0.761 raw NAV correlation with 0/3 factor overlap = sibling-by-construction (factor-independent). Verified by checking residual_vs_spy ≈ raw (defensive-equity-drift shared factor explanation).

**R3**: re-ran NAV builds for both seeds + 3 anchors; correlation computed via `_pair_corr` (same module as §5.1).

**R4 boundary**:
- seed=123 top-1's vs RCMv1 raw 0.868 is INTERESTING — exceeds 0.85 → reject_step5 per r41 tier (vs seed=42 top-1's max 0.810 = warn_label_void). seed=123 winner is **WORSE** at NAV diversification than seed=42 winner.
- Within-cycle stability raw 0.761 means cycle09b mining produces siblings within itself — this is a stronger sibling root cause finding than cycle04+05 (which were cross-cycle sibling).
- The fact that seed=123 G3 also fails on Trial9_v2 (with raw 0.654 just barely below 0.70) is borderline; sensitivity to anchor choice noted.
