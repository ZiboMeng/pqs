---
round: 01
phase: A
scope: A1 — forward evidence module audit (5 modules contract re-derivation + 4 live e2e + reverse-validate v2.1.3 fixes)
status: FIX_LANDED
blocker_count: 0
non_blocker_count: 1
docs_only_count: 2
cosmetic_count: 1
commits: TBD (CLAUDE.md update + audit harness)
review_commit: TBD
parent_round: none (first round)
---

# Round 1 (A1) — forward evidence module audit

## What I read

- `core/research/forward/bar_hash.py` (603 lines) — full re-read; contract for `resolve_factor_input_contract`, `compute_signal_input_hash`, `compute_execution_nav_hash`, `compute_benchmark_hash`, `compute_bar_hash_rollup`, `_resolve_lookback_window_start`, `_capture_anchor_values`, `_FACTOR_REGISTRY`.
- `core/research/forward/revalidate.py` (549 lines) — full re-read; contract for `revalidate_manifest`, `_revalidate_entry`, E1-E5 escalation table, materiality threshold constants + epsilon tolerances.
- `core/research/forward/runner.py` (862 lines) — full re-read; contract for `init`, `observe`, `status`, `decide`, `_first_post_freeze_trading_day`, `_resolve_dates_to_observe`, `_next_status_after_observe`, `_verify_cost_hash_or_halt`, `ForwardHaltError`.
- `core/research/forward/source_layer.py` (127 lines) — full re-read; contract for `classify_window`, `classify_as_of`, `aggregate_window_layers`.
- `core/research/forward/manifest_schema.py` (329 lines) — full re-read; pydantic models `ForwardRunStatus`, `CostAssumptions`, `CheckpointCadence`, `PerScopeHashInputs`, `BarHashInputs`, `SourceLayerView`, `SourceLayerBreakdown`, `DataRevisionEvent`, `ForwardRun`, `ForwardRunManifest`.
- PRD `docs/prd/20260427-forward_evidence_hardening_prd.md` v2.1.3 changelog (top 130 lines); cross-checked every changelog claim against shipped code.

## What I ran (live e2e against real BarStore + non-mutating synthetic manifests)

Audit harness: `dev/audit/r1_a1_forward_e2e.py`. Real `data/daily/*.parquet` panel for `["AAPL", "MSFT", "NVDA", "TSLA", "SPY", "QQQ"]`, end=2026-04-27 (2845 close rows). Live `RCMv1` frozen spec at `data/research_candidates/rcm_v1_defensive_composite_01.yaml`. NO live RCMv1 / Cand-2 manifest was mutated.

```
$ PYTHONPATH=. python dev/audit/r1_a1_forward_e2e.py
==============================================================================
R1 / A1 — forward evidence module audit (live e2e)
==============================================================================
panel: 5 attrs, 2845 close rows ≤ 2026-04-27

────────────────────────────────────────────────────────────
S1 — clean revalidate: no revisions, expect 0 events
────────────────────────────────────────────────────────────
  events: 0
  n_runs_checked: 1
  requires_data_review: False
  PASS: True

────────────────────────────────────────────────────────────
S2 — sub-threshold held in-ring revision (track_per_cell=True)
     expect flagged_only (NAV impact < 10 bps via populated digest)
────────────────────────────────────────────────────────────
  policy_decision: flagged_only
  estimated_nav_impact_bps: 2.5
  affected_scopes: ['execution_nav', 'signal_input']
  delta_summary: scopes=['execution_nav', 'signal_input']; n_revised_cells=2; materiality_class=in_ring; triggers=[]
  PASS: True

────────────────────────────────────────────────────────────
S3 — Blocker-1: revise TRUE 252nd prior trading day
     pre-v2.1.3 BDay window misses this row by ~9 trading days
     expect: signal_input_hash flips, summary detects diff
────────────────────────────────────────────────────────────
  true 252nd prior: 2025-04-25
  BDay(252) start:  2025-05-08  (gap = 13 days)
  events: 1
  affected_scopes: ['signal_input']
  policy_decision: invalidated
  PASS: True

────────────────────────────────────────────────────────────
S4 — Blocker-2: empty signal_input.per_cell_digest +
     dual-scope (signal+exec_nav) diff -> invalidated (bound_only)
────────────────────────────────────────────────────────────
  policy_decision: invalidated
  estimated_nav_impact_bps: None
  affected_scopes: ['execution_nav', 'signal_input']
  bound_only triggered: True
  empty per_cell_digest mention: True
  PASS: True

==============================================================================
RV1 — Blocker-1 reverse-validation: monkey-patch BDay back
==============================================================================
  buggy BDay logic, mutate AAPL/2025-04-25/close:
    h_pre  = 8a682944e8d7eb48515c21f3
    h_post = 8a682944e8d7eb48515c21f3
  hash collision (bug present): True
  RV1 PASS: True
  fix re-applied, hash flips on revision: True
  RV1 close: True

==============================================================================
RV2 — Blocker-2 reverse-validation: monkey-patch revalidate's
       empty-digest path back to optimistic gating on exec_nav
==============================================================================
  buggy logic policy_decision: flagged_only
  buggy logic NAV impact bps: 2.5
  pre-fix UNDER-classified as flagged_only: True
  RV2 PASS: True
  fix re-applied, same revision -> invalidated
  RV2 close: True

==============================================================================
R1 / A1 final summary
==============================================================================
  PASS: S1 clean
  PASS: S2 sub-threshold flagged_only
  PASS: S3 Blocker-1 252nd-prior detect
  PASS: S4 Blocker-2 dual-scope invalidated
  PASS: RV1 Blocker-1 reverse-validate
  PASS: RV2 Blocker-2 reverse-validate

OVERALL: PASS
```

Forward unit suite:

```
$ python -m pytest tests/unit/research/test_forward_*.py
======================== 96 passed in 275.83s (0:04:35) ========================
```

## Issues found

| ID | Severity | File:Line | Description | Fix |
|----|----------|-----------|-------------|-----|
| R01.1 | non-blocker | `core/research/forward/runner.py:169-173, 228` | `_first_post_freeze_trading_day` UTC-hour heuristic uses fixed `_NYSE_CLOSE_UTC_HOUR=20`. Correct for DST summer (16:00 EDT = 20:00 UTC) but WRONG for winter EST (16:00 EST = 21:00 UTC). Winter freezes between 20:00–21:00 UTC = 15:00–16:00 EST (i.e., 0–60 min PRE-close) would be incorrectly classified as POST-close, advancing `start_date` by 1 trading day too early. Narrow blast radius: no current candidate hits it (RCMv1 + Cand-2 both frozen in April DST window). | Deferred — proper fix needs `zoneinfo` / `pytz` America/New_York DST-aware comparison; out-of-scope for forward-evidence audit. Surface to B5 (strategy + execution lens) or a dedicated narrow PR. |
| R01.2 | docs-only | `core/research/forward/runner.py:169-172` | Comment claims "20:00 UTC during winter EST, 19:00 UTC during DST" — actual NYSE close is 21:00 UTC winter / 20:00 UTC summer. Comment is consistently off by 1 hour. Same root cause as R01.1. | Deferred (paired with R01.1 fix). Standalone doc fix is cosmetic without addressing the hour constant. |
| R01.3 | docs-only | `CLAUDE.md:594-626` "Forward OOS active workstream" | Section claimed "evidence-hardening done v2.1" with commits `c3cefc1` → `5cd51f3` and "51 → 86 tests; full unit suite 1772 passed". Stale: did not reflect v2.1.1 audit round 1 (`fd24285`), v2.1.2 audit round 2 (`7c7f860`, `e942ab9`), v2.1.3 codex Round-10 blocker fixes (`4abc3c9`, `051d869`). Forward slice is now 96 tests; full unit suite 1782. | **FIXED this round** — CLAUDE.md updated to layered v2.1 → v2.1.1 → v2.1.2 → v2.1.3 progression with full commit lineage and current test counts. |
| R01.4 | cosmetic | `core/research/forward/revalidate.py:124-130` | `_signed_drift` defined but unused (no callers in `core/`, `tests/`, or `scripts/`). Dead code. | Defer to B7 final consolidation; minor and may legitimately stage future signed-drift threading per codex Round-10 §"Non-blocking answer #2". |

## Fixes shipped + reverse-validation

### R01.3 — CLAUDE.md "Forward OOS active workstream" sync to v2.1.3

**Before** (stale, claims v2.1 with 51→86 tests / 1772 unit suite):

```
- **R-fwd-2 / R-fwd-3 evidence-hardening done (2026-04-28 ✅)** —
  per `docs/prd/20260427-forward_evidence_hardening_prd.md` v2.1
  (codex Round 6→9). Implemented in 5 commits on `main`
  (`c3cefc1` → `5cd51f3`):
  ...
  Forward slice: 51 → 86 tests; full unit suite 1772 passed.
```

**After** (v2.1.3 layered changelog):

```
- **R-fwd-2 / R-fwd-3 evidence-hardening SHIPPED v2.1.3 (2026-04-28 ✅)** —
  per `docs/prd/20260427-forward_evidence_hardening_prd.md`. Five
  layered commits on `main`:
  1. **v2.1 base** (`c3cefc1` → `5cd51f3`, codex Round 6→9): ...
  2. **v2.1.1 audit round 1** (`fd24285`): ...
  3. **v2.1.2 audit round 2** (`7c7f860`, `e942ab9`): ...
  4. **v2.1.3 codex Round-10 blocker fixes** (`4abc3c9`, `051d869`):
     - Blocker 1: ...
     - Blocker 2: ...
     - Adjacent: ...
  Forward slice: 51 → 96 tests; full unit suite 1782 passed.
```

**Reverse-validation.** This is a docs-only fix (no code changed), so the standard revert-reproduce-reapply protocol does not apply. The "bug" was: a reader trusting CLAUDE.md verbatim would not know the Round-10 fixes shipped. Pre-fix grep for `v2\.1\.[0-9]` against CLAUDE.md returned 0 lines (only `v2.1` mentioned). Post-fix:

```
$ grep -n "v2\.1\.[0-9]" CLAUDE.md
594:- **R-fwd-2 / R-fwd-3 evidence-hardening SHIPPED v2.1.3 (2026-04-28 ✅)** —
606:  2. **v2.1.1 audit round 1** (`fd24285`): 4 self-audit fixes
609:  3. **v2.1.2 audit round 2** (`7c7f860`, `e942ab9`): Bug 5 fix
613:  4. **v2.1.3 codex Round-10 blocker fixes** (`4abc3c9`, `051d869`):
624:  Forward slice: 51 → 96 tests; full unit suite 1782 passed.
626:- **Status: observation mode resumes**. Daily `forward observe`
```

### v2.1.3 fix re-validation (RV1 + RV2)

The audit harness explicitly reproduced the pre-fix bugs by monkey-patching the v2.1.3 fix points and re-running the affected revalidate path:

- **RV1 (Blocker 1)**: revert `_resolve_lookback_window_start` to BDay arithmetic → mutating `AAPL/2025-04-25/close` (the true 252nd prior trading day at as_of=2026-04-27) does NOT flip `signal_input_hash` (collision on `8a682944e8d7eb48515c21f3`). Re-apply the trading-day-row resolver → same mutation flips the hash. Bug is real, fix is real.
- **RV2 (Blocker 2)**: revert revalidate's empty-digest fail-close to the pre-fix optimistic gating (skip bound_only when execution_nav also differs) → 0.05% AAPL close revision under production-default empty `per_cell_digest` produces `policy_decision="flagged_only"` with `estimated_nav_impact_bps=2.5`. Re-apply the unconditional empty-digest fail-close → same revision → `invalidated`. Bug is real, fix is real.

## Doc-vs-code reconciliation

- **CLAUDE.md** "Forward OOS active workstream" — **fixed this round** (R01.3). v2.1 → v2.1.3 progression with full commit lineage now documented.
- **docs/INDEX.md** — already current (commit `1ec92f0` reclassified the forward evidence PRD as `SHIPPED v2.1.3`). No change needed.
- **README.md** — does NOT mention forward observation / evidence hardening at all (forward is a research-internal capability, not user-facing). Out of A1 scope; A3 will sweep README globally.
- **PRD `docs/prd/20260427-forward_evidence_hardening_prd.md`** — already current at v2.1.3 (commit `051d869`). No change needed.

## Cross-round meta-check

N/A — first round (no prior memos to re-engage).

## Readiness signal

ROUND 01 CLOSED, NEXT: 02

Acceptance: zero blocker findings. The 1 non-blocker (R01.1 DST UTC-hour) and 2 docs-only / 1 cosmetic findings are all surfaced; R01.3 (the docs-only that touched CLAUDE.md sync) was fixed within the round per A1 contract. R01.1 / R01.2 deferred to a later phase per their respective scopes (DST is strategy/execution layer concern, not forward-evidence hash).
