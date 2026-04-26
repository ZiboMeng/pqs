# M12 Review Decision — Path B (weighted thin-data gate)

**Date**: 2026-04-25 (post-OOSMVPDONE)
**Authorized by**: user (zibo) — explicit Path B selection with detailed
spec ("拍板 B"); this constitutes a narrow re-authorization of OOS
MVP scope solely for the M12 thin-data metric fix. Does NOT reopen
universe / mining / Candidate-3 / forward-OOS execution / any other
auto-re-frozen workstream.
**Lineage tag**: `oos-mvp-2026-04-25-audit`
**Supersedes**: M12 numbers in
`docs/memos/20260425-oos_mvp_close.md` §3 (which reflect the pre-fix
binary semantics; binary numbers still discoverable in the artifacts
under `thin_data_binary_share`).

---

## 1. Decision

**Adopt Path B**: the M12 `thin-data exposure` gate metric is
redefined from a binary "any-thin-history symbol" share to a
weight-day-weighted share that scales linearly with each symbol's
actual thin-data fraction.

Old metric (binary, pre-2026-04-25):

  `thin_data_binary_share = Σ_{s ∈ thin_set} weight_day_share[s]`

  where `thin_set = {symbol : thin_data_pct[symbol] > 0}`

New metric (weighted, post-2026-04-25 — **the gate**):

  `thin_data_weighted_share = Σ_s weight_day_share[s] × thin_data_pct[s]`

PRD v3 §C extreme thresholds (>5% warning, >10% extreme) now compare
against the WEIGHTED metric. The binary metric is kept on the report
as a diagnostic for backward comparability with pre-fix artifacts;
it does NOT participate in tier classification.

## 2. Why

The pre-fix binary gate counted a symbol's FULL weight-day share
the moment that symbol had ANY thin-data history, even if 95% of
its bars were clean. This produced systematic over-counting:

- A symbol with 5% thin history and 30% weight contributed 30% to
  `thin_data_binary_share` (sky-high).
- The same symbol's true PnL dependence on thin bars is closer to
  30% × 5% = 1.5%.

Real candidate impact:

| Candidate | binary share (pre-fix) | weighted share (post-fix) |
|-----------|-----------------------:|--------------------------:|
| RCMv1 | 56.86% | 14.97% |
| Cand-2 | 28.48% | 5.19% |

Both candidates were `manual_review_required` + `narrative_permission:
frozen` under the pre-fix gate. Under the post-fix weighted gate:

- **RCMv1**: weighted 14.97% > 10% extreme → **still
  manual_review_required + frozen**. The extreme status is real, not
  implementation false-positive — RCMv1 has heavy weight-day exposure
  (QUAL 9.6%, SOXL 8.1%, MTUM 5.8%, KLAC 5.5%) on symbols whose own
  thin_data_pct is in the 20-32% range, so the weighted product is
  still material.
- **Cand-2**: weighted 5.19% ∈ (5%, 10%) → **warning, narrative
  permission ALLOWED**. The pre-fix `manual_review_required` was
  largely an implementation artifact. Cand-2's exposure is more
  diluted (top contributor SOXL 9.3% × thin_pct 19.6%) and to symbols
  with lower thin_data_pct on average.

The audit therefore separates the two candidates' problem character
cleanly:

- Cand-2 unfreezes by virtue of an honest metric.
- RCMv1's freeze persists, attributable to genuine watch-list
  exposure rather than implementation gloss.

## 3. Implementation summary

### Renamed / added fields on `ConcentrationReport`

- ❌ removed: `thin_data_total_share` (was binary; ambiguous semantics)
- ✅ added: `thin_data_weighted_share` (gate metric)
- ✅ added: `thin_data_binary_share` (diagnostic only; equals the
  pre-fix `thin_data_total_share`)

### Tier classification (`_classify`)

`_classify` now takes `thin_data_weighted` instead of the unqualified
`thin_data`. Warning / extreme thresholds unchanged in numeric value
(per PRD v3 §C lines 285, 293) but applied to the weighted metric.

### `compute()` signature additions

New keyword `thin_data_pct_map: Optional[Mapping[str, float]] = None`
feeds the weighted share. Sidecar values may be passed in either
fraction form (0–1) or percent form (0–100); the function normalizes
percent-scale to fraction form (divides by 100 if any value > 1).

### Runner integration

`core/research/robustness/runner.py::_load_watch_symbols` now returns
a 3-tuple `(watch_symbols, thin_data_symbols, thin_data_pct_map)`.
The map is constructed from `data_quality_watch.parquet`'s
`thin_data_pct` column with a `/100` normalization since the sidecar
stores percent values (verified empirically:
`thin_data_pct=58.28` → 58.28%).

### Markdown rendering

`_format_md` now shows BOTH metrics with explicit "(gate metric)" /
"(diagnostic, pre-2026-04-25 definition)" labels. The Caveats section
gains a new bullet explaining the semantic split + linking back to
this memo.

### Watch exposure section (`watch_exposure.py`)

The prose in the master + drift report now reads:

> Candidate has X% weight-day-share on watch-list names over N eval
> days; thin-data WEIGHTED share (gate) Y%, thin-data binary share
> (diagnostic) Z%; watch-list sidecar reports A thin_data flagged
> symbol-days and B quarantined symbol-days summed across all watch
> symbols (NOT unique calendar days).

The "symbol-days" / "NOT unique calendar days" clarifications address
the readability concern raised in the audit (P2 finding).

## 4. Regression test contract

`tests/unit/research/test_concentration.py` ships 4 new cases pinning
the audit fix:

A. `test_weighted_thin_metric_correctly_dilutes_low_thin_pct_symbols`
   — large weight × tiny thin_pct: binary >> weighted; weighted gate
   does not falsely fire.
B. `test_weighted_gate_demotes_cand2_style_from_extreme_to_warning`
   — uniform 6+6 panel, watch thin_pct=0.12 → binary ~50% (would
   extreme-trip pre-fix), weighted = 6%, gate = **warning** + allowed.
C. `test_weighted_gate_keeps_rcm_v1_style_in_extreme` — same
   uniform panel but watch thin_pct=0.30 → weighted = 15%, gate =
   **manual_review_required** + frozen.

Plus `test_weighted_share_handles_percent_scale` — verifies the
auto-normalize-from-percent path works (0–100 input → 0–1 internal).

The two existing thin-data tests (`test_thin_data_warning` /
`test_thin_data_extreme`) were body-rewritten in place to drive the
weighted gate (NOT deleted; coverage preserved).

`test_md_renders_status_and_caveats` adds two new substring asserts:
"WEIGHTED share (gate metric)" and "binary share (diagnostic" must
appear in the rendered markdown — locks the explicit-labeling
contract.

`smoke.py` schema check now requires both new fields and no longer
recognizes the legacy `thin_data_total_share`.

## 5. Pytest tuple drift

| stage | passed | skipped | xfailed | xpassed |
|-------|-------:|--------:|--------:|--------:|
| pre-audit-fix (post-OOSMVPDONE + commit `31b128f`) | 1681 | 1 | 0 | 1 |
| post-audit-fix | 1685 | 1 | 0 | 1 |

Drift = +4. Composition:

- `test_weighted_thin_metric_correctly_dilutes_low_thin_pct_symbols` (new)
- `test_weighted_gate_demotes_cand2_style_from_extreme_to_warning` (new)
- `test_weighted_gate_keeps_rcm_v1_style_in_extreme` (new)
- `test_weighted_share_handles_percent_scale` (new)

Two existing tests body-rewritten (not new tests, no count delta).

## 6. Re-run scope

This audit fix touched only:

- `core/research/concentration/report.py` — semantics fix
- `core/research/concentration/watch_exposure.py` — prose update
- `core/research/robustness/runner.py` — sidecar load + pass map
- `tests/unit/research/test_concentration.py` — 4 new + 2 rewritten
- `tests/unit/reporting/test_watch_exposure_section.py` — fixture field rename
- `tests/integration/test_oos_mvp_smoke.py` — fixture field rename
- `dev/scripts/oos_mvp/smoke.py` — schema check field rename
- `data/research_candidates/<id>_concentration_report.{json,md}` (×2) — re-run output
- `data/research_candidates/<id>_robustness_eval.{json,md}` (×2) — re-run output (timestamp refresh)
- `data/research_candidates/<id>_robustness_window.yaml` (×2) — re-run output (timestamp refresh)

**Not touched** (per user direction "重跑的范围要收敛"):

- Universe / mining / Candidate-3
- Forward execution
- Frozen candidate specs
- `data/daily/*.parquet`
- `data/ref/*.parquet`
- `config/*.yaml`
- `core/research/frozen_spec.py`
- `core/factors/factor_registry.py::PRODUCTION_FACTORS`
- `requirements*.txt` / `pyproject.toml`

All HARD invariants from the original OOS MVP PRD remain held.

## 7. Status delta

| Candidate | pre-fix gate_status | post-fix gate_status | pre-fix narrative_permission | post-fix narrative_permission |
|-----------|---------------------|----------------------|------------------------------|--------------------------------|
| RCMv1 | manual_review_required | manual_review_required | frozen | frozen |
| Cand-2 | manual_review_required | warning | frozen | **allowed** |

Cand-2 is therefore **unfrozen for narrative permission** under the
audit-corrected metric. RCMv1's freeze stands and represents a real
finding — the user can now make a clean separation between
"implementation false-positive" (Cand-2's old freeze) and "real
exposure problem" (RCMv1's persistent freeze).

## 8. What this DOES NOT authorize

- Promoting Cand-2 past S2_paper_candidate (still S2; warning state
  is informational; further promotion needs forward-OOS evidence,
  which the MVP did not deliver — see closeout memo §1).
- Reopening forward execution (still requires a fresh PRD round).
- Changing universe membership (RCMv1's persistent extreme is a
  finding, not an action item — universe edits remain out-of-scope).
- Reopening mining or producing Candidate-3.

## 9. Next steps (informational, not authorized here)

User's audit synthesis prioritizes:

1. **Forward OOS runner** — turn R5 schema into a real
   forward-observation engine with 10/20/40/60d checkpoint pipeline.
   Highest ROI for "reach a deployable system" objective.
2. **Complete M12 sector + benchmark beta concentration** — currently
   `not_computed`; sector exposure can be a real risk even when
   single-name concentration looks fine.
3. **README / CLAUDE.md doc drift cleanup** — pricing semantics
   section still references yfinance; round-3 step-3b made polygon
   1m the canonical source. Treatment: P2 governance task, not
   blocking.
4. Reopen mining / universe only after items 1-2 land.

These are the user's explicit ordering; this audit fix is the
prerequisite (P0) above all of them.

## 10. References

- Closeout memo: `docs/memos/20260425-oos_mvp_close.md`
- Unfreeze authorization: `docs/memos/20260425-oos_framework_unfreeze.md`
- PRD v3: `docs/prd/20260425-oos_validation_framework_codex_v3.md`
  §C lines 281-294 (numeric thresholds — unchanged)
- Round-3 close memo (data-integrity context):
  `docs/memos/20260425-data_integrity_round3_close.md`
- Per-round Chinese reports for R1-R7:
  `docs/20260420-ralph_loop_log.md` sections
  `R-oos-mvp-2026-04-25-round-{01..07}`
