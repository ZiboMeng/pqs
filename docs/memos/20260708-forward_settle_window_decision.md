# Forward Observation Settle-Window — Decision Memo

**Date**: 2026-07-08
**Author**: operator (Claude) + user explicit-go 2026-07-08
**Lineage tag**: `forward-settle-window-2026-07-08`
**Status**: DECIDED (implementation in progress)
**Affects**: `core/research/forward/` revision-detection ("revalidate") materiality contract

---

## 1. Problem

Forward OOS observation on yfinance-frontier data halts (`requires_data_review`)
on essentially **every** observe, because yfinance's most-recent bars are
**preliminary** and get revised (preliminary→final settlement) within days.

The revision-detection contract (`revalidate`) locks a TD's signal_input /
execution_nav / benchmark hashes at first-observe and treats **any** later
divergence as `invalidated` — by design there is **no** "accept-benign-and-
continue" path (per `docs/forward_observation_log.md` 2026-06-17 entry).

Consequence: each observe's newest bars become the next observe's revised
bars → guaranteed halt → manual `re-init`. `re-init` is a **treadmill**: it
re-anchors to current data but the new frontier bars will themselves revise
before the next observe. Empirically: 2026-06-17 re-init → 2026-07-08 halt
(the 2026-06-25 halt was a separate track_per_cell=False noise artifact,
resolved by [[../memos]] `20260708`... see forward log 2026-06-29/30).

## 2. Evidence (2026-07-08 halt, read-only diagnosis)

cycle06 / cycle08 both halted on observe (06-30 → 07-08 catch-up):

| Item | cycle06 | cycle08 |
|---|---|---|
| revised-cell dates | **ALL 2026-06-29** (the prior observe's frontier bar) | same |
| n_revised_cells | 32 | 29 |
| max single-cell close drift | **0.368%** (`raw_max_close_drift_pct=0.00368`, a fraction) | 0.368% |
| E1 NAV cum_ret drift | **22.44 bps** | 20.92 bps |
| decision_sign_flip | False | False |
| affected_scopes | execution_nav + signal_input | same |

Confirmed NOT noise / NOT total-return / NOT distributions-table:
- `data/ref/distributions.parquet` mtime 2026-05-19 (unchanged) — not a
  distribution-factor rebuild.
- raw close == total_return close on 2026-06-29 for the revised held names —
  not a dividend/total-return artifact.
- ⇒ yfinance revised the **raw** 2026-06-29 bars directly (~0.37% max),
  i.e. genuine preliminary→final settlement of the prior frontier bar.

`track_signal_input_per_cell=True` (the prior fix) is **working**: it produced
precise cell-level attribution (32/29 named cells + deterministic 22/21 bps
NAV impact) instead of the prior empty-digest fail-closed. The halt is now a
*correct* detection of a *real* (but benign, sub-sign-flip) trailing-bar
revision — not a false alarm. The remaining problem is purely that the contract
has no tolerance for the **unsettled frontier**.

## 3. Decision

Add a **settle-window** to the revision-detection contract:

> A TD entry whose `as_of_date` is within the last **N settled trading days**
> of the current data frontier is **provisional**. Provisional entries are
> **re-anchored** to current data on each observe (their stored hashes are
> updated, NOT compared) and do **NOT** trigger `requires_data_review`.
> Once an entry is older than the settle window it is **frozen**; any later
> divergence on a frozen entry halts as today (settled-history protection
> preserved).

- `N` is **configurable** per candidate: stored on the manifest
  (`CheckpointCadence.settle_window_trading_days`), set at `init()` and
  exposed via the CLI `--settle-window`. **init()'s own default is `0`
  (opt-in)** so existing manifests + the whole test suite keep the exact
  legacy strict contract byte-for-byte; the **RECOMMENDED** value for
  yfinance-frontier candidates is **10 trading days** (`RECOMMENDED_
  SETTLE_WINDOW_TRADING_DAYS`), chosen to exceed observed yfinance
  finalization lag (this instance: a 06-29 bar revised ~6 trading days
  later; 10 gives ~2 calendar weeks' margin). cycle06/08 are re-init'd with
  N=10 explicitly. Revisit if a revision ever lands past the window.
- Settled-cell protection is preserved: a cell dated within the settled
  region still appears in earlier (frozen) entries' hash windows, so a
  revision to genuinely-settled history is still caught. Only cells that
  exist **solely** within provisional entries (i.e. dated in the unsettled
  trailing window) escape detection — exactly the intended provisional bars.

## 4. Rationale / why not the alternatives

- **re-init every observe (status quo)**: treadmill; will re-halt on the new
  frontier next observe; manual; silently re-anchors the whole history anyway.
  Rejected as a permanent answer (acceptable only as a one-off stopgap).
- **flat benign-NAV tolerance (accept < X bps, no sign-flip)**: coarser —
  picks an arbitrary bps threshold, and would also mask *settled-history*
  revisions under X bps (a real protection loss). The settle-window is
  targeted at the actual failure mode (unsettled frontier) and keeps full
  protection on settled history. Could still be added later as a complementary
  guard, but is not the primary fix.
- **freeze forward data source (snapshot the tape)**: heavier infra; loses the
  "observe on the same frontier a live operator would see" property.

## 5. Contract-change disclosure (directional)

This **loosens** the "no accept-benign-and-continue" stance recorded 2026-06-17,
but **only for the unsettled trailing window** — settled history retains the
strict fail-closed contract. Approved by user explicit-go 2026-07-08. Invariants
untouched: long-only / no-margin / benchmark logic / sealed-2026 unread /
backtest-execution consistency all unaffected (this is a revision-detection
policy, not a construction/execution change).

Reversibility: set `N = 0` in config → behavior reverts to the strict
pre-2026-07-08 contract (every entry frozen at first observe).

## 6. Implementation

Localized to the serialization/observe layer; `revalidate` internals untouched
(strict detection preserved verbatim for settled entries).

- **`manifest_schema.py`** — `CheckpointCadence` gains
  `settle_window_trading_days: int = Field(default=0, ge=0, …)`. Default 0 →
  legacy manifests deserialize to the strict contract, byte-unchanged.
- **`runner.py`**:
  - `RECOMMENDED_SETTLE_WINDOW_TRADING_DAYS = 10` (module constant; the value
    the operator passes for yfinance-frontier candidates).
  - `init(..., settle_window_trading_days=0)` — threads into `CheckpointCadence`.
    init's own default 0 = opt-in.
  - `_drop_provisional_tail(runs, available_index, settle_n) -> (kept, n_dropped)`
    — pure helper. A `TD` entry is provisional iff `< settle_n` trading days lie
    between its `as_of_date` and `available_index.max()`. Provisional TD entries
    dropped; settled + non-TD entries kept. `settle_n<=0` → everything kept.
  - `observe()` — calls `_drop_provisional_tail` immediately BEFORE
    `revalidate_manifest(...)`. Dropped provisional dates fall out of the
    `_resolve_dates_to_observe` "already-seen" set, so the existing append loop
    re-derives them from current data (NAV + all three hashes refreshed). Net
    effect: revalidate sees only settled entries (no benign-frontier halt); the
    provisional tail is always a fresh derivation. `settle_n=0` → drop is a
    no-op → observe() byte-identical to pre-change.
- **CLI `run_forward_observe.py`** — `init --settle-window N` (default: init's 0).

Why drop+re-derive (not just skip-in-revalidate): decision-point checkpoints
(TD10/20/40/60) are reached AT the frontier, so a provisional TD's NAV must
reflect current data at read time. Simple skip would leave stale first-observe
NAV; drop+re-derive refreshes it. Once an entry ages past N it stops being
re-derived → its last (near-final) values freeze and strict detection resumes.

## 7. Test plan / results

`tests/unit/research/test_forward_settle_window.py` (11 tests, all fast — no
data load): schema default-0 / ge-0 / round-trip; `_drop_provisional_tail`
disabled-at-0, exact-drop-count for N∈{1,5,10}, non-TD kept, boundary
(exactly-N settled vs N-1 provisional), empty/None-index safe; `init()`
default-0, override, persist-through-save/load. **11 passed.**

Regression: init default 0 ⇒ `settle_n=0` everywhere the existing suite doesn't
set it ⇒ `_drop_provisional_tail` returns all runs, 0 dropped ⇒ observe() path
byte-identical. `test_forward_runner` (54) + `v2_integration` (10) unaffected.

## 8. Application to active candidates

cycle06 / cycle08 (currently `requires_data_review`) will be recovered/re-observed
under the new settle-window logic once implemented + tested. Prior manifests
already backed up (`*.preReinit_2026-06-29.json`); a fresh backup taken before
any re-anchor. Sealed 2026 remains unread.
