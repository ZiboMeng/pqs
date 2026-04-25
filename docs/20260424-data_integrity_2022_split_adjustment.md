# Pre-2022-Aug Split-Adjustment Data Integrity Issue

> **Status update (2026-04-25): RESOLVED in round-3 step 3b.** This
> memo's narrative diagnosis (TSLA / GOOGL mixed-adjustment in
> 2022-Q1 / 2020 windows) was correct as far as it went. The
> data-integrity workstream subsequently traced the broader root
> cause (multi-source ingest cascade with no scale / label
> reconciliation) and rebuilt `data/daily/<sym>.parquet` from
> polygon 1m as the single canonical source on 2026-04-25. The
> alternation pattern in TSLA / GOOGL / TJX history is gone in the
> rebuilt store. The window-selection rationale (use 2022-08-26
> through 2022-12-15 for the bear cell) remains the canonical
> choice but for the further reason that in pre-step-3b state
> those were the contiguous "clean" windows.
> See `docs/memos/20260425-data_integrity_round3_step3b_complete.md`.

**Date**: 2026-04-24
**Status**: parked as a separate data-integrity issue; not on the parallel
paper main line.
**Affected files**: `core/data/bar_store.py` (read path) + underlying
parquet bars for some/all symbols in any window that ENDS before a
major split's effective date.

**Scope summary**:
- ❌ **2020-01-02 → 2020-04-22 (COVID bear)**: contaminated (TSLA + GOOGL
  mixed-adjusted)
- ❌ **2022-01-03 → 2022-04-22 (Q1 bear)**: contaminated (TSLA mixed-
  adjusted)
- ✅ **2022-08-26 → 2022-12-15 (Q4 bear)**: clean — selected as the
  current bear cross-regime window
- ✅ **2024-01-02 → 2024-04-19 (current up-tape)**: clean — already
  analyzed in checkpoints 10d/20d/40d/60d

## Background

The parallel-paper plan called for a cross-regime rerun: same frozen
candidates (`rcm_v1_defensive_composite_01` + `candidate_2_orthogonal_01`),
same universe (79 tradable), same pipeline, only the time window swapped
to a 2022 bear segment to test whether the day-60 day-tape-only finding
("Cand-2 dominates, RCMv1's defensive overlay underused") still holds in
risk-off conditions.

Window selected: **2022-01-03 → 2022-04-22** (75 real trading days). Both
candidates were run on this window via `scripts/run_paper_candidate.py`
without any spec / pipeline / universe modification.

## What went wrong

Candidate-2's `pnl_daily.csv` reported a **+190.95% single-day return on
2022-04-01**, with a final equity of $940,309 from a $100,000 initial
capital. RCMv1 reported much milder but still suspect numbers (final
equity $53,750, 11 days with |daily return| > 10%).

Investigation traced the +190.95% spike to inconsistent split-adjustment
of TSLA close prices in the underlying parquet store:

```
TSLA close prices in BarStore for the 2022-Q1 window:
  2022-03-29:   $366.52       ← split-adjusted (raw / 3)
  2022-03-30: $1099.57         ← RAW pre-split price
  2022-03-31: $1093.99         ← RAW
  2022-04-01: $1079.63         ← RAW
  2022-04-04:   $381.82        ← split-adjusted again
  2022-04-05: $1145.38         ← RAW again
```

TSLA's only relevant split was the **3-for-1 on 2022-08-25**, well after
this window. The 2022-Q1 series should be either:
- **consistently raw** (~$1000 throughout), or
- **consistently adjusted** (~$330 throughout — i.e. retroactively divided
  by 3 because the future split's adjustment factor cascades back).

It is neither: adjacent days show day-to-day jumps from $366 to $1099 to
$381 to $1145, which translates to spurious +200% / -65% / +200% paper
returns when the position is held across the discontinuity. That is the
+190.95% bug.

The store-side adjustment logic in
`core/data/bar_store.py::BarStore.load(adjusted=True)` documents that
`adj_factor(t) = Π (from_i / to_i) over splits i where date_i > t` — a
forward-looking adjustment. If the underlying parquet rows are already
mixed (some raw, some adjusted) before BarStore sees them, the load-time
multiplication can't repair the inconsistency.

## Verified affected and clean windows

The hazard appears in any window that lives substantially **before** a
future major split's effective date for symbols that hold significant
weight in either candidate.

A continuity check on 20 universe symbols (`TSLA, AAPL, NVDA, MSFT,
AMZN, META, GOOGL, SOXL, TQQQ, SPY, QQQ, VICI, TSN, ED, DG, GIS, MTUM,
QUAL, XLRE, SLV`), defined as "any adjacent-day close-price ratio
outside [0.67, 1.5]" (excluding legitimate +50% / -33% real moves),
returns:

| Window | Continuity issues | Status |
|--------|------------------:|--------|
| 2020-01-02 → 2020-04-22 (COVID bear) | TSLA + GOOGL flagged | ❌ contaminated |
| 2022-01-03 → 2022-04-22 (Q1 bear) | TSLA flagged | ❌ contaminated |
| **2022-08-26 → 2022-12-15 (Q4 bear)** | **0 / 20** | ✅ **clean** |
| 2024-01-02 → 2024-04-19 (up-tape) | 0 / 20 | ✅ clean |

The 2020 COVID window was originally proposed as the cross-regime
substitute for 2022-Q1 because TSLA's 5:1 (2020-08-31) and AAPL's 4:1
(2020-08-31) sit AFTER the window. But the issue isn't only about
"the immediately next split" — GOOGL's 20:1 on 2022-07-15 also cascades
back into the 2020 window, and the parquet rows are inconsistent the
same way TSLA's are in 2022-Q1. So 2020 is also off-limits.

The **2022-08-26 → 2022-12-15** window starts the day after TSLA's
3:1 split (2022-08-25). At that point, every previous major split in
the universe has already happened (TSLA 5:1 + AAPL 4:1 in 2020-08;
NVDA 4:1 in 2021-07; AMZN 20:1 in 2022-06; GOOGL 20:1 in 2022-07; TSLA
3:1 in 2022-08). The next major split is NVDA's 10:1 on 2024-06-10,
well after this window's 2022-12-15 end. The window therefore avoids
the cascade-back hazard entirely. The continuity check confirms this
empirically.

The 2024 window we already analyzed sits between the August 2022 split
cluster and NVDA's June 2024 split. Same clean-segment logic — and the
day-10/20/40/60 checkpoint memos for it remain valid.

## Decision (revised 2026-04-24)

Per user direction over two iterations:
- **Abandon both 2022-Q1 and 2020 windows**. No checkpoint memos written
  for those runs.
- **Do not pull the data-integrity fix into the parallel-paper main
  line**. Repairing `BarStore` adjustment is non-trivial (likely needs
  a parquet rebuild for at least TSLA and GOOGL and possibly more) and
  would violate the "no pipeline / no universe / no spec change"
  constraint of the parallel-paper plan.
- **Use the 2022-08-26 → 2022-12-15 (Q4 bear) window** as the bear
  cross-regime data source. Same frozen candidates, same universe, same
  pipeline, only the time window changes. Real bear regime (S&P 500
  hits its October 12 low and recovers ~7% into mid-December — a
  legitimate risk-off / partial-recovery test).

## Affected paper runs (deleted; gitignored anyway)

- `data/paper_runs/rcm_v1_defensive_composite_01/20260424T212820Z/`
  (2022-Q1)
- `data/paper_runs/candidate_2_orthogonal_01/20260424T212823Z/`
  (2022-Q1)
- No 2020 runs were ever generated — the window was rejected before
  running.

These directories were removed to keep the on-disk state aligned with
the snapshot reports.

## Follow-up tracker

This is now a standalone P2-class data-integrity item. It is NOT on the
parallel paper main line. Suggested triage:

1. **Reproduce** on more symbols across the affected window — confirm
   whether the issue is TSLA-only or systemic (likely systemic if the
   cause is the underlying parquet ingest).
2. **Trace** which ingest source produced the inconsistent rows
   (polygon_gz 2015-2023 vs other) — see CLAUDE.md "1m Bar Pipeline"
   summary.
3. **Decide** whether to (a) rebuild splits.parquet and re-run the
   adjustment cascade, (b) rebuild affected daily parquets from a
   trusted source, or (c) document the affected windows as
   "do not paper-run on this period without first..." and live with
   the limitation.

This decision is **not** in scope for the current parallel-paper
exercise. The next document the user should expect is the 10d
operational-sanity memo for the 2020 COVID rerun.
