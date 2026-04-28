# Forward Evidence Hardening — PRD

**Status**: DRAFT — design only, no implementation until accepted
**Date drafted**: 2026-04-27
**Authority required**: user explicit (zibo)
**Authoring lineage**: codex review-loop Round 6 (`d8fd133`) §"Highest-ROI Recommendations P0"
**Supersedes / extends**: `docs/prd/20260426-forward_oos_runner_prd.md` §4.6 (overlap-fetch caveat) + §6 R-fwd-2 / R-fwd-3 outline
**Lineage tag (when committed)**: `forward-evidence-hardening-2026-04-27`

---

> **Forward evidence is only as immutable as the bars beneath it.**
>
> A TD entry's `cum_ret` is computed at observation time. yfinance
> retroactively revises adjusted close / volume on the latest 1-2
> trading days. A subsequent TD's backtest re-run uses the revised
> bar; the earlier TD's stored `cum_ret` keeps the OLD bar's value.
> The two TDs are then internally inconsistent at the underlying-data
> level even though neither manifest entry is "wrong" relative to its
> own observation moment. Production-grade forward governance must
> distinguish that case from real alpha decay.

---

## 1. Background

### 1.1 Why now

Codex Round 6 (review log on `df344b2`'s parent ancestry) flagged
forward-evidence immutability as the **highest-ROI engineering
investment** before any further OHLCV-mining or paper-slot work:

> A forward track record that can be revised underneath by vendor
> adjustments is not a production-grade track record. If we cannot
> prove exactly which bars generated each TD entry, we cannot
> distinguish alpha decay from data revision, source-boundary drift,
> or bookkeeping noise.

### 1.2 Current state

`docs/prd/20260426-forward_oos_runner_prd.md` shipped R-fwd-1
(init / status / observe / decide / readiness). R-fwd-2 (observation
engine + checkpoint reduction) and R-fwd-3 (checkpoint pipeline)
were sketched but explicitly gated on "≥3-5 real TD entries" before
implementation, with the bar-hash guard listed as in-scope for those
rounds (Option C in §4.6).

Both candidates' manifests currently sit at TD001 / 2026-04-24 /
`source_mix=True`. The TD001 entries are **baseline** entries
(zero-day cum_ret); they are reproducible from the freeze date and
do not embed reconstructable data-state evidence.

### 1.3 Scope boundary

This PRD pins the **schema + contract** for forward-evidence
immutability and checkpoint packs. It does NOT itself authorize the
R-fwd-2 / R-fwd-3 implementation rounds. The implementation rounds
remain gated on accumulating enough real TDs (per the prior PRD).
What this PRD ships when accepted: a frozen schema + contract +
test plan + migration story, so the implementation rounds when they
fire have an executable spec, not a sketch.

---

## 2. Goals

### G1 — Per-TD bar-hash immutability

Every `ForwardRun` entry whose checkpoint_label starts with `TD`
must record a hash of the input bars used to compute it, scoped to
the held-today universe. A subsequent re-fetch that mutates any of
those bars must be detectable from the manifest alone, without
needing to recover the prior bar values.

### G2 — Data-revision event flagging

When a re-fetch produces bar values that disagree with the hash on
record for any prior TD entry, the system must record a
`data_revision_event` on **the affected TD entries** (not on the
manifest as a whole), with enough metadata to identify which symbol
(s) revised and when.

### G3 — Source-layer attribution at TD level

Each TD must record which source layer the bars came from at the
moment of observation (canonical-only / frontier-only / mixed) at
**per-symbol** granularity rather than the current aggregate
boolean `source_mix`. Aggregate counts roll up at checkpoint
reduction time (see G5).

### G4 — Explicit revision policy

The PRD must answer one binary question with a written rule:
**when a stored bar is revised by yfinance, is the affected prior
TD entry only flagged, or also invalidated as evidence?** Both
positions are defensible; what's not defensible is leaving the
question open.

### G5 — Checkpoint evidence pack file format

At each `decision_days` boundary (10, 20, 40, 60), produce a
self-contained checkpoint pack
(`<id>_forward_checkpoint_TD{N}.{json,md}`) that aggregates: returns,
MaxDD, turnover/fills, M12 concentration metrics, SPY/QQQ relative
returns, source-mix-day breakdown, revision-event count, and any
manifest invariant violations encountered along the way.

### G6 — Backward-compat for the existing TD001 entries

Both manifests already have a `runs[0]` entry. Migration must
preserve those rows (append-only contract). New fields are
**additive optional** with sensible defaults so the existing entries
continue to validate. No re-write of the historical entry's
numerical fields is permitted.

### G7 — yfinance-revision regression test

A unit test must simulate the exact yfinance revision behavior
(latest-1-2-day adjusted close / volume drift) and prove that the
hash check fires `data_revision_event=true` on the right TD entries
and not on unrelated ones.

---

## 3. Non-goals

- **G3 universe expansion** — out of scope. The bar-hash guard
  scopes to the candidate's held-today set on each observation
  date, not the full 79-symbol universe.
- **PIT fundamentals / alternative data integration** — Codex Round
  6 P1, separate PRD.
- **Candidate-fleet allocator** — Codex Round 6 P2, separate PRD.
- **Real broker adapter** — Codex Round 6 P4, separate PRD.
- **Promotion / paper-slot decisions** — out of scope. This is
  evidence-layer hardening; it does not touch promotion gates.
- **Mutating any existing TD001 stored value** — explicitly
  forbidden.

---

## 4. Design

### 4.1 Schema additions

`core/research/forward/manifest_schema.py::ForwardRun`:

```python
class ForwardRun(BaseModel):
    # ── existing fields (unchanged) ─────────────────────────────
    checkpoint_label: str = Field(min_length=1, ...)
    as_of_date: date
    n_observed_trading_days: int = Field(ge=0)
    cum_ret: Optional[float] = None
    sharpe: Optional[float] = None
    max_dd: Optional[float] = None
    vs_spy: Optional[float] = None
    vs_qqq: Optional[float] = None
    notes: Optional[str] = None
    source_mix: Optional[bool] = None      # legacy aggregate flag

    # ── new fields (additive optional, default None) ────────────
    bar_hash: Optional[str] = Field(
        default=None,
        min_length=12,
        description=(
            "sha256 (truncated to >=12 hex chars) of the canonical "
            "bar tuple (sym, date, close, volume) over the held-today "
            "universe at observation time. None on entries written "
            "before this schema field shipped."
        ),
    )
    bar_hash_inputs: Optional[BarHashInputs] = Field(
        default=None,
        description=(
            "Reproducibility metadata for bar_hash: the held-today "
            "symbol list and the per-symbol bar attributes folded "
            "into the hash. Lets a future audit recompute and verify "
            "without re-running the full backtest."
        ),
    )
    source_layer_breakdown: Optional[SourceLayerBreakdown] = Field(
        default=None,
        description=(
            "Per-source-layer count of held-symbol bars on this date. "
            "Replaces the aggregate `source_mix` boolean with explicit "
            "{canonical_only, frontier_only, mixed} attribution at "
            "per-symbol granularity."
        ),
    )
    data_revision_event: Optional[DataRevisionEvent] = Field(
        default=None,
        description=(
            "Set when a re-fetch produces bar values that disagree "
            "with this entry's stored bar_hash. None for entries that "
            "have not been re-validated, or for entries whose stored "
            "hash still matches the current bar values."
        ),
    )
```

Two new model classes:

```python
class BarHashInputs(BaseModel):
    held_symbols: list[str]      # sorted; lets a reader recompute
    bar_attributes: list[str]    # default ["close", "volume"]; future-proof
    bar_revision: str            # canonical-source pin (e.g.
                                 #   "trades_v2_late_report_dedup_2026-04-19"
                                 #   for polygon-canonical bars)


class SourceLayerBreakdown(BaseModel):
    canonical_only_n_symbols: int = Field(ge=0)
    frontier_only_n_symbols:  int = Field(ge=0)
    mixed_n_symbols:          int = Field(ge=0)
    # Sum must equal len(held_today). Validator enforces.


class DataRevisionEvent(BaseModel):
    detected_at_utc: datetime
    revised_symbols: list[str]
    detected_by_run_label: str   # which subsequent observe() call
                                 # noticed the divergence (e.g.
                                 # "TD007 / 2026-05-12")
    delta_summary: str           # short human-readable per-symbol
                                 # before/after summary
    policy_decision: Literal["flagged_only", "invalidated"]
    # See §4.4 for which value applies.
```

### 4.2 Backward-compat contract

The four new fields are all `Optional` with default `None`. Existing
TD001 entries on RCMv1 / Cand-2 manifests load without modification.
Migration is **lazy**: a one-time backfill script is *not* required
for ship; the next `observe()` call writes the new fields for any
new TD; old entries simply have `None` for the new fields and are
explicitly *not* covered by the data-revision guard.

A regression test pins this:

```python
def test_existing_TD001_entries_load_after_schema_extension():
    # Load both real manifests; assert all entries validate; assert
    # bar_hash / source_layer_breakdown / data_revision_event are
    # None for entries that pre-date the field; assert
    # n_observed_trading_days, cum_ret, source_mix unchanged.
```

### 4.3 bar_hash construction

Pure function (testable without observe() machinery):

```python
def compute_bar_hash(
    *,
    held_symbols: list[str],
    bar_panel: pd.DataFrame,        # close-only OR multi-attr
    as_of_date: date,
    bar_attributes: list[str] = ("close", "volume"),
) -> tuple[str, BarHashInputs]:
    """sha256(sorted (sym, attr, value) tuples) -> truncated 24-hex."""
```

Constraints:

- **Determinism**: same inputs → identical hash byte-for-byte.
  Sort symbols + attributes lexicographically before serializing.
- **No floats-as-strings**: serialize via `f"{value:.10g}"` to
  avoid Python repr drift across versions / platforms. The test
  must verify the hash is invariant to runtime float repr.
- **NaN handling**: deterministic — serialize NaN as the literal
  `"NaN"`. A held symbol whose bar is NaN at as_of_date is a real
  case (delisting in flight) and must not produce a non-deterministic
  hash.
- **Truncation**: 24 hex chars (96 bits). Wide enough that random
  collision is negligible at the scales we care about (≤ 60 TDs ×
  10 held symbols).

### 4.4 Revision policy (resolves G4)

**Default rule: `flagged_only`.**

When a re-fetch reveals that a bar referenced by a prior TD's
`bar_hash` has changed, set `data_revision_event` on that TD with
`policy_decision="flagged_only"`. Do **NOT** mutate the stored
`cum_ret`, `sharpe`, `max_dd`, or any other historical numeric
field. The TD remains as-of its observation moment; the revision
event documents that the underlying data has since drifted.

**Why not `invalidated`:**

- `invalidated` would force a decision: should the TD be removed
  from the run record? Removing breaks the append-only manifest
  contract. Keeping but marking "evidence void" is functionally
  equivalent to `flagged_only` with extra UX noise.
- yfinance's revisions are typically small (0.01-0.05% on adjusted
  close as new dividends / splits / late-reports work through). The
  number is rarely directionally informative on its own.
- Forward observation has explicit checkpoint days (10, 20, 40, 60).
  A revision detected mid-window does not change the checkpoint
  decision boundary; it is a diagnostic that the user reads at the
  next checkpoint.

**Escalation hatch**: a `data_revision_event` with revised_symbols ≥
N (default 3) **OR** with delta on any single symbol exceeding a
threshold (default 1.0% on close) sets `policy_decision="invalidated"`
instead. This is an opt-in rule, configurable, default conservative.
At first invalidation, status transitions to a new
`ForwardRunStatus.requires_data_review` (additive enum value) so the
user must `decide()` before further `observe()` runs.

### 4.5 Source-layer breakdown at observe time

`observe()` already calls `get_boundary(sym)` per held symbol to
compute the aggregate `source_mix` flag. The new design uses the
same per-symbol boundary lookup but populates the explicit
3-bucket count. Pseudocode:

```python
canonical_only_n = 0
frontier_only_n = 0
mixed_n = 0   # for symbols with bars that span both layers
              # in the lookback window
for sym in held_today:
    layer = source_boundaries.classify(sym, as_of_date)  # NEW helper
    if layer == "canonical_only":
        canonical_only_n += 1
    elif layer == "frontier_only":
        frontier_only_n += 1
    else:
        mixed_n += 1

source_layer_breakdown = SourceLayerBreakdown(
    canonical_only_n_symbols=canonical_only_n,
    frontier_only_n_symbols=frontier_only_n,
    mixed_n_symbols=mixed_n,
)
```

The aggregate `source_mix` boolean stays for backward-compat:
`source_mix = mixed_n_symbols > 0 or frontier_only_n_symbols > 0`.

### 4.6 Re-validation pass

A new entry point `runner.revalidate(candidate_id, ...) -> list[
DataRevisionEvent]` recomputes the `bar_hash` for every prior TD
entry and compares it to the stored hash. Mismatches return as a
list of revision events; the function persists them on the
corresponding TD entries (mutating only the `data_revision_event`
slot, never the historical numeric fields).

`revalidate()` is **invoked from `observe()` automatically** at the
end of each successful append, so daily ritual catches revisions
without a separate user step. It can also be called standalone for
audit purposes.

### 4.7 Checkpoint pack file format (resolves G5)

At each TD that hits a configured `decision_days` boundary,
`runner.observe()` additionally writes:

- `data/research_candidates/<id>_forward_checkpoint_TD{N}.json`
- `data/research_candidates/<id>_forward_checkpoint_TD{N}.md`

JSON shape:

```json
{
  "schema_version": "1.0",
  "candidate_id": "...",
  "checkpoint_label": "TD060",
  "as_of_date": "2026-...",
  "n_observed_trading_days": 60,
  "absolute_returns": {
    "cum_ret":   0.034,
    "sharpe":    0.82,
    "max_dd":   -0.058,
    "vs_spy":    0.012,
    "vs_qqq":   -0.008
  },
  "execution": {
    "n_fills_total":       127,
    "n_fills_per_td_avg":  2.12,
    "turnover_daily_mean": 0.041,
    "m12_top1_weight_max": 0.18,
    "m12_top3_weight_max": 0.41
  },
  "source_layer_aggregate": {
    "canonical_only_days": 42,
    "frontier_only_days":   3,
    "mixed_days":          15
  },
  "data_revisions": {
    "n_events":           2,
    "n_invalidated_tds":  0,
    "events": [ { ...DataRevisionEvent... } ]
  },
  "manifest_invariants": {
    "append_only_intact": true,
    "spec_hash_match":    true,
    "cost_hash_match":    true
  },
  "regime_notes": "string or null"
}
```

Markdown shape: human-readable summary of the JSON, formatted to
fit within a checkpoint review email / PR description.

The pack is **immutable once written** — re-running observe() past
the same TD does NOT overwrite existing checkpoint pack files. A
secondary `<id>_forward_checkpoint_TD{N}_v2.{json,md}` is written
if the underlying state has changed since the first write (e.g.
new revision events accumulated). Numbering is monotonic.

### 4.8 Module layout

```
core/research/forward/
  manifest_schema.py    [edit]   add 3 new models + 1 enum value
  runner.py             [edit]   observe() writes new fields,
                                 calls _maybe_write_checkpoint_pack,
                                 calls revalidate at end
  bar_hash.py           [new]    pure compute_bar_hash + verify
  source_layer.py       [new]    classify(sym, as_of_date) ->
                                 'canonical_only' | 'frontier_only'
                                 | 'mixed'
  checkpoint_pack.py    [new]    build + write JSON/MD pack from
                                 manifest + per-TD details
  revalidate.py         [new]    revalidate(candidate_id) ->
                                 list[DataRevisionEvent]
```

`source_boundaries.py` already exists in `core/data/`; reuse rather
than re-implement.

---

## 5. CLI

`runner.py`'s existing CLI gets one new subcommand:

```
python -m core.research.forward.runner revalidate <candidate_id>
```

Default `observe()` behavior unchanged externally; new fields are
populated transparently.

---

## 6. Acceptance gates (when the implementation rounds fire)

Round R-fwd-2 (this PRD makes implementable):

1. **Schema migration test passes** — both real manifests load
   under the extended schema; existing TD001 entries unmodified.
2. **bar_hash determinism test** — same inputs (across two runs in
   different processes) produce byte-identical hash.
3. **bar_hash NaN-safe test** — held symbol with NaN bar produces a
   deterministic hash, not a non-determinism crash.
4. **Source-layer breakdown sums correctly** — for a synthetic
   panel with N held symbols, the 3 buckets sum to N.
5. **Revision-detection golden test** — write a TD entry with hash
   H over panel P; mutate one row of P; revalidate; assert the
   resulting `data_revision_event` is on the right TD with the
   right `revised_symbols`.
6. **Revision policy default test** — synthetic small revision
   (0.05% on close) produces `flagged_only`, not `invalidated`.
7. **Revision policy escalation test** — synthetic large revision
   (3% on close) produces `invalidated` and the
   `requires_data_review` status.

Round R-fwd-3 (checkpoint pack):

8. **Checkpoint pack written at decision day boundary** — observe()
   crossing TD10 writes `<id>_forward_checkpoint_TD10.{json,md}`;
   later observes do NOT overwrite it.
9. **Checkpoint pack re-emission on state change** — if revisions
   accumulate after first pack, a `_v2` pack is written.
10. **Checkpoint pack content invariant** — JSON conforms to the
    documented schema; required keys present.

These ten tests + the existing 51-test forward slice should clear
1700+ on the full run.

---

## 7. HARD invariants

- ✗ Do NOT mutate any historical TD entry's `cum_ret` / `sharpe` /
  `max_dd` / `vs_spy` / `vs_qqq` after first write.
- ✗ Do NOT remove TD entries (append-only).
- ✗ Do NOT bypass schema validation by writing manifests via raw
  JSON.
- ✗ Do NOT make the checkpoint pack write conditional on cum_ret
  positivity or any other "looks good" gate — every reached
  decision-day must produce a pack regardless of result.
- ✗ Do NOT auto-promote / auto-paper-slot based on a checkpoint
  pack. Decision is a separate user step (per unfreeze memo §5).

---

## 8. Out-of-scope (deferred)

Same list as `forward_oos_runner_prd.md` §9, plus:

- Backfilling `bar_hash` onto the existing TD001 entries. Those
  entries are baseline (cum_ret=0.0); they predate the schema and
  are explicitly out of revision-guard scope. The first
  revision-guarded TD will be the first TD002 written under the
  extended schema.
- Cross-candidate revision correlation (e.g. flagging when both
  RCMv1 and Cand-2 are affected by the same revision event).
  Useful but not in this PRD.

---

## 9. Acceptance to ship this PRD

User commits this file with explicit approval. After commit:

- This PRD becomes the contract for R-fwd-2 / R-fwd-3 (when those
  rounds fire).
- The "≥3-5 real TD entries before implementation" gate from the
  original forward PRD STILL APPLIES — this PRD does not authorize
  implementation, only design.
- The `feedback_review_branch_doc_only.md` rule applies: review-log
  references this PRD by path; codex audits it on `main` HEAD
  rather than on review/claude-collab.

## 10. References

- Forward OOS Runner PRD: `docs/prd/20260426-forward_oos_runner_prd.md`
- Codex Round 6 audit (review log): `docs/claude_review_loop.md`
- yfinance overlap-fetch behavior: `scripts/fetch_data.py` +
  `core/data/market_data_store.py`
- Source boundaries: `core/data/source_boundaries.py` +
  `data/ref/daily_source_boundaries.parquet`
- Existing TD001 entries:
  `data/research_candidates/{rcm_v1_defensive_composite_01,candidate_2_orthogonal_01}_forward_manifest.json`
- M12 concentration (referenced by checkpoint pack §4.7):
  `core/backtest/concentration_metrics.py`
- Unfreeze memo (paper-slot rules): `docs/memos/20260426-research_layer_partial_unfreeze.md`

## 11. One-line summary

Pin the schema and contract for forward-evidence immutability and
checkpoint packs now, so when the implementation rounds fire (after
≥3-5 real TDs) they have an executable spec rather than a sketch.
