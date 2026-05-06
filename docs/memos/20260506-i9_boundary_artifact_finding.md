# I9 Boundary Artifact Finding — Train-Year Gap-Return Masking

**Date**: 2026-05-06
**Operator**: zibomeng (Claude Opus 4.7)
**Authority**: PRD-AC v1.1 §6 Phase 2 step 4 (I9 boundary verify);
operator tactical decision (no directional change to PRD)
**Lineage**: `mining-objective-nav-2026-05-05`

## TL;DR

Phase 2 round 2 I9 verification on cycle #04 (`track-c-cycle-2026-05-01-04`)
top-1 trial `ddc2896f9d8e` exposed a **+10.36% NAV jump** at the
2022-12-31 → 2024-01-02 boundary on the `partition_for_role(role="miner")`
panel. Root-caused, fixed in `core/mining/nav_objective.py
::recompute_nav_metrics_train_only`, unit-tested + script-verified.

Verdict: **PASS_WITH_WARNINGS** (masked metrics healthy; raw
boundary-day jumps surfaced informationally, not used in objective).

## Empirical evidence

`data/audit/i9_boundary_verify_track-c-cycle-2026-05-01-04_ddc2896f9d8e.json`:

| Boundary | Gap | Day-over-day return |
|---|---|---|
| 2017-12-30 → 2020-01-01 | 732d (2 yrs) | -0.0000% (clean) |
| 2020-12-31 → 2022-01-01 | 366d (1 yr)  | +0.0000% (clean) |
| 2022-12-31 → 2024-01-02 | 367d (1 yr)  | **+10.3593%** (dirty) |

Pre-fix metrics on raw NAV: `sharpe=1.0083  max_dd=-19.35%  vs_qqq=+1.7653`
Post-fix metrics (boundary returns masked):
`sharpe=0.9740  max_dd=-19.35%  vs_qqq=+4.6061`

Wall-clock per trial: median **19.36s** over 5 archived top trials
(p95 19.86s); ≤ 20s PRD §6 Phase 2 target. Phase 4 200-trial smoke
estimate **64.5 min** mining wall-clock.

## Root cause

`partition_for_role(role="miner")` returns a non-contiguous train-only
panel per `config/temporal_split.yaml::alternating_regime_holdout_v1`
train years = 2009-2017+2020/2022/2024. The harness BacktestEngine
carries forward EOD positions across the gap; `nav.pct_change()` then
computes a return between adjacent index dates — which represents a
full-validation-year hold return, NOT an in-train alpha return.

For 2022-12-31 → 2024-01-02 (1-year gap across 2023 validation), the
spec's positions held at 2022 EOY happened to gain 10.36% by the next
in-train day (2024-01-02). Including this in NAV-Sharpe falsely
rewards specs whose 2022 EOY portfolios got lucky in 2023.

The 2-year 2017-12-30 → 2020-01-01 gap shows clean ~0% — likely
because the spec's 2017 EOY positions had a turnover-by-rebalance
event AT the 2020-01-01 entry day so the return was offset against
new positions (or the harness's monthly rebalance mask resets
positions on the first day of new segment). Only the 2022→2024 path
shows the artifact in this trial; this asymmetry suggests the issue
is path-dependent on rebalance cadence / spec position turnover, not
a guaranteed jump per boundary.

## Why v1_legacy never surfaced this

Cycle #04 v1_legacy IC-only objective ran `evaluate_composite` on
factor panel × forward-return panel with no NAV path. IC is computed
per-date as Spearman rank correlation of composite signal vs forward
return; gap days are excluded by `dropna()` on the return panel
(forward returns at end of segments are NaN since there's no in-train
horizon to look forward to). So v1_legacy ranking is unaffected.

PRD-AC v1.1 v2_nav_based objective runs the harness backtest end-to-end
and consumes `metrics_full_period.sharpe / max_dd / vs_qqq` — these
ARE affected by gap returns. New concern; new fix.

## Fix

`core/mining/nav_objective.py`:

1. `mask_train_boundary_returns(daily_returns, gap_threshold_days=30)`:
   zero out returns at days where the prior trading day is more than
   30 calendar days earlier. Holiday-week gaps (≤30 days) preserved.

2. `recompute_nav_metrics_train_only(daily_returns, qqq_series)`:
   wraps the masking + Sharpe / max_dd / vs_qqq recomputation. Both
   spec AND QQQ legs are masked at the same boundary days for
   consistency.

3. `core/mining/research_miner.py::evaluate_composite` NAV path now
   uses `recompute_nav_metrics_train_only` in lieu of harness's raw
   `metrics_full_period` for the four NAV fields stamped into
   `CompositeMetrics`.

4. `compute_spec_residual_pooled_raw_correlation` input is
   pre-masked spec returns so the orthogonality computation is
   train-only.

## Why this is "real" not "artifact"

The 10.36% return is mathematically correct: positions held from
2022-12-31 to 2024-01-02 actually gained 10.36% if you held them
unrebalanced for 13 months. The "artifact" framing applies to the
mining objective: we're trying to select specs that work in train
years, not specs that lucked into good 2023 holdings.

After masking, the spec's NAV trajectory shows in-train returns only;
the gap days contribute zero. This is the PRD-aligned behavior.

## Phase 4 implications

- Median per-trial NAV-path elapsed = 19.36s (PRD R3-AC-1 ~15-22s
  estimate confirmed). 200-trial smoke estimate **~65 min** wall-clock.
- Phase 4 anchor calibration smoke (50 trials × 4 λ values = 200
  trial-equivalents) = ~65 min.
- 200-trial v2_nav_based smoke on cycle04 yaml clone = ~65 min.
- cycle #06 dry-run mining = ~65 min.
- Total Phase 4 mining wall-clock: ~3.5 hours.

## Audit trail

- I9 dev script: `dev/scripts/cycle06/i9_boundary_verify.py`
- Wall-clock benchmark: `dev/scripts/cycle06/wall_clock_benchmark.py`
- Mask helpers + tests: `core/mining/nav_objective.py` +
  `tests/unit/mining/test_nav_objective.py` (5 new tests)
- Audit JSON outputs:
  `data/audit/i9_boundary_verify_track-c-cycle-2026-05-01-04_ddc2896f9d8e.json`
  `data/audit/wall_clock_benchmark_track-c-cycle-2026-05-01-04.json`

## Reversibility

If `recompute_nav_metrics_train_only` over-masks (e.g. user wants
to see raw harness metrics), the fix is reversible:
- Pass `compute_nav=False` → v1_legacy path, no NAV computation
- Set `gap_threshold_days=99999` → mask never triggers
- Delete the `recomputed = ...` block in `evaluate_composite` → reverts
  to pre-mask `metrics_full_period.sharpe/max_dd/vs_qqq`

No data destruction; cycle04/05 archive untouched (they're v1_legacy
IC-only, never consumed NAV metrics).
