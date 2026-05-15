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

### 1m Bar Pipeline

Multi-source 1m bar ingest, stored RAW (unadjusted) under
`data/intraday/1m/<SYMBOL>.parquet`, aggregated up to 5/15/30/60m +
daily. Splits applied at READ time via `BarStore.load(adjusted=True)`
using `data/ref/splits.parquet`. Sources: Polygon flat files
(2015-2023), per-ticker CSV (2024-2025/11 stocks-only), C-drive CSV
(2025-12+ stocks-only). ETF gap auto-filled from yfinance fallback.

Key API: `from core.data.bar_store import BarStore`.

Full pipeline details (source layouts, schema, validated reliability,
build scripts) archived in
`docs/20260424-claude_md_phase_e_history.md` §1m Bar Pipeline.

### Trades Backfill Pipeline

Separate ingest path for ETF 2024+ bars (upstream CSV is stocks-only).
Reads encrypted tick-level zips (`trades_v1_YYYY-MM-DD.csv.gz`),
aggregates to 1m bars with extras (vwap, block_n, exchange shares).
Strategy B merge: only writes tickers not already in the `.staging/`
dir, preserving existing stocks_csv bars. Filter rules pinned via
`trades_v2_late_report_dedup_2026-04-19` rule-version.

Hard rule: new ingest scripts MUST write synchronously to
`data/ref/bar_provenance.parquet`.

Full ingest scripts / resilience design / filter rule list archived
in `docs/20260424-claude_md_phase_e_history.md` §Trades Backfill.

### Data Provenance Sidecar

Every (symbol, freq) bar range carries source metadata in
`data/ref/bar_provenance.parquet`. Source types: `polygon_gz`,
`stocks_csv`, `stocks_csv_c_drive`, `trades_backfill`, `yfinance_daily`,
`yfinance_fallback`. Used by: cross-source merge sanity check, factor
guard (volume-sensitive factors masked for `trades_backfill` tickers),
report per-epoch attribution.

Read via `BarStore.load(...).attrs['provenance']` or
`store.get_provenance(symbol, freq)`. Full schema + factor-guard
config archived in `docs/20260424-claude_md_phase_e_history.md`
§Data Provenance Sidecar.

### Factor Pipeline Contract

Single source of truth: `core/factors/factor_registry.py`. Two
registries with strict **directional** separation (production drives
execution; research is read-only at the execution boundary):
- `PRODUCTION_FACTORS` (7): only these drive execution; changes
  require user authorization
- `RESEARCH_FACTORS` (143 as of PRD 20260512 Bucket A/B/C/Macro
  expansion; up from 64 baseline): available for IC / OOS / regime
  research; may share a NAME with a production factor (e.g.
  `drawup_from_252d_low`) so long as the two implementations are
  numerically identical — see `factor_registry.py:213-220`.
  **Source-path split**: OHLCV factors come from
  `core/factors/factor_generator.generate_all_factors`; fundamental
  / sector / macro factors come from separate `compute_*` functions
  (different input signatures — EDGAR cache / sector_map / FRED).
  `scripts/run_research_miner.py::_build_factor_panel_map` merges
  all four paths.

`MultiFactorStrategy` gate: unknown names in `factor_weights` are
logged at WARNING and DROPPED — prevents research names silently
reaching execution. `MultiFactorSpace._TUNED_FACTORS` asserts
consistency at miner startup.

Promotion flow (manual, one-way): RESEARCH → PRODUCTION requires
registry addition + `MultiFactorStrategy.generate()` inline impl +
`_TUNED_FACTORS` update + passing full acceptance. Full promotion
steps + shadowed-research map archived in
`docs/20260424-claude_md_phase_e_history.md` §Factor Pipeline Contract.

### Multi-TF Timing Contract

Multi-timescale framework is a **timing / execution / risk layer** on
top of daily MFS, NOT a standalone alpha system (naive bar-direction
voting strictly underperformed 60m-only baseline).

Role by TF: 60m = primary context (can VETO to scale=0); 30m =
confirmation / confidence penalty; 15m / 5m = defer trigger only,
never flip direction (long-only).

Canonical API: `core.intraday.multi_timescale.decide_timing(ctx,
symbol, base_weight, daily_side) -> TimingDecision` with fields
`{execute, timing_scale, effective_weight, higher_tf_vote, reason}`.
Invariants enforced by `tests/unit/intraday/test_timing_decision.py`.

Legacy `evaluate_cross_tf_signal` / `CrossTFSignal` shim kept for
back-compat. Full role table + validation evidence +
`validate_timing_value.py` results archived in
`docs/20260424-claude_md_phase_e_history.md` §Multi-TF Timing Contract.

### Notify Module

Channel-agnostic notifier (`core.notify`). Backends: `wecom_bot`
(WeChat Work webhook, recommended), `server_chan`, `stdout`, `null`.

```python
from core.notify import get_notifier
n = get_notifier()  # reads config/notify.yaml
n.info("title", "body"); n.error("kill switch", "...")
```

All sends return `SendResult` (never raises on transport failure).
Rate limit + min_level gating built-in. Credentials via env var
expansion (`${PQS_WECOM_WEBHOOK_URL}`).

### Current TODO Checklist

**Completed phases** (one-line summaries; full tables moved to
`docs/20260424-claude_md_phase_e_history.md` on 2026-04-24):

- **Deep Mining 50-round** (2026-04-22 ✅) — 7 tracks × 50 rounds;
  synthesis `docs/20260422-deep_mining_50round_final_synthesis.md`
- **RCMv1 20-round** (2026-04-24 ✅) — R17 converged spec + R18
  acceptance PASS + R20 S1 candidate memo;
  `docs/20260424-rcm_v1_final_synthesis.md`
- **Codebase Audit v1** (2026-04-24 ✅) — 3 rounds, 0 functional bugs
- **Codebase Audit v2** (2026-04-24 ✅) — 3 rounds, 3 `--help` bugs +
  63 unused imports fixed; baseline 1386→1536 tests
- **Phase E Governance + Paper Layer** (2026-04-24 ✅) — 14 rounds;
  `candidate_registry` + `frozen_spec` + paper CLI pipeline;
  RCMv1 @ S2_paper_candidate; `docs/20260424-phase_e_final_synthesis.md`
- **Phase E-post + Candidate-2** (2026-04-24 ✅) — 8 rounds; 5 E-post
  gaps + Candidate-2 `{ret_5d, rs_vs_spy_126d, hl_range}` equal-weight
  @ S2_paper_candidate; `docs/20260424-phase_e_post_cand2_final_synthesis.md`
- **Data-integrity round-3** (2026-04-25 ✅) — 6 steps. Single
  canonical source = polygon 1m → daily, label = real ET trading
  day, two-tier N_min (350/300), incomplete-day quarantine policy,
  splits.parquet TJX+GOOGL fixes. `data/daily/*.parquet` rebuilt
  for 78 syms (BRK-B drop). 4 paper cells re-run drift = 0 bps but
  NAVs −5 to −71 pp vs pre-step3b (largest: 2022 Cand-2 +74.57% →
  +3.47% honest). Headline-4 docs refreshed; full caveat sweep done.
  Standing freeze (universe / mining / Candidate-3 / OOS / spec
  changes) remains. `docs/memos/20260425-data_integrity_round3_close.md`

- **OOS Framework MVP R1-R7** (2026-04-25 ✅) — 7-round ralph-loop
  per `docs/prd/20260425-oos_mvp_ralph_loop_execution.md` derived
  from PRD v3 `docs/prd/20260425-oos_validation_framework_codex_v3.md`.
  Lineage `oos-mvp-2026-04-25`. Shipped: `core/research/robustness/`
  (window schema + runner) + `core/research/concentration/` (M12
  warning + extreme tier, report-only) + watch_exposure section in
  master + drift reports + `core/research/forward/` (manifest schema
  ONLY, no runner per PRD v3 §B) + integration smoke + negative
  simulation. R2 numbers (+62.76% / +191.57%) are **pseudo-OOS
  robustness only, NOT deployable OOS** (PRD v3 §1.1+§1.3). Closeout:
  `docs/memos/20260425-oos_mvp_close.md`. OOS-framework workstream
  auto re-frozen at OOSMVPDONE; reopening forward execution
  requires a new PRD round.
- **OOS MVP audit fix — M12 weighted thin gate** (2026-04-25 ✅) —
  per `docs/memos/20260425-m12_review_decision.md`. Replaced the
  pre-fix binary thin-data gate with a weight-day-weighted share
  (Σ share[s] × thin_data_pct[s]) which is the PRD-§C-thresholds gate
  going forward. Old binary share kept as `thin_data_binary_share`
  diagnostic only. **Cand-2 unfrozen** (weighted 5.19% → warning,
  narrative_permission: allowed); **RCMv1 still frozen** (weighted
  14.97% > 10% extreme — real, not implementation artifact). pytest
  1681 → 1685 (+4 audit regression tests A/B/C + percent-scale).

- **Research cycle 2026-04-26 #01** (2026-04-26 ✅, **0 nominee**) —
  partial unfreeze authorized in
  `docs/memos/20260426-research_layer_partial_unfreeze.md`. Pre-
  registered immutable criteria yaml at
  `data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml`
  (sha256 `5e88d0c…d03ad28` recorded in commit `4100f7b`). 200-trial
  TPE mining on the 78-symbol × 2007-2023 panel produced top trial
  `62445bdc62ae` with composite `beta_spy_60d × amihud_20d × mom_126d`
  (IC_IR=1.04 full-period, 4/4 walk-forward folds positive). FAILED
  G2.A on `watchlist_total_share=39.50% > 30% ceiling` — exactly the
  failure mode the strict ceiling was designed to prevent. Per
  criteria immutability, no retroactive softening: cycle closes
  0-nominee. Closeout memo:
  `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`.
  Research-mining workstream auto re-frozen at this boundary;
  forward-OOS observation of RCMv1 + Cand-2 unaffected.

- **Track C cycle 2026-04-30 #01** (2026-04-30 ✅, **0 nominee**,
  Tier 2 sibling-by-construction-and-factor-overlap) — first
  controlled-mining cycle under post-Track-A alternating-regime
  temporal split + post-A++ pool reachability contract. Pre-
  registered immutable criteria yaml at
  `data/research_candidates/track-c-cycle-2026-04-30-01_promotion_criteria.yaml`.
  TWO mining runs under same lineage:
  (a) **Pre-A++ run** (commit `f770d05`, sha256 `95027106…`): 49
      archived trials with FAMILIES_V1's 33 factors. INVALIDATED
      because search space did not satisfy yaml's
      `factor_registry_pool: RESEARCH_FACTORS` declaration (Cand-2
      anchors `ret_5d`/`hl_range` unreachable; `mom_12_1` unreachable).
      Pre-A++ artifacts preserved at
      `data/ml/research_miner/track-c-cycle-2026-04-30-01.preAplusplus/`.
  (b) **Post-A++ run** (commit `da036da`, sha256
      `edda90b4…d05a`): A++ patch ships FAMILIES_V2 (6 families, 64
      reachable), pool→family selector, layered reachability + panel-
      availability assertions, sampler-time exclusion filter, +
      `mining_config.explicit_exclusions` for 3 intraday-dependent
      factors with unmet daily-mining data dependency. Mining: 200
      trials / 146 finite / 60 archived. Best IC_IR 0.6562 on top
      trial `beta_spy_60d × mom_12_1 × volume_ratio_20d` — STILL
      shares `beta_spy_60d` with RCMv1 verbatim, family-tuple (A,B,C)
      identical to RCMv1, same long-only × monthly × top-N
      construction.
  **Construction-collapse hypothesis empirically confirmed**: 33→61
  factor expansion (with 17 newly-reachable intraday/microstructure/
  short-reversal factors) produced zero archived trials in Family E
  or F at 21d horizon; TPE convergence is on construction not factor
  zoo. 2026 sealed window NOT consumed. Closeout:
  `docs/memos/20260430-track_c_cycle_2026-04-30-01_close.md`. Cycle
  #02 design (when authorized) should prioritize construction-DOF
  expansion (C-3 beta-controlled / C-1 weekly cadence / C-4 cross-
  asset / C-2 long/short), not further factor-zoo expansion.
  Research-mining workstream auto re-frozen at this boundary.

- **Track C cycle 2026-04-30 #02** (2026-04-30, ARCHIVED 2026-05-01,
  **numerical results NOT reliable**) — second controlled-mining
  cycle; single-variable diff vs #01 = +C-1 weekly cadence. Mining
  produced top-1 IC_IR=1.0592 on `beta_spy_60d × mom_12_1 ×
  volume_ratio_20d` — IDENTICAL composite to cycle #01's top-1 (3-of-3
  factor identical). C-1 horizon hypothesis fully refuted at the IC
  level (weekly + global top-N produces same sibling as monthly +
  global top-N). **ARCHIVED post-execution** (Task #49 / heterogeneous
  split-adjustment fix on 2026-05-01) — the daily price panel cycle
  #02 mined on had inconsistent split scaling for 13/78 universe
  symbols (LRCX 2015-04 alternating $72/$7 day-to-day etc.); the
  numeric IC_IR=1.0592 / NAV trajectories / Pearson correlations are
  not reproducible. Factor identity verdict (cycle #02 = cycle #01
  sibling) survives the data corruption (verified by post-fix harness
  re-run on top-1 spec). Yaml + archive marker preserved per
  immutability contract:
  `data/research_candidates/track-c-cycle-2026-04-30-02_ARCHIVED.md`.

- **Track C cycle 2026-05-01 #01** (2026-05-01, INVALID, do not cite) —
  yaml typo `mining_config.trials: 200` instead of canonical
  `n_trials: 200` caused miner CLI yaml→cli mapping to silently fall
  back to default 50 trials; only 3 archived. Yaml sha256 `5df2c305…`
  preserved. **Superseded by `track-c-cycle-2026-05-01-02`** (same
  axis, corrected yaml). Operator self-audit caught (not user); first
  example of why the "依赖捋清楚" rigor matters at yaml field level.

- **Track C cycle 2026-05-01 #02** (2026-05-01 ✅, **0 nominee**,
  10/10 trials Tier 2 sibling-by-NAV) — first cap-aware-construction
  cycle. Yaml sha256
  `9fa478f0ffad33dc2d40eff8ec63b2e86799404b06695b2626390970f169ff23`
  (commit `1edc42b`). Cap-aware = cluster_cap=0.20 + max_single=0.10
  over `core/research/risk_cluster_map.STOCK_RISK_CLUSTER_MAP` (17
  single-layer trade-level clusters, 54 stocks, 25 ETFs excluded) at
  top_n=10 monthly 21d horizon, full RESEARCH_FACTORS pool. Mining
  200 TPE trials, 58 archived. Best IC_IR=1.187 on `rs_vs_spy_126d ×
  drawup_from_252d_low × market_vol_ratio` — DIFFERENT from cycle
  #01/#02 sibling (sibling factors `beta_spy_60d` / `mom_12_1` appear
  at most once each in top-10; 13 unique factors across 30 top-10
  slots). **However**: cap-aware harness eval over top-10 + RCMv1 +
  Cand-2 reference NAVs found 100% (20/20) of pooled-raw-Pearson
  pairs ≥ 0.85 reject threshold (median 0.902, range 0.852-0.947).
  Residual after stripping shared SPY+QQQ beta: median 0.64; only
  1/20 above the 0.70 warn threshold. **Headline finding**: ~85% of
  NAV correlation is structural shared market beta of any long-only
  top-N portfolio over a 54-stock universe; cluster_cap construction
  does NOT break it because the universe itself is the binding
  constraint. Cluster_concentration_max ~0.30 vs cap_aware target
  0.20 is intra-month price drift between monthly rebalances, not a
  selector bug. Closeout:
  `docs/memos/20260501-track_c_cycle_2026-05-01-02_close.md`. Eval
  artifact:
  `data/ml/cycle03_evaluation/track-c-cycle-2026-05-01-02/evaluation_summary.json`.
  Research-mining workstream auto re-frozen. **Next-axis
  recommendation: C-4 cross-asset** (universe expansion to bonds +
  commodities + cash anchor) — directly attacks the structural cause
  this cycle exposed. C-1 weekly cap_aware secondary; C-2 long-short
  violates `no-short` invariant (out of scope).

- **Track C cycle 2026-05-01 #04 cross-asset** (2026-05-01 ✅,
  **0 nominee**, 10/10 Tier 2 by R41 v2 with NAV correlation) —
  first cap_aware_cross_asset cycle (53 stocks + 6 cross-asset ETFs:
  TLT/IEF/SHY/GLD/BIL/SHV; USO/SLV excluded). Yaml sha256
  `b07ece9c9b8c82325d48a0376a871e100f934cab79da98c227dca431fbdd9efc`
  (commit `56457f3`). Construction: cluster_cap=0.20 +
  max_single=0.10 + asset_class_caps={equities=0.70 / bonds=0.40 /
  commodities=0.20 / cash_anchor=0.30}, 22-cluster unified map (17
  stock + 5 cross-asset). 200 TPE trials, 62 archived. P0a-P0d prep
  shipped commit `cc582a2`: distribution sidecar
  `data/ref/distributions.parquet` + `BarStore.load(adjusted_total_return=
  True)` (CAGR parity vs yfinance auto_adjust ≤ 0.01% on 6/6 ETF) +
  P0b 2009-2014 backfill (9054 new daily rows; BIL phantom-split
  handled via yfinance-split-undo) + P0c risk_cluster_map cross-asset
  extension + P0d composite_evaluator cap_aware_cross_asset mode.
  P0e shipped commit `56457f3`: cycle #04 yaml + universe.yaml
  extension + eval pipeline. Closeout shipped commit `dac4176`:
  closeout memo + cross_cycle_nav_correlation post-eval.

  Two character clusters in top-10:
  (a) **Cluster A** (4 trials, drawup+amihud anchored): pooled raw
      NAV corr **0.66-0.70** vs RCMv1/Cand-2/Cycle03-top — first
      cycle ever achieving < 0.85 raw (PARTIAL DIVERSIFIER per yaml).
      Max_dd -16% to -18% (vs cycle03's -27%). Tier 2 by
      factor-overlap=2 with RCMv1.
  (b) **Cluster B** (6 trials, vol-anchored): pooled raw 0.91-0.94
      (NAV reject); max_dd -27% (similar to cycle03); 2025 vs_qqq
      +9.8% to +10.6% (8/10 trials pass hard gate; trial 8 best at
      +10.5% with -19% DD vs QQQ -22.86%). Tier 2 by NAV.

  **Empirical headline**: cap_aware_cross_asset DOES break NAV
  correlation for some mining outcomes (Cluster A first <0.85), but
  mining objective converges on RCMv1-anchor factors (drawup +
  amihud) → factor-overlap rule disqualifies the NAV-diverse trials.
  Breaking mechanism = asymmetric factor coverage on bonds (amihud
  doesn't compute on cash → composite NaN → selector defaults).

  **Process bug + fix**: cycle04 eval shipped with empty
  nav_correlation_vs_existing_pair → R41 v1 verdict was
  factor-overlap-only and incorrectly reported 5 Tier-1 nominees.
  Caught in self-audit; fixed via
  `dev/scripts/cycle04/cross_cycle_nav_correlation.py` post-eval.
  R41 v1 → v2 verdict shift: 5 false-positive Tier 1 → all Tier 2.
  Pipeline lesson: cross-cycle correlation must be in main eval for
  cycle #05+, not deferred to post-eval.

  Sealed 2026 panel NEVER read. Research-mining workstream auto
  re-frozen. **Next-cycle hypothesis (NOT pre-registered, awaits
  user authorization)**: cycle #05 should ban
  `drawup_from_252d_low + amihud_20d` in
  `mining_config.explicit_exclusions`; force factor diversity past
  RCMv1 anchors. Same construction + thresholds.

  **Operator-added enhancements (validated)**: smoke-abort gate
  (cycle03-top1 spec smoked at 34% non-equity → mining authorized);
  2025 QQQ soft-miss trade-off pre-registration (informational only;
  trial 2 partially triggered).

  **Cycle #06 stop rule pre-committed**: if cycle #05 also 0
  nominee, no cycle #06 mining; pivot strategically per collaborator
  §"更宏观的判断" (objective / data / frequency / tools / strategy
  type changes — long-only relaxation requires user explicit-go).
  Closeout:
  `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md`.

- **Track C cycle 2026-05-01 #05 anchor-sensitivity diagnostic**
  (2026-05-01 ✅, **0 nominee under strict CLAUDE.md QQQ rule**, 7 Tier 1
  R41 verdicts but only trial 9 passes yaml hard blockers, fails project
  invariant on OOS walk-forward window-mean) — first cycle to produce ANY
  Tier 1 R41 classification. Yaml sha256
  `ce559a0ac97a7eb36243de7494c44650ea0779839ec70bc159b94da06a2cbaf7`
  (commit `5110266`). Single-axis diff vs cycle #04 = ban
  `drawup_from_252d_low + amihud_20d` in `mining_config.explicit_exclusions`.
  Mining 200 trials, 149 finite, 44 archived. Best IC_IR=+0.5483 (down 54%
  from cycle04 +1.1991). Top-1: `rs_vs_spy_126d, max_dd_126d, ret_2d`.
  Top-10 R41: 7 Tier 1, 3 Tier 2 (NO Tier 1-conditional, NO Tier 5).

  **Trial 9 (`6c745c601a47`) deep audit** — passes yaml hard blockers BUT
  fails CLAUDE.md project invariant:
  - Spec: `beta_spy_60d (1/3) + max_dd_126d (1/3) + ret_1d (1/3)` (A/B/F)
  - cum_ret 502.6% / sharpe 0.78 / full max_dd -24.5% / vs_qqq full +6.3%
  - Per-year max_dd: 2018=-15.2%, 2019=-6.8%, 2021=-6.0%, 2023=-9.3%,
    **2025=-18.2%** (all > -20% ✓)
  - Per-year vs_qqq: 2018=+3.7%, 2019=-13.2%, 2021=-3.3%, 2023=-19.8%,
    2025=+9.6% → **5-window mean = -4.59% < 0** (CLAUDE.md QQQ Rule
    HARD constraint FAILS)
  - Stress slices: covid_flash max_dd=-13.3%, rate_hike_2022=-15.8% (both
    > -25% ✓)
  - NAV: raw 0.54-0.69 vs all 5 anchors (`partial_diversifier` band);
    residual 0.07-0.36; factor_overlap_max=1 (only beta_spy_60d shared)
  - Asset-class: equity 28.5% / bond 15.4% / commodity 6.3% / cash 10.4%
    / non_equity_avg 32.1% (HIGHER than cycle04 trial 8 ~24%)

  **Hypothesis verdict**: H1 (anchor-specific) SUPPORTED — mining found
  Tier 1 with overlap=0/1 with RCMv1; max_dd_126d substitutes drawup in
  Family B for 4/7 Tier 1 trials. H3 (drawup+amihud binding at IC) PARTIAL
  — IC_IR drop 54% confirms IC anchoring. H2 (low-vol attractor universal)
  PARTIAL — trial 9 has low-vol character (max_dd_126d) but mixed with
  short-momentum + market beta.

  **Strategic review options pre-authored, NOT pre-selected** (yaml
  pre-commit table didn't exactly fit Tier-1-but-fails-invariant outcome
  shape):
  - Option A: User softens CLAUDE.md OOS walk-forward window-mean rule
    for `diversifier` role (NOT `core_alpha`). Directional decision
    required.
  - Option B: D3b regime-aware mining objective (~1 week eng).
  - Option C: Two-stage allocation architecture (4-6 week PRD).
  - Option D: Lightweight diversifier role tag (1-2 day eng; pairs with A).
  - Option E: Hold + observe (default if user authorizes nothing).
  - Option F: Universe expansion (cycle #06 candidate IF A+D fails forward).

  Operator's recommended sequence (NOT user-locked): A+D → forward observe
  trial 9 as diversifier → if forward unhealthy, consider B; if forward
  healthy + multi-candidate, consider C as architecture pivot.

  **Methodology findings (R4 boundary)**:
  - smoke_abort_clause's "5-10 trial smoke" wording is misleading — at
    min_families=3 + cardinality=3 + max_per_family=2, prior probability
    of valid spec ~2.7%/trial → 80% of all-fail in 8 trials normal
    sampling. Cycle04 actually ran fixed-spec smoke. Yaml clause needs
    rewording for cycle #06+ if used.
  - Anchor max_dd full-period contains 2008-2009 (-44% to -48%), making
    Tier 1-conditional c3 lenient. Future cycles with overlap=2 candidates
    must use shared-window max_dd.
  - CLAUDE.md QQQ Rule "OOS walk-forward (average)" wording ambiguous —
    interpreted as Track A per-validation-year mean for cycle #05; if user
    interprets as rolling-window walk-forward (separate framework), trial
    9 standing changes.

  Sealed 2026 panel NEVER read. Research-mining workstream auto re-frozen
  at this boundary. Cycle #06 NOT auto-fired per pre-committed stop rule.
  Closeout: `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md`.

- **PRD-AC v1.1 implementation + Track C cycle 2026-05-06 #01** (2026-05-06 ✅,
  **0 nominee** per Track A acceptance + 4 strategic findings) — first
  v2_nav_based mining cycle. PRD: `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md`
  (v1.1 post-critique). 6 implementation commits (`f2b6059..3fec344`):
  Phase 1 schema + ObjectiveWeights extension; Phase 2 round 1 NAV
  evaluator gate + SPY-residual anchor + I20 detector; Phase 2 round 2
  I9 boundary mask fix + wall-clock benchmark (median 19.36s/trial);
  Phase 3 round 1 holding_freq end-to-end + sr_defer sampling stub
  (round 2 SR-defer full integration deferred); Phase 4 prep + cycle06
  yaml + analysis script. Yaml sha256
  `7b3e20dd8485900c0307c0ef89adc0228ccfb42964d54447550a52184a1bc1df`.
  Mining: 200 trials / 149 finite / 66 archived; top-1 trial
  `bab8cfe88af3` features `drawup_from_252d_low + trend_tstat_20d + ret_2d`
  (sibling pattern with cycle04/05 continues). Hypothesis tests:
  H1 Spearman v2/v1 = 0.89 (FAIL — too IR-heavy at 0.7/0.15 weights);
  H2 holding_freq monthly=49/weekly=10/daily=7 (FAIL by archived count;
  process finding: H2 should test SAMPLED not ARCHIVED); H3 v2 top-1
  nav_sharpe 0.565 < v1 top-1 0.664 (FAIL — Pareto regression);
  H4 anchor_corr 100% < 0.50 (PASS — Option β viable but suspiciously
  clean). Track A acceptance evaluator on top-3 trials: 0/3 pass; all
  fail validation_aggregate_excess_vs_spy/qqq + beta_to_qqq. Cycle
  stop rule fires per cycle04 close memo; strategic pivot to PRD-E
  (TAA) authorized. Closeout:
  `docs/memos/20260506-cycle06_closeout.md`. Phase 3 round 2 (SR-defer
  full mining integration) + cycle07 reweight authorization deferred
  pending forward observation evidence. Research-mining workstream
  auto re-frozen at this boundary.

- **cycle07-to-fleet master ralph-loop + Track C cycle 2026-05-07 (cycle07a)
  + 2026-05-08 (cycle08) + Trial 3 NAV-correlation Red verdict** (2026-05-06
  through 2026-05-07 ✅, **0 forward init**, 1 Track A nominee post-P0-fix
  but Red NAV verdict → evidence-only) — 13-round ralph-loop bundling
  cycle07a + cycle08 mining + 4 audit memos + retroactive Track A re-eval
  fix. Master PRD `docs/prd/20260424-cycle07_to_fleet_master_prd.md`.

  **cycle07a (2026-05-07)** — single-axis diff vs cycle06 = factor reweight
  (drawup_from_252d_low + 短动量 anchor 强化). Yaml sha256
  `1295911ab8949194c3eebf48...` (commit `2fc5198`). Mining 200 trials /
  finite ~149 / 30 archived; top-3 Track A original verdict 0/3 PASS.

  **cycle08 (2026-05-08)** — single-axis diff vs cycle07a = ObjectiveWeightsV3
  regime-conditional weights (BEAR-IC / NEUTRAL-IC / BULL-IC scoped composite
  evaluator). Yaml sha256 part of cycle07-fleet R7 prep (commit `d0b1c4c`).
  Mining 40-trial smoke (NOT full 200) / 11 archived. Track A original
  verdict 0/3 PASS. Smoke caveat preserves yaml integrity (yaml=200, runner
  override --n-trials 40 per R7 prep).

  **P0 wiring bug discovery + fix (2026-05-07)** — R12 audit reverse-validate
  caught suspicious "16 of 17 gates correlated FAIL with beta=present" pattern
  across 9 trials. Root cause: `dev/scripts/cycle{06,07a,08}/cycle*_track_a_eval.py`
  built `metrics["beta_to_qqq"]` (top-level scalar) but
  `core/research/temporal_split_acceptance.py:_eval_beta_gate` resolves
  nested `metrics["beta"]["beta_to_qqq"]` (mirroring yaml schema). Pre-fix
  gate fail-closed silently → all 9 trials had false-negative beta gate
  FAIL despite actual betas well below 0.85 cap. Fix shipped commits
  `5873653` + `9cacab3` (evaluator scripts + 6 regression tests
  `tests/unit/research/test_beta_metric_path_canonical.py`). Postmortem:
  `docs/audit/20260507-beta_metric_path_bug_postmortem.md`.

  **Post-fix 9-trial Track A re-eval (2026-05-07)**:
  - cycle06 (`bab8cfe88af3` / `31af04cf2ff9` / `a9e39c21feed`): 0/3 PASS,
    all fail `validation_aggregate_excess_vs_spy` (vs_spy aggregate is the
    real binding gate; not beta).
  - cycle07a (`81cfb5f4c4f5` / `f133a18d1495` / `1e771580f486`): **1/3 PASS**.
    Trial 3 `1e771580f486` (drawup_from_252d_low + mom_63d + ret_1d, monthly,
    cap_aware) is sole survivor — 17/17 gates PASS, 17yr cum_ret +1016.75%
    vs SPY +231.94% / QQQ +496.38%, sharpe 1.08, full max_dd -20.0%, beta
    0.534, top1 14.5% / top3 36.6%, 2025 holdout +25.1% (+8.4% vs SPY),
    covid_flash +3.6% (vs SPY -13.8%), rate_hike_2022 -7.3% (vs SPY -16.6%).
  - cycle08 (`8ac6bccbeed1` / `60998346d975` / `3f40e3f4ed1a`): 0/3 PASS,
    same vs_spy aggregate failure shape.
  Amendment memo: `docs/memos/20260507-cycle06_07a_08_track_a_post_fix_amendment.md`
  (cycle06+08 verdict UNCHANGED with revised gate-attribution; cycle07a
  Trial 3 = sole nominee).

  **Trial 3 NAV correlation pre-init gate (x.txt 2026-05-07 locked spec)**
  — pre-forward-init authorization required raw < 0.85 + residual < 0.50
  for all 3 pairs vs anchors. Harness:
  `dev/scripts/cycle07a/trial3_nav_correlation.py` (cycle04 cross-cycle
  template + cap_aware STOCK_RISK_CLUSTER_MAP). 16-year extended panel
  (cycle07a selector partition, 2009-2024). Output:
  `data/audit/cycle07a_trial3_nav_correlation.json`.

  | Pair | raw | residual_vs_spy | residual_vs_qqq |
  |---|---|---|---|
  | Trial 3 vs RCMv1 | **0.874** | 0.603 | 0.613 |
  | Trial 3 vs Cand-2 | **0.892** | 0.688 | 0.699 |
  | Trial 3 vs Trial 9 | 0.783 | 0.319 | 0.381 |

  **Verdict: RED** (raw ≥ 0.85 in 2 pairs; residual ≥ 0.50 in 4 of 6
  measurements). **Trial 3 NOT forward-init'd**; evidence-only memo
  records the structural finding:
  `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`.

  **Three structural findings (sibling-by-NAV root cause)**:
  - **Finding 1: drawup-anchor + monthly + top-N is the binding sibling
    geometry**. Trial 3 shares ONLY `drawup_from_252d_low` factor with
    RCMv1 (1 of 4) yet raw 0.874. Banning the FACTOR (cycle05) doesn't
    break the sibling pattern; banning the CONSTRUCTION does.
  - **Finding 2: Cand-2 sibling-by-NAV tighter than RCMv1**. Trial 3
    shares 0 of 3 factors with Cand-2 yet raw 0.892. Long-only top-10
    over 78-stock universe = MARKET-COVERAGE binding geometry; disjoint
    factors with same construction pick ~30-50% identical names monthly.
  - **Finding 3: Trial 9 (max_dd_126d) is structurally distinct**. Both
    use cap_aware monthly top-N yet raw 0.783 + residual 0.32-0.38. First
    cycle04-08 candidate where Family-B anchor swap (drawup → max_dd_126d)
    produces NAV-distinct behavior. Empirical confirmation that drawup vs
    max_dd is a real sibling boundary.

  **D.0 fleet allocator gate revision proposal (provisional, NOT
  ratified)**: D.0 (a) currently requires ≥ 2 Track A acceptance nominees;
  proposed tightening to ≥ 2 nominees AND pairwise raw NAV Pearson < 0.85
  across all fleet members on cycle04-canonical 16y extended panel.
  Under proposed rule, Trial 3 counts toward Track A nominee total (1 of 2)
  but does NOT count toward "additive fleet member" — D.0 (a) requires a
  next candidate that is BOTH Track A accept AND raw < 0.85 vs RCMv1 AND
  Cand-2 AND now Trial 3 (3-way constraint).

  **Cycle direction implication**: cycle04-08 + Trial 3 collectively
  demonstrate that cap_aware monthly top-10 over 78-stock universe CANNOT
  break sibling geometry by factor swap alone. Future cycle direction
  options (NOT pre-registered, awaiting user-go): construction DOF
  expansion (weekly / cross-asset / multi-horizon ensemble); universe
  expansion (78 → 200+ stocks OR add bonds/commodities permanently);
  strategy-type pivot (options sleeve in progress; intraday reversal /
  event-calendar untested); gate revision (relax 78-stock universe OR
  long-only invariant — requires user explicit-go).

  **Sealed 2026 panel NEVER read**. Research-mining workstream auto
  re-frozen. Cycle #09 NOT auto-fired per cycle04 stop rule + post-Trial-3-Red
  D.0 gate revision proposal. Closeouts:
  `docs/memos/20260520-cycle08_closeout.md` (cycle08 closeout, pre-fix);
  `docs/memos/20260506-cycle07_to_fleet_final_synthesis.md` (R13 final
  synthesis); `docs/audit/20260506-cycle07_fleet_audit_final_2.md` (R12
  audit, cycle07a R9 line retracted by amendment memo).

- **PRD-E v1.1 implementation (TAA / regime allocation)** (2026-05-06 ✅,
  **5/7 hard gates PASS — defensive sleeve confirmed, standalone alpha
  rejected**) — first non-mining strategy framework in PQS. PRD:
  `docs/prd/20260505-taa_regime_allocation_framework_prd.md` v1.1
  (post-critique). 3 phases shipped over 3 commits (`4bc85ab`,
  `288c3c0`, `281729b`):
  Phase 1 = regime_rules (V1 + V0_MINIMAL) + regime_label_generator
  (daily/monthly cadence + KL/Hamming) + asset_class_builder (universe
  → equal-weight target_wts). Phase 2 = taa_harness.run_taa_backtest
  + train-only smoke (4 variants V1/V0_MINIMAL × monthly/daily on
  partition_for_role(miner) panel). Phase 3 = taa_acceptance G1-G7
  evaluator + selector-panel validation run.

  **Phase 3 verdict (V1 + monthly + selector panel)**:
  - PASS: G1 2018 vs SPY +8.08% (BEAR year defensive value confirmed);
    G3 stress slices (covid_flash -4.73% / rate_hike_2022 -5.04%);
    G4 per-validation-year MaxDD ≤ 20% (max -4.42% in 2021);
    G5 BULL beta to SPY 0.008 (essentially zero); G7 full MaxDD
    -16.04% vs SPY -34.23% (half SPY's drawdown).
  - FAIL: G2 2025 vs SPY -11.20% (CLAUDE.md core role HARD; BULL year
    underperformance per PRD §7 acknowledged risk); G6 Calmar 0.073
    vs SPY 0.337 (HARD primary risk-adjusted; SPY's 10x CAGR offsets
    its 2.1x deeper drawdown).
  - Per-regime DD: BULL -4.89% / CRISIS -5.11% / NEUTRAL -10.26%
    (worst). CRISIS DD < 10% PRD-E target threshold ✓.
  - Standalone alpha verdict: NON-VIABLE (G2 + G6 fail). Defensive
    sleeve verdict: STRONG (5 of 5 defensive gates pass).

  **User directional decision 2026-05-06 = Option B**: close PRD-E1
  standalone path + PRESERVE TAA modules dormant for future fleet
  integration (PRD-E2 / Phase C-PRD-3). No alpha-first cost (modules
  don't run unless caller invokes); audit trail preserved. PRD-E2
  (forward observation runner integration) gated on user explicit-go
  + Trial 9 TD60 evidence (~2026-07-30).

  **Preserved (dormant)**: `core/research/taa/` (6 modules) +
  `tests/unit/research/taa/` (62 tests) + `dev/scripts/taa/`
  (2 dev scripts) + `data/audit/taa_phase{2,3}*.json`.
  Closeout: `docs/memos/20260506-prd_e_phase3_closeout.md`.

- **Bucket A + B + C + Macro factor library expansion + Signal-conf
  MVP Phase 1 skeleton** (2026-05-12 ✅, **+76 factors / 16 mining
  families / mining-search-ready**) — per
  `docs/memos/20260512-quant_factor_literature_synthesis_v2.md` (37
  topic literature review) +
  `docs/memos/20260512-bucket_abc_macro_mvp_schedule.md` (2-week
  schedule). User explicit-go Q1+Q2+Q3+Q4 = all yes 2026-05-12.

  Shipped across 18 commits in one session:
  - **Bucket A (24 OHLCV factors, families G/H/I/J)**: 6 volume
    microstructure + 3 4-quadrant + 6 consolidation + 3 higher
    moments + 3 anchor/reversal/BAB + 3 calendar timing
  - **Bucket B (41 fundamental factors, families K/L/M/N)**: SEC
    EDGAR companyfacts API ingest (210 MB cache, 52/59 stocks
    downloaded, ETFs skipped) + `core/data/{edgar_provider,
    fundamentals_store}.py` + 12 Piotroski + 3 Magic Formula +
    9 Beneish + 6 Altman + 5 capital return + 6 growth/leverage
  - **Bucket C (5 sector factors, family O)**:
    `config/sector_map.yaml` (59-sym manual GICS + 3 historical
    reclassifications incl. META/GOOGL 2018-09-28 Tech →
    Communication) + `core/data/sector_resolver.py` (PIT-aware)
  - **Macro (6 FRED factors, family P)**: 8-series FRED CSV cache
    (no API key needed; CPIAUCNS/FEDFUNDS/DGS10/DGS2/DTWEXBGS/
    DCOILWTICO/VIXCLS/UNRATE) + `core/data/fred_provider.py`
  - **Signal-conf MVP Phase 1 kernel**: `core/signals/signal_state.py`
    state machine (ARMED → CONFIRMED|EXPIRED with TTL); strategy
    class + multi-bar factors + ConfirmationPatternSpace + deferred-
    execution backtest deferred (~3-week follow-up scope)

  **Audit findings (R1-R3 live runs)**: 3 critical bugs caught + fixed:
    1. TTM cumulative double-counting (AAPL CFO TTM 283B vs real 118B,
       2.4×) — SEC EDGAR reports both standalone-Q and YTD-cumulative
       under same tag; fixed by duration-filter (60-100 days
       standalone Q only feed rolling-4 sum)
    2. Strict NaN propagation killed Piotroski for retailers/
       financials (WMT/CAT/GS/JNJ all NaN) — fixed via
       `sum(c.fillna(0))` + nan_mask only when ALL TTM flow inputs NaN
    3. Mask included balance-sheet (non-NaN earlier than TTM) leak
       composite=0 into pre-TTM window — fixed by dropping assets
       from mask logic

  **Post-fix AAPL 2024-12-31 sanity**: piotroski_f_score=8, magic
  earnings yield=3.08%, magic ROIC=47.2%, beneish M-score=-2.67,
  altman Z=10.97, buyback yield=2.80%, fcf yield=2.92%, fcf-to-assets=
  33.6%, revenue YoY=+7.8%, R&D intensity=6.66%. All within 1-6% of
  authoritative references.

  **Mining wiring (Round A)**: 10 new families G-P added to
  `core/mining/research_miner.py::FAMILIES_V2`; `scripts/
  run_research_miner.py::_build_factor_panel_map` extended to merge
  4 compute paths (OHLCV / fundamental / sector / macro) into single
  panel_map. Family-union contract enforced (143 reachable).

  **Round B smoke**: end-to-end miner CLI 3-trial random sampler
  against `--factor-registry-pool RESEARCH_FACTORS` PASS — all 10
  new families sampled from in trials (e.g. trial #2 drew
  {G:2,H:2,I:1,K:1,L:2,M:1,N:1,O:2,P:1}). Pipeline ready for cycle
  #09 when authorized.

  Test surface: 553 unit tests PASS (factors + data + signals +
  mining). Lineage `bucket-abcmacrosig-2026-05-12`.

- **Track C cycle 2026-05-12 #09** (2026-05-12, **INVALID MINING RUN**,
  sampler-architecture mismatch — NOT 0-nominee verdict) — first
  cycle on post-PRD-20260512 162-factor RESEARCH_FACTORS pool. Yaml
  sha256 `351e6e2ce004ef5a96a92ebe85f394ee193467dab78b60e4deb94c14ec0c424f`
  (commit `46ec4cd`, fix `fb81bbb`, final `3894af0`). Single-axis diff
  vs cycle08: factor_registry_pool=RESEARCH_FACTORS (162 not 67) +
  G_new_family_anchor HARD (≥1 anchor from G/I/K/L/M/N/O/P) +
  G_anti_sibling_nav 3-way (raw NAV Pearson < 0.85 vs RCMv1 / Cand-2 /
  Trial 9 v2) + drawup_from_252d_low + amihud_20d banned + 7 masked-dup
  banned per Z1 strict-train cluster r ≥ |0.99| (commit `aa0182e`) +
  v2_nav_based objective + monthly + cap_aware_cross_asset.

  Mining: 200 trials → **100% PRUNED at sampler stage, 0 backtest
  evaluations, 2.1 min wall-clock**. Root cause (R4 postmortem):
  `suggest_composite_spec` independent-family-sampling architecture
  was designed for cycle04-08's 4-6 families (P(valid spec)=2.74%).
  Today's 17-family expansion (Bucket A/B/C/Macro added G-Q) drops
  P(valid spec) to 0.0005% (100k Monte Carlo confirmed 0 hits).

  **NOT 0-nominee verdict** per yaml.stop_rule_post_cycle (which
  assumes "searched but didn't find alpha"). This is "didn't actually
  search" — INVALID mining run. yaml + launcher + closeout script
  preserved as forensic evidence; marker file
  `data/research_candidates/track-c-cycle-2026-05-12-09_INVALID.md`
  fail-closes the launcher. Postmortem:
  `docs/memos/20260512-cycle_09_sampler_architecture_postmortem.md`.

  **Operator R3+R4 audit failure analysis**: preflight R1+R2 missed
  the combinatorics check; 16-trial smoke ran but 0 archived was
  rationalized as "smoke too small". R4 should have asked "why did
  cycle08 work with same yaml params but cycle #09 doesn't?" Lesson
  added to [[feedback_audit_per_round_methodology]]: cycle-config
  changes crossing order-of-magnitude (family count / cardinality /
  universe size) must include numerical combinatorics sanity check.

  User explicit-go 2026-05-12 "同意 A 和 C 同时跑". Both Option A
  (sampler refactor) + Option C (alt-archetype A intraday reversal)
  shipped today:
  - **Option A**: `sampling_mode: family_first` added to
    `suggest_composite_spec` (commit `f41c7e5`). Default
    "independent" preserves cycle04-08 bit-for-bit. family_first
    architecture: pick k families first → pick 1 factor per family.
    P(valid spec) ≈ 100% by construction. yaml CLI plumbing:
    `mining_config.sampling_mode: family_first`. 10 new tests + 215
    regression PASS.
  - **Option C Phase 1**: `IntradayReversalStrategy` skeleton +
    config (commit `d7e48ed`). 13 unit tests PASS. Phase 2 (deferred-
    execution × BacktestEngine integration, ~1 week) + Phase 3
    (Track A acceptance) DEFERRED. PRD §11 4 directional questions
    PENDING user explicit-go before Phase 2 implementation.

  **cycle #09 re-fire** authorization: same sha256-locked yaml +
  Option A sampler refactor + `--bypass-invalid-marker` launcher
  flag. Decision NOT auto-triggered; user-go required.

- **Post-cycle10 strategic roadmap + K1 deferred-execution wrapper**
  (2026-05-13 ✅) — cycle10 closed 0-nominee (R7 fail-SPY risk
  realized per NAV-residualized objective). Roadmap memo v1 → v1.1 →
  v2 FINAL (commits `10838c5` → `a6aa4f0` → `7b12d85`): TC ceiling
  (Clarke-de Silva-Thorley 2002 FAJ, long-only TC=0.45-0.55) reframes
  bundle binding — legitimate attacks = horizon change (intraday) +
  cadence change (signal-driven) + cross-asset done RIGHT; universe
  expansion + LLM mining DON'T attack TC. D1 (200+ stocks) dropped
  with TC-ceiling reason replacing weak cycle04 n=1. D3 (LLM
  mining) DROP → DEFER until K1+T1 produces working construction.
  Signal seed library: 6 evidence-strong seeds (Faber 200-SMA /
  Connors RSI(2) / Donchian 20/55 / HY OAS / Zweig breadth thrust /
  GKM abnormal volume) + 3 orthogonal archetypes (trend /
  mean-reversion / cross-asset risk gate) for T1b + T2a. User 8/8
  explicit-go locked v2: T1a first then T1b∥T1c, PEAD+FOMC bundle,
  cycle11 3 objectives all-try, ML Phase 2 coupled with T2, F1+F2+F3
  all-do, K1 strict TDD, unified observe runner, seed library
  full-collect.

  **K1 ship (2026-05-13 evening)**: `SignalDrivenBacktest` wrapper at
  `core/backtest/signal_driven_runner.py` (212 lines) + 30-test TDD
  suite at `tests/unit/backtest/test_signal_driven_runner.py`. K1.1
  design audit `docs/audit/20260513-k1_deferred_exec_design.md`;
  K1.4 regression report `docs/audit/20260513-k1_regression_report.md`;
  K1.5 closeout `docs/memos/20260513-k1_deferred_exec_ship.md`.
  Commits: `37417ab` design / `7ee24f3` 27-RED+3-GREEN tests stub /
  `47ca31f` impl 30-GREEN.

  **Architectural choice**: wrapper pattern, NOT `BacktestEngine.run`
  modification. `core/backtest/backtest_engine.py` byte-identical to
  pre-K1 `main` — M11a/M11b parity bit-for-bit guaranteed by
  construction. Wrapper drives existing kernel (`SignalStateMachine`
  + `DeferredExecutionSchedule`) per bar → builds (date × symbol)
  weight panel → delegates to `BacktestEngine.run(signals_df=panel)`.
  T1a/T1b/T1c/T2a/T2c all consume this wrapper identically to a
  hypothetical engine extension. If T1b reveals need for state-aware
  cost models (e.g., mid-bar cost change), additive engine
  extension can land then.

  Test surface delta: +30 tests (1.3% of 2323 baseline). All 30
  GREEN; full `tests/unit/backtest/` 199/199 PASS (no regression
  on M11a/M11b parity / NaN-equity / concentration metrics /
  intraday paths / ghost cleanup / cap_aware).

  **Status**: T1a (alt-A `IntradayReversalStrategy` Phase 2-3)
  unblocked; estimated 3-5 days as first real consumer.

- **SPY/BIL/SHV off-by-one date label bug + Option A fix** (2026-05-13
  evening ✅) — surfaced during K1 ship-close broader regression run
  (3 pre-existing forward bar_hash test failures investigated).
  Postmortem: `docs/memos/20260513-spy_off_by_one_date_label_postmortem.md`.
  Closeout: `docs/memos/20260513-option_a_closeout.md`. User explicit-go
  Option A 2026-05-13.

  **Bug**: `core/data/calendar.py::align_daily_index` did
  `tz_localize(None)` without `tz_convert(_ET)` first. For yfinance
  data that occasionally returned UTC-tz-aware index, UTC-midnight bars
  rolled forward +1 calendar day (Mon trading → Tue label, Fri → Sat
  label) producing ~569 fake Saturday rows per affected symbol.

  **Affected PQS active universe**: 3/81 symbols — **SPY, BIL, SHV**
  (yfinance-fetched). Initial scan suggested 10+ but JPM/V/PG/HD/BAC/
  XOM/CVX are NOT in `config/universe.yaml` (leftover data files only).

  **Fix** (commit `2898be8`): `align_daily_index` now `tz_convert(_ET)`
  before `tz_localize(None)`. Pure correctness; tz-naive data (common
  case) bit-for-bit unchanged. Rebuild script
  `dev/scripts/data_fix/rebuild_off_by_one_symbols.py` re-fetched
  SPY/BIL/SHV via fixed path; old parquet preserved as
  `.preFix_2026-05-13` sidecars (gitignored).

  **Validation**: post-fix 81-symbol universe scan = 0 affected;
  3 previously-failing forward bar_hash tests = 3/3 PASS; backtest
  unit suite 199/199 PASS.

  **Re-run / deprecation** (Option A.5-A.7, commits `f2997c0` + this):
  - simple_baseline_v1 backtest: UNAFFECTED (script uses yfinance
    direct, not BarStore parquet). CAGR +14.90% / Sharpe 0.82 /
    per-year MaxDD ≤25% confirmed identical. Paper soak continues.
  - trial9_diversifier_002 forward: TD001 (pre-fix init) dropped via
    `--overwrite` re-init; status=not_started; first observe will
    run with clean SPY data on next daily ritual. TD60 ~2026-08-06
    timeline unchanged.
  - cycle04-10 mining: **numerical claims DEPRECATED** (vs_spy
    aggregates, NAV correlation magnitudes, beta_spy_60d factor
    values, IC numbers). **Qualitative findings PRESERVED**:
    sibling-by-NAV is REINFORCED not invalidated (1-day phase shift
    dilutes Pearson, so true correlation > measured 0.85-0.95);
    TC ceiling argument unaffected (pure theory + literature);
    bundle-binding-across-cycles n=5 demonstration structural.
    R7 fail-SPY stop-rule verdicts on cycle10 stand.
  - RCMv1 + Cand-2 forward manifests: numerically deprecated;
    preserved as forensic evidence (both already aborted 2026-04-30
    on unrelated data revision drift).
  - Trial 9 v1 manifest: numerically deprecated; preserved as forensic.
  - K1 ship: UNAFFECTED (synthetic test data, no real SPY).
  - Roadmap v2 strategic decisions (D1 drop / D3 defer / signal seed
    library / K1+T1 path): UNAFFECTED (literature + theoretical).

  **New audit discipline added** (will commit to
  `[[feedback_audit_per_round_methodology]]`): bar-level data
  integrity smoke test (weekend-row scan + cross-symbol date
  intersection check) before every cycle. The off-by-one bug
  persisted across 5 cycles + 4 forward candidates because no test
  covered bar-label correctness; the test that caught it only existed
  AFTER v2.1.3 forward observation rewrite (commits `c3cefc1`..`4abc3c9`).

- **PEAD bundle Phase 1 — dual-track free-path SHIPPED**
  (2026-05-14 ✅, commits `7c23fc5` + `faae8f1`) — **first event-driven
  non-parametric signal in PQS history that clears Sharpe > 1.0 + MaxDD
  < 10%**. PRD `docs/prd/20260514-pead_bundle_phase1_prd.md`; closeout
  `docs/memos/20260514-pead_bundle_phase1_close.md`. Dual-track A/B
  hypothesis pre-registered.

  **Modules shipped**: `core/research/pead/{earnings_dates,
  sue_calculator, price_jump_signal}` + 53 unit tests (100% pass).
  Earnings-date extractor handles two non-obvious EDGAR PIT artifacts:
  (a) **comparative-data restatement** — same period_end re-appears
  under later fy values (filed 1 year later, gap=398d) so MUST groupby
  period_end + take MIN(filed_date), not just `get_chain_facts` latest;
  (b) **YTD-cumulative vs standalone-Q** — same (fy, fp, form) reports
  both YTD-cum EPS and standalone-Q EPS, separated only by `start` →
  `end` duration (60-100d for Q, 300-380d for FY). FY rows dropped for
  SUE to prevent lag-4 mismatch (full-year EPS compared against
  standalone-Q 4 rows back inflates SUE to 11σ false positive).

  **Path 1 SUE (fundamental surprise)** — 8/9 smoke trials beat SPY
  Sharpe 0.76 at 30bp realistic cost. Top trial 1 (SUE≥1.5σ hold=21
  top_n=10): Sharpe 1.055, CAGR 5.48%, MaxDD **-7.64%** (best-in-PQS
  for >1.0 Sharpe). Top trial 6 (hold=60): Sharpe 1.063, CAGR 10.39%,
  MaxDD -24%. Signal robust across threshold 1.0-2.0σ, hold 21-60d,
  top_n 5-20 (NOT a knife-edge hyperparameter).

  **Path 2 price-jump (AR proxy)** — 0/9 beat SPY. Top Sharpe 0.717.
  Confirms pre-registered hypothesis: AR alone too confounded
  (guidance / sector co-move / macro). Fundamental SUE captures real
  information-diffusion alpha; price-reaction alone is noise.

  **Track A acceptance 14/17** — all per-year MaxDD < 25%, all stress
  slices < 10%, 2x cost robust ($13965 final at 60bp), concentration
  / beta / no-leveraged-ETF all PASS. **NAV daily-return Pearson
  vs anchors**: alt-A +0.09 (very low), T1b +0.38, cycle11 Donchian
  +0.37 — all well below 0.85 sibling threshold. **Genuine
  differentiated alpha source.** Fails 3 gates: `validation_aggregate_
  excess_vs_spy/qqq` + `2025 vs_qqq`. Failing gates are CAGR-based,
  NOT signal-quality. PEAD alpha shape = defensive (low DD, lower
  CAGR than SPY in 2025 BULL year +13%).

  **Forward-init as evidence-only** (user explicit-go 2026-05-14)
  — candidate `pead_sue_trial1_evidence_v1`, role
  `evidence_only_observation` (NOT fleet), spec_hash
  `9a2ef503a241f407d2cf43c6b5a2ab3b12cdc2d16bcd35963e694000a8ca9d30`.
  start_date 2026-05-15. Standalone observation track (does NOT use
  main `core/research/forward` runner because event-driven SUE doesn't
  fit factor-composite schema; precedent = simple_baseline_v1).
  Init / observe scripts at `dev/scripts/pead/{init,observe}_pead_
  evidence.py`. TD000 baseline locked: Sharpe 1.056, CAGR 5.51%,
  MaxDD -7.64% (2017-01 to 2026-05-14, $16522 final equity, 287
  signals, 477 trades).

  **TD60 decision point ~2026-08-13** (1 week after Trial 9 v2 TD60
  on ~08-06):
  - GREEN: realized Sharpe > 0.8, MaxDD < 15%, NAV daily-return
    Pearson vs T1b < 0.70 → Phase 2 (paid 8-K real-announce-date
    feed ~$50-100/mo) eligible
  - YELLOW: Sharpe 0.4-0.8 or MaxDD 15-25% → continue TD90
  - RED: Sharpe < 0.4 or MaxDD > 25% → close evidence track

  **Known limitations** (PRD §7): filed_date is 10-Q submission date
  (typically 7-14d AFTER actual 8-K earnings call); 0-10d strongest
  drift portion partially missed. Phase 2 paid 8-K feed unlocks this.
  FY rows dropped for SUE → lose Q4 events (25% of earnings
  opportunities). 54-stock universe restricted to EDGAR cache.

  **Strategic implication**: PEAD is NOT a standalone-alpha winner
  (CAGR < SPY); it's a **defensive sleeve candidate for fleet
  allocation** (Phase C-PRD-2, deferred). Forward soak validates
  whether Bernard-Thomas 1989 signal hold in 2026 real-time data
  before justifying paid-data Phase 2 OR fleet-architecture build.

- **P0 governance + foundation fixes + cycle06/08 sealed-pass + priority
  1-9 ship** (2026-05-15 ✅) — large multi-part session driven by a
  codex audit. Key items:

  **P0.a — QQQ governance unification** (commit `966e177`): CLAUDE.md
  deprecated QQQ 2026-05-02 but config files still applied HARD QQQ
  gate. New `config/evaluation_policy.yaml` + `core/research/
  evaluation_policy.py` runtime-override layer demotes all QQQ
  kill_candidate gates to diagnostic_only (v1/v2/v3 yaml preserved
  verbatim under immutability). `temporal_split_acceptance` +
  `mining/evaluator` read the policy.

  **P0.b + P0.b.4 — full-universe data repair**: completeness gate
  `core/data/data_completeness_gate.py` + `core/data/data_repair.py`
  (yfinance split-aware reverse-adjust). Repaired 12 priority symbols
  then 12 more (A/APD/AXP/BKNG/DG/KLAC/LRCX/SCHD/SOXL/TKO/TRGP/USMV);
  META wrong-ticker purge+refetch (was META Financial Group pre-
  2022-06-09, not Meta Platforms). Post-repair 81/81 universe
  completeness PASS. 1675+ rows filled.

  **P0 CRITICAL — MaxDD acceptance gate sign bug** (commit `1e0d81e`):
  `temporal_split_acceptance` MaxDD gates compared a NEGATIVE-stored
  maxdd against a POSITIVE threshold with `<=` → always True → the
  gate (per-year + stress-slice + role) NEVER fired. Every Track A
  "PASS" 2026-05-14/15 had a dead MaxDD gate. Fixed: `abs(maxdd)`
  comparison at 3 sites + 4 regression tests. Re-eval ALL candidates:
  cycle06 1/3, cycle07a 0/3, cycle08 1/3, cycle12 0/3 PASS.

  **executable_universe.yaml SoT** (commit `[B]`): cycle yamls'
  `universe_extension` blocks were stale-copy from cycle08 (claimed
  59; actual mining universe = 79). New `config/executable_universe.yaml`
  is the canonical 79-symbol executable-universe declaration + drop
  reasons; separates "data-store completeness (81/81)" from
  "executable mining universe (79)".

  **Sealed 2026 single-shot test — 2/2 PASS** (commit `60de4ee`):
  per corrected pipeline ordering (sealed gate BEFORE forward
  observation — a gate must precede what it gates). cycle08_3f40e3f4ed1a
  (sealed vs_spy +14.83%, Sharpe 4.10, MaxDD -7.66%) + cycle06_31af04cf2ff9
  (vs_spy +24.55%, Sharpe 4.00, MaxDD -6.62%). Window 2026-01-01..05-14.
  **The 2026 single-shot holdout for split `alternating_regime_holdout_v1`
  is now CONSUMED** — re-testing improved candidates needs split_name
  bump. Sharpe ~4 is a 4.5-month short-window figure (noisy/optimistic
  — not steady-state). Ledger has cycle08 as the event marker (script
  looped record_eval; B1 correctly blocked the 2nd; cycle06 result in
  the memo + sealed_2026_eval.json as part of the same single event).

  **Priority 1-9 shipped**: Family R chart-pattern factors (10, commit
  `f4a46a1`) + Family S regime-ML factors (3) → RESEARCH_FACTORS
  162→175; multi-TF cascade decision module (`core/research/
  multi_tf_cascade.py`); 130/30 long-short config schema
  (`core/research/long_short_config.py`, schema-only — execution
  wiring deferred, user explicit-go for the invariant relaxation);
  universe extension yaml + inverse-ETF cap grid; cycle12 mining
  (200 trials, 93 archived, Family R golden_cross_score in top-1 —
  but 0/3 Track A post-MaxDD-fix); PEAD cost sensitivity (Trial 1
  ROBUST at 60bp); LLM mining framework (`core/research/llm_mining.py`,
  framework-only). cycle12 used FAMILIES_OHLCV_ONLY (12 families) —
  fundamental/sector/macro families need separate compute paths.

**Forward OOS workstream (infrastructure history + active state)**:
Infrastructure (R-fwd-1 / R-fwd-2 / R-fwd-3 / F) shipped 2026-04-26
through 2026-04-29 + R8 DST fix; legacy candidates RCMv1 + Cand-2
forward-observed 2026-04-24 through 2026-04-28 then **aborted
2026-04-30** under v2.1 fail-closed gate (see "Forward observation
history" entry below). **Active forward candidates as of 2026-05-15**:
- `cycle08_3f40e3f4ed1a_evidence_v1` (core_alpha role, evidence stance,
  TD001 @ 2026-05-15, TD60 ~2026-08-14) — passed Track A post-MaxDD-fix
  + sealed 2026 (2/2). main core/research/forward runner.
- `cycle06_31af04cf2ff9_evidence_v1` (core_alpha role, evidence stance,
  TD001 @ 2026-05-15, TD60 ~2026-08-14) — same; vs_qqq diagnostic-only.
- `trial9_diversifier_002` (diversifier role) — **HALTED 2026-05-15,
  status=requires_data_review**. v2.1 revalidate detected the P0.b/
  P0.b.4 data repair (revised 2024 bars on ~15 held symbols feed the
  factor lookback windows); materiality=bound_only (revised cells
  outside execution_nav anchor ring). Last clean TD = TD002 @
  2026-05-14. ALSO: trial9_v2 Track A acceptance predates the P0
  MaxDD-gate fix → its "PASS" standing is unverified under the fixed
  evaluator. Needs (a) Track A re-eval + (b) re-init on repaired data
  before forward observation can resume — decision pending.
- `pead_sue_trial1_evidence_v1` (evidence-only role, TD001 @ 2026-05-15,
  TD60 ~2026-08-13) — standalone observation track
  (dev/scripts/pead/observe_pead_evidence.py), does NOT use main
  runner (event-driven SUE signal doesn't fit factor-composite schema)
- `spy_8otm_bull_put_v1` (options sleeve, TD007 @ 2026-05-15, TD60
  verdict ~ 2026-07-30) — options paper-trading layer, separate path
Forward fleet anti-sibling: cycle06/cycle08/trial9 pairwise raw NAV
0.704-0.825 (all < 0.85). Daily ritual log: docs/forward_observation_log.md.
- **R-fwd-1 done** — forward runner minimum closed loop (init /
  status / observe / decide / readiness) + source-boundary sidecar
  + `source_mix` flag on ForwardRun. PRD:
  `docs/prd/20260426-forward_oos_runner_prd.md`. Both candidates
  (RCMv1 / Cand-2) have first real forward TD entries:
  ```
  RCMv1   start_date=2026-04-24  TD001 / 2026-04-24 / source_mix=True
  Cand-2  start_date=2026-04-24  TD001 / 2026-04-24 / source_mix=True
  ```
  source_mix=True because forward observes yfinance frontier bars
  while candidates were constructed on polygon canonical (different
  adjustment semantics, surfaced honestly).
- **R-fwd-2 / R-fwd-3 evidence-hardening SHIPPED v2.1.3 (2026-04-28 ✅)** —
  per `docs/prd/20260427-forward_evidence_hardening_prd.md`. Five
  layered commits on `main`:
  1. **v2.1 base** (`c3cefc1` → `5cd51f3`, codex Round 6→9): schema
     models + factor input contract resolver + 3 per-scope hashers
     (signal_input / execution_nav / benchmark) + bar_hash rollup +
     materiality_anchor_values 10-day ring + per_cell_digest +
     window-scoped source-layer classifier + revalidate E1-E5
     materiality policy + runner integration with legacy_unhashed_inputs
     marker on pre-v2 TD001.
  2. **v2.1.1 audit round 1** (`fd24285`): 4 self-audit fixes
     (storage budget pinned via `track_per_cell=False` default;
     revalidate moved to TOP of observe; `requires_data_review`
     halt guard; epsilon tolerance on E1/E2/E3/E5 thresholds + E4
     symmetric drift check).
  3. **v2.1.2 audit round 2** (`7c7f860`, `e942ab9`): Bug 5 fix
     (flagged_only events lost on no-new-bar return path, now
     persisted via `manifest_dirty_from_revalidate` flag).
  4. **v2.1.3 codex Round-10 blocker fixes** (`4abc3c9`, `051d869`):
     - Blocker 1: `compute_signal_input_hash` window resolution
       changed from `pd.tseries.offsets.BDay(lookback)` to true
       trading-day rows from panel index. Pre-fix BDay(252) landed
       ~9-13 trading rows short of the true 252nd prior trading
       day on the NYSE calendar (BDay = Mon-Fri only, no holidays).
     - Blocker 2: empty `signal_input.per_cell_digest` (production
       default) now ALWAYS fail-closes to bound_only when the
       rolling hash differs, regardless of execution_nav scope
       state. Pre-fix optimistically gated on exec_nav and could
       under-classify dual-scope revisions as flagged_only.
     - Adjacent: revalidate now passes matching `track_per_cell` to
       `compute_signal_input_hash` recompute (was silently producing
       spurious 821-cell diffs in opt-in test mode).
  Forward slice: 51 → 102 tests (+2 R8 DST regressions); full unit
  suite 1838 passed.
- **F (config / universe snapshot hardening) SHIPPED (2026-04-29 ✅)** —
  per `docs/prd/20260428-config_universe_snapshot_hardening_prd.md`.
  Five-step layered shipping on `main`:
  1. **Step 1** (`1952e44`): `ConfigSnapshot` + `ConfigDriftEvent`
     pydantic models in `manifest_schema.py`; `ForwardRunManifest.config_snapshot`
     and `ForwardRun.config_drift_event` Optional fields. Lazy-migration
     compatible — pre-PRD-F manifests load with both fields = None.
  2. **Step 2** (`c28c969`): `_canonical_yaml_sha`
     (sorts dict keys recursively, **preserves list order** —
     conservative fail-closed) + `_factor_registry_contract_sha`
     (hashes the contract not the file bytes; refactor-stable) +
     `_build_config_snapshot()` helper. `init(config_dir=...)`
     wiring stamps the snapshot at forward-init time.
  3. **Step 3** (`368536d`): `revalidate_manifest(current_config_snapshot=...)`
     + `RevalidationSummary.config_drift_event` slot (kept separate
     from data_revision events per codex round-11 §B3). Severity
     policy: `universe_hash` / `factor_registry_hash` / `risk_config_hash`
     → halt (flips `current_status` to `requires_data_review`);
     `research_mask_hash` / `system_config_hash` → warn. `observe()`
     wiring builds a fresh snapshot, attaches event to latest TD,
     INFO-logs once per process per candidate when manifest is
     pre-PRD-F (lazy-migration boundary).
  4. **Audit fixes** (`abc4425`): `extra="forbid"` on F-PRD models
     (typo-key bug); docstring fix on `_canonical_yaml_sha`;
     terminal-status halt on `observe()` (decided candidates can't
     be silently overwritten).
  5. **Step 4 backfill** (`ad6491e`): `dev/scripts/forward/backfill_config_snapshot.py`
     opt-in CLI for pre-PRD-F manifests. Stamps `migration_note=
     "backfilled_<date>_assumed_unchanged_since_init"`. Idempotent
     without `--force`; `--dry-run` previews byte-identical. 8 tests
     in `tests/unit/research/test_backfill_config_snapshot.py`.
     Plus codex round-18 follow-up `observe(config_dir=...)` kwarg
     for hermetic-test contract symmetry with `init()`.
  Forward slice today: 146 tests (24 added since v2.1.3 baseline:
  10 F step-3 drift + 5 audit-round 1+2 fixes + 8 step-4 backfill +
  1 R18 §1 config_dir-kwarg regression). Full unit suite 1850 passed.
  **Operational rule established (audit reverse-validate finding)**:
  forward `fetchdata` MUST run post-NYSE-16:00-ET close. Earlier
  intraday fetches put a partial-day "close" on disk; the next
  observe()'s v2.1 revalidate correctly fail-closes (NAV impact
  exceeds E1=10 bps; raw drift exceeds E5=0.5%). **2026-05-12
  strengthening**: `scripts/fetch_data.py` main() now raises
  `SystemExit` if called pre-close (was warn-and-cap until 2026-05-12);
  `--allow-pre-close-today` remains as emergency override. Programmatic
  callers (importing download_daily / download_intraday) still get
  the original warn-and-cap as defense-in-depth.
  **Status**: F PRD §6 acceptance 13/13 ✅; codex round 19 + 20 closed;
  F line officially functional (no pending sign-off). RCMv1 + Cand-2
  production manifests still pre-PRD-F (config_snapshot=None); user
  has not yet run the opt-in backfill — drift detection on those two
  will activate when backfill is run. **Operational rule**: forward
  `fetchdata` must run after NYSE 16:15-16:30 ET (codex R20 operational
  note tightening earlier "post-NYSE-16:00 ET" rule).
- **Forward observation history (RCMv1 + Cand-2, TERMINATED 2026-04-30)**.
  First real `forward observe` since v2.1.3 + R8 DST fix ran 2026-04-28
  (commit `bcfbc0f`):
  - rcm_v1_defensive_composite_01: TD001 (legacy) + TD002 + TD003 (last 2026-04-28)
  - candidate_2_orthogonal_01:     TD001 (legacy) + TD002 + TD003 (last 2026-04-28)
  TD001 carries `legacy_unhashed_inputs=True` (no retroactive hash
  backfill); TD002 + TD003 carry full v2.1.3 4-scope hashes
  (signal_input + execution_nav + benchmark + bar_hash rollup).
  Cross-candidate benchmark_hash invariant verified live (same SPY+
  QQQ panel → same hash on same TD). Evidence note:
  `docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`.

  **Status: BOTH ABORTED 2026-04-30** via `decide --status aborted` —
  material data revision detected: **108 bps NAV drift + 2.42% raw
  drift across 13 (RCMv1) / 16 (Cand-2) held-eligible symbols
  including SPY+QQQ** → F-PRD v2.1 §4.4 fail-closed. The legacy
  candidates were nominated pre-G2.A 30% concentration ceiling +
  pre-M12 weighted thin-data fix and were already classified as
  `legacy_decay_verification` role per 2026-04-29 reclassification;
  abort closes their forward TD60 observation entirely. They will
  NOT enter fleet, will NOT calibrate new-framework gates, and the
  daily ritual no longer touches them (terminal status absorbs further
  observe() calls).

  **Current PQS active forward state**: as of 2026-05-14, 3 active
  forward candidates: `trial9_diversifier_002` (TD001 starts 2026-05-13,
  diversifier role, main runner), `pead_sue_trial1_evidence_v1` (TD001
  starts 2026-05-15, evidence-only role, standalone PEAD track), and
  `spy_8otm_bull_put_v1` (options paper, TD started 2026-05-04). RCMv1
  + Cand-2 manifests preserved at:
  - `data/research_candidates/rcm_v1_defensive_composite_01_forward_manifest.json`
  - `data/research_candidates/candidate_2_orthogonal_01_forward_manifest.json`
  Both retain 3 TDs + 1 DECIDE entry each as forensic evidence of
  their April 2026 forward trajectory + the fail-closed abort event.

- **Trial 9 (2026-05-01 ✅, A+D Phase C-PRD-1 SHIPPED commit `7dcdf50`)** —
  first **diversifier-role** forward observation candidate. PRD:
  `docs/prd/20260501-two_stage_allocation_architecture_prd.md`. Decision
  memo: `docs/memos/20260501-diversifier_role_decision.md`. User
  explicit-go 2026-05-01 + D10c compromise (soft-warn at 18% / hard-fail
  at 20% per-year max_dd + TD60 self-clearing). Source: cycle #05 trial
  `6c745c601a47` (`beta_spy_60d + max_dd_126d + ret_1d`).
  - candidate_id: `trial9_diversifier_001`
  - candidate_role: `diversifier` (first non-legacy role assigned in PQS)
  - spec_hash: `8f58d40d2ef579a7c1b0fee53cd29da23763f336dd91a4b4db2c97eb2acec5a6`
  - start_date: 2026-05-04 (Mon, next trading day)
  - soft_warn_flags: `['diversifier_2025_maxdd_18_20pct']`
  - frozen spec: `data/research_candidates/trial9_diversifier_001.yaml`
  - manifest: `data/research_candidates/trial9_diversifier_001_forward_manifest.json`
  - init script: `dev/scripts/forward/init_trial9_diversifier.py`

  **Phase C-PRD-1 deliverables** (all in commit `7dcdf50`):
  - `CandidateRole` enum (4 values) in `core/research/forward/manifest_schema.py`
  - `ForwardRunManifest.candidate_role + soft_warn_flags` (lazy migration)
  - `CandidateRecord.role` + idempotent `ALTER TABLE` migration
  - `runner.init(candidate_role=..., soft_warn_flags=...)` kwargs
  - `config/temporal_split_v2.yaml` (split_name v1→v2 per locked-after-first-use
    C4 policy; partition UNCHANGED; only diversifier role thresholds updated to
    PRD §6.2 evidence-derived values)
  - CLAUDE.md QQQ Outperformance Rule diversifier exception (waives ONLY
    OOS walk-forward window-mean rule for role=diversifier; all other gates
    unchanged; STRICTER for diversifier on NAV correlation + factor overlap
    + non-equity exposure)
  - `dev/scripts/forward/backfill_candidate_role.py` (legacy candidates
    explicitly tagged role=legacy_decay_verification; idempotent)
  - 32 new tests (`test_diversifier_role_phase_c_prd_1.py`) + 138 existing
    forward+registry+temporal_split tests pass (no regression)

  **Post-ship gap fix #1 — v2 dispatch (commit `60e0dfe`)**: v2 yaml was
  created at ship but the loader (`core/research/temporal_split.py:_DEFAULT_PATH`)
  defaulted to v1; v2 was only consumed by the 32 unit tests, NOT by
  acceptance pipeline / future cycle #06 mining. Closed via
  `resolve_split_path(role, freeze_date)` dispatch helper +
  `run_split_acceptance(freeze_date=...)` threading + extended `GateRule`
  schema for `action: soft_warn` (with `soft_warn_label` /
  `soft_warn_clear_condition` / `soft_warn_unclear_action` fields
  required iff soft_warn). Dispatch rule: `role=diversifier AND
  freeze_date >= 2026-05-01 → v2`; everything else → v1 (legacy contract;
  immutability for cycle04+05 archived trials + RCMv1+Cand-2). 20 new
  dispatch tests.

  **Post-ship gap fix #2 — forward attention check automation (commit
  pending)**: TD20/TD40/TD60 milestones need automated derived metrics
  beyond what `observe()` captures (residual NAV correlation, combo NAV,
  rolling 60d MaxDD, non-equity exposure drift, soft_warn self-clearing
  status, PRD §7.1 GREEN/YELLOW/RED verdict). Shipped pure-compute
  module `core/research/forward/attention_report.py` + CLI driver
  `dev/scripts/forward/attention_check.py`. Outputs JSON to
  `data/ml/forward_attention/` + stdout markdown. Gracefully handles
  empty manifests (trial 9 currently 0 runs; full report computable
  TD60+). 31 unit tests covering: NAV series derivation, multi-candidate
  combo, rolling MaxDD, residual corr (regress out benchmark beta),
  asset-class classification, PRD §7.1 verdict logic, end-to-end
  graceful degradation. Full unit suite 2323 passed (no regression).

  **TD60 decision point pre-committed** (~2026-07-30):
  - GREEN: residual NAV corr 60d <0.4 + per-regime BULL vs_qqq 60d > -3% +
    portfolio combo positive + soft_warn_flag self-cleared (60d rolling
    max_dd ≤ 15%) → authorize Phase C-PRD-2 (sleeve abstraction)
  - YELLOW: 0.4-0.6 residual OR BULL vs_qqq 60d in [-10%, -3%] → continue
    to TD90
  - RED: residual >0.6 OR BULL vs_qqq 60d <-10% OR portfolio combo
    negative → stop trial 9 forward; do NOT build C architecture for it

  **Phase C-PRD-2/3/4 NOT authorized** (deferred per PRD §8 evidence-gated
  triggers). D3b regime-aware mining objective DEFERRED + absorbed into
  Phase C-PRD-3 Stage 1 allocation. Track B Step 6+ ABSORBED into
  Phase C-PRD-3/4 (Steps 1-5 already shipped; reused unchanged as Stage 3
  inputs).

  **Operational contract**: forward `fetchdata` MUST run post-NYSE 16:15-16:30
  ET close (codex R20 operational note). Trial 9 first observe = 2026-05-04
  EOD; produces TD001 entry.

  **Trial 9 forward state (2026-05-05 EOD)**: TD001 (2026-05-04, cum_ret=0.0)
  + TD002 (2026-05-05, cum_ret +3.60%, vs_spy +2.80%, vs_qqq +2.31%, max_dd
  0.00%); status=in_progress. TD002 only after PRD 20260505 E4 near-zero
  exemption + `recover` CLI (see Phase E shipped list). TD001 carries 1
  PolicyRecoveryEvent in `policy_recovery_log` (audit trail; original
  data_revision_event downgraded `invalidated → flagged_only`).

  **Trial 9 forward state at closeout (2026-05-12)**: 4 TDs observed
  before halt. TD003 (2026-05-06) cum_ret +8.02% / vs_spy +5.82% /
  vs_qqq +4.62% / max_dd 0.00%. TD004 (2026-05-07) cum_ret +5.04% /
  vs_spy +3.15% / vs_qqq +1.76% / max_dd -2.75%. 2026-05-12 daily-ritual
  `observe()` revalidate detected retroactive yfinance refresh on all
  4 TDs; TD001-TD003 classified `flagged_only`/`in_ring` (sub-bps NAV
  impact); **TD004 classified `invalidated`/`bound_only`** with trigger
  `bound_only (signal_input scope diff with empty per_cell_digest
  (track_per_cell=False) — cannot prove diff is subset of execution_nav-
  anchored cells; conservative bound_only per PRD §4.4 (codex Round-10
  Blocker 2))`. Manifest flipped to `requires_data_review`. 4-round
  self-audit on 2026-05-12 verified: (a) 18 held syms × 10 anchor-ring
  dates × close anchor values vs current panel = 0 diff revealed, (b)
  re-hash of signal_input with `track_per_cell=True` against current
  panel still differs from stored, (c) therefore revised close cell
  is OUTSIDE execution_nav anchor coverage (i.e., non-held sym OR date
  older than 4/24 ring start). No retroactive reconstruction path
  exists (stored signal_input `per_cell_digest` was empty per production
  `track_per_cell=False` default). `recover` halts because policy
  re-eval produces same bound_only verdict. **Considered + rejected**:
  A1 magnitude-bounded exemption (post-hoc TD004 fit, breaks codex R10
  Blocker 2 intent); A1.c synthetic anchor reconstruction (infeasible —
  revised cell outside anchor coverage). **Shipped fix**: A4+A2 path
  per PRD `docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md`
  + closeout memo `docs/memos/20260512-trial9_diversifier_001_closeout.md`
  + commit `16de8dd`. `trial9_diversifier_001` status =
  `completed_fail` (DECIDE entry recorded). 4 TDs preserved as forensic
  evidence in manifest.

- **trial9_diversifier_002 (2026-05-12 ✅, A4+A2 SHIPPED commit `16de8dd`)** —
  successor to `trial9_diversifier_001` under PRD 20260512 per-candidate
  `track_signal_input_per_cell` opt-in. Composite + construction +
  universe IDENTICAL to v1; only material diff = `evidence_config:
  {track_signal_input_per_cell: true}` in frozen yaml, which causes
  forward runner (line 1041 of `core/research/forward/runner.py`) to
  pass `track_per_cell=True` to `compute_signal_input_hash` at TD-write
  time. Resulting non-empty `per_cell_digest` lets v2.1 revalidate do
  real cell-level diff (revalidate.py:429-444) so bound_only-with-empty-
  digest failure mode cannot recur on this candidate.
  - candidate_id: `trial9_diversifier_002`
  - candidate_role: `diversifier`
  - spec_hash: `44870b91073aa5440dfa5d8ccc07b1f43dcc25235ce9139e2ca0352559e8f985`
  - start_date: 2026-05-13 (Wed, next trading day after closeout)
  - soft_warn_flags: `['diversifier_2025_maxdd_18_20pct']` (mirrored from v1)
  - frozen spec: `data/research_candidates/trial9_diversifier_002.yaml`
  - manifest: `data/research_candidates/trial9_diversifier_002_forward_manifest.json`
  - init script: `dev/scripts/forward/init_trial9_diversifier_002.py`

  **PRD 20260512 deliverables** (commit `16de8dd`):
  - `FrozenStrategySpec.evidence_config: Optional[dict] = None` field
    (mirrors `execution_policy` precedent from PRD 20260505)
  - `runner.py:1041` reads `spec.evidence_config` to resolve
    `track_per_cell` kwarg
  - 9 new tests `tests/unit/research/test_forward_evidence_config.py`
    (legacy preservation / opt-in PASS / opt-in False explicit /
    rolling hash invariant across flag / yaml round-trip / from_dict
    missing field / from_dict explicit field / extras separation)
  - 893 research-tests-suite passes (no regression on RCMv1 / Cand-2 /
    trial9_001 legacy paths)

  **Storage cost** (close-only signal_input attr for diversifier with
  this composite): ~163 KB / TD → ~10 MB / 60-TD soak / candidate.
  Operator monitoring at TD030 (~2026-06-25) + TD060 to validate
  estimate (PRD 20260512 §5 / closeout memo §"What the operator owes
  future-self").

  **TD60 decision point pre-committed**: ~2026-08-06 (1-week slip from
  v1's ~2026-07-30 baseline; acceptable per resident-quant judgment to
  preserve diversifier-role evidence chain over restart cleanliness).
  Same GREEN/YELLOW/RED verdict criteria as v1 (residual NAV corr 60d
  + per-regime BULL vs_qqq 60d + portfolio combo + soft_warn self-clearing).

  **What the operator owes future-self**: first observe on 2026-05-13
  EOD (post-NYSE 16:15 ET fetch) will produce TD001 with NON-EMPTY
  `bar_hash_inputs.signal_input.per_cell_digest` — this is the
  load-bearing behavior change that prevents v1's failure mode from
  recurring.

**Track A — Temporal Split & Holdout Discipline (SHIPPED 2026-04-29)**

PRD `docs/prd/20260429-temporal_split_holdout_discipline_prd.md` v1.1
(codex round 19 + 20 PRD-level approved). Roadmap
`docs/memos/20260429-post_audit_strategic_roadmap.md` v3. Implementation
log `docs/memos/20260429-track_a_implementation_log.md`. F1/F2 fork
criteria locked pre-smoke at `docs/memos/20260429-track_a_f1_f2_fork_criteria.md`.

Shipped infra (no real mining yet):
- `config/temporal_split.yaml`: alternating_regime_holdout_v1 — train
  2009-2017+2020/2022/2024; validation 2018/2019/2021/2023/2025
  (2025 hard gate on core role); 2 stress slices (covid_flash +
  rate_hike_2022) borrowed for MaxDD sanity only; 2026 sealed
  single-shot.
- `core/research/temporal_split.py`: pydantic loader + train/validation/
  sealed sets + restrict_frames_to_train + validate_no_holdout_leakage +
  compute_panel_max_date + ensure_role_assigned + purge_labels_at_boundary
  (M4) + validate_factor_lookback (M3 cap) + enforce_c5_no_role_remint.
- `core/research/temporal_split_acceptance.py`: 17-gate evaluator (per
  validation year + stress slice + role + concentration + beta + cost);
  separate from acceptance_pack (codex round 13 frozen contract).
- `core/research/sealed_ledger.py`: M5 fail_closed_on_repeat + codex
  R20 B1 fail_closed_on_split_failure parquet ledger.
- `core/research/regime_classifier.py`: M9 manual + auto regime tag with
  tiered disagreement policy (memo / user-go / hard error).
- `core/mining/rcm_archive.py`: 7 new columns; idempotent ALTER;
  find_studies_by_spec_role for C5 lookup.
- `scripts/run_research_miner.py`: --temporal-split + --role flags;
  panel restrict + leak guard + summary metadata.

Track A test surface: 126 unit tests covering all 18 PRD §11 acceptance
criteria. Combined repo unit suite: full pre-Track-A 419 research
tests preserved + 126 Track A tests = 545 in research module.

What's still open:
- **PRIORITY REALIGN (2026-04-30, audit R36)** — see
  `docs/memos/20260430-priority_realign_alpha_first.md`. Project
  has crossed governance-saturation threshold; alpha not yet
  proven under new framework. Until cycle #01 produces a candidate,
  guard infrastructure has zero operational consumer. **Order is
  now alpha-first**: cycle #01 preflight (P0) + E.MV signoff
  (external) + generic NAV pair runner refactor (P1) + Track A
  acceptance β-stamp minimal extension (P1). **A.MV/B.MV full
  implementation DEMOTED to P2 candidate-gated; Fleet Step 6+
  HARD PAUSED.** Pre-emptive guard work is over until candidate
  evidence justifies it.
- **Track B** Fleet Allocator: **Steps 1-5 SHIPPED** (2026-04-29
  Step 5 = C2 correlation budget, codex R30 accepted code-level).
  Step 6+ (DD throttle / role caps / fleet observe / shadow→live):
  **HARD PAUSED until ≥2 candidates exist that BOTH pass Track A
  acceptance AND have realized-NAV pair correlation < 0.85.** Per
  R36 priority realign: continuing allocator downstream while no
  fleet candidate exists is empty plumbing. PRD
  `docs/prd/20260428-candidate_fleet_allocator_prd.md` v1.1 codex
  round-14 approved (frozen at this state).
- **Track C real mining: cycle #01 ALPHA-FIRST PRIORITY** (2026-04-30,
  `docs/memos/20260430-track_c_dry_run_plan.md` — renamed from
  "dry-run" per external reviewer §7 to reflect formal-cycle
  discipline). **Pre-registered immutable criteria yaml is P0
  internal to write before any trial runs** (does not depend on
  E.MV signoff; criteria immutability requires pre-registration
  same as cycle 2026-04-26 #01). Compute itself unblocks on E.MV
  §4.6 (NAV-orthogonality tier landed in template v1.1 at `01d2950`) +
  §4.7 (economic-assumption flags F1-F6) reviewer signoff (external
  dependency). **Cycle #01 closeout MUST classify candidate against
  auditor R36 §4 alpha-source taxonomy** (intraday reversal /
  event-calendar / cross-asset / volatility / different cadence /
  beta-controlled construction); a candidate that passes gates
  but is structurally a RCMv1/Cand-2 sibling does NOT enter
  nominee status — that's the anti-sibling discipline.
- **Forward-observation NAV correlation finding (2026-04-30)**:
  RCMv1 + Cand-2 pooled raw NAV Pearson **0.898** (Step 5 reject
  threshold 0.85). Residual decomposition: vs SPY 0.609 (drop 0.29) /
  vs QQQ 0.579 (drop 0.32). Both candidates' residual annualized
  Sharpe positive (vs QQQ: RCMv1 +2.08, Cand-2 +2.77). Classification:
  `mixed` — ~30% raw correlation is shared market beta, ~60% is
  shared alpha. Cand-2 "orthogonal" claim retracted at NAV level
  (still valid at factor-IC level only). Fleet-of-two equal-weight
  composition does NOT produce risk diversification — both candidates
  re-classified as legacy decay verification only. Track C must find
  a candidate that differs on BOTH beta AND residual alpha — a
  low-beta defensive candidate alone fixes only ~30% of the problem.
  Evidence: `docs/memos/20260430-rcmv1_cand2_realized_correlation.md`.
- **Concerns A/B/E (Track C downstream guards)** — proposed in
  `docs/memos/20260430-concerns_abE_proposed_solutions.md`. **E.MV
  shipped in template v1.1** (commit `01d2950`); reviewer signoff
  pending. **B.MV + A.MV implementation: DEMOTED to P2
  candidate-gated per priority realign 2026-04-30**:
  - B.MV reactivates when cycle #01 produces a candidate that
    passes Track A acceptance + evidence pack §4.6+§4.7 + is
    approved for forward init. Schema contract locked at
    `docs/memos/20260430-bmv_schema_decision.md` (no further
    iteration before consumer exists).
  - A.MV reactivates when that candidate completes forward soak
    (≥ TD60 healthy + no early-attention triggers) AND sealed eval
    is the next gate. Until then, manual sealed-eval discipline
    rule applies (clean window starts strictly after candidate
    `freeze_date` AND after `panel_max_date_at_freeze`).
  - **Minimal Track A acceptance β-stamp extension (NOT full
    A.MV) SHIPPED prep** commit `812a14f` (2026-04-30):
    `core/research/acceptance_helpers.py` adds
    `compute_beta_to_benchmark` + `build_estimated_beta_at_freeze`
    canonical-block builder per `bmv_schema_decision.md`
    §`estimated_beta_at_freeze` (8 unit tests).
    Schema invariant enforced: `used_by_b_mv=False` requires
    `reason_unused`. Defaults: `window=train_plus_validation`,
    `source=track_a_acceptance`, `used_by_b_mv=True`.
    **Pipeline wiring** (call site at the actual promotion path) is
    intentionally deferred to first cycle #06+ candidate that
    survives Track A acceptance — wiring with no consumer is dead
    code. Verified live 2026-05-02: 8 tests PASS, builder importable
    from `core.research.acceptance_helpers`. When wiring lands,
    promotion code calls
    `build_estimated_beta_at_freeze(strat_ret_d=..., spy_ret_d=...,
    qqq_ret_d=..., n_obs=..., computed_at=YYYY-MM-DD,
    computed_by="core/research/temporal_split_acceptance.py")` and
    writes returned dict under top-level `estimated_beta_at_freeze`
    key in candidate spec yaml.
- **NAV orthogonality tier** (single source of truth across script /
  dry-run plan / correlation memo / template, per audit-R2 + reviewer
  §3): `< 0.50` = `true_diversifier`; `0.50-0.70` = `partial_diversifier`;
  `0.70-0.85` = `warn_label_void` (cannot claim diversifier role);
  `≥ 0.85` = `reject_step5` (Step 5 reject). Mirrors Step 5 fleet
  correlation budget with one extra gate at 0.50; replaces the older
  flat 0.40 (factor-IC config) as structurally over-strict for
  long-only US-equity NAV correlation.
- **4-round self-audit methodology** (2026-04-30, forward-only):
  R1 factual / R2 logical / R3 actually-run-the-code / R4 boundary.
  Required for schema / threshold / new-pipeline / numerical-claim
  changes. Codified at `docs/checkpoints/20260430-self_audit_methodology.md`.
- **Generic NAV pair diagnostic runner** SHIPPED (2026-04-30 commit
  `4eb75bd`). `dev/scripts/correlation/run_pair_nav_correlation.py`
  takes any pair via `--candidate-a-id / --candidate-a-run-dirs /
  --candidate-b-id / --candidate-b-run-dirs / [--cell-labels] /
  [--min-overlap 60] / [--output-json]`. Legacy
  `rcmv1_cand2_realized_nav_correlation.py` reduced to thin wrapper
  preserving canonical
  `data/memos/20260430_rcmv1_cand2_realized_correlation.json` path.
  R3 numerical equivalence: 11/11 PASS vs pre-refactor snapshot
  (pooled pearson 0.898 / residual vs SPY 0.609 / vs QQQ 0.579 /
  reject_step5 — all identical to bit). R4 boundary: missing-bench-col
  / zero-var-bench / perfect-beta / n=0 / overlap < min all handled.
  **Design note**: pre-refactor CLAUDE.md spec listed
  `--benchmark-source` flag; R3 audit caught that a global benchmark
  source dir produces a cross-cell-benchmark regression (cell N's
  benchmark loaded from cell 0's window → zero overlap → false
  empty_diagnostic). Per-cell benchmark loading from each cell's own
  `benchmark_relative_paper.csv` is the correct architecture; no
  global flag needed. Verified live 2026-05-02 (legacy wrapper +
  generic CLI both reproduce headline numbers identically).
  Smoke pre-flight (2026-05-02): cycle #06+ candidate evidence pack
  §4.6 ready; manual script-edit at nominee time is no longer audit
  risk.
- **Track D** forward + first promotion: triggered when Track C
  produces a candidate that passes the new-framework acceptance + 2026
  sealed test (single-shot, gated on A.MV freeze-date rule).
- M17 / M18 unchanged.

**Framework Completion PRD** (`docs/20260421-prd_framework_completion.md`
v1.2) — shipped M0-M8 + M10 + M13 + M15 + M16 (see archive); open:

- [x] **M11a** paper-BT artifact-vs-replay consistency **(2026-04-24)**.
  Root cause: `_generate_orders` iterated `set(...)` whose order depends
  on per-process hash randomization (PYTHONHASHSEED). Cross-process
  runs of run_paper_candidate produced different fills under
  integer-share + binding cash → 18-65 bps monotone-signed drift
  (2022 RCMv1 78+/0−). Fix: `sorted(set(...))`. Post-fix drift = 0 bps
  across all 4 paper cells × 91-95 days. See
  `docs/memos/20260424-m11_paper_engine_parity_fix.md`.
- [x] **M11b** PaperTradingEngine vs BacktestEngine parity **(2026-04-24)**.
  Two semantic bugs in `run_day_daily`: (a) EOD equity used prev-day
  close instead of exec-day close (1-day stale), (b) signal_date was
  exec_date instead of exec_date−1BDay (fill_date off by +1 BDay).
  Fix: refactor signature into explicit `prev_close / exec_open /
  eod_close` dicts; correct signal_date. New tests for parity (1bps/day,
  5bps cumulative), fill_date contract, hash determinism. See same
  memo §2.1 + §6 for legacy-vs-new artifact semantics.
- [x] **M12** concentration gate real enforcement **(2026-04-27)**.
  Two-layer split per codex Round-5 audit (no default raise in
  BacktestEngine; metric exposure universal, enforcement opt-in):
  (a) `core/backtest/concentration_metrics.py` exposes
  `compute_concentration_metrics(weights_df)` and pure
  `validate_concentration(...)`; `BacktestEngine.run()` always
  populates `m12_top1_weight_max` / `m12_top3_weight_max` /
  `m12_n_dates_with_weights` in `BacktestResult.metrics`.
  (b) `acceptance_pack` Gate 7 enforces 0.40 / 0.70 ceilings when
  fresh backtest is available; skip-PASS only when no fresh backtest;
  fail-closed when fresh metrics unexpectedly missing. 20 regression
  tests across 3 files. See review log Round 5 + 6.
- [x] **M14** BacktestEngine NaN root-cause fix **(2026-04-24)**.
  Root cause: `price_row.get(sym, 0)` returns NaN (not default 0) when
  column exists with NaN value — panel union-merge across symbols with
  non-aligned calendars produces held-symbol NaN close days. Fix:
  fall back to `last_valid_close` (mirrors ghost-cleanup pattern).
  Eliminated all NaN-equity rows across 4 paper cells + unblocked
  10-30% previously-suppressed rebalance activity (+9.6% final NAV
  2022 Cand-2). 5 regression tests in `test_m14_nan_equity.py`. See
  `docs/memos/20260424-m14_nan_equity_fix.md` for root-cause / pre-post
  / residual.
- [x] **F01 + F02** acceptance threshold unification **(2026-04-28)**.
  Implemented per `docs/prd/20260428-acceptance_threshold_unification_prd.md`
  v1.1 (codex round-13 sign-off + round-14/15 GO + user explicit-go).
  Single source of truth = `core/config/schemas/acceptance.py`
  (`AcceptanceThresholds` with three nested submodels: `TierDThresholds`
  / `WalkForwardThresholds` / `FactorTierThresholds`); yaml at
  `config/acceptance.yaml`; loaded as `cfg.acceptance.*`. Step 1: schema
  + yaml + loader (commit 25246fa). Step 2: WindowAnalyzer wires
  `tier_d` (commit f498649) — class-level `TIER_D_*` constants removed.
  Step 3: factor_evaluator `_auto_tier` wires `factor_tiers` (commit
  58215d6) — 4 hardcoded IR cuts replaced. Step 4: dead `ValidationConfig`
  + `config/backtest.yaml::validation` block deleted. `acceptance_pack._THRESHOLDS`
  remains intentionally frozen per codex round-13 §"Decision 3" (no
  auto-sync; future divergence requires explicit versioned recalibration
  PRD).
- [ ] **M17** Realtime intraday live-feed infra — independent PRD
  `prd_live_feed.md` when validated best strategy exists.
- [ ] **M18** Cross-ticker DSL function expansion (P3, 0.3d each).
  Add `ratio / zscore / rank_cs / breakout` ONLY when a specific
  rule yaml demands them.

**Older TODO (data / intraday / research)**:
- [x] Provenance sidecar (trades_scanner + migration + BarStore API)
- [x] Factor guard (data_sensitivity config + apply_data_sensitivity_mask)
- [x] Notify module (base + wecom_bot + server_chan + stdout)
- [DEFERRED] Master report / diagnostics: show per-ticker data-epoch
      contribution (护栏 3 downstream — BarStore.attrs["provenance"]
      ready). Display layer NOT shipped per resident-quant decision
      2026-05-02: 0 immediate consumer (Trial 9 = 100% yfinance frontier),
      forward soak window not the time to change reporting surfaces.
      Activation triggers + ~2-hour impl sketch:
      `docs/memos/20260502-master_report_provenance_display_deferred.md`.
- [ ] fetch_data.py equivalent for universe + macro: currently one-off
      yfinance fetch in `scripts/`; productionize as part of pipeline
- [ ] validate_vs_yfinance 1m batching (yfinance 1m API limits 8d/req)
- [ ] Multi-timescale data contract (60m+30m formal, 15m+5m prototype)
- [ ] Multi-timescale signal protocol implementation
- [ ] Cross-TF validation / confirmation logic
- [ ] Execution scheduler (trade on lower TF triggers, not just 60m boundary)
- [ ] Multi-timescale leakage tests
- [ ] Per-timeframe IC analysis
- [ ] Combined vs single-TF performance comparison
- [ ] Multi-timescale intraday report
- [ ] Cost sensitivity at higher trading frequency
- [ ] Factor mining continued (new families, LLM candidates)
- [ ] Mining performance optimization

---

## Options Research Track

**Status (2026-05-04)**: Phase 1 free-path research COMPLETE (D→A→C→B→E
sweep on `pqs-options-v1-2026-05-02` branch, merged to main 2026-05-03
commit `b32fad6`); Path 2 paper-trading layer SHIPPED (commit `25e7613`);
first paper candidate `spy_8otm_bull_put_v1` initialized 2026-05-04
(`n_observe_days=0` at init; first observe = 2026-05-04 EOD); cumulative
single-name VRP scanner SHIPPED (commit `2645bb9`, N=3 snapshots so far,
COIN +11.7 ± 2.7 / NVDA +9.4 ± 1.3 / AMD +3.1 ± 5.9 ranks unchanged).

**Phase 1 verified numbers** (Sharpe / MaxDD grep'd from
`spread_backtest_summary_otm8_realistic.json` + `wheel_backtest_summary.json`):
- SPY 8% OTM bull put under realistic asymmetric skew (put 1.30 / call
  0.75 × VIX): Sharpe **0.62** (clears PRD §6 acceptance >0.60), CAGR
  **+0.99%/yr**, MaxDD -2.96%, 92% win rate, 388 trades. **Honest
  winner BUT synthetic** — 33-yr backtest uses VIX as IV proxy + skew
  factors calibrated to one yfinance live chain; paper-observe required
  to validate Sharpe estimate is not optimistic.
- Wheel (CSP→CC) **REJECTED**: MaxDD **-32.72%** > 25% PRD §1.4 ceiling.
  Long-only no-margin invariant amplifies loss when CC assigns at
  lower spot. Don't revisit.
- Single-name VRP 2-3× SPY VRP confirmed by snapshot
  (NVDA 2.0× / AMD 1.8× / COIN 2.7×) — magnitude exists but
  snapshot-only without paid historical chain data.
- Path D fleet correlation: options sleeve cuts 2022 H2 bear DD from
  -14.5% → -7.1% (alpha angle is correlation, not standalone CAGR).

**Key file locations**:
- Scripts: `dev/scripts/options/` (10 files: VRP scan + 4 backtests +
  paper init/observe + skew validation + fleet correlation)
- Core: `core/options/{paper,pricing,strategies}/` — `paper/runner.py`
  + `paper/spec.py` are load-bearing; `risk/`/`data/`/`execution/` are
  Phase 3+ placeholders (intentional, not orphan).
- Tests: `tests/unit/options/` (51 tests; isolation contract test is
  HARD merge gate).
- Data: `data/options/{analysis,backtest,snapshots,paper_runs}/`.
  Paper run state at `data/options/paper_runs/spy_8otm_bull_put_v1/`
  (spec.yaml + manifest.json).
- PRD: `docs/prd/20260502-pqs_options_v1_free_path_prd.md`
- Synthesis: `docs/memos/20260502-options_v1_phase_1_final_synthesis.md`
- Viability / paid-data deferral: `docs/memos/20260502-options_v1_phase_1_viability_memo.md`

**Daily ritual** (post-NYSE 16:30 ET):
```
python dev/scripts/options/observe_options_forward.py --candidate-id spy_8otm_bull_put_v1
python dev/scripts/options/cumulative_vrp_scan.py
```
SessionStart hook (commit `44916b1`) flags staleness on next-session
open via `dev/scripts/daily_freshness_check.py`.

**Decision point ~2026-07-30** (Trial 9 TD60 + options paper TD60
align in same window):
- Both GREEN → authorize paid options chain data spend (ORATS or
  Polygon options tier ~$50-200/mo) + single-name expansion
  (NVDA/AMD priority per Path B Tier 1) + capital scale-up.
- Options paper RED (Sharpe < 0.4 OR capital-sized DD > 15%) → halt
  options workstream, redirect to stock fleet.
- Both RED → strategic reassessment per PRD F5 (objective / data /
  frequency / tools / strategy-type changes).

**Anti-patterns** (do NOT without explicit user-go):
- Do NOT add capital to active paper run mid-cycle (changes
  `spec_hash`, breaks observation continuity).
- Do NOT validate wheel further (rejected for structural long-only
  reasons; more data won't move verdict).
- Do NOT add new Path A-Z sweep (Phase 1 saturated; new free-path
  Path = zero increment without paid data).
- Do NOT pay for chain data before Trial 9 TD60 + paper TD60 verdicts.
- Do NOT integrate options into MultiFactorStrategy or production
  candidate registry (options is a SEPARATE sleeve, not a factor).

**Capital sizing reality check**: $10K paper NAV uses 12% risk/trade
vs PRD §2 default 2% — oversized workaround for min-capital
constraint (one SPY 8% OTM bull put = $1000 max loss = 10% of $10K).
Production deployment requires $50-100K+ for proper sizing. Current
paper data validates **mechanism** (state machine, idempotency,
overlay closes), NOT real-Sharpe estimate.

**Free-path retests on deferred queue** (per Phase 1.4 viability memo
§R1-R3, gated on user explicit-go):
- R1 skew sensitivity sweep — re-run spreads with `skew_factor`
  ∈ [0.20, 0.50] (free, ~1 day eng)
- R2 single-name historical chain — requires paid data, gated on
  Trial 9 TD60 GREEN
- R3 wheel revisit with relaxed CC arm — optional, low expected
  value (rejection is structural)
