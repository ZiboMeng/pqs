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

---

### Current System State (Phase 0 Audit, 2026-04-17) [REVISED]

**Architecture:** config/ → core/ → scripts/ → tests/ with 674 passing unit tests, 51 commits.

Evidence levels used below:
- `code_verified`: feature exists in code and logic is correct upon inspection
- `test_verified`: covered by automated unit/integration tests
- `manual_verified`: verified by manual run (script output, backtest result) but no automated test
- `claimed_not_verified`: stated in changelog/docs but not independently confirmed in code or test

#### Confirmed Done

| Feature | Evidence | Notes |
|---------|----------|-------|
| Daily data 2007-2026 (37 symbols) + 60m intraday (32 symbols) | `code_verified` | data/daily/*.parquet, data/intraday/60m/*.parquet |
| Real T+1 open price execution (open_df in BacktestEngine.run) | `code_verified` | backtest_engine.py:119,151; run_backtest.py loads open prices |
| Paper-backtest shared rebalance logic | `code_verified` | paper_trading_engine.py:run_day_daily calls BacktestEngine._generate_orders |
| Kill switch 3-tier with auto-recovery from risk.yaml | `test_verified` | kill_switch.py states; test_kill_switch.py covers transitions |
| Cost accounting: separate slippage + commission | `test_verified` | test_cost_model.py, test_execution_simulator.py |
| Integer share mode in BacktestEngine | `code_verified` | backtest_engine.py:integer_shares param, floor() in _generate_orders |
| Walk-forward OOS (regime-aware pass criteria) | `test_verified` | test_window_analyzer.py covers walk_forward method |
| Expanding window validation | `code_verified` | window_analyzer.py:expanding_window() |
| Forward-block holdout (last 252d) | `code_verified` | evaluator.py data isolation in evaluate() |
| Data isolation (first 70% for quick filter) | `code_verified` | evaluator.py:quick_end_idx |
| 4 stress period tests | `code_verified` | evaluator.py:_check_stress_periods, config/backtest.yaml |
| Subperiod robustness | `code_verified` | evaluator.py:_check_subperiod_robustness |
| Cost sensitivity (2x gate) | `code_verified` | evaluator.py:_check_cost_robustness |
| Parameter sensitivity (±20%) | `code_verified` | evaluator.py:_check_param_robustness |
| Regime robustness (6 regimes) | `code_verified` | evaluator.py:_check_regime_robustness |
| OOS/IS Sharpe overfit gate | `code_verified` | evaluator.py:_assign_tier |
| 5-stage mining pipeline | `code_verified` | evaluator.py:evaluate() stages 1-5 |
| 30 candidate factors | `code_verified` | factor_generator.py:generate_all_factors |
| Feature importance analysis | `code_verified` | run_xgb_importance.py (uses sklearn, NOT xgboost) |
| MultiFactorStrategy (6-factor composite) | `code_verified` | multi_factor.py — BUT 0 unit tests |
| Left-side trading module | `test_verified` | left_side.py + test_left_side.py (10 tests) |
| Factor generator | `test_verified` | factor_generator.py + test_factor_generator.py (10 tests) |
| Master report (regime vs SPY+QQQ, attribution) | `code_verified` | master_report.py, master_report_builder.py |
| Universe rebalance (PIT) | `code_verified` | run_universe_rebalance.py, universe_manager.py |
| Diagnostics suite (4 detectors) | `code_verified` | diagnostics/detectors.py |
| target_vol=0.25 | `code_verified` | constructor.py:_DEFAULT_TARGET_VOL |

#### Partially Done (needs hardening)

| Feature | Evidence | Gap |
|---------|----------|-----|
| Paper-BT consistency < 0.2% | `manual_verified` | Run showed +18.0% vs +18.2% — but NO automated test |
| Left-side zero-harm | `manual_verified` | Manual backtest showed IR 0.327→0.328 — no automated test |
| Factor generator → mining integration | `claimed_not_verified` | MFS computes factors internally, factor_generator.py is unused by mining |
| left_side_trading config consumed | `claimed_not_verified` | risk.yaml has config, but no code reads cfg.risk.left_side_trading |
| Intraday data readiness | `code_verified` | Data exists but intraday engine not wired for multi-asset |
| "6 promoted strategies" | `manual_verified` | Archive DB state — not checked by any test |

#### Missing / Not Implemented

| Feature | Impact |
|---------|--------|
| MultiFactorStrategy unit tests | **Critical**: core strategy has 0 tests |
| Paper-BT consistency automated test | **Critical**: key claim has no test |
| strict_match reconciliation mode | **High**: no formal mechanism for provable consistency |
| Intraday live mode execution | **High**: --mode live only prints, doesn't trade |
| Real XGBoost | **Medium**: script uses sklearn GradientBoosting |
| SHAP attribution | **Medium**: not implemented |
| Intraday multi-asset | **Medium**: engine assumes single-asset patterns |

---

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
P1. Backtest / replay / paper consistency hardening (strict_match mechanism)
P2. Intraday pipeline truly functional
P3. Factor research closed loop + real XGBoost/SHAP + LLM-assisted exploration
P4. Performance, scalability, data vendor / broker prep
```

---

### Phase 1: Core Consistency Hardening [REVISED]

**Goal:** Ensure backtest, replay, and paper trading are provably consistent via a formal `strict_match` mechanism.

#### 1.1 strict_match Formal Mechanism [NEW]

**Config location:** `config/backtest.yaml` → `consistency` section

```yaml
consistency:
  strict_match:
    enabled: false                    # toggle for CI / regression
    zero_cost: true                   # disable slippage + commission
    deterministic_execution: true     # no randomness in fill logic
    force_shared_path: true           # paper must call BacktestEngine._generate_orders
    integer_shares: true              # both sides use floor()
    tolerance_equity_bps: 10          # max daily equity divergence (bps)
    tolerance_position_shares: 0      # exact share match required
    tolerance_cash_usd: 0.01          # rounding tolerance
```

**Behavior in strict_match mode:**
- Cost model returns zero slippage and zero commission
- No stochastic components in execution (no partial fills, no random delays)
- Both backtest and paper MUST use the identical code path for order generation
- Integer shares enforced on both sides
- Same signal → same price → same fills → same positions → same cash → same equity

**Reconciliation products (output of strict_match test):**

| Product | Format | Contents |
|---------|--------|----------|
| fills_reconciliation | DataFrame | date × symbol × side × qty × price — matched pair, mismatch flag |
| positions_reconciliation | DataFrame | date × symbol × backtest_qty × paper_qty × diff |
| cash_reconciliation | Series | date × backtest_cash × paper_cash × diff_usd |
| equity_reconciliation | Series | date × backtest_equity × paper_equity × diff_bps |
| mismatch_summary | Dict | first_mismatch_date, n_mismatches, max_divergence_bps, pass/fail |

**Automated test:** `tests/integration/test_strict_match_consistency.py`
- Run backtest and paper on identical 60-day window
- Assert: fills match exactly (count, symbols, quantities)
- Assert: positions match at every EOD
- Assert: cash divergence < tolerance_cash_usd
- Assert: equity divergence < tolerance_equity_bps at every date
- On failure: output first mismatch date and details

#### 1.2 Other Phase 1 Tasks

1. Add MultiFactorStrategy unit tests: factor computation, signal generation, regime scaling, min_holding_days, edge cases (empty data, single symbol, NaN prices)
2. Verify stressed cost actually changes backtest results (parametric test: 1x vs 2x cost → different equity curves)
3. Wire left_side_trading config from risk.yaml into LeftSideTrading class (read cfg.risk.left_side_trading.*)
4. Add open price regression test (confirm backtest with open_df ≠ without open_df)

#### Phase 1 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| strict_match fills | Exact match: same count, same symbols, same quantities, same prices |
| strict_match positions | EOD positions identical for every date in test window |
| strict_match cash | Daily cash divergence < $0.01 |
| strict_match equity | Daily equity divergence < 10 bps |
| First mismatch reporting | On failure, test outputs: date, symbol, expected vs actual |
| MultiFactorStrategy tests | ≥10 unit tests covering core logic paths |
| Stressed cost test | 1x and 2x cost produce measurably different CAGR (p < 0.01) |
| Left-side config wiring | cfg.risk.left_side_trading values flow to LeftSideTrading constructor |

---

### Phase 2: Intraday Pipeline [REVISED]

**Goal:** Make intraday backtest + paper trading actually executable, multi-asset, persistent, and recoverable.

#### 2.1 Intraday Data Contract [NEW]

**Canonical representation:**
```
Dict[str, pd.DataFrame]  # symbol → OHLCV DataFrame
```
Rationale: simpler than MultiIndex; each symbol is independent; consistent with daily data loading pattern.

**Bar data minimum fields:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| open | float | yes | |
| high | float | yes | |
| low | float | yes | |
| close | float | yes | |
| volume | float | yes | |
| timestamp | DatetimeIndex | yes | tz-naive ET (see rules below) |

**Timezone and time rules:**
- All intraday timestamps are **tz-naive, US/Eastern** (matching yfinance output after `align_intraday_index`)
- DST transitions: handled by `pandas_market_calendars`; the calendar module already normalizes
- Half-day sessions (e.g., day before Thanksgiving): detected via market calendar; `min_tradeable_bars_per_day` config skips days with too few bars
- Timestamp normalization: bar start time (e.g., 09:30 for first 60m bar = 09:30-10:30)

**Missing and anomalous bar handling:**

| Scenario | Behavior |
|----------|----------|
| Missing bars for a symbol | Skip that symbol for that bar; do not forward-fill OHLCV |
| Incomplete bar (partial data) | Use available fields; if close missing, skip bar |
| Halted / sparse asset | Exclude from portfolio valuation for that bar; do not generate orders |
| Stale data (no update for N bars) | Flag in diagnostics; exclude from order generation after staleness_threshold |

#### 2.2 Intraday Persistence Schema [NEW]

**Tables / objects and their roles:**

| Table | Key Fields | Purpose |
|-------|-----------|---------|
| `intraday_orders` | run_id, date, bar_timestamp, symbol, side, qty, signal_source | Every order generated |
| `intraday_fills` | run_id, date, bar_timestamp, symbol, side, qty, price, slippage, commission | Every execution |
| `intraday_positions` | run_id, date, bar_timestamp, symbol, qty, avg_cost | Position snapshot per bar |
| `intraday_equity` | run_id, date, bar_timestamp, equity, cash, portfolio_value | Equity snapshot per bar |
| `bar_checkpoints` | run_id, date, last_processed_bar, state_json | Resumption checkpoint |

**Recovery and idempotency:**
- `run_id`: UUID generated at session start; all records tagged
- `bar_checkpoints`: after each bar, write last_processed_bar timestamp + serialized state
- On restart: load latest checkpoint for current run_id; resume from next bar
- Idempotency: before processing a bar, check if fills already exist for (run_id, bar_timestamp); skip if yes
- No re-execution of already-processed bars

#### 2.3 Other Phase 2 Tasks

1. Refactor IntradayBacktestEngine for real multi-asset portfolio valuation
2. Make run_paper.py --mode live execute trades via run_day_daily (or intraday equivalent), not just print
3. Unify intraday backtest / replay / live to share the same bar processing loop
4. Handle edge cases listed in data contract

#### Phase 2 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| Multi-asset portfolio valuation | Intraday backtest runs on ≥5 symbols simultaneously with correct portfolio NAV |
| Bar-level persistence | All 5 persistence tables populated during intraday run |
| Restart recovery | Kill process mid-run → restart → resumes from last checkpoint, no duplicate fills |
| Incomplete data handling | Engine skips missing bars without crash; diagnostics flag stale assets |
| Idempotent re-run | Re-running same session produces identical results (no duplicate entries) |
| Live paper mode | `--mode live` writes fills + positions to DB (not just prints weights) |

---

### Phase 3: Factor Research Loop + ML [REVISED]

**Goal:** Close the factor research loop, add real ML, and establish LLM-assisted exploration with strict guardrails.

#### 3.1 Real XGBoost + SHAP

1. Install libomp/xgboost properly (conda install -c conda-forge xgboost libomp)
2. Replace sklearn GradientBoosting in run_xgb_importance.py with real XGBoost
3. Use time-series-safe split (temporal, not random): train on [0, T), validate on [T, T+V)
4. Add SHAP or permutation importance for factor attribution
5. Output reproducible config (hyperparameters, split dates, random seed) alongside results
6. Save model artifacts (feature importance, SHAP values) to `data/ml/` for downstream use

#### 3.2 Expanded Factor Families

Priority additions:
- Overnight / intraday return split factors
- Benchmark-relative factors (vs SPY and vs sector ETF)
- Regime-conditioned factors (factor value × regime indicator)
- Multi-horizon factors (combine 5d/21d/63d signals)
- Breadth / dispersion factors (cross-sectional vol, advance-decline ratio proxy)
- Execution-aware factors (penalize high-spread / low-volume symbols)

Each new factor must:
- Be registered in factor_generator.py with a unique name
- Pass NaN / constant / zero-variance safety checks
- Have IC screening results before entering mining

#### 3.3 LLM-Assisted Factor Exploration Policy [NEW]

**Role boundaries:**

LLM may serve as:
- Candidate factor generator (propose new factor ideas)
- Hypothesis expander (suggest variations of existing factors)
- Factor combiner (propose interaction / composite factors)
- Factor interpreter (explain what a factor captures economically)
- Failure mode analyzer (predict when/why a factor might fail)
- Reverse reviewer (challenge whether a factor is genuinely new)

LLM must NOT serve as:
- Final judge of factor validity (only quantitative evidence decides)
- Final decision-maker on whether to deploy a factor

**Structured candidate record:**

Every LLM-generated factor candidate must be recorded with:

```yaml
factor_name: "overnight_gap_momentum_21d"
hypothesis: "Stocks with consistently positive overnight gaps have institutional accumulation"
formula: "(open[t] / close[t-1] - 1).rolling(21).mean()"
required_fields: [open, close]
suitable_horizon: [5, 10, 21]
suitable_universe: "liquid US equities"
suitable_regime: [BULL, RISK_ON, NEUTRAL]
expected_edge: "IC ~0.03-0.05, captures informed pre-market flow"
expected_risk: "Sensitive to corporate actions, earnings dates"
possible_failure_modes:
  - "Pre-market gaps dominated by noise in low-vol regimes"
  - "Decays quickly if widely adopted"
novelty_vs_existing: "Differs from mom_21d because isolates overnight component"
```

**Mandatory research funnel for LLM candidates:**

```
LLM generates candidate
  → Dedup: check correlation with existing factors (>0.8 = reject)
  → Leakage check: verify no future data in formula
  → Data availability: confirm required fields exist in OHLCV
  → IC screen: compute rank IC on full history
  → OOS validation: walk-forward IC stability
  → Regime robustness: IC in each of 6 regimes
  → Keep / Reject / Archive (with reason)
```

**Mandatory reverse review (anti-overfitting checks):**

Before any LLM candidate enters Keep pool, verify:
- [ ] Not a renamed version of an existing factor
- [ ] Correlation < 0.7 with all existing Keep factors
- [ ] Positive IC in ≥3 out of 6 regimes
- [ ] Not concentrated in a single time period (>60% of IC from one quartile)
- [ ] Survives 2x cost stress test
- [ ] Not overfitting to < 5 symbols
- [ ] Not exploiting timing bias / selection bias / survivorship bias

#### 3.4 Factor → Mining Integration

- Option A: Wire factor_generator.py output into MultiFactorStrategy (replace internal computation)
- Option B: Document that MFS internal computation is architecturally intentional (self-contained strategy)
- Decision must be made and documented. Current state (both exist independently) is not acceptable long-term.

#### Phase 3 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| Real XGBoost | `import xgboost` succeeds; model trains and produces feature_importances_ |
| Time-safe split | Train/test split is temporal (no future leakage); split date recorded in output |
| Reproducible config | Hyperparameters + split + seed saved alongside results in data/ml/ |
| SHAP or permutation importance | At least one interpretability method produces per-factor attribution |
| New factor families | ≥3 new factor families added to factor_generator.py with IC screening |
| Factor candidate schema | ≥1 candidate fully recorded in structured format (all fields filled) |
| Full funnel walkthrough | ≥1 candidate completes: candidate → IC screen → OOS → regime check → keep/reject with logged reason |
| NaN/constant handling | factor_generator gracefully handles all-NaN, constant, zero-variance columns |
| Leakage test | Automated check that no factor uses shift(0) or future data |

---

### Phase 4: Performance, Scalability & Architecture Prep [REVISED]

**Goal:** Remove bottlenecks, prepare for serious research scale and future vendor/broker integration.

#### 4.1 Data Provider and Broker Adapter Separation [NEW]

**Principle:** Research data sources and broker execution layer MUST be decoupled. Strategy logic must NEVER import broker-specific APIs. Research logic must NOT depend on vendor-specific field naming.

**DataProvider minimum interface:**

```python
class DataProvider(ABC):
    def fetch_daily(self, symbols, start, end) -> Dict[str, OHLCVFrame]: ...
    def fetch_intraday(self, symbols, freq, start, end) -> Dict[str, OHLCVFrame]: ...
    def get_metadata(self, symbol) -> SymbolMetadata: ...          # exchange, sector, first_trade_date
    def get_calendar(self, start, end) -> TradingCalendar: ...     # trading days, half days
    def get_corporate_actions(self, symbol, start, end) -> List: ... # splits, dividends (optional)
    def healthcheck(self) -> bool: ...                              # vendor API reachable
    def fetch_incremental(self, symbol, freq, last_date) -> OHLCVFrame: ...  # delta only
```

**BrokerAdapter minimum interface (future, not implemented this phase):**

```python
class BrokerAdapter(ABC):
    def submit_order(self, order: Order) -> OrderAck: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_positions(self) -> Dict[str, float]: ...
    def get_cash(self) -> float: ...
    def get_open_orders(self) -> List[Order]: ...
    def get_fills(self, since: datetime) -> List[Fill]: ...
    def reconcile(self, expected: Dict, actual: Dict) -> ReconcileResult: ...
```

**Evolution principles:**
- Swap research data source first (e.g., yfinance → Polygon/Tiingo), then broker later
- When adding IBKR: use it as broker/execution adapter, NOT as primary research data warehouse
- DataProvider implementations should normalize to a common schema regardless of vendor
- Current YFinanceProvider already implements DataProvider ABC — future vendors follow same interface

#### 4.2 Other Phase 4 Tasks

1. Incremental intraday data updates (fetch only since last_date, not full 700-day window)
2. Mining parallelization (lock archive DB writes, isolate Optuna studies per worker)
3. Cache expensive computations: regime series, aligned price matrices, factor outputs
4. Review DataProvider abstraction (yfinance_provider.py) for completeness vs interface above

#### Phase 4 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| Incremental intraday fetch | Re-run intraday fetch → only downloads missing dates, not full window |
| Parallel mining safety | 2 concurrent mining processes → no DB corruption, no duplicate trials |
| Computation caching | Second backtest run on same data completes ≥30% faster |
| DataProvider interface | Abstract base class defined; YFinanceProvider verified against it |
| No correctness regression | All 674+ tests pass after performance changes |

---

## Autonomous Decision Authority (inherited from Phase B)

Authorized WITHOUT confirmation:
- Code changes, module splits, local refactors for optimization goals
- New factor/strategy candidates, experiments, analysis scripts
- Config enhancements, threshold tuning
- Test additions, tech debt cleanup
- Diagnostics/report/validation pipeline improvements
- Strategy/factor demotion, suspension, re-scoring
- LLM-generated factor candidates (subject to mandatory funnel)

MUST PAUSE for confirmation:
- Changing core constraints (long-only, no-margin, benchmark logic, etc.)
- Changing research boundaries (adding 15m to main system, new data sources, etc.)
- Changing evaluation criteria definitions
- Repo-level restructuring with direction forks
- Promoting LLM-generated factor to production without full funnel completion

---

## Work Method

Each iteration:
1. 本轮目标
2. 做了什么 + 修改了哪些文件
3. 跑了哪些测试 + 当前结果
4. 剩余风险
5. 下一步

Maintain TODO checklist. Update CLAUDE.md when work is actually completed (not when planned). Prefer small verifiable patches over large rewrites.

---

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

---

## Revision Summary (Phase C PRD v2)

### What was strengthened:

1. **[NEW] strict_match formal mechanism** — Config schema, behavioral rules, reconciliation products (fills/positions/cash/equity match tables), automated test spec, measurable acceptance criteria. Replaces vague "concept documentation."

2. **[NEW] LLM-Assisted Factor Exploration Policy** — Role boundaries (what LLM can/cannot decide), structured candidate record schema (11 fields), mandatory research funnel, mandatory reverse review checklist (7 anti-overfitting checks). Ensures LLM is a hypothesis generator, never a truth oracle.

3. **[NEW] Intraday Data Contract and Persistence Model** — Canonical data representation (Dict[str, DataFrame]), bar minimum fields, timezone rules (tz-naive ET), missing/anomalous bar handling table, 5-table persistence schema, recovery/idempotency design (run_id, bar_checkpoints).

4. **[REVISED] Current System State with evidence levels** — Every feature tagged as `code_verified`, `test_verified`, `manual_verified`, or `claimed_not_verified`. Priority now based on evidence strength, not changelog claims.

5. **[NEW] Data Provider and Broker Adapter Separation** — DataProvider minimum interface (7 methods), BrokerAdapter minimum interface (7 methods), evolution principles (data first, broker second), vendor-neutral schema requirement.

6. **[REVISED] Phase 1/2/3/4 acceptance criteria** — Phase 1: fill match, position match, cash match, daily equity match, first mismatch reporting. Phase 2: multi-asset NAV, bar-level persistence, restart recovery, idempotent re-run. Phase 3: time-safe split, reproducible config, full funnel walkthrough for ≥1 candidate. Phase 4: incremental fetch, parallel safety, caching speedup.

### What still needs code audit to confirm:
- Whether current BacktestEngine execution is truly deterministic (no hidden randomness)
- Whether IntradayBacktestEngine can be extended for multi-asset or needs rewrite
- Whether yfinance_provider.py already implements the full DataProvider interface
- Exact OpenMP/libomp installation path for real XGBoost on macOS
