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
| Feature importance (XGBoost 3.2.0) | `code_verified` | run_xgb_importance.py (real XGBoost + permutation) |
| MultiFactorStrategy | `test_verified` | multi_factor.py + test_multi_factor.py (16 tests) |
| Left-side trading module | `test_verified` | left_side.py + test_left_side.py |
| Master report (regime vs SPY+QQQ) | `code_verified` | master_report.py, master_report_builder.py |
| Universe rebalance (PIT) | `code_verified` | run_universe_rebalance.py |
| Diagnostics suite (4 detectors) | `test_verified` | diagnostics/detectors.py + test_detectors.py (19 tests) |
| target_vol=0.25 | `test_verified` | constructor.py:_DEFAULT_TARGET_VOL + test_constructor.py |

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
- Data: `core/data/` (yfinance_provider, market_data_store, validator, calendar, bar_store)
- Scripts: `scripts/` (run_all.sh, fetch_data.py, run_backtest.py, run_mining.py, run_paper.py, generate_report.py, run_factor_screen.py, run_xgb_importance.py, run_universe_rebalance.py, build_bars_parquet.py, build_splits_parquet.py, aggregate_bars.py, build_catalog.py, validate_vs_yfinance.py)
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

## Ralph-Loop Findings (2026-04-20+)

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
- 按用户在 Round 8 追加的指令，loop 结束后进入 **PRD §13.0 的 30 轮 LLM-assisted + XGBoost mining 阶段**（`docs/prd_llm_factor_mining.md`）
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
  - `FactorCandidate` dataclass 匹配 `docs/prd_llm_factor_mining.md` §4 YAML schema
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

**下阶段就绪**: `docs/prd_llm_factor_mining.md` auto-launch 阶段的底座已经在位。LLM 生成的 YAML 候选可以通过 CLI 直接进入 funnel，不需要新代码

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
- Python: `/home/zibo/miniconda3/envs/pqs/bin/python`
- Tests: 745 passing
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
python scripts/disk_guard.py                              # C: drive guard
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
