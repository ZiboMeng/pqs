# Concentration report — research-cycle-2026-04-26-01_S1_nominee

**concentration_gate_status**: `warning`
**narrative_permission**: `allowed`

## Metrics

- top-1 max weight: 10.00%
- top-3 max weight: 30.00%
- top-5 max weight: 50.00%
- distinct names held: 60
- max single-name weight-day share: 9.08%
- watch-list single-name max share: 8.62%
- watch-list total share: 39.50%
- thin-data WEIGHTED share (gate metric): 7.51%
- thin-data binary share (diagnostic, pre-2026-04-25 definition): 38.67%

## Tier classification (PRD v3 §C)

Triggered warnings:
  - thin_data_weighted_share=0.0751>0.05
  - watch_single_share=0.0862>=0.08

Triggered extremes:
  - (none)

## Sector concentration

- top sector: `Information Technology` (34.12%)
- block-for-review (top > 50%): **no**
- unknown-sector symbols: 0

Per-sector weight-day shares:
  - Information Technology: 34.12%
  - Leveraged ETF: 14.11%
  - Energy: 10.28%
  - Industrials: 10.13%
  - Financials: 8.16%
  - Health Care: 6.32%
  - Consumer Discretionary: 5.75%
  - Communication Services: 3.88%
  - Factor / Multi-sector ETF: 2.54%
  - Real Estate: 1.51%
  - Consumer Staples: 1.42%
  - Utilities: 0.83%
  - Materials: 0.73%
  - Commodity: 0.22%

## Benchmark beta concentration

- portfolio-weighted mean β: 1.720
- portfolio-weighted std β: 1.138
- max |per-symbol β|: 4.878
- n symbols with β: 56

_(Report-only — PRD v3 §C lists the dimension but does not specify numeric thresholds; tier classification is unchanged.)_

## Caveats

- This report is **read-only**: it never auto-blocks or auto-revokes
  a candidate. `manual_review_required` freezes narrative permission
  but does not stop further paper runs.
- Sector concentration: warning when top-sector > 50% weight-days
  (block-for-review label per PRD v3 §C line 287). This label is
  separate from the warning/extreme tier and does NOT freeze
  narrative permission; it surfaces a candidate for explicit
  sector-exposure review by the user.
- Benchmark beta concentration is REPORT-ONLY (no automatic tier).
  PRD v3 §C lists it as a dimension but specifies no numeric
  thresholds; statistics are surfaced for visual review.
- **Thin-data metric semantics (post-MVP audit fix 2026-04-25)**:
  the gate uses `thin_data_weighted_share` =
  Σ weight_day_share[s] × thin_data_pct[s], which honestly
  measures how much of the candidate's PnL depends on thin-data
  bars. The legacy `thin_data_binary_share` (any-thin-history
  flag × full weight) is kept for diagnostic continuity but
  systematically over-counts; it does NOT participate in tier
  classification anymore. See
  `docs/memos/20260425-m12_review_decision.md`.
