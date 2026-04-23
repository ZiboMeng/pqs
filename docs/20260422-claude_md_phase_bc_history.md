# CLAUDE.md Phase B/C History Archive (extracted 2026-04-22)

This file contains content extracted from `CLAUDE.md` during its 2026-04-22
shrink pass. All content below was previously inline in CLAUDE.md; it has
been moved here because it is historical narrative (per-round changelogs,
completed work tables, pre-P0.1-fix metrics, PRD v2→v3 revision notes) that
future ralph-loop iterations do not need to re-read on every turn.

**Active contracts** (invariants, QQQ rule, pricing semantics, data
pipelines, factor registry, multi-TF timing, notify, current TODO) remain
in CLAUDE.md.

The content below is preserved verbatim for audit and reference. Section
headers use the original structure so searches like "LLM-Round 15" or
"Round 12" still resolve to the original prose.

---

## Part A — Phase B / pre-P0.1-fix snapshot (from CLAUDE.md §"Current Best Strategy" + "Key Discoveries")

### Current Best Strategy (real open prices, target_vol=0.25)

⚠️ **以下数字产出于 P0.1 fix 前（`apply_extra_shift=True` 时代）。** 修复
double-lag bug 之后信号对应的数据窗口变了，同参数在当前 codebase
下不再复现这些 OOS 数字。Round 1 Ralph-loop mining（80 trials ×
1800s，capital=$100k，`post-2026-04-20-capital-100k` lineage）得到的
OOS IR 分布是 -0.709 到 -0.113，无一 trial 过 OOS 门槛。需要重新
搜索参数空间后才能获得 post-fix 下的"current best"。

- multi_factor: CAGR 19.0%, Sharpe 0.98, MaxDD -19.7%, IR 0.33
- Params: RS=0.30, momentum=0.30, quality=0.25, market_trend=0.10, pv_div=0.05
- OOS IR=0.40, pass_rate=70%, holdout excess=+14.4% vs SPY
- **vs QQQ: CAGR 19.0% > QQQ 15.9% ✅ | Holdout 47.7% > QQQ 40.5% ✅ | OOS avg excess +5.3% ✅**
- All robustness checks pass (regime, cost, param, stress, subperiod, holdout)

### Key Discoveries (Phase B, Loop 1-50)
1. Real open price reveals 5% CAGR overestimation vs close approximation
2. target_vol=0.25 (was 0.15) breaks OOS bottleneck — pass rate 0%→49%
3. Vol_parity harmful for multi_factor (already has low_vol factor)
4. Relative strength + momentum are dominant alpha sources
5. Kill switch config must match risk.yaml — threshold mismatch caused 37% paper-bt divergence

---

---

## Part B — Phase C completion tables (historical, work shipped)

Extracted from CLAUDE.md §"Partially Done / Fixed in Phase C / Fixed in
Intraday Sprint / Remaining / Constraint Completion Sprint / P0/P1 收口闭环".
These tables describe work completed during Phase C and the Intraday Sprint.
They were inline in CLAUDE.md as a status dashboard; after the sprint completed
the information stopped changing and is now reference-only.

#### Partially Done

| Feature | Evidence | Gap | Verification Source |
|---------|----------|-----|-------------------|
| Paper-BT consistency < 0.2% | `manual_verified` | No automated test | Manual run: +18.0% vs +18.2% |
| Left-side zero-harm | `manual_verified` | No automated test | Manual backtest: IR 0.327→0.328 |
| Factor generator → mining | `claimed_not_verified` | MFS computes internally | factor_generator.py unused by mining |
| left_side_trading config | `claimed_not_verified` | risk.yaml config not consumed | No code reads cfg.risk.left_side_trading |
| Promoted strategies count | `manual_verified` | No test checks DB state | archive.db promotions table |

#### Fixed in Phase C (formerly Missing)

| Feature | Status | Iteration |
|---------|--------|-----------|
| MultiFactorStrategy unit tests | ✅ `test_verified` (16 tests) | C-1 |
| Paper-BT consistency test | ✅ `test_verified` (4+1 integration) | C-2, C-8 |
| Commission double-counting bug | ✅ Fixed + 5 tests | C-3 |
| Cost robustness silent fallback | ✅ Fixed + 1 test | C-4 |
| Replay open price bug | ✅ Fixed (real open_df loaded) | C-5 |
| Left-side config wiring | ✅ `test_verified` | C-6 |
| QQQ outperformance validation | ✅ `test_verified` (2 integration) | C-7 |
| strict_match (share_mode configurable) | ✅ `test_verified` | C-8 |
| Intraday live mode execution | ✅ Uses run_day_daily | C-9 |
| Real XGBoost | ✅ XGBoost 3.2.0 | C-10 |
| Permutation importance | ✅ OOS permutation | C-11 |
| Leakage validation tests | ✅ 3 automated tests | C-12 |
| Factor candidate schema | ✅ Structured YAML | C-13 |
| Full funnel walkthrough | ✅ 1 candidate complete | C-13 |
| New factor families (overnight+breadth) | ✅ 5 new factors | C-14 |

#### Fixed in Intraday Sprint (post Phase C)

| Feature | Status | Notes |
|---------|--------|-------|
| Intraday persistence (5 tables) | ✅ `test_verified` (9 tests) | save_intraday_bar, checkpoint, idempotency |
| Replay uses intraday bar path | ✅ Code verified | 60m bars → run_multi_day; fallback to daily |
| IntradayBacktestEngine.run_multi_day() | ✅ `test_verified` (10 tests) | Multi-asset, NaN-safe, missing/stale bars handled |
| Intraday report | ✅ Code verified | fills summary, equity path, drawdown, diagnostics |

#### Remaining (all low-medium priority)

| Feature | Impact | Notes |
|---------|--------|-------|
| strict_match 10bps precision | Medium | Currently 500bps; needs BT vectorized→incremental unification |
| True **realtime** intraday live (盘中实时) | Medium | Live now runs bar-by-bar against cached store data (约束 1 done); real-time feed still missing |
| SHAP attribution | Low | Permutation importance (C-11) is functional alternative |
| QQQ check in mining evaluator | Low | Validated in tests (C-7), not auto-checked per-trial |
| Parallel mining | Low | Single-threaded works; parallelism needs DB lock design |
| Computation caching | Low | Regime/factor outputs recalculated each run |

#### Constraint Completion Sprint (2026-04-20)

| Constraint | Status | Evidence |
|-----------|--------|----------|
| 约束 1 — intraday live bar-by-bar runtime | ✅ done | `run_paper.py --mode live` now routes through `PaperTradingEngine.run_day_intraday` → `IntradayBacktestEngine.run_multi_day` with per-bar `on_bar_complete` / `skip_bar_fn` / `target_wts_fn` hooks. `run_day_daily` fallback only fires when NO intraday bars for the day. Idempotent: re-running on same (run_id, date) is a no-op. Checkpoint recovery works. Tests: `tests/unit/paper_trading/test_bar_by_bar_runtime.py` (8 tests). Remaining: real-time bar feed (below) |
| 约束 2 — factor_generator ↔ mining/execution | ✅ done | Single source of truth is now `core/factors/factor_registry.py` (PRODUCTION_FACTORS / RESEARCH_FACTORS / RESEARCH_TO_PRODUCTION_MAP). `MultiFactorStrategy.__init__` gates factor_weights against PRODUCTION_FACTORS (warn + drop on unknown). `MultiFactorSpace.__init__` asserts its tuned factor set equals PRODUCTION_FACTORS (fail fast on drift). factor_generator docstring documents the promotion path. Tests: `tests/unit/factors/test_factor_registry.py` (10 tests) — includes drift detector that compares factor_generator outputs against RESEARCH_FACTORS |
| 约束 3 — multi-TF timing/execution repositioning | ✅ done | Module docstring + new `TimingDecision` dataclass + `decide_timing()` API formalize the contract: 60m/30m = context/direction check, 15m/5m = trigger/defer only (cannot flip direction). Long-only invariant enforced: `effective_weight ≥ 0` for any TF combo. Legacy `evaluate_cross_tf_signal` kept as back-compat shim. New script `scripts/validate_timing_value.py` measures timing VALUE (entry bps vs day mean, defer behavior, scale distribution) instead of direction-voting CAGR. Tests: `tests/unit/intraday/test_timing_decision.py` (14 tests) |
| P1 闭环 — 生产迁移 + E2E + R3 + R6 | ✅ done | `run_multi_tf_backtest.py` migrated off `evaluate_cross_tf_signal` → uses `decide_timing` + new `TimingAggregator` (replaces `AttributionAggregator` in that script). `PaperTradingEngine.run_day_intraday` accepts `timing_provider` parameter. `run_paper.py --use-timing` flag wires it end-to-end. Timing thresholds moved to `config/risk.yaml::intraday_timing` (schema `IntradayTimingConfig`) + `TimingThresholds.from_config()`. Live short-circuit now checks `all(df.index[-1] <= cp_last_bar_ts)` across all symbols — robust to bar growth between runs. New `make_timing_target_provider(multi_bars, base_weights, thresholds)` helper builds the closure. E2E integration test `tests/integration/test_daily_to_timing_e2e.py` (6 tests) verifies: every bar drives decide_timing; bearish 15m defers all bars; idempotent re-run with timing; bar-set growth resumes without short-circuit. Tests: 937 → 943 passing. |
| Mining 前最后收口 (2026-04-20) | ✅ done | 4-item pre-mining closure. **1/4** (`1f76a94`): intraday ghost cleanup parallels daily (P1.6) — `IntradayBacktestEngine` tracks per-symbol stale-bars, liquidates after threshold (default 13 bars ≈ 2 RTH days of 60m). PaperTradingEngine owns `_intraday_stale_counts` so multi-day halts cumulate. **2/4** (`3a745f9`): archive lineage tagging — `MiningArchive(lineage_tag=...)` stamps every trial/promotion; legacy rows inherit `pre-2026-04-20`; leaderboard filters by lineage. QQQ gate columns also added to archive. **3/4** (`57ef662`): `StrategyConcentrationConfig` under `config/risk.yaml::strategy_concentration` (deliberately separate from `position_limits`); all 4 production paths (run_backtest/run_paper/run_multi_tf_backtest/mining) read `soft_cap_max_single` + `concentration_warn_threshold` from config — knobs are no longer dead. **4/4** (`b917d31`): QQQ semantics aligned at acceptance/report layer — `AcceptanceResult` extended with `qqq_excess_return` + `passed_qqq_gate`; `acceptance_check(qqq_benchmark=...)` mirrors mining evaluator's gate; master report renders QQQ row with pass/fail badge. Run_backtest passes qqq_close automatically. Tests 999 → 1005 passing (+25 total across 4 items). |
| P0/P1 收口闭环 (2026-04-20) | ✅ done | 8-item closeout before intraday mining. P0.1 (`64501e7`): `MultiFactorStrategy` default `apply_extra_shift=False` (was True — T-2 stale); 4 production scripts explicit. P0.2 (`38bbd91`): `BarStore.load` yfinance fallback provenance `first_bar_ts` fixed (typo + wrong branch semantics). P0.3 (`f7ff260`): new `core/data/vix_loader.py` with `strict` (live raise) vs `lenient` (research warn) modes; all 4 scripts migrated off `pd.Series(20.0, ...)` fallback. P0.4 (`32cd3b1`): QQQ hard gate in evaluator — `_check_qqq_gate` computes full/holdout/OOS-proxy excess vs QQQ; fail → tier D. P0.5 (`8729c38`): `integer_shares = not cfg.risk.position_limits.allow_fractional_shares` threaded into PaperTradingEngine/BacktestEngine/MiningEvaluator. P1.6 (`99dae9e`): ghost position cleanup — `BacktestEngine` tracks `stale_days_count` per symbol, force-liquidates at `last_valid_close` after threshold. P1.7 (`3cc5dbb`): `validate_timing_value.py` extended with holding-path + cost + VERDICT tag (current reading: POSITIVE +3.26 bps/event). P1.8 (`74818ba`): `intraday_fills.is_eod` column separates EOD force-close residuals from intraday decisions. Tests 943 → 980 passing (+37). |

---

---

## Part C — Ralph-Loop Findings (2026-04-20+) — LLM-Round 1-22 + Round 1-12 detailed changelogs

All per-round detailed changelogs from CLAUDE.md §"Ralph-Loop Findings
(2026-04-20+)". These are narrative records of each ralph-loop round —
useful for audit/forensics but not required context for running new
iterations (the per-round log continues in `docs/20260420-ralph_loop_log.md`).

## Ralph-Loop Findings (2026-04-20+)

### LLM-Round 22 — Layer 1 admission tool + v2 framework（用户 v1 critique 后）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-22`
**用户 R21 critique**: 分层错位 —— v1 把 alpha / Sharpe / COVID MaxDD
塞进 admission，造成 survivorship bias。应分 4 layers:
(1) Tradable Universe objective admission
(2) Risk Exposure Labels (非 filter)
(3) Priority Buckets (portfolio 构造层)
(4) Portfolio Constraints (weight-level)

**改动**:
- 新 `scripts/universe_admission_screen.py` (~280 行) 实现 **v2 Layer 1
  only** —— 完全客观准入规则，**无 alpha/performance-based 筛选**:
  - Security type 白名单（US common stock; reject 23 known ETF/leveraged
    tickers）
  - Listing ≥ 504 trading days (2y); ≥ 252d discovery
  - Price floor: > $5 extended / > $10 core
  - Liquidity: ADV60 dollar volume > $20M extended / > $50M core + 60d
    持续性 80%
  - Data completeness: SPY overlap ≥ 252d + < 10% 252d NaN
  - Tier 分级: CORE / EXTENDED / WATCH / REJECT + rejection reasons
- Dry-run test（未动 config）:
  - Current 32-symbol universe: 25 REJECT (ETF/leveraged) + 7 CORE
    (Mag7 common stocks) —— Layer 1 **正确分离** equity 和 ETF
  - 60-symbol probe list (R21 non-tech + Mag7 + 21 additional large
    caps): 60/60 CORE —— 无 over-filtering

**R21 v1 vs R22 v2 对比** (用户 critique 集成):

| 项 | v1 | v2 |
|---|---|---|
| History | ≥ 5y hard | ≥ 2y hard; ≥ 5y label |
| Liquidity | "avg volume × price > $50M" (模糊) | ADV60 $20M extended / $50M core + 持续性 |
| Security type | blacklist (SQQQ) | whitelist US common stock |
| Alpha admission | `α > 3%` hard gate | **Layer 3 priority bucket, not admission** |
| Sharpe admission | `> 0.5` hard gate | **Layer 3** |
| COVID MaxDD filter | `< -60%` drop | **删** (regime-specific hardcode, 过拟合) |
| Sector count | ≥ 3 每 sector 强制 | target coverage, 非强制 |
| Single sector | ≤ 8 symbols 数量限 | + **weight limit** 暴露控制 |
| QQQ exposure | 仅 SPY beta | **SPY + QQQ 双 beta/R²** |
| 新增 | — | 证券类型白名单 / price floor / mcap floor / rolling consistency |

**Workflow 状态** (R21 user-prescribed 5-step):
1. ✅ v1 criteria 提案 (R21)
2. ✅ user critique v1 → 指导 v2
3. ⏳ **等用户 confirm v2 framework**
4. [ ] R23 tooling run: broader admission screen (S&P 500 或 all-local 25340 tickers)
5. [ ] user confirm candidate list → config 改动

**PRD §13.2 halt 条件**: pytest 1109 / 1 PRODUCTION promote (R15 auth) /
26 candidates / 无 invariant 违反 / **universe config 未改（等 v2 approval）**

**下轮建议**:
- A: **等用户 v2 approval**（本轮工具已就绪）
- B: 同时做 R19 report §8 open question #2 (MR ensemble single-factor
  test)，§13.2 safe 不需新授权

### LLM-Round 21 — 非 tech alpha 源发现 + universe 筛选标准提案

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-21`
**用户新指令**: "可以给config授权 进行universe扩容 首先跟我确认扩容的筛选
标准 然后执行之后 扩容的candidate要给我确认"

**改动**:
- 扩展 `universe_alpha_diagnostic.py` 加 `--symbols` CLI flag 接受自定义
  list + `--out-name` 定制 artifact 名称
- 在 33 个非 tech candidates 上跑 audit（ABBV/UNH/LLY/JNJ/REGN/VRTX/
  ISRG/PG/KO/COST/WMT/PEP/JPM/V/MA/BAC/PNC/USB/BRK-B/CAT/HON/GE/BA/
  LMT/RTX/XOM/COP/PSX/NEE/DUK/DIS/NFLX/CMCSA）
- 写 universe 扩容筛选标准提案（本段）

**R21 audit 结果**（非 tech universe, 2018-01-01 至今）:

| Category | Count | Notable symbols |
|---|---:|---|
| **ALPHA_GENERATOR** | **5** | MA(+3.7% α), **CAT (+9.9%)**, GE, RTX (+12%), VRTX (+7.7%) |
| **DIVERSIFIER** | 12 | **LLY (α +24.8% Sharpe 1.07)**, **COST (+13.3% Sharpe 1.00)**, REGN, ABBV, LMT, PEP, KO, WMT, PG, DUK, JNJ, NEE |
| MARKET_LIKE | 15 | — |
| PURE_BETA | 1 | BA (α -12%) |

**重大发现**:
- **LLY α +24.8%/yr Sharpe +1.07** (pharma, β=0.66) — **比任何 Mag7 还强**
- COST α +13.3% Sharpe +1.00 (staples, β=0.69)
- 多数 Mag7（AAPL/GOOGL/AMZN）α ≈ 0 而 non-tech 里有 17 个 KEEP
  candidates

**累计 alpha 候选池** (R20 + R21): 6 tech + 17 non-tech = **23 symbols**
应进最终 expanded universe

**用户 R21 workflow** (5-step):
1. ✅ 筛选标准提案（本轮）
2. ⏳ **待用户确认标准**
3. 执行完整 broader audit → candidate list
4. ⏳ 待用户确认 candidate list
5. config 改动（risk.yaml / universe.yaml）

**提议筛选标准** (see also ralph_loop_log.md §R21):

Primary filters: daily data ≥5y / avg daily ADV > $50M / 不在 blacklist /
β 可计算

Alpha 准入（满足 ONE）:
- ALPHA_GENERATOR: β∈[0.7,1.3] AND α>3%
- BETA_PLUS_ALPHA: β>1.3 AND α>3%
- HIGH_SHARPE_DIVERSIFIER: β<0.7 AND Sharpe>0.5 AND α>0

排除: PURE_BETA / 高 r² vs SPY 无 alpha / 2020 COVID MaxDD < -60% 但非
ALPHA_GENERATOR

Sector diversification: 每个 GICS ≥3 symbols, 单一最多 8 ；targetsize 60-80

**PRD §13.2 halt 条件**: pytest 1109 / 1 PRODUCTION promote (R15 auth) /
26 LLM candidates / 无 invariant 违反。**待用户确认 universe 扩容标准后
方可进入实际 config 改动**

**下轮待做**:
- 用户确认上述标准后: R22 执行 broader audit （~100 candidates across
  all sectors/cap tiers）产出 candidate list
- 否则: R22 做 report §8 open question #2（MR ensemble single-factor
  test，不需新授权）

### LLM-Round 20 — universe alpha/beta 诊断（empirical audit of user's thesis）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-20`

**改动**:
- 新 `scripts/universe_alpha_diagnostic.py` —— CAPM beta + annualized
  alpha 对每个 universe 符号计算，按 (β, α) 分类为 PURE_BETA /
  MARKET_LIKE / DIVERSIFIER / ALPHA_GENERATOR / BETA_PLUS_ALPHA
- 在 32-symbol universe 上跑（2018-01-01 → 2026-04-18）
- 产出 `data/ml/universe_alpha_diagnostic.csv` + `universe_alpha_summary.json`
- 更新 `docs/20260421-llm_phase_blocker_report.md` §6.1.1 写入 empirical findings

**核心发现** — 用户 R19 direction 得到**定量 validation**:

| Category | Count | Symbols |
|---|---:|---|
| **ALPHA_GENERATOR** (β∈[0.7,1.3], α>3%) | **2** | MSFT, QQQ |
| **BETA_PLUS_ALPHA** (β>1.3, α>3%) | 4 | SOXL, NVDA, TSLA, META |
| **MARKET_LIKE** (β∈[0.7,1.3], α≈0) | **18** | SPY, AAPL, GOOGL, AMZN, XLK/XLC/XLY/XLF/XLI/XLE/XLB/XLRE/XLV/SCHD/MTUM/QUAL/VLUE/USMV |
| **DIVERSIFIER** (β<0.7) | 7 | XLU, XLP, SLV, GLD, SHY, IEF, TLT |
| **PURE_BETA** (β>1.3, α≤0) | 1 | **TQQQ** (α -20%/yr) |

**Summary**: **只 6/32 (19%) 符号产生 α > 3%**，且**全部是 tech/semis**
（MSFT/QQQ/SOXL/NVDA/TSLA/META）。**56% (18/32) 是 pure market_like**
—— AAPL/GOOGL/AMZN 尽管是 Mag7 但 α 接近 0，sector ETFs 多数
r² > 0.7 vs SPY（就是 beta proxy）。**7 个 diversifiers 全是 macro/factor
ETFs**，个股里没有 low-β 分散源

**Universe redesign 建议** (由 audit 推导，写入 blocker report §6.1.1):
- 丢弃 TQQQ（α 负）、考虑丢 SPY-proxy ETFs（XLK/XLC/XLY 高 SPY 相关）
- 扩容行业: healthcare (ABBV/UNH/LLY), staples (PG/KO), industrials
  (CAT/HON), financials ex-mega (PNC/USB), energy (COP/PSX)
- Mid-caps 作 alpha 源 (classical factor literature 支持)

**PRD §13.2 halt 条件**: pytest 1109 / 1 PRODUCTION promote (R15 auth) /
26 candidates / 无 invariant 违反。继续。

**下轮建议**:
- **A**: 实验性扩容 universe 加 5-10 个非 tech symbols（需 risk.yaml 或
  universe.yaml 改动 + 用户签核）
- **B**: 继续 R19 report §8 open questions（wider mining / MR ensemble
  single-factor promote）
- **C**: 跑跟 Audit 的 ALPHA_GENERATOR 组合测试（2-factor MSFT+QQQ long
  or 6-symbol alpha cluster long）

### LLM-Round 19 — blocker report 草稿 v0.1

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-19`

**改动**:
- 新 `docs/20260421-llm_phase_blocker_report.md` (~250 行) —— PRD §10 criterion
  #4 要求的 blocker report 初稿（`reports/` 是 gitignore，移到 `docs/`）
- **用户 R19 指令** (2026-04-21): "后面对于universe肯定要进行优化和扩充
  当前的暴露太偏大科技 需要进行筛选 来实现alpha正值 而不是纯赚beta" ——
  确认 §6.1 是 primary blocker resolution path；report §1 Executive
  Summary + §6.1 已更新为 **USER-VALIDATED, HIGHEST PRIORITY**
- 草稿 v0.1 整理 R1-R18 证据链，列 4 lines of evidence + drawup deep-dive
  + 6.1-6.4 推荐的 post-LLM-phase 下一步（universe expansion / 新数据源
  / 非线性 ensemble / pairs/arb 策略）+ 8 个 R20-R30 待解 open questions

**Blocker report 结构**:
1. Executive Summary
2. PRD §10 goals status
3. 4 lines of evidence:
   - R6 XGBoost cross-signal (OOS R² 负)
   - R15 composite MaxDD (best -50.87% 超过 -20% invariant)
   - R16 mining post-promotion (0/83 trials pass OOS)
   - R18 calendar anomalies (IC ~0)
4. Best candidate deep-dive: drawup 4-method consensus + 最终 mining 结果
5. Why thresholds should NOT be lowered (per user R17 指令)
6. Recommended next steps (out of LLM-phase scope)
7. LLM phase deliverables (7 tools + 26 candidates + 1 promoted)
8. Open questions for R20-R30
9. Appendix: 全候选列表

**PRD §10 midpoint (R19 / 30)**:
- #1 ✅ (R15 promotion)
- #2 ❌ blocked (0/83 trials pass OOS threshold)
- #3 ✅ (lineage_tag + YAML archive)
- **#4 草稿 v0.1 就位** (R19) — 剩余 R20-R29 迭代修订 + R30 finalize

**PRD §13.2 halt 条件**: pytest 1109 / 1 PRODUCTION promote (R15 auth) /
26 candidates / 无 invariant 违反。继续。

**下轮建议**:
- **A**: 运行 R19 report §8 open question #1 的实验 (80+ trial wider mining
  run, budget 3600s) 看 OOS barrier 在更大 sampling 下是否松动
- **B**: 做 R19 report §8 open question #2 实验 (MR ensemble 作为 single
  registered factor 直接 promote 测试)
- **C**: 现在 compile 本 report 到 final 版 (premature — 应该等 R29 再 finalize)

### LLM-Round 18 — Topic LLM-9 event/calendar（菜单覆盖完成）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-18`

**改动**:
- 新 `research/llm_candidates/round_18/` + 3 calendar-proxy candidates
- 覆盖 §9 菜单 LLM-9：event/calendar direction（最后未覆盖 topic）

**候选** (3):
- `monday_effect_mean_63d` — 63d rolling Monday returns
- `monthend_last5d_mean_63d` — 63d rolling returns in last 5 days of month
- `monthstart_first5d_mean_63d` — 63d rolling returns in first 5 days of month

**Funnel 结果** (15-sym):

| factor | IC mean | IC IR | verdict |
|---|---:|---:|---|
| monday_effect_mean_63d | — | — | ARCHIVE (n=0 sparse sampling) |
| monthend_last5d_mean_63d | -0.002 | -0.01 | ARCHIVE (~0 IC) |
| monthstart_first5d_mean_63d | -0.038 | -0.10 | ARCHIVE |

**研究确认** ⭐ —— **Mag7-heavy universe 下 calendar anomalies 几乎无信号**。
与预期一致：大盘股效率极高，classical calendar effects（Monday effect,
turn-of-month effect）在该 universe 被市场 arbitrage 掉。这是对 R15-R17
"factor space 不足以产生 alpha" 结论的第**四个**独立数据点:
- R6 XGBoost: 7/43 LLM top-20 但 OOS R² 负
- R15 composite: best MaxDD -50.87% 未能过 -25% invariant
- R16 mining: all trials OOS IR < 0.20 threshold
- **R18 calendar effects: IC ~0 across 3 candidates**

**菜单覆盖完成**:

| Topic | 轮 |
|---|---|
| LLM-1 candidate scaffold | R1 |
| LLM-3 intraday | R2 |
| LLM-4 benchmark-relative | R4 |
| LLM-5 XGBoost cross-signal | R6 |
| LLM-6 orthogonalization | R10/R11 |
| LLM-7 regime-conditioned | R7/R8 |
| LLM-8 interaction mining | R7 |
| LLM-9 event/calendar | **R18** |
| LLM-10 path-shape | R13 |
| LLM-11 cross-sectional | R14 |
| LLM-12 first promotion | R15 (user-auth) |

**PRD §13.2 halt 条件**: pytest 1109 / 1 PRODUCTION promote (R15 auth) /
26 cumulative candidates / 无 invariant 违反。继续。

**下轮建议**（菜单已覆盖，剩余 12 轮）:
- **A (推荐)**: 开始整理 R30 blocker report 的 data compilation。R15-R18
  已有核心证据，R19-R29 可以是"补充实验 + 数据压制" (e.g., try wider
  universe simulation, different rebalance cadence)
- **B**: 跑更大 mining run (80+ trials, 3600s budget) 确认 OOS barrier 在
  more sampling 下仍稳固
- **C**: 微调候选生成策略 (mean-revert ensemble LLM 候选作为单一 factor)

### LLM-Round 17 — OOS barrier 诊断 + 用户 "不降标准" 指令

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-17`
**用户指令**: "不要因为要 promote 降低标准 如果标准是 make sense 的话"

**本轮做了什么**: 诊断 R16 的 OOS barrier 根因 — 读 `core/mining/evaluator.py`
的 `_check_oos` + `_run_walk_forward` 逻辑，对照 archive 里 R15 trials 的
per-metric 数据

**关键诊断 — `oos_ir` 是 vs benchmark，不是 raw Sharpe**:

最佳 R15 trial (`81f5cdaa053e`) 完整数据:

| 指标 | 值 | 含义 |
|---|---:|---|
| quick_cagr | +17.41% | 全期绝对 CAGR（健康） |
| quick_max_dd | -33.36% | MaxDD |
| quick_sharpe | +0.72 | 全期 Sharpe（通过 quick gate 0.30） |
| **oos_sharpe** | **+0.376** | OOS 绝对 Sharpe **正** |
| **oos_ir** | **-0.089** | OOS Information Ratio **vs SPY** 负 |
| **oos_excess_return** | **-2.3%/period** | 跑输 SPY |
| oos_pass_rate | 0.57 | 57% of OOS windows individually passed |

**标准合理性分析** (用户指令下的 sanity check):
- `oos_min_ir_vs_benchmark = 0.20` (已从 default 0.30 **relaxed** 过)
- 要求的是"策略稳定 alpha vs SPY"，不是"策略赚钱"
- **passive SPY buy-and-hold 给 0 alpha**；能 promote 的策略必须系统性
  跑赢 benchmark（否则不如直接买 SPY）
- 这是**合理的量化标准**。**不降**

**drawup promotion 后真实故事**:
- 策略产生真实绝对回报（Sharpe +0.38, CAGR 17%）
- 但**没有稳定 alpha vs SPY**（跑输 2.3%/period）
- PRD §10 criterion #2 "QQQ gate pass" blocked NOT 因为阈值过严，而是
  当前 factor space 在当前 universe 下**真的不足以产生稳定超额收益**

**PRD §10 alternate path (criterion #4)** 正确出路:
- "30 轮结束后明确证明'当前 universe + factor 空间不足以支撑新增 alpha'，
  产出一份 blocker 报告"
- R15+R16+R17 诊断已提供定量证据（best trial 绝对 Sharpe +0.38 但 vs SPY
  IR -0.09）
- 剩余 R18-R30 里应:
  - (a) 继续菜单未覆盖 topics（LLM-9 event/calendar 是唯一剩余）
  - (b) 准备 R30 blocker report 的数据
  - (c) 不再降低 evaluator 标准

**PRD §13.2 halt 条件**: pytest 1109 / 1 PRODUCTION promote (R15 auth) /
23 candidates / 无 invariant 违反。继续。

**下轮建议**:
- **A**: LLM-9 event/calendar 候选（最后未覆盖 menu topic）
- **B**: 准备 R30 blocker report 的 data compilation

### LLM-Round 16 — mining run with drawup in PRODUCTION（OOS barrier 确认为全系统性）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-15` (mining trials 继续使用 R15 lineage 集中测试 drawup 促销效果)

**目标**: 验证 R15 promotion 后 `drawup_from_252d_low` 作为 7th PRODUCTION
factor 是否能让 MFS mining 产出通过 QQQ gate + MaxDD 约束的 trial，闭环
PRD §10 success criteria #1 + #2

**Mining run**:
- `scripts/run_mining.py --trials 30 --budget 1200 --type multi_factor
  --lineage-tag post-2026-04-20-llm-round-15`
- 耗时 121s，155 evaluated，83 unique archived，**11** 标注 lineage R15
- 72/83 passed quick，**0 passed OOS**，0 promoted，全部 tier D

**Drawup weight sweep 结果** (best top 10 R15 trials):

| spec_id | w_drawup | OOS IR | quick_sharpe | pass_rate |
|---|---:|---:|---:|---:|
| 81f5cdaa053e | **0.05** | **-0.089** | 0.72 | 0.57 |
| b63ca5d817f6 | 0.10 | -0.364 | 0.62 | 0.50 |
| 18d79c98fc92 | 0.15 | -0.328 | 0.64 | 0.57 |
| b576f47258ef | **0.00** (baseline) | -0.391 | 0.59 | 0.57 |
| afe1ed3d86b0 | 0.20 | -0.383 | 0.60 | 0.57 |

关键：**w_drawup=0.05 的 OOS IR (-0.089) 比 w_drawup=0.00 (-0.391) 好 30 pts**
— drawup 作为 production component 有改善效果，最佳权重比 R15 default (0.10)
更小 (0.05)。但**所有 trial OOS 仍为负，未能过 0.3 阈值**

**Lineage 对比**:

| lineage | n | quick_pass | oos_pass | best_oos |
|---|---:|---:|---:|---:|
| R1 capital-100k (pre-promotion, 52 trials) | 52 | 43 | 0 | +0.008 (边缘) |
| **R15 (drawup in PROD, 11 trials)** | 11 | 10 | 0 | -0.089 |
| closeout baseline | 20 | 19 | 0 | -0.325 |

**系统性发现** ⭐: OOS IR 问题是**跨 lineage** 全系统性 —— post-P0.1-fix
(apply_extra_shift=False) 的 codebase 在现有 universe + MFS 参数搜索空间下
OOS IR 集中在 [-0.5, +0.01] 区间，**从未达到 +0.3 门槛**。drawup promotion
在此 constraint 下做了边缘改善（-0.39 → -0.09）但 OOS 仍不能过门槛

**这意味着 PRD §10 success criteria 状态**:
- #1 "至少 1 个 LLM candidate 通过完整 funnel 并被 promote" —— ✅ **代码层
  达成** (R15)
- #2 "promoted 的因子在 QQQ hard gate 下为 pass" —— ❌ **blocked**（OOS barrier
  让 evaluator 永远不到 stage 6 QQQ gate）
- #3 "archive 可追溯" —— ✅

**PRD §10 alternate path** (criterion #4): "30 轮结束后明确证明'当前 universe
+ factor 空间不足以支撑新增 alpha'，产出一份 blocker 报告" —— **R15+R16
给了实证：drawup 是最强可 promote LLM 候选；其 PRODUCTION integration
只能把 OOS IR 改善 30 pts 但不能翻正**。值得在 R17-R30 里继续尝试，
或 R30 时产出 blocker report

**PRD §13.2 halt 条件**: pytest 1109 / 1 PROMOTED (drawup, user-authorized)
/ 23 LLM candidates + 1 promoted / 无 invariant 违反。继续

**下轮建议**:
- **A**: 扩大 mining 预算到 3600s + 80 trials，看更宽 parameter space 下
  有无 trial 过 OOS。确认"OOS barrier 真是 systemic"的假设
- **B**: 尝试 topic LLM-9 event/calendar candidates（唯一剩余未覆盖菜单 topic）
- **C**: **研究 WHY OOS is systemically negative** —— 可能是 evaluator.evaluate
  的 walk-forward window 配置 / stress test 过严 / post-fix 数据口径问题。
  这是**跨 LLM phase scope** 的问题，但如果 30 轮结束前不解决，success
  criterion #2 永远 blocked

默认推 **C**，因为它是唯一能解开 #2 的路径。具体任务：查 
`core/mining/evaluator.py` 的 OOS 判决逻辑，看是不是阈值设置过严

### LLM-Round 15 — composite ensemble + drawup → PRODUCTION promotion ⭐

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-15`
**用户授权**: "授权" — drawup → PRODUCTION_FACTORS

**里程碑**: PRD §10 success criterion #1 **in progress** —— 首个 LLM
generated candidate (`drawup_from_252d_low`) promoted to
`PRODUCTION_FACTORS`。最终 criterion (QQQ gate pass via evaluator.evaluate)
需后续 mining run 验证

**两部分改动**:

**Part 1 — Composite ensemble research** (Round 15 前半段，pre-authorization):

| config | CAGR | MaxDD | Pass |
|---|---:|---:|---|
| R9 纯 classical baseline | +11.89% | -59.34% | 1/5 |
| R15 C1 drawup + 5 MR ensemble | +14.91% | -56.96% | 2/5 |
| R15 C2 pure 5 MR ensemble | +11.76% | **-50.87%** | 3/5 (**MaxDD rel PASS**) |
| R15 C3 heavy drawup + 2 MR | +16.76% | -55.52% | 2/5 |
| R15 C4 MR + vol_63d + spy_trend | **+20.57%** | -56.66% | **3/5** (cost + QQQ full + QQQ holdout) |

C4 首次 PASS QQQ full gate（CAGR +20.57% > QQQ +18.39%），证明 mean-revert
ensemble + risk factors combination 有 aggregate alpha。C2 MaxDD -50.87%
最好但 CAGR 低。MaxDD abs -25% 仍无法 factor-level tool 达到

**Part 2 — PRODUCTION promotion**:
- `PRODUCTION_FACTORS`: 从 6 增至 **7**（加 `drawup_from_252d_low`）
- `MultiFactorStrategy.generate()`: 加 inline computation（与
  `factor_generator._quality_factors` 数值一致）
- `MultiFactorStrategy._DEFAULT_WEIGHTS`: rebalance 后
  low_vol 0.18 / momentum 0.22 / quality 0.18 / pv_div 0.14 /
  rel_strength 0.18 / **drawup_from_252d_low 0.10** = sum 1.00
- `MultiFactorSpace._TUNED_FACTORS`: 加 drawup
- `MultiFactorSpace.suggest()`: 新 `w_drawup_from_252d_low` slot (0.0-0.20, step 0.05)
- `MultiFactorSpace.instantiate()`: 传递新权重
- `RESEARCH_TO_PRODUCTION_MAP`: **未改**（drawup 同名 in research 和 production；
  非 shadow 关系）

**4-method consensus** 支持 promotion:
- R3 deep_check §5.4 OOS IR **+0.386** PASS
- R6 Ridge permutation **#1 of 43** (+0.024)
- R6 XGBoost permutation **#7 of 43** (+0.010)
- R12 factor_screen IR **+0.291** (**#2 of 33**)
- R15 composite backtest (作为 ensemble 组件多次出现 top 权重)

**测试**: 1109 passed（`test_shadowed_factor_merge::test_map_shrunk_by_
exactly_two` 通过 —— drawup 同名非 shadow，map 仍 7 entries）

**PRD §13.2 halt 条件** (post-authorization):
- pytest 1109 ✓
- **1 PROMOTED to PRODUCTION_FACTORS** (user-authorized §13.2 satisfied)
- 23 cumulative candidates + 1 promoted to RESEARCH + 1 promoted to PRODUCTION
- 无 invariant 违反

**下轮建议**:
- **A (强推)**: 跑 mining run `run_mining.py --type multi_factor --trials 30
  --budget 1200 --lineage post-2026-04-20-llm-round-15` 看 drawup 作为 7th
  PRODUCTION factor 后是否有 trial 过 QQQ gate + MaxDD 约束（这才是真正
  PRD §10 #1 closure）
- B: 菜单 LLM-9 event/calendar 因子（剩余未覆盖 topic）

### LLM-Round 14 — Topic LLM-11 cross-sectional（dedup 全灭）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-14`

**改动**:
- 新 `research/llm_candidates/round_14/` + 3 cross-sectional candidates
- 覆盖 §9 菜单 LLM-11：universe-aware / cross-sectional direction

**候选** (3):
- `rank_change_63d` — cross-sectional 63d momentum rank 的 21d 变化
- `above_median_persistence_63d` — 63 天内 21d 回报超过 panel 中位数的天数比例
- `dispersion_adjusted_mom_63d` — mom_63d 除以 panel-level dispersion

**Funnel + Orthog 结果** (15-sym funnel, 30-sym orthog):

| factor | Funnel | Orthog | 最终 |
|---|---|---|---|
| rank_change_63d | ARCHIVE (IC +0.022) | — | ARCHIVE |
| above_median_persistence_63d | dedup ρ=+0.72 vs xsection_rank_63d | LOW (retention 44.8%) | ARCHIVE |
| dispersion_adjusted_mom_63d | dedup ρ=+0.94 vs xsection_rank_63d | LOW (retention 19.5%) | ARCHIVE |

**关键发现** — 3/3 候选被既有 cross-sectional factors（`xsection_rank_63d`,
`rs_vs_spy_63d`, `rank_momentum_change`）explain 掉。说明 **cross-sectional
factor space 在本 universe 上几乎饱和**。

`dispersion_adjusted_mom_63d` 的 ρ=+0.94 与 `xsection_rank_63d` 是教科
书案例：normalize-by-panel-scalar 后 z-score 操作让最终 rank order 几乎
不变——正如我在 YAML 里预测的 "may degenerate to raw mom_63d after z-score"。
funnel 正确捕获

**菜单进度**: LLM-1 (R1), LLM-3 (R2), LLM-4 (R4), LLM-5 (R6), LLM-6 (R10/R11),
LLM-7 (R7/R8), LLM-8 (R7), LLM-10 (R13), LLM-11 (R14) 全部覆盖。剩余
LLM-9 (event-based) 和 LLM-12 (promote candidate) —— LLM-12 需用户授权

**PRD §13.2 halt 条件**: pytest 1109 / 0 PRODUCTION promote / 23 cumulative
candidates (1 promoted + 3 final archive via deep_check/orthog) / 无 invariant
违反。继续。

**下轮建议**:
- **A**: LLM-9 event/calendar 因子（月末效应 / 季末 / day-of-week）
- **B** (需授权): drawup → PRODUCTION
- **C** (研究价值): ensemble 5 个 mean-revert candidates composite
  backtest，看聚合 alpha 是否超过 single-factor。不触发 §13.2

### LLM-Round 13 — Topic LLM-10 path-shape（mean-revert 主题再确认）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-13`

**改动**:
- 新 `research/llm_candidates/round_13/` + 3 path-shape candidates
- 覆盖 §9 菜单 LLM-10：path-shape / rolling pattern factors

**候选** (3):
- `breakout_20d_persistence_63d` — fraction of 63 days close > prior 20d max
- `vol_compression_21_63` — 21d vol / 63d vol 比（低 = compression）
- `days_since_252d_high` — 距上次 52w peak 的天数（取负号）

**Funnel 结果** (15-sym):

| factor | IC mean | IC IR | verdict |
|---|---:|---:|---|
| breakout_20d_persistence_63d | -0.016 | -0.05 | ARCHIVE（近噪声） |
| days_since_252d_high | **-0.057** | -0.18 | ARCHIVE |
| vol_compression_21_63 | -0.038 | -0.12 | ARCHIVE |

`days_since_252d_high` 是**第 5 个 mean-revert direction-of-momentum 候选**
（累计主题再确认：R1 `momentum_quality_interaction`, R2 `first_last_bar_diff_21d`,
R4 `non_tech_rs_63d`, R12 `rs_21d_minus_63d`）。方向含义："最近 52w 高 →
21d 跑输"，符合本 universe 短期 mean-revert pattern

**Deep_check on `days_since_252d_high` (30-sym)**: FAIL
- OOS walk-forward IR +0.042（几乎零）
- Regime 4/6 正确 (BULL/RISK_OFF/CAUTIOUS/CRISIS 正；NEUTRAL/RISK_ON 负)
- Quartile 符号翻转：Q1 -0.006, Q2 +0.061, Q3 +0.058, Q4 -0.028
- 不稳定 factor, ARCHIVE

与 drawup_from_252d_low 对比（30-sym 都测过）:
- drawup: IC +0.108, OOS IR +0.386, **stable across quartiles** → PASS
- days_since: IC 近零, OOS IR 近零, quartile flip → FAIL

同样都是"52w 极值 path shape"类，但 distance-based 稳，time-based 不稳。
证实 R1-R4 主题 #1："distance-from-trough 强，direction-of-momentum 弱"

**PRD §13.2 halt 条件**: pytest 1109 / 0 PRODUCTION promote / 20 candidates
(1 promoted to RESEARCH + 2 final archive through deep_check) / 无 invariant
违反。继续。

**下轮建议**:
- 继续菜单 LLM-9 (event-based — proxy via calendar patterns) 或 LLM-11
  (cross-sectional，比如 cross-section dispersion variants)
- 或 (需授权) drawup → PRODUCTION 让 §13.2 halt 正式开始

### LLM-Round 12 — deep_check + factor_screen 后处理（drawup 第四方验证）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-12`

**改动**（只做 research runs，无 code change）:
- `rs_21d_minus_63d` deep_check (30-sym, 2018-01-01) — 跟进 Round 11 的
  MEDIUM orthog verdict
- `run_factor_screen.py` 全 33 factors 排名 — 验证 drawup post-promotion
  position

**deep_check result `rs_21d_minus_63d`**:

| 检查项 | 值 | 判决 |
|---|---:|---|
| OOS walk-forward mean IR | **-0.063** | ❌ FAIL (门槛 0.3) |
| Regime correct sign | 3/6 | ✅ PASS (恰好门槛) |
| Quartile max contribution | 0.353 | ✅ PASS |
| Quartile sign 翻转 | Q1-Q3 负，**Q4 +0.095** | diagnostic |
| **Overall** | | ❌ **FAIL** |

Round 11 orthog MEDIUM + Round 12 deep_check FAIL 合并 verdict: ARCHIVE。
残差 IC 比 raw 大但不稳定（regime + time quartile 两头翻符号）。Round
4 dedup-flag 针对 `rs_acceleration` (ρ=-0.80) 最终判决是正确的 ——
factor 本质是 sign-flipped rs_acceleration 但 alpha 不稳

**factor_screen 全 33 factors @21d horizon 排名**:

| rank | factor | IR | IC |
|---:|---|---:|---:|
| 1 | vol_63d | -0.300 | -0.127 |
| **2** | **drawup_from_252d_low** | **+0.291** | **+0.108** |
| 3 | vol_21d | -0.280 | -0.116 |
| 4 | max_dd_126d | +0.247 | +0.090 |
| 5 | drawdown_current | -0.161 | -0.051 |
| 6 | mom_252d | +0.136 | +0.047 |
| 7 | mom_12_1 | +0.128 | +0.044 |
| 8 | vol_regime | +0.110 | +0.031 |

drawup 排 #2，仅 vol_63d 差一点。这是第四个独立方法确认 drawup 的研究
价值:
- R3 deep_check OOS IR +0.386 ✅
- R6 Ridge permutation #1 / XGBoost #7 ✅
- R12 factor_screen IR +0.291 @ #2 of 33 ✅
- (唯一 blocker: R5 isolated-strategy MaxDD -77%，需 MFS composite 整合)

**最终的 4-method consensus**: drawup 是当前 universe 下最强的 single-factor
research signal（仅 `vol_63d` 的 low-vol 信号与之相当）。

**PRD §13.2 halt 条件**: pytest 1109 / 0 PRODUCTION promote / 17 candidates
(1 promoted to RESEARCH, 1 failed deep_check to archive) / 无 invariant
违反。继续。

**下轮建议**:
- **A (需新授权)**: drawup promotion to `PRODUCTION_FACTORS` —— 现有
  4-method 证据全部支持。操作: (1) 加 drawup 到 `MultiFactorStrategy.generate()`
  的 composite (2) 加到 `PRODUCTION_FACTORS` (3) 加权重 slot 到
  `MultiFactorSpace.suggest()`。触发 §13.2，需你明确首肯
- **B (无需授权)**: 继续菜单 LLM-9 event factors / LLM-11 cross-sectional

### LLM-Round 11 — orthog bug fix + 微信 round summary infra

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-11`
**用户指令**: "每轮训练总结发到微信"

**改动**:

1. **orthog bug 修复** (`scripts/llm_candidate_orthogonalization.py`):
   - 旧 logic: 对每 (date, symbol)，要求所有 32 controls 都非 NaN → 早期
     长 warmup 基本交集为空 → residual n=0
   - 新 logic: 每 date 独立挑选有足够覆盖的 controls（`min_controls_per_date=3`
     + 每 control `min_symbols_per_regression=5`）。然后 y 和选中的 controls
     都非 NaN 的 symbols 进入 regression
   - Post-fix 3 候选 residual IC:
     - rs_vs_qqq_63d: retention 43.6%, **LOW**
     - rs_vs_equal_weight_63d: retention 53.6%, **LOW**
     - rs_21d_minus_63d: retention **172.6%** (!), **MEDIUM** — residual 比
       raw 更强，signal 被既有 controls 掩盖

2. **微信 round summary infra**:
   - `scripts/send_round_summary.py` —— 从 markdown file 或 stdin 读摘要，
     通过 `core.notify` 发送
   - `config/notify.yaml` 翻成 `enabled: true, backend: wecom_bot`
   - `--stdout` flag 可强制用 stdout backend（测试/降级）
   - **需用户 export `PQS_WECOM_WEBHOOK_URL`** 环境变量；未设时自动
     fallback 到 NullNotifier（优雅降级，不 crash）

**PRD §13.2 halt 条件**: pytest 1109 / 0 PRODUCTION promote / 16 pending
candidates + 1 promoted << 200 / 无 invariant 违反。继续。

**用户操作 TODO**:
- 要真正收到微信推送，需要:
  ```bash
  export PQS_WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=XXXX"
  ```
  然后 Claude 下轮结束会自动 call `send_round_summary.py` 把总结推过来

**下轮建议**:
- 运行 `run_factor_screen.py` 给 `drawup_from_252d_low` 一个独立的 IC/OOS
  自动化报告（postR10 promotion 后 natural follow-up）
- 或运行 `run_mining.py --type multi_factor` 看 MFS composite 是否 surface
  drawup（虽然 drawup 不是 PRODUCTION_FACTOR，但 `generate_all_factors`
  包含它，可以用作 research 信号）
- orthogonalization tool MEDIUM verdict（rs_21d_minus_63d）值得 deep_check
  跟进

### LLM-Round 10 — 用户授权 drawup promotion + orthogonalization gate

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-10`

**用户授权动作** (Round 9 选项 A):
- `drawup_from_252d_low` 升级到 `RESEARCH_FACTORS` (`core/factors/factor_registry.py`)
- `_quality_factors` 在 `core/factors/factor_generator.py` 加入计算
  （`(close - rolling 252d min) / rolling 252d min`，跟 `max_dd_126d`
  作 symmetric counterpart）
- `research/llm_candidates/round_01/drawup_from_252d_low.yaml` 重命名为
  `.yaml.promoted`，防止 LLM funnel 工具误认为仍是 candidate

**里程碑**: LLM phase **首个 factor 成功 promote 到 research registry**，
满足 PRD §10 success criterion #3（"archive 可追溯：lineage_tag + candidate YAML"）
的部分。distinct 于 PRD §10 criterion #1（promote 到 `PRODUCTION_FACTORS`
+ QQQ gate PASS），那还需要未来 `evaluator.evaluate` 验证

**改动**:
- `core/factors/factor_registry.py`: `RESEARCH_FACTORS` 加 `drawup_from_252d_low`
- `core/factors/factor_generator.py`: `_quality_factors` 加 drawup 计算
- `research/llm_candidates/round_01/drawup_from_252d_low.yaml` → `.yaml.promoted`
- 新 `scripts/llm_candidate_orthogonalization.py` —— per-date cross-sectional
  OLS residualization 工具；对 dedup-flagged 候选定量判断 incremental value

**Orthogonalization 首跑** (3 个 dedup-flagged 候选):

| candidate | raw IC | residual IC | verdict |
|---|---:|---:|---|
| rs_vs_qqq_63d | +0.036 | N/A (n=0) | **BUG** |
| rs_vs_equal_weight_63d | +0.036 | N/A (n=0) | **BUG** |
| rs_21d_minus_63d | -0.020 | N/A (n=0) | **BUG** |

**Tool bug 待修 (下轮)**: `_orthogonalize_cs` 对每个 (date, symbol) 要求
所有 32 controls 都非 NaN，导致 long-warmup factor (126d/252d) + volume
factor 任一 NaN 都丢掉样本。Intersection 几乎为空。修复方式：对缺失
control 允许 drop that control per-date（而不是丢整个 symbol）

**Post-promotion cross-signal mining rerun**:
- **8 LLM candidates in XGBoost top-20** (R6 原 7 个；drawup 从 LLM 集变
  classical 集后，另一个 LLM 候选补位)
- classical `drawup_from_252d_low` 仍是 Ridge **#1** / XGB **#8**
- 新 Ridge top-5 里 `rs_21d_minus_63d` (#3), `rs_qqq_mom_63d` (#4), 
  `first_last_bar_diff_21d` (#5) 全是 LLM

**用户提醒**: "MaxDD 也太大了收益风险不成正比啊" 已在 Round 9 回应：
factor-level tool 的 -59% 到 -77% MaxDD 是 tool 局限不是真实表现。
production MFS 用 kill_switch + target_vol + regime scaling 实现 -19.7%
MaxDD（见 CLAUDE.md Phase B 记录）。接下来让 drawup 进 `run_mining.py`
evaluator.evaluate 路径跑**完整** MaxDD 检验才是 authoritative 判决

**PRD §13.2 halt 条件**: pytest **1109 (maintained)** / 0 PRODUCTION
promote (only RESEARCH_FACTORS change) / 16 pending candidates + 1 promoted
<< 200 / 无 invariant 违反。继续。

**下轮建议**:
- **A**: 跑 `run_mining.py --trials 20 --budget 900 --lineage
  post-2026-04-20-llm-round-10 --type multi_factor` 看能否发现 drawup
  作为 composite 组件在 MFS 框架下是否通过 QQQ gate + MaxDD 约束。如果
  pass，drawup 进 `PRODUCTION_FACTORS` promotion 有数据支撑
- **B**: 修 orthogonalization tool bug（sparse-controls handling）
- **C**: 继续菜单 LLM-9/10/11 候选生成

### LLM-Round 9 — composite backtest：decisive negative finding

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-9`

**改动**:
- 新 `scripts/llm_composite_backtest.py` —— 复合因子 backtest，支持从
  `research/llm_candidates/round_*/*.yaml` + `generate_all_factors` 里按
  名称选 components、加权、z-score composite
- 5 次配置测试验证 Round 5 的"composite diversification 才是 risk
  management"假设

**结果** — **假设反证**：

| config | top-K | CAGR | MaxDD | QQQ full |
|---|---:|---:|---:|---|
| drawup alone (R5 replica) | 5 | +22.10% | -77.99% | ✅ |
| A (drawup 0.3 + vol_63d -0.3 + spy_trend 0.4) | 5 | +28.08% | -69.35% | ✅ |
| A top-K=10 | 10 | +19.38% | -63.53% | ✅ |
| A top-K=15 | 15 | +16.43% | -54.73% | ❌ (-1.96%) |
| B (risk-heavy: vol -0.45) | 10 | +18.39% | -64.03% | ❌ (0.00%) |
| **Benchmark: pure classical composite** | **10** | **+11.89%** | **-59.34%** | **❌ (-6.5%)** |

**决定性发现**: 最后一行（纯 classical composite，无 LLM 候选）**MaxDD
-59.34% 仍然 FAIL**。问题不在"用哪些因子"，而在**factor-level composite
backtest 工具本身无法达到 -25% MaxDD 目标**。

**系统性解释**: production MFS 策略（按 CLAUDE.md 记录：CAGR 19%, MaxDD
-19.7%）达标靠的是：
- factor composite（本 tool 测的部分）
- **kill switch（停损）** — tool 没有
- **target_vol position sizing** — tool 没有
- **regime-scaled cash allocation** — tool 没有
- **market_trend 作 zero-out filter** — tool 当成数字因子而非 ex-ante 过滤

缺少这些 risk machinery → 单纯 factor backtest 永远过不了 MaxDD 约束

**路径重新梳理**：
- R5 findings: IC PASS ≠ 整体 PASS （MaxDD 把关）
- R6 findings: LLM 候选在 XGBoost top-20 有真实价值
- R8 findings: regime-gating 不是万能 risk mgmt（伤害强因子）
- **R9 findings: composite backtest 也不够，真 risk mgmt 在 MFS 框架内**

**结论**：下一步要么
(a) 给 `llm_composite_backtest.py` 加 kill_switch + target_vol + regime
    scaling（重复造 MFS 轮子）
(b) **直接把 drawup_from_252d_low 加到 `core/factors/factor_registry.py`
    的 `RESEARCH_FACTORS`**（非 PRODUCTION_FACTORS，不触发 §13.2
    halt）+ `generate_all_factors` 输出 —— 这让 drawup 进入
    `scripts/run_mining.py` 和 `scripts/run_factor_screen.py` 的
    正式研究流。下一步 optimizer 才能跑 evaluator.evaluate 跑完整
    QQQ gate + 5-stage pipeline

(b) 是最低摩擦路径，符合 PRD §12 Appendix 的 promotion 流程（research →
production 两阶段）。但仍然触及源码 `factor_registry.py`，需用户明确
授权才做

**PRD §13.2 halt 条件**: pytest 1109 / 0 PRODUCTION promote / 17 累计候选
/ 无 invariant 违反。继续。

**下轮建议**:
- **A**: 用户批准后把 `drawup_from_252d_low` 加到 `RESEARCH_FACTORS` +
  `generate_all_factors` 输出。触发 `llm_factor_propose.py` 的 dedup
  重新计算（此时新 candidates 会 dedup against drawup）+ `run_xgb_importance.py`
  能直接用 drawup
- **B**: 改进 composite tool 加 kill_switch + target_vol 机制（重 MFS 轮子）
- **C**: 继续菜单 LLM-6 orthogonalization / LLM-9 event factors

默认 **A**，但**需要用户首肯**才做 registry 改动

### LLM-Round 8 — Topic LLM-7：soft-gate regime-conditioned 反证

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-8`

**改动**:
- 新 `research/llm_candidates/round_08/` + 3 soft-regime 候选
- Soft regime = `tanh((SPY - 200d_EMA) / EMA * 20)` 连续 [-1, +1] 替代
  Round 7 的 binary `sign(SPY > EMA)`

**候选**:
- `rs_qqq_soft_regime_63d` = rs_vs_qqq_63d × tanh(regime)
- `mom_soft_regime_63d` = mom_63d × tanh(regime)
- `drawup_soft_regime_63d` = drawup_from_252d_low × tanh(regime)

**Funnel 结果（15-sym）**:
- mom_soft 与 rs_qqq_soft: IC/IR 与 Round 7 binary 版**完全一致**（+0.021 / +0.05 和 +0.020 / +0.05）
- drawup_soft: IC +0.052（弱于 parent drawup +0.083 in 15-sym）

**Deep_check 结果（30-sym, 2018-今）** — Round 7 vs Round 8:

| factor | OOS IR | Q4 IC | verdict |
|---|---:|---:|---|
| rs_qqq_regime_conditioned_63d (binary, R7) | +0.239 | +0.0015 | FAIL |
| **rs_qqq_soft_regime_63d (soft, R8)** | **+0.239** | **+0.0015** | **FAIL (identical)** |
| drawup_from_252d_low (no gate, R3) | +0.386 | +0.103 | **PASS** |
| drawup_soft_regime_63d (soft gate, R8) | +0.297 | +0.066 | FAIL |

**重大反证**: soft vs binary gate **没有差别** — rs_qqq_soft 和 rs_qqq_binary
数值完全相同（到小数第 4 位）。原因：2024-2026 持续 bull 使 SPY 长期 >>
200d EMA，两个 gate 都饱和到 +1，退化为同一信号。

**结论**: Round 7 hypothesis (a)（binary degeneracy）**错误**。真正原因是
hypothesis (b) —— **市场结构本身变化**：2024-2026 期间 `rs_vs_qqq_63d` 基础
预测力衰减。regime-gating 治标不治本

**第二发现**: **soft gate 对强 IC factor 反而有害**。
- drawup alone: OOS IR +0.386 (PASS)
- drawup × soft regime: OOS IR +0.297 (FAIL)
- 原因：bear 短 stint 期间 regime 反号，long-only 策略在 bear-to-bull
  recovery 时错过 top-drawup names 的反弹 alpha

**LLM 研究主题累计**:
1. (R1-R4) Direction-of-momentum 因子是 mean-reverter（4 独立 candidates）
2. (R5) IC PASS + QQQ PASS ≠ 整体 PASS；MaxDD invariant 必须把关
3. (R6) Univariate IC 与 cross-feature importance 正交
4. (R7) Interaction mining 必须 incremental-filter，18/28 pairs destroy alpha
5. **(R8) Regime-gating 不是万能 risk manager**；强 IC factor 反而被 regime
   gate 削弱 —— composite diversification 才是真正的 risk management

**PRD §13.2 halt 条件**: pytest 1109 / 0 promote / 17 累计候选 / 无 invariant
违反。继续。

**下轮建议**:
- **A**: Funnel universe size bump 15 → 30（降低 funnel 与 deep_check 的
  universe 不一致性；Round 7 的 4x IC differential 证明这是真的问题）
- **B**: LLM-6 orthogonalization gate —— Round 4 遗留的 dedup 方法论补完
- **C**: 回到 drawup_from_252d_low；建 `scripts/llm_composite_backtest.py`
  把它作为**一个 composite 组件**跟 low_vol / market_trend / mom 组合测试
  （composite-level MaxDD 应该恢复到可接受范围，这才是 Round 5 说的"真
  正的用法"）

### LLM-Round 7 — Topic LLM-8：factor interaction mining

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-7`

**改动**:
- 新 `scripts/run_factor_interaction_mine.py` —— 系统性挖 top-K factor 两两
  乘积 interaction，按 "incremental IC vs max(parent ICs)" 排名
- 新 `research/llm_candidates/round_07/` + 3 interaction candidates（top 3
  incremental IC pairs）:
  - `rs_qqq_regime_conditioned_63d` = rs_vs_qqq_63d × spy_trend_200d
  - `mom_regime_conditioned_63d`    = mom_63d × spy_trend_200d
  - `rs_qqq_mom_63d`                = rs_vs_qqq_63d × mom_63d

**Interaction mining 结果**（30-sym universe, 28 pairs from top-8 parents）:

| rank | pair | IC | parent max |IC| | incr |
|---:|---|---:|---:|---:|
| 1 | rs_vs_qqq_63d × spy_trend_200d | +0.087 | 0.029 | **+0.058** |
| 2 | spy_trend_200d × mom_63d | +0.087 | 0.029 | **+0.058** |
| 3 | rs_vs_qqq_63d × mom_63d | +0.069 | 0.029 | **+0.040** |
| ... | | | | |
| 10 | spy_trend_200d × drawup_from_252d_low | +0.111 | 0.108 | +0.003 |

**Funnel 结果（15-sym universe）**:

| factor | IC mean | IC IR | verdict |
|---|---:|---:|---|
| rs_qqq_regime_conditioned_63d | +0.020 | +0.05 | ARCHIVE |
| mom_regime_conditioned_63d | +0.021 | +0.05 | ARCHIVE |
| rs_qqq_mom_63d | +0.037 | +0.10 | ARCHIVE |

**Deep_check on top candidate (30-sym)** — `rs_qqq_regime_conditioned_63d`:
- OOS mean IR +0.239 (FAIL, < 0.3 门槛但差距小)
- Regime 5/6 correct sign (CRISIS IC +0.234 最强；NEUTRAL ≈ 0 弱)
- Quartile: **Q4 2024-2026 IC 崩到 +0.0015** — signal 在最近 2 年衰减
- Overall: FAIL (ARCHIVE)

**关键 cross-round findings**:
1. **Universe size sensitivity**：同一因子在 15-sym panel +0.020，30-sym panel
   +0.087 —— 4x differential。Interactions 需要更宽 universe 才能显现
   cross-sectional variance。Round 6 的 XGBoost 也是 30-sym 所以检测到了
2. **Regime-conditioned factors 近期衰减**：`rs_qqq_regime_conditioned_63d`
   Q1-Q3 IC 各 +0.09 到 +0.13，Q4 突然到 +0.001。2024-2026 市场 spy_trend_200d
   门限信号变弱/反噪（long bull run）
3. **Pairwise multiplication 不总是增 alpha**：28 pairs 里只 10 个有正增量；
   18 对 DESTROYED alpha（e.g., vol_63d 系列所有 interactions 都变差）。
   Interaction mining 必须筛选，不能全盘收

**PRD §13.2 halt 条件**: pytest 1109 / 0 promote / 14 累计候选 << 200 /
无 invariant 违反。继续。

**下轮建议**:
- **A**: LLM-7 regime-conditioned v2 — 用 CONTINUOUS 软门（EMA distance
  连续值 instead of binary sign）重写 Round 7 的 top-2 interactions，看是否
  能平滑近期衰减问题
- **B**: LLM-6 orthogonalization gate — 建 `scripts/
  llm_candidate_orthogonalization.py` 补完 dedup 方法论
- **C**: 改进 funnel universe — `llm_factor_propose.py` 当前 top-15 太窄；
  升到 30-sym 对标 deep_check 会让 funnel 和 deep_check 结论更一致

### LLM-Round 6 — Topic LLM-5：XGBoost cross-signal mining（7/11 候选进 top-20）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-6`

**改动**:
- 新 `scripts/run_llm_cross_signal_mining.py` —— 扩展 Round 9 的
  `run_model_comparison.py` 骨架，自动发现 `research/llm_candidates/
  round_*/*.yaml` 并将所有 LLM compute_fn 产出并入 feature panel，
  跑 Ridge + XGBoost + permutation importance
- Artifacts: `data/ml/llm_xgb_importance.parquet` + `data/ml/
  llm_cross_signal_summary.json`

**XGBoost Top-20 分布**（43 features = 32 classical + 11 LLM，
panel 79966 rows, split 2023-02-23）:

| XGB Rank | Factor | Perm Imp | Source |
|---:|---|---:|---|
| 1 | max_dd_126d | +0.146 | classical |
| 2 | mom_126d | +0.047 | classical |
| **3** | **rs_vs_qqq_63d** | **+0.037** | **LLM** |
| 4 | vol_63d | +0.029 | classical |
| 5 | spy_trend_200d | +0.022 | classical |
| 6 | mom_252d | +0.017 | classical |
| **7** | **drawup_from_252d_low** | **+0.010** | **LLM** |
| ... | ... | | |
| **11-18** | rs_21d_minus_63d / intraday_cumret_skew_21d / non_tech_rs_63d / momentum_quality_interaction / vol_term_ratio_5_63 | 各 +0.001 ~ +0.006 | **LLM** |

**PRD §9 LLM-5 completion signal**: **✅ MET** — 7 LLM candidates in XGBoost top-20.

**Ridge Top-20 分布**：`drawup_from_252d_low` 排 **#1**（+0.024，单因子
最强线性 signal），`first_last_bar_diff_21d` #3，`rs_21d_minus_63d` #6，
`intraday_cumret_skew_21d` #7，`momentum_quality_interaction` #15，
`rs_vs_equal_weight_63d` #20。 Ridge 共 6/11 LLM 候选进 top-20。

**关键 cross-round findings**:
1. **`drawup_from_252d_low` 的价值被 XGBoost 再次确认**：Ridge #1 + XGB #7。
   Round 5 MaxDD FAIL 是 *isolated-strategy* 的问题；**作为 composite 组件**
   它是最强的 LLM 候选
2. **`rs_vs_qqq_63d` (XGB #3)** 推翻了 Round 1 的 dedup-reject 直觉：虽然与
   `xsection_rank_63d` Spearman ρ=+0.94，但在 XGBoost full panel 下有
   **independent importance +0.037**。PRD §5.1 "dedup-flagged candidates
   must prove incremental value" 的教科书案例 —— 这里的 incremental value
   来自 nonlinear interactions 而非 residual linear IC
3. **Univariate-IC-weak 候选也有 interaction 价值**：`intraday_cumret_skew_21d`
   Round 2 测 IC ≈ 0，但 XGB #12。`momentum_quality_interaction` Round 1
   IC=-0.05 (archived)，但 XGB #14。说明 "univariate IC" 和 "cross-feature
   importance" 是两个正交的测度。LLM 候选筛选的 funnel 需要双验证
4. **XGBoost OOS R² = -0.107（过拟合）**但 perm importance 排序仍有诊断价值
   （类似 Round 9 findings）

**PRD §13.2 halt 条件**: pytest 1109 / 0 promote / 11 累计候选 << 200 /
无 invariant 违反。继续。

**下轮建议**:
- **A**: LLM-8 factor interaction mining —— 基于 Round 6 的 XGBoost top-20，
  挖掘具体的 factor × factor 交互项，产出新的 interaction factors
- **B**: LLM-6 orthogonalization gate —— 补完 dedup 的 residual IC 分析
  （Round 4 两个 NEEDS_HUMAN_REVIEW 候选用它可以定量判断 incremental value）
- **C**: LLM-12 第一个 LLM 候选 promote funnel —— 把 `rs_vs_qqq_63d` 或
  `drawup_from_252d_low` 作为 MFS 的 7th factor slot 加进 composite，跑
  完整 mining evaluator.evaluate。**这会触发 §13.2 halt**（涉 PRODUCTION
  代码改动），必须用户批准后才能做

### LLM-Round 5 — Topic LLM-1 §5.3 收尾：factor_backtest 工具 + drawup MaxDD FAIL

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-5`

**改动**:
- 新 `scripts/llm_candidate_factor_backtest.py` —— 简化 1-factor 策略
  backtest（long-only top-K equal-weighted，monthly rebalance），覆盖
  §5.3 最后两步：cost stress (1x vs 2x) + QQQ hard gate (full + holdout)
- **Gate 扩展**：除了 cost/QQQ 之外加入 MaxDD 两项（abs ≥ -25% 绝对下限 +
  rel ≥ 1.5× SPY MaxDD）。直接执行 CLAUDE.md invariant 约束
- Artifacts 到 `data/ml/llm_factor_backtests/<name>/factor_backtest.json`

**`drawup_from_252d_low` 完整 §5.3 funnel 结果**:

| Stage | Verdict | 数值 |
|---|---|---|
| IC screen (Round 1) | PASS | IC +0.083 (top-15) |
| Deep check §5.4 (Round 3) | PASS | OOS IR +0.386, 5/6 regimes, quartile stable |
| Cost stress (Round 5) | PASS | 2x CAGR 22.01% < 1x 22.23% |
| QQQ hard gate (Round 5) | PASS | Full +3.84%, holdout +74.39% |
| **MaxDD invariant (Round 5)** | **FAIL** | **-77.79%** vs SPY -34.63%, 2.24× 超标 |
| **Overall** | **❌ FAIL (ARCHIVE)** | 因 MaxDD 违反 invariant 整体失败 |

**关键系统性 finding**: IC PASS + QQQ PASS ≠ 整体 PASS。CLAUDE.md invariant
`Max drawdown target 15%-20%, not worse than SPY in crisis` 是硬约束，必须
在 funnel 末端强制把关。单因子 isolation backtest 容易出现极端集中
→ 极端回撤。**drawup_from_252d_low 的价值在于作为 composite 的一个组件
（配合 low_vol / market_trend 等风控因子），不是作为独立策略**。

**LLM-phase 状态升级**：`drawup_from_252d_low` 状态从 NEEDS_HUMAN_REVIEW
→ **ARCHIVED_WITH_NOTE**（文献值：strong IC & OOS robustness; requires
risk-managed composite integration before any production use）

**PRD §13.2 halt 条件**: pytest 1109 / 0 promote / 累计候选 11 / 无 invariant
违反**实际进入代码**（tool 主动捕获风险 — exactly 设计意图）。继续。

**下轮建议**:
- **A**: LLM-5 XGBoost cross-signal mining —— 把 Round 1-4 所有候选（11 个）
  和既有 30 research factors 喂给 Round 9 `run_model_comparison.py`（Ridge + 
  XGBoost + permutation importance），看 LLM 候选是否进 top-20，寻找
  cross-feature interactions
- B: LLM-6 orthogonalization gate 实现 —— funnel 当前 dedup 用 Spearman rank
  correlation，没做 orthogonalization（投影到 existing factors 正交空间后
  测 residual IC）。dedup-flagged 候选的 incremental value 需要 orthog 才能
  判断
- C: LLM-7 regime-conditioned candidates —— 3 个候选在不同 regime 下取不同权

### LLM-Round 4 — Topic LLM-4：benchmark-relative 候选（dedup 主导）

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-4`

**改动**:
- 新 `research/llm_candidates/round_04/` + `compute_fns.py` + 3 候选 YAML
- 3 候选均为 benchmark-relative 类（§3 方向）:
  - `non_tech_rs_63d` — (RS vs QQQ) × sign(RS_qqq − RS_spy)，rotation-resistance 度量
  - `rs_vs_equal_weight_63d` — 相对于 cross-sectional EW mean（非 cap-weighted）
  - `rs_21d_minus_63d` — term-structure of RS（短-长周期差）

**Funnel 结果**:

| factor | verdict | IC mean | IC IR | dedup |
|---|---|---:|---:|---|
| `non_tech_rs_63d` | ARCHIVE | -0.074 | -0.19 | — |
| `rs_21d_minus_63d` | NEEDS_HUMAN_REVIEW | — | — | rs_acceleration ρ=**-0.80**, xsection_rank_63d ρ=-0.75, rank_momentum_change ρ=-0.71 |
| `rs_vs_equal_weight_63d` | NEEDS_HUMAN_REVIEW | — | — | rs_vs_spy_63d ρ=+0.78, xsection_rank_63d ρ=+0.94 |

**关键发现**:
- **2/3 NEEDS_HUMAN_REVIEW 是 dedup 命中**（non-incremental），非真正的新 alpha。PRD §5.1 规定 ρ>0.7 触发 mandatory review 而非 auto-reject，但人审查后大概率归入 ARCHIVE
- `rs_21d_minus_63d` 与 `rs_acceleration` ρ=**-0.80** —— 实际上是符号翻转的同一因子。LLM 在未见既有 registry 时"重新发明"了已有因子
- `non_tech_rs_63d` IC = -0.074 —— **第 4 个 mean-revert direction-of-momentum 候选**（前三：`momentum_quality_interaction` -0.053，`first_last_bar_diff_21d` -0.085，`rs_acceleration` 本身也是负 IC 相关）。研究主题进一步强化：**在本 universe 上，动量方向特征普遍是 mean-reverters**
- `rs_vs_equal_weight_63d` dedup 符合预期：15 symbols 里 Mag7 占比过高，EW mean 接近 SPY

**LLM-4 completion signal (≥1 candidate enters keep)**: 形式上达成（2 NEEDS_HUMAN_REVIEW），但都是 dedup-path 非 IC-path；实质 incremental alpha 未新增

**PRD §13.2 halt 条件**: pytest 1109 / 0 promote / 11 累计候选（8+3）<< 200 / 无 invariant 违反。继续。

**下轮建议**:
- **A (推荐)**: 把 Round 3 的 `drawup_from_252d_low`（已 PASS §5.4）推进到完整 `evaluator.evaluate`（cost stress + QQQ hard gate），搭建 `scripts/llm_candidate_factor_backtest.py` skeleton
- B: 更 granular universe（40+ symbols）重测 Round 4 两个 dedup 候选，看 dedup 是否在 wider universe 下松弛

### LLM-Round 3 — Topic LLM-1/LLM-3 收尾：deep_check 工具 + 首个 PASS 候选

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-3`

**改动**:
- 新工具 `scripts/llm_candidate_deep_check.py` —— §5.4 reverse review
  自动化脚本：OOS walk-forward（3-month 非重叠窗口）+ regime 6-state
  stratification + 时间 quartile 稳定性，合并为 overall PASS/FAIL verdict
- 把 Round 1 `drawup_from_252d_low` 和 Round 2 `first_last_bar_diff_21d`
  跑过 deep_check（30-symbol universe，2018-01-01 至今）
- Artifacts 写入 `data/ml/llm_deep_checks/<name>/deep_check.json`

**Deep check 结果**:

| factor | overall | OOS IR | regimes correct sign | quartile max frac |
|---|---|---:|---|---:|
| **`drawup_from_252d_low`** | **✅ PASS** | +0.386 | 5/6 | 0.334 |
| `first_last_bar_diff_21d` | ❌ FAIL | -0.211 | 6/6 (unanimous neg) | 0.426 |

**里程碑**：`drawup_from_252d_low` 是 LLM phase 首个通过 §5.4 reverse
review 的候选。IC mean +0.10（30-sym universe，从 Round 1 的 +0.083
提升），5/6 regimes 符号一致（RISK_OFF 为 +0/中性），walk-forward
31 windows 的平均 IR +0.386。**状态从 ARCHIVE 升级为
NEEDS_HUMAN_REVIEW**（PRD §2.2：LLM 永远不是最终裁判）。

**`first_last_bar_diff_21d` 符号共识**：6/6 regimes 为负 IC，说明"下午
强势 → 21d 跑输"的 mean-reversion 效应在所有市场状态下都成立。但
|IR|=0.21 < 0.3 门槛，overall FAIL。这是关于 factor magnitude vs
signal stability 的教训：稳定但弱的信号不过 §5.4。

**PRD §13.2 halt 条件**: pytest 1109（无下降）/ 无 promote / 累计候选
8 + 1 深检 tool = 内部候选数 << 200 / 无 invariant 违反。继续。

**下轮建议**:
- **推荐**: 把 `drawup_from_252d_low` 推进到下一阶段 —— 跑完整
  `evaluator.evaluate`（QQQ hard gate + 成本 stress + subperiod robust），
  如果通过可以升级为 RESEARCH_FACTORS entry（需代码改动 + 人审核）
- 备选: LLM-4 benchmark-relative 候选扩展，在更广 universe 下重测 Round 1
  的 `rs_vs_qqq_63d`（之前 dedup 命中 xsection_rank_63d ρ=+0.94；在 30
  symbols 下 ρ 可能下降）

### LLM-Round 2 — Topic LLM-3：首批 3 个 intraday 候选

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-2`

**改动**:
- 新目录 `research/llm_candidates/round_02/` + 3 候选 YAML + `compute_fns.py`
- 3 个 intraday 候选覆盖 §3 intraday / path-shape 方向，基于 60m RTH bars（10:00-16:00 ET）:
  - `first_last_bar_diff_21d` — 最后 60m bar return − 第一 60m bar return
  - `intraday_cumret_skew_21d` — 日内 7-bar 累积回报路径的 skewness
  - `late_day_vol_share_21d` — 最后 2 个 RTH bar std / 全天 RTH std
- `compute_fns.py` 用 `@lru_cache` 避免重复 parquet 读取；所有 feature 都 cross-sectional z-score

**Funnel 结果**:

| factor | verdict | IC mean | IC IR | 备注 |
|---|---|---:|---:|---|
| first_last_bar_diff_21d | ARCHIVE | **-0.085** | **-0.24** | 强负信号：下午强的股票 21d 后跑输 → mean-revert |
| late_day_vol_share_21d | ARCHIVE | -0.024 | -0.08 | 弱负（假设方向对） |
| intraday_cumret_skew_21d | ARCHIVE | +0.003 | +0.01 | 纯噪声 |

**关键发现**:
- **`first_last_bar_diff_21d` |IC|=0.085 是本轮最强信号**，但符号是负的。符号反转模式与 Round 1 的 `momentum_quality_interaction`(-0.053) 一致。**形成研究主题**：在当前 top-15 Mag7-heavy universe 上，"动量方向 / 后发强势" 类因子表现为 mean-reversion 而非 trend-continuation
- Skewness-of-path 无信号（N=7 太少）；如果要测 path shape，可能需要更细时间分辨（5m/15m）
- LLM-3 completion signal ("≥1 candidate enters keep") **未达成**（0/3 过 IR ≥ 0.3 门槛），但产出了重要的 counter-finding

**PRD §13.2 halt 条件检查**: pytest 1109（无下降）/ 无 promote / 累计候选 8 << 200 / 无 invariant 违反。继续。

**下轮建议**: 
- **LLM-1 补充** ⭐ — 跟进 Round 1 的 `drawup_from_252d_low`（IC +0.083，最接近通过），对它做 OOS walk-forward + regime 分析；或把 Round 2 的 `first_last_bar_diff_21d` 符号翻转作为 "晨-午差"（仍然是真实特征但方向对齐 mean-revert hypothesis）做同样分析
- 备选 **LLM-2** — leakage truncation test tool（升级当前文本 heuristic 为计算层面检测）

### LLM-Round 1 — Topic LLM-1：候选生成管线首批 5 个候选

**时间**: 2026-04-21
**lineage_tag**: `post-2026-04-20-llm-round-1`

**改动**:
- 新目录 `research/llm_candidates/round_01/`（源码跟踪，非 gitignored）
- 5 个结构化 YAML 候选覆盖 §3 探索方向：
  - `rs_vs_qqq_63d` — benchmark-relative（QQQ 非 SPY）
  - `vol_term_ratio_5_63` — 非经典变体（short/long vol 比）
  - `drawup_from_252d_low` — path-shape（距年度低点涨幅）
  - `momentum_quality_interaction` — factor 交互（mom × inv-vol-rank）
  - `path_accel_21d` — 多周期组合（回报加速度）
- 新 `research/llm_candidates/round_01/compute_fns.py` 实现 5 个 `compute_fn`
- 所有 candidate 全部跑过 `scripts/llm_factor_propose.py` funnel；artifacts 入 `data/ml/llm_candidates/<name>/`

**Funnel 结果**:

| factor | verdict | IC mean | IC IR | 备注 |
|---|---|---:|---:|---|
| rs_vs_qqq_63d | **NEEDS_HUMAN_REVIEW** | — | — | dedup 命中 rs_vs_spy_63d (ρ=+0.78) + xsection_rank_63d (ρ=+0.94) |
| drawup_from_252d_low | ARCHIVE | +0.083 | +0.22 | **非平凡正 IC**，IR 刚好低于 0.3 门槛 |
| momentum_quality_interaction | ARCHIVE | -0.053 | -0.18 | **反直觉**：假设为正相关，实测 mean-revert |
| path_accel_21d | ARCHIVE | +0.024 | +0.06 | 弱 |
| vol_term_ratio_5_63 | ARCHIVE | -0.031 | -0.10 | 弱 |

**关键发现**:
- `drawup_from_252d_low` IC +0.083 是本轮最强信号，值得下轮做 OOS + regime robustness 分析后再决定 archive 还是晋升 RESEARCH_FACTORS
- `momentum_quality_interaction` 的**符号反转**是有价值的 counter-signal：说明在我们的 universe 上，"高 momentum + 低 vol" 的组合是 mean-reverter 而非 trender。这对未来 composite 设计有意义
- `rs_vs_qqq_63d` 与 `xsection_rank_63d` 几乎是同一因子（ρ=+0.94）——在 15 标的 top-universe 下，QQQ 价格接近 cross-sectional mean，所以 RS-vs-QQQ ≈ cross-sectional rank。这类 dedup 提醒必须在更广 universe 上重测

**PRD §13.2 halt 条件检查**: pytest 1109（无下降）/ 无 promote / 候选 5 << 200 / 无 invariant 违反。安全继续。

**下轮建议**: Topic LLM-2（dedup + leakage 自动检查工具 → 当前已有；可以升级成带 truncation test 的更严格版本），或 Topic LLM-3（intraday LLM 候选 3 个，基于 60m bars 而非 daily close）。当前 `drawup_from_252d_low` 作为 "almost there" 候选可以优先补 OOS + regime 验证。

### Round 12 — 非菜单：PaperTradingEngine ↔ BrokerAdapter mirror

**时间**: 2026-04-20
**选择理由**: Round 11 给了 `BrokerAdapter` ABC + `SimulatedBrokerAdapter`，但还没有接入 `PaperTradingEngine`。12 轮 mining 循环里 0 个策略晋升，菜单优先级 A-I 的研究主题大多未触发新增收益。与其再跑一轮 mining，不如补 PRD §3.4 的"接入 seam"——让未来切换真实 broker 只需在构造时注入 adapter，零 strategy 层改动。
**改动**:
- `PaperTradingEngine.__init__` 新增 `broker_adapter: Optional[BrokerAdapter] = None`（backward-compat，默认 None）
- `run_day_intraday` 的 `_on_bar` hook + residual fills block 调用新 helper `_mirror_fills_to_broker()`，为每笔 fill 执行 `set_next_fill_price(sym, executed_price)` → `submit_order(order)`
- `run_day_daily` 主 fill-booking 段后同样 mirror
- 两条路径 EOD 调用新 helper `_run_broker_reconcile()`，结果入 `self._broker_reconcile_results`
- 公开 `get_broker_reconcile_results()` 供外部读取
- 异常和 REJECTED ack 只 WARN 不 raise（broker 失联不能让策略 crash）
- 7 focused 单测 `tests/unit/paper_trading/test_broker_adapter_integration.py`：
  - 无 adapter 遗留路径不变 (backward-compat × 2)
  - 有 adapter：fills 到达 broker、reconcile 记录到 EOD、零成本下 reconcile PASS、多日累积 results（mirror × 4）
  - 接口纯度：adapter REJECTED 不会 crash engine（robustness × 1）

**测试变化**: 1102 → **1109 passing**（+7）

**关键设计**:
- adapter 是 **mirror**，engine 仍然是唯一 source-of-truth（未来替换时先 shadow 一段，再切 primary）
- 在零 cost model + pinned price 下 reconcile 应恰好通过；非零 cost 下会有 slippage 双重应用的 drift —— 这是 diagnostic 信号，不是 bug
- 为完整切换真实 broker 留下明确路径：在 `core/execution/brokers/<vendor>.py` 实现 `BrokerAdapter`，构造 `PaperTradingEngine(..., broker_adapter=IBKRAdapter(...))` 即可

**12 轮 loop 终点**:
- Round 1-12 完成所有 PRD §3.1-§3.4 的可行主题
- 但 0 个策略通过 `evaluator.evaluate()` 的 Tier-3 门槛（OOS 通过率 < 40%，QQQ outperformance 边际）
- 按用户在 Round 8 追加的指令，loop 结束后进入 **PRD §13.0 的 30 轮 LLM-assisted + XGBoost mining 阶段**（`docs/20260420-prd_llm_factor_mining.md`）
- 此阶段使用 Round 9（model_comparison）+ Round 10（llm_candidate funnel）的工具，持续 lineage_tag bump：`post-2026-04-20-llm-round-N`

### Round 11 — Topic L：BrokerAdapter 骨架

**时间**: 2026-04-20
**改动**:
- 新 `core/execution/broker_adapter.py`:
  - `BrokerAdapter` ABC 实现 CLAUDE.md §4.1 所有 7 个抽象方法：`submit_order` / `cancel_order` / `get_positions` / `get_cash` / `get_open_orders` / `get_fills` / `reconcile`
  - `OrderAck` + `ReconcileResult` 数据类
  - `SimulatedBrokerAdapter` 实现：wrap 现有 `ExecutionSimulator`，支持 `set_next_fill_price` / `set_default_fill_price` 做确定性测试
- 12 focused 单测覆盖 PRD 完成信号 "submit → ack → fill → reconcile round-trip"：
  - ABC 不可实例化
  - Happy-path BUY / SELL
  - 未配置价格 → 拒绝
  - 清洁 reconcile 通过 / 有 mismatch 时标记
  - Fills 历史按时间过滤
  - 接口纯度（strategy 层不依赖 broker 具体实现）

**测试变化**: 1090 → **1102 passing**（+12）

**下一步集成路径**: 未来 `PaperTradingEngine` 可以可选地注入 `BrokerAdapter` 替代直接用 `ExecutionSimulator`；接入真实 broker（IBKR / Alpaca）时只需在 `core/execution/brokers/<vendor>.py` 实现 ABC，**strategy 代码不改一行**

### Round 10 — Topic J：LLM factor system scaffold

**时间**: 2026-04-20
**改动**:
- 新 `core/factors/llm_candidate.py` 模块（scaffold，**不调 LLM API**）：
  - `FactorCandidate` dataclass 匹配 `docs/20260420-prd_llm_factor_mining.md` §4 YAML schema
  - `load_candidate_from_yaml()` + shape validation + 命名空间碰撞拒绝（`PRODUCTION_FACTORS` / `RESEARCH_FACTORS` 重名直接抛错）
  - `leakage_heuristic_check()` 文本层扫描 lookahead 关键字 + lag 关键字缺失
  - `dedup_check()` Spearman rank correlation vs 现有因子，阈值 0.7
  - `run_funnel()` orchestrator：shape → leakage → dedup → IC screen；**永不返回 KEEP 判决**（强候选路由到 `NEEDS_HUMAN_REVIEW`，遵守 PRD §2.2 "LLM 不是最终裁判"）
- 新 `scripts/llm_factor_propose.py` CLI：接 YAML file 或 stdin，跑 funnel，写 artifacts 到 `data/ml/llm_candidates/<name>/`
- 19 focused 单测覆盖 schema / YAML roundtrip / leakage 启发 / dedup / funnel verdicts（特别是 KEEP 永不返回的契约）

**关键契约**（per PRD §2.2）：
- LLM 角色仅限候选生成器 / 假设扩展 / 反向审查
- 最终 promote 决策**必须**由人类审核 OOS + regime + cost stress + QQQ gate 后做出
- 本 scaffold 的 verdict 是 NEEDS_HUMAN_REVIEW / ARCHIVE / REJECT 三选一

**测试变化**: 1071 → **1090 passing**（+19）

**下阶段就绪**: `docs/20260420-prd_llm_factor_mining.md` auto-launch 阶段的底座已经在位。LLM 生成的 YAML 候选可以通过 CLI 直接进入 funnel，不需要新代码

### Round 9 — Topic H：Ridge vs XGBoost 特征重要性对比

**时间**: 2026-04-20
**改动**:
- 新 `scripts/run_model_comparison.py` 在同一 feature panel 上训练 Ridge + XGBoost，对 OOS 用 permutation importance 给出 side-by-side top-20
- 严格时序 train/test split（no shuffle）；Ridge 用 5-fold TimeSeriesSplit CV 调 alpha
- 产出 artifacts 进 `data/ml/`：`model_comparison_config.json` / `model_comparison_top20.csv` / `ridge_perm_importance.parquet` / `xgb_perm_importance_comparison.parquet`
- 4 focused smoke test

**真实数据结果**（panel 79966 rows × 32 factors，train till 2023-02-23 / test 24609 rows）：

| metric | Ridge | XGBoost |
|---|---:|---:|
| OOS R² | **+0.00692** | **-0.14791** |
| Ridge alpha (CV) | 1000.000 | — |
| Rank agreement (Spearman ρ) | +0.349 | (moderate) |

**Top features**（两模型对比）:
- **#1 `max_dd_126d`** — 两模型 PER 都把它排 #1
- #11 `mom_252d` — 两模型一致
- Ridge top-5: max_dd_126d, risk_adj_mom_63d, drawdown_current, xsection_rank_63d, rs_vs_spy_126d
- XGBoost top-5: max_dd_126d, mom_126d, vol_63d, spy_trend_200d, mom_63d

**研究含义**:
- **XGBoost OOS R² 为负数** — 比"预测均值"还差，明显过拟合。在当前 universe + 特征集下，非线性模型不 generalize
- **Ridge OOS R² 只有 +0.007** — 线性信号本身也很弱，但至少正
- 两模型排 #1 都是 `max_dd_126d`，这是跨模型共识（promote 候选的强信号）
- MODERATE 的 rank agreement（+0.349）说明 XGBoost 在抓一些 Ridge 看不到的 nonlinear structure，但这些结构不 generalize OOS

**测试变化**: 1067 → **1071 passing**（+4 smoke tests）

### Round 8 — Topic G：cross-TF feature training（factor × timing 联合分析）

**时间**: 2026-04-20
**改动**:
- `scripts/validate_timing_value.py` 加 `--factor-bucket <name>` 模式：按日度因子值做 cross-sectional rank → 3 tercile buckets，per-bucket 计算 naive/timed/delta bps
- 新 `_print_factor_bucket_analysis()` helper：加载因子、per-event lookup、rank 分桶、per-bucket 统计、**诚实的 verdict 逻辑**（比较 top-tercile delta vs 同样本 overall delta，而不是 stale 历史 +3.26）
- 完整端到端用 Round 5 的 `realized_vol_60m_21d` 因子测试

**真实数据结果**（SPY + QQQ + Mag7，2024-01 至今，4596 events）:

| bucket | n | naive_net bps | timed_net bps | delta bps |
|---|---:|---:|---:|---:|
| bottom | 890 | -10.43 | -7.19 | +3.24 |
| middle | 1334 | -17.80 | -9.99 | +7.81 |
| top | 1334 | -14.87 | -10.21 | **+4.66** |

Overall (same sample): +5.49 bps/event。Top-tercile 比 overall 少 0.83 bps。Top-bottom spread +1.42 bps。

**Verdict**: **NEUTRAL** — `realized_vol_60m_21d` 虽然单独测 IC_21d ≈ +0.10（Round 5 发现），但**联合 decide_timing 不提供超越 baseline 的增量**。Cross-bucket spread +1.42 bps 在噪声内。明确不推荐 promote 到 PRODUCTION_FACTORS。

**研究含义**: Round 5 的 IC 是"因子对未来回报有预测"，Round 8 的 bucket 分析是"在固定 timing 框架下，高/低因子值事件的 timing 质量有无差异"。两个问题答案可以不同 —— 当前数据下，前者 +0.10，后者 NEUTRAL，说明该因子的 alpha 不来自 timing 层

### Round 7 — Topic I：mining 扩展到多 strategy type + QQQ gate 一致性

**时间**: 2026-04-20
**改动**:
- 真实 mining run（`--trials 5 --budget 900 --lineage post-2026-04-20-capital-100k`，**不带 --type**）跑完全部 4 种 ParameterSpace
- 运行时间 199 秒，140 evaluations，20 unique trials 分 4 种 strategy_type 均匀入库
- Archive 现在分布：multi_factor × 37 + dual_momentum × 5 + cross_asset_rotation × 5 + trend_following × 5 + legacy 20
- **15 个 non-multi_factor trials**（completion signal ≥ 3 达成）
- 所有 trials tier = D（`trend_following` 0/5 quick；`dual_momentum` / `cross_asset_rotation` 3/5 quick；multi_factor 37/37 quick；全部 OOS=0，与 Round 1 发现一致）
- QQQ gate 对所有 strategy_type 表现一致（gate 只在 passed_oos 后触发，当前没 OOS 通过所以 gate 未被调用）
- 新 focused 单测 `tests/unit/mining/test_all_strategy_types.py` 14 条，守护跨类型 invariant：`ALL_SPACES` 含 4 个注册类型；每个 `space.suggest()` + `space.instantiate()` 返回带 `.generate()` 的 strategy；archive schema 跨类型保留 `strategy_type`；`_assign_tier` 在 `passed_qqq_gate=False` 时强制 D 不论 strategy_type

**测试变化**: 1053 → **1067 passing**（+14）

**研究观察**: `trend_following` 在当前 universe × 当前参数范围下 quick_pass=0/5，意味着它的 quick 阈值（Sharpe ≥ 0.30）对该类策略过严或参数搜索空间过窄。后续轮可以针对性调搜索空间

### Round 6 — Topic E：shadowed-factor merge（`vol_63d ↔ low_vol` 与 `rs_vs_spy_63d ↔ rel_strength`）

**时间**: 2026-04-20
**改动**:
- 新模块 `core/factors/base_factors.py` 放共享 factor 计算函数：
  - `low_vol_factor(price_df, lookback, min_periods)` —— 返回 `-std`（不 annualize）
  - `rel_strength_factor(price_df, benchmark_col, lookback)` —— return 减 benchmark return
- `factor_generator._volatility_factors` 调用共享 `low_vol_factor`；`_relative_strength_factors` 调用 `rel_strength_factor`
- `MultiFactorStrategy.generate` 的 `low_vol` 和 `rel_strength` inline 实现移除，改调共享 helper
- `RESEARCH_TO_PRODUCTION_MAP` **缩减**：从 9 条 → 7 条（`vol_63d` 和 `rs_vs_spy_63d` 不再算 shadow，因为现在是同一实现）
- 14 focused 单测 + 1 现有 drift 测试自适应
- Backtest smoke 验证数值等价（helpers 是纯代码 refactor，z-score 后 annualization 常数相消；`min_periods=20` 两边一致所以 warmup 也一致）

**测试变化**: 1039 → **1053 passing**（+14）

**下次 promote 新因子（如 Round 5 的 `realized_vol_60m_21d`）时，直接加一个 helper 到 `base_factors.py` 即可，两路同时受益**，不再需要维护双实现。

### Round 5 — Topic F：首个 intraday factor family 引入

**时间**: 2026-04-20
**改动**:
- `core/factors/factor_generator.py` 新 `_intraday_factors()` helper + `generate_all_factors(intraday_bars_60m=...)` 可选参数
- 3 个新 RESEARCH-only 因子:
  - `realized_vol_60m_21d` — 21 日滚动 annualized realized vol，从 60m bar returns 计算（比 close-to-close vol 更精细）
  - `intraday_vol_ratio_21d` — intraday realized vol / daily close-to-close vol ratio
  - `intraday_autocorr_21d` — 日内 60m bar 间 lag-1 自相关滚动均值
- 三个名字加入 `RESEARCH_FACTORS`，**不在 `PRODUCTION_FACTORS`**（待 funnel 通过才 promote）
- 10 focused 单测 + 1 drift 测试适配（传入合成 60m bars）
- 真实数据 IC smoke（SPY/QQQ/Mag7/AAPL/MSFT/NVDA/META/GOOGL/AMZN，2020-今，N=8 symbols, 1582 days）:
  - `realized_vol_60m_21d`: IC_5d = +0.054, **IC_21d = +0.096** ← 非平凡
  - `intraday_vol_ratio_21d`: IC_5d = -0.015, IC_21d = -0.002 ← trivial
  - `intraday_autocorr_21d`: IC_5d = +0.003, IC_21d = +0.043 ← 边缘

**研究信号**: `realized_vol_60m_21d` 21d IC 约 +0.10，暗示"高日内波动 → 未来回报偏正"的 vol risk premium 关系。尚未通过完整 funnel（OOS / regime / cost stress），**不得直接进生产**。

**测试变化**: 1029 → **1039 passing**（+10）

### Round 4 — Topic D：factor gate WARN/ERROR 可配置

**时间**: 2026-04-20
**改动**:
- 新 `UnregisteredFactorError(ValueError)` + `enforce_execution_factor_names(weights, *, strict)` API 统一 gate 路径
- `MultiFactorStrategy.__init__` 新 kwarg `strict_registry: bool = False`（默认保持 legacy WARN+drop 不变）
- 新 `FactorRegistryConfig(strict_mode: bool = False)` pydantic schema + `config/risk.yaml::factor_registry`
- 3 个生产脚本（`run_backtest` / `run_paper` / `run_multi_tf_backtest`）从 config 透传
- `MiningSpace._registry_kwargs()` 新 helper 走同 concentration 的 lazy-load 模式
- 11 focused 单测全通过：strict raise / default warn / 空输入 no-op / config schema 默认 False / mining space 集成

**PRD §3.1 Topics A-D 至此全部关闭**。从 Round 5 开始转入 §3.2 research 菜单（E/F/G/H/I）或 off-menu OOS blocker

### Round 3 — Topic C：stale_counts 持久化到 checkpoint

**时间**: 2026-04-20
**改动**:
- `save_bar_checkpoint` 现在把 `self._intraday_stale_counts` 序列化进
  `state_json`（无需 signature 变更；仍从 instance 读）
- `load_bar_checkpoint` 返回 dict 里新增 `stale_counts` 字段；老
  checkpoint（pre-Round-3，state_json 无此键）用默认空 dict，向后兼容
- `run_day_intraday` 在 resume 路径**总是**从 cp 恢复 `stale_counts`，不
  依赖 `cp.date == date` 判断。语义上 stale_counts 是跨日累积的，进程
  重启后 halted 标的的 stale counter 能正确续上

**测试**: `tests/unit/paper_trading/test_stale_counts_checkpoint.py` 6 tests
覆盖：保存包含 stale_counts / 加载返回 stale_counts / 老 checkpoint 返回
空 dict / 同日 resume / 跨日 resume / **多日 halt 累积触发 ghost cleanup**
的端到端集成。全套 1012 → **1018 passing**.

### Round 2 — Topic B：leaderboard 显示 lineage + QQQ 完成

**时间**: 2026-04-20
**改动**:
- `core/mining/archive.py` 新 `lineage_summary()` helper: 返回 per-lineage
  聚合 DataFrame（含 `n_trials / n_quick_pass / n_oos_pass / n_holdout_pass
  / n_qqq_gate_pass / n_gate_evaluated / avg_quick_sharpe / worst_oos_ir /
  best_oos_ir`），关键区分 "gate_evaluated"（Stage 6 被调用）vs "gate_pass"
  （通过 gate）
- `scripts/run_mining.py --leaderboard` 现在显示 13 列（原 8 列 + `qqq_ok` +
  3 个 qqq_*_excess + `lineage_tag`），并在底部追加 "按 Lineage 分组汇总"
  表格
- 新增 CLI 参数 `--lineage-filter <tag>` 可只看单一 lineage

**测试**: `tests/unit/mining/test_archive_lineage.py` 加 3 个 focused 测试
（空 archive / 两 lineage 聚合 / gate_evaluated vs gate_pass 区分）。
全套 1009 → **1012 passing**.

**Round 1 数据的 CLI 可视化**: 两个 lineage 并排显示 —— `post-2026-04-20-
capital-100k` (37 trials) 与 `post-2026-04-20-closeout` (20 trials) 的
quick/OOS 差异一目了然，n_gate_evaluated = 0 明确证实 QQQ gate 未在
任何 trial 触发。

### Round 1 — Topic A 实战：post-P0.1-fix OOS 失败率 100%

**时间**: 2026-04-20
**参数**: `run_mining.py --trials 80 --budget 1800 --lineage-tag post-2026-04-20-capital-100k --type multi_factor`
**结果**: 120 evaluated, 37 unique trials written to archive, 56 passed_quick, **0 passed_oos**, 0 promoted
**QQQ gate 触发**: **0**（gate gated on passed_oos，无 trial 到 Stage 6）
**OOS IR 区间**: -0.709 到 -0.113（全部负）
**Quick Sharpe 区间**: 0.424 到 0.774（多数过 quick 门槛 0.30）
**-999 崩溃**: 0（post-smoke NaN 护栏在 80 trials 规模下稳定）

**诊断**：`apply_extra_shift` 默认从 `True` 改为 `False`（P0.1 fix）后，原先
Phase B 文档记录的"current best"参数（RS=0.30, momentum=0.30 等）在当前
codebase 上不再复现历史 OOS 数字。这不是 bug —— 是修正 double-lag 后
数据口径变了。Phase B 的"best"本质上是旧口径下的局部最优。

**这意味着**：整个策略参数空间需要在 post-fix 口径下重新搜索。80 trials /
1800s 不足以发现新的最优。

**对 ralph-loop 的直接影响**：
- Topic A（让 QQQ gate 在 Stage 6 触发）按字面 completion signal **未达成**
- 但 80-trial mining 本身验证了：lineage 隔离、NaN 护栏、archive 写入、
  `_assign_tier` 降级逻辑在大规模下都正常
- QQQ gate 的 plumbing 在单测层已充分覆盖（`test_qqq_hard_gate.py` + 
  `test_acceptance_qqq.py` + `test_archive_lineage.py`），只是生产
  archive 里现在还没有真实值


---

## Part D — v2 → v3 PRD revision notes

Extracted from CLAUDE.md §"QQQ Constraint Upgrade / Other Revisions / Still
needs code audit to confirm". These were notes explaining what changed when
the Phase C PRD was revised from v2 to v3 (2026-04 timeframe). Meta-historical
at this point — active invariants and contracts live in current CLAUDE.md.

### QQQ Constraint Upgrade
- **旧标准 `excess vs QQQ >= -2%` 已废止**
- **新标准：策略收益必须跑赢 QQQ**
  - Full period + holdout: 硬约束（CAGR/return > QQQ）
  - OOS walk-forward average: 硬约束（mean excess > 0）
  - Individual window / regime: 诊断观察（不作为 pass/fail）
- Risk guardrail: 不允许通过恶化回撤或集中度来硬换 QQQ outperformance
- Current best strategy 需要在新约束下重新验证

### Other Revisions
1. **strict_match:** `integer_shares: true` → `share_mode: integer | fractional`，核心要求是两边一致 [REVISED]
2. **Stressed cost test:** 从 `p < 0.01` 改为确定性工程标准——2x cost 必须产生更低 CAGR 和更高 total cost [REVISED]
3. **Intraday timezone:** tz-naive ET 标注为当前实现兼容，非长期架构目标；保留向 tz-aware UTC 演进空间 [REVISED]
4. **Halted/stale valuation:** 持仓资产不得从 NAV 移除，必须继续按 last valid price 估值 [REVISED]
5. **Leakage rules:** 从 `shift(0) 检查` 改为基于时间可得性语义的正式规则（signal/data/execution timestamp） [REVISED]
6. **Factor correlation:** 从 `> 0.7 自动 reject` 改为 `> 0.7 触发强制审查`，需证明增量价值 [REVISED]
7. **[NEW] Pricing and Valuation Semantics:** raw/adjusted 规则、signal/execution/valuation 三阶段价格约定、stale data 估值规则
8. **[NEW] QQQ Outperformance Rule:** 分层硬约束定义 + risk guardrail
9. **Evidence levels:** 关键条目增加 `verification_source` 字段

### Still needs code audit to confirm:
- Whether BacktestEngine execution is truly deterministic
- Whether yfinance_provider.py implements full DataProvider interface

---
