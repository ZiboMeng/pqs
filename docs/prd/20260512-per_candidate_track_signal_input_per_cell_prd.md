# PRD — Per-candidate `track_signal_input_per_cell` opt-in for v2.1 revalidate

**Authors**: operator (zibomeng@), with Claude Code assist
**Date**: 2026-05-12
**Status**: DRAFT (single-round operator-driven; user explicit-go for scope)
**Triggered by**: `trial9_diversifier_001` TD004 bound_only invalidation 2026-05-12

---

## §1 Background

`trial9_diversifier_001` accumulated 4 forward observations (TD001-TD004)
between 2026-05-04 and 2026-05-07. The 2026-05-12 daily ritual `observe()`
triggered v2.1 `revalidate_manifest` and recorded:

- TD001/TD002/TD003: `policy_decision: flagged_only`, `materiality_class:
  in_ring`, triggers `[]` — these are the regular yfinance retro
  refresh pattern, contained within `execution_nav` scope, NAV-impact
  sub-E1.
- **TD004: `policy_decision: invalidated`, `materiality_class: bound_only`,
  trigger `bound_only (signal_input scope diff with empty per_cell_digest
  (track_per_cell=False) — cannot prove diff is subset of execution_nav-
  anchored cells; conservative bound_only per PRD §4.4 (codex Round-10
  Blocker 2))`**.

TD004 flipped the manifest to `requires_data_review`. Manual diagnostic
on 2026-05-12 confirmed:

- All 18 held syms × 10 anchor-ring dates × close anchor values match
  current panel exactly (0 diff revealed in anchor coverage)
- Re-hashing signal_input with `track_per_cell=True` against current
  panel gives a hash that still differs from stored
- Therefore the revised close cell is outside execution_nav anchor
  coverage (i.e., a non-held sym OR a date older than the 10-day ring)
- No retroactive reconstruction is feasible because the stored
  `per_cell_digest` for signal_input was empty (production default
  `track_per_cell=False`)

`recover --dry-run` halts with the same trigger because current policy
re-evaluation produces the same `bound_only` classification. No PRD
20260505-style noise-floor exemption can save it: codex R10 Blocker 2
is deliberately conservative against signal_input revisions that
cannot be attributed to known execution_nav-bounded cells.

## §2 Root cause

`compute_signal_input_hash` at `core/research/forward/bar_hash.py:353`
takes a `track_per_cell: bool = False` kwarg. Production callers
(`runner.py:1041`) do NOT pass this kwarg → all production TDs are
written with `per_cell_digest = {}`. Storage budget reasoning is the
original justification (~2 MB per TD for the full universe × lookback
× attrs cube; docstring estimate balloons to >100 MB by TD60).

When revalidate detects a signal_input scope hash diff, it tries to
diff the stored vs new per-cell digests (`revalidate.py:285-289`).
With stored = empty, the diff is empty → falls into the "empty
per_cell_digest fail-closed" path (`revalidate.py:419-428`) → sets
`bound_only_reason` → escalates to `invalidated`.

This is the codex R10 Blocker 2 contract working as designed. The
gate cannot distinguish "1 revised cell entirely inside execution_nav
scope" (in which case execution_nav's E1/E5 numbers are exhaustive)
from "1 revised cell visible to execution_nav PLUS another hidden
cell outside execution_nav scope" (in which case E1/E5 are incomplete
bounds).

The architectural escape valve is `track_per_cell=True` — when set,
`per_cell_digest` is populated at observation time and revalidate
can do real cell-level diff (`revalidate.py:429-444`). The mode is
currently flagged "tests only" in the docstring (`bar_hash.py:378`)
but the implementation is fully production-quality.

## §3 Fix — opt-in `evidence_config.track_signal_input_per_cell`

Add an optional `evidence_config` field to `FrozenStrategySpec`, mirroring
the existing `execution_policy` pattern (PRD 20260505 Step 6.1-min):

```python
# core/research/frozen_spec.py
@dataclass
class FrozenStrategySpec:
    ...
    execution_policy: Optional[dict] = None
    evidence_config: Optional[dict] = None   # NEW
    extras: dict = field(default_factory=dict)
```

Documented shape (v1.0):

```yaml
evidence_config:
  track_signal_input_per_cell: bool   # default False; opt-in for diversifier
                                      # or other roles with high tolerance for
                                      # signal_input scope drift events
```

Reader: `runner.py:1041` resolves the kwarg from spec at TD-write time:

```python
sig_h, sig_in = compute_signal_input_hash(
    spec=spec, universe=v2_universe, panel=panel, as_of_date=d,
    track_per_cell=(
        bool((spec.evidence_config or {}).get("track_signal_input_per_cell", False))
    ),
)
```

`revalidate.py:277` already handles per-TD heterogeneity correctly:
`track_signal_per_cell = bool(stored_sig_digest)` recomputes with the
SAME `track_per_cell` setting the entry was hashed under. So a single
candidate could in principle have some opt-in TDs and some default
TDs — though in practice the flag is set at init time and persists
for the candidate's life.

## §4 Default policy

- Default = `False` for ALL existing candidates (legacy preservation
  for RCMv1, Cand-2, trial9_diversifier_001)
- Opt-in = candidates that initialize with `evidence_config.track_signal_input_per_cell:
  true` in their frozen yaml
- Roles eligible to opt in: `diversifier` (immediately); `core_alpha`
  (case-by-case — storage cost is real even though smaller than the
  docstring suggests)
- No automatic role-based default; the field MUST be explicitly set
  per-candidate to surface the decision in the frozen yaml

## §5 Storage cost reality check

The bar_hash.py docstring estimate of "~2 MB/TD" was for the
**full union of all signal_input attributes** (typically `close + open
+ high + low` ≈ 4 attrs) over the **full universe × full lookback**
cube. Actual cost is candidate-dependent:

- trial9_diversifier_001 spec uses factors `beta_spy_60d + max_dd_126d
  + ret_1d` — combined `signal_input.bar_attributes = ['close']` (1 attr)
- 81 syms × 252 days × 1 attr × 8-char hash digest ≈ 163 KB / TD
- 60-TD soak: **~10 MB / candidate**
- diversifier observation cadence: TD60 = 1 candidate × 10 MB → trivial

A future candidate with `signal_input.bar_attributes = ['close', 'high',
'low']` (e.g., a range-breakout factor) would scale ×3. Still under
budget for individual diversifier candidates. Document this in spec
review when opt-in is requested.

## §6 Audit / rollback

- This PRD adds an OPTIONAL field — pre-PRD yaml files load unchanged
  (`evidence_config is None`); pre-PRD code paths unchanged
- Rollback: deleting the field from a spec yaml reverts that candidate
  to `track_per_cell=False` going forward; already-written TDs retain
  their original per_cell_digest content (heterogeneous TDs supported
  natively by revalidate's `track_signal_per_cell = bool(stored_sig_digest)`
  pattern at `revalidate.py:277`)
- Reversal of the PRD itself: deleting the field from `FrozenStrategySpec`
  is a code-level revert; storage of historical per_cell_digest content
  on existing TDs is harmless even after revert (revalidate gracefully
  handles populated-but-unused digests)

## §7 Test surface

1. **Legacy path preservation**: pre-PRD spec without `evidence_config`
   produces TDs with `per_cell_digest = {}` (unchanged from current
   behavior); revalidate's bound_only fail-closed path still fires
   on signal_input scope diff with empty digest
2. **Opt-in PASS**: spec with `evidence_config.track_signal_input_per_cell:
   true` produces TDs with non-empty `per_cell_digest`; revalidate's
   cell-level diff path fires (`revalidate.py:429-444`) and small
   in-ring revisions stay `flagged_only`
3. **Opt-in FAIL → still fail-closed**: spec with `track_per_cell=True`
   + revision on a non-anchored cell (held sym outside anchor ring,
   or non-anchored attribute) still triggers bound_only per the existing
   per-cell coverage check
4. **Heterogeneous TDs (edge case)**: candidate's spec changes
   `evidence_config.track_signal_input_per_cell: true` after some
   default TDs were written — revalidate handles the mix correctly
   (each TD evaluated under its OWN stored setting via line 277)
5. **Boundary E4/E5**: opt-in does not change E1/E2/E3/E4/E5 thresholds;
   only changes whether signal_input scope can be cell-attributed
6. **Backward compat**: existing `FrozenStrategySpec.from_dict` parsing
   accepts yaml without `evidence_config` (field defaults to `None`);
   parses correctly with empty dict (`evidence_config: {}`); parses
   correctly with full dict (`evidence_config: {track_signal_input_per_cell:
   true}`)

## §8 Acceptance criteria

- All §7 test cases shipped
- pytest core/research/forward + tests/unit/research/forward suite
  passes without regression
- A new opt-in candidate (`trial9_diversifier_002`) initializes with
  `evidence_config.track_signal_input_per_cell: true`; first observe
  shows `bar_hash_inputs.signal_input.per_cell_digest` non-empty
- A subsequent retroactive revision on this opt-in candidate
  classifies via cell-level coverage path, NOT empty-digest fail-closed
  (verified by manually editing one panel value during dev run)

## §9 Out of scope

- A1.c (synthetic anchor-based reconstruction for legacy TDs without
  per_cell_digest) — architecturally clean but not needed once A2
  opt-in is shipped because new candidates write per_cell_digest
  natively; deferred indefinitely unless a future legacy-candidate
  recovery is required
- Global default flip to `track_per_cell=True` — premature; storage
  budget reality differs per-spec; case-by-case opt-in surfaces the
  decision properly
- Anchor ring extension (currently 10 days) — separate PRD if revisions
  beyond 10 days become a frequent failure mode; not justified by a
  single TD004 case

---

## Implementation steps

1. Add `evidence_config: Optional[dict] = None` to `FrozenStrategySpec`
   (frozen_spec.py)
2. Update `FrozenStrategySpec.from_dict` / `from_yaml_file` to populate
   it from yaml (catch-all extras handle this for free via existing
   code if pattern is mirrored from `execution_policy`)
3. Update `runner.py:1041` `compute_signal_input_hash` call to read
   the kwarg from `spec.evidence_config`
4. Add 6 unit tests covering §7 cases
5. Run full forward + research test suite
6. `decide()` trial9_diversifier_001 → `completed_fail` with notes
   pointing to this PRD
7. Init `trial9_diversifier_002` from same factor composite, with
   `evidence_config.track_signal_input_per_cell: true`,
   `start_date=2026-05-13`
8. Commit, push, 4-round audit
