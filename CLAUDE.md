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

**Architecture:** config/ → core/ → scripts/ → tests/ with 745 passing tests, 80+ commits.
**Phase C progress:** 19 iterations + intraday sprint (4 tasks). Intraday pipeline now functional.

Evidence levels:
- `code_verified`: feature exists in code and logic is correct upon inspection
- `test_verified`: covered by automated unit/integration tests
- `manual_verified`: verified by manual run but no automated test
- `claimed_not_verified`: stated in docs but not independently confirmed

#### Confirmed Done

| Feature | Evidence | Verification Source |
|---------|----------|-------------------|
| Daily data 2007-2026 (37 symbols) + 60m intraday (32 symbols) | `code_verified` | data/daily/*.parquet, data/intraday/60m/*.parquet |
| Real T+1 open price execution | `code_verified` | backtest_engine.py:119,151; run_backtest.py:load_open_prices |
| Paper-backtest shared rebalance logic | `code_verified` | paper_trading_engine.py:run_day_daily → BacktestEngine._generate_orders |
| Kill switch 3-tier with auto-recovery | `test_verified` | kill_switch.py; test_kill_switch.py |
| Cost accounting: separate slippage + commission | `test_verified` | test_cost_model.py, test_execution_simulator.py |
| Integer share mode | `code_verified` | backtest_engine.py:integer_shares, _generate_orders floor() |
| Walk-forward OOS (regime-aware) | `test_verified` | test_window_analyzer.py |
| Expanding window validation | `code_verified` | window_analyzer.py:expanding_window() |
| Forward-block holdout (last 252d) | `code_verified` | evaluator.py data isolation |
| Data isolation (first 70% quick filter) | `code_verified` | evaluator.py:quick_end_idx |
| 4 stress period tests | `code_verified` | evaluator.py:_check_stress_periods, config/backtest.yaml |
| Subperiod robustness | `code_verified` | evaluator.py:_check_subperiod_robustness |
| Cost sensitivity (2x gate) | `code_verified` | evaluator.py:_check_cost_robustness |
| Parameter sensitivity (±20%) | `code_verified` | evaluator.py:_check_param_robustness |
| Regime robustness (6 regimes) | `code_verified` | evaluator.py:_check_regime_robustness |
| OOS/IS Sharpe overfit gate | `code_verified` | evaluator.py:_assign_tier |
| 5-stage mining pipeline | `code_verified` | evaluator.py:evaluate() stages 1-5 |
| 30 candidate factors | `test_verified` | factor_generator.py + test_factor_generator.py |
| Feature importance (sklearn GB) | `code_verified` | run_xgb_importance.py (NOT xgboost) |
| MultiFactorStrategy | `code_verified` | multi_factor.py — **0 unit tests** |
| Left-side trading module | `test_verified` | left_side.py + test_left_side.py |
| Master report (regime vs SPY+QQQ) | `code_verified` | master_report.py, master_report_builder.py |
| Universe rebalance (PIT) | `code_verified` | run_universe_rebalance.py |
| Diagnostics suite (4 detectors) | `test_verified` | diagnostics/detectors.py + test_detectors.py (19 tests) |
| target_vol=0.25 | `code_verified` | constructor.py:_DEFAULT_TARGET_VOL |

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
| True intraday live (盘中实时) | Medium | Needs real-time data feed; currently daily-level live |
| SHAP attribution | Low | Permutation importance (C-11) is functional alternative |
| QQQ check in mining evaluator | Low | Validated in tests (C-7), not auto-checked per-trial |
| Parallel mining | Low | Single-threaded works; parallelism needs DB lock design |
| Computation caching | Low | Regime/factor outputs recalculated each run |

---

### Current Best Strategy (real open prices, target_vol=0.25)
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

**Goal:** Ensure backtest, replay, and paper trading are provably consistent via a formal `strict_match` mechanism. Validate QQQ outperformance under new hard constraint.

#### 1.1 strict_match Formal Mechanism [REVISED]

**Config location:** `config/backtest.yaml` → `consistency` section

```yaml
consistency:
  strict_match:
    enabled: false                    # toggle for CI / regression
    zero_cost: true                   # disable slippage + commission
    deterministic_execution: true     # no randomness in fill logic
    force_shared_path: true           # paper must call BacktestEngine._generate_orders
    share_mode: integer               # integer | fractional — BOTH sides must use same mode
    tolerance_equity_bps: 10          # max daily equity divergence (bps)
    tolerance_position_shares: 0      # exact share match required
    tolerance_cash_usd: 0.01          # rounding tolerance
```

**Key change:** `share_mode` replaces hardcoded `integer_shares: true`. The requirement is that **both backtest and paper use the same share_mode**, not that integer is always used. [REVISED]

**Behavior in strict_match mode:**
- Cost model returns zero slippage and zero commission
- No stochastic components in execution
- Both backtest and paper MUST use the identical code path for order generation
- Same share_mode enforced on both sides
- Same signal → same price → same fills → same positions → same cash → same equity

**Reconciliation products:**

| Product | Format | Contents |
|---------|--------|----------|
| fills_reconciliation | DataFrame | date × symbol × side × qty × price — matched pair, mismatch flag |
| positions_reconciliation | DataFrame | date × symbol × backtest_qty × paper_qty × diff |
| cash_reconciliation | Series | date × backtest_cash × paper_cash × diff_usd |
| equity_reconciliation | Series | date × backtest_equity × paper_equity × diff_bps |
| mismatch_summary | Dict | first_mismatch_date, n_mismatches, max_divergence_bps, pass/fail |

**Automated test:** `tests/integration/test_strict_match_consistency.py`

#### 1.2 Other Phase 1 Tasks

1. Add MultiFactorStrategy unit tests (≥10): factor computation, signal generation, regime scaling, min_holding_days, edge cases
2. Verify stressed cost produces directionally correct degradation (see acceptance criteria)
3. Wire left_side_trading config from risk.yaml into LeftSideTrading class
4. Add open price regression test
5. **Validate current best strategy against QQQ hard constraint (full period + holdout)**

### 1.3 Known Critical Bugs to Fix First [NEW]

*To avoid wasted iterations, Claude must fix these identified bugs before running consistency tests:*

1. **Replay Open Price Bug**
   `scripts/run_paper.py:run_replay()` currently builds `open_prices` from a daily price matrix that only loads `close`, so T+1 `close` is being passed as T+1 `open`. This breaks backtest-paper consistency. It must explicitly load and pass true T+1 `open` prices.

2. **Cost Robustness Bug**
   `core/mining/evaluator.py:_check_cost_robustness()` attempts to initialize `CostModel` with `stress_multiplier`, but `CostModel` currently accepts only a `CostModelConfig`. This likely causes a silent fallback to the base cost model, invalidating the intended 2x cost stress test.

3. **Execution Cost Accounting Inconsistency (likely commission double counting)**
   `ExecutionSimulator.simulate_fill()` uses `cost_bps()` to shift execution price, while `cost_bps()` currently represents total cost (`commission + slippage`). It then also applies `commission_usd` separately to cash. This likely double-counts commission and should be fixed by enforcing a clear accounting split:

   * **slippage** → execution price
   * **commission** → cash accounting

#### Required Fix Validation

Before proceeding with broader consistency or mining work, Claude must:

* patch all three issues
* add or update automated tests covering each bug
* verify that:

  * replay uses true T+1 open prices
  * 2x cost stress actually changes results versus 1x
  * execution accounting no longer mixes total-cost-in-price with separate commission-in-cash
* summarize the fix, the files changed, and the regression tests added


#### Phase 1 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| strict_match fills | Exact match: same count, same symbols, same quantities, same prices |
| strict_match positions | EOD positions identical for every date in test window |
| strict_match cash | Daily cash divergence < $0.01 |
| strict_match equity | Daily equity divergence < 10 bps |
| First mismatch reporting | On failure: output date, symbol, expected vs actual |
| MultiFactorStrategy tests | ≥10 unit tests covering core logic paths |
| Stressed cost test | 2x cost produces lower CAGR than 1x cost; total trading cost under 2x is higher than under 1x; difference exceeds configured minimum threshold [REVISED] |
| Left-side config wiring | cfg.risk.left_side_trading values flow to LeftSideTrading constructor |
| QQQ full-period | Best strategy CAGR > QQQ CAGR over full backtest period [NEW] |
| QQQ holdout | Best strategy return > QQQ return over holdout period [NEW] |

---

### Phase 2: Intraday Pipeline [REVISED]

**Goal:** Make intraday backtest + paper trading actually executable, multi-asset, persistent, and recoverable.

#### 2.1 Intraday Data Contract [REVISED]

**Canonical representation:**
```
Dict[str, pd.DataFrame]  # symbol → OHLCV DataFrame
```

**Bar data minimum fields:**

| Field | Type | Required |
|-------|------|----------|
| open | float | yes |
| high | float | yes |
| low | float | yes |
| close | float | yes |
| volume | float | yes |
| timestamp | DatetimeIndex | yes |

**Timezone rules:** [REVISED]
- **Current implementation:** tz-naive, US/Eastern (matching yfinance output after `align_intraday_index`)
- **Target architecture:** future versions should migrate to tz-aware UTC-normalized internal representation with ET conversion at display/execution boundaries
- **Migration constraint:** any tz change must be accompanied by a regression test proving identical backtest results before and after

**Missing and anomalous bar handling:** [REVISED]

| Scenario | Order Generation | Valuation |
|----------|-----------------|-----------|
| Missing bars for a symbol | Skip order generation for that symbol | **Mark at last valid price** (stale-flagged) |
| Incomplete bar (partial data) | Skip if close missing | Use available fields for valuation |
| Halted / sparse asset | Exclude from order generation | **Continue valuation at last valid price** — never remove from NAV |
| Stale data (no update for N bars) | Exclude from order generation after staleness_threshold | Continue valuation at last valid price + diagnostic flag |

#### 2.2 Intraday Persistence Schema

| Table | Key Fields | Purpose |
|-------|-----------|---------|
| `intraday_orders` | run_id, date, bar_timestamp, symbol, side, qty, signal_source | Every order generated |
| `intraday_fills` | run_id, date, bar_timestamp, symbol, side, qty, price, slippage, commission | Every execution |
| `intraday_positions` | run_id, date, bar_timestamp, symbol, qty, avg_cost | Position snapshot per bar |
| `intraday_equity` | run_id, date, bar_timestamp, equity, cash, portfolio_value | Equity snapshot per bar |
| `bar_checkpoints` | run_id, date, last_processed_bar, state_json | Resumption checkpoint |

**Recovery and idempotency:**
- `run_id`: UUID generated at session start
- `bar_checkpoints`: after each bar, write last_processed_bar + serialized state
- On restart: load latest checkpoint; resume from next bar
- Before processing a bar: check if fills exist for (run_id, bar_timestamp); skip if yes

#### Phase 2 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| Multi-asset portfolio valuation | Intraday backtest runs on ≥5 symbols with correct portfolio NAV (sum of position values + cash) |
| Bar-level persistence | All 5 persistence tables populated during intraday run |
| Restart recovery | Kill process mid-run → restart → resumes from checkpoint, no duplicate fills |
| Incomplete data handling | Engine skips missing bars without crash; stale assets remain in NAV at last valid price |
| Idempotent re-run | Re-running same session produces identical results |
| Live paper mode | `--mode live` writes fills + positions to DB |

---

### Phase 3: Factor Research Loop + ML [REVISED]

**Goal:** Close the factor research loop, add real ML, establish LLM-assisted exploration with strict guardrails.

#### 3.1 Factor Timing and Leakage Rules [REVISED]

Every factor / signal must have explicit timing semantics:

| Attribute | Definition |
|-----------|-----------|
| signal_timestamp | The "as-of" time when the signal is considered generated |
| data_availability_timestamp | The latest real-world time at which all input data would have been available |
| execution_timestamp | When orders based on this signal would be executed |

**Leakage rules:**
- A factor must NOT use any data with `data_availability_timestamp > signal_timestamp`
- A factor must NOT use any field that would not have been observable at `signal_timestamp`
- Specifically prohibited: using T-day close to generate T-day signal that executes at T-day close (same-bar execution)
- Specifically required: signal generated from data available at T-day close → execution at T+1 open (minimum 1-bar lag)
- Leakage checks are based on **temporal availability semantics**, not simplistic `shift()` counting

**Automated leakage validation:**
- For each factor in factor_generator.py, verify the computation chain includes at least `shift(1)` or equivalent lag
- Check that no factor accesses `price_df` at index `t` for a signal dated `t` without shifting
- Flag factors that use aligned/merged data without explicit lag documentation

#### 3.2 Real XGBoost + SHAP

1. Install xgboost + libomp (conda install -c conda-forge xgboost libomp)
2. Replace sklearn GradientBoosting with XGBRegressor
3. Time-series-safe split: train [0, T), test [T, T+V) — temporal, never random
4. SHAP or permutation importance for factor attribution
5. Reproducible config saved alongside results (hyperparameters, split dates, seed)
6. Artifacts saved to `data/ml/`

#### 3.3 Expanded Factor Families

Priority additions:
- Overnight / intraday return split factors
- Benchmark-relative factors (vs SPY and vs sector ETF)
- Regime-conditioned factors (factor value × regime indicator)
- Multi-horizon factors (combine 5d/21d/63d signals)
- Breadth / dispersion factors (cross-sectional vol, advance-decline proxy)
- Execution-aware factors (penalize high-spread / low-volume symbols)

Each new factor must: be registered with unique name, pass NaN/constant/zero-variance checks, have IC screening before entering mining.

#### 3.4 LLM-Assisted Factor Exploration Policy

**Role boundaries:**

LLM may serve as:
- Candidate factor generator
- Hypothesis expander
- Factor combiner
- Factor interpreter
- Failure mode analyzer
- Reverse reviewer

LLM must NOT serve as:
- Final judge of factor validity
- Final decision-maker on deployment

**Structured candidate record:**

```yaml
factor_name: ""
hypothesis: ""
formula: ""              # pseudocode or pandas expression
required_fields: []
suitable_horizon: []
suitable_universe: ""
suitable_regime: []
expected_edge: ""
expected_risk: ""
possible_failure_modes: []
novelty_vs_existing: ""
```

**Mandatory research funnel:**

```
LLM generates candidate
  → Dedup: check correlation with existing factors
  → Leakage check: verify temporal availability (see 3.1)
  → Data availability: confirm required fields exist
  → IC screen: compute rank IC on full history
  → OOS validation: walk-forward IC stability
  → Regime robustness: IC in each of 6 regimes
  → Keep / Reject / Archive (with logged reason)
```

**Correlation review rule:** [REVISED]
- Correlation > 0.7 with any existing Keep factor triggers **mandatory review**, not automatic rejection
- Candidate must demonstrate incremental value: better regime robustness, lower turnover, better cost-adjusted alpha, or more stable OOS performance
- If no incremental value can be demonstrated, reject with documented reason

**Mandatory reverse review:**
- [ ] Not a renamed version of an existing factor
- [ ] If correlation > 0.7 with existing factor, incremental value documented
- [ ] Positive IC in ≥3 out of 6 regimes
- [ ] Not concentrated in a single time period (>60% of IC from one quartile)
- [ ] Survives 2x cost stress test
- [ ] Not overfitting to < 5 symbols
- [ ] Not exploiting timing bias / selection bias / survivorship bias

#### 3.5 Factor → Mining Integration

Decision required:
- **Option A:** Wire factor_generator output into MFS (replace internal computation)
- **Option B:** Document that MFS internal computation is intentional (self-contained strategy)
- Current state (both exist independently) is not acceptable. Must choose and document.

#### Phase 3 Acceptance Criteria [REVISED]

| Criterion | Measurable Standard |
|-----------|-------------------|
| Real XGBoost | `import xgboost` succeeds; model trains and produces feature_importances_ |
| Time-safe split | Train/test split is temporal; split date recorded in output |
| Reproducible config | Hyperparameters + split + seed saved in data/ml/ |
| SHAP or permutation | At least one interpretability method produces per-factor attribution |
| New factor families | ≥3 new families added to factor_generator.py with IC screening |
| Factor candidate schema | ≥1 candidate fully recorded in structured format |
| Full funnel walkthrough | ≥1 candidate completes: candidate → IC → OOS → regime → keep/reject with logged reason |
| NaN/constant handling | factor_generator handles all-NaN, constant, zero-variance gracefully |
| Leakage validation | Automated check verifies temporal lag in factor computation chain |

---

### Phase 4: Performance, Scalability & Architecture Prep [REVISED]

**Goal:** Remove bottlenecks, prepare for serious research scale and future vendor/broker integration.

#### 4.1 Data Provider and Broker Adapter Separation

**Principle:** Research data sources and broker execution MUST be decoupled. Strategy logic must NEVER import broker APIs. Research logic must NOT depend on vendor-specific field naming.

**DataProvider minimum interface:**

```python
class DataProvider(ABC):
    def fetch_daily(self, symbols, start, end) -> Dict[str, OHLCVFrame]: ...
    def fetch_intraday(self, symbols, freq, start, end) -> Dict[str, OHLCVFrame]: ...
    def get_metadata(self, symbol) -> SymbolMetadata: ...
    def get_calendar(self, start, end) -> TradingCalendar: ...
    def get_corporate_actions(self, symbol, start, end) -> List: ...  # optional
    def healthcheck(self) -> bool: ...
    def fetch_incremental(self, symbol, freq, last_date) -> OHLCVFrame: ...
```

**BrokerAdapter minimum interface (future):**

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
- Swap research data source first, broker second
- IBKR = broker/execution adapter, NOT primary research data warehouse
- DataProvider swap must pass price semantics regression test (see Pricing and Valuation Semantics)
- Current YFinanceProvider already implements DataProvider ABC

#### 4.2 Other Phase 4 Tasks

1. Incremental intraday data updates
2. Mining parallelization (lock archive DB writes)
3. Cache expensive computations
4. DataProvider interface completeness review

#### Phase 4 Acceptance Criteria

| Criterion | Measurable Standard |
|-----------|-------------------|
| Incremental intraday fetch | Re-run downloads only missing dates |
| Parallel mining safety | 2 concurrent processes → no DB corruption |
| Computation caching | Second run ≥30% faster |
| DataProvider interface | ABC defined; YFinanceProvider verified against it |
| No correctness regression | All 674+ tests pass |

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
- Intraday report: `core/reporting/intraday_report.py`
- Tests: `tests/unit/` + `tests/integration/` (745 passing)

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
```

## Iteration Log
See `reports/loop_changelog.md` for Phase B history (50 iterations).

## IMPORTANT: Git Safety
NEVER use `git add -A` or `git add .` — always add specific files.

---

## Revision Summary (v2 → v3)

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
- Python: `/opt/miniconda3/envs/kcots/bin/python`
- Tests: 745 passing
- Key data: daily (37 symbols, 2007-2026), 60m (32 symbols), 30m/15m (32 symbols, 60d)

### Current TODO Checklist
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
