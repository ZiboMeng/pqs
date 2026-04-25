# OOS Framework Workstream — Explicit Unfreeze (MVP scope only)

**Date**: 2026-04-25
**Authorized by**: user (zibo) — verbal in session, recorded here
**Supersedes**: `docs/memos/20260425-data_integrity_round3_close.md` §"What
remains frozen" item "No OOS-framework work" (now narrowed)

---

## What is unfrozen

OOS-framework MVP execution under the contract in:
- `docs/prd/20260425-oos_validation_framework_codex_v3.md` (PRD v3, scope)
- `docs/prd/20260425-oos_mvp_ralph_loop_execution.md` (execution PRD,
  R1-R7)
- `dev/scripts/ralph_loop/oos_mvp_launcher.md` (loop launcher prompt)

Lineage tag: `oos-mvp-2026-04-25`. Completion promise: `OOSMVPDONE`.

The HARD invariant list inside the execution PRD §2 + launcher continues
to hold during the loop. Anything outside R1-R7 scope is still frozen.

## What remains frozen (unchanged)

Carrying forward from round-3 close memo:
- No universe extension
- No new mining round
- No new data tier
- No Candidate-3 work
- No retroactive RCMv1 / Cand-2 frozen-spec change
- No new factor in PRODUCTION_FACTORS
- No additions to `requirements*.txt` / `pyproject.toml`
- No SQLite schema migration on `registry.db`
- No edits to `config/*.yaml`, `core/research/frozen_spec.py`, or
  `core/factors/factor_registry.py::PRODUCTION_FACTORS`
- No deployable-OOS framing in any closeout memo (pseudo-OOS only,
  per PRD v3 §1.1 + §1.3)

## Scope of unfreeze (explicit)

Authorized write paths:
- `core/research/{robustness,concentration,forward}/`
- `tests/unit/research/`, `tests/unit/reporting/`, `tests/integration/`
- `data/research_candidates/<id>_robustness_window.yaml`
- `data/research_candidates/<id>/{robustness_eval,concentration_report}.{json,md}`
- `dev/scripts/oos_mvp/`
- Watch-exposure section hooks in `core/reporting/master_report.py` and
  `scripts/paper_drift_report.py` (R4 only, narrow signature)
- `CLAUDE.md` "Current TODO" entry on close
- `docs/INDEX.md` (new PRD + memo entries)
- `docs/memos/20260425-oos_mvp_close.md` (R7 closeout)
- `data/baseline/latest.json` rebuild via existing baseline script

Authorized read-only:
- everything else in the repo (loop may search / inspect, must not
  modify outside the write list above)

## Halt + reauth conditions

Loop must halt and pause for explicit user reauthorization on:
- any HARD invariant violation (per execution PRD §2 + launcher)
- pytest drift not explained by regression tests added that round
- same round retried twice
- single round running > 30 min
- artifact size anomaly (single file > 10 MB or cumulative > 100 MB)
- any attempt to write outside the authorized paths above

After `OOSMVPDONE` emits successfully, the OOS-framework workstream
**re-freezes by default**. Re-opening forward-OOS work (R5 schema only
shipped, no runner) requires a fresh user decision and likely a new
PRD round.

## How this was issued

User asked "怎么解冻". This memo records the authorization. No code
changes are part of the unfreeze itself; the unfreeze is purely a
permission scope adjustment that the upcoming ralph-loop iteration
will operate inside.

## One-line summary

OOS-framework MVP (R1-R7) is unfrozen for the duration of the
ralph-loop run; everything else from round-3 close stays frozen;
re-freeze is automatic at `OOSMVPDONE`.
