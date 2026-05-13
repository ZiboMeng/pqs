# PRD — Alt-archetype A: Intraday reversal alpha

**Date**: 2026-05-12
**Status**: DESIGN — implementation gated on cycle #09 result or user-go
**Lineage**: `alt-archetype-intraday-reversal-2026-05-12`
**Purpose**: alternative alpha source that does NOT share cycle04-08 daily
monthly cap_aware top-N over 78-stock universe construction. Pure
intraday-driven thesis.

---

## §1 Hypothesis

**Daily rebalance monthly construction is saturated** for the PQS
universe — cycle04-08 5 cycles, ~1000 trials all produced sibling
candidates. Intraday-driven alpha has fundamentally different temporal
signature; can break sibling pattern by being literally a different
time scale.

Empirical foundation:
- Lehmann 1990 weekly reversal: 1d/5d winner -0.35%/-0.55%/week,
  loser +0.86%/+1.24%/week
- Overnight-daytime persistence reversal (Akbas-Boehmer-Jiang-Koch 2022):
  high overnight + low daytime → t+1 reversal
- 2024 momentum 1-year run +28% → 2σ event → 2025 reversal expected
  per Morgan Stanley research

---

## §2 Existing infrastructure leverage

Today's ship gives intraday reversal direct infrastructure:
- `core/signals/signal_state.py` state machine (ARMED → CONFIRMED|EXPIRED)
- `core/signals/strategies/confirmation_pattern.py` strategy class
  supporting volume_gate_same_bar + breakout_high_n + TTL window
- 5 multi-bar factors (`breakout_signal_age_5d`,
  `time_since_arm_bars`, `volume_surge_ratio_at_setup`,
  `confirmation_strength`, `retest_proximity_pct`)
- weekly_reversal_signal_5d factor in Bucket A (Lehmann-style)
- volume_surge_when_flat (stealth accumulation gate)
- chaikin_money_flow_20d / obv_norm_20d (accumulation/distribution)

Still missing for true intraday reversal:
- 60m bar ingest (existing — `data/intraday/1m/<sym>.parquet` aggregate to 60m)
- Multi-timescale framework (existing — `core/intraday/multi_timescale.py`
  already ships `decide_timing(ctx, ...)` with 60m/30m/15m/5m roles)
- Daily-only mining doesn't reach intraday alpha

---

## §3 Design

**Strategy class**: `IntradayReversalStrategy`
- Universe: 30-50 most liquid stocks from existing PQS pool (filter via
  dollar_vol_20d top quantile)
- Cadence: daily rebalance, holding period 1-5 days
- Setup detection: weekly reversal signal (`weekly_reversal_signal_5d`
  ≤ 5th percentile) + low overnight gap noise filter
- Confirmation: intraday volume + early-session price action confirms
  reversal direction within first 60m of trading day
- Sizing: equal-weight top-N (3-5), small per-position because rapid turnover

**Backtest extension** (depends on PRD-20260512-signal_confirmation §4.1
deferred-execution implementation):
- T-day setup → T+1 morning confirmation → T+1 open-or-early fill
- Holding 1-5 days
- M11a/M11b paper-BT parity preservation

**Acceptance**:
- Track A acceptance per temporal_split_v2 (5 validation years 2018/19/21/23/25)
- Per-year max_dd ≤ 20%; stress slice ≤ 25%
- Pairwise raw NAV corr < 0.85 vs (RCMv1, Cand-2, Trial 9, cycle #09 candidate)
- Cost sensitivity 2× — must still profitable

**Engineering estimate**: 2-3 weeks
- Week 1: IntradayReversalStrategy class + multi-bar factor integration
- Week 2: Backtest deferred-execution extension (covers signal-conf MVP too)
- Week 3: Validation + acceptance pack

---

## §4 Out of scope (deferred unless user-go)

- 5m / tick-level alpha (PQS data infrastructure doesn't have post-2024
  for ETFs; intraday currently 60m)
- Options overlay (separate sleeve)
- Long-short pairs (violates long-only invariant)

---

## §5 Fire trigger

- IF cycle #09 also 0 nominee → fire alt-archetype A immediately
- IF cycle #09 nominee + fleet healthy → fire A as 2nd diversifying alpha
- IF Trial 9 RED → fire A as core_alpha replacement candidate

In all 3 cases, alt-archetype A is a useful work product.
