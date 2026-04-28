# Forward Evidence Hardening — PRD

**Status**: SHIPPED v2.1.1 — implementation in `core/research/forward/{bar_hash,source_layer,revalidate,runner,manifest_schema}.py`; live-data audit fixes folded in
**Date drafted**: 2026-04-27 (v1) / 2026-04-28 (v2 codex Round-7 revision; v2.1 codex Round-8 cleanup; v2.1.1 self-audit fixes during step 1-5 implementation rollout)
**Authority required**: user explicit (zibo)
**Authoring lineage**: codex review-loop Round 6 (`d8fd133`) §"Highest-ROI Recommendations P0"; v2 incorporates codex Round 7 (`c4d6a08`) blocking changes; v2.1 incorporates codex Round 8 (`e2ff695`) cleanup items; v2.1.1 incorporates 4 implementation-time audit fixes (`fd24285`)
**Supersedes / extends**: `docs/prd/20260426-forward_oos_runner_prd.md` §4.6 (overlap-fetch caveat) + §6 R-fwd-2 / R-fwd-3 outline
**Lineage tag (when committed)**: `forward-evidence-hardening-2026-04-27`
**Implementation commits**: `c3cefc1` step 1 (schema + resolver) → `9ee1b36` step 2 (per-scope hashers) → `74f73d0` step 3 (window-scoped source) → `b09f9b7` step 4 (revalidate + materiality) → `5cd51f3` step 5 (runner integration) → `fd24285` v2.1.1 audit fixes

### v1 → v2 changelog (codex Round-7 driven)

1. Single held-today `bar_hash` replaced with three **input-scope fingerprints** (`signal_input_hash` / `execution_nav_hash` / `benchmark_hash`); top-level `bar_hash` retained only as a roll-up of these three.
2. Per-symbol/date/attribute evidence (digests + selected old numeric values) added so `revised_symbols` and `delta_summary` are recoverable from the manifest, not just an aggregate hash.
3. Revision policy rewritten from **count-based** to **materiality-based**: invalidate on per-TD NAV impact ≥10 bps, checkpoint metric drift ≥25 bps, or decision-sign / gate-crossing flip. Raw close/open drift secondary guard tightened from 1.0% → 0.50%.
4. TD001 lazy migration boundary made explicit: TD002+ must hash the start-date input bars (the cumulative-return denominator); checkpoint packs surface `evidence_clean_start_label` and TD001 carries `legacy_unhashed_inputs=true`.
5. Source-layer classification changed from as-of-date single-point (`classify(sym, as_of)`) to **window-scoped** (`classify_window(sym, start, as_of, attributes)`); checkpoints aggregate both `as_of_held_source` and `window_input_source`.
6. Checkpoint pack JSON expanded to **decision-grade**: adds `evidence_quality`, `revision_materiality_bps`, exposure breakdown (net/gross/cash/leverage/high-risk-ETF), realized beta/correlation vs SPY/QQQ over the forward window, 1x/2x/3x cost-stress summary, M12 + watch-list + leveraged-ETF exposure.

### v2.1 → v2.1.1 changelog (implementation-time audit fixes)

Self-audit run between PRD v2.1 implementation and codex review.
Each finding was reproduced via direct end-to-end execution against
the real RCMv1 manifest + live `data/daily/*.parquet` store, NOT
just unit tests. All 4 issues map to v2.1 design points that
needed implementation-level clarification rather than design changes;
PRD logic stands.

1. **Storage budget pinned (PRD §G2 + §4.3 clarified).** v2.1 §G2
   estimated "60 TDs × ~10 holdings × 2 attrs × 10 days × 8 bytes ≈
   96 KB". A naïve implementation that stores `signal_input.per_cell_digest`
   over the full pre-top_n universe × 252-day lookback yields ~1.5 MB
   PER TD instead — manifest hits 4.6 MB at TD003 and would balloon
   to ~100 MB by TD60. The PRD now explicitly states:
   `signal_input` per_cell_digest **MUST be empty by default in
   production**; only the rolling hash is persisted for the signal
   scope. The rolling hash alone is sufficient for revision
   detection (signal-only revisions always fail-closed to bound_only
   regardless of cell granularity per the §4.3 coverage matrix).
   Production runner sets `track_per_cell=False`; tests opt in
   explicitly when asserting cell content. Resulting per-TD storage
   ≈ 30 KB (execution_nav per_cell + materiality_anchor + benchmark
   anchor + metadata).
2. **Revalidate trigger frequency clarified (PRD §4.6).** Original
   wording "revalidate is invoked from observe() automatically at
   the end of each successful append" can be read as "only on append"
   — but the daily-ritual purpose is to catch retroactive revisions
   that may land between observations including no-new-bar days
   (e.g. yfinance revising the prior day's close on Saturday).
   PRD now explicitly: revalidate runs at the **TOP** of every
   observe() call, regardless of whether new bars are available.
   If invalidation triggers, observe() persists events + flips
   status + returns without appending; if all events are
   flagged_only, observe() continues to append.
3. **Halt-guard contract added (PRD §4.4).** v2.1 introduced
   `requires_data_review` status but didn't explicitly require
   observe() to halt when manifest is already in that status. PRD
   now: observe() **MUST** raise `ForwardHaltError` at the top of
   the function when `current_status == requires_data_review`. Only
   `decide()` (with `completed_fail` / `aborted` / `completed_success`)
   may transition out of that state. This prevents silently
   overwriting prior `data_revision_event` records on subsequent
   observe runs.
4. **Float-precision tolerance on materiality thresholds (PRD §4.4 +
   E1-E5 table).** Revisions expressed as the canonical multiplicative
   idiom `*= 1.005` (i.e. "+0.5%") yield drift values like
   `0.00499999...` after binary float arithmetic. Strict `>= 0.005`
   silently misses boundary cases the operator clearly intended to
   fire. PRD now: thresholds compared with absolute epsilon
   (`_BPS_EPS = 1e-6`, `_PCT_EPS = 1e-9`) — well below any
   decision-relevant precision. Same fix on E1 (NAV impact 10 bps),
   E2/E3 (checkpoint metric drift 25 bps), and E5 (raw drift 0.50%).
5. **E4 sign-flip detection symmetric.** v2.1 implementation
   computed `stored_cum + drift / 10000` to detect sign flip — but
   `nav_impact_bps` is unsigned (the magnitude of the revision; the
   direction is unknown a priori). PRD clarification: E4 fires
   conservatively whenever `|drift_magnitude| >= |stored_cum|`,
   meaning at least one revision direction would flip the sign.

### v2 → v2.1 changelog (codex Round-8 cleanup)

1. **Stale §3 non-goal removed.** v1's "bar-hash guard scopes to held-today set" wording deleted; replaced with the v2 three-scope contract (signal = full pre-top_n universe; execution = held-or-traded; benchmark = SPY/QQQ).
2. **RCMv1 feature description corrected.** §1.4 incorrectly cited `mom_126d`; the frozen spec actually uses `beta_spy_60d / drawup_from_252d_low / days_since_52w_high / amihud_20d`. v1.4 example table now derived directly from the YAML.
3. **Factor input-contract resolver made explicit** (§4.3.0). New `resolve_factor_input_contract(spec) -> {factor: FactorInputContract}` helper with fail-closed unknown-factor guard. Pinned regression tests for RCMv1 + Cand-2 + an unknown-factor failure case prevent silent under-hashing.
4. **Old-numeric capture timing clarified.** G2 + §4.3 explicitly state `materiality_anchor_values` and `per_cell_digest` are captured at the TD's **observation time**, not at revision-detection time (by which point the original values are gone).
5. **Signal-scope materiality fallback added** (§4.3 coverage matrix + §4.4 fallback). A revision to a non-held name's signal input is detected via `per_cell_digest` but cannot be mapped to deterministic NAV impact without storing the cross-sectional ranked output, so v2.1 fail-closes to `bound_only` → `requires_data_review`. Same fail-closed treatment for high/low/volume revisions on held names (only close/open are anchored).
6. **`materiality_anchor_values` ring depth widened from 5 → 10 trading days** (codex Round-8 §6 preference; storage cost still negligible at ~96 KB / candidate / checkpoint horizon).
7. **Checkpoint pack `economic_distinction` correlation policy refined** (§4.7 + acceptance test 15b). Primary `rolling_corr_*_30d` for all packs; `expanding_corr_*` populated for TD10/20 to avoid blank/misleading early packs; `rolling_corr_*_60d` populated only at TD60+; 126d not added until forward cadence extends.

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

This PRD pins the **v2 schema + contract** for forward-evidence
immutability and checkpoint packs. It does NOT itself authorize the
R-fwd-2 / R-fwd-3 implementation rounds. The implementation rounds
remain gated on accumulating enough real TDs (per the prior PRD).
What this PRD ships when accepted: a frozen schema + contract +
test plan + migration story, so the implementation rounds when they
fire have an executable spec, not a sketch.

### 1.4 Why v1's held-today scope was insufficient

`observe()` (`core/research/forward/runner.py`) loads the full panel
from 1900-01-01, runs `_compute_composite(spec, panel)` over the
candidate's full universe, and runs `BacktestEngine.run(...,
price_df=panel["close"], open_df=panel["open"])` over the entire
[start_date..as_of] window. Per-TD `cum_ret` / `max_dd` slice from
that NAV path; `vs_spy` / `vs_qqq` slice SPY/QQQ closes over the
same window.

Concretely on `main f4ca217` (verified by codex Round-7/8 audit
against the frozen specs):

- RCMv1's composite (`data/research_candidates/rcm_v1_defensive_composite_01.yaml`)
  is `beta_spy_60d + drawup_from_252d_low + days_since_52w_high +
  amihud_20d` — `amihud_20d` reads volume (a volume revision on a
  *non-held* symbol can change the composite ranking and therefore
  tomorrow's fills); `drawup_from_252d_low` and `days_since_52w_high`
  push the close-input lookback out to 252 trading days, so the
  signal-input window per TD is much wider than the held-today set.
- Cand-2's composite (`data/research_candidates/candidate_2_orthogonal_01.yaml`)
  is `ret_5d + rs_vs_spy_126d + hl_range` — `hl_range` reads high
  and low; `rs_vs_spy_126d` extends the lookback to 126 days.
- `BacktestEngine` uses `open_df` for fill prices when supplied,
  which the runner does. An open revision on a previously-held
  symbol changes a historical fill price and thus the entire
  forward NAV path.
- `vs_spy` / `vs_qqq` use SPY / QQQ closes over the full window.

A held-today (sym, date, close, volume) hash misses all of the
above. v2 fingerprints the actual evidence path: signal input
window, execution NAV window, benchmark window.

**Per-candidate input contract derived from the frozen specs**
(consumed by §4.3's `compute_signal_input_hash`):

| candidate | factor | attributes | lookback (days) |
|-----------|--------|-----------|-----------------|
| RCMv1 | `beta_spy_60d` | close (sym + SPY) | 60 |
| RCMv1 | `drawup_from_252d_low` | close | 252 |
| RCMv1 | `days_since_52w_high` | close | 252 |
| RCMv1 | `amihud_20d` | close + volume | 20 |
| **RCMv1 (union)** | — | **close + volume (+ SPY close)** | **252** |
| Cand-2 | `ret_5d` | close | 5 |
| Cand-2 | `rs_vs_spy_126d` | close (sym + SPY) | 126 |
| Cand-2 | `hl_range` | high + low | ~20 |
| **Cand-2 (union)** | — | **close + high + low (+ SPY close)** | **126** |

---

## 2. Goals

### G1 — Per-TD input-scope fingerprints

Every `ForwardRun` entry whose checkpoint_label starts with `TD`
must record three scoped fingerprints, NOT a single held-today hash:

- **signal_input_hash** — hash of the raw bars needed by the candidate
  spec to compute its composite signal at `as_of_date` (lookback
  window = max factor lookback in the spec, resolved via
  `resolve_factor_input_contract(spec)` — e.g. 252d for RCMv1 from
  `drawup_from_252d_low` / `days_since_52w_high`, 126d for Cand-2
  from `rs_vs_spy_126d`).
- **execution_nav_hash** — hash of the open + close bars actually
  used by the backtest from `start_date` through `as_of_date`, over
  every symbol that was held or traded inside the window (NOT just
  symbols held at `as_of_date`). This is the bar set that determines
  fills and NAV.
- **benchmark_hash** — hash of SPY (and QQQ if `secondary_benchmark`)
  closes from `start_date` through `as_of_date`. These drive
  `vs_spy` / `vs_qqq` directly.

A top-level `bar_hash` field is retained as a roll-up
(`sha256(signal_input_hash || execution_nav_hash || benchmark_hash)`)
for cheap diff detection, but the three component hashes are the
binding evidence.

A subsequent re-fetch that mutates any of those bars must be
detectable from the manifest alone, with enough per-symbol
evidence stored to identify *which* symbols revised and *by how
much* (see G2).

### G2 — Recoverable revision evidence

When a re-fetch produces bar values that disagree with any of the
three scoped hashes on record, the system must record a
`data_revision_event` on **the affected TD entries** (not on the
manifest as a whole), with enough metadata to recover:

- the exact list of `revised_symbols`
- per-revised-symbol/date/attribute deltas (old vs new numeric
  values) sufficient to compute portfolio NAV impact in basis points

**Old values are captured at the original TD's observation time**
(not at detection time — by detection time the original values are
gone from the live store). Concretely, when `observe()` writes a
TD entry, it snapshots into `materiality_anchor_values` the close
+ open numerics for the held-or-traded set on the most recent
**10 trading days before-or-at `as_of_date`** (codex Round-8 §6
preferred 10d over 5d for fewer false `requires_data_review`
halts; storage cost is negligible). `revalidate()` then compares
those stored anchors against the current store to compute deltas.

`per_cell_digest` (per-(sym, date, attr) 8-char prefix digest) is
*also* captured at observation time and is what detects revisions
**inside** the per-scope hashed window. PRD v2.1.1 storage budget:

- `signal_input.per_cell_digest` MUST be empty by default in
  production. Storing the full pre-top_n × 252-day grid would
  balloon the manifest to >100 MB by TD60. The signal-scope
  rolling hash alone is sufficient for revision detection;
  signal-only revisions always fail-closed to bound_only per the
  §4.3 coverage matrix regardless of cell granularity. Tests may
  opt in to track per-cell signal digests via a `track_per_cell=True`
  flag for fine-grained attribution assertions.
- `execution_nav.per_cell_digest` IS populated (held-or-traded set
  × [start_date..as_of] × {close, open}). Typical size: 11 syms ×
  ~3 days × 2 attrs ≈ 70 cells × 50 bytes ≈ 3.5 KB per TD.
- `benchmark.per_cell_digest` IS populated (SPY/QQQ × window ×
  close). Typical size: ~1 KB per TD.

Total per-TD storage ≈ 30 KB (per_cell + materiality_anchor +
metadata). 60 TDs ≈ 1.8 MB per candidate per checkpoint horizon —
trivial relative to the audit value.

### G3 — Window-scoped source-layer attribution

Each TD must record source-layer attribution at **per-symbol +
window granularity**, not just as-of-date single-point. Replace
`classify(sym, as_of)` with `classify_window(sym, start, as_of,
attributes)`. Each TD aggregates two views:

- `as_of_held_source` — held-symbol layer at `as_of_date`
  (today's state)
- `window_input_source` — every (symbol, date, attribute) tuple
  that fed into either `signal_input_hash`, `execution_nav_hash`,
  or `benchmark_hash` (the actual evidence path)

Both views roll up to {canonical_only / frontier_only / mixed}
per-symbol counts. The legacy aggregate `source_mix` boolean stays
for backward-compat but is computed from the `as_of_held_source`
view.

### G4 — Materiality-based revision policy

The PRD must answer one binary question with a written rule:
**when a stored bar is revised by yfinance, is the affected prior
TD entry only flagged, or also invalidated as evidence?**

The v1 default of "flagged_only unless ≥3 symbols revised or any
single close drift ≥1.0%" is replaced with a materiality-based
escalation that reflects portfolio NAV impact, not just raw count.
See §4.4 for the rule table; in summary:

- default action = `flagged_only` for revisions whose estimated
  NAV impact and checkpoint-metric drift are below the materiality
  thresholds
- escalate to `invalidated` (with new `requires_data_review`
  status) when:
  - estimated per-TD NAV impact ≥10 bps, OR
  - estimated checkpoint metric drift (cum_ret / vs_spy / vs_qqq) ≥25 bps, OR
  - decision-sign flips on any frozen acceptance gate (G2.A
    watchlist ceiling, G2.B leveraged-ETF ceiling, M12 ceilings,
    QQQ Outperformance Rule), OR
  - raw close/open drift on any single (symbol, date) ≥0.50%
    (lowered from v1's 1.0%; still secondary guard, used to surface
    suspicious individual revisions even when weight × drift is
    small)
- the "≥3 symbols revised" rule survives only as a diagnostic
  surfaced in the checkpoint pack, NOT as a standalone invalidation
  trigger

### G5 — Decision-grade checkpoint evidence pack

At each `decision_days` boundary (10, 20, 40, 60), produce a
self-contained checkpoint pack
(`<id>_forward_checkpoint_TD{N}.{json,md}`) that aggregates not
just performance but full decision-grade evidence:

- **performance**: cum_ret, sharpe, max_dd, vs_spy, vs_qqq
- **execution**: fills, turnover, M12 top-1 / top-3 concentration
- **evidence quality**: `evidence_quality` ∈ {`clean`,
  `revision_flagged`, `requires_data_review`};
  `revision_materiality_bps` per-TD and aggregate
- **portfolio risk**: net / gross exposure, cash, leverage,
  high-risk leveraged-ETF (TQQQ / SOXL family) exposure, top
  positions
- **economic distinction**: realized beta and rolling correlation
  vs SPY and QQQ over the forward window (so we can see if the
  candidate is just a closet tracker)
- **cost stress**: 1x / 2x / 3x slippage forward NAV, especially
  important for Cand-2 whose `hl_range` factor implies elevated
  turnover assumptions
- **manifest invariants**: append-only intact, spec hash match,
  cost hash match
- **source-layer breakdown**: both `as_of_held_source` and
  `window_input_source` views (per G3)
- **regime notes**: optional human-readable regime context
- **evidence boundary**: `evidence_clean_start_label` (the first
  TD label whose entries carry the v2 input-scope hashes; TD001
  with `legacy_unhashed_inputs=true` is excluded from the
  guarantee)

### G6 — TD001 lazy migration boundary

Both manifests already have a `runs[0]` (TD001) entry. v1 said
"new fields are additive optional with sensible defaults so
existing entries continue to validate" — this is necessary but
not sufficient. Codex Round 7 §4 escalation: TD002+ must hash the
start-date input bars (the cumulative-return denominator),
because a revision to the start-date bar can affect every future
`cum_ret` in the manifest while remaining outside per-TD revision
scope.

Concretely:

- Existing TD001 entries carry `legacy_unhashed_inputs=true` and
  are explicitly **out** of revision-guard scope (their stored
  numerics are not re-validatable).
- The first TD002 written under the v2 schema computes
  `signal_input_hash` / `execution_nav_hash` / `benchmark_hash`
  over a window starting at `manifest.start_date` (not
  `TD002.as_of_date`); subsequent TDs hash the same anchored window
  expanded forward.
- Checkpoint packs surface `evidence_clean_start_label` so the
  reviewer knows TD001 is grandfathered.

### G7 — yfinance-revision regression test

A unit test must simulate the exact yfinance revision behavior
(latest-1-2-day adjusted close / volume drift, plus a synthetic
start-date bar revision case) and prove that:

- `signal_input_hash` / `execution_nav_hash` / `benchmark_hash`
  detect the appropriate revision class
- `revised_symbols` and `delta_summary` reconstruct correctly from
  the per-symbol stored evidence
- materiality calculation produces the expected NAV-impact bps
- escalation to `requires_data_review` fires only when the
  materiality threshold is crossed

---

## 3. Non-goals

- **Universe expansion** — out of scope. The three v2 input-scope
  hashes are bounded as follows; none of them grow the 79-symbol
  universe beyond what the candidate already references:
  - `signal_input_hash` scope = the candidate's full pre-top_n
    signal universe over the factor lookback window (already part
    of `panel_contract.universe` in the frozen spec).
  - `execution_nav_hash` scope = the held-or-traded set over
    `[manifest.start_date .. as_of_date]` (a strict subset of the
    signal universe).
  - `benchmark_hash` scope = SPY (and QQQ if `secondary_benchmark`)
    over `[manifest.start_date .. as_of_date]`.
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
    legacy_unhashed_inputs: Optional[bool] = Field(
        default=None,
        description=(
            "True for entries written before the v2 input-scope "
            "fingerprint schema shipped (e.g., TD001 baseline rows "
            "on RCMv1 / Cand-2). These rows are explicitly out of "
            "revision-guard scope. None on v2-and-later entries."
        ),
    )
    signal_input_hash: Optional[str] = Field(
        default=None, min_length=12,
        description=(
            "sha256(>=24 hex) of the raw bars feeding the candidate's "
            "composite signal at as_of_date. Lookback = max(factor "
            "lookbacks in the spec). Universe = full universe before "
            "top_n filtering, since signal computation reads all "
            "names. Attributes = the per-factor input attribute set "
            "(e.g., close+volume for amihud_20d; close+high+low for "
            "hl_range)."
        ),
    )
    execution_nav_hash: Optional[str] = Field(
        default=None, min_length=12,
        description=(
            "sha256(>=24 hex) of the open + close bars used by "
            "BacktestEngine from start_date through as_of_date over "
            "every symbol that was held or traded inside the window. "
            "This is the bar set that determines fills and NAV; "
            "revisions to it can change cum_ret without changing "
            "today's holdings hash."
        ),
    )
    benchmark_hash: Optional[str] = Field(
        default=None, min_length=12,
        description=(
            "sha256(>=24 hex) of SPY (and QQQ if "
            "secondary_benchmark) closes from start_date through "
            "as_of_date. Drives vs_spy / vs_qqq."
        ),
    )
    bar_hash: Optional[str] = Field(
        default=None, min_length=12,
        description=(
            "Roll-up: sha256(signal_input_hash || execution_nav_hash "
            "|| benchmark_hash). Cheap top-level diff; the three "
            "component hashes remain the binding evidence."
        ),
    )
    bar_hash_inputs: Optional[BarHashInputs] = Field(
        default=None,
        description=(
            "Reproducibility + materiality metadata: per-scope symbol "
            "lists, attribute sets, lookback windows, and per-symbol "
            "old-value snapshots sufficient to reconstruct "
            "revised_symbols and compute NAV-impact bps from a "
            "subsequent revision."
        ),
    )
    source_layer_breakdown: Optional[SourceLayerBreakdown] = Field(
        default=None,
        description=(
            "Two views: as_of_held_source (today's held layer) and "
            "window_input_source (every (symbol, date, attribute) "
            "tuple folded into the three input-scope hashes). "
            "Replaces the aggregate `source_mix` boolean."
        ),
    )
    data_revision_event: Optional[DataRevisionEvent] = Field(
        default=None,
        description=(
            "Set when a re-fetch produces bar values that disagree "
            "with this entry's stored input-scope hashes. None for "
            "entries that have not been re-validated, or whose stored "
            "hashes still match."
        ),
    )
```

New model classes:

```python
class PerScopeHashInputs(BaseModel):
    """Reproducibility evidence for one input-scope hash."""
    scope: Literal["signal_input", "execution_nav", "benchmark"]
    symbols: list[str]              # sorted; full universe for
                                    # signal_input, held-or-traded
                                    # set for execution_nav, [SPY, QQQ?]
                                    # for benchmark
    bar_attributes: list[str]       # the OHLCV subset folded in
    window_start: date              # signal: as_of - max_lookback
                                    # execution_nav / benchmark: start_date
    window_end: date                # always as_of_date
    bar_revision: str               # canonical-source pin (e.g.
                                    #   "trades_v2_late_report_dedup_2026-04-19"
                                    #   for polygon-canonical bars)
    # Per-(symbol, date, attribute) digest for fine-grained revision
    # detection without storing every value. Stored as a compact
    # mapping: { sym: { date: { attr: digest_short } } }.
    per_cell_digest: dict
    # Old numeric values for close + open on revised-detection
    # critical attributes, restricted to the held / traded set on
    # as_of_date and a small ring of recent dates (default: last
    # 10 trading days, codex Round-8 §6). Captured at TD
    # observation time, NOT at revision-detection time. Lets
    # revalidate() compute NAV-impact bps without re-running the
    # full backtest.
    materiality_anchor_values: dict  # { sym: { date: { "close": x,
                                     #                   "open":  y } } }


class BarHashInputs(BaseModel):
    """Top-level container holding all three per-scope input sets."""
    signal_input:   PerScopeHashInputs
    execution_nav:  PerScopeHashInputs
    benchmark:      PerScopeHashInputs


class SourceLayerView(BaseModel):
    canonical_only_n_symbols: int = Field(ge=0)
    frontier_only_n_symbols:  int = Field(ge=0)
    mixed_n_symbols:          int = Field(ge=0)
    # Sum must equal the relevant universe size for the view.
    # Validator enforces.


class SourceLayerBreakdown(BaseModel):
    as_of_held_source:    SourceLayerView   # today's held set
    window_input_source:  SourceLayerView   # every cell in the
                                            # three input-scope hashes


class DataRevisionEvent(BaseModel):
    detected_at_utc: datetime
    revised_symbols: list[str]
    detected_by_run_label: str   # which subsequent observe() call
                                 # noticed the divergence (e.g.
                                 # "TD007 / 2026-05-12")
    delta_summary: str           # short human-readable per-symbol
                                 # before/after summary
    # Materiality outputs (computed at detection time):
    estimated_nav_impact_bps:    Optional[float] = None
    estimated_cum_ret_drift_bps: Optional[float] = None
    estimated_vs_spy_drift_bps:  Optional[float] = None
    estimated_vs_qqq_drift_bps:  Optional[float] = None
    decision_sign_flip:          bool = False  # True if any frozen
                                               # gate's pass/fail
                                               # would change
    raw_max_close_drift_pct:     Optional[float] = None  # 0.50% guard
    affected_scopes: list[Literal[
        "signal_input", "execution_nav", "benchmark"
    ]]
    policy_decision: Literal["flagged_only", "invalidated"]
    # See §4.4 for the materiality rule table.
```

### 4.2 Backward-compat contract + TD001 boundary

All v2 fields are `Optional` with default `None`. Existing TD001
entries on RCMv1 / Cand-2 manifests load without modification.
Migration is **lazy**: no one-time backfill script is required.

**Explicit TD001 boundary** (codex Round-7 §4): the next `observe()`
call after this PRD ships rewrites the in-memory existing TD001
entry to set `legacy_unhashed_inputs=true` (the only mutation
permitted on a historical row, and it is metadata-only, not
numeric). All TD002+ entries are required to populate the v2
input-scope hashes anchored from `manifest.start_date`, NOT from
their own `as_of_date`. This ensures a revision to the start-date
bar (the cumulative-return denominator) is detectable.

Concretely:

- TD001 row: `legacy_unhashed_inputs=true`, all v2 hash fields
  remain `None`. Stored numerics (cum_ret, etc.) are NEVER
  rewritten.
- TD002 row written under v2 schema: `legacy_unhashed_inputs=false`
  (or `None`); `signal_input_hash` / `execution_nav_hash` /
  `benchmark_hash` populated; `execution_nav_hash` and
  `benchmark_hash` windows are anchored at `manifest.start_date`,
  expanding daily.
- Subsequent TDs: same anchoring; window_end advances to that TD's
  `as_of_date`.

A regression test pins this:

```python
def test_existing_TD001_entries_carry_legacy_marker_after_observe():
    # Load both real manifests; run observe() once; assert TD001
    # entry now has legacy_unhashed_inputs=true and v2 hash fields
    # remain None; assert n_observed_trading_days, cum_ret,
    # source_mix unchanged; assert any newly written TD has all
    # three v2 hashes populated and execution_nav_hash window
    # starts at manifest.start_date.
```

A second regression pins the start-date anchoring:

```python
def test_TD002_execution_nav_hash_anchored_at_start_date():
    # Synthetic 5-day forward run; assert execution_nav_hash on
    # TD002, TD003, TD004 share the same first-bar inputs (the
    # start_date OHLC) by reusing the materiality_anchor_values
    # for that date.
```

### 4.3 Per-scope hash construction

#### 4.3.0 Factor input-contract resolver (codex Round-8 §3)

`compute_signal_input_hash` cannot just trust the spec's
`feature_set` names — it must know each factor's raw attributes
and lookback so the hash is grounded in actual data dependencies,
not factor identity. Silent under-hashing (hashing fewer cells
than the factor actually reads) creates false confidence and is
worse than no hash at all. Therefore introduce:

```python
@dataclass(frozen=True)
class FactorInputContract:
    factor_name: str
    attributes: tuple[str, ...]   # subset of {open, high, low, close, volume}
    lookback_days: int            # max bars read by the factor
    cross_sectional: bool         # True if factor reads benchmark series
                                  # (e.g. beta_spy_60d, rs_vs_spy_126d)
    benchmark_symbols: tuple[str, ...] = ()  # populated when cross_sectional


def resolve_factor_input_contract(
    spec: FrozenStrategySpec,
) -> dict[str, FactorInputContract]:
    """Resolve every factor in spec.feature_set to its input contract.

    Implementation:
      - load core/factors/factor_registry.py → factor metadata
      - for factors not yet recorded in the registry, look up the
        factor's source function and read its docstring contract
        (e.g. _family_a_benchmark_relative for beta_spy_60d)
      - fail-closed: if a factor lacks an explicit contract entry,
        raise ContractResolutionError. v2 hash creation MUST refuse
        to proceed with an unknown factor; the operator must add a
        contract entry before forward observation can resume.

    Returns:
      { "beta_spy_60d":           FactorInputContract(("close",), 60,  True,  ("SPY",)),
        "drawup_from_252d_low":   FactorInputContract(("close",), 252, False, ()),
        "days_since_52w_high":    FactorInputContract(("close",), 252, False, ()),
        "amihud_20d":             FactorInputContract(("close","volume"), 20, False, ()),
        "ret_5d":                 FactorInputContract(("close",), 5,   False, ()),
        "rs_vs_spy_126d":         FactorInputContract(("close",), 126, True,  ("SPY",)),
        "hl_range":               FactorInputContract(("high","low"), 20, False, ()),
        ... }
    """
```

**Pinned regression tests** (RCMv1 + Cand-2 are the live frozen
specs; their contracts must not silently change):

```python
def test_resolve_factor_input_contract_rcm_v1():
    spec = FrozenStrategySpec.from_yaml_file(
        "data/research_candidates/rcm_v1_defensive_composite_01.yaml"
    )
    c = resolve_factor_input_contract(spec)
    assert set(c.keys()) == {
        "beta_spy_60d", "drawup_from_252d_low",
        "days_since_52w_high", "amihud_20d",
    }
    # Union of attributes:
    assert union_attributes(c) == {"close", "volume"}
    assert max_lookback(c) == 252
    # SPY pulled in via cross_sectional flag, not extra symbol:
    assert union_benchmark_symbols(c) == {"SPY"}


def test_resolve_factor_input_contract_cand_2():
    spec = FrozenStrategySpec.from_yaml_file(
        "data/research_candidates/candidate_2_orthogonal_01.yaml"
    )
    c = resolve_factor_input_contract(spec)
    assert set(c.keys()) == {"ret_5d", "rs_vs_spy_126d", "hl_range"}
    assert union_attributes(c) == {"close", "high", "low"}
    assert max_lookback(c) == 126
    assert union_benchmark_symbols(c) == {"SPY"}


def test_resolve_factor_input_contract_unknown_factor_fails_closed():
    # Synthetic spec with a factor name not in the registry; must
    # raise ContractResolutionError, NOT silently default to close-only.
    with pytest.raises(ContractResolutionError):
        resolve_factor_input_contract(synthetic_spec_with_unknown_factor)
```

#### 4.3.1 Per-scope hashers

Three pure functions, one per scope (each testable without observe()
machinery):

```python
def compute_signal_input_hash(
    *,
    spec: FrozenStrategySpec,         # determines lookback + attrs
    universe: list[str],              # full pre-top_n universe
    bar_panel: pd.DataFrame,          # OHLCV multi-attr
    as_of_date: date,
) -> tuple[str, PerScopeHashInputs]:
    """Window: as_of_date - max(factor lookbacks via
    resolve_factor_input_contract); end = as_of_date.
    Attributes: union of factor input attributes across the spec
    (close + volume + high + low as needed); benchmark_symbols
    folded in for cross_sectional factors."""


def compute_execution_nav_hash(
    *,
    held_or_traded_symbols: list[str], # union over [start_date..as_of]
    bar_panel: pd.DataFrame,           # OHLC multi-attr
    start_date: date,                  # manifest.start_date (anchored)
    as_of_date: date,
) -> tuple[str, PerScopeHashInputs]:
    """Window: start_date through as_of_date. Attributes: open + close
    (open drives fills; close drives EOD MTM)."""


def compute_benchmark_hash(
    *,
    benchmark_symbols: list[str],     # ["SPY"] or ["SPY", "QQQ"]
    bar_panel: pd.DataFrame,
    start_date: date,
    as_of_date: date,
) -> tuple[str, PerScopeHashInputs]:
    """Window: start_date through as_of_date. Attributes: close only."""


def compute_bar_hash_rollup(
    signal_h: str, exec_h: str, bench_h: str,
) -> str:
    """sha256(signal_h || exec_h || bench_h)[:24]."""
```

**Shared determinism constraints (apply to all three):**

- Same inputs → identical hash byte-for-byte. Sort
  symbols / dates / attributes lexicographically before
  serializing.
- **No floats-as-strings**: serialize via `f"{value:.10g}"` to
  avoid Python repr drift across versions / platforms. Tests must
  verify the hash is invariant to runtime float repr.
- **NaN handling**: deterministic — serialize NaN as the literal
  `"NaN"`. Real cases include delisting-in-flight on
  `execution_nav` and pre-IPO bars on `signal_input`.
- **Truncation**: 24 hex chars (96 bits). Random collision
  negligible at our scale (≤60 TDs × 3 scopes).

**Materiality evidence (codex Round-7 §2 + Round-8 §4-5):**

All capture below happens at the TD's **observation time** inside
`observe()`. After detection time the original values are gone from
the live store, so observation-time capture is the only point where
the old numerics can be preserved.

Each `PerScopeHashInputs.per_cell_digest` stores per-(symbol, date,
attribute) digest (8-char prefix of sha256(value-str)) so a
revalidate pass can identify *exactly* which cells changed without
re-reading the original raw values. Covers every cell folded into
the scope's hash.

Each `PerScopeHashInputs.materiality_anchor_values` stores the
**old close + open numeric value** for the held-or-traded set on
the last **10 trading days** before-or-at `as_of_date` (codex
Round-8 §6: 10d preferred over 5d for fewer false halts; storage
overhead negligible). This is the minimum state needed to compute
NAV-impact bps deterministically when a revision is detected on
those cells.

**Coverage matrix and fallback rules:**

| revision location | detection? | NAV-impact computable? | resolution |
|-------------------|-----------|------------------------|------------|
| `execution_nav` cell within 10-day anchor ring | ✅ via `per_cell_digest` | ✅ via `materiality_anchor_values` | normal materiality calc per §4.4 |
| `execution_nav` cell outside 10-day ring | ✅ via `per_cell_digest` | ❌ old close/open not stored | `materiality_estimate_class="bound_only"` → fail-closed → `requires_data_review` |
| `benchmark` cell (SPY/QQQ close) within 10-day ring | ✅ | ✅ | normal materiality calc |
| `benchmark` cell outside ring | ✅ | ❌ | `bound_only` → fail-closed |
| `signal_input` cell on a held/traded symbol within ring | ✅ | partial (close/open captured; volume/high/low not) | if revision is on close/open → normal calc; if on volume/high/low → `bound_only` → fail-closed (codex Round-8 §5) |
| `signal_input` cell on a non-held name (full universe) | ✅ via `per_cell_digest` | ❌ — NAV impact requires re-running cross-sectional ranking | `materiality_estimate_class="bound_only"` → fail-closed → `requires_data_review` (codex Round-8 §5) |

**Why fail-closed on non-held signal-input revisions:** signal_input
hashes the full pre-top_n universe so we *detect* a non-held name's
volume revision affecting `amihud_20d` rank, but the NAV impact
requires re-running the candidate's cross-sectional ranking and
top_n selection at the original observation time, which we cannot
reproduce without storing the entire ranked composite output. v2
deliberately does NOT store that — it would balloon the manifest
and substitute "more data" for "less hashing." Instead we take the
conservative path: detect the revision, escalate to
`requires_data_review`, force the user to `decide()`. This is
codex Round-8 §5's recommended fallback.

### 4.4 Materiality-based revision policy (resolves G4)

**Baseline action: `flagged_only`.**

When a re-fetch reveals that any cell folded into a prior TD's
input-scope hashes has changed, set `data_revision_event` on that
TD with `policy_decision="flagged_only"` by default. Do **NOT**
mutate the stored `cum_ret`, `sharpe`, `max_dd`, or any other
historical numeric field. The TD remains as-of its observation
moment; the revision event documents that the underlying data has
since drifted.

**Materiality computation at detection time:**

```
NAV_impact_bps[TD]   ≈ Σ_sym ( old_weight[sym, TD] × close_drift_pct[sym, recent] ) × 10000
cum_ret_drift_bps    ≈ ( cum_ret_recomputed - cum_ret_stored ) × 10000
vs_spy_drift_bps     ≈ ( vs_spy_recomputed - vs_spy_stored )   × 10000
vs_qqq_drift_bps     ≈ ( vs_qqq_recomputed - vs_qqq_stored )   × 10000
raw_max_close_drift_pct = max over revised cells of |new - old| / |old|
```

`old_weight` and `cum_ret_stored` come from the manifest itself.
`close_drift_pct` is derived from `materiality_anchor_values`
(stored old) versus the current store (live new).

**Escalation rule table** (any condition triggers
`policy_decision="invalidated"` and
`ForwardRunStatus.requires_data_review`):

| # | Trigger | Threshold | Rationale |
|---|---------|-----------|-----------|
| E1 | `NAV_impact_bps` for any TD | `≥ 10` | Per-TD NAV move that materially shifts decision-day cum_ret |
| E2 | `cum_ret_drift_bps` at next checkpoint | `≥ 25` | Decision-grade drift on the metric checkpoint review uses |
| E3 | `vs_spy_drift_bps` OR `vs_qqq_drift_bps` at next checkpoint | `≥ 25` | Same logic for SPY/QQQ relatives |
| E4 | `decision_sign_flip` on any frozen gate | `True` | G2.A watchlist ≤30%, G2.B leveraged-ETF ≤25%, M12 top-1 ≤40% / top-3 ≤70%, QQQ Outperformance Rule full-period / holdout / mean-OOS — any pass↔fail flip |
| E5 | `raw_max_close_drift_pct` on any single (sym, date) | `≥ 0.50%` | Secondary guard — surfaces suspicious individual revisions even when weight × drift is small (lowered from v1's 1.0%) |

**Diagnostics-only (no longer trigger invalidation):**

- "≥3 symbols revised" — surfaced in checkpoint pack as a
  `broad_revision_flag`, but not a standalone invalidation.
- yfinance's normal small (0.01-0.05% on adjusted close as new
  dividends / splits / late-reports work through) revisions stay
  `flagged_only`.

**Fallback when materiality cannot be precisely computed** (any
row in the §4.3 coverage matrix marked `bound_only` — e.g. a
revision outside the 10-day `materiality_anchor_values` ring, a
high/low/volume revision on a held name, or any revision on a
non-held name's signal input): mark `estimated_nav_impact_bps=None`
with a `materiality_estimate_class="bound_only"` annotation in
the event's `delta_summary`. Treat the event as
`requires_data_review` by default — fail-closed, because we cannot
prove materiality is below threshold.

**Why escalate by materiality, not count:**

- A 0.8% close revision on a 35% weight position moves portfolio
  NAV ~28 bps — decision-material even though only 1 symbol
  changed. The v1 "≥3 symbols" rule misses this entirely.
- Three 0.05% revisions on tiny tail positions move NAV by <1 bp
  combined — not decision-material even though count threshold is
  met.
- Decision-sign flips on frozen gates are categorically severe:
  the manifest is no longer evidence for the *same* candidate as
  promoted.

**Append-only contract preserved:** `invalidated` does NOT remove
the TD entry. It marks the entry's evidence as void, and blocks
further `observe()` until the user `decide()`s. The append-only
manifest property is unaffected.

### 4.5 Window-scoped source-layer breakdown

`observe()` currently calls `get_boundary(sym)` per held symbol on
`as_of_date`, which only certifies today's state. Per codex Round-7
§5, that is insufficient because metrics use a full window.
Replace the as-of-date lookup with a window-scoped helper:

```python
def classify_window(
    sym: str,
    start: date,
    as_of: date,
    attributes: list[str] = ("open", "close"),
) -> Literal["canonical_only", "frontier_only", "mixed"]:
    """Classify the (sym, [start..as_of], attributes) cells by source
    layer. canonical_only iff every cell is from polygon-canonical;
    frontier_only iff every cell is from yfinance frontier; mixed
    otherwise. Reads data/ref/bar_provenance.parquet."""
```

Each TD aggregates **two views** populated into
`SourceLayerBreakdown`:

```python
# View 1 — as_of_held_source: today's held set, attributes = close
# (matches the legacy source_mix definition; preserves the
# back-compat semantics of the existing boolean).
as_of_held_source = SourceLayerView(
    canonical_only_n_symbols = ...,
    frontier_only_n_symbols  = ...,
    mixed_n_symbols          = ...,  # always 0 for as_of view
                                     # (single-date classification)
)

# View 2 — window_input_source: every cell folded into the three
# input-scope hashes (signal_input ∪ execution_nav ∪ benchmark
# scopes). Symbol set = union of all three scopes. Attributes per
# scope as documented in §4.3. mixed_n_symbols > 0 if any symbol's
# bars over its applicable scope window crossed the source boundary.
window_input_source = SourceLayerView(
    canonical_only_n_symbols = ...,
    frontier_only_n_symbols  = ...,
    mixed_n_symbols          = ...,
)

source_layer_breakdown = SourceLayerBreakdown(
    as_of_held_source   = as_of_held_source,
    window_input_source = window_input_source,
)
```

The aggregate `source_mix` boolean stays for backward-compat,
computed from the `as_of_held_source` view to match v1 semantics:
`source_mix = (as_of_held_source.frontier_only_n_symbols +
              as_of_held_source.mixed_n_symbols) > 0`.

**Why both views matter:** a forward TD whose held set is fully
canonical at `as_of_date` may still have its 60-day beta lookback
window or its execution NAV path span the source boundary. The
checkpoint reviewer needs to see both — "is today clean" and "is
the evidence path clean".

### 4.6 Re-validation pass

A new entry point `runner.revalidate(candidate_id, ...) -> list[
DataRevisionEvent]` recomputes the three v2 input-scope hashes
(`signal_input_hash`, `execution_nav_hash`, `benchmark_hash`) for
every prior TD entry — except those marked
`legacy_unhashed_inputs=true` — and compares each to the stored
value. Mismatches:

1. Identify revised cells via `per_cell_digest` diff.
2. Reconstruct old close + open numerics from
   `materiality_anchor_values` for the recent ring; for revisions
   landing outside the ring, fall back to `bound_only` materiality
   (per §4.4).
3. Compute `estimated_nav_impact_bps` /
   `estimated_cum_ret_drift_bps` / `estimated_vs_spy_drift_bps` /
   `estimated_vs_qqq_drift_bps` and the `decision_sign_flip` boolean.
4. Apply the §4.4 escalation rule table to choose
   `policy_decision`.

Mismatches return as a list of revision events; the function
persists them on the corresponding TD entries (mutating only the
`data_revision_event` slot, never the historical numeric fields).

**When does revalidate run** (PRD v2.1.1 audit fix):

`revalidate_manifest()` MUST run at the **top** of every
`observe()` call — BEFORE the new-bar resolver — so retroactive
revisions are caught regardless of whether any new TD bars are
available that day. Pre-fix wording "at the end of each successful
append" silently skipped revalidate on no-new-bar days, defeating
the daily-ritual purpose. The function is also callable standalone
for audit purposes.

**Halt contract** (PRD v2.1.1 audit fix): when revalidate flips
status to `requires_data_review`, the next `observe()` call MUST
raise `ForwardHaltError` at the top of the function. Only
`decide()` (with `completed_fail` / `aborted` / `completed_success`)
may transition out of that state. This prevents silently
overwriting prior `data_revision_event` records on subsequent
observe runs.

**Float-precision tolerance** (PRD v2.1.1 audit fix): all E1-E5
threshold comparisons in the materiality table use absolute
epsilon tolerance (`_BPS_EPS = 1e-6`, `_PCT_EPS = 1e-9`) — far
below any decision-relevant precision but above the binary float
roundoff for canonical revision idioms like `*= 1.005`.

### 4.7 Decision-grade checkpoint pack (resolves G5)

At each TD that hits a configured `decision_days` boundary,
`runner.observe()` additionally writes:

- `data/research_candidates/<id>_forward_checkpoint_TD{N}.json`
- `data/research_candidates/<id>_forward_checkpoint_TD{N}.md`

JSON shape (codex Round-7 §6 expanded):

```json
{
  "schema_version": "2.0",
  "candidate_id": "...",
  "checkpoint_label": "TD060",
  "as_of_date": "2026-...",
  "n_observed_trading_days": 60,
  "evidence_clean_start_label": "TD002",
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
  "evidence_quality": {
    "class": "clean",   // clean | revision_flagged | requires_data_review
    "revision_materiality_bps": {
      "per_td_max_nav_impact":      0,
      "checkpoint_cum_ret_drift":   0,
      "checkpoint_vs_spy_drift":    0,
      "checkpoint_vs_qqq_drift":    0,
      "raw_max_close_drift_pct":    0.0,
      "decision_sign_flip_any_gate": false
    },
    "broad_revision_flag":           false,
    "td001_legacy_unhashed_inputs":  true
  },
  "portfolio_risk": {
    "net_exposure":          0.97,
    "gross_exposure":        0.97,    // long-only ⇒ gross == net
    "cash_pct":              0.03,
    "leverage":              1.00,    // long-only ⇒ ≤1.00
    "leveraged_etf_exposure_pct": 0.04,  // TQQQ / SOXL family
    "watchlist_total_share_pct":  0.18,  // G2.A diagnostic
    "top_positions": [
      { "sym": "...", "weight": 0.13 },
      { "sym": "...", "weight": 0.11 }
    ]
  },
  "economic_distinction": {
    "realized_beta_vs_spy": 0.85,
    "realized_beta_vs_qqq": 0.78,
    // Primary correlation field for ALL packs (TD10 / 20 / 40 / 60).
    "rolling_corr_spy_30d": 0.92,
    "rolling_corr_qqq_30d": 0.88,
    // Expanding-sample fallback when the forward run has fewer
    // than 30 TDs (TD10 and TD20 packs); equals
    // rolling_corr_*_30d once n_observed_trading_days >= 30.
    // Prevents the early packs from being blank or misleading.
    "expanding_corr_spy":   0.91,
    "expanding_corr_qqq":   0.86,
    // Longer window — populated only at TD60+ (i.e. when
    // n_observed_trading_days >= 60). null before that. Codex
    // Round-8 §7: 126d unnecessary at the current 10/20/40/60
    // cadence.
    "rolling_corr_spy_60d": null,
    "rolling_corr_qqq_60d": null
  },
  "cost_stress": {
    "1x_cost_cum_ret":  0.034,
    "2x_cost_cum_ret":  0.022,
    "3x_cost_cum_ret":  0.011,
    "1x_cost_sharpe":   0.82,
    "2x_cost_sharpe":   0.55,
    "3x_cost_sharpe":   0.28
  },
  "source_layer_aggregate": {
    "as_of_held": {
      "canonical_only_days": 42,
      "frontier_only_days":   3,
      "mixed_days":          15,
      "source_mix_days":     18    // frontier + mixed
    },
    "window_input": {
      "canonical_only_n_cells": ...,
      "frontier_only_n_cells":  ...,
      "mixed_n_cells":          ...
    }
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

**Field rationale (decision-grade additions):**

- `evidence_quality.class`: a single label for the reviewer.
  `clean` ⇔ no revisions detected over the pack window.
  `revision_flagged` ⇔ revisions detected, all below materiality
  thresholds. `requires_data_review` ⇔ at least one E1-E5 trigger
  fired (per §4.4).
- `revision_materiality_bps`: aggregate of the per-TD materiality
  estimates. `per_td_max_nav_impact` is the worst single-TD impact
  in the pack window; the others are checkpoint-level drift.
- `td001_legacy_unhashed_inputs`: explicit reminder that TD001 is
  grandfathered out of revision-guard scope. Prevents the pack
  from overstating cleanliness.
- `portfolio_risk`: invariant constraints (long-only, leveraged-ETF
  caps, watchlist concentration) verified against the actual
  weight history. Necessary for paper-slot / production
  decision-making, not just performance review.
- `economic_distinction`: realized beta and rolling correlation
  vs SPY/QQQ — addresses "is this candidate genuinely distinct
  from the benchmark or just a closet tracker?"
- `cost_stress`: 1x / 2x / 3x slippage NAV. Especially critical
  for Cand-2 whose `hl_range` factor implies elevated turnover
  assumptions; without this, a high-turnover candidate's forward
  NAV looks healthy at 1x cost but degrades materially at the
  cost levels real execution will hit.

Markdown shape: human-readable summary of the JSON, formatted to
fit within a checkpoint review email / PR description. Must
explicitly call out `evidence_quality.class` and any non-zero
`revision_materiality_bps` in the first 5 lines.

The pack is **immutable once written** — re-running observe() past
the same TD does NOT overwrite existing checkpoint pack files. A
secondary `<id>_forward_checkpoint_TD{N}_v2.{json,md}` is written
if the underlying state has changed since the first write (e.g.
new revision events accumulated, evidence_quality class change).
Numbering is monotonic.

### 4.8 Module layout

```
core/research/forward/
  manifest_schema.py    [edit]   add v2 models (PerScopeHashInputs,
                                 BarHashInputs, SourceLayerView,
                                 SourceLayerBreakdown extended,
                                 DataRevisionEvent extended) + 1
                                 enum value (requires_data_review)
                                 + legacy_unhashed_inputs field
  runner.py             [edit]   observe() writes v2 fields, marks
                                 TD001 legacy on first v2 invocation,
                                 anchors execution_nav / benchmark
                                 windows at manifest.start_date,
                                 calls _maybe_write_checkpoint_pack,
                                 calls revalidate at end
  bar_hash.py           [new]    compute_signal_input_hash,
                                 compute_execution_nav_hash,
                                 compute_benchmark_hash,
                                 compute_bar_hash_rollup, plus
                                 per_cell_digest + materiality_anchor
                                 helpers
  source_layer.py       [new]    classify_window(sym, start, as_of,
                                 attributes) -> 'canonical_only' |
                                 'frontier_only' | 'mixed';
                                 wraps data/ref/bar_provenance.parquet
  checkpoint_pack.py    [new]    build + write JSON/MD pack from
                                 manifest + per-TD details, including
                                 evidence_quality, materiality_bps,
                                 portfolio_risk, economic_distinction,
                                 cost_stress sections
  revalidate.py         [new]    revalidate(candidate_id) ->
                                 list[DataRevisionEvent]; computes
                                 NAV-impact / cum_ret / vs_spy /
                                 vs_qqq drift bps and decision-sign
                                 flips against frozen gate thresholds
  cost_stress.py        [new]    helper that re-runs the windowed
                                 BacktestEngine at 2x / 3x cost
                                 multipliers and returns NAV +
                                 sharpe; consumed by checkpoint pack
```

`source_boundaries.py` already exists in `core/data/`; reuse for
the underlying provenance lookups rather than re-implementing.
`classify_window` wraps it.

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
   under the v2 schema; existing TD001 entries validate; first
   v2 observe() marks TD001 with `legacy_unhashed_inputs=true`
   without touching numerics.
2. **Per-scope hash determinism** — `signal_input_hash`,
   `execution_nav_hash`, `benchmark_hash` each produce byte-identical
   bytes across two runs in different processes (cross-platform
   float repr safe).
3. **Per-scope hash NaN-safe** — symbols with NaN bars in any of
   the three scopes produce deterministic hashes (delisting in
   flight + pre-IPO bars).
4. **execution_nav_hash anchored at start_date** — TD002 / TD003 /
   TD004 share the same first-bar contribution; mutating the
   start-date OHLC triggers revisions on every TD2..TDN.
5. **Window-scoped source classification** — synthetic panel where
   sym X is canonical for [start..as_of-30d] and frontier for the
   most recent 30d returns `mixed` from `classify_window`. The
   `as_of_held_source` view classifies it as frontier on as_of
   (single-date), the `window_input_source` view classifies it as
   mixed.
6. **Source-layer breakdown sums correctly** — for both views,
   buckets sum to the relevant universe size.
7. **Revision-detection golden test** — write a TD entry with v2
   hashes over panel P; mutate one cell in each of the three
   scopes (one at a time); revalidate; assert the
   `data_revision_event.affected_scopes` correctly identifies
   which scope (and only which scope) detected the change, and
   `revised_symbols` reconstructs from `per_cell_digest` +
   `materiality_anchor_values`.
8. **Materiality calculation** — synthetic revision: weight 35%,
   close drift 0.8% → `estimated_nav_impact_bps ≈ 28`; assert the
   computation matches expectation. Smaller weights × drift
   produce <10 bps; threshold E1 fires only on the 28-bps case.
9. **Materiality fallback when out-of-ring** — revision lands 15
   trading days back (outside the 10-day anchor ring); assert
   `estimated_nav_impact_bps=None`,
   `materiality_estimate_class="bound_only"`, and
   `policy_decision="invalidated"` (fail-closed).
9b. **Materiality fallback on non-held signal-input revision** —
    a non-held universe name's volume cell revises; assert
    `affected_scopes=["signal_input"]`,
    `materiality_estimate_class="bound_only"`,
    `policy_decision="invalidated"` (codex Round-8 §5).
9c. **Factor input contract resolver** — RCMv1 spec resolves to
    {beta_spy_60d / drawup_from_252d_low / days_since_52w_high /
    amihud_20d}, attribute union {close, volume}, max lookback
    252, benchmark SPY; Cand-2 spec resolves to {ret_5d /
    rs_vs_spy_126d / hl_range}, attribute union {close, high,
    low}, max lookback 126, benchmark SPY; unknown factor name
    raises `ContractResolutionError` (codex Round-8 §3).
10. **Decision-sign flip detection** — synthetic revision that
    pushes `watchlist_total_share_pct` from 28% to 31% (crosses
    G2.A 30% ceiling) → `decision_sign_flip=True` →
    `requires_data_review`.
11. **Default flagged_only on small revision** — synthetic
    revision (0.05% close drift on a 5% weight position) →
    `policy_decision="flagged_only"`, NAV impact <1 bp, no
    invalidation.
12. **Raw drift secondary guard** — synthetic 0.55% close drift on
    a 0.1% weight (NAV impact ~0.06 bps, well below E1) → still
    triggers E5 (≥0.50% raw drift) → `requires_data_review`.

Round R-fwd-3 (decision-grade checkpoint pack):

13. **Checkpoint pack written at decision day boundary** — observe()
    crossing TD10 writes `<id>_forward_checkpoint_TD10.{json,md}`;
    later observes do NOT overwrite it.
14. **Checkpoint pack re-emission on state change** — if revisions
    accumulate after first pack, a `_v2` pack is written.
15. **Checkpoint pack content invariant — required v2 sections** —
    JSON contains all of: `evidence_quality`, `revision_materiality_bps`,
    `portfolio_risk` (with `leveraged_etf_exposure_pct` and
    `watchlist_total_share_pct`), `economic_distinction` (with
    realized beta + 30d rolling corr vs SPY and QQQ +
    expanding-sample corr; 60d corr null if
    n_observed_trading_days < 60, populated otherwise),
    `cost_stress` (1x/2x/3x cum_ret + sharpe),
    `source_layer_aggregate.as_of_held` AND
    `source_layer_aggregate.window_input`,
    `evidence_clean_start_label`,
    `td001_legacy_unhashed_inputs`.
15b. **Expanding-sample correlation populated on early packs** — TD10
     and TD20 packs have `expanding_corr_spy` / `expanding_corr_qqq`
     populated, NOT null. `rolling_corr_*_60d` is null on TD10 / 20 /
     40, populated on TD60. Codex Round-8 §7.
16. **evidence_quality class transitions** — pack with no events =
    `clean`; pack with events all <materiality = `revision_flagged`;
    pack with any E1-E5 trigger = `requires_data_review`.
17. **Cost stress reproducibility** — re-running the cost-stress
    helper at 2x cost on a synthetic forward panel produces a
    deterministic NAV (no random sampling) and matches the JSON
    value byte-for-byte across two invocations.
18. **Markdown surfaces evidence_quality first** — assert the .md
    pack contains `evidence_quality.class` and any non-zero
    `revision_materiality_bps` in the first 5 non-blank lines.

These ~18 tests + the existing 51-test forward slice should clear
~1700 on the full run.

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

- Retro-hashing TD001 entries. They carry `legacy_unhashed_inputs=true`
  and are explicitly outside revision-guard scope. The first
  revision-guarded TD is the first TD002 written under v2 schema,
  with windows anchored at `manifest.start_date`.
- Cross-candidate revision correlation (e.g. flagging when both
  RCMv1 and Cand-2 are affected by the same revision event).
  Useful but not in this PRD.
- Dividend-yield treatment in evidence. The current store does
  not surface dividends as a separate field (per CLAUDE.md
  Pricing and Valuation Semantics: dividends not currently
  applied). When a dividends sidecar lands, a v3 PRD round will
  extend `signal_input_hash` and `execution_nav_hash` attribute
  sets accordingly. Until then, frontier yfinance auto-adjusted
  semantics are documented via `bar_revision` in
  `PerScopeHashInputs`.
- Real-time materiality recompute on every `observe()`. v2's
  materiality calc runs at revision-detection time
  (`revalidate()`) and at checkpoint-pack write time, NOT on
  every TD. Continuous recompute is a future optimization if
  revision frequency turns out higher than expected.

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
- Codex Round 6 audit (review log, v1 driver): `docs/claude_review_loop.md`
- Codex Round 7 audit (review log, v2 driver — `c4d6a08` on
  `review/claude-collab`): `docs/claude_review_loop.md`
  §"Round 7 Audit (Codex) - Forward Evidence PRD Needs Scope Correction"
- Codex Round 8 audit (review log, v2.1 cleanup driver — `e2ff695`
  on `review/claude-collab`): `docs/claude_review_loop.md`
  §"Round 8 Audit (Codex) - PRD v2 Direction Accepted, Cleanup Required Before Implementation"
- Frozen specs whose factor lists drive `resolve_factor_input_contract`:
  `data/research_candidates/rcm_v1_defensive_composite_01.yaml`,
  `data/research_candidates/candidate_2_orthogonal_01.yaml`
- Forward runner code under audit: `core/research/forward/runner.py`
  (`observe()` loads full panel + uses open_df + slices NAV from
  start_date..as_of; the canonical evidence path)
- Bar provenance sidecar (source-layer reads): `data/ref/bar_provenance.parquet`
- yfinance overlap-fetch behavior: `scripts/fetch_data.py` +
  `core/data/market_data_store.py`
- Source boundaries: `core/data/source_boundaries.py` +
  `data/ref/daily_source_boundaries.parquet`
- Existing TD001 entries:
  `data/research_candidates/{rcm_v1_defensive_composite_01,candidate_2_orthogonal_01}_forward_manifest.json`
- M12 concentration (referenced by checkpoint pack §4.7):
  `core/backtest/concentration_metrics.py`
- Frozen acceptance gates referenced by E4 decision-sign flip
  (G2.A watchlist 30%, G2.B leveraged-ETF 25%, M12, QQQ rule):
  `data/research_candidates/research-cycle-2026-04-26-01_promotion_criteria.yaml`,
  `core/backtest/concentration_metrics.py`, CLAUDE.md
  §"QQQ Outperformance Rule"
- Unfreeze memo (paper-slot rules): `docs/memos/20260426-research_layer_partial_unfreeze.md`

## 11. One-line summary

Pin the v2 schema and contract for forward-evidence immutability —
input-scope fingerprints over signal lookback / execution NAV /
benchmark windows, materiality-based revision policy, decision-grade
checkpoint packs — so when the implementation rounds fire (after
≥3-5 real TDs) they have an executable spec rather than a sketch.
