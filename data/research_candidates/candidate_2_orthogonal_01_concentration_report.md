# Concentration report — candidate_2_orthogonal_01

**concentration_gate_status**: `manual_review_required`
**narrative_permission**: `frozen`

## Metrics

- top-1 max weight: 10.00%
- top-3 max weight: 30.00%
- top-5 max weight: 50.00%
- distinct names held: 57
- max single-name weight-day share: 9.26%
- watch-list single-name max share: 9.26%
- watch-list total share: 31.07%
- thin-data total share: 28.48%

## Tier classification (PRD v3 §C)

Triggered warnings:
  - thin_data_share=0.2848>0.05
  - watch_single_share=0.0926>=0.08

Triggered extremes:
  - thin_data_share=0.2848>0.1

## Caveats

- This report is **read-only**: it never auto-blocks or auto-revokes
  a candidate. `manual_review_required` freezes narrative permission
  but does not stop further paper runs.
- Sector + benchmark-beta concentration are not computed in this MVP
  (no per-symbol sector mapping wired); both are marked
  `not_computed` in the JSON. Neither participates in tier
  classification per PRD v3 §C extreme thresholds.
