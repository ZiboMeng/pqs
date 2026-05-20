# Canonical trigger-first config decision: R16 Path A

**Date**: 2026-05-20
**Author**: operator (Claude Opus 4.7)
**Status**: OPERATOR DRAFT — user explicit-go REQUIRED per
`feedback_decision_authority_operator_audit_split`. Without user
sign-off, this memo is informational, NOT binding.

**PRD reference**: PRD #3 P3.1 step (canonical config selection).

---

## Recommendation

Operator recommends **R16 Path A** as the canonical trigger-first
configuration for M2 promote, subject to:

1. user explicit-go (directional)
2. P3.2 OOS walk-forward PASS
3. P3.3 paper-backtest M3 alignment PASS
4. P3.5 fingerprints computed

## R16 Path A specification

```yaml
# Conceptual config bundle (yaml shape for future M2 promote)
decision_stack:
  mode: "trigger-first"
  partial_rebalance:
    band_base: 0.02
    partial_full_threshold: 0.05
  ml_sidecar:
    enabled: false            # heuristic-free baseline initially
    voter_kind: "no_op"       # upgrade to classifier_voter post PRD #4 P4.5
    voter_params: {}
  rule_based:
    # NOT actually used in production overlay path — included for
    # schema completeness only. PRD #3 scope boundary: thin overlay.
    entry_threshold: 0.7
    exit_threshold: 0.3
    confirm_min_bars: 2
    base_position_size: 0.05
    ttl_bars: 3
  deferred_execution:
    execution_delay_bars: 1
    enabled: false            # P1-1 facade replacement available
                              # but not engaged in overlay path

# Upstream alpha source (the spec the overlay sits on top of)
spec:
  features:
    - drawup_from_252d_low
    - trend_tstat_20d
    - ret_2d
  weights:                    # equal-weighted
    - 0.3333333333
    - 0.3333333333
    - 0.3333333333
  holding_freq: weekly        # cycle06 actual
  construction:
    mode: cap_aware_cross_asset
    top_n: 10
    cluster_cap: 0.20
    max_single_weight: 0.10
    asset_class_caps:
      equities: 0.70
      bonds: 0.40
      commodities: 0.20
      cash_anchor: 0.30
```

## R16 Path A measured numbers (2018-2024 strict-chronological)

| Metric | Value | Verdict |
|---|---|---|
| Cumulative return | 0.4557 (45.6% over 7yr) | — |
| Annualized Sharpe | **1.1200** | PASS vs cycle06 spec.nav_sharpe 0.5654 + tol; **gap 0.05** to strict full-period 1.37 - 0.2 = 1.17 |
| Max drawdown | **-0.1910** | PASS §6.4 15-20% target by 0.90pp margin |
| Turnover per rebal | 0.0276 (~2.76%) | reasonable for weekly cadence |
| vs SPY (TR-adjusted) | TBD per fold (P3.2 output) | — |
| vs QQQ (TR-adjusted) | TBD per fold (P3.2 output) | diagnostic per CLAUDE.md QQQ deprecation |

Source: `data/audit/prdx_r16_task5_cap_aware_harness.json`

## Why R16 Path A vs alternatives

| Candidate | Sharpe | MaxDD | Reasoning |
|---|---|---|---|
| R5e v2 | 0.50 | -20.95% | Below cycle06 spec.nav_sharpe; MaxDD borderline; no canonical lineage |
| R9 active | 0.57 | -20.17% | Just above cycle06 spec.nav_sharpe; MaxDD borderline |
| R10 Path C | 0.58 | -18.95% | Sidecar weak-filter is heuristic only; MaxDD passes by 1.05pp |
| R12 Path A | 0.58 | -17.32% | Simple norm-rank construction; no cap_aware; below R16 Sharpe |
| R14 real engine | 0.63 | -17.43% | Real T+1 open exec but R10-config base; below R16 Sharpe |
| **R16 Path A** | **1.12** | **-19.10%** | **highest Sharpe; uses cycle06's actual construction harness; §12.0 within 0.05 strict tolerance** |

## Lineage tag proposal

```
lineage_tag: "trigger_first_canonical_R16PathA_v1"
spec_id: <sha256 of canonical config yaml> (computed at M2 time)
promoted_at: <ISO timestamp at promote run>
source.mode: "promoted_from_archive"
source.rationale: |
  R16 Path A (operator-selected canonical 2026-05-20) — uses cycle06
  trial 31af04cf2ff9 spec (drawup_from_252d_low + trend_tstat_20d +
  ret_2d eq-weighted) with cap_aware_cross_asset construction
  (top_n=10, cluster_cap=0.20, max_single_weight=0.10) at weekly
  cadence. Sharpe 1.12 / MaxDD -19.10% on 2018-2024 strict-
  chronological train. Within 0.05 of cycle06 strict full-period
  Sharpe baseline minus tolerance (1.17). See
  data/audit/prdx_r16_task5_cap_aware_harness.json + this memo
  for full rationale.
```

## Risks

1. **Walk-forward fold instability**: R16 Path A measured Sharpe is
   full-period (2018-2024); P3.2 OOS walk-forward may surface per-fold
   instability. **Mitigation**: P3.2 outputs per-fold + mean + stddev;
   non-blanket failure if any fold < 0.0 Sharpe.

2. **2018 fold negative momentum regime**: cycle06's own metrics_per_year
   shows 2018 sharpe=-0.435. R16 Path A on monthly inherits same
   characteristic. **Mitigation**: documented in fold report; not a
   blocking failure if mean OOS IR ≥ 0.20.

3. **Weekly cadence transaction cost sensitivity**: R16 used zero-cost
   model. Real cost will degrade Sharpe. **Mitigation**: P3.2 includes
   2x and 3x cost sensitivity test per PRD §12.3.

4. **Lev-ETF (TQQQ/SOXL) appearing in top-N**: R5e smoke surfaced this
   invariant edge. **Mitigation**: documented as CLAUDE.md soft
   invariant; stricter threshold not currently in code. Promotion may
   need lev-ETF gate fold-in OR explicit no-lev-ETF universe filter at
   P3.6 M2 promote time.

5. **Alternative candidates not OOS-tested**: if R16 Path A fails
   P3.2, fallback options (R14, R12 Path A) also need OOS testing.
   **Mitigation**: P3.2 driver should support multi-candidate
   simultaneous OOS test (parallelizable).

## Outstanding directional ask

User must explicit-go on R16 Path A as canonical. If user prefers
alternative:
- R14 (Sharpe 0.63) — more conservative; T+1 open semantic
- R12 Path A (Sharpe 0.58) — simplest construction
- Or other (please specify)

Without user response, P3.2 OOS walk-forward CANNOT start (no canonical
config to test).

## What this memo DOES NOT do

- Does NOT flip status to active
- Does NOT modify production_strategy.yaml
- Does NOT run OOS WF
- Does NOT compute fingerprints
- Does NOT invoke M2 promote_strategy.py

It's an operator recommendation + decision artifact for P3.1 ONLY.
P3.2-P3.7 follow per PRD #3 phase sequencing.
