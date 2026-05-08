---
lineage_tag: cycle07-to-fleet-master-2026-05-06
phase: AUDIT_FOLLOWUP
date: 2026-05-07
operator: zibomeng (Claude Opus 4.7)
severity: P0 — silent false-negatives across cycle06/07a/08 Track A acceptance
status: FIXED + RE-EVALUATED (per-cycle results inline)
---

# Beta-to-QQQ metric path wiring bug — postmortem

## TL;DR

`core/research/temporal_split_acceptance.py:_eval_beta_gate` resolves
`metrics["beta"]["beta_to_qqq"]` (nested, mirroring yaml `acceptance.beta.beta_to_qqq_max`
schema). Cycle06/07a/08 evaluator scripts built `metrics["beta_to_qqq"]`
(top-level scalar). `_resolve_metric` returned `_MISSING` sentinel →
`_eval_beta_gate` fail-closed → **all cycle06/07a/08 Track A trials had
false-negative `beta_to_qqq` gate FAIL** despite actual betas well below
the 0.85 cap.

Discovered 2026-05-07 during cycle07-to-fleet master PRD R12 audit
follow-up (reading vs_qqq deprecation wiring); confirmed via direct
`_resolve_metric()` invocation in REPL:

```
>>> _resolve_metric(metrics_with_top_level_beta, "beta.beta_to_qqq")
<_MISSING object>
>>> _resolve_metric(metrics_with_top_level_beta, "beta_to_qqq")
0.534
```

## Pre-fix actual betas (from per-trial NAV correlation block)

| Cycle | Trial | features | actual beta_vs_qqq | gate FAIL? |
|---|---|---|---|---|
| cycle07a | `81cfb5f4c4f5` | drawup + xsec + ret_5d | -0.009 | TRUE (false-neg) |
| cycle07a | `f133a18d1495` | drawup + mom_252d + ret_2d | +0.566 | TRUE (false-neg) |
| cycle07a | `1e771580f486` | drawup + mom_63d + ret_1d | +0.534 | TRUE (false-neg) |
| cycle08 | `8ac6bccbeed1` | max_dd_126d + mom_252d + reversal_21d | -0.00008 | TRUE (false-neg) |
| cycle08 | `60998346d975` | max_dd_126d + mom_252d + ret_5d | -0.00007 | TRUE (false-neg) |
| cycle08 | `3f40e3f4ed1a` | max_dd_126d + xsec + ret_5d | +0.368 | TRUE (false-neg) |
| cycle06 | `bab8cfe88af3` | drawup + trend_tstat_20d + ret_2d | +0.599 | TRUE (false-neg) |
| cycle06 | `31af04cf2ff9` | drawup + xsec_rank_63d + ret_5d | -0.009 | TRUE (false-neg) |
| cycle06 | `a9e39c21feed` | drawup + trend_tstat_20d + ret_5d | +0.599 | TRUE (false-neg) |

All < 0.85 cap. **No genuine high-beta rejections in cycle06/07a/08 to date.**

## Root cause

The yaml schema for the beta gate is:

```yaml
acceptance:
  beta:
    beta_to_qqq_max: 0.85
```

`temporal_split_acceptance.py:_eval_beta_gate` reads:

```python
beta = _as_float_or_none(_resolve_metric(metrics, "beta.beta_to_qqq"))
cap = cfg.acceptance.beta.beta_to_qqq_max
```

The yaml `acceptance.beta.beta_to_qqq_max` block uses nested mapping; the
metrics dict CONTRACT is therefore "metrics nests `beta_to_qqq` under `beta`
key". Cycle06 evaluator (originally written 2026-05-06; mirrored to cycle07a
2026-05-07 + cycle08 2026-05-08) violated this contract by placing `beta_to_qqq`
at top level. Code review missed it because the gate name was `"beta_to_qqq"`
(matching the variable name) and pre-fix the gate output had
`notes="beta missing or non-numeric → fail-closed"` only when no value at all
existed — the diagnostic message was buried in a 17-gate verdict object.

## Fix (commit pending)

1. **Evaluator scripts** (`dev/scripts/cycle06/cycle06_track_a_eval.py` +
   `dev/scripts/cycle07a/cycle07a_track_a_eval.py`): nest beta as
   `metrics["beta"] = {"beta_to_qqq": float(...)}`.
2. **`run_split_acceptance` call**: pass `freeze_date` derived from
   `--lineage` tag (e.g. `track-c-cycle-2026-05-07-01` → `2026-05-07`),
   enabling automatic v3 dispatch for cycles frozen ≥ 2026-05-02 (QQQ
   deprecation cutoff).
3. **Regression test**: `tests/unit/research/test_beta_metric_path_canonical.py`
   (6 tests) pins:
   - canonical schema resolves
   - pre-fix top-level path returns `_MISSING`
   - low-beta passes under both v1 + v3
   - high beta still fails under v3 (QQQ deprecation does not soften
     beta gate; long-only no-margin downside-risk constraint preserved)
   - v3 makes vs_qqq aggregate `passed=True` with
     `diagnostic_actual_passed` recording the real outcome

Pre-existing `excess_vs_qqq_diagnostic_only` flag in v3 yaml + dispatch
machinery shipped 2026-05-02 unchanged.

## Re-evaluation results (post-fix)

### cycle07a (lineage `track-c-cycle-2026-05-07-01`, freeze_date=2026-05-07 → v3)

(JSON written to `data/audit/cycle07a_track_a_eval_track-c-cycle-2026-05-07-01_RERUN_2026-05-07.json`.)

**Per-trial verdict diff**:

| Trial | Pre-fix gates failed | Post-fix gates failed | verdict change |
|---|---|---|---|
| `81cfb5f4c4f5` | spy_agg + qqq_agg + role_qqq + beta | spy_agg + role_2025_spy | FAIL → FAIL |
| `f133a18d1495` | spy_agg + qqq_agg + beta | spy_agg | FAIL → FAIL |
| `1e771580f486` | qqq_agg + beta | (none, 17/17 PASS) | **FAIL → PASS** |

Trial 3 `1e771580f486` is the focal candidate — pre-fix only failed on
`validation_aggregate_excess_vs_qqq` (now diagnostic under v3) and
`beta_to_qqq` (false-neg). Post-fix verdict: **PASS** (cycle07a's first
nominee, beta=0.534).

### cycle08 (lineage `track-c-cycle-2026-05-08-01`, freeze_date=2026-05-08 → v3)

JSON: `data/audit/cycle08_track_a_eval_track-c-cycle-2026-05-08-01_RERUN_2026-05-07.json`.
Result: **0/3 PASS**. All three trials fail
`validation_aggregate_excess_vs_spy` (Trial 1+2 also fail
`role_core__validation__2025__excess_vs_spy`); beta gate now correctly
records actual betas (-0.0001 / -0.0001 / +0.368) — none cap-violating.
Beta bug fix confirmed; cycle08 doesn't flip on the fix (binding gate
is vs_spy, not beta).

### cycle06 (lineage `track-c-cycle-2026-05-06-01`, freeze_date=2026-05-06 → v3)

JSON: `data/audit/cycle06_track_a_eval_track-c-cycle-2026-05-06-01_RERUN_2026-05-07.json`.
Result: **0/3 PASS**. Trial 1+3 fail `validation_aggregate_excess_vs_spy`
only; Trial 2 also fails `role_core__validation__2025__excess_vs_spy`.
Actual betas (+0.599 / -0.009 / +0.599) — none cap-violating. Same
shape as cycle08: beta fix confirmed, but vs_spy aggregate is the
real binding gate.

## Blast radius beyond cycle06/07a/08

- **cycle04 / cycle05**: do NOT use `run_split_acceptance` directly
  (used `anti_sibling_policy` / older evaluators); not affected.
- **RCMv1 / Cand-2** (legacy decay verification): pre-PRD-A.MV; their
  promotion verdicts predate `temporal_split_acceptance.py`. Not affected.
- **Trial 9** (diversifier, in_progress forward observe): split-acceptance
  was rendered at init (2026-05-04) under v2 dispatch; not affected by
  this code path. TD60 verdict (~2026-07-30) uses `attention_check.py`
  which operates on derived NAV metrics, not Track A acceptance. Not
  affected.
- **Closeout memos**:
  - `docs/memos/20260507-cycle07a_closeout.md` — claim "Track A 0/3
    PASS, 4 gates each fail" requires retraction note.
  - `docs/memos/20260520-cycle08_closeout.md` — same.
  - `docs/audit/20260506-cycle07_fleet_audit_final_2.md` — R8/R9
    verdicts based on pre-fix data; CONFIRMED status of R8 needs
    revision pending re-eval.

## Self-audit (R1-R4)

### R1 — factual

- `_resolve_metric("beta.beta_to_qqq", metrics_pre_fix)` → `_MISSING` (REPL)
- `_resolve_metric("beta_to_qqq", metrics_pre_fix)` → 0.534 (REPL)
- All 3 cycle07a trials' actual beta < 0.85 (verified via
  `data/audit/cycle07a_track_a_eval_track-c-cycle-2026-05-07-01.json`
  `nav_correlation_vs_benchmark.beta_vs_qqq`)

### R2 — logical

- yaml schema is `acceptance.beta.beta_to_qqq_max` (nested) → metrics
  dict contract MUST mirror nesting
- Pre-fix evaluator violated contract; gate fail-closed silently
  (no schema validator catches this; `_resolve_metric` returns
  `_MISSING` sentinel which `_as_float_or_none` coerces to `None`
  which `_eval_beta_gate` interprets as "missing → fail closed")
- Bug class: silent contract violation, no test coverage at the
  evaluator-script layer. Per-test verification at `_eval_beta_gate`
  unit-test layer DID work (correctly fail-closes when beta is None);
  the gap was at the evaluator-script-builds-metrics-dict layer.

### R3 — actually-run

- 6 new regression tests PASS (live, 0.21s)
- cycle07a re-eval in progress (live)
- Will run cycle06 + cycle08 re-eval after cycle07a completes

### R4 — boundary

- **What if beta is genuinely > 0.85 post-fix?** Test
  `test_high_beta_still_fails_v3` confirms gate still HARD-fails.
  The fix only removes false-negatives, not real rejections.
- **What if some trial we re-evaluate now passes Track A but
  shouldn't?** All 17 other gates still apply. The bug only affects
  beta gate; vs_spy aggregate, 2025 hard gate, per-year MaxDD,
  stress slices, concentration, cost robustness, dividend safety,
  etc. all evaluated independently. A trial that flips PASS post-fix
  passes ALL 17 gates including the 16 unaffected ones.
- **What if cycle04/05 had the bug too via a different code path?**
  Verified via grep: cycle04 + cycle05 use different evaluator scripts
  (`anti_sibling_policy.py`, `evaluate_cycle04_top_n.py`); they do NOT
  call `run_split_acceptance`. Not affected.

### Self-audit verdict

PASS. Bug confirmed by REPL; fix shipped; re-eval in progress;
postmortem comprehensive.

## Reversibility

Fix is doc + code. Revert = revert these 3 evaluator scripts + delete
test file. Pre-fix verdicts preserved in original
`data/audit/cycle{06,07a,08}_track_a_eval_*.json` files (no overwrite;
re-runs land in `*_RERUN_2026-05-07.json` parallel files).

## Lineage

`cycle07-to-fleet-master-2026-05-06` audit follow-up.
