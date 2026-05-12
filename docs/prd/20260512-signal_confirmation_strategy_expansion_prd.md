# PRD — Signal-confirmation strategy expansion (setup-then-trigger / TTL-gated entries)

**Authors**: operator (zibomeng@), with Claude Code assist
**Date**: 2026-05-12
**Status**: DRAFT (single-round operator-driven; awaiting user direction
on scope + go/no-go)
**Triggered by**: 2026-05-12 全盘审计 finding — PQS mining + strategy
framework has ZERO signal-confirmation / armed-then-fired / TTL-based
entry patterns; the structural cycle04-08 + Trial 3 sibling-by-NAV
problem may have orthogonal axis here.

---

## §1 Background

Resident-quant audit on 2026-05-12 surveyed the entire PQS codebase
(strategies + factors + mining + intraday) and found:

**Every production strategy is single-bar evaluation**:

| Strategy | Signal pattern |
|---|---|
| dual_momentum | Single bar: 12mo momentum → rank → top-N |
| trend_following | Single bar: price > 200 EMA (+ optional 50 EMA same-bar confirm) |
| cross_asset_rotation | Single bar: absolute momentum + asset-class rank |
| multi_factor (production) | Single bar: 7-factor weighted sum → rank → top-N |

**Mining search space** (`core/mining/strategy_space.py::ALL_SPACES`)
covers only lookback / top_n / rebalance / factor_weights / regime
thresholds — **no TTL, no confirmation_window, no setup_threshold,
no retest_lookback, no pending_signal_age, no signal_state_age**.

**Grep across full codebase** for `pending_signal` / `armed` /
`confirmation_window` / `ttl_bars` / `signal_age` / `expire` /
`retest` / `state_machine` / `pending_position` / `signal_history` =
**0 hits**.

The closest existing primitive is:
- `core/intraday/multi_timescale.py` — implements VETO semantics
  (higher TF can disable / scale lower TF entry), NOT confirmation
  (no "wait N bars for second trigger")
- `core/intraday/sr_swing.py` — detects swing S/R levels, but is
  **research-only and not integrated into production factor set**
- `MultiFactorStrategy.min_holding_days` — turnover throttle, NOT a
  signal TTL gate

## §2 Why this matters (resident-quant view)

Cycles 04-08 + Trial 3 produced 6 candidates that pass Track A
acceptance individually but **all share raw NAV Pearson 0.78-0.89 vs
RCMv1** — sibling-by-NAV at the construction level, not the factor
level. Memo `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`
§"Three structural findings" empirically demonstrates: long-only top-N
over the 78-stock universe with monthly rebalance produces ~30-50%
identical holdings across disjoint-factor candidates. **Banning
specific factors (cycle05) doesn't break the geometry; expanding
factor zoo (cycle04→05 +17 factors) doesn't break it; the
construction itself is binding.**

The cycle07-fleet closeout `docs/memos/20260506-cycle07_to_fleet_final_synthesis.md`
§"Cycle direction options" enumerates ways out:
- (a) Construction DOF expansion (weekly cadence / cross-asset universe /
  multi-horizon ensemble)
- (b) Universe expansion (78 → 200+ stocks OR add bonds/commodities permanently)
- (c) **Strategy-type pivot** (options sleeve in progress; intraday
  reversal / event-calendar untested; **signal-confirmation untested**)
- (d) Gate revision (relax 78-stock universe OR long-only invariant)

This PRD scopes option (c) sub-item "signal-confirmation untested."
Architecturally it changes the entry-timing causal chain from "today
rank top → today buy" to "today setup → if confirm appears within
TTL window → buy" which has structural NAV-distinct potential — it
introduces TIME as a first-class signal-state dimension, not just a
ranking dimension.

## §3 Patterns to bring into mining search

Survey of well-established quant patterns that PQS currently does
NOT have, ordered by minimum-viable-implementation cost:

### 3.1 Same-day OHLC confirmation (lowest cost)

**Volume-confirmation gate**:
> Primary signal: composite cross-sectional rank ≥ top-N (today, T).
> Confirmation: T-day volume > N×ADV (same bar).
> No confirmation → no entry on T+1.

Effort: ~3 days. No state machine; pure same-bar AND-gate at signal time.
Closest to existing MFS architecture.

### 3.2 Next-bar / 1-day deferred confirmation (medium cost)

**Primary alert + secondary candle**:
> T-day signal: composite rank ≥ top-N.
> Armed state: signal waits for T+1 confirmation candle (e.g., T+1
> close > T+1 open, or T+1 high > T high).
> If T+1 confirms → enter at T+2 open.
> If T+1 fails → signal voids, no entry.

Effort: ~1 week. Minimum state machine (1 bar of memory per symbol).

### 3.3 Multi-bar TTL window (medium-high cost)

**Breakout-then-retest**:
> T-day setup: price > N-day high (the breakout bar).
> Armed window: [T+1, T+M] where M ∈ {3, 5, 10, 21} (mining-tunable).
> Confirmation: price returns to ≥ N-day high level after touching it
> (the retest), OR alternatively, price holds above N-day high for K
> consecutive bars within window.
> Entry: at the confirmation bar's close OR next bar's open.
> Expiry: M bars without confirmation → signal voids.

Effort: ~2 weeks. State machine tracking (sym × armed_ts × current_age)
per signal. NAV/backtest engine needs to handle the "armed but not
filled" carry.

**Anchor entry with timeout**:
> Similar shape: signal at T, must enter within M bars OR void.
> Variant: a separate "anchor price" that the next signal must clear
> (e.g., "enter only if price > T-day high within next 5 bars").

### 3.4 Multi-phase patterns (high cost)

- **Divergence-then-trigger** (RSI/MACD divergence at level → break above)
- **Wyckoff accumulation/distribution** (absorption → spring → mark-up)
- **Stochastic re-entry** (first oversold → return to neutral → second
  oversold within lookback → execute)
- **Support/resistance bounce** (test level → hold → rally → retest confirms)

Effort: ~3-4 weeks each. Pattern recognizers + state machine + multi-bar
factor families.

## §4 Proposed minimum viable closed loop (MVP — for user decision)

Target = **§3.2 "primary alert + secondary candle" + §3.3
"breakout-then-retest with TTL"** as the MVP scope. Two patterns
cover the architectural surface area; deeper patterns (§3.4) reuse
the same state machine.

### 4.1 Architecture sketch

| Layer | Change |
|---|---|
| Signal generation | New strategy class `core/signals/strategies/confirmation_pattern.py` |
| State persistence | New file `core/signals/signal_state.py` — pandas-DataFrame keyed by `(sym × signal_ts × ttl_bars × current_age)`. State written at each bar; expired states purged |
| Factor generators | New multi-bar factor family in `core/factors/factor_generator.py`: `breakout_signal_age_5d` / `retest_proximity_pct` / `time_since_arm_bars` / `confirmation_strength` |
| Mining search space | New `ConfirmationPatternSpace` in `strategy_space.py::ALL_SPACES`: parameters `setup_lookback` (5-60d) / `confirmation_ttl_bars` (1-21d) / `confirmation_threshold_pct` (0.5%-3%) / `arm_type` (breakout / divergence / etc.) |
| Backtest engine | `core/backtest/backtest_engine.py` extension: deferred-execution support (signal armed at T, fill date at T+k when confirmation lands). Cash carry semantics during armed state |
| Evaluator | `core/mining/evaluator.py` portfolio-level state tracker; NAV during armed-not-filled is just cash (or carries SPY beta if "hedge during arm" is a future feature) |
| Leakage test | New test family: confirmation logic must not "look ahead" — at T+k decision, only bars ≤ T+k visible |

### 4.2 Search space dimensions (proposed)

```python
class ConfirmationPatternSpace(ParameterSpace):
    """Setup → armed → confirmed → executed signals with TTL window."""

    def sample(self, trial):
        return {
            "arm_type":                  trial.suggest_categorical(
                "arm_type",
                ["breakout_high_n",
                 "next_bar_close_gt_open",
                 "consec_above_high_n_bars",
                 "retest_after_breakout"]
            ),
            "setup_lookback_days":       trial.suggest_int(
                "setup_lookback", 5, 60),
            "confirmation_ttl_bars":     trial.suggest_int(
                "ttl_bars", 1, 21),
            "confirmation_threshold_pct": trial.suggest_float(
                "conf_thresh_pct", 0.5, 3.0, step=0.25),
            "top_n":                     trial.suggest_int(
                "top_n", 3, 10),
            "rebalance_monthly":         trial.suggest_categorical(
                "monthly", [True, False]),
        }
```

### 4.3 Acceptance criteria

This MVP succeeds if it produces ANY archived mining trial with:
- Track A acceptance pass (per `core/research/temporal_split_acceptance.py`)
- Raw NAV Pearson < 0.85 vs RCMv1 AND vs Cand-2 AND vs Trial 9
  (cycle04-08 sibling threshold)
- Cap_aware OR equivalent role-appropriate concentration discipline
- Non-trivial trade frequency (≥ 50 trades/yr) — confirms armed-then-
  fired isn't just "wait forever, never enter"

A 0-nominee outcome is acceptable IF it surfaces a clear signal-pattern
limitation (e.g., "TTL > 10 days produces same NAV as untime-gated;
TTL ≤ 3 days produces too-few trades"). The architectural value is
adding the search dimension regardless of immediate alpha.

### 4.4 Out of scope (defer)

- §3.4 multi-phase patterns (Wyckoff / divergence / stochastic re-entry)
  — reuse the MVP state machine when MVP is proven
- Intraday confirmation (60m / 30m / 15m TTL windows) — daily TTL
  first; intraday is multi-TF coordination problem on top
- Live execution integration (paper / broker) — research-only first
- Hedging during armed state — phase 2

## §5 Estimated engineering

| Phase | Scope | Time |
|---|---|---|
| Phase 1: Schema + state machine | `signal_state.py` + tests | 3 days |
| Phase 2: Single pattern (breakout-then-retest) | strategy class + factor + leakage test | 4 days |
| Phase 3: Backtest deferred-execution support | engine extension + parity test | 4 days |
| Phase 4: Mining search space + 1 cycle dry-run | `ConfirmationPatternSpace` + 200-trial mining | 2 days |
| Phase 5: Acceptance integration + closeout | Track A eval + memo | 2 days |
| **Total MVP** | | **~3 weeks** |

Add §3.2 next-bar-confirmation variant: +2 days at Phase 2.
Add §3.1 same-day volume gate: +1 day at Phase 2 (no state machine).

## §6 Open questions for user decision

1. **MVP scope**: stick to §3.3 breakout-then-retest only, or include
   §3.2 (next-bar) + §3.1 (volume gate) in same MVP?
2. **Cycle interaction**: if MVP ships before trial9_002 TD60 (~2026-08-06),
   does new cycle mine while trial9_002 still in forward observation?
   Or wait for trial9_002 TD60 verdict to inform direction?
3. **Universe**: MVP on existing 78-stock universe + same cap_aware
   construction, OR expand universe in parallel (compound the change
   axes)?
4. **Codex/external review**: is this PRD scope big enough to warrant
   external review round before kickoff, or operator-only roundtrip?
5. **Storage/state cost**: armed signals persist state per bar. For
   78 syms × 252 days × 21 TTL = ~400K state rows / candidate / year.
   Acceptable, but flag now.

## §7 Reversibility / rollback

- All new modules are additive (`core/signals/strategies/confirmation_pattern.py`
  + `core/signals/signal_state.py` + new factor family + new mining
  space). Pre-PRD mining + production paths unchanged.
- Mining `ALL_SPACES` registration is opt-in per cycle yaml's
  `strategy_space` field; existing cycles don't auto-select the new
  space.
- Backtest engine extension is gated by strategy class; existing
  strategies don't touch the deferred-execution path.
- Rollback: delete new modules + revert `ALL_SPACES` entry. No data
  schema changes to migrate.

## §8 Cross-references

- Cycle07-fleet final synthesis: `docs/memos/20260506-cycle07_to_fleet_final_synthesis.md`
- Trial 3 Red verdict + sibling-by-NAV evidence: `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`
- Strategy-type pivot option enumeration: same memo §"cycle direction options"
- Anti-pattern guard: docs/checkpoints/20260430-self_audit_methodology.md (R3 leakage testing applies)
- Existing intraday primitives: `core/intraday/sr_swing.py` (S/R level detection — could feed §3.3 retest detection)
