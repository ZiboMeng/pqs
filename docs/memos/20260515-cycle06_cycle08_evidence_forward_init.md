# cycle06 + cycle08 survivors — sealed 2026 test + forward-init

**Date**: 2026-05-15
**Authority**: user explicit-go 2026-05-15.

## Pipeline (corrected ordering)

Per user correction 2026-05-15, the OOS evaluation order is:

```
Track A acceptance (train+validation)
  → sealed 2026 single-shot test  (generalization GATE — comes first)
    → forward observation          (operational live confirmation)
      → promotion
```

The sealed test is the gate; it must precede forward observation (a
gate must come before the thing it gates). CLAUDE.md had a conflicting
A.MV line implying forward-first — that line is superseded; the Track D
trigger line ("passes acceptance + 2026 sealed test" → forward +
promotion) is the correct ordering.

## Background

The 2026-05-15 P0 fix (`temporal_split_acceptance.py` MaxDD gate
sign-bug, commit `1e0d81e`) revealed every prior Track A "PASS" had a
non-functional MaxDD gate. Post-fix re-eval left 2 genuine survivors
(official QQQ-diagnostic governance + working MaxDD gate):

- `cycle08_3f40e3f4ed1a` — max_dd_126d + xsection_rank_63d + ret_5d, monthly
- `cycle06_31af04cf2ff9` — drawup_from_252d_low + trend_tstat_20d + ret_2d, weekly

Both mined 2026-05-06/08 — BEFORE the 2026-05-13 WebSearch leak, so a
sealed 2026 test on them is clean.

## Sealed 2026 single-shot test — RESULT: 2/2 PASS

Window 2026-01-01 → 2026-05-14 (~4.5 months, genuine OOS — candidates
never saw 2026). SPY did ~+9.5% over the window.

| candidate | cum_ret | vs SPY | vs QQQ | Sharpe | MaxDD | verdict |
|---|---|---|---|---|---|---|
| cycle08_3f40e3f4ed1a | +24.35% | +14.83% | +6.94% | 4.10 | -7.66% | PASS |
| cycle06_31af04cf2ff9 | +34.06% | +24.55% | +16.66% | 4.00 | -6.62% | PASS |

Pre-committed sealed-pass criteria (locked before the run):
vs_spy > 0 (HARD), MaxDD ≤ 25% (HARD), Sharpe > 0 (HARD). Both clear
all three with margin.

**Senior-quant caveat**: Sharpe ~4.0 is a 4.5-month short-window
figure — annualized Sharpe from a partial year is noisy and optimistic.
Honest read: both candidates clearly beat SPY double-digit on clean
2026 OOS with single-digit drawdown — a real PASS — but the Sharpe-4
magnitude should NOT be treated as a steady-state estimate. Forward
observation gives the cleaner rolling read.

## Sealed ledger mechanics — caveat

The sealed-eval script (`dev/scripts/sealed/run_sealed_2026_eval.py`)
on its first run looped `record_eval` per candidate. The first call
(cycle08_3f40e3f4ed1a) recorded; the second (cycle06_31af04cf2ff9) was
correctly blocked by `sealed_ledger` B1 (`fail_closed_on_split_failure`
— one core sealed eval per split_name). B1 worked as designed; the
script's per-candidate loop was the bug.

Resulting state:
- `data/mining/sealed_eval_ledger.parquet` has ONE row: cycle08, which
  is the event marker that locked split `alternating_regime_holdout_v1`.
- cycle06's sealed result is recorded in this memo + `sealed_2026_eval.json`
  as part of the SAME single sealed event.
- The script was corrected post-hoc to record one batch entry; it
  cannot re-run (B1 locks the split).

The 2026 holdout for `alternating_regime_holdout_v1` is now consumed.
Re-testing improved candidates on 2026 requires bumping split_name
(new holdout window, e.g. 2027).

## Forward-init decision (evidence-only cohort)

Both candidates PASSED the sealed gate → forward-init as the next
pipeline step (operational live confirmation).

Anti-sibling pre-flight (3-way raw NAV Pearson vs active forward
candidate trial9_diversifier_002): cycle08↔cycle06 0.766,
cycle08↔trial9 0.825, cycle06↔trial9 0.704 — all < 0.85 → forward
fleet is 3-way non-sibling.

**Role**: the main `core/research/forward` runner's `CandidateRole`
enum has no `evidence_only` value ({core_alpha, diversifier,
legacy_decay_verification, risk_control}). Both candidates take
`candidate_role = core_alpha` — the role whose acceptance gates they
actually passed. The "evidence-only" operational stance (observe, do
NOT commit to fleet allocation) is expressed by candidate_id
`_evidence_v1` suffix + registry status S2_PAPER + the fleet allocator
(Track B Step 6+) being HARD PAUSED.

- candidate_ids: `cycle08_3f40e3f4ed1a_evidence_v1`,
  `cycle06_31af04cf2ff9_evidence_v1`
- freeze_date 2026-05-15; first observe 2026-05-16 EOD
- TD60 verdict ~2026-08-14

### TD60 decision criteria (pre-committed)

- GREEN: realized Sharpe > 0.8, 60d rolling MaxDD < 20%, NAV
  daily-return Pearson vs trial9_v2 < 0.85 → eligible for committed
  fleet role
- YELLOW: Sharpe 0.4-0.8 or MaxDD 20-25% → continue to TD90
- RED: Sharpe < 0.4 or MaxDD > 25% → close evidence track

## Caveats carried forward

- cycle08 was a 40-trial smoke (not full 200-trial mining) — overfit
  risk relative to a full search; the strong sealed result is
  reassuring but not dispositive.
- Both survived a retroactive re-eval after a foundation bug fix;
  forward observation is the live proving ground.
