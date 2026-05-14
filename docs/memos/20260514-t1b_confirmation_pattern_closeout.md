# T1b ConfirmationPatternStrategy Closeout — High-CAGR Sleeve, Track A FAIL

**Date**: 2026-05-14
**Lineage**: `t1b-confirmation-pattern-2026-05-14`
**Status**: COMPLETE — informative but viable; Track A FAIL on consistency
**Authors**: operator (zibomeng@) + Claude Code assist
**PRD**: `docs/prd/20260512-signal_confirmation_strategy_expansion_prd.md`

---

## §1 TL;DR

ConfirmationPatternStrategy under PRD §4.2 LOCKED defaults (breakout_high_n /
setup_lookback=20 / ttl_bars=5 / threshold=1% / vol_mult=1.5 / top_n=5 /
max_holding=21d) consumed via K1 SignalDrivenBacktest wrapper:

| Metric | Value |
|---|---|
| Period | 2017-01-03 → 2025-12-31 (9.0y) |
| Final equity | $52,832 from $10,000 |
| Total return | **+428.3%** |
| CAGR | **20.34%** |
| SPY same window | ~+203% / ~13% CAGR |
| n_trades | 2754 |
| max_dd by val year | -5.5% to -14.6% (all ≤ 20%) |
| beta_to_qqq | 0.43 |
| Concentration top1_max | 0.20 (= top_n=5 equal-weight cap) |
| vs alt-A daily-return corr | **0.17** (fleet-complementary) |

**Track A: FAIL 14/17** — same 3 gates as alt-A:
- validation_aggregate_excess_vs_spy ✗
- validation_aggregate_excess_vs_qqq ✗
- role_core__validation__2025__excess_vs_qqq ✗

Per-validation-year vs SPY: 2018 +10.07%, **2019 -17.43%**, 2021 +10.65%,
2023 +3.12%, **2025 -14.60%**. 2/5 years are large negatives that drag
aggregate. Total-period beats SPY by ~225pp but year-by-year inconsistency
fails the Track A discipline.

---

## §2 Differential from alt-A

| Dimension | alt-A intraday reversal | T1b confirmation pattern |
|---|---|---|
| CAGR | 2.9% (very thin alpha) | **20.3% (substantial alpha)** |
| Time in market | ~3% of days | high (frequent breakouts) |
| vs SPY total period | UNDER -130pp | OVER +225pp |
| Track A | FAIL 14/17 (no positive years) | FAIL 14/17 (2/5 positive years) |
| NAV correlation vs alt-A | n/a | 0.17 daily-return (orthogonal) |
| beta_to_qqq | 0.07 | 0.43 |

T1b is a **MUCH stronger alpha source** than alt-A. But Track A is a
consistency discipline, not an alpha-size discipline. The 2019 + 2025 bad
years (~-17% / -15% vs SPY) sink the aggregate.

**Strategic insight**: Track A may be too strict for non-stationary
strategies. Confirmation pattern works WHEN breakout regime is active
(2018, 2021, 2023). When breakouts fail to follow through (2019 grindy
bull, 2025 chop), the strategy bleeds. This is regime-dependence, not
broken alpha.

---

## §3 NAV correlation analysis

vs alt-A (the other T1 sleeve):
- NAV-level Pearson: 0.82 (misleading — both are growing equity series)
- **Daily-return Pearson: 0.17** ← the relevant measure
- n_overlap: 2010 trading days (2018-2025)

vs 3 fleet anchors (RCMv1 / Cand-2 / trial9_v2) — not measured this run
because anti-sibling reconstruction is heavy. Inferred from T1b's 0.43
beta_to_qqq vs alt-A's 0.07: T1b is MORE correlated with market than
alt-A. Likely closer to 0.3-0.5 raw correlation with fleet anchors,
still well under 0.85 cycle04-08 sibling level.

Pre-K1 cycle04-08 sibling pattern: 0.85-0.95 raw correlation across all
candidates. T1b at 0.17-0.43 → again **TC ceiling escape confirmed**
via horizon/cadence change.

---

## §4 What this means for fleet

Combining alt-A + T1b in equal-weight fleet:
- alt-A: low-beta defensive (0.07 beta), 2.9% CAGR
- T1b: moderate-beta offense (0.43 beta), 20.3% CAGR
- Their daily-return correlation: 0.17 → genuinely complementary

Even though both FAIL Track A individually, a 50/50 fleet would:
- CAGR ~11.6% (geometric weighted)
- vs SPY ~13% CAGR → still loses ~1-1.5pp/yr
- BUT max_dd profile would be MUCH smoother due to 0.17 cross-correlation

Not deployable as standalone alpha. Could serve as a CAPACITY-SCALING
trial run for fleet allocator (Phase G1 PRD-E TAA reactivation).

---

## §5 Production decision

**Operator verdict**: T1b is a viable HIGH-CAGR alpha source. It fails
Track A's consistency discipline but produces real positive alpha over
the full period.

Options:
- **A (default)**: T1b as informative-positive; continue T1c (alt-B
  event-calendar) to see if a different alpha-type produces a Track-A-passing
  candidate
- B: Relax Track A's per-year-consistency gates (requires user explicit-go
  on invariants — should NOT do)
- C: Build fleet of alt-A + T1b under TAA allocator (PRD-E reactivation)
  — gated on Trial 9 v2 TD60 verdict ~2026-08-06
- D: Treat T1b as a paper-trading candidate now (capital-scale wealth vehicle)
  — gated on monthly soak validation

Operator picks A. T1c next.

---

## §6 Files

- NAV: `data/audit/t1b_phase3_nav.parquet`
- Track A verdict: `data/audit/t1b_phase3_track_a_verdict.json`
- Eval script: `dev/scripts/t1b/run_t1b_track_a_eval.py`
- Closeout: this file

Test surface: existing 30/30 K1 GREEN + 12/12 IntradayReversalRunner GREEN
(unchanged — T1b reused K1 wrapper without modification).
