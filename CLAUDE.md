# PQS — Personal Quantitative System

## Phase C: Continuous Development PRD (v3)

### System Identity
个人量化研究与模拟交易系统。目标：长期可持续跑赢 SPY **和 QQQ**，保持低回撤（15%-20%），具备黑天鹅韧性。

### Invariant Constraints (NEVER violate without explicit user approval)
- long-only, no-margin, no-short
- SQQQ blacklisted; TQQQ/SOXL require stricter risk thresholds
- No real broker/API integration this phase; paper trading = internal simulation
- macOS local execution; no AWS/cloud deployment priority
- Benchmark: SPY primary, QQQ secondary; **strategy must outperform both SPY and QQQ over full evaluation period and holdout** (see QQQ Outperformance Rule) [REVISED]
- Left-side trading = enhancement module only, never default engine
- Intraday: 60m/30m primary, 15m research only
- All thresholds must be configurable (config/*.yaml), never hardcoded
- Must preserve backtest-execution consistency
- Chinese reporting, English code naming
- Initial capital ~$10,000, must scale to $1M+
- Max drawdown target 15%-20%, not worse than SPY in crisis
- **Outperforming QQQ does not waive drawdown, crisis-resilience, or long-only risk constraints** [NEW]

### QQQ Outperformance Rule [NEW]

**硬目标：策略收益必须跑赢 QQQ，不接受仅仅"接近 QQQ"或"落后不超过 2%"。**

旧标准 `excess vs QQQ >= -2%` 已废止。新标准如下：

| Evaluation Scope | Requirement | Type |
|-----------------|-------------|------|
| Full backtest period | Strategy CAGR > QQQ CAGR | **Hard constraint** |
| Holdout period (last 252d) | Strategy return > QQQ return | **Hard constraint** |
| OOS walk-forward (average) | Mean excess return vs QQQ > 0 across all windows | **Hard constraint** |
| Individual OOS window | Excess vs QQQ reported per window | Diagnostic observation |
| Individual regime period | vs QQQ reported per regime | Diagnostic observation |

**Rationale for tiered approach:**
- QQQ is tech-concentrated; in pure bull markets (BULL regime), even well-diversified strategies may lag QQQ temporarily
- Requiring per-window outperformance would force dangerous tech concentration, conflicting with drawdown and diversification goals
- Full-period + holdout + average-OOS constraints ensure the strategy genuinely outperforms QQQ in aggregate

**Risk guardrail:** Strategies must not achieve QQQ outperformance by:
- Concentrating in ≤3 symbols
- Exceeding position limits in config/risk.yaml
- Accepting MaxDD materially worse than SPY
- Disabling regime-based risk scaling

**Master report must:**
- Display `vs QQQ` column in regime-stratified table
- Display QQQ excess in strategy summary
- Flag any promoted strategy that fails full-period or holdout QQQ constraint

#### Diversifier Role Exception [ADDED 2026-05-01, user explicit-go]

**Scope**: candidates registered in `core/research/forward/manifest_schema.py` with `candidate_role = CandidateRole.DIVERSIFIER`. Does NOT apply to `core_alpha`, `legacy_decay_verification`, or `risk_control` roles.

**Waived rule cell** (exactly one):
- `OOS walk-forward (average) | Mean excess return vs QQQ > 0 across all windows` → **WAIVED for diversifier role only**

**NOT waived** (explicit list — diversifier MUST still pass):
- `Full backtest period | Strategy CAGR > QQQ CAGR | Hard constraint`
- `Holdout period (last 252d) | Strategy return > QQQ return | Hard constraint` (interpreted as "validation 2025 vs_qqq > 0 strict" under Track A temporal split)
- `Full backtest period | Strategy vs SPY > 0`
- All risk constraints: per-validation-year MaxDD ≤ 20% (hard) / ≤ 18% (soft warn for diversifier with TD60 self-clearing); stress slice MaxDD ≤ 25%
- All concentration constraints (M12 top1 ≤ 40%, top3 ≤ 70%)
- Long-only / no-short / no-margin invariants
- Anti-sibling NAV correlation (diversifier requires STRICTER thresholds: raw NAV < 0.70 vs all anchors, residual NAV < 0.50)
- Anti-sibling factor overlap (diversifier requires `factor_overlap_with_active_core = 0`)
- Cross-asset utilization (diversifier requires `non_equity_weight_avg ≥ 15%`)

**Rationale**: a diversifier in a fleet legitimately can underperform QQQ in individual BULL windows if the fleet's combined NAV outperforms. The window-mean rule was originally designed for standalone core strategies. Diversifier role's mechanism is portfolio-level risk reduction, not standalone alpha.

**Authority**: PRD `docs/prd/20260501-two_stage_allocation_architecture_prd.md` §6.2; decision memo `docs/memos/20260501-diversifier_role_decision.md`; user explicit-go 2026-05-01.

**Reversibility**: revocation requires user explicit-go + draft of `docs/memos/YYYY-MM-DD-diversifier_role_revoke_memo.md`; CLAUDE.md edit reverted; active diversifier candidates revert to `legacy_decay_verification` role.

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
gates, OOS/IS Sharpe overfit gate, 5-stage mining pipeline, 64
research factors (7 production, see factor_registry), XGBoost 3.2.0
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
- `RESEARCH_FACTORS` (64): available for IC / OOS / regime research;
  may share a NAME with a production factor (e.g.
  `drawup_from_252d_low`) so long as the two implementations are
  numerically identical — see `factor_registry.py:213-220`

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

**Forward OOS active workstream (observation mode)**:
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
  exceeds E1=10 bps; raw drift exceeds E5=0.5%). Workflow discipline
  not a code fix.
  **Status**: F PRD §6 acceptance 13/13 ✅; codex round 19 + 20 closed;
  F line officially functional (no pending sign-off). RCMv1 + Cand-2
  production manifests still pre-PRD-F (config_snapshot=None); user
  has not yet run the opt-in backfill — drift detection on those two
  will activate when backfill is run. **Operational rule**: forward
  `fetchdata` must run after NYSE 16:15-16:30 ET (codex R20 operational
  note tightening earlier "post-NYSE-16:00 ET" rule).
- **Forward observation active**. First real `forward observe` since
  v2.1.3 + R8 DST fix ran 2026-04-28 (commit `bcfbc0f`):
  - rcm_v1_defensive_composite_01: TD001 (legacy) + TD002 + TD003
  - candidate_2_orthogonal_01:     TD001 (legacy) + TD002 + TD003
  TD001 carries `legacy_unhashed_inputs=True` (no retroactive hash
  backfill); TD002 + TD003 carry full v2.1.3 4-scope hashes
  (signal_input + execution_nav + benchmark + bar_hash rollup).
  Cross-candidate benchmark_hash invariant verified live (same SPY+
  QQQ panel → same hash on same TD). Idempotency confirmed (re-run
  observe returns empty, n_runs unchanged). Evidence note:
  `docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`.
  Next decision pack at TD010; currently at TD003 (~7 TDs out).
- **Status: observation-mode running**. Daily `forward observe`
  ritual is live. **NEW (2026-04-29)**: RCMv1 + Cand-2 reclassified
  as **legacy decay verification** under Track A — they were nominated
  pre-G2.A 30% concentration ceiling + pre-M12 weighted thin-data fix;
  not eligible for new-framework promotion unless re-run through current
  gates. Forward TD60 observation continues to record decay signal but
  these two will not enter fleet, will not calibrate new-framework gates.

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
    A.MV) IS scheduled P1 pre-cycle**: when Track A acceptance
    promotes a candidate, compute β-SPY+β-QQQ on `train+validation`
    window and write nested `estimated_beta_at_freeze` block per
    `bmv_schema_decision.md`. Cost ~half day; avoids B.MV
    rework when candidate eventually arrives.
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
- [ ] Master report / diagnostics: show per-ticker data-epoch contribution
      (护栏 3 downstream — BarStore.attrs["provenance"] now available)
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
