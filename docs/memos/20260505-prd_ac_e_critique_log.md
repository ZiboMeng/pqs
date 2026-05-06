# PRD-AC + PRD-E Critique Log

**Date**: 2026-05-05  
**Operator**: zibomeng (Claude Opus 4.7)  
**Authority**: User explicit-go 2026-05-05 ("先做 critique 有 issue 的话就做修订" + "记录这个修正的点 然后再做一遍 audit 如果还有需要修改的 一并修改")

记录 Round 1 + Round 2 audit 找到的 issues + 修订决定。修订后两 PRD 应清楚 align 用户原意 + 5.4 OOS discipline + CLAUDE.md invariants.

---

## PRD-AC (Mining Objective NAV-Based + Execution Policy)

### Round 1 issues

#### I1 🔴 Anchor 选择 over-strict (BLOCKER)

**位置**: §4.6  
**问题**: Default anchor = universe-equal-weight long-only baseline 跟任何 long-only top-N 自然 raw NAV correlation ~0.85+ (universe-bound floor). 用作 NAV-orthogonality anchor → 几乎所有 spec trip penalty → 0 archived 或 mining gaming penalty 选 factor-coverage-thin spec.  
**Fix**: §4.6 重写: SPY-residual NAV space (Option β) 作 default; γ (skip orthogonality) 作 Phase 4 smoke 决定; 显式 acknowledge "anchor 选择 50% 概率 fall back γ" risk.

#### I2 🟡 Search space scaling 偏乐观

**位置**: §4.5, §5.2  
**问题**: 加 6 cells 后 TPE 200 trials 可能 2/6 cell empty (per §5.2 acceptance "≥4/6"). 实际可能需要 400-600 trials → mining time +2-3x not +1.5-2x.  
**Fix**: §7 risks 加 "TPE 200 trials 可能不够 cover 6 cells, 备选 400 trials"; §5.2 acceptance 加 "若 explored < 4/6 cells, 增 trials 到 400 重跑".

#### I3 🟡 Backward compat regression §5.1 表述不严

**位置**: §5.1  
**问题**: "top-1 trial IC_IR identical to ≤ 4 decimal places" — TPE non-deterministic + factor data revision 让这条很可能 fail.  
**Fix**: §5.1 改成 "v1_legacy run on cycle #04 yaml clone reproduces cycle04 archive trials' IC_IR Spearman rank correlation > 0.95 over top-20".

#### I4 🟢 per-trial 22s 是 full panel; train-only ~15s/trial

**位置**: §2, §5.2  
**问题**: R3-AC-1 timeit 实际 panel n=4876, 不是 train-only n=3345. 真实 train-only mining time ~50min not 73min.  
**Fix**: §2 + §5.2 数字修正 22s → ~15-22s, 73min → 50-75min.

#### I5 🟢 holding_freq=daily 高成本风险 PRD §7 没列

**位置**: §7  
**Fix**: §7 加 risk row "holding_freq=daily 高换手 + 高成本可能让 NAV-Sharpe < weekly/monthly; cost_model commission/slippage representative for daily holding 没 verify; mitigation: smoke run with holding_freq=daily + cost_model 2x sensitivity".

#### I6 🟢 enable_sr_defer 区分性问题

**位置**: §4.5  
**问题**: 在 NAV trajectory 不 enter resistance zone 的 spec 上, enable_sr_defer=true 跟 false 等价 (defer activation = 0). TPE 在这种 spec 上区分不出两个 cell, sample efficiency 损失.  
**Fix**: §4.5 加 prefilter rule "enable_sr_defer 只 enable 在 spec 历史 train-only NAV trajectory 触发 ≥ N (e.g. 5%) defer 频率的 spec; 其他 spec hard-skip enable_sr_defer=true cell, 节省 TPE 100% 用在有意义 cell".

### Round 2 issues

#### I7 🔴 NEW BLOCKER — §5.3 R41 verdict 跟 CLAUDE.md invariant 冲突

**位置**: §5.3, §5.2 acceptance  
**问题**: R41 anti_sibling_policy v2.0 用 RCMv1+Cand-2 作 anchor; CLAUDE.md 明确 "RCMv1+Cand-2 will not calibrate new-framework gates". 用 R41 v2.0 作 cycle #06 acceptance gate = 把 RCMv1+Cand-2 当 calibration source → 违反 invariant.  
**Fix**: §5.3 cycle #06 dry-run acceptance 删除 R41 v2.0 verdict 引用; 改用 Track A temporal_split.yaml acceptance criteria (per-validation-year vs SPY/QQQ + concentration + beta + cost robustness) + Phase 4 smoke metrics (NAV-Sharpe / qqq excess / orthogonality vs SPY-residual anchor).

#### I8 🟢 NEW Minor — holding_freq schema mapping 不 explicit

**位置**: §4.5  
**问题**: PRD 写 `spec.rebalance_cadence`, 但 frozen_spec schema 实际 field 是 `rebalance.freq` (`core/research/frozen_spec.py:122`).  
**Fix**: §4.5 改成 "holding_freq → spec.rebalance.freq schema field"; 加 schema mapping 表 (PRD-AC search dim → frozen_spec yaml field).

#### I9 🟡 NEW R3 hole — train-only non-contiguous panel BacktestEngine 没 verify

**位置**: §6 Phase 2  
**问题**: partition_for_role(miner) 返回 non-contiguous panel (2017-12-29 → 2020-01-02 等 gap). BacktestEngine 跨 boundary 怎么 handle path-dependent NAV 没 verify. R3-AC-1 timeit 用 full panel 没 exercise non-contiguous boundary.  
**Fix**: §6 Phase 2 加 R3 task "verify BacktestEngine on train-only restricted panel produces NAV consistent with cycle04 archive trials' NAV (cycle04 mining used same partition); confirm boundary handle 不引入 artifact"; §5.1 backward compat 加 "v1_legacy 跑 cycle04 yaml clone NAV path-dependence reproducibility check".

---

## PRD-E (TAA Regime Allocation)

### Round 1 issues

#### I10 🔴 BLOCKER — Phase 3 hard gate 几乎必 fail

**位置**: §5.2 Phase 3  
**问题**: "Per-validation-year vs SPY positive ≥ 3/5" — TAA / 60/40 / Permanent Portfolio 在 BULL years 几乎 always underperform SPY. 5 validation years 含 2019 / 2021 / 2023 三个 long bull → 90%+ 概率 fail. PRD §7 risks 自己 acknowledge 但 §5.2 仍 hard gate → self-contradictory.  
**Fix**: §5.2 Phase 3 改 hard gates 到 risk-adjusted:
- "Calmar ≥ buy-hold SPY Calmar (CAGR / |MaxDD|)" — primary risk-adjusted metric (per I15)
- "MaxDD < SPY MaxDD across full period"
- "Per-validation-year, vs SPY positive ≥ 2/5 in BEAR/RISK_OFF regime years (2018, 2022 stress)" — regime-conditional outperform
- "Sharpe ≥ buy-hold SPY Sharpe" (secondary metric)

#### I11 🟡 Round 1 BLOCKER 2 demote → wording fix

**位置**: §3 Non-goals + §5.2 Phase 3  
**问题**: §3 "不 ship forward observation runner" 跟 §5.2 "eligible for forward observation freeze" wording ambiguous.  
**Fix**: §3 + §5.2 + §10 explicit say "PRD-E1 (this PRD) = research framework, PRD-E2 (separate, gated on PRD-E1 success) = forward observation runner integration"; "Phase 3 pass = candidate ELIGIBLE for forward freeze, but actual freeze 需要 PRD-E2 wire forward runner schema".

#### I12 🟡 Phase 1 "auto vs manual ≥ 60%" 阈值 arbitrary

**位置**: §5.2 Phase 1  
**问题**: 60% 没 justification; manual 自己是 heuristic 不是 ground truth.  
**Fix**: §5.2 Phase 1 改 "manual + auto regime label 分布 shape similar (KL divergence < 0.5 OR Hamming distance < 30%)" + "high disagreement 不阻止 Phase 2 但触发 user-go review".

#### I13 🟢 DEFAULT_TAA_RULES_V1 没 cite source / 没 explore minimum viable

**位置**: §4.3  
**Fix**: §4.3 加 source citations (60/40 portfolio convention, Permanent Portfolio convention, Swensen "Unconventional Success" 30/30/20/20 framework); 加 minimum viable variant DEFAULT_TAA_RULES_V0_MINIMAL = {BULL: 60/40, RISK_OFF: 30/70} 二档作 sanity baseline.

#### I14 🟢 "regime classifier 100% reusable" 略夸大

**位置**: §4.1  
**问题**: R3-E-1 verify 的是 RegimeDetector class 方法存在, 没 hands-on verify .classify_series 输出 schema 跟 manual_regime_labels 兼容.  
**Fix**: §4.1 改 "regime classifier reusable with thin wrapper (~30 lines) for schema alignment"; §6 Phase 1 加 task "RegimeDetector.classify_series schema verification + wrapper if needed".

### Round 2 issues

#### I15 🟢 NEW Minor — Sharpe vs Calmar 选哪个 hard gate

**位置**: §5.2 Phase 3  
**问题**: Round 1 I10 fix 建议 Sharpe; 但 Calmar = CAGR / |MaxDD| 更直接 capture diversifier role 的 risk-management 价值 (TAA 主要 selling point 是 DD 控制).  
**Fix**: §5.2 Phase 3 改 primary metric 从 Sharpe 到 **Calmar** (CAGR / |MaxDD|); Sharpe 作 secondary metric 仅 informational.

#### I16 🟢 NEW Minor — Regime detection cadence 设计选择不 explicit

**位置**: §4.4  
**问题**: PRD 没 say regime label 是 daily 计算 vs monthly cadence. daily = 立即响应 + 高 turnover; monthly = 低 turnover + mid-month regime change 不响应.  
**Fix**: §4.4 explicit choose **monthly cadence** (跟 rebalance cadence align); §7 risks 加 "mid-month regime change 不立即响应; mitigation: smoke run with daily cadence variant 看 NAV difference 是否 material".

---

## 修订实施

两个 PRD 单一 commit 修订, 之后 push. Round 1 + Round 2 + Round 3
audit total 20 issues addressed:

### Round 3 NEW issues (post round-2 revision audit)

#### I17 🔴 NEW BLOCKER (PRD-E) — validation set BEAR/RISK_OFF year 数学不 well-defined

**位置**: §5.2 Phase 3  
**问题**: I10 fix 写 "vs SPY positive ≥ 2/5 in BEAR/RISK_OFF regime years",
但 `temporal_split.yaml` validation_years 5 个里只有 2018 是 BEAR
(rate_hike_bear), 其他 4 个全是 BULL (normal_bull / liquidity_mania /
ai_narrow / current_market). "≥ 2/5 in BEAR/RISK_OFF" 实际 sample 只 1
year, gate 不 well-defined.  
**Fix**: §5.2 Phase 3 改成 "2018 vs SPY positive (HARD; single BEAR
validation year)" + "stress slice MaxDD ≤ 25% (covid_flash + rate_hike_2022,
BEAR/RISK_OFF analogues from train years)" + 删除 raw vs-SPY-positive-
across-BULL-years gate (TAA 结构性 underperform).

#### I18 🟡 NEW (PRD-AC) — R41 Tier 2 + Track A pass edge case

**位置**: §5.3  
**问题**: PRD §5.3 删 R41 v2.0 verdict 作 gate, 但没 explicit 处理 spec
passing Track A + Phase 4 smoke gates BUT R41 informational = Tier 2
(sibling-by-NAV) 怎么算 nominee.  
**Fix**: §5.3 加 "I18 fix: R41 Tier 2 + Track A pass spec counts as
nominee; closeout memo surface R41 informational verdict; user
directional decision at Track D promotion time".

#### I19 🟢 NEW Minor (PRD-AC) — SPY-residual β computation method 没 specify

**位置**: §4.6  
**Fix**: §4.6 explicit β = train-only full-period OLS (use existing
`_ols_beta` helper); document β value in archive per trial.

#### I20 🟢 NEW Minor (PRD-AC) — Cross-asset spec 不适用 SPY-residual anchor

**位置**: §4.6  
**问题**: SPY-residual 假设 spec-vs-SPY beta meaningful; cross-asset spec
beta ~0.3-0.5, residual 大部分是 cross-asset alpha 跟 SPY-bound floor 无关.  
**Fix**: §4.6 加 spec-class-conditional anchor: cross-asset spec (>30%
non-equity weight) 默认 skip SPY-residual orthogonality, 保留其他 NAV
gates; Phase 4 smoke decide.

---

### 全部 20 issues addressed

修订后 PRDs:
- 20 issues 全部 address (Round 1 = 14, Round 2 = 4, Round 3 = 4 — 12+4+4 actually = 20 但 round 1 = 6 in PRD-AC + 8 in PRD-E? let me recount)

Actually accurate counts:
- Round 1: I1-I6 (PRD-AC) + I10-I14 (PRD-E) = 11
- Round 2: I7-I9 (PRD-AC) + I15-I16 (PRD-E) = 5
- Round 3: I18-I20 (PRD-AC) + I17 (PRD-E) = 4
- **Total: 20 issues addressed**

- BLOCKERs: I1 (anchor), I7 (R41 invariant), I10 (TAA hard gate), I17
  (validation BEAR coverage) — 4 BLOCKERs all fixed
- R3 hole: I9 (boundary verification) — Phase 2 explicit task
- Minor: I3-I6, I8, I11-I16, I18-I20 — inline edits

修订 effort: ~半天 (不动代码, 只改 docs).

### Round 4 audit recommendation

PRD-level critique 进行 3 rounds 后剩余 issue 都是 minor/wording, 进入
diminishing returns. Phase 1 implementation kickoff 才是 next R3 layer
(写代码 + 跑 verify). 不再 round 4 critique 同 PRD draft (would yield
0-1 minor issues per round w/ effort > value).
