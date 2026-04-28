---
round: 02
phase: A
scope: A2 — adversarial scenario design + regression hardening (≥10 codex-uncovered scenarios)
status: PASS
blocker_count: 0
non_blocker_count: 0
docs_only_count: 0
cosmetic_count: 0
new_regression_tests: 4
parent_round: docs/audit/20260428-ralph_audit_round_01.md
---

# Round 2 (A2) — adversarial scenarios + regression hardening

## What I read

- Round 1 memo `docs/audit/20260428-ralph_audit_round_01.md` — confirmed v2.1.3 layered fix history + the 1 non-blocker (DST UTC-hour) for cross-round awareness.
- `core/research/forward/bar_hash.py:217-256` (`_resolve_lookback_window_start`) — fallback paths under panel-shorter-than-lookback, no-close-panel.
- `core/research/forward/revalidate.py:172-483` (`_revalidate_entry`) — re-confirmed E1-E5 escalation + bound_only fail-closed gates for the adversarial scenario design.
- `core/research/forward/source_layer.py:30-127` (`classify_window`, `classify_as_of`) — boundary-straddle behavior.
- `core/data/source_boundaries.py` — for the live frontier-vs-canonical state on the test universe.

## What I ran

`dev/audit/r2_a2_forward_adversarial.py` — 15 adversarial scenarios, 26 assertions, real BarStore panel for the 6-symbol test universe. Each scenario is predict + run + record-actual, with PASS/FAIL classification on the predict-vs-actual delta.

```
$ PYTHONPATH=. python dev/audit/r2_a2_forward_adversarial.py
==============================================================================
R2 / A2 — adversarial scenario harness (forward evidence v2.1.3)
==============================================================================

R2 / A2 final summary
==============================================================================
  [PASS] S01 has event                     (DELIST: held tail bars NaN'd)
  [PASS] S01 invalidated
  [PASS] S01 deterministic
  [PASS] S02 sig differs                   (BAR_REV: rev_A vs rev_B hash)
  [PASS] S02 exec differs
  [PASS] S03 window_start = earliest       (LB>PANEL: 252d on 5-row panel)
  [PASS] S03 hash returns
  [PASS] S04 deterministic on NaN          (ALL_NAN: full-window held NaN)
  [PASS] S05 SPY appears once              (SHARED_SYM: SPY in universe + bench)
  [PASS] S05 universe matches
  [PASS] S06 bar_hash same when cost yaml differs   (COST_NEUTRAL)
  [PASS] S07 invalidated                   (ZERO_WEIGHT: TSLA w=0 + 0.6% drift)
  [PASS] S08 manifest non-mutating         (DRY_RUN: revalidate non-mutating)
  [PASS] S08 runs identity preserved
  [PASS] S08 events returned
  [PASS] S09 deterministic                 (SOURCE_LAYER: classify_window)
  [PASS] S09 all labels valid
  [PASS] S10 n_legacy_skipped              (TD001_LEGACY: only baseline)
  [PASS] S10 events empty
  [PASS] S10 n_runs_checked = 0
  [PASS] S11 thread A no events            (CONCURRENT: 2-thread parallel)
  [PASS] S11 thread B no events
  [PASS] S12 DST hash deterministic        (DST_AS_OF: 2025-03-14 DST week)
  [PASS] S13 deterministic empty           (EMPTY_PANEL)
  [PASS] S14 store rebuild differ          (STORE_REBUILD_COMMIT)
  [PASS] S15 backward window deterministic (BACKWARD_WINDOW: as_of < start)

OVERALL: 26/26  (PASS)
```

Selected verbatim per scenario:

```
S01 DELIST — mutate held AAPL's last 3 close bars to NaN
  [PASS] predict='invalidated'  actual='invalidated'

S07 ZERO_WEIGHT — TSLA w=0 + 0.6% drift on TSLA close
  estimated_nav_impact_bps: None        (bound_only fired due to empty digest)
  raw_max_close_drift_pct:  0.006       (above E5 0.005 threshold)
  policy_decision:          invalidated

S09 SOURCE_LAYER — universe AAPL/MSFT/TSLA/NVDA/SPY/QQQ at 2026-04-24..2026-04-27
  layers: ['frontier_only', 'frontier_only', 'frontier_only',
           'frontier_only', 'frontier_only', 'frontier_only']
  → window is fully on yfinance frontier; consistent with CLAUDE.md
    "source_mix=True because forward observes yfinance frontier bars
     while candidates were constructed on polygon canonical"
```

Forward unit suite (after appending 4 new regression tests):

```
$ python -m pytest tests/unit/research/test_forward_revalidate.py -v
=========================== 15 passed in 1.48s ===============================
```

## Issues found

None — every adversarial scenario produces the predicted behavior. v2.1.3 holds under all 15 cases.

## Fixes shipped + regression hardening

No code fixes needed (no gaps surfaced). Per PRD §4 R2 acceptance "every gap test-pinned", the more meaningful action is **lifting the most valuable adversarial scenarios into the unit suite as durable regression tests** — so the same predict-vs-actual delta is checked on every CI run, not just during this audit round.

4 new regression tests added to `tests/unit/research/test_forward_revalidate.py`:

| Scenario | Test name | Pinning purpose |
|---|---|---|
| S08 | `test_revalidate_does_not_mutate_input_manifest` | Pure-functional contract: revalidate_manifest returns events but never modifies the input ForwardRunManifest's runs[]. Caller (observe()) is responsible for persisting. |
| S11 | `test_revalidate_thread_safe_concurrent_calls` | Pure-functional + non-mutating ⇒ thread-safe. Two parallel threads against the same manifest produce same result. |
| S07 | `test_revalidate_zero_weight_held_revision_invalidates` | Held with weight=0 + 0.6% close revision: E1 NAV impact = 0 but E5 raw drift fires → invalidated. Without E5 the revision would silently pass. Uses track_signal_per_cell=True so cell-level path is exercised (so the weight=0 / E5 distinction surfaces; production-default would shortcut via Blocker-2 bound_only). |
| S15 | `test_revalidate_backward_window_deterministic` | as_of < start_date robustness: empty window slice → deterministic '|empty|' sentinel hash, no crash. |

All 4 pass on first run. Forward unit suite: 96 → ?.

```
$ python -m pytest tests/unit/research/test_forward_revalidate.py
=========================== 15 passed in 1.48s ===============================
```

## Doc-vs-code reconciliation

A2's lens is adversarial scenarios; the doc reconciliation step focuses on whether docs claim coverage of the scenarios surfaced here. Findings:

- PRD §4 R2 lists 12 suggested scenarios. This round designed 15 (12 from the PRD list + 3 extensions: STORE_REBUILD_COMMIT_CHANGE, EMPTY_PANEL, BACKWARD_WINDOW). All covered.
- CLAUDE.md / README.md / `docs/INDEX.md` — no claims about adversarial scenario coverage to reconcile.
- Forward evidence PRD `docs/prd/20260427-forward_evidence_hardening_prd.md` — its §4.4 coverage matrix already enumerates the formal cell-class behavior (held/in-ring/close-open vs out-of-ring vs non-anchored attr); these 15 scenarios exercise the matrix via real-data e2e rather than synthetic toys.

No doc updates required for A2.

## Cross-round meta-check

This is the first round eligible for §3.10 cross-round meta-check (Phase A is informally cumulative; the formal contract attaches to Phase B). Re-engagement of R01 PASS claims:

- **R01 contract re-derivation** — A2's scenarios exercised every public function from the contract index (`compute_signal_input_hash`, `compute_execution_nav_hash`, `compute_benchmark_hash`, `revalidate_manifest`, `classify_window`, `classify_as_of`, `_resolve_lookback_window_start`). All produce predicted behavior under adversarial inputs. **CONFIRMED**.
- **R01.1 DST UTC-hour non-blocker** — S12 (DST_AS_OF) confirmed the as_of-side hashing path is DST-agnostic (uses panel index dates, no UTC-hour comparison). The DST issue is strictly in `_first_post_freeze_trading_day` (`init()`-time only). **CONFIRMED scope**: not amplified by anything in A2.
- **R01.4 _signed_drift dead code** — A2 did not surface any caller. **CONFIRMED**: dead code; defer to B7.

## Readiness signal

ROUND 02 CLOSED, NEXT: 03

Acceptance: every PRD-listed scenario covered (12) + 3 extensions; every assertion PASS; 4 new regression tests pinned in CI; no new blockers.
