# Post-cycle10 Strategic Roadmap (DRAFT v1.1 — discussion)

**Date**: 2026-05-13
**Status**: DRAFT v1.1 — adds TC-ceiling unifying frame + D1/D3 re-audit + 6-signal seed library
**Authors**: operator (zibomeng@) + Claude Code assist
**Trigger**:
- cycle10 closed 0-nominee (informative null per `docs/memos/20260513-cycle10_closeout.md`)
- User raised 4 architectural questions exposing existing 80%-built infra:
  Q1 confirmation-signal entry / Q2 cadence limit lift / Q3 intraday-daily
  coordination / Q4 ML state
- v1.1: user pushed back on n=1 drops of D1 (universe expansion) + D3 (LLM mining);
  asked for WebSearch on signal designs. Three audits (2026-05-13) returned:
  D1 verdict = drop but for NEW reason (TC ceiling, not breadth);
  D3 verdict = defer (not drop) until K1+T1 produces working construction;
  Signal library = 6 seed candidates from 8-category literature audit.

---

## §1 Live State (2026-05-13 EOD)

### 1.1 Fleet (3 active sleeves in paper / forward)

| Sleeve | Role | Status | Next milestone |
|---|---|---|---|
| `trial9_diversifier_002` | research diversifier | Forward TD007 of 60 | TD60 verdict ~2026-08-06 |
| `simple_baseline_v1` | wealth-vehicle baseline | Paper TD001 (NAV $10K) | Daily soak continuing |
| `spy_8otm_bull_put_v1` | options sleeve | Paper TD005 | TD60 ~2026-07-30 |

### 1.2 Mining workstream

- **cycle04-10**: 10 cycles, **0 deployable nominees**. Each cycle confirmed bundle-binding from a different angle:
  - cycle04-08: factor / construction / cadence variants → raw NAV ≥ 0.85 sibling
  - cycle09: sampler architecture bug (cycle09b yaml family expansion broke combinatorics)
  - cycle10: NAV-residualized objective → broke sibling at factor selection but R7 fail-SPY risk realized (per `docs/memos/20260513-cycle10_closeout.md`)
- **Verdict**: bundle-binding extends past objective-layer fix. Within the long-only-monthly-top10-79stock-bundle, no design modification produces NAV-distinct AND SPY-beating candidates.

### 1.3 Wealth-vehicle baseline ship state

- simple_baseline_v1: train-only backtest CAGR +14.9% vs SPY +10.5% (Δ +4.35pp/yr), Sharpe 0.82, per-year MaxDD ≤25%
- Live in paper since 2026-05-13 (TD001), spec_hash `ccd65b8c2bd3b15a445c107aa3268c597849e2c270c5c679739507aafd7c59a2`
- Design provenance: Antonacci 2012 / Faber 2007 / Whaley 2009 / Newfound P&P

---

## §2 The unifying insight (surfaced 2026-05-13)

User observation: **"信号出现就调仓, 不需要规定 monthly/weekly"** — signal-driven > calendar-driven.

This single principle:
1. **Lifts** the monthly-rebalance limitation (Q2)
2. **Enables** ConfirmationPattern setup-then-trigger (Q1)
3. **Coordinates** intraday-daily naturally (intraday confirmation gates daily setup) (Q3)
4. **Reframes** ML Phase 2 from "predict 21d forward returns" to "rank signal-trigger setups" (Q4)

**All 4 of the user's questions share ONE technical blocker**: deferred-execution BacktestEngine integration (PRD §4.1 of `docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md`).

### §2.2 The second unifying insight (v1.1 — D1/D3 audit byproduct)

Cycle04-10 sibling-by-NAV-correlation is structural: **long-only Transfer Coefficient (TC) ceiling, not factor zoo, not universe breadth**.

Clarke-de Silva-Thorley 2002 (FAJ): `IR ≈ IC × √BR × TC`. For long-only US large-cap, TC = 0.40-0.55 (vs unconstrained 0.80-0.95). 5 cycles of factor swap (cycle04-08) and 1 cycle of objective swap (cycle10) confirm that within the (long-only × calendar-rebalance × top-N × bounded-universe) bundle, **TC binds before any other axis**.

This reframes the legitimate attacks on bundle binding:

| Attack | Mechanism | Status |
|---|---|---|
| Long/short relaxation (130/30) | TC 0.45 → 0.75 directly | ❌ Violates `no-short` invariant (need user explicit-go) |
| **Horizon change** (intraday reversal, daily-to-intraday) | Different alpha source, different TC ceiling | ✅ K1 + T1a is exactly this |
| **Cadence change** (signal-driven, not calendar) | Signal-triggered = heterogeneous time-in-market = different geometry | ✅ T1b + T2a is exactly this |
| **Different asset class** (cross-asset done RIGHT, 20-30 ETFs) | Bond/commodity/FX alpha source independent of equity TC | 🟡 Worth retrying post-T1 (cycle04 with only 6 ETFs was n=1 weak) |
| Factor zoo expansion | Add more factors to same construction | ❌ Cycle04-08 already established this doesn't work (5x) |
| Universe expansion (78 → 500) | Add more stocks to same long-only top-N | ❌ TC stays at ceiling; D1 dropped (v1.1) |
| LLM-generated factors | Same as factor zoo, different generator | ❌ Cheap but same binding (D3 deferred until construction fixed) |

**Why this matters for the plan**: K1 + T1 (intraday reversal + signal-driven cadence) is the **cheapest legitimate attack** on TC. T2c LLM mining becomes legitimate only AFTER a working non-bundle construction exists.

---

## §3 Current PQS infra inventory (80%+ built, awaiting one plumbing PR)

| Component | Status | Test coverage | Path |
|---|---|---|---|
| `SignalStateMachine` (ARMED → CONFIRMED \| EXPIRED, TTL-gated) | ✅ COMPLETE | `test_signal_state.py` | `core/signals/signal_state.py` |
| `ConfirmationPatternStrategy` Phase 1 skeleton | ⚠️ SKELETON | NO end-to-end tests | `core/signals/strategies/confirmation_pattern.py` |
| `IntradayReversalStrategy` Phase 1 skeleton | ⚠️ SKELETON | NO end-to-end tests | `core/signals/strategies/intraday_reversal.py` |
| `core.intraday.multi_timescale.decide_timing` | ✅ COMPLETE | `test_timing_decision.py` | `core/intraday/multi_timescale.py` |
| `IntradayBacktestEngine` | ✅ ship | tested for 60m | `core/backtest/intraday_engine.py` |
| `XGBQuintileModel` + `LambdaRankIC` (ML Phase 1.6) | ✅ COMPLETE | 33 tests | `core/ml/xgb_ranking.py` |
| **Deferred-execution `BacktestEngine` extension** | ❌ **NOT BUILT** | n/a | `core/backtest/backtest_engine.py` (extension PRD §4.1) |

**Bottleneck identified**: one missing component (deferred-execution `BacktestEngine` extension) blocks **5 separate workstreams**. ROI is unusually high for plumbing work.

---

## §4 Action items — unified plan

### 🔑 Keystone (1-2 weeks)

| ID | Task | Eng cost | Unlocks |
|---|---|---|---|
| **K1** | Ship deferred-execution `BacktestEngine` extension (PRD §4.1). Accept `entry_signals` + `exit_signals` + `position_sizing_rule` instead of fixed-weight DataFrame. Maintain `held_positions` / `armed_signals` / `position_age` state across bars. Preserve `cap_aware` construction + `cost_model` integration. | 1-2 weeks | T1a, T1b, T1c, T2a, T2c |

### 🥇 Tier 1 — Unlock 80%-built workstreams (3-4 weeks, sequential or parallel post-K1)

| ID | Task | Eng | Source |
|---|---|---|---|
| **T1a** | alt-A `IntradayReversalStrategy` Phase 2-3 (Track A + NAV correlation gate) | 3-5 days | PRD 20260512-alt_archetype_intraday_reversal_prd.md |
| **T1b** | `ConfirmationPatternStrategy` baseline (e.g. "drawup_252d_low > 0.7 setup + breakout confirmation + trailing-stop exit") Phase 2-3 | 1 week | PRD 20260512-signal_confirmation_strategy_expansion_prd.md |
| **T1c** | alt-B event-calendar (PEAD ML-revival + pre-FOMC drift) PRD + ship (uses K1 engine) | 3-4 weeks | 12-axis WebSearch 2026-05-13; pre-existing roadmap |

**Tier 1 success criteria**: each new sleeve passes (a) Track A 17-gate acceptance, (b) NAV correlation gate raw < 0.70 vs existing fleet, (c) MaxDD invariant.

### 🥈 Tier 2 — Signal-driven mining (after T1 ship, 4-6 weeks)

| ID | Task | Eng | Description |
|---|---|---|---|
| **T2a** | Signal-driven cycle11 PRD | 1 week | Mining objective switches from `IC_IR on 21d_forward_ret` to `Sharpe on signal-triggered trades`. Selection space: setup_predicate + confirmation_predicate + exit_predicate. Sibling characteristics fundamentally different from cycle04-10 (no fixed cadence, no fixed top-N). |
| **T2b** | cycle11 mining run + acceptance + closeout | 1-2 weeks | First mining cycle in PQS that ISN'T calendar+top-N. Hypothesis: bundle-binding does not extend to signal-driven game. |
| **T2c** | ML Phase 2 — multi-timescale transformer / regime-conditional ML on signal-driven setup | 2-3 weeks | Phase 1.6 confirmed ML sibling under same construction. Signal-driven construction reopens ML as differentiated alpha source. |

### 🥉 Tier 3 — Incremental optimization (hand-touch, 1-2 days each, any time)

| ID | Task | Eng | Description |
|---|---|---|---|
| **F1** | simple_baseline VIX threshold sensitivity (25/22 vs 30/20 vs 28/18) | 1 day | Train-only; produce 3-config comparison table |
| **F2** | simple_baseline `mtum_risk_off_weight` sweep (0.15 / 0.25 / 0.35 / 0.50) | half day | Train-only |
| **F3** | Multi-TF `validate_timing_value.py` rerun on current data | half day | CLAUDE.md notes "naive bar-direction voting strictly underperformed 60m-only" — verify still holds, document |

### 🎯 Tier 4 — Fleet phase (gated)

| ID | Task | Trigger |
|---|---|---|
| **G1** | Reactivate dormant PRD-E TAA sleeve allocator | Fleet ≥ 3 NAV-distinct sleeves verified (post T1) |
| **G2** | Capital allocation logic for live deployment | T1 ship + Trial 9 v2 TD60 GREEN OR alt-A TD60 GREEN |

### 🔄 Sunk-cost / autopilot (daily, no decision)

- **S1** Trial 9 v2 forward observe → TD60 ~2026-08-06
- **S2** simple_baseline_v1 paper soak daily
- **S3** Options paper observe daily
- **S4** Cumulative VRP single-name scan monthly

### ⏸️ Explicitly DROPPED / DEFERRED (with reason — v1.1 re-audited)

| ID | Task | Status | Reason |
|---|---|---|---|
| **D1** | 200+ stock universe expansion (Task #16, 2-3 weeks data fetch) | ❌ **DROP** (v1.1 re-audited) | Real binding constraint is **long-only TC ceiling 0.45-0.55** (Clarke-de Silva-Thorley 2002 FAJ), NOT breadth. 78 → 500 raises √BR by 2.5× but TC unchanged → ρ=0.40 collapse N_eff to ~12 independent bets. Plus Hou-Xue-Zhang 2017 RFS: 64% of anomalies die when properly weighted; Polygon delisted coverage spotty below large-cap (breaks `bar_provenance` discipline); $10K-$100K is `deep below capacity` (Frazzini-Israel-Moskowitz 2019 FAJ). **Real attacks on TC = horizon change + cadence change + cross-asset done RIGHT**, all covered by K1/T1. |
| **D2** | Multi-asset permanent universe + cycle11 OLD-game mining | ❌ **DROP** | Replaced by T2 signal-driven cycle11 |
| **D3** | LLM-driven mining (AlphaAgent / Hubble / QuantaAlpha) | ⏸️ **DEFER** (v1.1 re-audited; was DROP) | Reproducibility good (AlphaAgent + QuantaAlpha open-source, ~1-2 weeks); cost trivial (~$50-100/run @ claude opus 4.7 batch+cache). BUT: (a) HLZ multi-testing unaddressed in all 3 flagship papers (10k candidates → false-discovery factory); (b) arXiv 2602.14233 critical audit: only 26.8% of 2023-25 LLM finance papers acknowledge look-ahead bias, 1.2% acknowledge survivorship; (c) sibling-by-NAV is geometric (long-only top-N over 78 stocks), LLM-generated factors don't change construction. **Trigger condition to reactivate**: K1+T1 produces a Track A nominee with non-bundle construction → then deploy LLM as search-space expansion ON TOP of working construction. Re-evaluate at T2 closeout. |
| **D4** | XLE / sector tilt added to simple_baseline | ⏸️ DEFER | Sealed-window leak rollback 2026-05-13; needs train-only sector evidence |
| **D5** | Weekly cadence on cycle04-08 bundle | ❌ DROP | cycle08 already FAILED; signal-driven supersedes |

### 📚 Signal candidate seed library (v1.1 — for T1b ConfirmationPattern + T2a cycle11)

Filtered for STRENGTH OF EVIDENCE from 8-category literature audit (2026-05-13). Used as the seed pool for T1b/T2a mining; selection space at mining time can extend beyond these.

| # | Signal | Role in PQS | Strongest evidence | Free-data |
|---|---|---|---|---|
| **1** | **Faber 10-mo / 200-SMA cross** | Risk-off regime gate (fleet-wide) | Faber SSRN 962461 (2007/2013 revisit): vol cut ~30%, MaxDD cut materially; avoided 2008 OOS | yfinance daily |
| **2** | **Connors RSI(2) < 5 above 200-SMA** | Mean-reversion entry trigger | Connors-Alvarez 2008 + replications: hit rate ~75% / profit factor ~2.0; vendor-evidence not academic-peer-reviewed | yfinance close |
| **3** | **Donchian 20/55 breakout (Turtle S1/S2)** | Trend-following entry trigger | Faith 2007 (Turtle method); long-only US-equity weaker than original futures but rule is rule-encodable | OHLC rolling max/min |
| **4** | **HY OAS rolling 60d z-score** (FRED BAMLH0A0HYM2) | Cross-asset risk-off gate | LEADING indicator (credit moves before equity); widely cited (Situ SSRN 5815822, State Street notes) | FRED free |
| **5** | **Zweig breadth thrust** (10d EMA A/(A+D) 0.40 → 0.615 in ≤10 days) | Bottom-detection trigger | Zweig 1986; reportedly 13/13 hit rate 1944-2014 (small sample but uncommonly strong) | $ADV/$DECL from Stooq or computed from universe |
| **6** | **Gervais-Kaniel-Mingelgrin abnormal-volume** | Visibility tilt / volume-confirmed factor | Gervais-Kaniel-Mingelgrin J.Finance 2001 + JFE 2020 replication: weekly abnormal-vol top-decile excess 50-100 bps/month, weaker post-2010 but significant | Daily volume + price |

**Three orthogonal archetype combinations to test in T1b/T2a mining** (each has its own state machine + acceptance):

| Archetype | Entry signal | Confirmation | Regime gate | Exit |
|---|---|---|---|---|
| **A: Trend-following** | Donchian 55-day high | ADX(14) > 25 at trigger bar | SPY > 200-SMA | Donchian 20-day low OR ATR(14)×2 trailing |
| **B: Mean-reversion** | Connors RSI(2) < 5 | 5-SMA crossback up next day | SPY > 200-SMA | RSI(2) > 70 OR 10-bar TTL |
| **C: Cross-asset risk gate** | HY OAS z-score < -0.5 AND VIX/VXV < 0.95 | Zweig breadth thrust optional secondary | (this IS the regime gate) | HY OAS z > +1.5 OR VIX/VXV > 1.05 → cash |

Why three archetypes: signal sources are orthogonal (price/breakout, price/reversion, credit/volatility). If T2a mining produces 3 candidates one per archetype, they SHOULD show low pairwise NAV correlation by construction. This is the structural diversifier we couldn't get from cycle04-10 factor swaps.

**Archived / not-seeded** (per literature audit): pre-FOMC drift (dead post-2015), Hurst exponent (signal-to-noise too close on daily), pure OBV divergence (no peer-reviewed standalone Sharpe), Wyckoff phases (rule-encodable but no academic Sharpe — keep as MINING TARGET not seed).

---

## §5 Execution dependency graph

```
                                  Week 1-2
                                  ┌──────────────────┐
                                  │  K1: deferred-   │
                                  │  exec engine     │
                                  │  (1-2 weeks)     │
                                  └────────┬─────────┘
                                           │
            ┌──────────────────────────────┼──────────────────────────────┐
            ▼                              ▼                              ▼
       Week 3-4                       Week 3-4                       Week 3-6
     ┌──────────┐                  ┌──────────┐                  ┌──────────┐
     │ T1a alt-A│                  │ T1b      │                  │ T1c      │
     │ Phase2-3 │                  │ ConfPat  │                  │ alt-B    │
     │ 3-5 days │                  │ baseline │                  │ event    │
     │          │                  │ 1 week   │                  │ 3-4 wk   │
     └─────┬────┘                  └─────┬────┘                  └─────┬────┘
           │                             │                             │
           └─────────────┬───────────────┴─────────────┬───────────────┘
                         │                             │
                         ▼                             ▼
                   Week 4-5                       Week 5-8
                ┌──────────────┐               ┌──────────────┐
                │ T2a cycle11  │               │ T2c ML       │
                │ signal-driven│               │ Phase 2      │
                │ PRD          │               │ 2-3 weeks    │
                │ 1 week       │               │ (parallel)   │
                └───────┬──────┘               └──────────────┘
                        │
                        ▼
                  Week 6-8
                ┌──────────────┐
                │ T2b cycle11  │
                │ mining +     │
                │ closeout     │
                └──────────────┘

S1-S4 autopilot daily (always)
F1-F3 hand-touch insertable (1-2 days each)
G1-G2 gated post-T1 (sleeve allocator reactivation)
```

**Total wall-clock to fleet ≥ 4 sleeves**: ~8-10 weeks if K1+T1 prioritized.

---

## §6 Open questions for joint decision

### Q1: Tier 1 ordering — parallel or sequential?
- **Parallel**: T1a (3-5d) + T1b (1wk) + T1c (3-4wk) all start after K1. T1c is longest, drives Week 3-6 critical path.
- **Sequential**: T1a first (fastest, validates K1 engine end-to-end), then T1b, then T1c. Less risk if K1 has bugs.
- **My recommendation**: T1a first (1 week K1 + 5 days T1a = validation of full chain), then T1b + T1c parallel.

### Q2: alt-B PEAD scope at retail
- 2026 PEAD literature shows large-cap Sharpe ~0.63 (Lan et al. ML revival); micro-cap 0.86 but PQS large-cap universe excludes
- Implementation needs earnings dates + SUE data — PQS has 210MB EDGAR cache; need to verify SUE computation feasible from existing data
- pre-FOMC drift post-2015 weaker, only high-VIX regime
- **Question**: ship PEAD-only first (faster, more solid evidence) or PEAD+FOMC bundle?

### Q3: Signal-driven cycle11 mining objective
- Old game: maximize `IC_IR(composite_score, fwd_21d_ret)`
- New game options:
  - (a) Maximize `Sharpe of signal-triggered trades` (per-trade P&L distribution)
  - (b) Maximize `Calmar of signal-triggered NAV` (return / MaxDD)
  - (c) Maximize `IR vs benchmark of strategy NAV` (active alpha)
- Each has different overfitting profile + computational cost
- **Question**: pick one for v1 PRD, defer others?

### Q4: ML Phase 2 scope and timing
- Phase 1.6 confirmed sibling-on-same-construction at IC level
- Phase 2 options:
  - (a) Multi-timescale transformer (sequence model on 60m+30m+daily features)
  - (b) Regime-conditional ranker (different ranker per BULL/BEAR/CRISIS regime)
  - (c) Signal-driven ML — rank candidate setup-trigger combos via XGB/Transformer
- (c) couples tightly with T2a signal-driven cycle11; might pursue together
- **Question**: ML Phase 2 timed with T2 or as separate workstream?

### Q5: F1/F2/F3 priority and timing
- All cheap (1-2 days each)
- F1+F2 directly optimize live baseline (real wealth impact)
- F3 validates Multi-TF API (informs T1a alt-A design)
- **Question**: F1+F2 now (before K1) or F3 first (informs T1a)?

### Q6: Test surface budget
- K1 adds substantial test surface (entry/exit signal contract, state machine, position lifecycle)
- T1a/b/c each add per-strategy tests
- T2 adds new mining cycle test patterns
- **Question**: any pushback on test discipline (e.g., accept TDD only for K1, integration-test-only for T1)?

### Q7: Forward-observation discipline as new sleeves ship
- Each T1 ship adds a new forward candidate
- Daily ritual already covers Trial 9 v2 + simple_baseline + options
- **Question**: same observe-script pattern per sleeve? Or unified observe runner?

### Q8: Signal candidate seed library — accept all 6 or trim? (v1.1)
- §4 signal library has 6 seeds + 3 archetype combos
- Each adds 1-2 days implementation if pulled into T1b/T2a
- 6 seeds × 3 archetypes = wide net but bounded
- **Question**: accept all 6 as seed pool / accept 3 archetype combos as test set / trim to operator's strongest-evidence subset?
- **My recommendation**: accept all 6 as seed pool; T2a mining selects which subsets compose archetypes; the 3 archetype table is the smoke-test set for K1+T1b (not the binding scope of T2a)

---

## §7 Risks + mitigations

### R1: K1 plumbing reveals deeper architecture issues
- **Risk**: deferred-execution engine touches `BacktestEngine` core; might break existing cycle04-10 backtests if not careful
- **Mitigation**: keep old code path; add new path via flag `--execution-mode signal_driven` (default `calendar`); regression test all existing strategies before merge

### R2: Signal-driven candidates also fail Track A SPY HARD gate
- **Risk**: signal-driven still long-only US equity → still tied to SPY beta
- **Mitigation**: signal-driven strategies have **heterogeneous time-in-market**. Strategy can sit in cash 50%+ of days. Sharpe-per-time-in-market may dominate SPY at-risk-adjusted basis even if absolute CAGR < SPY.
- **Acceptance**: revise CLAUDE.md to allow "signal-driven sleeves judged on cash-adjusted Sharpe, not CAGR vs SPY"? Or hold the line?

### R3: cycle11 0-nominee
- **Risk**: signal-driven game produces 0 candidates passing acceptance
- **Mitigation**: stop rule pre-registered in cycle11 yaml. If 0-nominee, confirms "signal-driven IS NOT the answer either" — INFORMATIVE NULL like cycle10. Strategic pivot at that point would be options-sleeve scale-up + multi-asset permanent universe.

### R4: Forward observation infrastructure scales linearly
- **Risk**: each new sleeve adds daily observe overhead
- **Mitigation**: K1 already includes shared deferred-execution path; observe scripts converge to common pattern. Should be sub-linear.

### R5: 2026 sealed window contamination via forward observation
- **Risk**: as more sleeves observe in 2026, more sealed-window data enters context
- **Mitigation**: per `feedback_websearch_sealed_data_discipline` memory rule — design must justify from train+theory only; observation data is read-only at design time

---

## §8 What I'm NOT recommending (and why — v1.1 refined)

- **D1 universe expansion to 200-500 stocks**: real binding is long-only TC ceiling (0.45-0.55), not breadth. Clarke-de Silva-Thorley 2002 + Hou-Xue-Zhang 2017 + Polygon delisted-coverage gap. Adding stocks raises √BR by 2.5× but TC unchanged → ρ-driven N_eff collapse to ~12. Plus survivorship-bias risk + multiple-testing-surface expansion + smid liquidity drag at $10K-$100K. **The literature is unambiguous: long-only is the binding constraint, not size of universe.**
- **D3 LLM-driven mining NOW**: deferred not dropped. Cheap to reproduce + open-source available, but: (a) HLZ multi-testing unsolved (false-discovery factory at 10k candidates); (b) arXiv 2602.14233 shows the field is methodologically weak (1.2% acknowledge survivorship bias); (c) LLM-generated novel factors don't fix portfolio GEOMETRY (the binding constraint per cycle04-08 + Trial 3 RED). Reactivate AFTER K1+T1 produces working construction, then deploy LLM as search-space expansion.
- **More cycle10-style mining on same bundle**: HLZ multiple-testing math + 10-cycle 0-nominee = <5% base rate. Wasteful.
- **130/30 long-short** (real TC fix): violates `no-short` invariant in CLAUDE.md. Off-table without explicit-go.

**What I AM recommending (TC ceiling–consistent attacks)**:
- K1 + T1a: horizon change (intraday reversal) — different TC ceiling
- T1b + T2a: cadence change (signal-driven, heterogeneous time-in-market) — geometry escape
- (post-T1) cross-asset done RIGHT (20-30 ETFs, not 6) as next-cycle hypothesis

The pattern: attack TC ceiling via construction (horizon / cadence / asset class), not via factor zoo (cycle04-08) or universe size (D1).

---

## §9 Recommended decision (operator preference, pending user concurrence)

**Path**: K1 → T1a → (T1b ∥ T1c) → (T2a + T2c) — with F1+F2 inserted opportunistically Week 1 (before K1 ship).

**Estimated wall-clock**: 8-10 weeks to a 4-sleeve forward fleet (Trial 9 v2 + simple_baseline + alt-A + alt-B), with T2 cycle11 evidence by Week 8-10.

**Major decision points along the way**:
- End of Week 2: K1 ship → T1a kickoff. Decision: confirm T1b+T1c sequencing.
- End of Week 4 (T1a ship): does alt-A pass Track A + NAV gate?
- End of Week 7 (T1b ship): does ConfirmationPattern produce viable candidates?
- End of Week 8-10 (T2 closeout): does signal-driven mining produce nominees?

Each decision point is a potential pivot. The architecture is built for incremental commitment.

---

## §10 What this memo is asking (v1.1 refresh)

This is a **DISCUSSION DRAFT**. Specific asks:

1. **Confirm or revise** §9 path
2. **Answer §6 open questions** Q1-Q8 (Q8 is new: signal candidate seed library scope)
3. **Flag any deferred/dropped items in §4 D1-D5** you want to override (D1 + D3 already re-audited in v1.1; D2/D4/D5 still open to challenge)
4. **Add any axis I missed** — especially anything not covered by the 12-axis WebSearch synthesis + v1.1 D1/D3 re-audit

### v1.1 changes summary (2026-05-13 evening)

- New §2.2 TC ceiling unifying frame (Clarke-de Silva-Thorley 2002): long-only TC 0.45-0.55 is the actual binding constraint, not breadth / not factor zoo
- D1 (200+ stocks) drop reason updated from weak n=1 to load-bearing literature (TC ceiling + Hou-Xue-Zhang microcap + Polygon coverage + sub-capacity)
- D3 (LLM mining) **DROP → DEFER**: AlphaAgent + QuantaAlpha + Hubble all reproducible at low cost ($50-100/run) but unsolved HLZ multi-testing + portfolio geometry binding → defer until K1+T1 working construction exists, then deploy as expansion
- New §4 signal candidate seed library: 6 evidence-strong seeds + 3 orthogonal archetypes (trend / mean-reversion / cross-asset risk gate) for T1b + T2a
- §8 refined with explicit "TC ceiling–consistent attacks" framing

After your input, v2 finalizes and K1 starts.
