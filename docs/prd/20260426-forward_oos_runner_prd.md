# Forward OOS Runner + Checkpoint Pipeline — PRD v1

**Date**: 2026-04-26
**Author**: Claude (drafted post-OOSMVPDONE per user direction
"forward OOS runner is the next big direction")
**Lineage tag (planned)**: `forward-oos-runner-2026-04-26`
**Status**: DRAFT — not yet authorized for execution; user review +
explicit unfreeze required before any code lands.
**Supersedes / extends**:
- `docs/prd/20260425-oos_validation_framework_codex_v3.md` §B
  (forward manifest schema — already shipped in OOS MVP R5)
- `docs/memos/20260425-oos_mvp_close.md` §6 (re-freeze status note;
  this PRD is the "fresh PRD round" required to reopen forward
  execution per the closeout memo)

---

## 1. Background

The OOS MVP (R1-R7, commits 22d1ff3..cfac98f, plus audit fixes
31b128f / 78b7c1d / c455dd1) shipped:

- pseudo-OOS robustness eval runner (`core/research/robustness/`)
- M12 concentration gate (`core/research/concentration/`, with
  weighted thin-data + sector + beta dimensions)
- watch-list exposure section in master + drift reports
- **forward run manifest SCHEMA** (`core/research/forward/`) — schema
  only, NO runner

Per PRD v3 §1.1 + §1.3: pseudo-OOS robustness is *not* deployable
OOS evidence. The chronic trap the framework warns about ("在更可信
的数据上重新做一轮更高级的 in-sample 叙事") is precisely what
robustness-only would be if treated as proof of strategy quality.

To reach a deployable system, the next gate is **real forward
observation**: bars that did not exist at the candidate's
frozen-date, observed AFTER the spec / cost / cadence are pinned.

This PRD designs the runner that performs that observation against
the schema R5 already locked in.

## 2. Goals

1. **Forward observation engine**: a runnable component that, given
   a frozen candidate, advances forward through post-frozen-date
   trading days as new bars arrive, replays the candidate against
   each new day, and accumulates NAV / fills / metrics.
2. **Checkpoint discipline**: at 10 / 20 / 40 / 60 TD post-frozen-date
   (and weekly), emit standardized checkpoint artifacts so the user
   can review forward behavior on a fixed cadence rather than ad hoc.
3. **Manifest-as-contract**: the forward manifest (R5 schema) is the
   single source of truth. The runner READS the manifest at start
   and writes the runs[] entries; it never re-derives the contract.
4. **No hindsight tuning**: cost / cadence / spec / benchmark are
   all pinned at start in the manifest; runner has no path to mutate
   them mid-run. PRD v3 §B: "forward 不得被 hindsight 调参污染".
5. **Honest evidence_class**: the runner only writes
   `evidence_class=forward_oos` to manifests when bars are post-
   frozen-date. R5 schema already enforces this at construction; the
   runner must not bypass it (e.g., never call
   `model_dump(mode="json")` and edit the dict).

## 3. Non-goals

- Live broker integration (no real fills against a real broker).
- Real-time alerts / scheduler / daemon. Runner is a CLI invoked
  manually; daily cron is acceptable but out of MVP scope.
- Promoting a candidate past S2_paper_candidate. Promotion remains
  a separate user decision based on forward outcome.
- Reopening mining / universe / Candidate-3.
- Refactoring or extending R5 manifest schema beyond what's
  strictly required to write entries.

## 4. Design

### 4.1 Module layout (proposed)

```
core/research/forward/
├── __init__.py           (re-exports — current)
├── manifest_schema.py    (R5 — current)
├── manifest_io.py        (NEW — load/save JSON with validation)
├── runner.py             (NEW — the forward observation engine)
└── checkpoints.py        (NEW — 10/20/40/60 TD reduce + emit)

dev/scripts/oos_mvp/
├── run_robustness_eval.py    (current)
├── smoke.py                  (current)
└── run_forward_observe.py    (NEW — CLI to advance + emit checkpoints)
```

### 4.2 Manifest lifecycle

**Initialization** (one-time per candidate):

```
forward init --candidate-id <id> --start-date YYYY-MM-DD
  -> writes data/research_candidates/<id>_forward_manifest.json
     with:
       schema_version=1.0
       evidence_class=forward_oos
       spec_hash=<sha256 of frozen yaml>
       start_date=<arg>
       benchmark="SPY", secondary="QQQ"
       cost_assumptions={source, config_hash}
       checkpoint_cadence={weekly:true, decision_days:[10,20,40,60]}
       current_status="not_started"
       data_integrity_snapshot={...current data state...}
       runs=[]
```

The init step is intentionally separate from the observe step so
the user can review the manifest BEFORE any bar is observed —
this is the "spec frozen at start" guarantee.

**Observation** (each forward trading day, after market close):

```
forward observe --candidate-id <id>
  -> reads <id>_forward_manifest.json
  -> determines latest observable date (last data/daily bar
     post-start_date)
  -> for each new TD since the last run entry:
       compute composite signal on data up to that TD
       compute target weights (top-N etc.)
       execute via BacktestEngine (replay-style, T+1 open)
       compute NAV / fill_count / vs_spy / vs_qqq
       APPEND to manifest.runs (don't overwrite previous entries)
  -> if a checkpoint day reached (10/20/40/60 TD), also emits
     <id>_forward_checkpoint_{N}d.{json,md}
  -> updates manifest.current_status to "in_progress" or
     "decision_pending" (after 60 TD checkpoint)
```

**Decision points** (user-driven):

At 60 TD `decision_pending` the user reviews the cumulative forward
outcome and either:
- Marks `current_status="completed_success"` (forward passed; manual
  promotion past S2 still needed if applicable)
- Marks `current_status="completed_fail"` (forward failed; candidate
  remains S2 indefinitely or user revokes)
- Marks `current_status="aborted"` (user halt mid-window for any
  reason — e.g., regime shift made the forward irrelevant)

Status mutations are CLI-driven (`forward decide --status ...`); the
runner never auto-decides.

### 4.3 Per-day observation contract

Each `ForwardRun` entry written by `observe`:

```python
ForwardRun(
    checkpoint_label="<TD-day>",     # e.g. "TD003" or "weekly_w01" or "10TD"
    as_of_date=<that day's date>,
    n_observed_trading_days=<count since start_date>,
    cum_ret=<cumulative return since start>,
    sharpe=<annualized Sharpe>,       # null until enough obs
    max_dd=<max drawdown>,
    vs_spy=<excess vs SPY cumulative>,
    vs_qqq=<excess vs QQQ cumulative>,
    notes=<any per-day note (e.g. 'data backfilled')>,
)
```

Two writes per day in the typical case:
1. `TD<NNN>` daily entry
2. (Friday or end-of-week) `weekly_w<NN>` aggregation entry

Weekly + TD entries co-exist; no entry replaces another. The
manifest's runs list is append-only.

### 4.4 Checkpoint reduction

At 10/20/40/60 TD, `checkpoints.py` produces a reduce of the
manifest entries up to that TD into a structured checkpoint
artifact:

- `<id>_forward_checkpoint_{N}d.json`: aggregate metrics +
  per-day series + flag list
- `<id>_forward_checkpoint_{N}d.md`: human-readable narrative

Flags computed at each checkpoint:

- `early_pass_signal`: cum_ret > 0 AND vs_spy > 0 (informational
  only; PRD §B: "forward 不因 10TD 或 20TD 结果好看而提前宣称
  deployable")
- `early_fail_signal`: cum_ret < -5% OR max_dd < -10%
- `regime_shift_alert`: vs_qqq direction reversed vs construction
  window (would warrant aborted status if confirmed at next
  checkpoint)

**Source-layer breakdown (R-fwd-3 must include)**, per
2026-04-26 user audit feedback:

- `source_mix_days`: count of TD entries where `source_mix=True`
- `canonical_only_days`: count where `source_mix=False`
- `frontier_only_days`: count where source_layer (computed via
  per-day held-symbol boundary lookup) is purely on the frontier
  side — distinct from "mixed within window"

Surfaces these prominently in the checkpoint markdown narrative
because in the early forward sample (3-5 TDs), source-layer
context matters more than the raw return numbers.

**Hard rule**: checkpoints are REPORT-ONLY. They never mutate
candidate_registry status, never re-write the manifest's
`current_status`, never auto-promote / auto-revoke.

### 4.5 Cost / cadence pinning

The runner reads cost from `manifest.cost_assumptions.source` (a
config path). At each observation it:

1. Reads the cost yaml at the path
2. Computes its sha256
3. Compares against `manifest.cost_assumptions.config_hash`
4. **If mismatched**: HALT with explicit error. The runner never
   silently accepts a changed cost model — the manifest's
   config_hash is the contract.

Cadence is similar: `manifest.checkpoint_cadence.decision_days` is
read once at init; runner uses it as the truth.

## 5. CLI

```
forward init    --candidate-id <id> [--start-date YYYY-MM-DD]
                                    [--benchmark SPY] [--secondary QQQ]
                                    [--decision-days 10,20,40,60]
                                    [--data-integrity-commit <sha>]

forward observe --candidate-id <id> [--up-to YYYY-MM-DD]
                                    [--dry-run]

forward decide  --candidate-id <id> --status <enum>
                                    [--notes "..."]

forward status  --candidate-id <id>   # print current state
```

Exit codes:
- 0 = success (init created / observe advanced N days / decide
  applied / status printed)
- 1 = manifest validation error (don't write anything)
- 2 = data unavailable (e.g., observe called but no new bars)
- 3 = HALT condition (cost hash mismatch, cadence violation,
  attempt to flip evidence_class, etc.)

## 6. Acceptance gates (per ralph-loop round if executed via loop)

Round R-fwd-1: schema-aware manifest IO
- `manifest_io.py` load/save with `ForwardRunManifest.model_validate`
- `forward init` CLI works on RCMv1 frozen spec
- 5+ unit tests
- pytest no regression

Round R-fwd-2: observation engine
- `runner.py::observe(candidate_id, up_to_date) -> list[ForwardRun]`
- Reuses `core.research.robustness.runner._load_panel /
  _compute_composite / _composite_to_target_weights / BacktestEngine`
  pipeline (DRY: don't duplicate the panel + composite logic)
- Cost hash verification (HALT on mismatch)
- 8+ unit tests covering: append-only manifest writes / cost hash
  mismatch HALT / data-unavailable graceful exit / spec_hash
  verification / multi-day catch-up / weekly aggregation entry

Round R-fwd-3: checkpoint pipeline
- `checkpoints.py::reduce_to_checkpoint(manifest, n_td)` →
  `<id>_forward_checkpoint_{N}d.{json,md}`
- 4 checkpoint flags computed (early_pass / early_fail /
  regime_shift / nominal)
- Markdown narrative generation
- 6+ unit tests

Round R-fwd-4: integration smoke + end-to-end CLI
- `dev/scripts/oos_mvp/run_forward_observe.py` end-to-end
- Synthetic test: 65 TD synthetic bars, verify manifest grows
  to 65 entries + 4 checkpoint files emitted at TDs 10/20/40/60
- Real-data test: skipped if data/daily/SPY.parquet < frozen-date+1d

Round R-fwd-5: docs + decision memo + emit FWDOOSDONE
- Closeout memo `docs/memos/<date>-forward_oos_runner_close.md`
- CLAUDE.md TODO update
- INDEX update
- `<promise>FWDOOSDONE</promise>` at top of R7 reply

## 7. HARD invariants

The forward runner workstream MUST honor:

- ✗ Do NOT modify R5 manifest schema (`manifest_schema.py`) without
  bumping `schema_version`. Any field addition is permitted only as
  optional, default-None.
- ✗ Do NOT permit any path that would write a manifest with
  `evidence_class != forward_oos`. R5 schema rejects these at
  construction; the runner must not bypass via raw dict writes.
- ✗ Do NOT mutate frozen candidate spec yamls.
- ✗ Do NOT modify candidate_registry state-machine enum.
- ✗ Do NOT auto-promote / auto-demote / auto-revoke based on
  forward outcome. Status changes are user-driven via
  `forward decide`.
- ✗ Do NOT alter cost_model.yaml mid-run. Cost hash mismatch =
  HALT.
- ✗ Do NOT rebuild data/daily/*.parquet.
- ✗ Do NOT add new dependencies (requirements / pyproject
  unchanged).
- ✗ Do NOT touch config/*.yaml.
- ✗ Do NOT modify PRODUCTION_FACTORS.

## 8. Operational ergonomics

- One manifest per candidate. Multiple concurrent forward runs are
  supported (RCMv1 + Cand-2 in parallel) — they're independent
  files.
- The append-only constraint on `runs[]` means a re-run of `observe`
  is idempotent: it advances only past the last entry's `as_of_date`.
- `dry-run` flag on `observe` shows what would be appended without
  writing the manifest. Useful for debugging.
- Cron-friendly: `python dev/scripts/oos_mvp/run_forward_observe.py
  --candidate-id <id>` returns 0 even when no new bars are
  available; that's a no-op.

### 4.6 fetch_data overlap-fetch caveat (post-2026-04-26 audit note)

`scripts/fetch_data.py` uses `start = last_date` (NOT `last_date + 1d`)
when calling yfinance, so each daily fetch re-downloads the most
recent stored day and lets `MarketDataStore.append`'s
`drop_duplicates(keep="last")` overwrite the existing row with the
new value. This is BY DESIGN — yfinance occasionally retroactively
revises the latest 1-2 days' adjusted close / volume / dividend
adjustment, and the overlap fetch catches those revisions.

Implication for forward observation: a TD entry's stored
``cum_ret`` is computed at the moment of observation. If yfinance
later revises the underlying bar, a SUBSEQUENT TD's backtest
re-run uses the revised bar, while the earlier TD's stored
``cum_ret`` keeps the OLD bar's value. The two TDs are then
internally inconsistent at the underlying-data level, even though
neither manifest entry is "wrong" relative to its observation
moment.

R-fwd-1 accepts this risk (option A — document only). Mitigation
options for R-fwd-2 / R-fwd-3:

- **Option C: bar-hash immutability guard** — record the
  per-symbol bar hash at first observation in the manifest; on
  subsequent fetch_data writes, detect mismatches and flag
  ``data_revision_event=true`` on the affected TD entries.
- (Option B = "make fetch_data not re-fetch the latest day"
  rejected by user 2026-04-26: fetch_data's overlap is the
  intentional yfinance-revision catch.)

R-fwd-2/3 SCOPE: include Option C, gated on having ≥5 real TD
entries to actually test against.

## 9. Out-of-scope (deferred)

- Multiple-window forward runs per candidate (one window per
  manifest is fine for MVP).
- Forward run on intraday bars (daily only for MVP; intraday
  forward can be a follow-up PRD).
- Cross-candidate aggregation reports (one candidate at a time).
- Auto-cron / scheduler integration (manual CLI for MVP).
- Resolving the M12 manual_review_required status BEFORE forward
  observation. The forward runner can run on a candidate with
  `narrative_permission: frozen` — the runner doesn't read M12
  status. The user resolves M12 separately if/when ready.

## 10. Acceptance to ship this PRD

User must explicitly authorize before any code lands:
1. Confirm forward observation is the next priority (per the
   audit synthesis they wrote in the M12 thread).
2. Confirm the 5-round split above is reasonable scope (each round
   ~1-3 hours).
3. Either invoke this as a ralph-loop or do it manually.

This PRD is a draft. No commit lands code until that authorization.

## 11. References

- PRD v3: `docs/prd/20260425-oos_validation_framework_codex_v3.md`
  §B (forward OOS) + §1.1, §1.3 (deployable evidence framing)
- Execution PRD: `docs/prd/20260425-oos_mvp_ralph_loop_execution.md`
- Closeout memo: `docs/memos/20260425-oos_mvp_close.md` §6
  (re-freeze status; this PRD is the fresh-round trigger)
- M12 audit memo: `docs/memos/20260425-m12_review_decision.md`
- Round-3 close (data-integrity context):
  `docs/memos/20260425-data_integrity_round3_close.md`
- R5 schema: `core/research/forward/manifest_schema.py`
- Existing runner code (to reuse): `core/research/robustness/runner.py`
