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

## Caveats

- This report is **read-only**: it never auto-blocks or auto-revokes
  a candidate. `manual_review_required` freezes narrative permission
  but does not stop further paper runs.
- Sector + benchmark-beta concentration are not computed in this MVP
  (no per-symbol sector mapping wired); both are marked
  `not_computed` in the JSON. Neither participates in tier
  classification per PRD v3 §C extreme thresholds.
- **Thin-data metric semantics (post-MVP audit fix 2026-04-25)**:
  the gate uses `thin_data_weighted_share` =
  Σ weight_day_share[s] × thin_data_pct[s], which honestly
  measures how much of the candidate's PnL depends on thin-data
  bars. The legacy `thin_data_binary_share` (any-thin-history
  flag × full weight) is kept for diagnostic continuity but
  systematically over-counts; it does NOT participate in tier
  classification anymore. See
  `docs/memos/20260425-m12_review_decision.md`.
