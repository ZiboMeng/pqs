# PRD — Alt-archetype B: Event-driven alpha (FOMC / earnings / CPI)

**Date**: 2026-05-12
**Status**: DESIGN
**Lineage**: `alt-archetype-event-driven-2026-05-12`

---

## §1 Hypothesis

Event windows have systematic predictable abnormal returns:
- Pre-FOMC drift: ~50% of post-1994 excess market returns occur in
  ±2 trading days around FOMC (NY Fed sr512)
- CPI / NFP release-day abnormal volatility (BIS WP 1079)
- Earnings PEAD: Garfinkel-Hribar-Hsiao 2024 SUE LS 5.1%/3mo (~20%/yr)
  + GenAI may compress window per CFA Institute 2025

Event-driven alpha is structurally orthogonal to cycle04-08 monthly
top-N continuation — completely different temporal signature.

---

## §2 Existing infrastructure leverage

- 4 macro event window factors shipped Round D 2026-05-12:
  pre_fomc_window_flag / post_fomc_window_flag / pre_cpi / pre_nfp
- `config/macro_event_calendar.yaml` overrideable
- For earnings PEAD: requires per-symbol earnings calendar
  (yfinance partial 5-6 yr; SEC EDGAR Form 8-K for actual but no
  consensus)

---

## §3 Design — two cycles

**Cycle E1: Pre-FOMC drift cycle**
- Universe: liquid US equities (~30 syms top dollar vol)
- Strategy: long top-N (3-5) most-momentum stocks 2 days before each
  FOMC; close position FOMC day +1 or +3
- Acceptance: per-FOMC event return, sign rate, cost-adjusted Sharpe
  - Requires ≥ 100 events (achievable: ~144 FOMC since 2009)

**Cycle E2: Earnings PEAD cycle**
- Universe: filter to most-likely-PEAD candidates (mid-cap + high SUE
  + high investor attention proxy)
- Strategy: long top-N positive-SUE stocks for 5-20 day post-earnings
  window
- Acceptance: per-event return × 100s of events
- Dependency: needs earnings calendar (yfinance fallback OK for 2019+)

**Engineering estimate**:
- E1: 1-2 weeks (FOMC calendar manually curate from federalreserve.gov;
  strategy class + 21d backtest)
- E2: 2-3 weeks (earnings calendar ingest + SUE proxy +
  attention factor + PEAD backtest)

---

## §4 Acceptance criteria

Pure event-driven alpha has different acceptance regime:
- Per-event Sharpe ≥ 0.5 (annualized via sqrt(#events/year))
- No look-ahead via filed_date PIT
- Cost sensitivity (event windows = high turnover)
- Pairwise NAV correlation < 0.85 vs (RCMv1, Cand-2, Trial 9,
  cycle #09 candidate, alt-A intraday) — 5-way constraint as fleet grows

---

## §5 Fire trigger

- E1 (FOMC) can fire IMMEDIATELY — minimal data dependency, just need
  FOMC calendar yaml curation
- E2 (PEAD) gated on earnings calendar ingest pipeline

Recommended sequence: cycle #09 first (uses today's 95 new factors,
no new data), then E1 (FOMC, fast), then alt-A intraday (heavier),
then E2 (PEAD, needs earnings data).
