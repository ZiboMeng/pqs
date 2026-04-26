# Concentration report — rcm_v1_defensive_composite_01

**concentration_gate_status**: `manual_review_required`
**narrative_permission**: `frozen`

## Metrics

- top-1 max weight: 10.00%
- top-3 max weight: 30.00%
- top-5 max weight: 50.00%
- distinct names held: 38
- max single-name weight-day share: 9.63%
- watch-list single-name max share: 9.63%
- watch-list total share: 57.73%
- thin-data WEIGHTED share (gate metric): 14.97%
- thin-data binary share (diagnostic, pre-2026-04-25 definition): 56.86%

## Tier classification (PRD v3 §C)

Triggered warnings:
  - thin_data_weighted_share=0.1497>0.05
  - watch_single_share=0.0963>=0.08

Triggered extremes:
  - thin_data_weighted_share=0.1497>0.1

## Sector concentration

- top sector: `Factor / Multi-sector ETF` (21.28%)
- block-for-review (top > 50%): **no**
- unknown-sector symbols: 0

Per-sector weight-day shares:
  - Factor / Multi-sector ETF: 21.28%
  - Information Technology: 19.30%
  - Consumer Discretionary: 12.93%
  - Leveraged ETF: 11.40%
  - Consumer Staples: 7.85%
  - Financials: 7.85%
  - Health Care: 6.12%
  - Communication Services: 4.21%
  - Energy: 3.06%
  - Materials: 2.60%
  - Industrials: 1.57%
  - Real Estate: 1.16%
  - Commodity: 0.41%
  - Treasury / Bond: 0.25%

## Benchmark beta concentration

- portfolio-weighted mean β: 1.718
- portfolio-weighted std β: 1.672
- max |per-symbol β|: 6.261
- n symbols with β: 36

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
