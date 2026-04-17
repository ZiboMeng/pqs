# PQS — Personal Quantitative System

## Phase C: Continuous Development PRD

### System Identity
个人量化研究与模拟交易系统。目标：长期可持续跑赢 SPY/QQQ，保持低回撤（15%-20%），具备黑天鹅韧性。

### Invariant Constraints (NEVER violate without explicit user approval)
- long-only, no-margin, no-short
- SQQQ blacklisted; TQQQ/SOXL require stricter risk thresholds
- No real broker/API integration this phase; paper trading = internal simulation
- macOS local execution; no AWS/cloud deployment priority
- Benchmark: SPY primary, QQQ secondary; excess vs QQQ >= -2%
- Left-side trading = enhancement module only, never default engine
- Intraday: 60m/30m primary, 15m research only
- All thresholds must be configurable (config/*.yaml), never hardcoded
- Must preserve backtest-execution consistency
- Chinese reporting, English code naming
- Initial capital ~$10,000, must scale to $1M+
- Max drawdown target 15%-20%, not worse than SPY in crisis

### Current System State (Phase 0 Audit, 2026-04-17)

**Architecture:** config/ → core/ → scripts/ → tests/ with 674 passing unit tests, 51 commits.

#### Confirmed Done (verified in code)
- ✅ Daily data 2007-2026 (37 symbols) + 60m intraday (32 symbols)
- ✅ Real T+1 open price execution in BacktestEngine (open_df parameter)
- ✅ Paper-backtest shared rebalance logic (run_day_daily uses BacktestEngine._generate_orders)
- ✅ Kill switch 3-tier (NORMAL→DEGRADED→SUSPENDED) with auto-recovery, from risk.yaml
- ✅ Cost accounting: separate slippage (in exec price) + commission (in cash), CostBreakdown
- ✅ Integer share mode in BacktestEngine
- ✅ Walk-forward OOS (32 windows, regime-aware pass criteria)
- ✅ Expanding window validation
- ✅ Forward-block holdout (last 252d invisible during mining)
- ✅ Data isolation (Stage 1 uses first 70% of non-holdout)
- ✅ 4 stress period tests (2008, 2020-COVID, 2022, 2018-Q4)
- ✅ Subperiod robustness (no quartile > 50% contribution) in evaluator Stage 3c
- ✅ Cost sensitivity (robust to 3x)
- ✅ Parameter sensitivity (±20% → Sharpe change < 50%)
- ✅ Regime robustness (6 regimes, differentiated criteria)
- ✅ OOS/IS Sharpe overfit gate
- ✅ 5-stage mining pipeline: Quick → OOS → Robustness+Stress+Subperiod → Diversity → Holdout
- ✅ 30 candidate factors in factor_generator.py (5 families + 3 macro)
- ✅ GBM feature importance analysis (sklearn GradientBoosting)
- ✅ MultiFactorStrategy (6-factor composite with market_trend)
- ✅ Left-side trading module (core/signals/left_side.py) — standalone, backtested zero-harm
- ✅ Master report: regime-stratified (vs SPY + vs QQQ), strategy attribution
- ✅ Universe rebalance script (PIT + cross-sectional scoring)
- ✅ Diagnostics suite (4 detectors) wired into paper trading EOD
- ✅ target_vol=0.25 (optimized from 0.15)

#### Partially Done (needs hardening)
- ⚠️ Paper-BT consistency claimed < 0.2% but NO automated test exists
- ⚠️ Factor generator exists separately from MultiFactorStrategy (MFS computes factors internally)
- ⚠️ Left-side module implemented but config/risk.yaml left_side_trading NOT consumed by any code
- ⚠️ fetch_data.py has incremental daily but intraday always re-downloads full window

#### Missing / Not Implemented
- ❌ MultiFactorStrategy has ZERO unit tests (mission-critical code)
- ❌ Intraday live mode (run_paper.py --mode live) only prints weights, doesn't execute
- ❌ Real XGBoost — script uses sklearn GradientBoostingRegressor, not xgboost
- ❌ No paper-backtest consistency automated test
- ❌ Intraday pipeline not truly multi-asset capable
- ❌ No SHAP-based factor attribution
- ❌ Factor generator not integrated into mining loop (MFS has own factor computation)

#### Docs Inconsistencies
- CLAUDE.md previously said "XGBoost" but code uses sklearn
- "6 promoted" vs actual archive state may differ
- "Paper-BT < 0.2%" claimed without test backing

### Current Best Strategy (real open prices, target_vol=0.25)
- multi_factor: CAGR 18.9%, Sharpe 0.98, MaxDD -19.7%, IR 0.33
- Params: RS=0.30, momentum=0.30, quality=0.25, market_trend=0.10, pv_div=0.05
- OOS IR=0.40, pass_rate=70%, holdout excess=+14.4%
- All robustness checks pass (regime, cost, param, stress, subperiod, holdout)

### Key Discoveries (Phase B, Loop 1-50)
1. Real open price reveals 5% CAGR overestimation vs close approximation
2. target_vol=0.25 (was 0.15) breaks OOS bottleneck — pass rate 0%→49%
3. Vol_parity harmful for multi_factor (already has low_vol factor)
4. Relative strength + momentum are dominant alpha sources
5. Kill switch config must match risk.yaml — threshold mismatch caused 37% paper-bt divergence

---

## Phase C Execution Plan

### Priority Order (highest first)

```
P0. Fix critical test gaps (MultiFactorStrategy tests, paper-BT consistency test)
P1. Backtest / replay / paper consistency hardening
P2. Intraday pipeline truly functional
P3. Factor research closed loop + real XGBoost/SHAP
P4. Performance, scalability, data vendor prep
```

### Phase 1: Core Consistency Hardening

**Goal:** Ensure backtest, replay, and paper trading are provably consistent.

Must do:
1. Add MultiFactorStrategy unit tests (factor computation, signal generation, regime scaling, min_holding_days)
2. Add test_backtest_paper_consistency integration test (same signals → same fills → <1% equity divergence)
3. Verify replay uses real next-day open (already confirmed, add regression test)
4. Verify stressed cost actually changes backtest results (add parametric test)
5. Wire left_side_trading config from risk.yaml into LeftSideTrading class
6. Add strict_match mode concept documentation

Acceptance:
- MultiFactorStrategy has ≥10 unit tests
- Paper-BT consistency has automated test with threshold
- Stressed cost test proves results differ

### Phase 2: Intraday Pipeline

**Goal:** Make intraday backtest + paper trading actually executable, not scaffolding.

Must do:
1. Audit IntradayBacktestEngine for real multi-asset support
2. Make run_paper.py --mode live actually execute trades (not just print weights)
3. Add bar-level persistence for intraday paper trading
4. Handle edge cases: incomplete bars, half days, missing symbols
5. Unify intraday backtest / replay / live execution path

Acceptance:
- Intraday backtest runs on 60m data for 5+ symbols
- Live paper mode writes fills and positions to DB
- Bar-level state can be reloaded after restart

### Phase 3: Factor Research Loop + ML

**Goal:** Close the factor research loop and add real ML support.

Must do:
1. Replace sklearn GradientBoosting with real XGBoost (fix OpenMP/libomp first)
2. Add SHAP or permutation importance for factor attribution
3. Expand factor families (overnight, regime-conditioned, interaction, breadth)
4. Wire factor_generator into mining pipeline (or document why MFS internal is better)
5. Build structured factor candidate tracking (hypothesis → validate → keep/reject)

Acceptance:
- Real XGBoost runs and produces feature importance
- New factor families have IC screening results
- Factor research funnel has structured archive

### Phase 4: Performance & Scalability

**Goal:** Remove bottlenecks, prepare for larger-scale research.

Must do:
1. Incremental intraday data updates (not full re-download)
2. Mining parallelization (safe archive access)
3. Cache expensive computations (regime, aligned matrices)
4. DataProvider abstraction review for future vendor swap

Acceptance:
- Same workload runs faster
- No correctness regression from parallelization

---

## Autonomous Decision Authority (inherited from Phase B)

Authorized WITHOUT confirmation:
- Code changes, module splits, local refactors for optimization goals
- New factor/strategy candidates, experiments, analysis scripts
- Config enhancements, threshold tuning
- Test additions, tech debt cleanup
- Diagnostics/report/validation pipeline improvements
- Strategy/factor demotion, suspension, re-scoring

MUST PAUSE for confirmation:
- Changing core constraints (long-only, no-margin, benchmark logic, etc.)
- Changing research boundaries (adding 15m to main system, new data sources, etc.)
- Changing evaluation criteria definitions
- Repo-level restructuring with direction forks

## Work Method

Each iteration:
1. 本轮目标
2. 做了什么 + 修改了哪些文件
3. 跑了哪些测试 + 当前结果
4. 剩余风险
5. 下一步

Maintain TODO checklist. Update CLAUDE.md when work is actually completed. Prefer small verifiable patches over large rewrites.

## Key File Locations
- Config: `config/*.yaml` (system, backtest, universe, risk, cost_model, reporting, regime, events)
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
- Data: `core/data/` (yfinance_provider, market_data_store, validator, calendar)
- Scripts: `scripts/` (run_all.sh, fetch_data.py, run_backtest.py, run_mining.py, run_paper.py, generate_report.py, run_factor_screen.py, run_xgb_importance.py, run_universe_rebalance.py)
- Tests: `tests/unit/` (mirrors core/ structure, 674 passing)

## Scripts Quick Reference
```bash
bash scripts/run_all.sh research      # full pipeline: data→universe→factors→mining→backtest
bash scripts/run_all.sh full          # data + backtest + report
bash scripts/run_all.sh mine          # Optuna search (1h)
bash scripts/run_all.sh daily         # daily paper trading
bash scripts/run_all.sh backtest-quick # skip walk-forward
bash scripts/run_all.sh universe      # universe rebalance
bash scripts/run_all.sh factors       # IC screening
bash scripts/run_all.sh xgb           # GBM importance
bash scripts/run_all.sh leaderboard   # mining rankings
```

## Iteration Log
See `reports/loop_changelog.md` for Phase B history (50 iterations).

## IMPORTANT: Git Safety
NEVER use `git add -A` or `git add .` — always add specific files. Files have been accidentally deleted multiple times by broad git adds.
