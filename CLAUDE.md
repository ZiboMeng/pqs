# PQS — Personal Quantitative System

## Phase C: Continuous Development PRD (v3)

### System Identity
个人量化研究与模拟交易系统。目标：长期可持续跑赢 SPY，保持低回撤（15%-20%），具备黑天鹅韧性（2008-style 场景 MaxDD ≤ 25%）。**QQQ 作为 sector-tilt diagnostic reference，非 hard outperformance gate**（per `docs/memos/20260502-qqq_benchmark_deprecation.md`）。

### Invariant Constraints (NEVER violate without explicit user approval)
- long-only, no-margin, no-short
- SQQQ blacklisted; TQQQ/SOXL require stricter risk thresholds
- No real broker/API integration this phase; paper trading = internal simulation
- macOS local execution; no AWS/cloud deployment priority
- Benchmark: **SPY primary (HARD outperform gate over full period + 2025 holdout); QQQ secondary (DIAGNOSTIC only — sector-tilt reference, NOT a hard gate)** [REVISED 2026-05-02 per `docs/memos/20260502-qqq_benchmark_deprecation.md`]
- Left-side trading = enhancement module only, never default engine
- Intraday: 60m/30m primary, 15m research only
- All thresholds must be configurable (config/*.yaml), never hardcoded
- Must preserve backtest-execution consistency
- Chinese reporting, English code naming
- Initial capital ~$10,000, **target scale $100K (10x in 5-10 years)** [REVISED 2026-05-02 — $1M+ aspiration deprecated as fund-grade-not-individual-realistic]
- Max drawdown target 15%-20%, not worse than SPY in crisis; **2008-style scenario MaxDD ≤ 25% (testable via stress slices)** [QUANTIFIED 2026-05-02]
- **Outperforming SPY does not waive drawdown, crisis-resilience, or long-only risk constraints**

### Benchmark Outperformance Rule [REVISED 2026-05-02 — QQQ deprecated]

**硬目标：策略收益必须长期跑赢 SPY** (full period + 2025 holdout, both HARD)。**QQQ 作为 diagnostic reference，非 hard gate** —— sector-concentrated benchmark 的 outperformance 是 active strategy bet (NOT invariant).

| Evaluation Scope | vs SPY | vs QQQ |
|-----------------|--------|--------|
| Full backtest period | **Strategy CAGR > SPY CAGR — HARD** | Strategy CAGR vs QQQ — diagnostic |
| 2025 holdout (Track A validation) | **Strategy return > SPY return — HARD** | Strategy return vs QQQ — diagnostic |
| OOS walk-forward (average) | Mean excess vs SPY > 0 — diagnostic (preferred) | Mean excess vs QQQ — diagnostic |
| Individual OOS window | Excess vs SPY reported per window — diagnostic | Excess vs QQQ reported — diagnostic |
| Individual regime period | vs SPY reported per regime — diagnostic | vs QQQ reported — diagnostic |

**Why QQQ deprecated as hard gate** (8-angle analysis at `docs/memos/20260502-qqq_benchmark_deprecation.md`):
- QQQ = Nasdaq-100 = sector-tilt (60% tech), not market-broad
- 1999-2025 long-term: QQQ +8.3% vs SPY +7.8% = +0.5% only (the 2009-2021 +5.7%/yr gap was zero-rate cherry-pick, not regime invariant)
- Long-only beat-QQQ requires beta>1 → MaxDD>QQQ → DIRECTLY violates 15-20% MaxDD invariant
- Industry / academic norm: long-only US large-cap benchmark = S&P 500 / Russell 1000, NOT QQQ
- 5 mining cycles' sibling-by-NAV convergence root-caused by infeasibility of (beat QQQ AND MaxDD ≤ 20%)

**Risk guardrails** (unchanged from prior version):
- No concentration in ≤3 symbols
- Position limits per config/risk.yaml respected
- MaxDD not materially worse than SPY (and 2008-style scenario MaxDD ≤ 25% per `Black Swan Quantification` below)
- Regime-based risk scaling enabled

**Master report must:**
- Display `vs SPY` column as primary outperformance display
- Display `vs QQQ` column as diagnostic (does NOT block promotion)
- Display QQQ excess in strategy summary as informational
- Flag "fails QQQ diagnostic" as info note (NOT a gate)

#### Black Swan Quantification [QUANTIFIED 2026-05-02]

Pre-2026-05-02 invariant said "黑天鹅韧性" without testable threshold.
Replaced by:
- **Stress slice MaxDD ≤ 25%** for 2008-equivalent regime (lehman/covid_flash/rate_hike_2022)
- Future: regime-conditional Monte Carlo per stress test (TBD post-Trial-9 forward)

#### Diversifier Role Additional Constraints [SIMPLIFIED 2026-05-02]

**Scope**: candidates with `candidate_role = CandidateRole.DIVERSIFIER`.

**Pre-2026-05-02 history**: this section was named "Diversifier Role Exception" because the OOS walk-forward window-mean vs QQQ rule was waived for diversifier role only. After 2026-05-02 QQQ deprecation, that cell is diagnostic for ALL roles (no exception needed). Section renamed to reflect remaining content = diversifier-specific STRICTER constraints.

**Diversifier-specific STRICTER rules** (apply only to role=`diversifier`):
- Anti-sibling NAV correlation: raw NAV < 0.70 vs all anchors, residual NAV < 0.50
- Anti-sibling factor overlap: `factor_overlap_with_active_core = 0`
- Cross-asset utilization: `non_equity_weight_avg ≥ 15%`
- Per-validation-year MaxDD ≤ 20% (hard) / ≤ 18% (soft warn with TD60 self-clearing per D10c)

**Standard rules** (apply to ALL roles, including diversifier):
- Full-period vs SPY > 0 (HARD)
- 2025 holdout vs SPY > 0 (HARD)
- Per-validation-year MaxDD ≤ 20% (hard)
- Stress slice MaxDD ≤ 25%
- Concentration: M12 top1 ≤ 40%, top3 ≤ 70%
- Long-only / no-short / no-margin invariants

**Rationale**: a diversifier in a fleet contributes via low-correlation NAV addition + cross-asset exposure. The stricter rules are designed to ensure diversifier ROLE delivery is mechanism-distinct from core_alpha (which delivers via standalone alpha).

**Authority**: PRD `docs/prd/20260501-two_stage_allocation_architecture_prd.md` §6.2; decision memo `docs/memos/20260501-diversifier_role_decision.md`; QQQ deprecation memo `docs/memos/20260502-qqq_benchmark_deprecation.md`; user explicit-go 2026-05-01 + 2026-05-02.

**Reversibility**: revocation of diversifier role requires user explicit-go + draft of `docs/memos/YYYY-MM-DD-diversifier_role_revoke_memo.md`; CLAUDE.md edit reverted; active diversifier candidates revert to `legacy_decay_verification` role. Revocation of QQQ deprecation is a separate decision (see `docs/checkpoints/20260502-invariant_revision.md`).

---

### Pricing and Valuation Semantics [NEW]

#### Raw vs Adjusted Price Rules

| Context | Price Type | Rationale |
|---------|-----------|-----------|
| Factor research (IC, screening) | Adjusted (split + dividend) | Factors measure return-based signals; adjusted prices give correct returns |
| Backtest execution (order fill) | Adjusted close/open | T+1 open is adjusted; consistent with factor signals |
| Portfolio mark-to-market | Adjusted close | Consistent with execution price basis |
| Corporate actions | Splits via `data/ref/splits.parquet`; dividends not currently applied | Splits handled deterministically at read time |

**Current implementation (post-round-3 step-3b, 2026-04-25):**
- Canonical source = polygon 1m → daily aggregation
  (`core/data/daily_aggregator.py`); stored raw (unadjusted) at
  `data/daily/<sym>.parquet` and `data/intraday/1m/<sym>.parquet`.
- Splits applied at **read time** via
  `BarStore.load(..., adjusted=True)` using `data/ref/splits.parquet`
  cascade.
- Dividends are NOT currently applied in adjustment (deferred).
  Strategy returns therefore exclude dividend yield component until a
  dividends sidecar is added.
- yfinance is **fallback only** for ETF 2024+ daily gaps where polygon
  1m did not cover (round-3 close memo §parking-lot). Stocks-only
  paths never touch yfinance post round-3.

**Constraint:** When switching DataProvider in the future, the
replacement MUST produce price series with identical adjustment
semantics (raw bars + splits.parquet read-time cascade) AND must
write to `data/ref/bar_provenance.parquet` synchronously. A price
semantics regression test must exist before any vendor swap.

#### Signal, Execution, and Valuation Price Convention

| Stage | Price | Timing |
|-------|-------|--------|
| Signal generation | T-day adjusted close (shifted by 1 to prevent lookahead) | End of T |
| Order generation | Based on T-day portfolio value (using T-day close) | End of T |
| Execution fill | T+1 adjusted open (real open_df, not close approximation) | Open of T+1 |
| Portfolio valuation | T+1 adjusted close | Close of T+1 |

#### Halted / Stale / Missing Data Valuation [REVISED]

| Scenario | Order Generation | Valuation |
|----------|-----------------|-----------|
| Symbol has no bar today | Do NOT generate new orders | **Mark at last valid price** (stale-flagged) |
| Symbol halted mid-day | Do NOT generate new orders | Mark at last traded price |
| Stale > N bars (configurable) | Exclude from order generation | Continue valuation at last price + diagnostic flag |
| Symbol delisted | Liquidate position at last price | Remove from universe |

**Rule:** Positions in halted/stale assets are NEVER removed from NAV calculation. They are marked at last valid price and flagged as stale in diagnostics.

---

### Current System State (Phase 0 Audit, 2026-04-17) [REVISED]

**Architecture:** config/ → core/ → scripts/ → tests/. Live test count in `data/baseline/latest.json` (build via `python dev/scripts/baseline/build_research_baseline_snapshot.py`).
**Phase C progress:** 19 iterations + intraday sprint (4 tasks). Intraday pipeline now functional.

Evidence levels: `code_verified` / `test_verified` / `manual_verified` / `claimed_not_verified`.

#### Confirmed Done (compressed 2026-04-24 R8)

Capabilities shipped + test-verified: daily/60m data ingest, real T+1
open-price execution, paper-backtest shared rebalance logic, 3-tier
kill switch with auto-recovery, separate slippage/commission cost
accounting, integer-share mode, regime-aware walk-forward OOS,
expanding-window validation, 252d forward-block holdout, 4-period
stress + subperiod + 2x-cost + ±20% param + 6-regime robustness
gates, OOS/IS Sharpe overfit gate, 5-stage mining pipeline, **143
research factors** across **16 mining families A-P** (post-PRD 20260512
Bucket A/B/C/Macro expansion; +76 factors from 67 baseline), 7
production, see factor_registry), XGBoost 3.2.0
feature importance, MultiFactorStrategy (16 tests), left-side trading,
SPY+QQQ master report, PIT universe rebalance, 4-detector diagnostics,
target_vol=0.25 constructor. Full feature table moved to
`docs/20260424-claude_md_phase_e_history.md` §"Phase E-post +
Candidate-2 8-round" for audit; individual file pointers remain
discoverable via `grep` / §"Key File Locations" at the bottom of
this file.

#### Phase C completion tables (archived 2026-04-22)

The following historical tables moved to
`docs/20260422-claude_md_phase_bc_history.md` §Part B:
  - Partially Done (5 rows)
  - Fixed in Phase C (15 rows, C-1 … C-14)
  - Fixed in Intraday Sprint (4 rows)
  - Remaining low-medium priority (6 rows)
  - Constraint Completion Sprint (约束 1-3 + P1 闭环 + Mining 前最后收口)
  - P0/P1 收口闭环 (8 items, P0.1 … P1.8)

**Current state**: all Phase C + Intraday Sprint + Constraint Completion
items are shipped. Active work tracked under "Current TODO Checklist"
at the bottom of this file; ralph-loop rounds live in
`docs/20260420-ralph_loop_log.md`.

#### Phase B "Current Best Strategy" + "Key Discoveries Loop 1-50" (archived)

Pre-P0.1-fix numbers (CAGR 19.0% / Sharpe 0.98 / MaxDD -19.7%) and
Phase B loop findings moved to
`docs/20260422-claude_md_phase_bc_history.md` §Part A. Those numbers
**do not reproduce on the post-2026-04-20 codebase** because the P0.1
`apply_extra_shift=False` fix changed the signal data window. Any new
"current best" must be established under the current codebase —
see ralph-loop results for post-fix search state.

---

## Phase C Execution Plan

### Priority Order (highest first)

```
P0. Fix critical test gaps (MultiFactorStrategy tests, paper-BT consistency test)
P1. Backtest / replay / paper consistency hardening (strict_match mechanism)
P2. Intraday pipeline truly functional
P3. Factor research closed loop + real XGBoost/SHAP + LLM-assisted exploration
P4. Performance, scalability, data vendor / broker prep
```

---

### Phases 1-4 (compressed 2026-04-24 R8)

Phase 1 (core consistency hardening incl. `strict_match`),
Phase 2 (intraday pipeline), Phase 3 (factor research loop +
real XGBoost/SHAP + LLM-assisted funnel), Phase 4 (performance +
DataProvider/BrokerAdapter separation blueprint): nearly all
items shipped and covered by `data/baseline/latest.json` tests.
Acceptance criteria / detail preserved in
`docs/20260424-claude_md_phase_e_history.md` + the Phase C PRD
document itself (git history).

Still open from Phase 4 blueprint — tracked in Framework
Completion TODO below:
- M11 paper-BT consistency gate (pack v3)
- M17 live-feed infra (separate PRD when needed)
- M18 cross-ticker DSL func expansion on demand

---

## Autonomous Decision Authority (inherited from Phase B)

Authorized WITHOUT confirmation:
- Code changes, module splits, local refactors
- New factor/strategy candidates, experiments
- Config enhancements, threshold tuning
- Test additions, tech debt cleanup
- Diagnostics/report/validation improvements
- Strategy/factor demotion, suspension, re-scoring
- LLM-generated factor candidates (subject to mandatory funnel)

MUST PAUSE for confirmation:
- Changing core constraints (long-only, no-margin, benchmark logic, etc.)
- Changing research boundaries (adding 15m, new data sources, etc.)
- Changing evaluation criteria definitions
- Repo-level restructuring with direction forks
- Promoting LLM-generated factor without full funnel

---

## Work Method

Each iteration:
1. 本轮目标
2. 做了什么 + 修改了哪些文件
3. 跑了哪些测试 + 当前结果
4. 剩余风险
5. 下一步

Maintain TODO checklist. Update CLAUDE.md when work is actually completed. Small verifiable patches over large rewrites.

### Session-start discipline (read EVERY restart)

**每次新会话/重启,先读 memory 取 context 再动手。** MEMORY.md 一行
索引会自动进 context,但**完整 context 需要把当前工作相关的 memory
文件实际读出来**(尤其 feedback 类纪律),不能只看索引就开工。Active
work 涉及 audit / temporal_split / forward / mining / PRD 时,先 pull
对应 memory 文件确认纪律,再执行。

### Audit discipline(标准纪律,见 memory `feedback_audit_surfaces_not_thorough`)

做 audit / 收口 / "做完了吗" 自检的**目的 = 暴露"之前做的哪些没做
彻底"(做出来 ≠ 做彻底),不是确认"它存在就行"**:
- 必须对比「之前结论/结果 ↔ literature/标准 ↔ 当前 PRD」,产出"没
  做透"对照表,**全部 fold 进当前 PRD/supplement**(列出来不算)。
- 必须主动翻查并**纠正自己上一轮的 overclaim**("严谨/不用重做/合规"),
  诚实留痕不 hand-wave(Phase 2A "不重做" overclaim 是先例)。
- 非实测的 PLACEHOLDER/judgment 值即便"做出来了"也算没做透。
- 配合 4-tier 自审(`feedback_self_audit_methodology`)+ per-round
  4 维(`feedback_audit_per_round_methodology`)+ 禁 blanket verdict
  (`feedback_no_blanket_failure_verdict`)。

---

## Key File Locations
- Config: `config/*.yaml` (system, backtest, universe, risk, cost_model, reporting, regime, events, **production_strategy** ← PRD M1 SoT)
- Strategies: `core/signals/strategies/` (dual_momentum, trend_following, cross_asset_rotation, multi_factor)
- Left-side: `core/signals/left_side.py`
- Mining: `core/mining/` (miner, evaluator, archive, strategy_space)
- Factors: `core/factors/` (factor_engine, factor_evaluator, factor_generator)
- Backtest: `core/backtest/` (backtest_engine, intraday_engine, window_analyzer)
- Diagnostics: `core/diagnostics/detectors.py`
- Risk: `core/risk/` (failure_detector, kill_switch, stress_tester)
- Reporting: `core/reporting/` (master_report, master_report_builder)
- Paper trading: `core/paper_trading/` (paper_trading_engine, pnl_tracker)
- Universe: `core/universe/` (universe_manager, asset_scorer)
- Data: `core/data/` (yfinance_provider, market_data_store, validator, calendar, bar_store)
- Scripts: `scripts/` (run_all.sh, fetch_data.py, run_backtest.py, run_mining.py, run_paper.py, generate_report.py, run_factor_screen.py, run_xgb_importance.py, run_universe_rebalance.py, build_bars_parquet.py, build_splits_parquet.py, aggregate_bars.py, build_catalog.py, validate_vs_yfinance.py)
- Intraday report: `core/reporting/intraday_report.py`
- Tests: `tests/unit/` + `tests/integration/` (current count: see `data/baseline/latest.json`)

## Scripts Quick Reference
```bash
bash scripts/run_all.sh research      # full pipeline
bash scripts/run_all.sh full          # data + backtest + report
bash scripts/run_all.sh mine          # Optuna search (1h)
bash scripts/run_all.sh daily         # daily paper trading
bash scripts/run_all.sh backtest-quick # skip walk-forward
bash scripts/run_all.sh universe      # universe rebalance
bash scripts/run_all.sh factors       # IC screening
bash scripts/run_all.sh xgb           # feature importance
bash scripts/run_all.sh leaderboard   # mining rankings

# PRD M0 (2026-04-21): baseline snapshot replaces hardcoded test counts
python dev/scripts/baseline/build_research_baseline_snapshot.py
jq '.tests, .git, .archive' data/baseline/latest.json
```

## Iteration Log
See `reports/loop_changelog.md` for Phase B history (50 iterations).

## IMPORTANT: Git Safety
NEVER use `git add -A` or `git add .` — always add specific files.

## docs/ storage convention (effective 2026-04-24, forward-only)
New documents go into per-category subdirs under `docs/` (e.g.
`docs/prd/`, `docs/synthesis/`, `docs/checkpoints/`, `docs/memos/`,
etc.). Existing flat files stay where they are. Full convention +
category list: `docs/INDEX.md` "Convention for new docs" section.
Update `docs/INDEX.md` when adding a new doc.

---

## Ralph-Loop Findings & PRD-revision meta-notes (archived 2026-04-22)

Per-round detailed changelogs (**LLM-Round 1-22**, intraday-sprint
**Round 1-12**), the Phase B pre-P0.1-fix "Current Best Strategy" snapshot,
Phase C completion tables (Partially Done / Fixed in Phase C / Intraday
Sprint / Constraint Completion Sprint / P0-P1 closeout), and the v2→v3 PRD
revision notes (QQQ Constraint Upgrade / Other Revisions / Still needs code
audit) all moved to `docs/20260422-claude_md_phase_bc_history.md` to keep
CLAUDE.md focused on active execution context.

**What stayed in CLAUDE.md**: Invariant Constraints, QQQ Outperformance
Rule, Pricing and Valuation Semantics, Confirmed Done inventory, Phase C
acceptance criteria (still referenced), Phase D framework, multi-TF contract,
1m bar pipeline / trades backfill / provenance sidecar / factor pipeline
contract / notify, and current TODO.

**Ongoing ralph-loop logs**: `docs/20260420-ralph_loop_log.md` (not
CLAUDE.md). New rounds append there with lineage tag + 11-part Chinese
report per PRD convention. CLAUDE.md is no longer the running changelog.


## Phase D: Iterative Optimization Loop

### Mode
迭代优化 loop。每轮：审计 → 选主题 → 小步修改 → 验证 → 决定下一轮方向。

### Overall Goals (ordered)
1. 可交易性
2. 研究质量
3. 因子/策略发现能力
4. 回测/模拟/报告可信度
5. 运行效率
6. **多时间尺度协同决策能力**

### Multi-Timescale Intraday Framework [NEW]

#### Architecture: 日线策略 + intraday 执行层增强

当前定位（C 模式）：
- **日线 MultiFactorStrategy 决定持仓方向**（已验证，CAGR 19%）
- **Intraday 多时间尺度决定具体执行时机**（更好的 entry/exit timing）
- 成熟后演进到 A 模式（独立 intraday alpha + 日线 alpha 组合）

#### Timescale Roles

| 时间尺度 | 职责 | 数据可用性 | 验证等级 |
|---------|------|----------|---------|
| **60m** | 主趋势 / 大级别 regime / 高层上下文 | 730天 (yfinance) | **正式验证** |
| **30m** | 结构确认 / 次级趋势 / 风险状态 | 60天+ (yfinance) | **正式验证** |
| **15m** | 执行确认 / 信号加强或否决 / 短周期 timing | 60天 (yfinance) | 原型/概念验证 |
| **5m** | 精细 entry / exit / stop / execution timing | 60天 (yfinance) | 原型/概念验证 |

**约束**：15m/5m 因为只有 60 天历史，当前仅作执行层原型。等真实数据源到位后升级为正式验证层。

#### Multi-Timescale Signal Protocol

```
Decision Chain:
  60m context (trend direction, regime) 
    → 30m confirmation (structure, risk state)
      → 15m trigger (entry timing, signal strength) [prototype]
        → 5m execution (precise entry/exit/stop) [prototype]

Rules:
  - Higher timeframe has VETO power over lower timeframe
  - Lower timeframe cannot initiate position against higher TF direction
  - Cross-TF conflict → no trade (conservative)
  - Only CLOSED bars may generate signals (no incomplete bar lookahead)
  - signal_timestamp = bar_close_time for each timeframe
```

#### Multi-Timescale Leakage Rules

| Rule | Description |
|------|------------|
| Bar completion | Only closed/completed bars generate signals. No using incomplete bars. |
| Cross-TF alignment | 60m bar close at 10:30 means data up to 10:30. 30m bar at 10:00 and 10:30 are both valid. 15m bars at 10:00/10:15/10:30 are valid. |
| No future higher TF | A 15m signal at 10:15 must NOT use the 60m bar closing at 10:30 (not yet complete) |
| Execution delay | Minimum 1-bar delay at the execution timeframe (e.g., 15m signal → next 15m bar open) |

#### Multi-Timescale Validation Requirements

When multi-timescale is implemented:
- Each timeframe's signal must show independent IC > 0 — **TESTED: IC negative for bar direction (mean-reversion at intraday). Signal works via trend-aligned sizing, not bar-level IC. Documented in phase_d_log iter 8-9.**
- Combined signal must show higher IC than any single timeframe — **TESTED: combo IC (-0.011) marginally better than 60m (-0.013). See above.**
- Cost sensitivity must be tested (lower TF = more trades = higher cost) — **PASSED: 2x cost Sharpe=0.85, 3x cost still profitable (+9.6% CAGR). iter 11.**
- Walk-forward must use temporal split on the LOWEST timeframe used — **TESTED: 4-fold temporal split, 3/4 folds positive, mean Sharpe 0.99. iter 12.**
- Report must show per-timeframe contribution — **DONE: per-TF IC, per-regime, cost sensitivity, walk-forward all in run_multi_tf_backtest.py. iter 7-12.**

### Optimization Theme Menu

Each loop iteration selects ONE theme:

| Theme | Focus |
|-------|-------|
| **A** | Multi-timescale intraday framework |
| **B** | Factor mining / training / strategy discovery |
| **C** | Intraday module hardening |
| **D** | Report / risk statistics enhancement |
| **E** | Performance optimization |

Selection priority:
1. Blocks research credibility?
2. High-leverage bottleneck?
3. Verifiable research gain?
4. Small-step achievable?
5. Evidence supports continued depth?

**Rule**: If multi-timescale framework has no minimal closed loop yet, it should be prioritized before pure alpha optimization.

### Per-Iteration Output Format (Chinese)

1. 本轮主题 (A/B/C/D/E)
2. 本轮目标
3. 为什么这轮优先做它
4. 做了什么
5. 修改了哪些文件
6. 跑了哪些测试/实验
7. 结果如何
8. 当前发现的新问题/新机会
9. 剩余风险
10. 下一轮建议方向
11. TODO checklist（更新后）

### Hard Rules

1. **小步快跑**：每轮一个主目标，优先可验证 patch
2. **不假装完成**：代码存在 ≠ 链路闭环，手工跑 ≠ 测试覆盖
3. **方向自适应**：允许切主题但必须基于本轮结果解释
4. **因子走漏斗**：LLM 只做 candidate generation，不做最终裁判
5. **不破坏核心约束**：long-only, no-margin, risk constraints, QQQ rule, pricing semantics

### Environment
- Python: `/home/zibo/miniconda3/envs/pqs/bin/python`
- Tests: count tracked in `data/baseline/latest.json` (refresh via `python dev/scripts/baseline/build_research_baseline_snapshot.py`); as of 2026-04-22 around 1300+ passing
- Key data (yfinance provider, legacy): daily (37 symbols, 2007-2026), 60m (32 symbols), 30m/15m (32 symbols, 60d)
- **Key data (new 1m pipeline):** see "1m Bar Pipeline" section below

## Module CONTEXT.md 索引(2026-05-19 reorg)

CLAUDE.md 是 context 入口,**仅留项目级**(不变量/纪律/架构/概括/Phase 框架/Key Files/Scripts/Multi-TF 框架)。各模块的**历史与契约细节** content-preserving 搬迁至模块文件夹下 `CONTEXT.md`(无删改,可 grep 回溯):

| CONTEXT.md | 承接 |
|---|---|
| `core/data/CONTEXT.md` | 1m Bar Pipeline / Trades Backfill / Data Provenance Sidecar 细节 |
| `core/factors/CONTEXT.md` | Factor Pipeline Contract 细节(PRODUCTION/RESEARCH 两 registry、promotion flow) |
| `core/intraday/CONTEXT.md` | Multi-TF Timing Contract 实现细节(`decide_timing` API 等;框架本身留下方 Phase D §Multi-Timescale) |
| `core/notify/CONTEXT.md` | Notify Module backends/用法 |
| `core/mining/CONTEXT.md` | 研究/挖矿/Phase 完成史:Deep Mining 50r / RCMv1 / Phase E / Track C cycle #01-#09 / PRD-E TAA / Bucket A-Macro / Post-cycle10 / SPY off-by-one / PEAD / P0-gov / ML-redo |
| `core/research/CONTEXT.md` | Track A/B/C/D 基建史 / Concerns A/B/E / NAV orthogonality tier / Generic NAV runner / Framework Completion PRD / Older TODO |
| `core/research/forward/CONTEXT.md` | Forward OOS 史(R-fwd-1/2/3 / F PRD)/ RCMv1+Cand-2 terminated / Trial9 全审计 / trial9_002 / chart_native_s1 forward 细节 |
| `core/options/CONTEXT.md` | Options Research Track 全细节+史(含 daily ritual / anti-patterns) |

> 纪律保全:4-round self-audit 方法论 = memory `feedback_self_audit_methodology` + `docs/checkpoints/20260430-self_audit_methodology.md`(本次仅搬其在 TODO 区的指针副本,纪律本体不在 CLAUDE.md 故无损)。docs/ 历史档案(`docs/2026*-claude_md_*_history.md`)沿用不变。

## Active State(2026-05-19,精简;细节见上表 CONTEXT.md)

**活跃 forward 候选**(daily ritual 见 `docs/forward_observation_log.md`;细节 `core/research/forward/CONTEXT.md`):
- `cycle06_31af04cf2ff9_evidence_v1` / `cycle08_3f40e3f4ed1a_evidence_v1` — core_alpha,re-init start 2026-05-19,Track-A PASS + sealed 2/2;**leakage 不受影响**(factor-composite,grounded+C-lite 双确认)。
- `chart_native_s1_evidence_v1` — evidence_only,start 2026-05-19。**⚠ LEAKAGE CAVEAT**:原 17/17 Track-A PASS 是 leakage-inflated,leakage-correct 后 FAIL;Option A 保留+caveat,β 不 refit。见 `data/research_candidates/chart_native_s1_evidence_v1_CAVEAT.md` + `docs/memos/20260518-chart_native_s1_evidence_leakage_caveat_decision.md`。所有 forward 判读/TD60 必引此 caveat。
- `pead_sue_trial1_evidence_v1`(evidence_only,独立轨)/ `spy_8otm_bull_put_v1`(options sleeve)/ `simple_baseline_v1`(baseline soak)— 见 forward/options CONTEXT.md。
- `trial9_diversifier_001/002` — **RETIRED**(completed_fail),仅 forensic。

**进行中的工作**:PRD-1/2/3(`docs/prd/20260518-prd{1,2,3}_*.md`)经 `/loop` 推进;执行账本 SoT = `docs/memos/20260518-prd123_execution_ledger.md`;互审+顺序 = `docs/memos/20260518-prd123_cross_audit_and_execution_order.md`。PRD-1 P1.1/P1.2/P1.3 ✅(leakage-correct 仅 chart_native_s1 受影响,已 caveat;cycle06/08 grounded+C-lite 确认不受影响)。

> 本节为入口级精简;任何"它是怎么来的/历史/契约全文"一律去对应 `CONTEXT.md`(grep-able,未删改)。
