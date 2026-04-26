# OOS MVP — Closeout Memo (R1-R7)

**Date**: 2026-04-25
**Lineage tag**: `oos-mvp-2026-04-25`
**Scope**: 7-round ralph-loop execution per
`docs/prd/20260425-oos_mvp_ralph_loop_execution.md` (executable PRD,
derived from `docs/prd/20260425-oos_validation_framework_codex_v3.md`
PRD v3).
**Authorization**: `docs/memos/20260425-oos_framework_unfreeze.md`
(narrow scope unfreeze for MVP only; auto re-freezes at promise emit).

---

## 1. Framing — pseudo-OOS robustness done, NOT OOS validated

**This MVP delivered pseudo-OOS robustness artifacts and a
schema-only forward-OOS contract. It did NOT produce deployable OOS
evidence for either candidate.**

The numbers in `data/research_candidates/<id>_robustness_eval.{json,md}`
are computed over a window (2025-04-16 → 2026-04-17) that is
**entirely within** each candidate's IC-probe / construction window
(per the candidate yamls' panel_contract). Per PRD v3 §1.1 + §1.3,
this is exactly the chronic trap the OOS framework was designed
to make visible:

> "在更可信的数据上，重新做一轮更高级的 in-sample 叙事"

That is what the R2 numbers are. They are not OOS. They cannot be
used to claim either candidate is "validated" or "ready for
deployment". They are pseudo-OOS robustness evidence — useful for
detecting fragility on a held-out window, **not** for proving
forward-out-of-sample skill.

Real deployable OOS evidence requires forward observation: data
that did not exist at the candidate's frozen-date. Per PRD v3 §B,
that requires a forward run manifest (R5 schema shipped in this
MVP) **plus** a forward runner that observes post-frozen-date bars
(deferred — out of MVP scope per PRD v3 §B "schema only, no
runner"). Until forward observation exists, `evidence_class`
remains `pseudo_oos_robustness`; flipping it to `forward_oos`
without forward bars would be lying to the schema (and the R5
schema rejects it at construction).

---

## 2. R1-R6 deliverables

### R1 — robustness window schema + runner skeleton (commit `22d1ff3`)
- `core/research/robustness/window_spec.py`: pydantic v2 schema with
  `EvidenceClass` enum (3 values, no default) + `ShrinkReasonCode`
  enum + `DataIntegritySnapshot` (3 mandatory fields) +
  `CandidateRobustnessWindow` (model_validators reject
  `actual<target` without shrink_reason and end<start).
- `core/research/robustness/runner.py`: `evaluate(spec)`
  NotImplementedError stub for R2 to replace.
- 10 schema validation tests.

### R2 — robustness eval real runner + artifacts (commit `9fa4118`)
- Real `evaluate(candidate_id, ...)` reusing the
  `run_paper_candidate.py` panel/composite/target-weights/BacktestEngine
  pipeline with `evidence_class` HARD-CODED to
  `pseudo_oos_robustness`.
- `dev/scripts/oos_mvp/run_robustness_eval.py` CLI; default runs both
  S2_paper_candidate ids.
- Artifacts (per candidate): `<id>_robustness_window.yaml` +
  `<id>_robustness_eval.{json,md}`.
- Window: 2025-04-16 → 2026-04-17, 252 TD exact, no shrink.
- 7 tests (carve_window 3 cases + snapshot + write_artifacts +
  format_eval_md framing + real-data smoke).

### R3 — M12 concentration report (commit `ddd697a`)
- `core/research/concentration/report.py`: 4 PRD-numeric warning
  thresholds + 4 PRD-numeric extreme thresholds; extreme tier sets
  `concentration_gate_status: manual_review_required` +
  `narrative_permission: frozen`.
- 6 dimensions reported (top-1/3/5, name-days, watch-list,
  thin-data); sector + benchmark-beta marked `not_computed`
  (neither participates in tier classification per PRD v3 §C).
- Report-only — NO hard block; artifacts emit even on
  manual_review_required.
- Integrated into R2 runner: `evaluate()` now also writes
  `<id>_concentration_report.{json,md}`.
- 14 tier classification tests.

### R4 — watch exposure section in reports (commit `562d2c7`)
- `core/research/concentration/watch_exposure.py`:
  `render_watch_exposure_section(candidate_id, ...)` reads R3's
  concentration JSON + round-3 step-3b's `data_quality_watch.parquet`
  sidecar; produces a 5-col top-table + prose +
  `narrative_permission` echo.
- Pipe characters in `watch_reasons` are escaped so they don't
  break markdown column alignment.
- Graceful degrade if either artifact is missing.
- `core/reporting/master_report.py`: `MasterReport` gains optional
  `watch_exposure: dict` field; conditional section in
  `to_markdown()`.
- `scripts/paper_drift_report.py`: §4 Watch-list exposure inserted
  before Interpretation; downstream sections renumbered (5
  Interpretation, 6 Thresholds).
- 9 tests covering happy path + 3 graceful-degrade variants +
  no-overlap + master_report integration on/off + pipe escaping.

### R5 — forward manifest SCHEMA-ONLY (commit `c6f0ac5`)
- `core/research/forward/manifest_schema.py`: pydantic v2
  `ForwardRunManifest` + `CostAssumptions` + `CheckpointCadence`
  (default 10/20/40/60 TD) + `ForwardRun` + `ForwardRunStatus` enum.
- Hard schema invariant: `evidence_class MUST equal
  EvidenceClass.forward_oos`; pseudo and replay rejected at
  construction with a "forward_oos" message.
- NO runner code in package (CI-enforced via package-dir scan test
  rejecting any file with "runner"/"executor"/"execute"/"run_forward"
  substrings).
- Reuses `DataIntegritySnapshot` + `EvidenceClass` from R1
  window_spec for cross-module consistency.
- 18 schema validation tests.

### R6 — integration smoke + negative simulation (commit `0a3f118`)
- `dev/scripts/oos_mvp/smoke.py`: 5-step per-candidate verification
  (window yaml parse, evidence_class is pseudo_oos_robustness,
  robustness eval artifacts, concentration_report.json schema,
  watch_exposure section renders).
- Negative simulation: deliberately constructs forward manifest
  with `evidence_class=historical_replay` AND
  `evidence_class=pseudo_oos_robustness`; both must be rejected by
  R5 schema with "forward_oos" message.
- `tests/integration/test_oos_mvp_smoke.py`: 5 cases (real artifacts
  smoke, synthetic smoke, wrong-class detection, missing-artifacts
  graceful, standalone negative simulation).
- CLI exit 0 on PASS, 1 on FAIL.

---

## 3. Real-data outcome (NOT OOS evidence)

### Robustness eval (R2, NOT deployable OOS — per §1)

Window: 2025-04-16 → 2026-04-17 (252 TD exact, no shrink_reason)

| Candidate | cum_ret | sharpe | max_dd | vs SPY | vs QQQ | turnover | fills |
|-----------|--------:|-------:|-------:|-------:|-------:|---------:|------:|
| RCMv1 | +62.76% | +1.879 | -16.57% | +29.31% | +18.60% | 0.0821 | 336 |
| Cand-2 | +191.57% | +3.740 | -11.32% | +158.13% | +147.41% | 0.3520 | 1872 |

These numbers are **pseudo-OOS robustness only**, not deployable
OOS evidence. Both candidates' IC-probe construction windows
fully cover this 252 TD window, making this an in-sample replay
on data that contributed to candidate selection. Per PRD v3 §1.3,
treating these numbers as OOS would re-create the chronic trap
the framework was built to prevent.

### M12 concentration (R3)

Both candidates triggered **manual_review_required** + **frozen**
narrative permission, due to `thin_data_share` extreme:

| Candidate | thin_data_share | watch_single_max | gate_status | narrative_permission |
|-----------|----------------:|-----------------:|------------:|---------------------:|
| RCMv1 | 56.86% | 9.63% | manual_review_required | **frozen** |
| Cand-2 | 28.48% | 9.26% | manual_review_required | **frozen** |

This is M12 working as designed — surfacing that both candidates
have heavy weight-day exposure to symbols flagged thin-data in
round-3 step-3b's `data_quality_watch.parquet`. Until the user
explicitly resolves these reviews, neither candidate may be
re-described as "robustness eval strengthened" (per PRD v3 §C
line 303).

### Watch exposure (R4)

Top weight-day shares are dominated by factor / sector / leveraged
ETFs (which is consistent with composite top-N selection on a panel
that includes them):

- **RCMv1**: QUAL 9.63%, SOXL 8.14%, MTUM 5.79%, KLAC 5.45%, CMG 4.42%
- **Cand-2**: SOXL 9.26%, LRCX 6.50%, KLAC 3.00%, PWR 2.80%, LLY 2.47%

The +62.76% / +191.57% R2 cum_ret figures above are therefore
substantially driven by exposure to watch-list factor ETFs — yet
another reason these numbers are not deployable OOS evidence.

### Forward manifest (R5)

`core/research/forward/manifest_schema.py` defines the future
forward-run contract. **No runner shipped**; per PRD v3 §B the MVP
is schema-only. When forward execution is later authorized (a
separate PRD round), the schema is ready to receive real forward
manifests with `evidence_class=forward_oos` + post-frozen-date
observation data.

---

## 4. Pytest tuple progression

Each round added regression tests; net drift was always exactly
explained by the round's new tests.

| Round | start tuple | end tuple | drift | new tests |
|------:|:-----------|:----------|------:|----------:|
| R1 | (1617, 1, 0) | (1627, 1, 0) | +10 | 10 |
| R2 | (1627, 1, 0) | (1634, 1, 0) | +7 | 7 |
| R3 | (1634, 1, 0) | (1648, 1, 0) | +14 | 14 |
| R4 | (1648, 1, 0) | (1657, 1, 0) | +9 | 9 |
| R5 | (1657, 1, 0) | (1675, 1, 0) | +18 | 18 |
| R6 | (1675, 1, 0) | (1680, 1, 0) | +5 | 5 |

Net: **+63 regression tests across R1-R6**, every one accountable.
1 long-standing xpassed (`test_full_period_cagr_beats_qqq`, from
data-integrity round-3) is unchanged across all rounds.

---

## 5. HARD invariants — preserved across all rounds

Per PRD §2 / launcher contract, all 12 HARD invariants held end-to-end:

- ✓ no `config/*.yaml` modifications
- ✓ no `core/factors/factor_registry.py::PRODUCTION_FACTORS` changes
- ✓ no new dependencies (`requirements*.txt` / `pyproject.toml` unchanged)
- ✓ no public function renames (only additive signatures or new functions)
- ✓ no SQLite schema migration (`registry.db` untouched)
- ✓ no test deletions (1 R1 stub-assertion was rewritten in R2,
  not deleted; coverage strengthened)
- ✓ no `candidate_registry` state-machine changes (S0/S1/S2/S5
  remained 4-state)
- ✓ no `core/research/frozen_spec.py` modifications
- ✓ no frozen candidate spec modifications (only NEW
  `<id>_robustness_window.yaml` files added)
- ✓ no `data/daily/*.parquet` rebuilds
- ✓ no `data/ref/splits.parquet` modifications
- ✓ no work outside R1-R7 scope

---

## 6. Re-freeze status

Per the unfreeze memo (`docs/memos/20260425-oos_framework_unfreeze.md`)
the OOS-framework workstream **automatically re-freezes** when this
memo is committed and `<promise>OOSMVPDONE</promise>` emits. Re-opening
forward-OOS work (the R5 schema's runner side) requires:

1. A fresh user decision (this MVP did not authorize forward execution)
2. Likely a new PRD round (forward runner has its own constraints
   beyond what PRD v3 §B sketched)
3. Resolving the M12 `manual_review_required` status on both
   candidates first — narrative_permission is frozen for both, so
   no candidate may be promoted further until the user reviews the
   thin-data exposure findings.

The other round-3 freeze items (no universe extension / no new
mining round / no Candidate-3 / no retroactive frozen-spec change /
no new factor in PRODUCTION_FACTORS / no new data tier) remain
frozen — those were never unfrozen by the OOS MVP scope.

---

## 7. What the user should NOT do based on R1-R6 results

- ❌ Treat the +62.76% / +191.57% R2 cum_ret as "candidate validated"
- ❌ Promote either candidate past S2_paper_candidate based on
  these numbers
- ❌ Write any new memo / report / external doc that frames R2 as
  "OOS evidence", "deployable", or "robustness strengthened"
  (per PRD v3 §C line 303 — narrative permission is frozen for
  both candidates)
- ❌ Disable / loosen the R5 schema's `evidence_class == forward_oos`
  hard invariant to ship a "forward_oos" manifest without forward bars

## 8. What the user CAN do

- ✓ Use M12 findings (thin_data_share extreme) as a real signal
  that the underlying watch-list / thin-data data quality affects
  candidate apparent strength → motivate next-round data
  improvements
- ✓ Keep both candidates at S2_paper_candidate (no demotion needed
  — narrative permission frozen ≠ candidate revoked)
- ✓ When ready, open a **new** PRD round to design + ship the
  forward runner; the R5 schema is ready to receive its output
- ✓ Re-run `dev/scripts/oos_mvp/smoke.py` after any future change
  to verify the contracts still hold (CI-friendly, exit 0/1)

---

## 9. Promise

`<promise>OOSMVPDONE</promise>` will be emitted at the top level
of the R7 assistant-turn reply per PRD §3 R7 explicit harness
contract (in-doc promise alone does not close the loop).

## 10. Key references

- PRD v3: `docs/prd/20260425-oos_validation_framework_codex_v3.md`
- Execution PRD: `docs/prd/20260425-oos_mvp_ralph_loop_execution.md`
- Unfreeze authorization: `docs/memos/20260425-oos_framework_unfreeze.md`
- Per-round Chinese reports: `docs/20260420-ralph_loop_log.md`
  (sections `R-oos-mvp-2026-04-25-round-{01..06}`)
- Round-3 close memo (data-integrity context):
  `docs/memos/20260425-data_integrity_round3_close.md`
- Smoke runner: `dev/scripts/oos_mvp/smoke.py`
- CLI entry for robustness eval re-run:
  `dev/scripts/oos_mvp/run_robustness_eval.py`
