# K1 Deferred-Execution `BacktestEngine` Extension — Design Audit

**Date**: 2026-05-13 (post-roadmap v2 lock, commit `7b12d85`)
**Status**: K1.1 design — to be validated by test surface (K1.2) and implementation (K1.3)
**Authors**: operator (zibomeng@) + Claude Code assist
**PRD reference**: `docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md` §4.1
**Authorization**: Roadmap v2 §10 user explicit-go 2026-05-13
**Discipline**: TDD-grade strict per Q6 audit conclusion (load-bearing: 5 downstream consumers)

---

## §1 Goal

Extend `core/backtest/backtest_engine.py::BacktestEngine` so it can drive a backtest in **two execution modes**:

| Mode | Trigger | Engine consumes | Status |
|---|---|---|---|
| `calendar` (default) | Fixed cadence (cycle04-10) | `signals_df` = (date × symbol) target-weight matrix | ✅ EXISTING (unchanged, bit-for-bit preserved) |
| `signal_driven` (new) | Entry / exit predicates fire | `entry_signals` + `exit_signals` + `position_sizing_rule` | ❌ NEW (K1 ship target) |

**Backward-compat is non-negotiable**: with `--execution-mode calendar` (or no flag), cycle04-10 archived backtests must produce **bit-identical NAV** to current `main`. This is enforced by K1.4 regression.

---

## §2 API diff

### 2.1 Current signature (calendar mode, unchanged)

```python
BacktestEngine.run(
    signals_df:       pd.DataFrame,   # (date × symbol) target weights
    price_df:         pd.DataFrame,
    open_df:          Optional[pd.DataFrame] = None,
    vix_series:       Optional[pd.Series] = None,
    regime_series:    Optional[pd.Series] = None,
    benchmark_series: Optional[pd.Series] = None,
) -> BacktestResult
```

### 2.2 New signal-driven path (K1 addition)

```python
BacktestEngine.run(
    # Existing calendar-mode args (unchanged signature) — only price_df is hard-required in this mode
    price_df:         pd.DataFrame,
    signals_df:       Optional[pd.DataFrame] = None,   # required if execution_mode == "calendar"
    open_df:          Optional[pd.DataFrame] = None,
    vix_series:       Optional[pd.Series] = None,
    regime_series:    Optional[pd.Series] = None,
    benchmark_series: Optional[pd.Series] = None,
    # NEW (signal_driven mode)
    execution_mode:   str = "calendar",                # "calendar" | "signal_driven"
    entry_signals:    Optional[pd.DataFrame] = None,   # (date × symbol) bool — True = arm signal at T
    exit_signals:     Optional[pd.DataFrame] = None,   # (date × symbol) bool — True = close position at T+1 open
    confirmation_predicate: Optional[Callable] = None, # f(state, t, sym) -> bool; None = no confirmation gate (immediate arm→fill T+1)
    position_sizing_rule:   Optional[Callable] = None, # f(state, t, sym, target_n) -> weight; None = equal-weight top_n
    ttl_bars:         int = 0,                          # 0 = same-bar AND-gate (§3.1); 1-21 = TTL window (§3.2)
    top_n:            int = 10,                         # active position count target (cap_aware preserved)
) -> BacktestResult
```

**Dispatch logic in `run()`**:
```python
if execution_mode == "calendar":
    # EXISTING code path — bit-for-bit unchanged
    return self._run_calendar(signals_df, price_df, ...)
elif execution_mode == "signal_driven":
    # NEW code path
    return self._run_signal_driven(entry_signals, exit_signals, price_df, ...)
else:
    raise ValueError(f"execution_mode must be 'calendar' or 'signal_driven', got {execution_mode!r}")
```

### 2.3 Why this signature shape

- **Single `run()` entry point** preserves caller ergonomics (mining harness, paper runner, forward observe all call `engine.run(...)`)
- **Default `execution_mode="calendar"`** = backward-compat guarantee
- **`exit_signals` separate from `entry_signals`** (not just one signal predicate) because exits need different semantics: an exit must close an EXISTING position, not arm new ones. Combining them creates ambiguity for the "no position open, exit signal fires" case (which is a no-op)
- **`confirmation_predicate` as injected callable** rather than DataFrame so it can read state (`armed_signals`, `position_age`) at evaluation time — this is the §3.2 retest-after-breakout pattern
- **`ttl_bars=0` collapses to `confirmation_predicate=None`** (same-bar AND-gate §3.1); `ttl_bars>0` enables state-machine TTL countdown

---

## §3 State machine spec

### 3.1 New state objects (carried across bars)

```python
# Per-symbol state at each bar
@dataclass
class SignalSlot:
    armed_at: pd.Timestamp           # arm date (when entry_signal fired)
    armed_price: float               # close price at arm date (for diagnostics)
    age_bars: int                    # bars elapsed since arm
    status: Literal["armed", "confirmed", "expired"]

# Per-symbol state for live positions
@dataclass
class PositionSlot:
    opened_at: pd.Timestamp          # fill date (T+1 of confirmation date)
    opened_price: float              # fill price (open of T+1)
    shares: int                      # filled shares
    age_bars: int                    # bars since fill (for min_holding_days enforcement)
```

### 3.2 State transition diagram

```
                              entry_signal fires at T
                                     │
                                     ▼
                              ARMED (age=0)
                            ┌────────┼──────────┐
                            │        │          │
                  confirmation_predicate(state, t, sym):
                       True  │      None         False (or no fire)
                            ▼                    ▼
                       CONFIRMED              age++
                       (fill T+1 open)        │
                                              ▼
                                       age == ttl_bars?
                                       ┌───┴───┐
                                     yes       no
                                      │        │
                                      ▼        ▼
                                  EXPIRED   wait next bar
                                  (purge)
```

For `ttl_bars=0` (§3.1 same-bar AND-gate): confirmation_predicate evaluated at T itself; if True, fill at T+1 open; if False, immediate expire (no carry).

For `ttl_bars>0` (§3.2 TTL window): confirmation_predicate evaluated at each bar T+1, T+2, ..., T+ttl_bars; first True fires fill at NEXT bar's open; if no True by T+ttl_bars, expire.

### 3.3 Exit semantics

`exit_signals[t, sym] == True` AND `PositionSlot` exists for `sym` → close position at T+1 open. Exit overrides any pending arm.

**Critical invariant**: exit signal cannot cause a new entry; armed signal cannot cause exit. They are orthogonal predicates.

### 3.4 Cash carry semantics

Per PRD §4.1: "NAV during armed-not-filled is cash (no SPY hedge in MVP)".
Translation: when a signal is armed but not yet confirmed, the capital that WOULD be deployed if it filled sits in cash and earns 0%. NAV = sum(position_value) + cash. No SPY-anchored cash deployment.

---

## §4 cap_aware + risk preservation

### 4.1 cap_aware selector

At signal-trigger time (when confirmation predicate fires for a sym at T+k):
1. Add sym to candidate active-position set
2. Apply cap_aware selector over current active-positions ∪ {sym}
3. If sym passes cluster_cap + max_single_weight + asset_class caps → fill T+1; else drop (signal expires)

This means the selector still runs but at signal-trigger time (not bar 0), and the selector input is "current portfolio + 1 new candidate" not "full universe".

### 4.2 Risk overlay integration

- `kill_switch` from `core/risk/kill_switch.py` checks at top of each bar BEFORE processing entries. If kill-switch fires, all armed signals expire + no new entries; existing positions held (kill-switch is a NEW-ENTRY gate, not a force-liquidate).
- `stress_test` halt does the same.
- Position size limits per `config/risk.yaml` apply at fill time via `cap_aware` selector.

---

## §5 Cost integration

Slippage + commission apply to deferred fills the same as calendar fills:
- ExecutionSimulator already abstracts the slippage tier via `freq` parameter ("interday" vs "intraday")
- New code path calls `self._sim.execute(...)` at fill time with the exact same signature as the calendar path
- Per-share commission + per-trade min_trade_usd respected

**No change to cost model**. Cost integration test (K1.2 test #18-19) verifies a known signal-driven trade incurs the expected slippage + commission.

---

## §6 Leakage discipline

Per `docs/checkpoints/20260430-self_audit_methodology.md` R3:
- At bar T, only data ≤ T visible
- `entry_signals` is provided pre-computed by the caller (strategy module's responsibility; engine doesn't re-derive)
- `confirmation_predicate(state, t, sym)` receives only `state` snapshot at T (engine guarantees this); predicate cannot peek future
- Fill price = `open_df.loc[T+1, sym]` per existing convention

K1.2 test #20 (leakage test): inject a `confirmation_predicate` that tries to access `state[t+1]` and verify engine raises (defensive — should be impossible by data structure, but explicit test catches API regressions).

---

## §7 Test surface plan (K1.2 = 25-30 tests, TDD-grade)

| # | Category | Test | Type |
|---|---|---|---|
| 1-3 | State machine | ARMED → CONFIRMED transition fires correctly when predicate True | unit |
| 4-6 | State machine | ARMED → EXPIRED transition fires when age == ttl_bars | unit |
| 7 | State machine | armed signal purged after expire | unit |
| 8-10 | TTL semantics | ttl_bars=0 → same-bar AND-gate (§3.1) — confirmation eval at T, no carry | unit |
| 11-13 | TTL semantics | ttl_bars=5 → confirmation can fire at T+1..T+5, first True fills T+(k+1) | unit |
| 14 | Position lifecycle | Position opens on confirmed signal at T+1 open price | unit |
| 15 | Position lifecycle | Position closes on exit_signal at T+1 open | unit |
| 16 | Position lifecycle | Position age increments correctly across bars | unit |
| 17 | Orthogonality | exit_signal for sym with no position = no-op (no negative shares) | unit |
| 18-19 | Cost | Slippage + commission applied to signal-driven fills (same as calendar) | unit |
| 20 | Leakage | Confirmation predicate cannot access future bars (defensive API test) | unit |
| 21-22 | cap_aware | Cluster_cap + max_single_weight enforced at signal-trigger time | unit |
| 23 | Risk overlay | Kill-switch halts new entries, doesn't force-liquidate existing | unit |
| 24-26 | Regression | --execution-mode calendar produces bit-identical NAV to current main for: cycle04 top-1, cycle10 top-1, simple_baseline | integration |
| 27 | Smoke | Signal-driven backtest with `entry=SPY>200SMA, ttl=0, exit=SPY<200SMA` runs end-to-end and produces sensible NAV trajectory | integration |
| 28 | Cash carry | Armed-not-filled period = cash, NAV stays flat (modulo open positions) | integration |
| 29 | Mixed signals | Multiple syms with overlapping arm/exit dates handled correctly | integration |
| 30 | Edge case | Empty entry_signals + empty exit_signals → no-op backtest, NAV = initial_capital | unit |

**Test files**:
- `tests/unit/backtest/test_deferred_execution.py` (tests 1-23, 30)
- `tests/integration/backtest/test_deferred_execution_regression.py` (tests 24-29)

---

## §8 Implementation phasing (K1.3)

Implementation deferred until K1.2 tests are written and all RED (failing). Phasing within K1.3:

1. **K1.3a**: Add `execution_mode` parameter + dispatch logic in `run()` (calendar path unchanged); all calendar tests + regression tests should still pass
2. **K1.3b**: Add SignalSlot + PositionSlot dataclasses + state init
3. **K1.3c**: Implement `_run_signal_driven` main loop — state transitions only (no fills yet); tests 1-7 pass
4. **K1.3d**: Add TTL countdown + confirmation_predicate evaluation; tests 8-13 pass
5. **K1.3e**: Add fill semantics (T+1 open fill, position open/close, exit semantics); tests 14-17 pass
6. **K1.3f**: Add cost integration via ExecutionSimulator; tests 18-19 pass
7. **K1.3g**: Add cap_aware preservation; tests 20-22 pass
8. **K1.3h**: Add risk overlay integration; test 23 passes
9. **K1.3i**: End-to-end smoke; tests 27-29 pass
10. **K1.3j**: Edge cases + leakage test; tests 20, 30 pass

Each sub-step ships incrementally — sub-step's tests must be green before next sub-step begins.

---

## §9 Risks identified

### R1: M11a/M11b parity breaks
- **Risk**: Refactoring `run()` for dispatch breaks parity tests
- **Mitigation**: K1.3a is **pure dispatch** — no logic change in calendar path. M11a/M11b parity tests should pass after K1.3a with zero change.

### R2: Performance regression on calendar mode
- **Risk**: Adding state objects + dispatch overhead slows existing backtests
- **Mitigation**: State objects only allocated when `execution_mode == "signal_driven"`. Calendar path has zero new allocations. Verify via benchmark in K1.4.

### R3: Confirmation predicate API too narrow
- **Risk**: §3.2 retest-after-breakout needs predicate to see indicator values, not just state
- **Mitigation**: Predicate signature `(state, t, sym)` — state is a snapshot that includes indicator panels via closure (strategy module passes them in). If turn out predicate signature insufficient, extend with `**kwargs` (additive, not breaking).

### R4: cap_aware re-entry at signal-trigger
- **Risk**: cap_aware was designed for "select N from universe at bar 0"; now we re-evaluate at every signal-trigger moment, which is a different invocation pattern
- **Mitigation**: cap_aware functions in `core/research/risk_cluster_map.py` are pure (no state); fine to call at arbitrary t. K1.3g verifies via tests 21-22.

### R5: Diversifier role candidates need different position sizing
- **Risk**: Role-aware sizing not in scope for K1
- **Mitigation**: `position_sizing_rule` is injected callable; can pass `role="diversifier"` sizing in T1b without engine change. Punt to T1b.

---

## §10 Out of scope for K1

- §3.3 multi-phase patterns (Wyckoff / divergence) — reuse state machine when MVP validated (PRD §4.6)
- Intraday confirmation (60m / 30m / 15m TTL windows) — daily TTL first
- Live execution integration (paper / broker) — research-only first
- Hedging during armed state (SPY anchor) — phase 2

---

## §11 K1 acceptance — verifiable

K1 ships when ALL of these green:

1. **K1.2 test suite**: 25-30 tests, all PASS
2. **Calendar regression**: cycle04 top-1 + cycle10 top-1 + simple_baseline produce bit-identical NAV to pre-K1 `main`
3. **No performance regression**: calendar-mode benchmark within ±5% of pre-K1 wall-clock
4. **M11a/M11b parity**: existing paper-BT parity test still PASS
5. **End-to-end smoke**: signal_driven backtest with simple SPY > 200SMA entry / SPY < 200SMA exit produces sensible NAV and trade count
6. **Documentation**: CLAUDE.md "Confirmed Done" inventory updated; K1 closeout memo at `docs/memos/20260513-k1_deferred_exec_ship.md`

Estimated wall-clock: 1-2 weeks. K1.2 (tests, 2-3 days) → K1.3 (impl, 4-6 days, 10 sub-steps) → K1.4 (regression, 1 day) → K1.5 (docs, 0.5 day).

---

## §12 Next action

K1.2: write the 25-30 tests. All RED until K1.3 ships. No code in `core/backtest/backtest_engine.py` until K1.2 is green-on-stub.
