# Closeout — trial9_diversifier_001

**Date**: 2026-05-12
**Status**: completed_fail (v2.1 revalidate bound_only)
**Successor**: `trial9_diversifier_002` (PRD 20260512 opt-in,
start_date 2026-05-13)

---

## What happened

`trial9_diversifier_001` initialized 2026-05-04 per Two-Stage
Allocation Architecture PRD Phase C-PRD-1 + diversifier role decision
memo 2026-05-01. Daily forward observations TD001-TD004 recorded
between 2026-05-04 and 2026-05-07 with healthy diversifier signal:

| TD | as_of | cum_ret | vs_spy | vs_qqq | max_dd |
|---|---|---|---|---|---|
| TD001 | 2026-05-04 | 0.00% | — | — | 0.00% |
| TD002 | 2026-05-05 | +3.60% | +2.80% | +2.31% | 0.00% |
| TD003 | 2026-05-06 | +8.02% | +5.82% | +4.62% | 0.00% |
| TD004 | 2026-05-07 | +5.04% | +3.15% | +1.76% | -2.75% |

The 2026-05-12 daily-ritual `observe()` triggered v2.1
`revalidate_manifest` and surfaced retroactive yfinance refresh events
on all 4 TDs (typical sub-bps NAV impact on a few held syms each TD).
Three of four TDs (TD001-TD003) classified `flagged_only` /
`in_ring` — normal yfinance behavior, no halt.

TD004 classified `invalidated` / `bound_only` with trigger:

> `bound_only (signal_input scope diff with empty per_cell_digest
> (track_per_cell=False) — cannot prove diff is subset of execution_nav-
> anchored cells; conservative bound_only per PRD §4.4 (codex Round-10
> Blocker 2))`

The manifest flipped to `requires_data_review`.

## Root cause investigation (2026-05-12)

Per CLAUDE.md feedback memory `self_audit_methodology.md` R3 — code
execution + numeric verification — diagnostic on `data/audit/`
verified:

1. **Anchor coverage check**: 18 held syms × 10 ring dates × close
   values from `execution_nav.materiality_anchor_values` against
   current panel close → **0 diff revealed** (anchor and current
   panel close prices match exactly within the held×ring region)
2. **signal_input re-hash**: re-computed signal_input hash with
   `track_per_cell=True` against current panel → still differs from
   stored hash
3. **Conclusion**: the revised close cell is OUTSIDE the execution_nav
   anchor coverage region (i.e., a non-held sym OR a date older than
   the 10-day ring start of 2026-04-24). No retroactive reconstruction
   path exists for this case because the original signal_input
   `per_cell_digest` was empty (production default `track_per_cell=False`).

This is exactly the case codex R10 Blocker 2 was designed to fail-closed
on: when signal_input scope cannot be cell-attributed AND execution_nav
anchor cannot prove containment, the conservative classification is
`bound_only`. The gate worked as specified.

## Why `recover` doesn't help

`recover` re-evaluates the existing event under current policy. With
the stored `per_cell_digest` empty, the cell-level diff path
(`revalidate.py:429-444`) has no data and falls through to the
empty-digest fail-closed branch. No exemption rule can salvage this
without either (a) retroactive synthetic reconstruction that requires
data we don't have, or (b) a magnitude-bounded heuristic that
post-hoc fits the specific TD004 drift value.

Both routes were considered in self-audit on 2026-05-12 and rejected
in favor of (c) structural fix via opt-in `track_signal_input_per_cell`
for the successor candidate.

## Closeout decision

`decide --status completed_fail` with notes pointing to:
- This memo
- `docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md`
  (the structural fix)
- `data/research_candidates/trial9_diversifier_002.yaml` (the successor)

The 4 forward TDs are preserved in the manifest as forensic evidence
of the failure mode + as a baseline NAV trajectory for cross-check
against `trial9_diversifier_002` (same composite, identical universe,
different freeze_date).

## Successor: trial9_diversifier_002

- candidate_id: `trial9_diversifier_002`
- spec_path: `data/research_candidates/trial9_diversifier_002.yaml`
- factors: `beta_spy_60d + max_dd_126d + ret_1d` (identical to v1)
- construction: cap_aware_cross_asset monthly top-10 (identical to v1)
- evidence_config: `track_signal_input_per_cell: true` (NEW)
- start_date: 2026-05-13 (next trading day after closeout)
- soft_warn_flags: `['diversifier_2025_maxdd_18_20pct']` (mirrored)
- TD60 decision point: ~2026-08-06 (1 week slip from v1's ~2026-07-30)

## What the operator owes future-self

- Daily ritual on trial9_002 same shape as trial9_001 was;
  `dev/scripts/oos_mvp/run_forward_observe.py observe --candidate-id trial9_diversifier_002`
- Forward observation expected to NOT trip bound_only on signal_input
  scope drift events (cell-level diff path now active)
- Storage budget actual measurement: spot-check
  `trial9_diversifier_002_forward_manifest.json` size at TD030 vs
  TD060 to validate the ~10 MB / 60-TD projection in PRD 20260512 §5

## Cross-references

- PRD: `docs/prd/20260512-per_candidate_track_signal_input_per_cell_prd.md`
- v1 init memo: `docs/memos/20260501-diversifier_role_decision.md`
- v1 forward manifest (preserved): `data/research_candidates/trial9_diversifier_001_forward_manifest.json`
- Two-stage allocation PRD: `docs/prd/20260501-two_stage_allocation_architecture_prd.md`
