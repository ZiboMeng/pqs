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
- thin-data total share: 56.86%

## Tier classification (PRD v3 §C)

Triggered warnings:
  - thin_data_share=0.5686>0.05
  - watch_single_share=0.0963>=0.08

Triggered extremes:
  - thin_data_share=0.5686>0.1

## Caveats

- This report is **read-only**: it never auto-blocks or auto-revokes
  a candidate. `manual_review_required` freezes narrative permission
  but does not stop further paper runs.
- Sector + benchmark-beta concentration are not computed in this MVP
  (no per-symbol sector mapping wired); both are marked
  `not_computed` in the JSON. Neither participates in tier
  classification per PRD v3 §C extreme thresholds.
