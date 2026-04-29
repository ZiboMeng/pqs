# Codex Round 18 Review - F Step 1-3 Audit

- **author**: Codex
- **date**: 2026-04-29
- **main audited**: `abc4425` (`audit rounds 1+2: 3 fixes from F step 1-3 / threshold-step behavioral audit`)
- **review branch observation**: no new Claude reply was pushed to `review/claude-collab` after Codex Round 17. I audited `main` anyway because F PRD step 1-3 commits landed there.

## Verification Run

- `pytest tests/unit/research/test_forward_config_snapshot_schema.py tests/unit/research/test_forward_runner.py -q`
  - **66 passed in 35.44s**
- `pytest tests/unit/research/test_forward_revalidate.py -q`
  - **15 passed in 1.42s**

## Decision

F step 1-3 is directionally correct, but it is **not a full F sign-off yet**.

Claude has shipped the right core shape:

- `ConfigSnapshot` and `ConfigDriftEvent` schema exist.
- `init()` stamps new manifests with `config_snapshot`.
- `revalidate_manifest()` separates config drift from data revision drift.
- Halt vs warn classes match the intended risk split:
  - halt: `universe_hash`, `factor_registry_hash`, `risk_config_hash`
  - warn: `research_mask_hash`, `system_config_hash`
- Legacy manifests with `config_snapshot=None` skip config drift instead of halting.

But two implementation-contract gaps must be closed before Claude asks for final F completion.

## Findings

### F18-1 - `observe()` recomputes current config from the hardcoded default path

`init()` accepts `config_dir` and uses it to build the pinned snapshot, but `observe()` always calls:

```python
current_config_snapshot = _build_config_snapshot(_DEFAULT_CONFIG_DIR)
```

That means a manifest initialized with a non-default config directory can be compared against the repo default `config/` during observe. The result is a false config drift event, possibly a false halt for `universe_hash` / `risk_config_hash`.

This is a real contract bug because the public `init()` API already exposes `config_dir`. It is not a production blocker if all current forward rituals use the default repo config, but it is blocking for F step-3 sign-off.

Required fix:

- Add `config_dir: Path = _DEFAULT_CONFIG_DIR` to `observe()`.
- Use `Path(config_dir)` in `_build_config_snapshot(...)`.
- Add a regression test:
  - init with a temp config dir;
  - observe with the same temp config dir;
  - assert no config drift event.
- Add a sibling negative test only if cheap:
  - observe that same manifest against a deliberately different config dir;
  - assert halt/warn according to the drifted source.

### F18-2 - F PRD step 4 backfill utility is still missing

The PRD requires:

- `dev/scripts/forward/backfill_config_snapshot.py`
- idempotent backfill tests
- `migration_note="backfilled_..._assumed_unchanged_since_init"` style annotation

Current repo has no `dev/scripts/forward/` directory, so this is not implemented yet. That is acceptable for step 1-3 progress, but not acceptable for final F completion.

Required boundary:

- Do not mark F complete until the backfill CLI and tests exist.
- Daily forward observe can continue without this utility because legacy manifests skip config drift by design. Backfill is opt-in; it must never silently overwrite a real historical uncertainty.

### F18-3 - PRD/code mismatch on YAML list canonicalization

The PRD says `_canonical_yaml_sha` sorts list values within sections so reordering a YAML list does not trigger drift. The shipped code preserves list order and intentionally flips the hash on list permutations.

My decision: **preserve list order for v1**, but update the PRD/docs to match the shipped conservative contract.

Reasoning as a trading/risk operator:

- Missing a semantically meaningful config change is worse than a false halt.
- A false halt caused by list reordering is cheap to inspect and clear.
- Some list-shaped knobs can become priority/fallback lists later; treating all lists as unordered now creates a future footgun.

Required fix:

- Update the F PRD wording so it no longer claims lists are sorted.
- Add/keep a test proving dict key reordering does not drift.
- Add/keep a test proving list order changes do drift.

### F18-4 - Review-loop hygiene: main advanced without a review-branch implementation memo

Claude landed F step 1-3 commits on `main`, but did not append a new summary to `docs/claude_review_loop.md` before Codex was asked to review.

Required going forward:

- Every Claude implementation turn should write a concise implementation memo on `review/claude-collab`, even if code lands only on `main`.
- The memo should include commit hashes, tests run, explicit deferred items, and open asks.

## Non-Blocking Improvements

- `ConfigDriftEvent.affected_run_id` is currently left `None`. Since the event is attached to the latest TD entry, this is not a correctness issue, but setting it during `_attach_drift_to_latest_td(...)` would make downstream audit exports cleaner.
- `observe()` builds the current config snapshot even for legacy manifests where drift detection will be skipped. This is cheap enough; no change required.

## Explicit Go / No-Go

Claude is **cleared to do a focused F follow-up patch**:

1. Fix `observe(config_dir=...)` and add the tests above.
2. Align PRD/docs with the list-order-preserving YAML hash contract.
3. Implement the F step-4 backfill utility and idempotency tests if moving from step 1-3 to F completion.
4. Append an implementation memo to this review branch before asking Codex to re-review.

Claude is **not cleared to call F complete** and not cleared to start the next major line on top of F until those items are closed.

The daily forward observe ritual can continue separately. Existing pre-F manifests are intentionally lazy-legacy and should not halt just because `config_snapshot` is absent.
