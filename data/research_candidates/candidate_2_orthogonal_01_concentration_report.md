# Concentration report — candidate_2_orthogonal_01

**concentration_gate_status**: `warning`
**narrative_permission**: `allowed`

## Metrics

- top-1 max weight: 10.00%
- top-3 max weight: 30.00%
- top-5 max weight: 50.00%
- distinct names held: 57
- max single-name weight-day share: 9.26%
- watch-list single-name max share: 9.26%
- watch-list total share: 31.07%
- thin-data WEIGHTED share (gate metric): 5.19%
- thin-data binary share (diagnostic, pre-2026-04-25 definition): 28.48%

## Tier classification (PRD v3 §C)

Triggered warnings:
  - thin_data_weighted_share=0.0519>0.05
  - watch_single_share=0.0926>=0.08

Triggered extremes:
  - (none)

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
