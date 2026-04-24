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

### 1m Bar Pipeline [NEW 2026-04-18]

**Source locations (heterogeneous):**
- 2015-2023: `~/Documents/projects/Data/1m/YYYY/YYYYMM/YYYYMMDD.gz`
  Polygon flat: `ticker,volume,open,close,high,low,window_start(ns UTC),transactions`
  Full market including ETFs (~10,679 tickers/day)
- 2024-01 to 2025-11: `~/Documents/projects/Data/1m/YYYY/YYYYMM/YYYYMMDD/<SYMBOL>.csv`
  Schema: `exchange,symbol,open,high,low,close,amount,volume,bob,eob,type`
  **⚠ Stocks only, NO ETFs** (~4,598 tickers/day; only 7/32 universe present:
  AAPL/MSFT/GOOGL/AMZN/META/NVDA/TSLA)
- 2025-12 + 2026: `/mnt/c/Users/Admin/Documents/projects/output/{2025,20260M}/...`
  Same schema as 2024-01 (stocks only)

**Output layout:**
```
pqs/data/
  intraday/1m/<SYMBOL>.parquet     # RAW (unadjusted) DatetimeIndex tz-naive ET
  intraday/5m/<SYMBOL>.parquet
  intraday/15m/<SYMBOL>.parquet
  intraday/30m/<SYMBOL>.parquet
  intraday/60m/<SYMBOL>.parquet
  daily/<SYMBOL>.parquet           # RTH-only aggregate, date index
  ref/splits.parquet               # canonical splits (symbol, date, from, to)
  .yf_cache/                       # BarStore yfinance fallback cache (1d TTL)
  _catalog.parquet                 # coverage per (symbol, freq)
```

**Schema (unified across sources):** `open/high/low/close` float32, `volume` int64,
`amount` float64 (dollar volume; NaN for 2015-2023). Index = `timestamp`/`date`.

**Splits:** table at `ref/splits.parquet` (4959 rows, 2821 tickers, 1978-2026).
Applied forward at READ TIME by `BarStore`:
```
adj_factor(t) = Π (from_i / to_i) over splits i where date_i > t
adj_price = raw_price * factor; adj_volume = raw_volume / factor
```
(Note: `美股复权计算方法.md` in source describes backward-adjust despite calling
it 前复权; we use standard forward adjust to match quant convention / yfinance.)

**BarStore API (`core/data/bar_store.py`):**
```python
store = BarStore()
df = store.load("SPY", freq="1m", adjusted=True)              # local + yfinance tail-fill
df = store.load("SPY", freq="60m", fallback="local")          # local only
df = store.load("SPY", freq="daily", fallback="yfinance")     # yfinance only (cached)
raw = store.load("AAPL", freq="1m", adjusted=False)           # pre-split RAW
```

**ETF gap & yfinance fallback:** Because 2024+ source has stocks only, ETF 1m
bars stop at 2023-12-31 locally. `BarStore.load(..., fallback="auto")` (default)
auto-fills the tail from yfinance. yfinance coverage:
- 1m: last 59 days only
- 5m/15m/30m/60m: last 720 days
- daily: full history

**Validated reliability (2015-01 window, apples-to-apples split-only):**
- Open/High/Low median error: **0.000%** across all 8 test symbols
- Close median error: 0.000–0.067% (max 0.134%)
- Tiny close diffs = closing auction (16:00) vs last 15:59 1m bar; not a data bug

**Scripts:**
```bash
python scripts/build_splits_parquet.py            # refresh splits.parquet
python scripts/build_bars_parquet.py --phase all --workers 6   # full ingest + consolidate
python scripts/build_bars_parquet.py --month-only 202401 --workers 6  # single month
python scripts/aggregate_bars.py                  # 1m → 5m/15m/30m/60m/daily
python scripts/aggregate_bars.py --symbols SPY AAPL   # filter to symbols
python scripts/build_catalog.py                   # build _catalog.parquet
python scripts/validate_vs_yfinance.py --freq daily --mode split --symbols SPY AAPL
python scripts/validate_vs_yfinance.py --freq 1m --symbols AAPL  # needs 2026-02+ ingested
```

**Invariant:** Bars stored RAW (unadjusted). Adjustment is applied only at read
time by `BarStore.load(adjusted=True)` using splits.parquet. This keeps the
storage vendor-agnostic — swapping 2024+ source (adding ETFs) requires only
re-running `build_bars_parquet.py`, not reprocessing splits or downstream code.

### Trades Backfill Pipeline [NEW 2026-04-20]

**Problem:** Upstream 2024-2025/11 source (per-ticker CSV in
`~/Documents/projects/Data/1m/`) is stocks-only — no ETFs. This created a
major data gap for SPY/QQQ/XL*/GLD/TLT/etc. 2024+ bars.

**Solution:** separate ingestion pipeline consuming tick-level trade data
from encrypted zips (`trades_v1_YYYY-MM-DD.csv.gz` / `.csv`):

- Source: `/mnt/c/Users/Admin/Documents/projects/trades/**/YYYYMMDD.zip`
  (one zip per trading day, ~1.7-4GB, AES-encrypted)
- Password: `sha256(basename + "vvtr123!@#qwe")` — per-zip dynamic
- Schema: `ticker,conditions,correction,exchange,id,participant_timestamp,`
  `price,sequence_number,sip_timestamp,size,tape,trf_id,trf_timestamp`
- Aggregation: tick-level → 1m bars with extras (n_trades, vwap,
  buy/sell_volume_proxy, large_trade_volume, block_n, exch_top1_share)

**Strategy B (chosen merge policy):**
  Trades scanner only writes tickers NOT already present in
  `.staging/<month>/`. This preserves existing stocks_csv bars unchanged
  while filling ETF gaps. Avoids volume semantics conflicts between
  sources.

**Filter rules (`trades_v2_late_report_dedup_2026-04-19`):**
  - `correction < 1` (drop corrected/cancelled)
  - Drop trades in `DROP_EXCHANGES = {4}` (FINRA ADF OTC duplicate prints)
  - Drop trades whose `conditions` include any `LATE_REPORT_CONDS = {14,
    16, 18, 19, 20, 22, 29, 31, 32, 33, 34, 38, 39, 42, 43, 45, 47-51,
    54-58}` (late/delayed duplicate reports per vendor's condition table)

**Resilience:**
  - Atomic parquet writes via tmp + rename (interrupted process leaves
    clean main file)
  - Peak memory lock (`/tmp/trades_scanner_peak.lock`, `fcntl.LOCK_EX`)
    serializes parse+filter+aggregate across parallel scanner instances
    to prevent OOM on 15GB system
  - Per-instance state file (`data/trades_scanner_state_<year>.json`) and
    per-instance `/tmp/scanner_<label>_decrypt.csv` support multi-scanner
    orchestration
  - `disk_guard.py` watches `/mnt/c` free space; kills Baidu Netdisk
    processes if < 30GB to prevent disk fill

**Scripts:**
```bash
python scripts/trades_scanner.py --watch [--year-include 2024] \
    [--state-file ...] [--decrypt-tmp /tmp/...]           # main ingester
python scripts/scanner_sequential_2026_2025.py --a-pid ... # 2026→2025 chain
python scripts/scanner_terminator.py --pid ... --year 2025 \
    --completion-date 20251231                             # year-end gate
python dev/scripts/ops/disk_guard.py                              # C: drive guard
python scripts/consolidate_trades.py                      # .staging_trades → root
python scripts/consolidate_sanity_check.py                # cross-source price sanity
python scripts/post_processing_pipeline.py [--skip-wait]  # end-to-end orch
```

**Final state after 2024+2025+2026 ingest (2026-04-20):**
  - 25,355 symbols across 1m/5m/15m/30m/60m; 25,329 daily
  - 1m: 4.03B rows, 84.6GB on disk
  - 0 failed zips after retries
  - Universe tickers (37) refreshed from yfinance canonical daily (covers
    2015 polygon_gz gaps on low-volume ETFs like VLUE)
  - Macro reference (^VIX, ^TNX, DX-Y.NYB) fetched from yfinance
  - Known issues: ZTST has 2 sentinel bars at $12345 on 2025-11-28 and
    2025-12-24 (vendor source bug; not systemic — see
    `reports/known_data_issues/ztst_sentinel.md`)

**Hard rule for future data ingestion:** any new ingestion script MUST
synchronously write `data/ref/bar_provenance.parquet` rows using the same
schema as `trades_scanner.update_provenance()` (symbol, freq, source_type,
rule_version, first_bar_ts, last_bar_ts, n_bars_added, updated_at). This
keeps the provenance sidecar in sync without migration scripts.

---

### Data Provenance Sidecar [NEW 2026-04-20]

Every (symbol, freq) has explicit source metadata in
`data/ref/bar_provenance.parquet`. Consumers use this to:
  - detect cross-source merge artifacts (sanity check)
  - mask volume-sensitive factors for `trades_backfill` tickers (factor
    guard — see `DataSensitivityConfig`)
  - attribute strategy performance by data epoch in reports

**Source types:**
  - `polygon_gz` — 2015-2023 Polygon flat files (full market)
  - `stocks_csv` — 2024-01 to 2025-11 per-ticker CSV (stocks only)
  - `stocks_csv_c_drive` — 2025-12+ per-ticker CSV (stocks only, C: drive)
  - `trades_backfill` — 2024+ tick-level trades (ETF + stocks not in csv)
  - `yfinance_daily` — universe ETFs + macro refs (canonical adjusted daily)
  - `yfinance_fallback` — on-the-fly yfinance fill when BarStore detects
    a tail gap (fallback='auto')

**API:**
```python
from core.data.bar_store import BarStore
store = BarStore()
df = store.load("SPY", freq="1m", fallback="auto")
print(df.attrs["provenance"])  # list of rows
print(store.get_provenance("SPY", "1m"))
```

**Factor guard:**
```yaml
# config/universe.yaml
data_sensitivity:
  volume_sensitive_factors: [volume_surge_20d, price_volume_div, ...]
```
```python
from core.factors.factor_generator import generate_all_factors
factors = generate_all_factors(price_df, volume_df,
                               backfill_tickers=backfill_set)
# volume-sensitive factors get NaN for backfill tickers
```

---

### Factor Pipeline Contract [NEW 2026-04-20, 约束 2]

Single source of truth: `core/factors/factor_registry.py`

| Registry | Contents | Role |
|----------|----------|------|
| `PRODUCTION_FACTORS` | 6 names (low_vol, momentum, quality, pv_div, rel_strength, market_trend) | Accepted by `MultiFactorStrategy.factor_weights`; tuned by `MultiFactorSpace.suggest()` |
| `RESEARCH_FACTORS` | 35 names from `factor_generator.generate_all_factors` | Available for IC / OOS / regime research only |
| `RESEARCH_TO_PRODUCTION_MAP` | dict: research name → production name | Documents which research factor is already represented by which production factor |

**Gate behavior:**
- `MultiFactorStrategy.__init__` calls `check_execution_factor_names(weights)`; unknown names logged at WARNING and **dropped** from composite computation — prevents research names (e.g. `price_volume_div`) silently appearing in execution
- `MultiFactorSpace.__init__` asserts `_TUNED_FACTORS == PRODUCTION_FACTORS` — if registry changes without updating the space, mining fails fast

**Promotion flow (manual, one-way: research → production):**
```
1. Add candidate to factor_generator.generate_all_factors + RESEARCH_FACTORS
2. Run scripts/run_factor_screen.py  → IC + significance
3. Run scripts/run_xgb_importance.py → OOS attribution
4. If funnel passes:
   a. Add inline computation block to MultiFactorStrategy.generate()
   b. Add name to PRODUCTION_FACTORS + production_factor_names()
   c. Add weight slot + range to MultiFactorSpace.suggest() and
      MultiFactorSpace._TUNED_FACTORS
   d. Add entry to RESEARCH_TO_PRODUCTION_MAP if it shadows a research name
   e. Re-run full suite (test_factor_registry enforces consistency)
```

**Research-only vs shadowed-research** (at current registry state):
- Shadowed (10 factors): e.g. `vol_63d` ↔ `low_vol`; research form kept for granular analysis, production form kept for execution stability
- Research-only (25 factors): e.g. `reversal_5d`, `overnight_gap_21d`, `advance_ratio_10d`, `rs_acceleration` etc. — available in research but cannot drive execution until promoted

This ends the previous "dual-track, unclear relationship" state. Tests:
`tests/unit/factors/test_factor_registry.py` (10 tests).

---

### Multi-TF Timing Contract [NEW 2026-04-20, 约束 3]

The multi-timescale framework is **NOT** a standalone alpha system. The
iter #9/#10/#11 validation sprint proved the naive bar-direction voting
approach produces strictly lower Sharpe than a 60m-only baseline and
fails cost-stress at even 0.1× base cost. Multi-TF is repositioned as a
TIMING / EXECUTION / RISK layer on top of daily MFS.

**Role by TF:**

| TF | Role | Authority |
|----|------|-----------|
| 60m | Primary context / regime / direction check | Can VETO a daily target (scale → 0 if contradicts strongly) |
| 30m | Secondary confirmation / risk state | Confidence penalty on timing_scale |
| 15m | Execution trigger / timing | DEFER only — cannot flip direction |
| 5m | Fine execution trigger | DEFER only — cannot flip direction |

**Canonical API:**
```python
from core.intraday.multi_timescale import build_context, decide_timing

ctx = build_context(multi_bars, symbol, bar_ts)
decision = decide_timing(ctx, symbol, base_weight=0.3, daily_side=1)
# decision.execute         : bool — route orders this bar?
# decision.timing_scale    : float [0,1] — scale of base_weight
# decision.effective_weight: base_weight × timing_scale if execute else 0
# decision.higher_tf_vote  : per-TF {confirm / contradict / neutral / absent}
# decision.reason          : confirmed / soft_contradict / deferred / ...
```

**Contract invariants (enforced by `tests/unit/intraday/test_timing_decision.py`):**
- Lower TF (15m/5m) adverse → `execute=False` (defer), **never** flip
- `effective_weight ≥ 0` for any TF combo (long-only)
- No higher context → pass-through (`execute=True, timing_scale=1.0`)
- Short side (`daily_side=-1`) → `execute=False` (system is long-only)
- `base_weight=0` → `execute=False` (nothing to time)

**Validation approach (replaces "does multi-TF beat 60m on CAGR?"):**
`scripts/validate_timing_value.py` measures timing-relevant metrics:
  - Entry bps vs day mean (timed vs naive first-bar-open execution)
  - Defer rate (what % of days timing deferred past first bar, to EOD)
  - Average applied timing_scale

Initial run (5 symbols × 2871 daily events, 2024-01 to current):
  - naive  entry: mean +0.25 bps vs day mean (median -4.22 bps)
  - timed  entry: mean -0.33 bps vs day mean (median -3.12 bps)
  - deferred ≥1 bar: 34.3% of days
  - deferred to EOD: 0.0% (1/2871)
  - avg timing_scale: 0.717

Interpretation: timing is approximately a wash on entry bps. Real value
(if any) must come from compounding over full position path + downstream
slippage — the current simple "mean vs day close" proxy is too coarse.
The script is a placeholder that keeps the right questions in view; a
more sophisticated validation (holding-period tracking, turnover delta)
is future work.

**Legacy `evaluate_cross_tf_signal` / `CrossTFSignal`:** kept as a back-
compat shim — do not remove; existing scripts (run_multi_tf_backtest,
validate_combo_tfs, etc.) still consume it. New code should use
`decide_timing` / `TimingDecision`.

---

### Notify Module [NEW 2026-04-20]

Channel-agnostic notifier for paper trading alerts, kill-switch events,
daily PnL summaries.

Backends:
  - `wecom_bot` — WeChat Work group-bot webhook (recommended, no rate limit)
  - `server_chan` — Server 酱 Turbo (5/day free; keep for criticals)
  - `stdout` — dev / testing
  - `null` — disabled (default)

API:
```python
from core.notify import get_notifier
n = get_notifier()  # reads config/notify.yaml
n.info("Daily summary", f"NAV={nav:,.0f}, PnL={pnl:+.0f}")
n.error("Kill switch stage 2", f"drawdown={dd:.2%}")
```

All sends return `SendResult` (never raises on transport failure). Rate
limit + min_level gating built-in. Credentials via env var expansion
(`${PQS_WECOM_WEBHOOK_URL}`) — never commit secrets.

---

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

**Framework Completion PRD** (`docs/20260421-prd_framework_completion.md`
v1.2) — shipped M0-M8 + M10 + M13 + M15 + M16 (see archive); open:

- [ ] **M11** paper-BT consistency gate in pack v3 (P1.5, 1-2d). Replay
  spec over 126d, diff equity vs fresh backtest, fail if > 10 bps drift.
  Currently skip-PASS.
- [ ] **M12** concentration gate real enforcement (P2, 0.5d). Inspect
  fresh-backtest weight matrix for per-date top-1/top-3 concentration;
  reject if top-1 > 0.40 or top-3 > 0.70. Currently skip-PASS.
- [ ] **M14** BacktestEngine NaN root-cause fix (P2, 1d; conditional).
  Ghost-cleanup + NaN last-price can produce NaN as equity last bar.
  Pack v2 workaround uses `.dropna()` before CAGR; also surfaces in
  R6 Candidate-2 paper run `final_equity=NaN`.
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
