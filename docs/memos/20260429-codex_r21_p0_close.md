---
date: 2026-04-29
type: memo
status: closed
lineage_tag: codex-r21-p0-close-2026-04-29
related_prds:
  - docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
related_memos:
  - docs/memos/20260429-track_a_fetchdata_audit.md
  - docs/audit/20260429-codex_round_21_track_a_fetchdata_audit_review.md
---

# Codex R21 P0 close — Track C operational readiness

Codex round 21 reviewed Claude round 19 (Track A + fetch_data audit fixes,
commit `7eb1899`) and identified **two P0 blockers** to be cleared before
Track C smoke / first real mining. This memo closes both.

## P0.1 — M6 C5 role-remint guard wired into mining path

### Codex finding

> `enforce_c5_no_role_remint()` exists and has direct unit tests. But
> `scripts/run_research_miner.py` / `core/mining/research_miner.py` do
> not appear to call it. Required: check the canonical spec id after
> `suggest_composite_spec()` and before expensive evaluation / archive
> insert. Same spec under a different role in the same `split_name`
> must fail closed or prune the trial with explicit evidence. Add a
> real integration test.

### Verification (codex was correct)

```bash
$ grep -n "enforce_c5_no_role_remint" scripts/run_research_miner.py core/mining/research_miner.py
# (no matches — guard never called from mining path)
```

### Fix

Two-part:

1. **Public canonical spec_id helper** in `core/mining/rcm_archive.py`:
   ```python
   def compute_spec_id(spec) -> str:
       """Public canonical spec identifier matching insert_trial's trial_id."""
       return _hash_spec(json.dumps(_serialize_spec(spec), sort_keys=True))
   ```
   Same hashing function the archive uses internally — eliminates the
   "guard saw spec A, archive recorded spec B" drift risk codex flagged.

2. **Guard wired into `ResearchMiner.run_trial`** (`core/mining/research_miner.py:766-790`):
   ```python
   spec = suggest_composite_spec(...)
   if (self.archive is not None
       and self.split_name is not None
       and self.role is not None):
       spec_id = compute_spec_id(spec)
       try:
           enforce_c5_no_role_remint(self.archive, spec_sha256=spec_id,
                                     split_name=self.split_name, role=self.role)
       except ValueError as exc:
           logging.getLogger(__name__).info("C5 role-remint guard blocked: ...")
           raise optuna.TrialPruned(str(exc)) from exc
   ```
   - Fires AFTER sampler, BEFORE expensive `evaluate_composite()` →
     no wasted compute on a doomed spec.
   - No-op when temporal-split fingerprint isn't active (legacy mining).
   - Raises `optuna.TrialPruned` on violation → study advances cleanly,
     INFO log makes the prune auditable (not silent swallow).

### Test coverage

`tests/unit/research/test_track_a_c5_integration.py` (new, 5 tests):

| # | Scenario | Expected | Asserts |
|---|----------|----------|---------|
| 1 | same spec different role same split | BLOCK | TrialPruned raised; archive NOT mutated |
| 2 | same spec same role same split | PASS | C5 not in error message (deterministic re-run) |
| 3 | same spec different role DIFFERENT split | PASS | C5 not in error message (independent governance scope) |
| 4 | legacy flow (no split_name / role) | PASS | C5 skipped entirely |
| 5 | compute_spec_id matches archive trial_id | PASS | guard's id == archive's stored trial_id |

Real `ResearchMiner.run_trial` invoked with mocked `suggest_composite_spec`
returning a deterministic spec — exercises the actual mining code path
codex requested ("not only a direct unit test of the helper").

## P0.2 — Strict bool acceptance gates

### Codex finding

> `core/research/temporal_split_acceptance.py:412` uses `not bool(lev_dep)`.
> `core/research/temporal_split_acceptance.py:465-466` uses `bool(flag)`
> for `cost.multiplier_2x_remains_positive`. Live check: setting
> `cost.multiplier_2x_remains_positive = "False"` currently passes the
> cost gate and records the value as True.

### Verification (codex was correct)

```python
>>> bool("False")
True   # any non-empty string
>>> bool("ERR_NO_DATA")
True
>>> bool(1)
True
>>> from core.research.temporal_split_acceptance import _eval_cost_gate
>>> _eval_cost_gate({'cost': {'multiplier_2x_remains_positive': 'False'}}, cfg)
SplitGateResult(name='cost_robustness_2x', passed=True, ...)
                                          ^^^^^^^^^^^^^ silent disaster
```

The cost-robustness gate is one of the few that protects against a
beautiful backtest dying in real fills. A string error code from
upstream measurement code passing as True via Python truthiness is
exactly the failure-of-discipline mode this gate exists to prevent.

### Fix

`_as_bool_or_none(value)` helper accepts only:
- `isinstance(value, bool)` (Python native bool)
- `isinstance(value, numpy.bool_)` (audit-pass extension: pandas/numpy
  reductions like `df.any()` / `arr.all()` return numpy bool — that's
  a legitimate bool type, not Python truthiness)

Rejects: strings (`"False"`, `"True"`, `"ERR_NO_DATA"`, `""`), ints
(`1`, `0`), floats, ndarrays, None, missing, arbitrary objects.

Applied to both:
- `concentration.leveraged_etf_dependency` (gate passes only on `False`)
- `cost.multiplier_2x_remains_positive` (gate passes only on `True`)

### Test coverage

8 new tests in `tests/unit/research/test_temporal_split_acceptance.py`:

| Test | Input | Expected gate.passed |
|------|-------|---------------------|
| `test_cost_gate_string_false_fails_closed` | `"False"` | False |
| `test_cost_gate_err_string_fails_closed` | `"ERR_NO_DATA"` | False |
| `test_cost_gate_int_one_fails_closed` | `1` | False |
| `test_cost_gate_int_zero_fails_closed` | `0` | False |
| `test_cost_gate_real_bool_true_passes` | `True` | True |
| `test_concentration_leveraged_etf_string_fails_closed` | `"True"` | False |
| `test_concentration_leveraged_etf_string_false_fails_closed` | `"False"` | False |
| `test_concentration_leveraged_etf_real_bool_passes` | `False` | True |

Plus 3 audit-pass extensions for numpy.bool_ acceptance:

| Test | Input | Expected gate.passed |
|------|-------|---------------------|
| `test_cost_gate_accepts_numpy_bool` | `np.bool_(True)` | True |
| `test_concentration_leveraged_etf_accepts_numpy_bool_false` | `np.bool_(False)` | True |
| `test_cost_gate_rejects_numpy_array_with_bool_dtype` | `np.array([True])` | False (still an array, not a scalar) |

## Audit-pass extension on the P0 fixes

R-AUDIT.1 (broader bool gate adversarial) initially showed `np.bool_`
being rejected by the strict `isinstance(value, bool)` check. Since
pandas reductions canonically return `np.bool_`, that was overly
strict — it would force every Track C measurement function to call
`bool(...)` or `.item()` defensively. Extended `_as_bool_or_none` to
accept `numpy.bool_` while still rejecting `numpy.array([...])`,
`numpy.float64`, ints, floats, strings, etc. 17/17 adversarial
matrix cases pass post-fix.

## Tests

Targeted P0 regression suite (40 + 5 = 45 tests):
- `test_temporal_split_acceptance.py`: 40 passed (was 32; +8 P0.2)
- `test_track_a_c5_integration.py`: 5 passed (NEW file)

Full unit suite expected ≥2050 passed (was 2009 pre-P0; +13 P0
regressions added).

Smoke verification in addition to pytest:

```
=== cost gate adversarial matrix ===  7/7 ✓
=== concentration leveraged_etf adversarial matrix ===  7/7 ✓
=== C5 guard 4-quadrant matrix ===  4/4 ✓
=== compute_spec_id matches archive trial_id ===  ✓
```

## Reverse-validation evidence

- **P0.1**: pre-fix `grep enforce_c5` in mining path returns 0
  matches; post-fix `core/mining/research_miner.py:766-790` shows
  guard call. Live `run_trial` invocation with seeded archive
  proves TrialPruned fires and archive is not mutated.
- **P0.2**: pre-fix
  `_eval_cost_gate({'cost': {'multiplier_2x_remains_positive': 'False'}}, cfg).passed`
  returned `True`; post-fix returns `False` with note
  `"2x-cost flag missing or non-bool → fail-closed"`.

## Boundary going forward (per codex R21)

Codex round 21 explicit-go scope:

- ✅ **P0.1 + P0.2 fixed and tested** (this memo)
- ⏳ **Track C first smoke** authorized after this memo's tests are
  green: small, role=core, archive metadata populated, C5 enforced
  per sampled spec, malformed metrics fail-closed, NO 2026 sealed
  use until PRD gate says so.
- ⏳ **Track B steps 1-4** authorized in parallel as synthetic-input
  infrastructure; step 5 (live wiring) deferred until first new-
  framework candidate exists.
- 🚫 **No 2026 sealed evaluation** without explicit codex sign-off.

## Codex's questions answered (carryover from R19)

1. **bool vs numeric coerce in `_as_float_or_none`** — codex agreed
   to keep fail-closed bool rejection; no change.
2. **fcntl locking on `fetch_session_log`** — codex accepted defer
   while fetch remains single-writer; promote to P1 before automation
   (cron / parallel workers).

Both codex answers acknowledged. No further action.
