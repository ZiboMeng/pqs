# PRD — Signal-confirmation strategy expansion (setup-then-trigger / TTL-gated entries)

**Authors**: operator (zibomeng@), with Claude Code assist
**Date**: 2026-05-12
**Status**: DRAFT **v1.1** (post operator 4-round audit + post strategic decision memo)
**Triggered by**: 2026-05-12 全盘审计 finding — PQS mining + strategy
framework has ZERO signal-confirmation / armed-then-fired / TTL-based
entry patterns; the structural cycle04-08 + Trial 3 sibling-by-NAV
problem may have orthogonal axis here.

**v1.1 changes vs v1** (per audit F1-F9 + strategic memo
`docs/memos/20260512-signal_confirmation_mvp_strategic_decision.md`):
- F1: §2 factual error fixed — Trial 3 is the only Track A 17/17 PASS
  post-fix; cycle04/05/06/08 top trials FAIL Track A. NAV 0.78-0.89 is
  Trial 3 single-candidate's pairwise observation, not cycle04-08 集体.
- F2: §4.3 acceptance NAV anchor clarified — RCMv1 / Cand-2 backtest
  NAV (2009-2025 full period), Trial 9 backtest NAV (same period).
- F3: §2 added honest "mechanism uncertainty" paragraph — TTL +
  confirmation breaking sibling-by-NAV is empirical, not a-priori.
- F4: §3.1 renamed "Same-bar AND-gate filter" (not "confirmation").
- F5: §3.2 deleted (was §3.3 ttl_bars=1 special case; redundant).
- F6: setup_lookback range 5-60 → 5-252 (covers full factor span).
- F7: Phase 3 backtest engine effort 4 → 6 days; total MVP ~3 → ~3.5 weeks.
- F8: §4.4 added — armed_state vs min_holding_days explicit difference.
- F9: §4.5 added — MFS sleeve vs replacement clarified.
- Decision 2 (strategic memo): §4.3 acceptance opened to dual-role
  gate (core_alpha first, then diversifier).
- Decision 3 (strategic memo): scope = §3.1 + §3.2 (was §3.3), 2
  patterns.

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

Cycles 04-08 + Trial 3 produced collectively 5 top-trial candidates
through mining. Track A acceptance verdict post-P0 fix (commit `5873653`):
- cycle04 top trials: 0/3 Track A pass
- cycle05 top trial (Trial 9): does not pass core_alpha Track A (fails
  OOS walk-forward window-mean vs QQQ); passes v2 split as
  **diversifier role** with explicit waiver
- cycle06 top trials: 0/3 Track A pass
- cycle07a top trial (Trial 3): **1/3 — 17/17 PASS** (sole Track A pass)
- cycle08 top trials: 0/3 Track A pass

The sole Track A pass (Trial 3) has **raw NAV Pearson 0.874 vs RCMv1,
0.892 vs Cand-2, 0.783 vs Trial 9** — all violations of the cycle04-08
sibling threshold (raw < 0.85). Memo
`docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`
§"Three structural findings" empirically demonstrates this is the
binding sibling pattern:

- Trial 3 shares ONLY `drawup_from_252d_low` factor with RCMv1 (1 of 4)
  yet raw 0.874
- Trial 3 shares 0 of 3 factors with Cand-2 yet raw 0.892
- **Banning specific factors (cycle05) doesn't break it; expanding
  factor zoo (cycle04→05 +17 factors) doesn't break it; the
  construction itself is binding** — long-only top-N over the 78-stock
  universe with monthly rebalance produces ~30-50% identical holdings
  across disjoint-factor candidates.

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
TTL window → buy" which **may or may not** have structural NAV-distinct
potential — it introduces TIME as a first-class signal-state dimension.

### §2.1 Mechanism uncertainty (honest)

Whether TTL + confirmation actually breaks sibling-by-NAV is an
**empirical question, NOT an a-priori guarantee**.

The setup step is still factor-based ranking; if RCMv1 top-10 names
have a 70%+ confirmation hit rate within a 5-day TTL window, then
signal-confirmation merely delays the same holdings by N bars and
NAV correlation stays high. Sibling-by-NAV is broken only if the
confirmation filter is **selective enough to materially shift the
held set** away from RCMv1's natural top-N picks.

This PRD's MVP is therefore framed as a **search-axis expansion**,
not a guaranteed alpha-source addition. The architectural value of
adding "time-as-signal-state" to the mining search space stands
regardless of whether the first cycle produces a NAV-distinct
candidate — but actual diversification effect must be empirically
verified at acceptance time.

## §3 Patterns to bring into mining search

Survey of well-established quant patterns that PQS currently does
NOT have, ordered by minimum-viable-implementation cost. **MVP scope =
§3.1 + §3.2** (per Decision 3 in strategic memo).

### 3.1 Same-bar AND-gate filter (lowest cost — IN MVP)

**Volume confirmation filter**:
> Primary signal: composite cross-sectional rank ≥ top-N (today, T).
> Filter: T-day volume > N × ADV (same bar).
> No filter pass → no entry on T+1.

Effort: ~1 day. **No state machine** (pure same-bar AND-gate at signal
time). Closest to existing MFS architecture. Serves as the
zero-TTL baseline against which §3.2's TTL-based variants are compared.

### 3.2 Multi-bar TTL window (medium-high cost — IN MVP)

**Breakout-then-retest**:
> T-day setup: price > N-day high (the breakout bar).
> Armed window: [T+1, T+M] where M ∈ {1, 3, 5, 10, 21} (mining-tunable;
> M=1 reduces to next-bar confirmation as a special case).
> Confirmation: price returns to ≥ N-day high level after touching it
> (the retest), OR alternatively, price holds above N-day high for K
> consecutive bars within window.
> Entry: at the confirmation bar's close OR next bar's open.
> Expiry: M bars without confirmation → signal voids.

Effort: ~2 weeks (state machine + new factor family + leakage tests +
backtest engine deferred-execution support). State machine tracks
(sym × armed_ts × ttl_bars × current_age). NAV/backtest engine handles
"armed but not filled" carry as cash (no SPY hedge in MVP).

**Anchor entry with timeout** (folded into §3.2):
> Variant of breakout-then-retest: the "anchor price" is the T-day high
> (the breakout level). Same TTL state machine; different confirmation
> rule (e.g., "enter only if price > T-day high within next M bars").

### 3.3 Multi-phase patterns (high cost — DEFERRED, NOT IN MVP)

- **Divergence-then-trigger** (RSI/MACD divergence at level → break above)
- **Wyckoff accumulation/distribution** (absorption → spring → mark-up)
- **Stochastic re-entry** (first oversold → return to neutral → second
  oversold within lookback → execute)
- **Support/resistance bounce** (test level → hold → rally → retest confirms)

Effort: ~3-4 weeks each. Pattern recognizers + state machine + multi-bar
factor families. **Reuse MVP state machine** when MVP is empirically
validated.

## §4 Proposed minimum viable closed loop (MVP)

Target = **§3.1 (same-bar AND-gate filter) + §3.2 (breakout-then-retest
TTL window)** as the MVP scope. Two patterns cover the architectural
surface area; deeper patterns (§3.3) reuse the same state machine.

### 4.1 Architecture sketch

| Layer | Change |
|---|---|
| Signal generation | New strategy class `core/signals/strategies/confirmation_pattern.py` |
| State persistence | New file `core/signals/signal_state.py` — pandas-DataFrame keyed by `(sym × signal_ts × ttl_bars × current_age)`. State written at each bar; expired states purged. **In-memory ephemeral during mining; persisted in forward manifest only when forward observation begins** |
| Factor generators | New multi-bar factor family in `core/factors/factor_generator.py`: `breakout_signal_age_5d` / `retest_proximity_pct` / `time_since_arm_bars` / `confirmation_strength` / `volume_surge_ratio_at_setup` |
| Mining search space | New `ConfirmationPatternSpace` in `strategy_space.py::ALL_SPACES`: see §4.2 |
| Backtest engine | `core/backtest/backtest_engine.py` extension: deferred-execution support (signal armed at T, fill date at T+k when confirmation lands). Cash carry semantics during armed state. **Must preserve M11a/M11b paper-BT parity guarantees** |
| Evaluator | `core/mining/evaluator.py` portfolio-level state tracker; NAV during armed-not-filled is cash (no SPY hedge in MVP) |
| Leakage test | New test family: confirmation logic must not "look ahead" — at T+k decision, only bars ≤ T+k visible. Per `docs/checkpoints/20260430-self_audit_methodology.md` R3 |

### 4.2 Search space dimensions (proposed)

```python
class ConfirmationPatternSpace(ParameterSpace):
    """Setup → armed → confirmed → executed signals with TTL window."""

    def sample(self, trial):
        return {
            "arm_type":                  trial.suggest_categorical(
                "arm_type",
                ["volume_gate_same_bar",     # §3.1 (ttl_bars semantically 0)
                 "breakout_high_n",
                 "consec_above_high_n_bars",
                 "retest_after_breakout"]
            ),
            "setup_lookback_days":       trial.suggest_int(
                "setup_lookback", 5, 252),  # extended per audit F6
            "confirmation_ttl_bars":     trial.suggest_int(
                "ttl_bars", 0, 21),   # 0 = same-bar filter (§3.1); 1-21 = §3.2
            "confirmation_threshold_pct": trial.suggest_float(
                "conf_thresh_pct", 0.5, 3.0, step=0.25),
            "volume_multiplier":         trial.suggest_float(
                "vol_mult", 1.0, 3.0, step=0.25),  # for arm_type=volume_gate_same_bar
            "top_n":                     trial.suggest_int(
                "top_n", 3, 10),
            "rebalance_monthly":         trial.suggest_categorical(
                "monthly", [True, False]),
        }
```

Note: `arm_type=volume_gate_same_bar` is special-cased so the state
machine is bypassed for the §3.1 path. This serves as the zero-TTL
baseline so we can attribute any signal-confirmation NAV difference
to "TTL state" vs "filter".

### 4.3 Acceptance criteria — DUAL-ROLE GATE (per Decision 2)

This MVP cycle's yaml pre-registers BOTH role acceptance gates. Each
trial is evaluated through both; whichever the candidate naturally
passes determines its role assignment.

**core_alpha gate (try first)**:
- Track A acceptance pass per
  `core/research/temporal_split_acceptance.py` (full per-validation-year
  vs SPY HARD + 2025 holdout HARD + per-year max_dd ≤ 20% + stress
  slice + beta + concentration)
- Raw NAV Pearson < 0.85 vs (RCMv1 backtest NAV 2009-2025) AND vs
  (Cand-2 backtest NAV 2009-2025) AND vs (Trial 9 backtest NAV
  2009-2025). All three thresholds must clear (sibling-by-NAV reject)
- ≥ 50 trades / year (non-trivial trade frequency — confirms
  armed-then-fired isn't "wait forever, never enter")
- avg `armed_age / max_ttl_bars` < 0.80 (confirmation isn't too strict
  — protect against perpetually-armed signals; audit F10)

→ If pass: candidate role = **core_alpha**

**diversifier gate (try second only if core_alpha fails)**:
- vs SPY > 0 (full period HARD + 2025 holdout HARD)
- per-year max_dd ≤ 20% (HARD), soft-warn at 18%
- Cross-asset utilization: `non_equity_weight_avg ≥ 15%`
- Factor overlap with active core_alpha: `factor_overlap_with_active_core = 0`
- Raw NAV correlation: < 0.70 vs all anchors (stricter than core_alpha)
- Residual NAV correlation: < 0.50 vs all anchors after regressing
  out SPY+QQQ beta
- ≥ 50 trades / year + armed_age check (same as core_alpha)

→ If pass: candidate role = **diversifier**

**Both fail** → 0 nominee (acceptable outcome; surfaces signal-pattern
limitation — see §6.1).

### 4.4 armed_state vs min_holding_days clarification (per audit F8)

These are **different concepts at different layers**:

| Concept | Layer | Purpose |
|---|---|---|
| `min_holding_days` | Production MFS (post-fill state) | Turnover throttle — once a position is filled, it cannot be sold for N days. Reduces transaction cost via trade frequency reduction |
| `armed_state` | New (pre-fill state) | Confirmation gate — signal generated at T does not produce a fill until either confirmation criterion is met (within TTL) OR signal expires |

The two are orthogonal: a confirmed armed signal becomes a fill, which
then becomes subject to min_holding_days. min_holding_days does NOT
gate signal generation; armed_state does NOT gate position holding.
Tests in §7 cover the boundary case (signal armed → confirm → fill →
min_holding_days enforced from fill date, not arm date).

### 4.5 MFS sleeve vs replacement (per audit F9)

The new strategy class **does NOT replace** `MultiFactorStrategy` in
production. Specifically:

- `config/production_strategy.yaml` is NOT modified by this PRD
- `core/signals/strategies/multi_factor.py::MultiFactorStrategy` is
  unchanged
- New `core/signals/strategies/confirmation_pattern.py` is a separate
  strategy class consumed only by mining + (potentially future) fleet
  allocator
- A mining-produced confirmation-pattern candidate that passes Track A
  acceptance enters the candidate registry at status=S2_paper_candidate;
  if approved for forward init via operator review → fleet sleeve;
  NEVER auto-replaces production MFS

This is identical to how cycle04-08 mining candidates were treated.

### 4.6 Out of scope (defer)

- §3.3 multi-phase patterns (Wyckoff / divergence / stochastic re-entry)
  — reuse the MVP state machine when MVP empirically validated
- Intraday confirmation (60m / 30m / 15m TTL windows) — daily TTL
  first; intraday is multi-TF coordination problem on top
- Live execution integration (paper / broker) — research-only first
- Hedging during armed state — phase 2

## §5 Estimated engineering (revised per audit F7)

| Phase | Scope | Time |
|---|---|---|
| Phase 1: Schema + state machine | `signal_state.py` + tests (PASS / FAIL / boundary paths) | 3 days |
| Phase 2: Two patterns + factor family | volume_gate (§3.1) + breakout-then-retest (§3.2) strategy class + 5 new factors + leakage tests | 4 days |
| Phase 3: Backtest engine deferred-execution | engine extension + M11a/M11b parity preservation tests + cash carry semantics | **6 days (revised from 4)** |
| Phase 4: Mining search space + 1 cycle dry-run | `ConfirmationPatternSpace` + 200-trial mining on existing 78-stock universe + post-mining diversity check (audit F13) | 2 days |
| Phase 5: Acceptance integration + closeout | dual-role gate evaluator + Track A integration + closeout memo | 2 days |
| **Total MVP** | | **~3.5 weeks** |

## §6 Open questions (post strategic memo)

Most v1 questions are resolved by the strategic memo's Decision 1-3.
Residual:

1. **Codex/external review**: Per strategic memo Decision rejected
   alternative C, codex review runs **in-flight parallel to Phase 1-2
   engineering** rather than blocking kickoff. Will user trigger codex
   review via `/ultrareview` or wait for Phase 5 closeout? — pending
2. **Mining cycle yaml lineage tag**: proposed
   `track-c-cycle-2026-XX-XX-conf01` where XX-XX is the kickoff date.
   Pre-registration follows existing cycle04-08 yaml immutability
   discipline (yaml sha256 recorded in archive). — pending kickoff date
3. **Storage cost monitoring**: per audit F10/F11, MVP includes
   in-flight diversity check on archived trials (`ttl_bars` distribution
   + `avg armed_age / max_ttl` percentile). Operator-only review at
   Phase 4 dry-run. — defer to Phase 4

## §7 Reversibility / rollback

- All new modules are additive (`core/signals/strategies/confirmation_pattern.py`
  + `core/signals/signal_state.py` + new factor family + new mining
  space). Pre-PRD mining + production paths unchanged.
- Mining `ALL_SPACES` registration is opt-in per cycle yaml's
  `strategy_space` field; existing cycles don't auto-select the new
  space.
- Backtest engine extension is gated by strategy class; existing
  strategies don't touch the deferred-execution path. **M11a/M11b
  parity guarantees** are preserved via Phase 3 parity tests.
- Rollback: delete new modules + revert `ALL_SPACES` entry. No data
  schema changes to migrate.

## §8 Cross-references

- Strategic decision memo (drives this PRD revision):
  `docs/memos/20260512-signal_confirmation_mvp_strategic_decision.md`
- Cycle07-fleet final synthesis:
  `docs/memos/20260506-cycle07_to_fleet_final_synthesis.md`
- Trial 3 Red verdict + sibling-by-NAV evidence:
  `docs/memos/20260507-cycle07a_trial3_red_verdict_evidence_only.md`
- Strategy-type pivot option enumeration: same memo §"cycle direction options"
- Anti-pattern guard: `docs/checkpoints/20260430-self_audit_methodology.md` (R3 leakage testing applies)
- Existing intraday primitives: `core/intraday/sr_swing.py` (S/R level detection — could feed §3.2 retest detection)
- Trial 9 v2 closeout (parallel workstream):
  `docs/memos/20260512-trial9_diversifier_001_closeout.md`
- Priority realign 警告 (guard-before-alpha):
  `docs/memos/20260430-priority_realign_alpha_first.md`
