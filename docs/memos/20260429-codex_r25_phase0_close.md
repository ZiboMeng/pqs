---
date: 2026-04-29
type: memo
status: closed
lineage_tag: codex-r25-phase0-close-2026-04-29
related_prds:
  - docs/prd/20260428-candidate_fleet_allocator_prd.md (v1.1)
related_memos:
  - docs/memos/20260429-track_bc_audit_close.md
  - docs/audit/20260429-codex_round_25_track_bc_review_and_plan.md
---

# Codex R25 Phase 0 close — 2 P0 + 4 P1 fixed (audit-miss acknowledgement)

## Audit miss acknowledgement

Round 24 was my own two-pass audit on Track B + C. I claimed it was
substantive. **Codex Round 25 found 2 P0 + 4 P1 that I missed**.

The misses were not in the work I did — they were in the **audit
methodology itself**:

| Codex finding | What I tested | What I should have tested |
|---|---|---|
| **P0.1** split components | `splits.sum() == 1.0` only | also `0 <= split[i] <= 1` and finite |
| **P0.2** schema mismatch | `FleetManifest` round-trip with hand-built `ConcentrationSnapshot` | `ConcentrationSnapshot(**compute_concentration_metrics(matrix))` integration |
| **P1** ResearchMiner direct API | C5 via real CLI | C5 via direct `ResearchMiner(... split_name=..., role=None)` constructor |
| **P1** role vocabulary divergence | each module in isolation | cross-module: Track A `core/diversifier` vs Fleet `core/satellite` |
| **P1** PRD vs implementation | implementation correctness | also re-read PRD wording vs implementation semantics |

**Lessons internalized for future audits:**

1. **Sum / aggregate validators do not catch component violations.**
   `{1.2, -0.2}` sums to 1.0 ✓ but is long/short. Always test
   adversarial vectors that satisfy aggregate constraints while
   violating component constraints.
2. **Module round-trip is not module integration.** A schema test that
   constructs ``ConcentrationSnapshot(top1=0.18, top3=0.42)`` directly
   says nothing about whether the producer (`compute_concentration_metrics`)
   matches the consumer's contract. Always feed producer-output into
   consumer-input.
3. **CLI guards do not protect direct API.** When a guard lives in a
   script, the underlying class can be constructed directly with the
   same partial state and bypass the guard. Test the constructor
   independently.
4. **Cross-module vocabulary drift is silent.** Two modules each owning
   a `role` field with overlapping but non-identical literal sets
   (`core/diversifier` vs `core/satellite`) needs an explicit translator
   the moment promotion crosses the boundary.
5. **PRD wording vs implementation semantics is a third contract.**
   Tests can pass and audit can find no bugs, while the implementation
   silently diverges from what the PRD promised. Re-read PRD wording
   side-by-side with implementation as part of audit.

## Fixes shipped (Phase 0 narrow patch per codex R25)

### P0.1 — split component validation + post-compose invariants

**File**: `core/fleet/allocator.py:compose_weight_matrix`

Pre-fix (Round 24): only validated `abs(sum(splits) - 1.0) <= 1e-9`.
`{c1: 1.2, c2: -0.2}` accepted; produced `AAPL=1.2, MSFT=-0.2`
(leverage + short).

Post-fix:
- Each split component MUST be finite (no NaN / inf).
- Each split component MUST satisfy `0 <= v <= 1.0 + 1e-9`.
- Sum check (Round 24 BUG #B2/B3) still runs after component check.
- Post-compose: fleet matrix MUST be all-finite, all-non-negative,
  row-sum `<= 1.0 + 1e-6`. These are defense-in-depth checks for
  arithmetic surprise that input validation didn't catch.
- `apply_overlap_throttle` now also rejects negative cells (defense
  in depth — public API can be called by non-Track-B callers).

**Reverse-validation evidence**:

```python
>>> alloc.compose_weight_matrix(cw, splits={"c1": 1.2, "c2": -0.2})
ValueError: splits['c1'] = 1.2 > 1.0; no single candidate may exceed full allocation...

>>> alloc.compose_weight_matrix(cw, splits={"c1": float("inf"), "c2": -float("inf") + 1.0})
ValueError: splits['c1'] = inf; must be finite. Non-finite split components corrupt the entire fleet matrix.

>>> alloc.compose_weight_matrix(cw, splits={"c1": -0.1, "c2": 1.1})
ValueError: splits['c1'] = -0.1 < 0; long-only no-margin invariant requires every split component >= 0...
```

**Tests added**: 6 in `test_compose_weight_matrix.py` + 1 in
`test_overlap_and_metrics.py` (negative-cell rejection in throttle).

### P0.2 — `ConcentrationSnapshot` schema includes `m12_n_dates_with_weights`

**File**: `core/fleet/manifest_schema.py:ConcentrationSnapshot`

Pre-fix: schema had only `m12_top1_weight_max` and `m12_top3_weight_max`
with `extra="forbid"`. `compute_concentration_metrics()` returned three
keys including `m12_n_dates_with_weights`. Calling `ConcentrationSnapshot(
**metrics)` failed with `extra_forbidden`.

Post-fix: schema declares `m12_n_dates_with_weights: int = Field(ge=0)`.
Producer output now feeds directly into consumer schema.

**Reverse-validation evidence**:

```python
>>> metrics = alloc.compute_concentration_metrics(fleet)
>>> ConcentrationSnapshot(**metrics)  # post-fix: succeeds
m12_top1_weight_max=0.18 m12_top3_weight_max=0.18 m12_n_dates_with_weights=1
```

**Tests added**: `test_compute_concentration_metrics_feeds_directly_into_schema`
in `test_overlap_and_metrics.py` — full producer→consumer→manifest→
load round-trip without manual key surgery.

### P1 — `ResearchMiner.__init__` temporal-tuple validation

**File**: `core/mining/research_miner.py`

Pre-fix: CLI script enforced `--temporal-split` requires `--role`, but
direct `ResearchMiner(... split_name="v1", split_sha256="h", role=None)`
silently set the C5 guard's `role` check to None and bypassed
enforcement.

Post-fix: `__init__` rejects partial temporal-fingerprint tuples. If
ANY of `{split_name, split_sha256, role}` is provided, ALL three must
be provided. Pure legacy mining (all three None) still works.

**Tests added**: 5 in `test_research_miner_temporal_tuple.py` —
split-only, role-only, split+sha-no-role (the exact bypass codex
flagged), complete tuple accepted, legacy accepted.

### P1 — Track A ↔ Fleet role vocabulary bridge

**File**: `core/fleet/manifest_schema.py`

Pre-fix: Track A used `core/diversifier`; Fleet used `core/satellite`.
Both shared `core` semantically. The labels diverged for the secondary
role because Track A's name reflects the GOVERNANCE constraint (a
diversifier must demonstrate low correlation to existing core to be
eligible) while Fleet's name reflects the ALLOCATION semantic
(satellite sleeve is the ≤ 40% capacity outside core). No bridge
existed; promotion would either silently re-use the Track A label
(rejected by Fleet's pydantic literal) or silently re-interpret it
without an audit trail.

Post-fix: `TRACK_A_TO_FLEET_ROLE_MAP` dict + `track_a_role_to_fleet_role()`
function exported from `core.fleet`. Unknown Track A roles raise
`ValueError` with explicit pointer to extend the map and document the
new role's mapping. Prevents silent re-interpretation at promotion.

**Tests added**: 3 in `test_fleet_schema.py` — core passes through,
diversifier→satellite, unknown role rejected.

### P1 — C3 PRD sync (cash-clip v1 semantics)

**File**: `docs/prd/20260428-candidate_fleet_allocator_prd.md` §4.3

Pre-fix: PRD said "proportionally trimmed across the contributing
candidates (not just clipped at the sum) — this preserves the relative
exposure intent of each candidate". Implementation in Step 4 actually
clipped fleet-level cells and dropped excess to cash.

Post-fix: PRD now documents **cash-clip v1 semantics** as the accepted
v1 behavior, with rationale (long-only no-margin invariant; clean
composition with future C5 throttle; defers contribution-aware
attribution to v2). Includes explicit "v2 plan" line so the deferral
is auditable.

## Tests

- Targeted Phase 0 + integration suite: **83 passed** (62 pre-R25 +
  6 P0.1 component + 1 P0.1 throttle + 1 P0.2 integration + 5 P1
  ResearchMiner + 3 P1 role bridge + manifest schema fixes)
- Full unit suite: running in background; expected ~2102 (was 2087
  + ~16 net new)

## Phase 0 closes; what stays

Per codex R25 boundary:

- ✅ **Phase 0 narrow follow-up patch**: P0.1 + P0.2 + 4 P1 (this memo)
- ▶️ **Phase 1**: Fleet Step 5 C2 correlation budget — authorized after
  this memo's tests are green
- ▶️ **Track C controlled mining + evidence-pack template**: authorized
  in parallel
- ⏸️ **Step 6+ (DD throttle, role caps, observe)**: stays frozen until
  Step 5 ships
- 🚫 **2026 sealed eval / fleet live wiring / shadow→live**: hard frozen

## Going forward

I am committing to:
1. Always test adversarial vectors that satisfy aggregate constraints
   while violating components.
2. Always test producer→consumer integration, not just isolated module
   round-trips.
3. Always test direct API constructors, not just CLI guards.
4. Always check cross-module vocabulary divergence at promotion
   boundaries.
5. Always re-read PRD wording side-by-side with implementation as part
   of audit.

These five gaps are the audit-discipline lessons from this round.
