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

---

### Pricing and Valuation Semantics [NEW]

#### Raw vs Adjusted Price Rules

| Context | Price Type | Rationale |
|---------|-----------|-----------|
| Factor research (IC, screening) | Adjusted (split + dividend) | Factors measure return-based signals; adjusted prices give correct returns |
| Backtest execution (order fill) | Adjusted (auto_adjust=True from yfinance) | T+1 open is adjusted; consistent with factor signals |
| Portfolio mark-to-market | Adjusted close | Consistent with execution price basis |
| Corporate actions | Handled by yfinance auto_adjust | Splits and dividends baked into price series |

**Current implementation:** yfinance `auto_adjust=True` is used everywhere. All price series (open, high, low, close) are split- and dividend-adjusted. This is consistent across backtest, paper trading, and factor research.

**Constraint:** When switching DataProvider in the future, the replacement MUST produce price series with identical adjustment semantics. A price semantics regression test must exist before any vendor swap.

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
- M12 concentration gate real enforcement
- M14 BacktestEngine NaN root-cause fix
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
registries with strict separation:
- `PRODUCTION_FACTORS` (7): only these drive execution; changes
  require user authorization
- `RESEARCH_FACTORS` (64): available for IC / OOS / regime research

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

**Active workstream**:
- **OOS Framework MVP** (2026-04-25, UNFROZEN narrow scope) — PRD v3
  `docs/prd/20260425-oos_validation_framework_codex_v3.md` + execution
  PRD `docs/prd/20260425-oos_mvp_ralph_loop_execution.md` (R1-R7) +
  ralph-loop launcher `dev/scripts/ralph_loop/oos_mvp_launcher.md`.
  Lineage `oos-mvp-2026-04-25`; promise `OOSMVPDONE`. Unfreeze scope
  + halt conditions: `docs/memos/20260425-oos_framework_unfreeze.md`.
  Auto re-freeze at promise emit. All other round-3 freeze items
  remain frozen.

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
- [ ] **M12** concentration gate real enforcement (P2, 0.5d). Inspect
  fresh-backtest weight matrix for per-date top-1/top-3 concentration;
  reject if top-1 > 0.40 or top-3 > 0.70. Currently skip-PASS.
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
