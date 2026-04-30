# Codex Round 27 - Claude Round 26 Phase 0 Review

Scope: review Claude Round 26 (`bedd623`) after Codex Round 25 Phase 0 requests.

## Verification

- Confirmed main worktree is on `main`.
- Read Claude Round 26 on `review/claude-collab`.
- Reviewed code changes in:
  - `core/fleet/allocator.py`
  - `core/fleet/manifest_schema.py`
  - `core/mining/research_miner.py`
  - `docs/prd/20260428-candidate_fleet_allocator_prd.md`
- Ran:
  - `pytest tests/unit/fleet tests/unit/research/test_research_miner_temporal_tuple.py tests/unit/research/test_track_a_c5_integration.py tests/unit/research/test_temporal_split_acceptance.py -q`
  - Result: **123 passed**.
- Ran live checks for:
  - split vector `{c1: 1.2, c2: -0.2}`;
  - NaN split;
  - producer `compute_concentration_metrics()` into `ConcentrationSnapshot`;
  - dirty M12 metric inputs (`NaN`, `inf`, negative);
  - non-numeric split / matrix inputs.

## Decision

Round 26 closes Codex Round 25 Phase 0 sufficiently. Fleet Step 5 / C2 correlation budget may proceed.

Do **not** reopen the two P0s:

1. Split component validation now catches the long/short vector class.
2. `ConcentrationSnapshot` now accepts `m12_n_dates_with_weights`, and producer -> schema integration is tested.

Also accepted:

- `ResearchMiner.__init__` now rejects partial temporal tuples, so direct API users cannot bypass C5 by setting `split_name` / `split_sha256` without `role`.
- `track_a_role_to_fleet_role()` explicitly maps `core -> core`, `diversifier -> satellite`.
- C3 cash-clip semantics are correctly documented in PRD §4.3 as the accepted v1 behavior.

## Carryovers Before Step 6 / Step 8

These do not block Fleet Step 5, but they should be folded into the next narrow hardening pass or before daily fleet observe writes manifests.

### P1 - `compute_concentration_metrics()` should fail closed on dirty matrices

Live check:

- NaN input returns `m12_top1_weight_max = NaN`.
- `inf` input returns `inf`.
- Negative input is converted through `abs()` and reported as positive concentration.

Why it matters:

- `compose_weight_matrix()` and `apply_overlap_throttle()` reject dirty matrices, so the intended path is guarded.
- But `compute_concentration_metrics()` is a public method and will be used near manifest-writing logic later.
- A concentration metric should never mask a short exposure by taking absolute value without first rejecting negatives. In a long-only PM layer, negative weights are not "high concentration"; they are an invariant breach.

Required follow-up:

- At `compute_concentration_metrics()` entry, require finite numeric DataFrame values.
- Reject negative cells before `abs()`.
- Add tests for `NaN`, `inf`, `-0.1`, and non-numeric object/string cells.

### P1 - PRD residual wording still says proportional trim

PRD §4.3 now correctly says cash-clip v1, but later text still says proportional trim:

- Acceptance criterion #6 still says "proportional trim is applied".
- Implementation step #4 still says "C3 overlap throttle (proportional trim)".

Required follow-up:

- Replace those residual references with "fleet-level cell clip; excess to implicit cash".
- This is docs-only, but important because PRD acceptance criteria are what future audit rounds will enforce.

### P2 - Type-confusion error polish

Current behavior:

- `splits={"c1": "0.5", "c2": 0.5}` raises a raw `TypeError` from `np.isfinite`.
- Candidate matrix with string/object cells raises a raw comparison `TypeError`.

Recommendation:

- Convert these into domain `ValueError`s with the same "finite numeric values required" wording.
- Not a blocker because the system fail-closes rather than silently passing, but clear operator errors matter once this becomes a daily workflow.

## Phase 1 Boundary

Fleet Step 5 C2 correlation budget is authorized with the following boundaries:

- Inputs are realized per-candidate daily returns, not factor ICs or objective scores.
- Require finite numeric values and enough overlapping dates before computing correlation.
- Explicitly define behavior for missing dates:
  - either inner-join overlapping dates with a minimum overlap threshold;
  - or fail closed if the overlap is too small.
- Warn threshold stays 0.70; reject threshold stays 0.85.
- Return a structured result / event that can later be written to `FleetManifest`, but do not implement daily observe yet.
- Step 6+ stays frozen: no DD throttle, no role caps/removal, no fleet observe, no shadow->live.

## Track C Boundary

Track C controlled mining planning may proceed in parallel:

- Produce the evidence-pack template before a larger mining run.
- Keep the run train-only for mining and validation-years-only for acceptance.
- Do not touch 2026 sealed evaluation.
- Do not promote a candidate into Fleet until it has passed validation and then forward evidence gates.

## Macro Note

From a trading perspective, the framework is moving in the right order now:

1. Keep research governance locked.
2. Add allocator-level correlation and concentration controls.
3. Only then expand mining scale.
4. Delay sealed 2026 and fleet live wiring until the evidence and PM layer are stable.

That ordering matters more than any single feature. A strategy factory that can generate many candidates but cannot police role drift, correlation collapse, stale data, and execution assumptions is not a trading framework; it is a backtest generator. This line is now closer to being the former, but keep the gates hard.
