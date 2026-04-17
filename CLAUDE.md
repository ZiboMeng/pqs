# PQS — Personal Quantitative System

## Phase B: Continuous Loop Iteration PRD

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

### Current System State (Phase A Completed)
Architecture: config/ → core/ → scripts/ → tests/ with 615 passing unit tests.

**Already implemented (Round 1-5):**
- Point-in-time universe (32 symbols with first_trade_dates, survivorship bias prevention)
- 6-regime robustness testing (BULL/RISK_ON/NEUTRAL/CAUTIOUS/RISK_OFF/CRISIS)
- 4 stress period tests (2008 crisis, 2020 COVID, 2022 rate hike, 2018 Q4)
- Forward-block holdout (last 252d invisible during mining)
- Quick filter data isolation (Stage 1 uses first 70% of non-holdout)
- Walk-forward test_bars by strategy frequency (trend=126d, monthly=252d)
- Regime-aware OOS pass rate (defensive windows use relaxed DD criteria)
- OOS/IS Sharpe ratio overfit gate (< 0.50 → Tier D)
- Mining evaluator 5-stage pipeline: Quick → OOS → Robustness+Stress → Diversity → Holdout
- Master report with regime-stratified perf, strategy attribution, bt-vs-paper reconciliation
- Diagnostics module: FactorDecay, CostDrift, StrategyAlpha, PaperBtDivergence detectors
- Kill switch 3-tier: NORMAL → DEGRADED (50% position) → SUSPENDED (0%) with auto-recovery
- TimeframeOptimizer integrated into FeaturePipeline
- Archive with full audit trail (stress/holdout/overfit columns, DB migration support)

**Completed in Loop 1-44 (46 commits, 654 tests, 87 mining trials):**

Infrastructure:
- ✅ Daily data 2007-2026 (35 symbols) + 60m intraday (32 symbols)
- ✅ Real T+1 open price execution (not close approximation)
- ✅ Integer share mode in BacktestEngine
- ✅ 654 unit tests passing
- ✅ 9 runnable scripts via run_all.sh (12 modes incl. research/universe/factors/xgb)

Validation (11 criteria, all implemented):
- ✅ Walk-forward OOS (32 windows, regime-aware pass criteria)
- ✅ Expanding window validation (recursive training growth)
- ✅ Forward-block holdout (last 252d invisible during mining)
- ✅ Data isolation (Stage 1 uses first 70% of non-holdout)
- ✅ 4 stress period tests (2008, 2020-COVID, 2022, 2018-Q4)
- ✅ Subperiod robustness (no quartile > 50% contribution)
- ✅ Cost sensitivity (robust to 3x)
- ✅ Parameter sensitivity (±20% → Sharpe change < 50%)
- ✅ Regime robustness (6 regimes, differentiated criteria)
- ✅ OOS/IS Sharpe overfit gate
- ✅ Diversity gate (correlation < 0.70)

Mining & Factors:
- ✅ 5-stage mining pipeline: Quick → OOS → Robustness+Stress+Subperiod → Diversity → Holdout
- ✅ 30 candidate factors (momentum, vol, quality, volume, relative strength, macro)
- ✅ GBM feature importance analysis
- ✅ MultiFactorStrategy (6-factor composite)
- ✅ 6 strategies promoted (all Tier B, real open validated, 49% pass rate)

Execution:
- ✅ Paper trading daily-mode (shared BacktestEngine rebalance logic)
- ✅ Paper-backtest consistency < 0.2% (same period, same signals)
- ✅ Kill switch 3-tier from config (NORMAL→DEGRADED→SUSPENDED, auto-recovery verified)
- ✅ Diagnostics suite (4 detectors) wired into paper trading EOD

Reporting:
- ✅ Master report: regime-stratified (vs SPY + vs QQQ), strategy attribution, bt-paper reconciliation
- ✅ Universe rebalance script (PIT + cross-sectional scoring)
- ✅ Factor IC screening script
- ✅ GBM feature importance script

**Current best validated strategy (real open prices, target_vol=0.25):**
- multi_factor b713867fe630 (Tier B): OOS IR=0.40, pass_rate=70%, holdout +14.4%
- Full-period: CAGR 18.9%, Sharpe 0.98, MaxDD -19.7%, IR 0.33
- Params: RS=0.30, momentum=0.30, quality=0.20, market_trend=0.10, pv_div=0.05
- All robustness checks pass (regime, cost, param, stress, subperiod, holdout)

**Key discoveries (Loop 1-47):**
1. Real open price reveals 5% CAGR overestimation vs close approximation (Loop 26-27)
2. target_vol=0.25 (was 0.15) breaks OOS bottleneck — pass rate 0%→49% (Loop 33)
3. Vol_parity harmful for multi_factor (already has low_vol factor) (Loop 10)
4. Relative strength + momentum are dominant alpha sources (Loop 15, 25)
5. Kill switch config must match risk.yaml — 5% threshold gap caused 37% paper-bt divergence (Loop 42)

**Remaining gaps (minor):**
- ML signals used for analysis only, not as trading signal
- Intraday pipeline not built
- Left-side trading module implemented (Loop 45) but not yet backtested for impact

### Intraday Quantitative Pipeline (to be built in loop iterations)
    1. Download intraday data (60m/30m/15m) via fetch_data.py --intraday-only
    2. Build intraday-specific strategies (60m momentum, mean-reversion, volatility breakout)
    3. Wire IntraDayBacktestEngine into mining pipeline with proper intraday cost model
    4. Intraday-specific validation: avoid first/last bar, EOD force close, overnight risk
    5. Separate intraday mining archive and leaderboard from interday
    6. Master report must have TWO sections: interday performance + intraday performance
    7. Intraday and interday strategies should be independently evaluated, reported, and promoted
    8. Future goal: portfolio-level combination of best interday + best intraday strategies

### Priority Stack (P1 = highest)
```
### P1 Expansion: Intraday Quantitative Pipeline (to be built in loop iterations)
    1. Download intraday data (60m/30m/15m) via fetch_data.py --intraday-only
    2. Build intraday-specific strategies (60m momentum, mean-reversion, volatility breakout)
    3. Wire IntraDayBacktestEngine into mining pipeline with proper intraday cost model
    4. Intraday-specific validation: avoid first/last bar, EOD force close, overnight risk
    5. Separate intraday mining archive and leaderboard from interday
    6. Master report must have TWO sections: interday performance + intraday performance
    7. Intraday and interday strategies should be independently evaluated, reported, and promoted
    8. Future goal: portfolio-level combination of best interday + best intraday strategies
P1. Backtest realism
P2. Validation rigor
P3. Strategy/factor mining quality
### P3 Expansion: Factor & ML Mining (to be built in loop iterations)                                                                                                                       
    1. Build factor generation pipeline — auto-construct candidate factors from OHLCV + macro features
    2. Wire factor_evaluator to real candidates — run IC screen, quintile analysis, decay detection on generated factors
    3. Integrate XGBoost for feature importance analysis + nonlinear alpha signal generation
    4. Implement SHAP-based factor attribution — understand which factors drive predictions
    5. Build multi-factor combination layer — weighted scoring or ML ensemble → composite alpha signal
    6. Establish factor research funnel: generate → IC screen → OOS validate → regime robustness → promote/reject
    7. Add new strategy structure discovery beyond the 3 existing templates (e.g., mean-reversion, statistical arbitrage pairs within ETF universe, volatility harvesting)
    8. Connect ML signals to existing backtest/execution pipeline with same T+1 open execution semantics
P4. Universe selection quality
P5. Internal paper trading ↔ backtest consistency
P6. Unified master report
P7. Failure detection & strategy degradation
P8. Tech debt affecting research credibility
```
If "add new strategy" conflicts with "fix backtest distortion", fix distortion first.

### Research Funnel
```
Candidate Pool → Research Pool → Validation Pool → Keep Pool
                                                  ↘ Reject/Downgrade Pool
```
Every rejected candidate must be logged with reason in archive. No blind brute-force mining.

Validation Pool criteria (all implemented and enforced in mining evaluator):
- ✅ Walk-forward OOS (regime-aware pass criteria, type-specific test_bars)
- ✅ Expanding window (recursive training set growth)
- ✅ Forward-block holdout (last 252d invisible during mining)
- ✅ Parameter sensitivity (±20% → Sharpe change < 50%)
- ✅ Cost sensitivity (2x cost → still positive alpha)
- ✅ Regime robustness (growth ≥2 positive, defensive ≥1 not worse than SPY)
- ✅ Stress period survival (DD ≤ 25% in 2008, 2020-COVID, 2022, 2018-Q4)
- ✅ Subperiod robustness (no single quartile > 50% contribution)
- ✅ OOS/IS Sharpe ratio ≥ 0.50
- ✅ Holdout IR ≥ 0.20
- ✅ Diversity (correlation < 0.70 with existing promoted strategies)

### Autonomous Decision Authority
Authorized WITHOUT confirmation:
- Code changes, module splits, local refactors for optimization goals
- New factor/strategy candidates, experiments, analysis scripts
- Config enhancements, threshold tuning
- Test additions, tech debt cleanup
- Diagnostics/report/validation pipeline improvements
- Strategy/factor demotion, suspension, re-scoring
- Research funnel maintenance

MUST PAUSE for confirmation:
- Changing core constraints (long-only, no-margin, benchmark logic, etc.)
- Changing research boundaries (adding 15m to main system, new data sources, etc.)
- Changing evaluation criteria definitions
- Repo-level restructuring with direction forks
- Discovering that confirmed direction has serious flaws

### Loop Iteration Protocol

**Each iteration MUST:**
1. Identify 1-2 highest-leverage improvements based on current system state
2. Implement changes (code + config + tests as needed)
3. Run verification (at minimum `pytest tests/unit/ -x -q --ignore=tests/unit/regime`)
4. When doing mining/backtest work, run appropriate scripts (`run_backtest.py`, `run_mining.py`)
5. Output structured report (see format below)
6. Persist iteration log to `reports/loop_changelog.md`
7. Update memory system with significant findings

**Iteration can be:**
- Lightweight: code improvement + unit test verification (10-15 min)
- Medium: code change + backtest-quick validation (15-30 min)
- Full research: data fetch + mining run + analysis + report (30+ min)

The iteration depth should match the task — don't force full mining for a config fix, don't skip validation for a backtest logic change.

**Iteration output format:**
```
## Loop Iteration N — [date]

### 1. 本轮目标
[What and why]

### 2. 为什么优先做这个
[Leverage analysis]

### 3. 已完成
[List of changes with file:line references]

### 4. 代码改动说明
For each change:
- 改了什么
- 为什么改
- 预期改善什么
- 怎么验证
- 副作用或限制

### 5. 验证结果
[Test results, backtest metrics if run]

### 6. 风险点
[Known risks or limitations]

### 7. 待确认
["无" if nothing needs user input]

### 8. 下一轮最可能的高杠杆改进项
[What to do next and why]
```

### Key File Locations
- Config: `config/*.yaml` (system, backtest, universe, risk, cost_model, reporting, regime, events)
- Strategies: `core/signals/strategies/` (dual_momentum, trend_following, cross_asset_rotation)
- Mining: `core/mining/` (miner, evaluator, archive, strategy_space)
- Factors: `core/factors/` (factor_engine, factor_evaluator)
- Backtest: `core/backtest/` (backtest_engine, intraday_engine, window_analyzer)
- Diagnostics: `core/diagnostics/detectors.py`
- Risk: `core/risk/` (failure_detector, kill_switch, stress_tester)
- Reporting: `core/reporting/` (master_report, master_report_builder)
- Paper trading: `core/paper_trading/` (paper_trading_engine, pnl_tracker)
- Universe: `core/universe/` (universe_manager, asset_scorer)
- Data: `core/data/` (yfinance_provider, market_data_store, validator, calendar)
- Scripts: `scripts/` (run_all.sh, fetch_data.py, run_backtest.py, run_mining.py, run_paper.py, generate_report.py)
- Tests: `tests/unit/` (mirrors core/ structure, 615 passing)

### Scripts Quick Reference
```bash
# Full pipeline (data + backtest + report)
bash scripts/run_all.sh full

# Data fetch only
python scripts/fetch_data.py

# Backtest only (quick = skip walk-forward)
python scripts/run_backtest.py
python scripts/run_backtest.py --no-walk-forward

# Mining
python scripts/run_mining.py --trials 80 --budget 3600
python scripts/run_mining.py --leaderboard

# Paper trading
python scripts/run_paper.py
```

### Left-Side Trading Rules
- Disabled in CRISIS regime
- Max 20% of total position
- Under kill switch jurisdiction
- Must be researched, reported, and measured separately
- If it doesn't stably improve "beat SPY/QQQ + low DD + black swan resilience", demote or disable

### Changelog Location
Iteration logs: `reports/loop_changelog.md`
Memory: `/Users/zibo/.claude/projects/-Users-zibo-Documents-pqs/memory/`
