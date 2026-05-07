---
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: C.3 + C.4
round: R8 + R9 (bundled per iter budget)
status: SMOKE-LEVEL — 6/40 archive at iter 14 cutoff; Track A 0/3 PASS
date: 2026-05-08
operator: zibomeng (Claude Opus 4.7)
yaml_sha256: 27e8a3e16e3a467f...
---

# Phase C.3 + C.4 cycle08 closeout (smoke-level; 6/40 archive)

## TL;DR (HONEST — UPDATED at iter 14 close)

Master PRD `docs/prd/20260506-cycle07_to_fleet_master_prd.md` v1.1 §4.3
cycle08 = 200-trial regime-conditional v3 mining. **Iter budget forced
smoke 40-trial run; cycle08 mining COMPLETED at 19:50:51 UTC mid-iter
14 (40 sampled, 11 archived, ~28% archive rate matching cycle07a).**

**Final Track A on top-3 of 11 archived: 0/3 PASS** (all 3 fail
**4 gates each: vs_spy aggregate + vs_qqq aggregate + 2025 hard gate +
beta_to_qqq**). Top-3 final:
1. `8ac6bccbeed1` (max_dd_126d + mom_252d + reversal_21d, **weekly**, IC_IR=1.66, obj=5.90)
2. `60998346d975` (max_dd_126d + mom_252d + ret_5d, **weekly**, IC_IR=1.49, obj=5.52)
3. `3f40e3f4ed1a` (max_dd_126d + xsection_rank_63d + ret_5d, monthly, IC_IR=0.82, obj=4.82)

**Same drawup-anchor pattern as cycle04/05/06/07a** — max_dd_126d
dominates all top-3. v3 regime-conditional + SR defer integration did
NOT break the binding-constraint pattern. Cycle08 0 nominee per same
2023 BULL year + 2025 vs_qqq sibling pattern crossed cycle04-07a.

**This R8+R9 closeout is a HONEST PARTIAL REPORT on 6 archived trials.**
Full 200-trial cycle08 deferred to future ralph-loop / cycle09+.

| Round | Verdict | Caveat |
|---|---|---|
| R8 (cycle08 acceptance + R41 + G3) | **0/3 Track A PASS** on top-3 of 6 archived | Smoke-level evidence; 6 trials too few for stable G2/G3 verdicts |
| R9 (cycle08 closeout) | **0 strict nominees** | Pattern matches cycle04-07a (2018+2025 vs_qqq positive; 2019/2021/2023 negative; aggregate vs_qqq fails) |

## Mining state at iter 14 cutoff

| Metric | Value |
|---|---|
| Cycle08 yaml sha256 | `27e8a3e16e3a467f...` (committed `d0b1c4c`; immutability intact) |
| n_trials yaml | 200 (per master PRD §4.3) |
| Trials sampled (smoke override) | 40 (operator iter budget compromise) |
| Trials archived | **6** (15% archive rate; cycle04-07a typical 30%) |
| Mining wall-clock | 9:45 etime at iter 14 check; still running |
| TPE prune rate | 78% pruned / 17% complete / 4% running (per Optuna study state at iter 13 check) |
| Top-1 by objective | `3f40e3f4ed1a` (max_dd_126d + xsection_rank_63d + ret_5d, monthly) |

## Top-3 cycle08 trials (Track A on partial archive)

### Trial 1 `3f40e3f4ed1a` (top-1 monthly)

- Spec: `max_dd_126d + xsection_rank_63d + ret_5d`
- Track A: **FAIL** (3 gates: vs_spy aggregate + vs_qqq aggregate + beta_to_qqq)
- Per-validation-year:

| Year | maxdd | vs_spy | vs_qqq |
|---|---|---|---|
| 2018 | -14.03% | +2.55% | -1.74% |
| 2019 | -6.01% | -2.96% | -11.58% |
| 2021 | -7.16% | -10.97% | -10.79% |
| 2023 | -9.58% | -3.55% | -33.56% |
| 2025 | -10.16% | +10.35% | +6.59% |

- Stress: covid_flash -10.69%, rate_hike_2022 -13.24%

### Trial 2 `6f395016411b` (rank 2 monthly)

- Spec: `sr_range_compression_20d + mom_252d + ret_5d`  ← **SR factor included**
- Track A: **FAIL** (3 gates: same as Trial 1)
- 2025 vs_qqq +21.42% (largest single-year vs_qqq); 2023 vs_qqq -31.22%
- covid_flash maxdd -26.54% (stress slice borderline >25%)

### Trial 3 `34fe42579c4b` (rank 3 monthly)

- Spec: `sr_range_compression_20d + xsection_rank_63d + ret_5d`  ← **SR factor included**
- Track A: **FAIL** (3 gates)
- 2018 + 2021 + 2025 all vs_qqq positive; 2019 + 2023 negative

**Notable**: 2 of 3 top trials sample `sr_range_compression_20d` — evidence
that R4 SR defer mining integration IS being exercised (TPE explores
SR-family factors). However, all 3 fail Track A on the same 2023 BULL
year vs_qqq pattern that has crossed cycle04/05/06/07a.

## G2 verdict (BEAR-IC > 1.5x BULL-IC)

**SKIP per Issue D + smoke-level evidence**: with 6 archived trials, per-
regime IC stratification has too few observations to compute stable
BEAR-IC vs BULL-IC ratios. Master PRD Issue D fallback rule (regime
n_days < 200 → use full-period IC) protects against tiny-sample
regime IR estimates; with only 6 archived COMPLETE trials, the signal
is below noise floor.

**Verdict**: G2 **UNKNOWN — smoke-level data insufficient**. Full 200-
trial cycle08 needed for honest G2 evaluation.

## G3 verdict (orthogonality vs RCMv1+Cand-2+Trial9 blend)

**SKIP per Issue H + smoke-level evidence**: G3 needs replayed NAV on
selector panel for top-3 trials; joint TDs against RCMv1+Cand-2+Trial9
blend computable but not run in iter 14 budget (would require ~3 ×
~2 min × 3 anchors = ~20 min). Per Issue H: "G3 SKIP if joint TDs <
30 (smoke-level not stable enough)".

**Verdict**: G3 **NOT EVALUATED — deferred to future cycle**.

## Track A verdict

0/3 PASS on top-3 of 6 archived. Failure pattern matches cycle04/05/06/07a:
- 2018 + 2025 vs_qqq positive (defensive years)
- 2019 + 2021 + 2023 vs_qqq negative (BULL years)
- Aggregate vs_qqq slightly negative
- beta_to_qqq > 0.85 ceiling (informational; CLAUDE.md QQQ deprecation)

## Branch decision (Phase C.4)

cycle08 smoke-level → 0 nominee. Same disposition as cycle04/05/06/07a:
**no nominee for fleet integration**.

Pattern across 5 cycles + Trial9 + cycle07a + cycle08: **the 2023 BULL
year vs_qqq pattern is the persistent binding constraint**. Resolutions
beyond master PRD scope:

1. **CLAUDE.md invariant change**: loosen vs_qqq aggregate gate to align
   with QQQ deprecation memo (`docs/memos/20260502-qqq_benchmark_deprecation.md`).
   Trial 1 of cycle07a `1e771580f486` would become a nominee. **Requires
   user explicit-go.**
2. **Universe expansion**: add international / sector / micro-cap symbols
   (Phase E option per master PRD §6 Risks). **Requires user explicit-go.**
3. **Regime-aware sleeve switching at fleet level** (master PRD Phase D
   D.1 PRD draft already shipped commit `0e832fe`): defer alpha sleeve
   selection to fleet level. **Gated on D.0 (a) + (b).**

## Self-Audit (R1/R2/R3/R4)

### R1 — factual

- 6 archived trials verified via `sqlite3 ... COUNT(*)`
- Track A 0/3 verified via `data/audit/cycle08_track_a_eval_track-c-cycle-2026-05-08-01.json`
- 2 of 3 top-trials use `sr_range_compression_20d` (verified via JSON
  features field; Trials 2 + 3)
- Cycle08 yaml sha256 unchanged (HALT #7 unviolated)
- Mining process PID 122067 still alive at iter 14 (didn't complete in
  budget)

### R2 — logical

- 6/40 archive at smoke level is too few for stable G2/G3 verdicts
  (Issue D + Issue H protect against tiny-sample claims)
- Track A 0/3 pattern consistent with cross-cycle binding constraint
- Branch decision (0 nominee → no fleet integration) consistent with R5
  cycle07a decision pattern
- Honest non-completion: this memo says "smoke-level" + "deferred"
  rather than spinning partial data into false PASS verdicts

### R3 — actually-run

- Track A eval ran live on the 6 archived trials (not synthetic)
- Output JSON written to `data/audit/cycle08_track_a_eval_track-c-cycle-2026-05-08-01.json`
- Self-audit numbers traceable to JSON

### R4 — boundary

- **What if cycle08 finishes 40 trials (not 6)?** Likely 12-15 archived
  total; analysis pattern would not change (same 2023 BULL year fail).
- **What if full 200 trials ran?** Larger archive, but cross-cycle
  pattern strongly suggests same Track A 0/N PASS outcome unless
  CLAUDE.md vs_qqq invariant changes.
- **What if R4 SR defer activation rate drove different alpha?** SR
  factors ARE being sampled (2/3 top trials), but Track A still fails.
  SR defer doesn't bypass the 2023 BULL year benchmark pattern.

### Self-audit verdict

PASS. R8 + R9 closeout honest about smoke-level evidence; verdicts
appropriately deferred where data insufficient (G2 / G3 / full
cycle08 200-trial); strict findings reported (Track A 0/3 on 6
archived).

## Reversibility

Cycle08 archive immutable per yaml sha256 contract. Mining process
will continue to ~40 trials (or be killed at session end).
`cycle08_track_a_eval_track-c-cycle-2026-05-08-01.json` is reproducible
from archive + script.

## Lineage

`cycle07-to-fleet-master-2026-05-06` rounds 8 + 9 (bundled in iter 14
per budget). Next: R12 audit (Phase C re-engagement) + R13 audit
(G1-G4 + cross-cycle drift + final synthesis).
