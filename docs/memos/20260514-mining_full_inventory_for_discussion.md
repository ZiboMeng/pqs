# PQS Mining 完整历史 + Universe + 框架硬约束 + 战略 pivot 选项 —— 讨论版

**Date**: 2026-05-14 evening
**Audience**: 用户（senior US-equity quant operator）+ operator (Claude)
**Purpose**: 为后续 directional 讨论提供完整事实 base. **请直接在本 memo 各 §的 "📝 用户 annotation" 区批注**.
**Style**: 通俗 + 详细 + 数字精确到 verifiable bit
**Companion docs**:
- `docs/audit/20260514-mining_pipeline_plain_chinese_summary.md` (R1 mining 流程图)
- `docs/audit/20260514-comprehensive_project_audit.md` (R6 全面 audit verdict)
- `CLAUDE.md` (single source of truth for invariants + current state)

---

## §1 TL;DR — 5 句话总结

1. **PQS 在 2026-04-22 后做了约 16 个独立 mining 尝试**（Deep Mining 50-round → RCMv1 → Cand-2 → cycle04~cycle11 → PEAD），**只产生 0 个 forward-deployed fleet member**。
2. **共同失败模式 = sibling-by-NAV**: factor 怎么换、reweight 怎么调，最后产出 candidate 的 NAV daily-return Pearson 普遍 > 0.85 跟现有锚（RCMv1/Cand-2/Trial 9），意味着 **construction (long-only top-N monthly over 78-股 universe)** 才是 binding constraint，**不是 factor**。
3. **TC ceiling 是 PQS 当前框架真正的天花板**：Clarke-de Silva-Thorley 2002 long-only Transfer Coefficient 上界 0.45-0.55，cycle04-11 全部 0 nominee 是这个理论上界的实证表现，不是 implementation bug.
4. **唯一突破来自 PEAD bundle (2026-05-14 today)**: 第一个**事件驱动 + 非参数化触发** + Sharpe > 1.0 + MaxDD < 10% 的真 alpha 信号. 但 alpha shape = defensive (low CAGR < SPY) → 单独 deploy 无法过 Track A，**unlock 在 fleet 合成层**.
5. **决定性的 70-90 天窗口**: trial9_v2 / PEAD / options paper 3 个 forward candidate 的 TD60 verdicts 集中在 **2026-07-30 → 08-13** 三周内. 三个里至少 1 GREEN 才触发 fleet allocator / paid data 决策；如果全 RED, **strategic reassessment 在所难免**（objective / data / strategy type 大改, per cycle04 stop rule）.

📝 **用户 annotation §1**:
> [在这里写你的反应]

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

---

## §3 PQS Mining 阶段历史（pre-Track-A 时代）

### §3.1 Phase B Loop 1-50 (archived — NOT reproducible on current codebase)

- 50 iteration 的 LLM-Round + ralph-loop 搜索
- **Pre-P0.1-fix 数字**: CAGR 19.0% / Sharpe 0.98 / MaxDD -19.7%
- **数字 NOT 可重现 in post-2026-04-20 codebase** (P0.1 `apply_extra_shift=False` fix 改了 signal data window)
- 详 `docs/20260422-claude_md_phase_bc_history.md` §Part A

### §3.2 Deep Mining 50-round (2026-04-22 ✅, archived)

- 7 个 track × 50 rounds 同时探索
- 结果 archived in `docs/20260422-deep_mining_50round_final_synthesis.md`
- 这一波找到了多个 track 的方向 trade-off (因子 / 构造 / cadence 等)

### §3.3 RCMv1 20-round (2026-04-24 ✅, **converged to S2_paper_candidate**)

- 17-round 后 spec 收敛 + R18 acceptance PASS + R20 S1 candidate memo
- **RCMv1** = `rcm_v1_defensive_composite_01`, defensive composite of multiple factors
- Sharpe ~0.9, CAGR ~13%, MaxDD ~-20%
- 详 `docs/20260424-rcm_v1_final_synthesis.md`

### §3.4 Phase E governance + paper layer (2026-04-24 ✅, 14 rounds)

- Shipped `candidate_registry` + `frozen_spec` + paper CLI pipeline
- RCMv1 升 S2_paper_candidate status
- 详 `docs/20260424-phase_e_final_synthesis.md`

### §3.5 Phase E-post + Candidate-2 (2026-04-24 ✅, 8 rounds)

- 5 个 E-post gaps + Candidate-2 (`{ret_5d, rs_vs_spy_126d, hl_range}` equal-weight)
- Cand-2 升 S2_paper_candidate status
- 详 `docs/20260424-phase_e_post_cand2_final_synthesis.md`

### §3.6 Data-integrity round-3 (2026-04-25 ✅, 6 steps)

- 单一 canonical source = polygon 1m → daily 重建 78 syms
- 4 paper cells 重跑 drift = 0 bps BUT NAVs -5 to -71 pp vs pre-step3b
- 比如 2022 Cand-2 + 74.57% → +3.47% honest
- **Note**: 这是 universe-level data integrity fix，影响所有后续 mining 数字

### §3.7 OOS Framework MVP R1-R7 (2026-04-25 ✅)

- Shipped: `core/research/robustness/` + `core/research/concentration/` + drift reports + integration smoke
- Forward execution runner ONLY (no real forward init yet)
- 是后来 Track C cycle 框架的 infrastructure 基础

### §3.8 Research cycle 2026-04-26 #01 (2026-04-26 ✅, **0 nominee**)

- **第一次 partial unfreeze** 后的 cycle
- Pre-registered immutable criteria yaml sha256 `5e88d0c…d03ad28` (commit `4100f7b`)
- 200-trial TPE on 78-symbol × 2007-2023 panel
- Top trial `62445bdc62ae`: `beta_spy_60d × amihud_20d × mom_126d` (IC_IR=1.04 full-period, 4/4 walk-forward folds positive)
- **FAILED G2.A** on `watchlist_total_share=39.50% > 30% ceiling`
- ⚠️ 这就是 G2.A 30% 集中度上限设计的目的 —— catch concentration in 1-2 sectors
- 详 `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`

📝 **用户 annotation §3** (pre-Track-A 时代):
> [对 RCMv1 / Cand-2 / Phase E 的回头看，你觉得哪些 decision 应该重做？哪些是对的？]

---

## §4 Track A 时代（2026-04-29 开始）— cycle04~cycle11 详细

### §4.1 Track A discipline shipped (2026-04-29 ✅)

PRD `docs/prd/20260429-temporal_split_holdout_discipline_prd.md`. 关键 deliverable:
- `config/temporal_split.yaml` (split_name=`alternating_regime_holdout_v1`, **locked since 2026-04-29**)
- 17-gate `temporal_split_acceptance` evaluator
- 5-validation-year (2018/19/21/23/25) + 2 stress slice (covid_flash/rate_hike_2022) + 2026 sealed test (single-shot)
- Sealed eval ledger fail-closed on repeat
- C5 role-remint guard

**自此 PQS 所有 cycle 数字都是在这个 split 下产出的**.

### §4.2 cycle 2026-04-30 #01 (Tier 2 sibling-by-construction-and-factor-overlap)

**Lineage**: `track-c-cycle-2026-04-30-01`

**Two phases**:

#### Phase (a) Pre-A++ run (commit `f770d05`, sha256 `95027106…`):
- 49 archived trials with FAMILIES_V1's 33 factors
- **INVALIDATED**: search space 不满足 `factor_registry_pool: RESEARCH_FACTORS` 声明
- Cand-2 anchors `ret_5d`/`hl_range` unreachable; `mom_12_1` unreachable
- Pre-A++ artifacts preserved at `data/ml/research_miner/track-c-cycle-2026-04-30-01.preAplusplus/`

#### Phase (b) Post-A++ run (commit `da036da`):
- A++ patch ships FAMILIES_V2 (6 families, 64 reachable)
- Mining: 200 trials / 146 finite / 60 archived
- **Best IC_IR 0.6562** on `beta_spy_60d × mom_12_1 × volume_ratio_20d`
- ⚠️ Still shares `beta_spy_60d` with RCMv1 **verbatim**
- Family-tuple (A,B,C) identical to RCMv1
- Same long-only × monthly × top-N construction

**结论**: construction-collapse hypothesis 实证 confirmed. **33→61 factor 扩展 (with 17 newly-reachable intraday/microstructure/short-reversal factors) 产生零 archived trial 在 Family E 或 F at 21d horizon**. TPE convergence 在 construction not factor zoo.

2026 sealed window NOT consumed. 详 `docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md`.

### §4.3 cycle 2026-04-30 #02 (ARCHIVED — heterogeneous split-adjustment 污染)

**Lineage**: `track-c-cycle-2026-04-30-02`

- Single-axis diff vs cycle #01 = +**C-1 weekly cadence**
- Top-1 IC_IR=**1.0592** on `beta_spy_60d × mom_12_1 × volume_ratio_20d`
- **IDENTICAL composite** to cycle #01's top-1 (3-of-3 factor identical)
- **C-1 horizon hypothesis 完全 refute** at the IC level
- **ARCHIVED post-execution 2026-05-01**: 13/78 universe symbols 价格 panel inconsistent split scaling
- 数字 NOT 可重现, factor identity verdict (cycle #02 = cycle #01 sibling) SURVIVES the data corruption (verified by post-fix harness re-run on top-1 spec)

### §4.4 cycle 2026-05-01 #01 (INVALID — yaml typo)

- yaml typo `mining_config.trials: 200` vs canonical `n_trials: 200`
- miner CLI yaml→cli mapping 静默 fallback 到 default 50 trials; 只 3 archived
- Superseded by `track-c-cycle-2026-05-01-02`
- ⚠️ Operator self-audit 抓到 (not user); **第一例 "依赖捋清楚" 在 yaml field level 的失败**

### §4.5 cycle 2026-05-01 #02 (0 nominee, 10/10 Tier 2 sibling-by-NAV)

**Lineage**: `track-c-cycle-2026-05-01-02`
**yaml sha256**: `9fa478f0ffad33dc2d40eff8ec63b2e86799404b06695b2626390970f169ff23`

- **第一个 cap-aware-construction cycle** (`cluster_cap=0.20 + max_single=0.10`)
- Universe: 17 single-layer trade-level clusters / 54 stocks
- Top-1 IC_IR=1.187 on `rs_vs_spy_126d × drawup_from_252d_low × market_vol_ratio`
- **DIFFERENT from cycle #01/#02 sibling factors**
- 13 unique factors across 30 top-10 slots

**Cap-aware harness eval found 100% (20/20) of pooled-raw-Pearson pairs ≥ 0.85 reject threshold** (median 0.902, range 0.852-0.947).

- Residual after stripping shared SPY+QQQ beta: median 0.64
- Only 1/20 above 0.70 warn threshold

**Headline finding**: ~85% of NAV correlation 是 structural shared market beta of any long-only top-N portfolio over a 54-stock universe; cluster_cap construction 不 break it 因为 universe 本身 binding.

- Cluster_concentration_max ~0.30 vs cap_aware target 0.20 是 intra-month price drift between monthly rebalances, NOT a selector bug.

**结论**: long-only top-N 在 54-股 universe + monthly cadence framework 下，sibling-by-NAV 是 structural inevitable (not implementation).

Next-axis recommendation: **C-4 cross-asset** (universe expansion to bonds + commodities + cash anchor) — direct attack on structural cause.

### §4.6 cycle 2026-05-01 #04 cross-asset (0 nominee, 10/10 Tier 2 by R41 v2 with NAV correlation)

**Lineage**: `track-c-cycle-2026-05-01-04`
**yaml sha256**: `b07ece9c9b8c82325d48a0376a871e100f934cab79da98c227dca431fbdd9efc`

- **第一个 cap_aware_cross_asset cycle**: 53 stocks + 6 cross-asset ETFs (TLT/IEF/SHY/GLD/BIL/SHV; USO/SLV excluded)
- 22-cluster unified map (17 stock + 5 cross-asset)
- Asset class caps: equities ≤70% / bonds ≤40% / commodities ≤20% / cash_anchor ≤30%
- 200 TPE trials / 62 archived

**P0a-P0d prep shipped commit `cc582a2`**:
- Distribution sidecar `data/ref/distributions.parquet`
- `BarStore.load(adjusted_total_return=True)` (CAGR parity vs yfinance auto_adjust ≤ 0.01% on 6/6 ETF)
- P0b 2009-2014 backfill (9054 new daily rows; BIL phantom-split handled)
- P0c risk_cluster_map cross-asset extension
- P0d composite_evaluator cap_aware_cross_asset mode

**Two character clusters in top-10**:

**Cluster A (4 trials, drawup+amihud anchored)**:
- Pooled raw NAV corr **0.66-0.70** vs RCMv1/Cand-2/Cycle03-top
- **第一个 cycle 拿到 <0.85 raw**（partial diversifier per yaml）
- Max_dd -16% to -18% (vs cycle03's -27%)
- Tier 2 by **factor-overlap=2** with RCMv1

**Cluster B (6 trials, vol-anchored)**:
- Pooled raw 0.91-0.94 (NAV reject)
- Max_dd -27% (similar to cycle03)
- 2025 vs_qqq +9.8% to +10.6% (8/10 trials pass hard gate; trial 8 best at +10.5% with -19% DD)
- Tier 2 by NAV

**Empirical headline**: cap_aware_cross_asset **DOES** break NAV correlation for some mining outcomes (Cluster A first <0.85), **BUT** mining objective converges on RCMv1-anchor factors (drawup + amihud) → factor-overlap rule disqualifies the NAV-diverse trials.

**Breaking mechanism = asymmetric factor coverage on bonds**: amihud doesn't compute on cash → composite NaN → selector defaults.

**Process bug + fix**: cycle04 eval shipped with empty `nav_correlation_vs_existing_pair` → R41 v1 verdict was factor-overlap-only and incorrectly reported 5 Tier-1 nominees. Caught in self-audit; fixed via `dev/scripts/cycle04/cross_cycle_nav_correlation.py` post-eval. R41 v1 → v2 verdict shift: 5 false-positive Tier 1 → all Tier 2.

**Cycle #06 stop rule pre-committed**: if cycle #05 also 0 nominee, no cycle #06 mining; pivot strategically.

详 `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md`.

### §4.7 cycle 2026-05-01 #05 anchor-sensitivity diagnostic (0 nominee under strict CLAUDE.md QQQ rule, 7 Tier 1 R41 verdicts but only Trial 9 passes yaml hard blockers)

**Lineage**: `track-c-cycle-2026-05-01-05`
**yaml sha256**: `ce559a0ac97a7eb36243de7494c44650ea0779839ec70bc159b94da06a2cbaf7`

- **Single-axis diff vs cycle #04**: ban `drawup_from_252d_low + amihud_20d`（cycle04 锚）
- Mining: 200 trials / 149 finite / 44 archived
- **Best IC_IR=+0.5483** (down 54% from cycle04 +1.1991)
- Top-1: `rs_vs_spy_126d, max_dd_126d, ret_2d`
- **Top-10 R41: 7 Tier 1, 3 Tier 2, NO Tier 1-conditional, NO Tier 5**
- **第一次 cycle 产生 ANY Tier 1 classification**

#### Trial 9 (`6c745c601a47`) deep audit — passes yaml hard blockers BUT fails CLAUDE.md project invariant:

- Spec: `beta_spy_60d (1/3) + max_dd_126d (1/3) + ret_1d (1/3)` (A/B/F)
- cum_ret 502.6% / sharpe 0.78 / full max_dd -24.5% / vs_qqq full +6.3%
- Per-year max_dd: 2018=-15.2%, 2019=-6.8%, 2021=-6.0%, 2023=-9.3%, **2025=-18.2%** (all > -20% ✓)
- Per-year vs_qqq: 2018=+3.7%, 2019=-13.2%, 2021=-3.3%, 2023=-19.8%, 2025=+9.6% → **5-window mean = -4.59% < 0** (CLAUDE.md QQQ Rule HARD constraint FAILS)
- Stress slices: covid_flash max_dd=-13.3%, rate_hike_2022=-15.8% (both > -25% ✓)
- NAV: **raw 0.54-0.69 vs all 5 anchors (partial_diversifier band)**; residual 0.07-0.36; factor_overlap_max=1 (only beta_spy_60d shared)
- Asset-class: equity 28.5% / bond 15.4% / commodity 6.3% / cash 10.4% / non_equity_avg **32.1%** (higher than cycle04 trial 8 ~24%)

**Hypothesis verdict**:
- H1 (anchor-specific) SUPPORTED — mining found Tier 1 with overlap=0/1 with RCMv1
- max_dd_126d substitutes drawup in Family B for 4/7 Tier 1 trials
- H3 (drawup+amihud binding at IC) PARTIAL — IC_IR drop 54% confirms IC anchoring
- H2 (low-vol attractor universal) PARTIAL — Trial 9 has low-vol character (max_dd_126d) mixed with short-momentum + market beta

#### Trial 9 → forward init as diversifier role (2026-05-01)

- candidate_id: `trial9_diversifier_001`
- **CLAUDE.md QQQ deprecation 2026-05-02 让 Trial 9 forward init 可行** (没了 OOS walk-forward window-mean vs_qqq HARD blocker)
- PRD `docs/prd/20260501-two_stage_allocation_architecture_prd.md` Phase C-PRD-1 shipped
- start_date 2026-05-04, soft_warn_flag `diversifier_2025_maxdd_18_20pct`
- ⚠️ **Trial 9 v1 在 2026-05-12 halted at TD004**: v2.1 revalidate bound_only-with-empty-digest (codex R10 Blocker 2 fail-closed by design)
- **Trial 9 v2 (`trial9_diversifier_002`)** shipped 2026-05-12 with `track_signal_input_per_cell=true` opt-in (PRD 20260512)
- Trial 9 v2 active forward NOW (TD002 today)

📝 **用户 annotation §4 (cycle04-cycle05 era)**:
> [Trial 9 当时 forward init 这个决定，回头看你怎么评估？是不是太早？]

### §4.8 cycle 2026-05-06 #06 v2 NAV-based (0 nominee, 4 strategic findings)

**Lineage**: `track-c-cycle-2026-05-06-06`
**PRD**: `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md` v1.1

**第一个 v2_nav_based mining cycle**:
- 6 implementation commits (`f2b6059..3fec344`) shipped Phase 1 + Phase 2 + Phase 3
- Yaml sha256 `7b3e20dd8485900c0307c0ef89adc0228ccfb42964d54447550a52184a1bc1df`
- Mining: 200 trials / 149 finite / 66 archived
- Top-1 trial `bab8cfe88af3`: `drawup_from_252d_low + trend_tstat_20d + ret_2d`
- ⚠️ Sibling pattern with cycle04/05 **持续**

**Hypothesis tests**:
- H1 Spearman v2/v1 = **0.89** (FAIL — too IR-heavy at 0.7/0.15 weights)
- H2 holding_freq monthly=49/weekly=10/daily=7 (FAIL by archived count; process finding: H2 should test SAMPLED not ARCHIVED)
- H3 v2 top-1 nav_sharpe 0.565 < v1 top-1 0.664 (FAIL — Pareto regression)
- H4 anchor_corr 100% < 0.50 (PASS — Option β viable but suspiciously clean)

**Track A acceptance on top-3 trials: 0/3 PASS**; all fail validation_aggregate_excess_vs_spy/qqq + beta_to_qqq.

详 `docs/memos/20260506-cycle06_closeout.md`.

### §4.9 cycle 2026-05-07 #07a factor reweight + post-fix Trial 3 (1 Track A pass post-P0-fix, NAV-corr Red verdict)

**Lineage**: `track-c-cycle-2026-05-07-07a`
**Single-axis diff vs cycle06**: factor reweight (drawup_from_252d_low + 短动量 anchor 强化)
**Yaml sha256**: `1295911ab8949194c3eebf48...` (commit `2fc5198`)

Mining 200 trials / finite ~149 / 30 archived; **top-3 Track A original verdict 0/3 PASS**.

#### P0 wiring bug discovery + fix (2026-05-07)

**R12 audit reverse-validate** caught suspicious "16 of 17 gates correlated FAIL with beta=present" pattern across 9 trials.

**Root cause**: `dev/scripts/cycle{06,07a,08}/cycle*_track_a_eval.py` built `metrics["beta_to_qqq"]` (top-level scalar) but `core/research/temporal_split_acceptance.py:_eval_beta_gate` resolves nested `metrics["beta"]["beta_to_qqq"]` (mirroring yaml schema). Pre-fix gate fail-closed silently → all 9 trials had **false-negative beta gate FAIL** despite actual betas well below 0.85 cap.

Fix shipped commits `5873653` + `9cacab3` (evaluator scripts + 6 regression tests `tests/unit/research/test_beta_metric_path_canonical.py`). Postmortem: `docs/audit/20260507-beta_metric_path_bug_postmortem.md`.

#### Post-fix 9-trial Track A re-eval (2026-05-07):

- **cycle06**: 0/3 PASS (all fail `validation_aggregate_excess_vs_spy` — vs_spy aggregate 真 binding gate)
- **cycle07a**: **1/3 PASS** — Trial 3 `1e771580f486` is sole survivor:
  - composite: `drawup_from_252d_low + mom_63d + ret_1d`
  - 17/17 gates PASS
  - 17yr cum_ret +1016.75% vs SPY +231.94% / QQQ +496.38%
  - Sharpe 1.08, full max_dd -20.0%, beta 0.534
  - top1 14.5% / top3 36.6%
  - 2025 holdout +25.1% (+8.4% vs SPY)
  - covid_flash +3.6% (vs SPY -13.8%)
  - rate_hike_2022 -7.3% (vs SPY -16.6%)
- **cycle08**: 0/3 PASS (same vs_spy aggregate failure shape)

Amendment memo: `docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md`.

#### Trial 3 NAV correlation pre-init gate

**Pre-forward-init authorization required raw < 0.85 + residual < 0.50 for all 3 pairs vs anchors**.

| Pair | raw | residual_vs_spy | residual_vs_qqq |
|---|---|---|---|
| Trial 3 vs RCMv1 | **0.874** | 0.603 | 0.613 |
| Trial 3 vs Cand-2 | **0.892** | 0.688 | 0.699 |
| Trial 3 vs Trial 9 | 0.783 | 0.319 | 0.381 |

**Verdict: RED** (raw ≥ 0.85 in 2 pairs; residual ≥ 0.50 in 4 of 6 measurements). **Trial 3 NOT forward-init'd**; evidence-only memo records the structural finding: `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`.

#### Three structural findings (sibling-by-NAV root cause)

- **Finding 1**: drawup-anchor + monthly + top-N **是 binding sibling geometry**. Trial 3 shares ONLY `drawup_from_252d_low` factor with RCMv1 (1 of 4) yet raw 0.874. **Banning the FACTOR doesn't break the sibling pattern; banning the CONSTRUCTION does**.
- **Finding 2**: Cand-2 sibling-by-NAV tighter than RCMv1. Trial 3 shares 0 of 3 factors with Cand-2 yet raw 0.892. Long-only top-10 over 78-stock universe = MARKET-COVERAGE binding geometry; disjoint factors with same construction pick ~30-50% identical names monthly.
- **Finding 3**: Trial 9 (max_dd_126d) is **structurally distinct**. Both use cap_aware monthly top-N yet raw 0.783 + residual 0.32-0.38. First cycle04-08 candidate where Family-B anchor swap (drawup → max_dd_126d) produces NAV-distinct behavior. Empirical confirmation that **drawup vs max_dd 是 real sibling boundary**.

### §4.10 cycle 2026-05-08 #08 regime-conditional (0 nominee, 40-trial smoke)

**Lineage**: `track-c-cycle-2026-05-08-08`
**Single-axis diff vs cycle07a**: `ObjectiveWeightsV3` regime-conditional weights (BEAR-IC / NEUTRAL-IC / BULL-IC scoped composite evaluator)

- Mining 40-trial smoke (NOT full 200) / 11 archived
- Track A original verdict 0/3 PASS
- Smoke caveat preserves yaml integrity (yaml=200, runner override `--n-trials 40` per R7 prep)

### §4.11 cycle 2026-05-12 #09 (INVALID — sampler architecture mismatch)

**Lineage**: `track-c-cycle-2026-05-12-09`
**Yaml sha256**: `351e6e2ce004ef5a96a92ebe85f394ee193467dab78b60e4deb94c14ec0c424f`

**Single-axis diff vs cycle08**:
- `factor_registry_pool=RESEARCH_FACTORS` (162 not 67) — Bucket A/B/C/Macro shipped 2026-05-12
- `G_new_family_anchor` HARD (≥1 anchor from G/I/K/L/M/N/O/P)
- `G_anti_sibling_nav` 3-way (raw NAV Pearson < 0.85 vs RCMv1 / Cand-2 / Trial 9 v2)
- `drawup_from_252d_low + amihud_20d` banned
- 7 masked-dup banned per Z1 strict-train cluster r ≥ |0.99|
- v2_nav_based objective + monthly + cap_aware_cross_asset

**Mining: 200 trials → 100% PRUNED at sampler stage, 0 backtest evaluations, 2.1 min wall-clock**.

**Root cause (R4 postmortem)**: `suggest_composite_spec` independent-family-sampling architecture was designed for cycle04-08's 4-6 families (P(valid spec)=2.74%). Today's 17-family expansion drops P(valid spec) to **0.0005%** (100k Monte Carlo confirmed 0 hits).

**NOT 0-nominee verdict** per yaml.stop_rule_post_cycle (which assumes "searched but didn't find alpha"). This is **"didn't actually search"** — INVALID mining run.

Postmortem: `docs/memos/20260512-cycle_09_sampler_architecture_postmortem.md`.

**User explicit-go 2026-05-12** "同意 A 和 C 同时跑". Two paths shipped:
- **Option A**: `sampling_mode: family_first` added to `suggest_composite_spec` (commit `f41c7e5`). Default "independent" preserves cycle04-08 bit-for-bit. P(valid spec) ≈ 100% by 构造.
- **Option C Phase 1**: `IntradayReversalStrategy` skeleton + config (commit `d7e48ed`). Phase 2-3 deferred.

**cycle #09 re-fire 待 user-go**: same sha256-locked yaml + Option A sampler refactor + `--bypass-invalid-marker` launcher flag.

### §4.12 Post-cycle10 strategic roadmap + K1 (2026-05-13)

**cycle10 closed 0-nominee** (R7 fail-SPY risk realized per NAV-residualized objective per `docs/memos/20260513-cycle10_closeout.md`).

**Roadmap memo v1 → v1.1 → v2 FINAL** (commits `10838c5` → `a6aa4f0` → `7b12d85`):

- **TC ceiling (Clarke-de Silva-Thorley 2002 FAJ, long-only TC=0.45-0.55) reframes bundle binding**
- **Legitimate attacks** = horizon change (intraday) + cadence change (signal-driven) + cross-asset done RIGHT
- **D1 (200+ stocks) dropped** with TC-ceiling reason replacing weak cycle04 n=1
- **D3 (LLM mining) DROP → DEFER** until K1+T1 produces working construction
- **Signal seed library**: 6 evidence-strong seeds (Faber 200-SMA / Connors RSI(2) / Donchian 20/55 / HY OAS / Zweig breadth thrust / GKM abnormal volume) + 3 orthogonal archetypes (trend / mean-reversion / cross-asset risk gate)

**User 8/8 explicit-go** locked v2:
1. T1a first then T1b∥T1c
2. PEAD+FOMC bundle
3. cycle11 3 objectives all-try
4. ML Phase 2 coupled with T2
5. F1+F2+F3 all-do
6. K1 strict TDD
7. unified observe runner
8. seed library full-collect

#### K1 ship (2026-05-13 evening)

- `SignalDrivenBacktest` wrapper at `core/backtest/signal_driven_runner.py` (212 lines)
- 30-test TDD suite at `tests/unit/backtest/test_signal_driven_runner.py`
- K1.1 design audit / K1.4 regression report / K1.5 closeout memos
- **Architectural choice**: wrapper pattern, **NOT** `BacktestEngine.run` modification → M11a/M11b parity bit-for-bit guaranteed
- All 30 GREEN; full `tests/unit/backtest/` 199/199 PASS

#### SPY/BIL/SHV off-by-one date label bug + Option A fix (2026-05-13 evening)

- Postmortem `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`
- 3 PQS active syms affected (SPY/BIL/SHV via yfinance)
- Fix commit `2898be8`: `align_daily_index` now `tz_convert(_ET)` before `tz_localize(None)`
- Cycle04-10 mining numerical claims **DEPRECATED**; qualitative findings PRESERVED (sibling-by-NAV REINFORCED not invalidated)
- 81-symbol universe scan post-fix = 0 affected; 3 forward bar_hash tests = 3/3 PASS

### §4.13 cycle 2026-05-14 #11 signal-driven mini-smoke (informative null at 30bp + open_df fix)

**Lineage**: `track-c-cycle-2026-05-14-11`

**Cost gate revision (per user directive 2026-05-14)**:
- baseline slip raised 5bp → 30bp (= 6× original) to match realistic retail at-market execution
- Memo `docs/memos/20260514-cost_gate_revision_6x.md`
- cycle04-10 archive immutable (locked_after_first_use); cycle11+ uses 30bp baseline

**T2b cycle11 mini-smoke v1** (5bp cost) → Connors RSI(2) hold=3 Sharpe **3.54** ← INFLATED

**T2b cycle11 re-smoke v2** (30bp cost) → 15/20 trial 跑赢 SPY ← STILL inflated
verdict: Donchian-20 hold=21 Sharpe 1.31, CAGR 21.24%

**Spot-check audit (operator-initiated)**: standalone Donchian-20 hold=21 Sharpe **0.66** (vs smoke v2 的 1.31, 差 0.65 Sharpe)

**Root cause**: smoke v1/v2 没传 open_df → `BacktestEngine` fallback 用同日 close 作 fill price → 对 breakout 策略**系统性高估**.

**Smoke v3 post-fix** (open_df 传入):
- 3/20 marginally 过 SPY (Sharpe 0.76)
- Top: **Faber hold=252 Sharpe 0.788** (= +0.029 over SPY = 4% 边际)
- 全部 Connors RSI(2) 变种**亏钱** (Sharpe -0.054 到 -0.657, MaxDD -33% 到 -61%)

**Verdict**: cycle11 informative null — 78-股 universe + 30bp + 参数化 signal-driven mining 逃不出 TC ceiling.

**Audit memo** `docs/audit/20260514-cycle11_smoke_execution_artifact.md` documents close-fallback artifact + recurrence-prevention.

📝 **用户 annotation §4 (cycle04-cycle11 全程)**:
> [这一连串 0 nominee 你怎么看？cycle10 R7 fail-SPY 触发是不是太早？cycle11 信号驱动这个方向应该 push further，还是认输？]

---

## §5 PEAD Bundle Phase 1 (2026-05-14 — TODAY) 详述

### §5.1 实验设计 (PRD 20260514)

- PRD: `docs/prd/20260514-pead_bundle_phase1_prd.md`
- Roadmap v2 Q2 LOCK trigger
- Pre-registered hypothesis:
  - if both win → 鲁棒 PEAD
  - **if only Path 1 → fundamental-anchored real信号**
  - if only Path 2 → price-momentum echo

### §5.2 Path 1 SUE (基本面 surprise)

**Definition** (Foster-Olsen-Shevlin 1984):
```
expected_EPS(Q) = EPS(Q-4)  (naive same-quarter LY)
residual(Q) = actual_EPS(Q) - expected_EPS(Q)
sigma(Q) = std(residual_{Q-1 .. Q-8})  (8-q rolling std)
SUE(Q) = residual(Q) / sigma(Q)
Signal = SUE(Q) > +threshold (long-only)
Hold = max_hold business days
```

**Smoke 9-trial @ 30bp**: 8/9 trial 跑赢 SPY (Sharpe 0.76).

**Top results**:

| Trial | SUE σ | hold | top_n | Sharpe | CAGR | MaxDD | n_trades | signals/yr |
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

**模式**: threshold 1.0-1.5σ + max_hold 21-60d + top_n 5-20 → **robust knife-edge-free Sharpe 提升**.

### §5.3 Path 2 price-jump (AR proxy)

**Definition** (Chan-Jegadeesh-Lakonishok 1996):
```
On earnings announcement day T:
  AR(T) = ret_stock(T) - ret_SPY(T)
  Signal = AR(T) > +AR_threshold
```

**Smoke 9-trial @ 30bp**: **0/9** beat SPY (top Sharpe 0.717).

### §5.4 Hypothesis 验证 verdict

- Pre-registered "**if only Path 1 → fundamental-anchored real信号**" 触发 ✅
- **基本面 SUE 是 information diffusion 真信号**；**价格跳空作 surprise 代理 = 噪声占主导**
- Phase 1 给出的最干净的 mechanism-of-action 判断

### §5.5 Track A acceptance on trial 1 + trial 6

**Trial 1 (SUE≥1.5σ hold=21 top_n=10)**:
- 14/17 gates PASS
- Per-validation-year MaxDD: 2018=-6.08%, 2019=-4.35%, 2021=-4.38%, 2023=-1.73%, 2025=-2.27% (all <<20%)
- Stress: covid_flash -1.77%, rate_hike_2022 -4.07% (<<25%)
- 2x cost robust: $13965 final at 60bp (POSITIVE)
- top1 0.10 / top3 0.30 / beta_to_qqq 0.10
- **Fail 3 gates** (all CAGR-related): `validation_aggregate_excess_vs_spy`, `validation_aggregate_excess_vs_qqq`, `role_core__validation__2025__excess_vs_qqq`

**Trial 6 (SUE≥1.5σ hold=60 top_n=10)**: same shape, MaxDD higher (-24%) but full pass on per-year MaxDD.

### §5.6 NAV daily-return Pearson vs anchors

| Pair | daily-return Pearson | Verdict |
|---|---|---|
| trial 1 vs alt-A intraday reversal | +0.09 | PASS (low) |
| trial 1 vs T1b ConfirmationPattern | +0.38 | PASS |
| trial 1 vs cycle11 Donchian-20 | +0.37 | PASS |
| trial 6 vs alt-A | +0.12 | PASS |
| trial 6 vs T1b | +0.54 | PASS |
| trial 6 vs cycle11 | +0.55 | PASS |

**所有 daily-return correlation < 0.85** → PEAD 跟现有 anchor genuine differentiated.

### §5.7 Per-year vs SPY breakdown (关键诊断)

| Year | strat ret | SPY ret | excess | regime |
|---|---|---|---|---|
| 2018 | +6.1% | -7.1% | **+13.2%** | BEAR |
| 2019 | +5.2% | +30.9% | -25.7% | BULL |
| 2021 | +6.0% | +27.3% | -21.2% | BULL |
| 2023 | +1.7% | +23.9% | -22.2% | BULL |
| 2025 | +6.0% | +12.8% | -6.8% | BULL |

**结论**: PEAD 在 BEAR (2018) 大幅跑赢；BULL 年 (2019/21/23/25) underperform → **典型 defensive sleeve 行为** — 低波低 DD 但 CAGR 不及市场.

### §5.8 Forward-init evidence-only

- candidate_id: `pead_sue_trial1_evidence_v1`
- candidate_role: `evidence_only_observation` (NOT fleet)
- spec_hash: `9a2ef503a241f407d2cf43c6b5a2ab3b12cdc2d16bcd35963e694000a8ca9d30`
- start_date: 2026-05-15 (Fri)
- TD000 baseline: Sharpe 1.056, CAGR 5.51%, MaxDD -7.64%
- **TD60 verdict ~2026-08-13**

详 `docs/memos/20260514-pead_bundle_phase1_close.md`.

📝 **用户 annotation §5 (PEAD)**:
> [PEAD evidence-only forward-init 决定你满意吗？60 天 soak 后如果 Sharpe 还 > 0.8，你倾向 fleet 合成还是 paid 8-K 数据 Phase 2？]

---

## §6 Forward observation candidates 完整状态

### §6.1 历史 (legacy decay verification)

| Candidate | Init | Aborted/Closed | Reason |
|---|---|---|---|
| `rcm_v1_defensive_composite_01` | 2026-04-24 | **aborted 2026-04-30** | 108 bps NAV drift + 2.42% raw drift across 13 held syms incl. SPY+QQQ → F-PRD v2.1 §4.4 fail-closed |
| `candidate_2_orthogonal_01` | 2026-04-24 | **aborted 2026-04-30** | Same data revision (16 held syms) |
| `trial9_diversifier_001` | 2026-05-04 | **completed_fail 2026-05-12** | TD004 v2.1 revalidate `bound_only` (codex R10 Blocker 2 fail-closed by design); fix via PRD 20260512 per-candidate `track_signal_input_per_cell` opt-in |

### §6.2 当前 active (3 candidates 并行)

| Candidate | Role | Start | TD count today | TD60 verdict |
|---|---|---|---|---|
| `trial9_diversifier_002` | diversifier | 2026-05-13 | 2 (TD001 baseline + TD002 cum_ret +0.36%) | **~2026-08-06** |
| `pead_sue_trial1_evidence_v1` | evidence_only | 2026-05-15 | 1 (TD000 baseline) | **~2026-08-13** |
| `spy_8otm_bull_put_v1` (options) | options sleeve | 2026-05-04 | 6 (TD006, no entries yet) | **~2026-07-30** |

### §6.3 决策窗口集中 2026-07-30 到 08-13 (~2 周)

- 3 个 forward soak verdict 同期对齐
- 至少 1 GREEN → 触发 Phase C-PRD-2 fleet allocator + paid 数据决策
- 全 RED → strategic reassessment per cycle04 stop rule

📝 **用户 annotation §6**:
> [3 个 candidate 这种"组合下注"策略你觉得分散得够吗？还有哪类候选应该再 forward-init？]

---

## §7 当前框架硬约束（invariants — NEVER violate without explicit user-go）

来源: `CLAUDE.md` §"Invariant Constraints":

### §7.1 Strategy-level

- **long-only**: 不可做空
- **no-margin**: 不可融资
- **no-short**: 不可借券
- **SQQQ blacklisted** (反向 ETF)
- **TQQQ/SOXL** require stricter risk thresholds (`max_single=10%, max_total=12%, require_risk_on_regime=true`)

### §7.2 Benchmark + risk

- **SPY primary HARD outperform gate** (full period + 2025 holdout)
- **QQQ secondary diagnostic ONLY** (deprecated as hard gate 2026-05-02)
- **MaxDD target 15-20%**, not worse than SPY in crisis
- **2008-style scenario MaxDD ≤ 25%** (testable via stress slices)
- **No concentration in ≤3 symbols** (concentration ceilings top1≤40% / top3≤70%)

### §7.3 Data + execution

- **Pricing semantics**: adjusted close + splits.parquet read-time cascade (no dividends currently)
- **T+1 open execution** (real open_df, not close approximation)
- **Halted/stale assets**: mark at last valid price + diagnostic flag (NOT removed from NAV)

### §7.4 Process

- **All thresholds must be configurable** (config/*.yaml), never hardcoded
- **Backtest-execution consistency** preserved
- **Chinese reporting, English code naming**
- **Sealed 2026 panel single-shot**: NEVER touched yet; one-shot post-forward-soak

### §7.5 Cost (cycle11+ revision)

- **30bp slippage_interday + 60bp slippage_intraday + 2bp commission** baseline (= 6× cycle04-10 baseline)
- 2x cost robustness gate: final equity must remain POSITIVE
- cycle04-10 archive locked at 5bp (immutability rule)

📝 **用户 annotation §7**:
> [哪条 invariant 你愿意 review？哪条 absolute？特别是 long-only / no-short — 这个 boundary 调整对 alpha 空间影响极大]

---

## §8 PQS 已 ruled out 的路径（实证 + 理论 双重证据）

### §8.1 Factor zoo expansion 作为 primary unlock

- cycle04→cycle11: 33 factor → 162 factor (5× 扩展)
- 同样的 sibling-by-NAV 问题反复出现
- cycle #04 cross-asset cluster A (drawup+amihud anchor) 是唯一打破 NAV correlation 的 cluster，但被 factor-overlap rule 否决

**Verdict**: 加 factor 不解决 long-only top-N 的 binding constraint.

### §8.2 IC-based mining objective (v1)

- cycle04-08 all v1
- 全 0 nominee
- v2 NAV-based (cycle06+) Pareto-regressed at top-1 Sharpe → H3 fail

**Verdict**: 切换 objective 不是 root cause fix.

### §8.3 Weekly cadence (vs monthly)

- cycle 2026-04-30 #02 single-axis weekly
- top-1 IDENTICAL composite to cycle #01 monthly
- C-1 hypothesis refuted at IC level

**Verdict**: cadence change 不破 sibling-by-NAV.

### §8.4 Parametric technical signals at 30bp realistic cost

- cycle11 mini-smoke v3 post-bug-fix
- 3/20 marginally 过 SPY，best Sharpe 0.788 (+0.029 over SPY)
- 全部 Connors RSI(2) variants 亏钱
- Donchian / Faber / Connors family 都不过 30bp

**Verdict**: 参数化 breakout / mean-reversion / trend-following 在 30bp 真实成本 + 78-股 universe 下无 alpha unlock.

### §8.5 Price-jump alone as earnings-surprise proxy (Path 2 PEAD)

- 0/9 trial 跑赢 SPY
- AR > +X% 触发被 macro / sector / guidance confound 淹没

**Verdict**: 单纯价格反应不等于真正的 information diffusion.

### §8.6 FOMC pre-announcement drift (T1c)

- T1c FOMC drift 在 post-2015 数据上 confirmed dead
- 详 `docs/memos/20260513-fomc_drift_smoke.md`

**Verdict**: Fed cycle 已被市场学习消化.

### §8.7 Wheel options strategy

- Phase 1 sweep
- MaxDD -32.72% > 25% ceiling
- Long-only no-margin 结构性原因（CC assignment at lower spot 时放大 loss）

**Verdict**: 不再 revisit.

📝 **用户 annotation §8**:
> [这些 ruled-out 你都同意吗？哪条想再开一次？]

---

## §9 PQS 未 ruled out / 开放方向

### §9.1 Event-driven signals — PEAD Phase 1 已证实有效

- PEAD Path 1 SUE: Sharpe 1.06 / MaxDD -7.6%
- 唯一 unlock 已 evidence-only forward soak

**Open question**: Phase 2 paid 8-K real-announce-date data ($50-200/mo) — 当前 filed_date 比 8-K 晚 7-14 天，漏掉最强的 0-10d drift；如果 0-10d 加回来，Sharpe 可能 1.5+，CAGR 可能过 Track A hard gate.

### §9.2 Intraday execution layer

- **T1a alt-A intraday reversal** (Phase 3 backtest done): 用 intraday-bridge 模块，alpha 在 5-bp 成本下 marginally 过 Track A
- **T1b ConfirmationPattern**: Sharpe 1.18 / CAGR 20.3% 但 year-inconsistent → Track A fail
- **T1c FOMC drift**: dead

**Open question**: T1a/T1b 在 30bp realistic cost 下能否过 Track A? 当前都没 re-eval at 30bp.

### §9.3 Cross-asset universe expansion (partially explored)

- cycle #04 cross-asset 加了 6 ETF (TLT/IEF/SHY/GLD/BIL/SHV)
- Cluster A pooled raw NAV corr 0.66-0.70 (第一个 < 0.85)
- 但 factor-overlap rule 否决了 Cluster A

**Open question**: 是否应该 weaken factor-overlap rule 在 cross-asset context? OR 重做 cycle #04 with strict factor-overlap ban?

### §9.4 Universe expansion to 200+ stocks (D1, dropped 2026-05-13)

- Roadmap v2 把 D1 删掉，理由 = TC ceiling 不靠 universe size 解
- **BUT**: cycle04 实证 only n=1, 理论 argument 不是绝对

**Open question**: 78-股 → 200-股 真的对 TC ceiling 没用吗? 是否值得 single-axis 测一次?

### §9.5 ML alpha mining Phase 2 (T2c, coupled with T2)

- Roadmap v2 用户 lock Q4 "ML Phase 2 coupled with T2"
- ML Phase 1 closeout per `docs/memos/20260513-ml_phase_1_closeout.md`
- ML Phase 1 §3.9 abort condition fired (Track A FAIL)

**Open question**: ML Phase 2 design wait for T2 (cycle11 / PEAD) 或 immediate restart?

### §9.6 Options sleeve Phase 2 (paid chain data)

- Phase 1 (free path) viability memo: SPY 8% OTM bull put Sharpe 0.62 (synthetic 33yr backtest)
- Phase 2 unlock = paid ORATS / Polygon options chain data (~$50-200/mo)
- Gated on Trial 9 v2 TD60 GREEN + options paper TD60 GREEN

**Open question**: 如果 options paper TD60 RED 但 Trial 9 v2 GREEN, 单边 unlock Phase 2 OK 吗?

### §9.7 Long-only constraint relaxation (requires explicit user-go)

- 任何 short/margin/leverage 调整都是 invariant level change
- Theoretically 最大 alpha unlock (TC ceiling 从 0.45 → 0.7+ for long-short)
- 跟 PQS "long-term sustainable, not Black-Swan-fragile" 原则有 tension

**Open question**: 用户 stance？ never (current default)? conditional (e.g., only in specific regime)? gradual (start with covered short via options)?

### §9.8 Fleet合成 architecture (Phase C-PRD-2 + PRD-3)

- 当前架构 = single candidate deploy
- PRD 20260501 two-stage allocation 已写但 deferred
- PEAD defensive + T1b high-CAGR + Trial 9 v2 diversifier 合成可能同时拿到多个属性

**Open question**: Phase C-PRD-2 启动 trigger?
- Roadmap v2 默认 = Trial 9 v2 TD60 GREEN
- 但 PEAD 今天 evidence-only 推出 → 是否提前 trigger?

📝 **用户 annotation §9**:
> [9 个开放方向，按你想 push 的优先级排序。哪几个先做？哪几个等？]

---

## §10 战略 pivot options (NOT pre-selected, awaits user-go)

### Option A — Conservative continue
- 维持 3-candidate forward soak (trial9_v2 + PEAD evidence + options paper)
- 等 7/30-8/13 TD60 verdicts
- 中间 idle period 做 INDEX.md cleanup + 文档对齐 + 测试覆盖度
- **Operator pros**: zero new risk, max信息 budget for 3 verdicts
- **Operator cons**: 3 个月 no new alpha attack

### Option B — PEAD Phase 2 immediate prep
- 不等 PEAD TD60，开始 Phase 2 设计:
  - Polygon / IEX 8-K real-announce-date feed integration (~3 day eng)
  - Cross-validate PEAD Sharpe 在 real 8-K vs filed_date (~1 week eng)
  - 准备 fleet 合成 schema (PEAD defensive + momentum overlay)
- **Operator pros**: PEAD 是 today 唯一 unlock, momentum-of-attention valuable
- **Operator cons**: 付费数据 prematurely; 如果 PEAD TD60 RED 浪费 $50-200/mo

### Option C — Cycle #09 family_first re-fire (test the architecture fix)
- Option A sampler refactor 已 ship；从未在 real 200-trial test
- 162-factor pool + family_first sampling 可能产出 truly different sibling
- 单跑 ~2 hour wall-clock
- **Operator pros**: 真正测 sampler fix, 低成本
- **Operator cons**: 可能 again 0 nominee → 不增信息

### Option D — T1a/T1b 30bp re-eval
- T1a alt-A intraday reversal + T1b ConfirmationPattern 当前 5-bp 成本 evaluated
- 重新跑 30bp realistic cost 看 attrition
- 如果 T1b 在 30bp 还有 alpha → fleet 合成 PEAD + T1b 可能 immediate go
- ~1 day eng
- **Operator pros**: cheap directional info, 可能 unblocks fleet immediately
- **Operator cons**: 已知 T1b year-inconsistent，30bp 后可能更糟

### Option E — Strategic reassessment (跟用户讨论)
- 大盘 review: 5 cycles + cycle11 + PEAD 这 6 周的工作整体方向
- 用户 directly weigh in on universe / cadence / long-only constraint / paid data budget
- **Operator pros**: alignment + new directional signal
- **Operator cons**: blocks tactical work until decision

### Option F — Universe expansion D1 single-axis test
- 78-股 → 200-股 expansion smoke
- 同一 cycle04 family setup
- 看 NAV correlation 跟 raw Sharpe trade-off
- **Operator pros**: kill D1 hypothesis 一次性
- **Operator cons**: 已 ruled out by roadmap v2 (although n=1)

### Option G — long-only relaxation discussion (requires explicit user-go, NOT executable until user authorizes)
- 跟用户讨论 short / margin / leverage boundary
- 最大潜在 unlock 但最大 invariant change
- **Out of scope until user signals interest**

**Operator recommended sequence** (NOT user-locked):
1. **Option A (default) + Option D 并行** for next 2 weeks (D 一次性 cheap directional)
2. After 2 weeks: if D 给出 T1b 30bp positive → consider fleet 合成 (Option B prep)
3. ~6/15 mid-point: re-assess if no GREEN signal in TD30
4. ~7/30 first TD60 (options paper) → branch decision

📝 **用户 annotation §10**:
> [7 个 option 你想动哪个？多个并行 OK 吗？是否要 reorder operator 推荐 sequence？]

---

## §11 给用户的 critical reflection questions

下面是我作为 operator 觉得用户最需要 weigh-in 的几个 directional question，请直接批注：

**Q1**: Trial 9 v2 是 mining 历史上唯一 forward init 的 diversifier-role candidate, 但 source cycle (#05) 是 7 个 Tier 1 R41 verdicts (PASS yaml hard blockers) **failing CLAUDE.md project invariant** (OS walk-forward window-mean rule, 后来 2026-05-02 deprecated QQQ rule 才 unlock 它). **回头看，是不是 CLAUDE.md QQQ deprecation 太就便 Trial 9 forward init?**

📝 **用户 Q1**:
> [...]

**Q2**: PQS 当前 long-only no-short 不变量是 absolute, but Clarke-de Silva-Thorley 2002 paper 证明长期 alpha 上限 ~0.45-0.55 TC ceiling. **用户对调整 long-only invariant 的 stance**? 
- A) Never
- B) Conditional (specific regime / specific candidate)
- C) Gradual (covered options first, then bond futures, ...)
- D) 等 fleet 合成 evidence 再讨论

📝 **用户 Q2**:
> [...]

**Q3**: cycle04-11 6 周 0 nominee 的实证，相比 Trial 9 v2 forward init 的 7-week-old data, 哪个证据 weight 更高?
- A) Cycle 0-nominee n=8+ 证 framework infeasible → 必须改架构
- B) Trial 9 v2 forward 数据更新 → 看 60 天结果再决定
- C) 两个 evidence 互补 → 同时改

📝 **用户 Q3**:
> [...]

**Q4**: PEAD Path 1 SUE 是 Sharpe 1.06 / MaxDD -7.6% 的 standout, **但 alpha shape = low CAGR defensive (5.5% vs SPY 13%)**. 三个可能 fleet 用法:
- A) PEAD 50% + T1b 50% (high CAGR + low DD)
- B) PEAD 100% as standalone defensive (accept low CAGR)
- C) PEAD + RP risk parity 多 candidate (Trial 9 v2 + future winners)

📝 **用户 Q4**:
> [...]

**Q5**: 2026 sealed panel single-shot 纪律 — 当前 PEAD evidence-only forward soak 通过后,sealed eval **何时该消耗**? 
- A) 立即 (今天 PEAD trial 1 已 frozen)
- B) PEAD TD60 GREEN 后
- C) Fleet 合成框架 ready + 多 candidate aggregate verdict 后
- D) 永不 - sealed 留作绝对终 single-shot

📝 **用户 Q5**:
> [...]

---

## §12 用户随机 annotation 区

📝 **任何其它想说的**:
> [...]

---

## §13 Appendix — 完整 reference 列表

### Mining 历史 PRDs
- `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` (Track A)
- `docs/prd/20260428-candidate_fleet_allocator_prd.md` (Track B, paused at Step 5)
- `docs/prd/20260424-cycle07_to_fleet_master_prd.md`
- `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md` (cycle06+ v2)
- `docs/prd/20260505-taa_regime_allocation_framework_prd.md` (PRD-E, dormant)
- `docs/prd/20260501-two_stage_allocation_architecture_prd.md` (Phase C-PRD-1/2/3/4)
- `docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md`
- `docs/prd/20260514-pead_bundle_phase1_prd.md` (TODAY)

### Cycle 关键 closeout memos
- `docs/memos/20260426-research-cycle-2026-04-26-01_close.md` (G2.A fail)
- `docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md` (cycle #01)
- `docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md` (cap_aware #02)
- `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md` (cross-asset #04)
- `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md` (anchor-sensitivity #05, Trial 9 source)
- `docs/memos/20260506-cycle06_closeout.md` (v2 NAV-based)
- `docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md` (Track A retroactive fix)
- `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md` (Trial 3 NAV Red)
- `docs/memos/20260513-cycle10_closeout.md`
- `docs/memos/20260514-cycle11_smoke_execution_artifact.md` (cycle11 close-fallback bug)
- `docs/memos/20260514-t2b_cycle11_resmoke_v2_realistic_cost.md` (DEPRECATED post-fix)
- `docs/memos/20260514-pead_bundle_phase1_close.md` (TODAY)

### 自审 + 数据 integrity 关键 memos
- `docs/checkpoints/20260430-self_audit_methodology.md` (4-round audit)
- `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`
- `docs/memos/20260512-trial9_diversifier_001_closeout.md`
- `docs/audit/20260507-beta_metric_path_bug_postmortem.md` (cycle07a P0 fix)
- `docs/audit/20260514-comprehensive_project_audit.md` (today's audit)

### 战略 + roadmap memos
- `docs/memos/20260429-post_audit_strategic_roadmap.md` v3
- `docs/memos/20260430-priority_realign_alpha_first.md` (P0→P1 demotion)
- `docs/memos/20260430-rcmv1_cand2_realized_correlation.md` (RCMv1+Cand-2 sibling-by-NAV evidence)
- `docs/memos/20260502-qqq_benchmark_deprecation.md` (CLAUDE.md QQQ rule revision)
- `docs/memos/20260513-post_cycle10_strategic_roadmap.md` (Roadmap v2 final)
- `docs/memos/20260514-cost_gate_revision_6x.md` (30bp baseline)

### 历史阶段 archive
- `docs/20260422-claude_md_phase_bc_history.md` (Phase B + early Phase C)
- `docs/20260424-claude_md_phase_e_history.md` (Phase E details)
- `docs/20260422-deep_mining_50round_final_synthesis.md`
- `docs/20260424-rcm_v1_final_synthesis.md`
- `docs/20260424-phase_e_final_synthesis.md`
- `docs/20260424-phase_e_post_cand2_final_synthesis.md`
