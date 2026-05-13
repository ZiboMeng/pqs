# PRD — Alt-archetype A: Intraday reversal alpha

**Date**: 2026-05-12
**Status**: DESIGN — implementation gated on cycle #09 verdict
**Lineage**: `alt-archetype-intraday-reversal-2026-05-12`
**Purpose**: alternative alpha source that does NOT share cycle04-08 daily
monthly cap_aware top-N over 78-stock universe construction. Pure
intraday-driven thesis.

---

## §1 Hypothesis

**Daily rebalance monthly construction is saturated** for the PQS
universe — cycle04-08 5 cycles, ~1000 trials, all produced sibling
candidates (raw NAV Pearson 0.85-0.95 vs RCMv1/Cand-2/Trial9).
Intraday-driven alpha has fundamentally different temporal signature;
can break sibling pattern by being literally a different time scale.

Empirical foundation:
- Lehmann 1990 weekly reversal: 1d/5d winner -0.35%/-0.55%/week,
  loser +0.86%/+1.24%/week (still robust in 2010s with cost adjustment)
- Overnight-daytime persistence reversal (Akbas-Boehmer-Jiang-Koch 2022):
  high overnight + low daytime → t+1 reversal
- 2024 momentum 1-year run +28% → 2σ event → 2025 reversal expected
  per Morgan Stanley + JP Morgan research notes (Q2 2025)
- 60m bar level mean-reversion documented in Heston-Korajczyk-Sadka 2010:
  ~30bps/day average opportunity at 1h frequency

**人话**: PQS 现有 cycle04-08 都在 daily + monthly 节奏挖 alpha，5 个 cycle
全失败，说明这个节奏挖到的东西本质上是同一类（互相 sibling）。intraday
（小时级别）是真正不同的时间尺度，理论上应该是独立的 alpha 源 — 而且这个
方向在学术 + 业界都有持续证据。

---

## §2 Existing infrastructure leverage

Today's ship gives intraday reversal direct infrastructure:
- `core/signals/signal_state.py` state machine (ARMED → CONFIRMED|EXPIRED)
- `core/signals/strategies/confirmation_pattern.py` strategy class
  supporting volume_gate_same_bar + breakout_high_n + TTL window
- 5 multi-bar factors (`breakout_signal_age_5d`,
  `time_since_arm_bars`, `volume_surge_ratio_at_setup`,
  `confirmation_strength`, `retest_proximity_pct`)
- `weekly_reversal_signal_5d` factor in Bucket A (Lehmann-style 5d
  composite Z-score)
- `volume_surge_when_flat` (stealth accumulation gate)
- `chaikin_money_flow_20d` / `obv_norm_20d` (accumulation/distribution)
- `core/backtest/deferred_execution.py` (M11a sorted; cash-carry;
  T+k execution kernel — integration with BacktestEngine still pending)

**Still missing for true intraday reversal**:
- 60m bar reliability sweep (data/intraday/1m/<sym>.parquet → 60m
  aggregate exists; provenance sidecar `data/ref/bar_provenance.parquet`
  flags `trades_backfill` for ETF 2024+, `polygon_gz` for 2015-2023,
  `stocks_csv` for 2024-2025; need check completeness on ~30-50 sym
  intraday universe)
- Multi-timescale framework (existing — `core/intraday/multi_timescale.py`
  already ships `decide_timing(ctx, ...)` with 60m/30m/15m/5m roles,
  but currently TIMING layer not ALPHA source)
- Daily-only mining doesn't reach intraday alpha (need intraday miner
  variant)

---

## §3 Design

**Strategy class**: `IntradayReversalStrategy` (inherits `BaseStrategy`)
- Universe: 30-50 most liquid stocks from existing PQS pool, filter via
  `dollar_vol_20d` top quantile + bar_provenance source mix consistency
  check (no symbols with mid-window source transitions during validation)
- Cadence: daily rebalance, holding period 1-5 days
- Setup detection: `weekly_reversal_signal_5d ≤ 5th percentile` OR
  `overnight_gap_5d_extreme` + low-noise filter (e.g.
  `vol_21d > 30th percentile` to exclude microcap-like behavior)
- Confirmation: intraday volume + early-session price action confirms
  reversal direction within first 60m of trading day
  - `volume_surge_at_open_60m > 1.5 × 20d avg` (60m bar from
    `data/intraday/1m/<sym>.parquet` aggregate)
  - `early_session_price_move` align with reversal direction
- Sizing: equal-weight top-N (3-5), small per-position because rapid
  turnover increases tail concentration risk

**Backtest extension** (depends on PRD 20260512 signal_confirmation §4.1
deferred-execution × BacktestEngine integration — currently kernel only):
- T-day setup → T+1 morning confirmation → T+1 60m-bar fill
- Holding 1-5 days, exit on:
  - Reversal target hit (e.g. mean-revert 50% of 5d move)
  - Stop-loss (e.g. opposite direction 0.5σ move)
  - TTL bars exhausted (5d cap)
- M11a/M11b paper-BT parity preservation (sorted iteration mandatory)

**Acceptance** (per CLAUDE.md temporal_split_v2 invariants):
- Track A acceptance per `config/temporal_split.yaml` (5 validation
  years 2018/19/21/23/25)
- Per-year max_dd ≤ 20% hard; stress slice ≤ 25% hard
- Pairwise raw NAV corr < 0.85 vs (RCMv1, Cand-2, Trial 9 v2, cycle #09
  nominee if exists) — 3-way OR 4-way constraint
- Cost sensitivity 2× — must still profitable (cycle #09 doesn't test
  this; intraday has higher turnover so cost sensitivity is binding)
- **Sealed 2026 panel reserved** — single-shot OOS test if Track A
  passes

---

## §4 Data contract & dependencies

### 4.1 Intraday bar coverage requirements

| Symbol class | 2009-2014 | 2015-2023 | 2024-2025 | 2026 sealed |
|---|---|---|---|---|
| Stocks (53) | yfinance backfill 60m | polygon_gz 1m→60m | stocks_csv 1m→60m | stocks_csv_c_drive |
| ETFs (6 cross-asset) | yfinance backfill 60m | polygon_gz 1m→60m | trades_backfill 1m→60m | trades_backfill |
| SPY/QQQ benchmarks | yfinance 60m | polygon_gz 1m→60m | trades_backfill 1m→60m | trades_backfill |

**Required validation pre-fire**:
- run `python dev/scripts/intraday/validate_60m_coverage.py --universe stocks_plus_cross_asset`
- ≥ 95% bar coverage per (sym, year) for years used in train+validation
- bar_provenance source consistency: NO symbol with mid-validation
  source switch (e.g. stocks_csv → trades_backfill in 2024 mid-year)

### 4.2 Compute path

```
intraday_factor_generator (NEW; mirror core/factors/factor_generator.py
  but operates on 60m panel, lookback windows in 60m bars)
  ↓
intraday_miner (NEW; mirror core/mining/research_miner.py; FAMILIES_INTRADAY
  contains intraday-specific factor families)
  ↓
deferred-execution × BacktestEngine integration (PREREQ; ~1 week)
  ↓
Track A acceptance (same evaluator; runs on intraday strategy NAV
  series same way as cycle04-08 daily)
```

### 4.3 Sealed OOS discipline

Per [[feedback_temporal_split_discipline]]:
- Train years 2009-2017 + 2020 + 2022 + 2024 → factor IC / strategy
  build
- Validation 2018/19/21/23/25 → Track A acceptance evaluator (one-shot
  per nominee)
- Sealed 2026 → reserved for promotion eval only after Track A pass
  + forward-soak healthy

---

## §5 Engineering decomposition

**Estimate: 2-3 weeks wall-clock** (assumes deferred-execution ×
BacktestEngine integration is 1 of the 3 weeks; if already shipped
post cycle #09 fire, 2 weeks suffices).

| Week | Work | Tests | Deliverable |
|---|---|---|---|
| 1 | `IntradayReversalStrategy` class + 60m factor compute path + intraday miner | 30-50 unit tests | Strategy runs on smoke 5-sym 60m panel |
| 2 | deferred-execution × BacktestEngine integration (covers signal-conf MVP too — Family Q strategies need same plumbing) | M11a/M11b parity regression tests | Backtest produces same NAV as M11b reference on smoke |
| 3 | Validation + Track A acceptance pack + anti-sibling NAV measurement vs RCMv1/Cand-2/Trial9/(cycle #09 nominee) | acceptance pack + cross-cycle nav correlation | Closeout memo: PASS / 0-nominee + verdict |

---

## §6 Out of scope (deferred unless user-go)

- 5m / tick-level alpha (PQS data infrastructure doesn't have post-2024
  comprehensive for ETFs; intraday currently 60m primary)
- Options overlay integration (separate sleeve, see options PRD)
- Long-short pairs (violates long-only invariant)
- 15m intraday execution timing (research-only per CLAUDE.md
  multi-timescale framework)

---

## §7 Risk assessment

### 7.1 Strategy-side risks

| Risk | Probability | Mitigation |
|---|---|---|
| Sharpe inflated by survivorship in 30-50 sym universe | Medium | Use same 53-stock + 6-ETF universe as cycle04-08 (PIT membership per universe.yaml; no survivorship) |
| Reversal alpha degraded post-2020 (multiple papers) | Medium-High | Validate 2018/19/21/23/25 separately; require 4/5 positive vs SPY |
| Higher turnover → cost-sensitivity binding | High | Pre-fire 2× cost sensitivity test; reject if 2× cost breaks profitability |
| 60m bar timestamp drift (DST) | Low-Medium | Per R-fwd-2 R8 DST fix lessons: NYSE calendar-aware bar alignment mandatory |
| Bar provenance source transition during validation | Medium | Validate 2.1 step §4.1 (require single source per year per sym) |

### 7.2 System-side risks

| Risk | Probability | Mitigation |
|---|---|---|
| deferred-execution × BacktestEngine integration introduces M11a regression | Medium | Comprehensive parity test suite (sort iteration, signal_date contract, EOD equity correctness — same as M11b ship) |
| 60m miner exhausts mining infra memory (60m panel ~6× daily) | Low | Smoke 5-sym before fleet; pre-allocate memory budget |
| Intraday data source quality lower than daily | Medium | Per-symbol coverage report + reject symbols with > 5% missing 60m bars |

---

## §8 Reversibility

If this PRD ships but the resulting intraday reversal candidate fails
Track A or produces hit but NAV still siblings cycle04-08 candidates:
- **No code rollback needed** — strategy is additive (`IntradayReversalStrategy`
  is a new class, doesn't modify daily-mining path)
- **Discontinuation**: simply stop running it; no production state to
  unwind
- **Sealed panel**: NOT consumed unless Track A acceptance passed
  (sealed eval is single-shot post-acceptance gate)

If this PRD is rejected pre-implementation:
- placeholder file remains for future revisit
- no infrastructure work blocked

---

## §9 Pre-registered acceptance criteria

Immutable once committed with sha256 lock:

```yaml
acceptance_pre_registered:
  freeze_date: <fill_at_fire_time>
  yaml_sha256: <fill_at_fire_time>

  hard_blockers:
    - any_validation_year_maxdd_above_0_20
    - any_stress_slice_maxdd_above_0_25
    - validation_aggregate_excess_vs_spy_le_0  # SPY HARD primary
    - validation_2025_role_hard_gate_failure
    - raw_nav_pearson_vs_existing_anchors_gte_0_85
    - cost_sensitivity_2x_renders_unprofitable

  acceptance_thresholds:
    sharpe_train_min: 0.80
    sharpe_validation_aggregate_min: 0.70
    sharpe_cost_2x_validation_min: 0.50
    raw_nav_pearson_max_pairwise: 0.85
    residual_nav_pearson_max_pairwise: 0.50
    turnover_annual_max: 8.0   # 8x = monthly equivalent
```

---

## §10 Fire trigger logic

- **IF cycle #09 also 0 nominee** → fire alt-archetype A immediately
  (this is the cycle04 pre-committed stop rule pivot direction per
  cycle04 closeout)
- **IF cycle #09 nominee + Trial 9 GREEN** → fire A as 2nd diversifying
  alpha after fleet construction stabilizes
- **IF cycle #09 nominee + Trial 9 RED** → fire A as core_alpha
  replacement candidate (Trial 9 retires; cycle #09 + alt A form
  2-candidate fleet)
- **IF cycle #09 nominee + Trial 9 YELLOW (extend to TD90)** → defer
  alt A by 1 month; reassess at TD90 verdict

In all 4 cases, alt-archetype A is a useful work product because it
EXPANDS the strategy-type space PQS has explored. Per
[[feedback_parallel_alpha_mining_default]], this is base mining
activity that doesn't wait for sequential candidate verdicts.

---

## §11 Open directional questions — LOCKED 2026-05-12

User explicit-go 2026-05-12: "53-stock / 5d / first-60m-close / 2.5bp slip 开 Phase 2"

| Q | Lock | Locked value |
|---|---|---|
| Q1 Universe scope | LOCKED | **53-stock cycle04+ universe** (full PIT membership, exclude cross-asset ETFs; intraday liquidity adequate at this scope) |
| Q2 Holding period upper bound | LOCKED | **5 days hard cap** (cost-sensitivity binding; aligns with PRD §3 design intent) |
| Q3 Entry timing within first 60m | LOCKED | **T+1 first-60m-bar-close (10:30 ET)** (post-opening-noise confirmation; aligns with deferred-execution kernel `execution_delay_bars=1` convention) |
| Q4 Cost model | LOCKED | **2.5bp slip per leg + commission** (intraday turnover ≈ 5-8× daily-rebalance baseline; market-impact premium captured) |

These 4 values are now **immutable for alt-archetype A first-fire**. Wrong-in-hindsight values → new lineage (alt-archetype-intraday-reversal-2026-05-12b) per cycle04-08 immutability precedent. NOT softened post-fire.

**Phase 2 unblocked** as of 2026-05-12.

---

## §12 Authorization markers

- prd: docs/prd/20260512-alt_archetype_intraday_reversal_prd.md (this file)
- depends_on:
  - cycle #09 verdict: INVALID per sampler postmortem; alt-A independent
  - deferred-execution × BacktestEngine integration (~1 week downstream
    work — IN PROGRESS Phase 2 from 2026-05-12)
- user_explicit_go RECEIVED 2026-05-12:
  - §11 4 directional decisions LOCKED (53-stock / 5d / first-60m-close / 2.5bp)
  - Phase 2 START authorized: "53-stock / 5d / first-60m-close / 2.5bp slip 开 Phase 2"
- pending user_explicit_go:
  - sha256 lock-in immutability contract (§9 yaml at fire time, post-Phase-2)
  - first fire authorization (post-Phase-3 Track A acceptance)

---

## §13 Stop-rule chain

If this alt-archetype A ALSO produces 0-nominee:
- THIRD consecutive 0-nominee with broad-factor-broad-construction
  search (cycle08 + cycle09 + alt-A)
- Triggers ALT B (event-driven) consideration —
  `docs/prd/20260512-alt_archetype_event_driven_prd.md`
- Does NOT trigger PQS shutdown; alpha mining base activity continues
  per [[feedback_parallel_alpha_mining_default]]

If alt-archetype A produces nominee + cycle #09 nominee + Trial 9 v2
nominee (all 3 simultaneously surviving):
- 3-candidate fleet construction PRD activated (Phase C-PRD-2 / -3
  per Trial 9 v2 sleeve abstraction)
- Anti-sibling 3-way NAV constraint extended to 4-way: all 3
  candidates pairwise raw NAV < 0.85

---

*End of PRD. Implementation begins ONLY on user explicit-go per §11
+ cycle #09 verdict landing.*
