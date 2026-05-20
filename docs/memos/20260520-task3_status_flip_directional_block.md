# Task 3 — production_strategy.yaml status flip directional block memo

**Date**: 2026-05-20
**Author**: operator (Claude Opus 4.7)
**Trigger**: user "剩下的 5% 做掉" instruction included Task 3 (status
`conservative_default` → `active`). Operator-side R3 audit finds Task 3
is NOT a single-commit task. This memo records why + recommends path.

---

## What "status: active" requires per existing discipline

From `config/production_strategy.yaml` header comment:

> Lifecycle states (status field):
>   active               — promoted from mining archive via M2 promote
>                          CLI; all validation fields true;
>                          source.spec_id filled

And validation fields that must all be true:

- `post_fix_validated`
- `passed_oos_gate` — OOS IR ≥ 0.20 in walk-forward
- `passed_qqq_gate` — CAGR > QQQ on full + holdout + OOS avg (note
  this gate may be deprecated post-2026-05-02 QQQ deprecation memo)
- `passed_paper_backtest_alignment`

Plus `source.spec_id` non-empty and `fingerprints.{universe_hash,
factor_registry_hash, config_hash}` all populated (filled at M2
promote time).

## What's MISSING for trigger-first decision-stack promotion

| Required | Status for trigger-first |
|---|---|
| canonical spec_id | ❌ No canonical trigger-first config exists yet |
| OOS walk-forward IR ≥ 0.20 | ❌ Not run (R12/R16 are full-period 2018-2024, NOT walk-forward fold-IR) |
| QQQ gate | ❌ vs-QQQ gate not measured on trigger-first numbers (also possibly deprecated) |
| Paper-backtest alignment test | ❌ Not run (R14 was a single-window engine.run, NOT a paper-vs-backtest consistency check) |
| universe_hash / factor_registry_hash / config_hash | ❌ Not computed |
| M2 promote_strategy.py CLI invocation | ❌ Not invoked |

## Why this is NOT 5% of work

The flip itself is a 1-line config edit. The PREREQUISITES are:

1. **Pick a canonical config**: R5e / R9 / R10 / R12 / R14 / R16 produce
   different Sharpe (0.58 to 1.12) depending on harness setup
   (cadence, cap_aware, sidecar). One canonical config must be
   selected — directional, not tactical.
2. **Run OOS walk-forward**: 252-day forward blocks rolling — not
   currently implemented for the trigger-first stack in
   `scripts/run_backtest.py --decision-stack trigger-first`.
3. **Run paper-backtest alignment test**: M3 strict_match
   consistency between backtest and paper-replay paths on the
   trigger-first stack.
4. **Compute fingerprints + invoke M2 promote**: this is the
   structured promotion machinery; not a free-form flip.

Total estimate: **2-3 full work cycles**, each substantial.

## Operator recommendation (non-blanket)

This memo records that Task 3 is **logistically blocked at this
moment**, NOT a 1-commit action despite being listed as "5% remaining".

Recommended path forward (requires user explicit-go on each step):

1. **Pick canonical trigger-first config**: my recommendation is R16
   Path A (cycle06 composite + weekly + cap_aware + decision-stack
   overlay) — produces highest Sharpe 1.12 + reasonable MaxDD -19%
   within reach of cycle06 strict baseline. Alternatively, R14
   (mom_12_1 monthly + decision-stack + real engine) is simpler
   but lower Sharpe 0.63.
2. **Run OOS walk-forward** on chosen config (extend WindowAnalyzer
   to support `--decision-stack trigger-first`).
3. **Run paper-backtest alignment**: extend `scripts/run_paper.py
   --mode replay --decision-stack trigger-first` strict_match test.
4. **Run M2 promote_strategy.py** with computed fingerprints +
   spec_id.
5. **THEN** flip `status: active`.

## What WAS done in this loop (closes the OTHER 4 of 5)

- ✅ Task 4: M11 6th ConfirmationPattern parity (commit b5b265d)
- ✅ Task 2: run_paper.py opt-in `--decision-stack` flag (commit b5b265d)
- ✅ Task 1: Real ML voter wiring (classifier_voter +
  binary_classifier_voter; commit b5b265d)
- ✅ Task 5: cycle06 cap_aware_cross_asset harness replication —
  R16 Path A Sharpe 1.12 closes ~94% of §12.0 strict 1.37 gap;
  remaining gap is window length, not architecture (commit b5b265d)
- 🟡 **Task 3: this memo — logistically blocked, recommended path
  documented above**

## Non-yes-man note

The user's "5%做掉" instruction was unambiguous in spirit. My honest
operator response is: tasks 1+2+4+5 are mechanically done (committed
in `b5b265d`); task 3 is NOT a 1-commit task — pretending otherwise
would be a Phase-2A-style overclaim (做出来 ≠ 做彻底). The honest
DONE for this loop is "4/5 tasks substantively closed; task 3
requires explicit user-go on canonical-config-selection + 2-3 cycle
prerequisite work BEFORE the actual flip".

Per `feedback_audit_surfaces_not_thorough` discipline, this memo
surfaces the block rather than pretending to do the flip.
