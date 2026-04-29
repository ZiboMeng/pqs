# PRD — Config / Universe Snapshot Hardening (forward manifest)

**Status**: Draft v1.0 — 2026-04-28
**Author**: zibo (drafted by Claude based on codex round-11 §B3 + codex round-12 P1 first step)
**Authority required**: user explicit (zibo) — implementation is **not** authorized by this PRD; this is design + acceptance-criteria draft only
**Lineage tag (when committed)**: `config-snapshot-hardening-2026-04-28`
**Parent context**:
- Codex round-11 §B3 — "给 forward manifest 增加 config/universe snapshot hardening PRD" (queue #5)
- Codex round-12 §P1 — "Recommended next step: First draft the scoped PRD for config/universe snapshot hardening in forward manifests; then, separately, true PIT metadata / fundamentals vendor requirements"
- Codex round-11 §Q4 (adversarial harness coverage gap #5) — "config drift vs data revision split: 现在 signal hash 依赖当前 universe/config 载入结果；这个很容易把'研究配置变化'伪装成'数据修订'"

---

## 1. Why this PRD

### 1.1 The exact failure shape

Today the v2.1.3 forward evidence pipeline reads `config/universe.yaml` (and a few other sources) **at observe time**, not at init time, when constructing the panel inputs to `compute_signal_input_hash`. The hash thus depends on **whatever the live yaml says today**, not on whatever the yaml said when the candidate was frozen.

Concretely:

1. Researcher freezes RCMv1 with `seed_pool` containing `[A, AAPL, ABT, …, BRK-B, …]`.
2. Forward runner inits the manifest, pinning `spec_hash` + `cost_assumptions.config_hash` + `data_integrity_snapshot.daily_store_rebuild_commit`.
3. At TD007, researcher edits `config/universe.yaml` to add `META` to seed_pool.
4. TD007's `forward observe` reads the NEW universe to construct panel + hash.
5. `signal_input_hash` differs from TD006's; revalidate sees a hash mismatch.
6. Revalidate **classifies this as a `DataRevisionEvent`** (the only event class for hash-mismatch in v2.1.3).
7. Investigator sees "data was revised" — looks for polygon revision — finds none — gets confused.

The truth was **config drift**, not data revision. The labeling was wrong.

### 1.2 Why this matters

Codex round-11 §B3:
> 重点不是立刻大改，而是先把 contract 讲清楚：universe hash / blacklist hash / benchmark plumbing hash / config bundle hash / data revision 和 config drift 如何分账。否则以后 revalidate 很容易把"研究配置变了"误记成"数据修订了"。

Codex round-12 §P1:
> a clean separation of config drift vs data revision

In real-money workflow this misclassification corrodes the same governance the v2.1.3 forward evidence layer was built to protect: a candidate's `requires_data_review` halt is a heavy-weight signal that should mean "the data tier moved", not "you edited a yaml".

### 1.3 Where this PRD sits in the roadmap

Per codex round-12 dependency analysis:

```
this PRD (F)  →  separate PRD: PIT metadata / fundamentals vendor (J)
```

`F` is the prerequisite scoping for `J`. `F` itself does NOT add any new data sources — it tightens the contract on what the forward layer already consumes. PIT vendor work (sector history / shares-outstanding / fundamentals) is its own larger PRD that this one must precede.

### 1.4 What this PRD is NOT

- **Not a new data tier**: no PIT vendor integration, no new bar source, no new fundamentals layer.
- **Not a recalibration of `bar_revision`**: the data-side hash already exists (`bar_revision = polygon_canonical_rebuild_<commit>`); this PRD adds **config-side** hashes that are orthogonal.
- **Not a redesign of `acceptance_pack._THRESHOLDS`**: that contract stays frozen (codex round-13 §"Decision 3").
- **Not a touch on the per-candidate `FrozenStrategySpec`**: the spec already holds its own snapshot. This PRD adds manifest-level snapshots that complement (not replace) the spec.
- **Not a forward observe refactor**: the existing observe path stays append-only.

---

## 2. Constraints

### 2.1 Hard constraints (cannot violate)

- **Append-only manifest contract**: existing `ForwardRunManifest` invariant. New fields added via `model_copy(update={…})`-style migration — never in-place mutation of `runs[]` history.
- **Schema migration boundary**: pre-existing manifests on disk (TD001 / TD002 / TD003) must continue to load + observe correctly. Missing config-snapshot fields default to a new "legacy_unhashed_configs" marker (analogous to v2.1.3's `legacy_unhashed_inputs` for bar-side).
- **No retroactive recomputation**: existing TD entries on disk are NOT recomputed with new config snapshot. They are marked as `legacy_unhashed_configs=True` and trusted as-is.
- **Long-only / SPY+QQQ benchmark / pricing semantics** all hold (CLAUDE.md "Invariant Constraints").
- **No new event class without contract clarity**: if `ConfigDriftEvent` is added, its escalation policy (when does config drift halt? when does it warn?) must be defined in this PRD, not deferred.

### 2.2 Reverse-validation requirement (PRD §3.2 of ralph-audit cycle)

Every fix reverse-validates. For implementation: regression tests must pin (a) edit `config/universe.yaml` mid-run + observe → emits `ConfigDriftEvent` (not `DataRevisionEvent`); (b) revert the edit + observe → no drift event; (c) edit a bar value at the same time → both events fire with correct labels.

### 2.3 No half-finished implementation

If implementation lands, all 5 in-scope config sources (per §4) snapshot together in the same change-set. No "snapshot universe first, leave benchmark for later".

---

## 3. State today

### 3.1 What ForwardRunManifest pins today

| Field | What it covers | Drift detection |
|---|---|---|
| `spec_hash` | Frozen `FrozenStrategySpec` artifact | YES — hash mismatch raises at runner.observe load |
| `cost_assumptions.config_hash` | `config/cost_model.yaml` SHA-256 | YES — `_verify_cost_hash_or_halt` halts on mismatch |
| `data_integrity_snapshot.daily_store_rebuild_commit` | git commit of last data tier rebuild | YES — passed as `bar_revision` into hashers |
| `runs[].bar_hash` (v2.1.3+) | Bar-data inputs for signal_input + execution_nav + benchmark scopes | YES — revalidate catches data revisions per scope |

### 3.2 What is NOT pinned today

| Source | Why it matters | Current behavior on edit |
|---|---|---|
| `config/universe.yaml` (seed_pool / sector_etfs / factor_etfs / cross_asset / blacklist) | Defines tradable + held-eligible universe; subset of which is the panel | Silent — observe uses current yaml; signal_input hash changes; revalidate misclassifies as DataRevision |
| `core/factors/factor_registry.py::PRODUCTION_FACTORS` | Defines what factor names MFS recognizes; promotion changes here change execution surface | Silent — observe uses current registry |
| `core/factors/factor_registry.py::RESEARCH_FACTORS` | If a candidate spec references a research factor that gets demoted, observe could break or silently degrade | Silent |
| `config/research_mask.yaml` | Research mask SoT (Phase E-post R5); affects which symbols enter held-eligible | Silent on edit |
| Benchmark plumbing (`benchmark` + `secondary_benchmark` columns of panel) | Already encoded in `benchmark_hash` for the bar VALUES, but the **definition** ("SPY = column 'SPY' in panel") is implicit | Silent if benchmark column source changes |
| `core/factors/factor_evaluator.py` IR cuts + acceptance thresholds (post-threshold-PRD) | Affects acceptance-tier decisions on revalidate | Will be covered by separate `AcceptanceThresholds` if that PRD ships |

---

## 4. In-scope: 5 config sources to snapshot

Each gets a hash field in the manifest, snapshotted at `init()` time, verified at `observe()` time.

### 4.1 S1 — Universe snapshot

**What**: SHA-256 of the **canonicalized** `config/universe.yaml` content (sorted keys, lists sorted within each section so that re-ordering doesn't false-trigger).

**Granularity**: single hash for the full yaml body. Codex round-11 §B3 listed "blacklist hash" separately, but having both `universe_hash` and `blacklist_hash` adds change-detection granularity without semantic value (any blacklist edit is an edit to universe.yaml). v1 ships single `universe_snapshot_hash`; if codex review wants split, fold in v1.1.

**Field**: `manifest.config_snapshot.universe_hash: str` (12+ char prefix of SHA-256).

### 4.2 S2 — Factor registry snapshot

**What**: SHA-256 of the canonicalized **set of (name, scope)** pairs:
- `PRODUCTION_FACTORS` (frozenset of 7 names)
- `RESEARCH_FACTORS` (frozenset of 64 names)
- `RESEARCH_TO_PRODUCTION_MAP` (dict of name → name)

**Why not the file source itself**: the file `core/factors/factor_registry.py` also contains computation code; its content hash would change on any code refactor (cosmetic comment edit, type hint update). What we actually care about is the **public contract** (which names exist in which registry), not the implementation. Hashing the canonicalized data is the right level.

**Field**: `manifest.config_snapshot.factor_registry_hash: str`.

### 4.3 S3 — Research mask snapshot

**What**: SHA-256 of `config/research_mask.yaml` body (canonicalized).

**Why**: Phase E-post R5 made `research_mask.yaml` the single source of truth for `{min_price, min_usd_volume, rolling_window_days}` mask construction. A mid-forward edit would silently change held-eligible at `forward observe` time.

**Field**: `manifest.config_snapshot.research_mask_hash: str`.

### 4.4 S4 — Risk config snapshot

**What**: SHA-256 of `config/risk.yaml`.

**Why**: holds `factor_registry.strict_mode`, `position_limits`, `kill_switch` 3-tier thresholds. Edits during forward window can change the **operational risk envelope** without any hash detecting it today.

**Field**: `manifest.config_snapshot.risk_config_hash: str`.

### 4.5 S5 — System config snapshot (optional but cheap)

**What**: SHA-256 of `config/system.yaml`.

**Why**: holds `initial_capital` + path settings. Capital edit mid-forward would silently change paper-engine NAV scaling. Cheap to add even if seldom edited.

**Field**: `manifest.config_snapshot.system_config_hash: str`.

### 4.6 What is OUT of scope here

| Source | Why out |
|---|---|
| `core/research/concentration/report.py` thresholds | PRD v3 §C derived; separate spec lineage |
| `acceptance_pack._THRESHOLDS` | codex round-13 §"Decision 3" frozen rule |
| Per-candidate `FrozenStrategySpec` | already hashed via `spec_hash` |
| `config/cost_model.yaml` | already hashed via `cost_assumptions.config_hash` |
| `data/daily/<sym>.parquet` content | covered by `bar_hash` (v2.1.3) |
| `config/backtest.yaml` | edited frequently for research; out of scope unless it actually drives forward path (today: mining gates only) |
| `config/regime.yaml` | regime detection runs at forward observe time but not currently part of forward decision pack; defer to separate concern |
| `config/reporting.yaml` | output formatting only |
| `config/notify.yaml` | notification only |
| `config/events.yaml` | reference data only |

If experience post-ship shows any of these matters, add in v1.1.

---

## 5. Proposed design

### 5.1 New manifest sub-model: `ConfigSnapshot`

```python
# core/research/forward/manifest_schema.py (additions)

class ConfigSnapshot(BaseModel):
    """Config-side hashes pinned at forward init time.

    Distinct from ``CostAssumptions`` (cost yaml) and
    ``DataIntegritySnapshot`` (data tier commit) because those existed
    pre-PRD-F. This new model captures the 5 config sources whose
    silent edits would otherwise misclassify as data revisions.

    Append-only; once an entry is on a manifest it does not mutate.
    Pre-PRD-F manifests have no ConfigSnapshot — they get treated as
    legacy_unhashed_configs=True at revalidate time.
    """

    schema_version: str = Field(default="1.0", min_length=1)
    universe_hash: str = Field(min_length=12)
    factor_registry_hash: str = Field(min_length=12)
    research_mask_hash: str = Field(min_length=12)
    risk_config_hash: str = Field(min_length=12)
    system_config_hash: str = Field(min_length=12)
    snapshot_at_utc: datetime
    sources: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Map of hash field name → source path. e.g. "
            "{'universe_hash': 'config/universe.yaml', "
            "'factor_registry_hash': 'core/factors/factor_registry.py'}. "
            "Recorded for human-readable audit."
        ),
    )


class ForwardRunManifest(BaseModel):
    # ... existing fields ...
    config_snapshot: Optional[ConfigSnapshot] = None  # NEW; Optional for legacy
```

### 5.2 Drift event class: `ConfigDriftEvent`

```python
# core/research/forward/manifest_schema.py (additions)

class ConfigDriftEvent(BaseModel):
    """Emitted when revalidate detects config-side drift between
    snapshot at init and current source.

    Distinct from DataRevisionEvent (which fires on bar-side drift).
    """

    detected_at_utc: datetime
    detected_by_run_label: str
    affected_run_id: Optional[str] = None  # which TD entry's recompute saw this
    drifted_sources: list[str] = Field(min_length=1)  # e.g. ["universe_hash", "research_mask_hash"]
    snapshot_hashes: dict[str, str]  # at init
    current_hashes: dict[str, str]   # at revalidate
    severity: Literal["warn", "halt"]


class ForwardRun(BaseModel):
    # ... existing fields including data_revision_event ...
    config_drift_event: Optional[ConfigDriftEvent] = None  # NEW
```

A single TD entry can carry **both** `data_revision_event` and `config_drift_event` if both kinds of drift are detected at the same observe call. They are NOT collapsed into a combined event — keeping them separate preserves diagnostic clarity per codex round-11 §B3 "data revision 和 config drift 如何分账".

### 5.3 Severity policy

When does `ConfigDriftEvent` halt vs warn?

| Drifted source | Severity | Rationale |
|---|---|---|
| `universe_hash` | **halt** | Universe edit changes which symbols are held-eligible; signal_input hash composition shifts; can silently invalidate cross-TD comparability |
| `factor_registry_hash` | **halt** | Promotion / demotion of factors changes execution surface; spec validity may be compromised |
| `risk_config_hash` | **halt** | Position limit / kill-switch threshold edit changes risk envelope; must explicitly re-authorize |
| `research_mask_hash` | **warn** | Mask edit affects future trades but does not retroactively change historical holdings; first observation post-edit can use new mask |
| `system_config_hash` | **warn** | Capital path edit is benign for forward research-mode evidence (NAV is relative); halt if you wanted strict capital lockdown |

**Halt path**: when any halt-severity drift fires, `manifest.current_status → ForwardRunStatus.requires_data_review` (re-uses the v2.1.3 halt machinery; "data review" name stays even though the drift is config-side, because the operational handling is identical: pause, investigate, decide via `decide()`).

**Warn path**: event recorded in TD entry; observe continues; running daily ritual logs WARNING.

### 5.4 Revalidate integration

```python
# core/research/forward/revalidate.py (sketch)

def revalidate_manifest(
    manifest: ForwardRunManifest,
    *,
    spec, universe, panel,
    benchmark_symbols,
    detected_by_run_label,
    bar_revision: str = DEFAULT_BAR_REVISION,
    # NEW: optional config_snapshot recompute hook
    current_config_snapshot: Optional[ConfigSnapshot] = None,
) -> RevalidationSummary:
    # ... existing bar-side revalidate paths (Blocker-2 fix etc.) ...

    # NEW: config-side drift check
    if manifest.config_snapshot is not None and current_config_snapshot is not None:
        drifted = [
            f for f in ("universe_hash", "factor_registry_hash",
                        "research_mask_hash", "risk_config_hash",
                        "system_config_hash")
            if getattr(current_config_snapshot, f) != getattr(manifest.config_snapshot, f)
        ]
        if drifted:
            severity = "halt" if any(
                f in {"universe_hash", "factor_registry_hash", "risk_config_hash"}
                for f in drifted
            ) else "warn"
            event = ConfigDriftEvent(
                detected_at_utc=now_utc(),
                detected_by_run_label=detected_by_run_label,
                drifted_sources=drifted,
                snapshot_hashes={f: getattr(manifest.config_snapshot, f) for f in drifted},
                current_hashes={f: getattr(current_config_snapshot, f) for f in drifted},
                severity=severity,
            )
            # attach to the latest run; halt if severity=='halt'
```

### 5.5 Init integration

```python
# core/research/forward/runner.py::init (sketch, additions)

def init(...):
    # ... existing logic computes spec_hash, cost_config_hash etc. ...
    config_snapshot = _build_config_snapshot()  # NEW helper
    manifest = ForwardRunManifest(
        # ... existing fields ...
        config_snapshot=config_snapshot,
    )
    save_manifest(manifest, path)


def _build_config_snapshot() -> ConfigSnapshot:
    return ConfigSnapshot(
        universe_hash=_canonical_yaml_sha("config/universe.yaml"),
        factor_registry_hash=_factor_registry_contract_sha(),
        research_mask_hash=_canonical_yaml_sha("config/research_mask.yaml"),
        risk_config_hash=_canonical_yaml_sha("config/risk.yaml"),
        system_config_hash=_canonical_yaml_sha("config/system.yaml"),
        snapshot_at_utc=datetime.now(timezone.utc),
        sources={
            "universe_hash": "config/universe.yaml",
            "factor_registry_hash": "core/factors/factor_registry.py::PRODUCTION+RESEARCH+MAP",
            "research_mask_hash": "config/research_mask.yaml",
            "risk_config_hash": "config/risk.yaml",
            "system_config_hash": "config/system.yaml",
        },
    )
```

`_canonical_yaml_sha` parses + sorts keys + sorts list values within sections + dumps to canonical bytes + SHA-256. `_factor_registry_contract_sha` reads the runtime `frozenset(PRODUCTION_FACTORS) | frozenset(RESEARCH_FACTORS)` plus `RESEARCH_TO_PRODUCTION_MAP` items, sorts them, and hashes — implementation-stable against code refactors.

### 5.6 Lazy migration boundary

Pre-PRD-F manifests have `config_snapshot=None`. At observe time:

- If `manifest.config_snapshot is None`: skip config drift check (treat as legacy); log INFO once per run id about migration.
- The next time the manifest is **rebuilt** (e.g. via `init` of a fresh candidate), it gets a config_snapshot.
- Existing manifests can OPT IN to migration via a new utility `dev/scripts/forward/backfill_config_snapshot.py` (one-shot CLI) that snapshots the *current* config and stamps it on the manifest with `migration_note="backfilled_2026-04-NN_assumed_unchanged_since_init"`. **Default is no-backfill**; user must explicitly run backfill if they want drift detection on legacy manifests.

This mirrors the v2.1.3 lazy-migration boundary pattern exactly (TD001 stays as-is with `legacy_unhashed_inputs=True`).

---

## 6. Acceptance criteria

A change-set passes this PRD if and only if all of the following hold:

1. **`ConfigSnapshot` model exists** at `core/research/forward/manifest_schema.py` with the 5 hash fields + `snapshot_at_utc` + `sources` per §5.1.
2. **`ConfigDriftEvent` model exists** with the structure per §5.2.
3. **`ForwardRunManifest.config_snapshot` Optional field** added; existing manifests (TD001/TD002/TD003) load correctly with the field absent.
4. **`ForwardRun.config_drift_event` Optional field** added.
5. **`init()` populates `config_snapshot`** for new manifests via `_build_config_snapshot()` per §5.5.
6. **`revalidate_manifest` checks config drift** when both `manifest.config_snapshot` and `current_config_snapshot` are non-None (per §5.4).
7. **Severity policy** per §5.3 enforced; halt-severity drift flips `manifest.current_status → requires_data_review`.
8. **Lazy migration boundary**: pre-PRD-F manifests with `config_snapshot=None` skip config drift check + log INFO once per run; do NOT halt or warn on absence.
9. **Backfill utility** at `dev/scripts/forward/backfill_config_snapshot.py` lets users opt-in stamp current snapshot onto a legacy manifest.
10. **Regression tests**:
    - `test_init_populates_config_snapshot`
    - `test_observe_emits_config_drift_event_on_universe_edit` (reverse-validation: revert edit → no event)
    - `test_observe_emits_both_events_when_universe_edit_plus_bar_revision`
    - `test_legacy_manifest_without_config_snapshot_still_observes`
    - `test_research_mask_edit_warns_not_halts`
    - `test_universe_edit_halts`
11. **Full pytest suite green** including the 6 new tests.
12. **Reverse-validation evidence in commit message**: revert the new drift detection; verify the regression test from §10.b would FAIL on pre-fix code (proving the test catches what it claims to catch).
13. **Docs updates**: README §1.4 (or a new pointer); CLAUDE.md "Forward OOS active workstream" section; INDEX.md PRD entry.

---

## 7. Implementation steps (when authorized)

5 commits, each its own reversible step.

### 7.1 Step 1 — schema additions only (no live wiring)

- Add `ConfigSnapshot` + `ConfigDriftEvent` pydantic models.
- Add `config_snapshot: Optional[ConfigSnapshot]` to `ForwardRunManifest`.
- Add `config_drift_event: Optional[ConfigDriftEvent]` to `ForwardRun`.
- Verify existing manifests still load (load-round-trip test on rcm_v1 + cand2).

### 7.2 Step 2 — `_build_config_snapshot` helper + init wiring

- Add `_canonical_yaml_sha` + `_factor_registry_contract_sha` helpers.
- Wire `init()` to populate `config_snapshot`.
- Test `test_init_populates_config_snapshot`.

### 7.3 Step 3 — revalidate config-drift detection

- Add the diff loop per §5.4.
- Add severity policy per §5.3.
- Tests for the 3 drift cases (warn / halt / both kinds).

### 7.4 Step 4 — backfill utility

- `dev/scripts/forward/backfill_config_snapshot.py` CLI.
- Tests for backfill correctness + idempotency.

### 7.5 Step 5 — docs

- README + CLAUDE.md + INDEX updates.
- Note in CLAUDE.md "Forward OOS active workstream" that observation now distinguishes drift classes.

---

## 8. Risk

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Halt-severity drift on benign refactor (e.g. cosmetic universe.yaml comment edit) | medium | low (false halt) | `_canonical_yaml_sha` strips comments + normalizes whitespace; only meaningful content drives the hash |
| Factor-registry hash false-trigger on type-hint refactor | medium | low | hash the **contract** (set of names + map) not file bytes; refactors that don't change contract don't change hash |
| Backfill silently overwrites real drift | low | medium | backfill stamps `migration_note="backfilled_…_assumed_unchanged"` so drift detection knows the snapshot is post-init not at-init |
| Lazy migration leaves legacy manifests permanently unprotected | low | medium | INFO log on every observe of legacy manifest reminds; documentation steers users to backfill once |
| Researcher edits config to fix typo + mid-run | medium | medium (false halt) | typo edits should be done before init; mid-run edits trigger halt by design and require explicit `decide()` to clear |
| Two parallel forward runs see the same yaml edit at different times | low | low (false-halt one of them) | each manifest has its own snapshot; behavior is symmetrical |

---

## 9. Out of scope (explicit)

- **PIT data layer** (sector history, shares-outstanding, fundamentals): codex round-12 P1 second-step PRD; this PRD is the prerequisite scoping.
- **Live broker integration**: PRD M17.
- **`acceptance_pack._THRESHOLDS` versioning**: codex round-13 §"Decision 3" rule applies independently.
- **Config edits during paper-only mode (no forward manifest)**: paper engine has its own contract; this PRD is forward-manifest-specific.
- **Universe expansion as a first-class operation**: codex round-12 P3 — separate PRD when forward evidence is encouraging.
- **Capacity / liquidity realism**: codex round-12 P4 — staged after allocator.

---

## 10. Open questions (for codex / user)

### Q1 — Should `universe_hash` be split into `universe_hash` + `blacklist_hash`?

Codex round-11 §B3 explicitly listed both. v1 design ships single `universe_hash` for change-detection simplicity; any blacklist edit IS a `universe.yaml` edit. Split adds granularity without semantic value. Codex / user input welcome.

### Q2 — Should `risk_config_hash` be split per subsection (kill_switch / position_limits / factor_registry mode)?

Same trade-off as Q1. v1 ships single `risk_config_hash`. If any subsection sees frequent edits and warrants finer-grained event labeling, split in v1.1.

### Q3 — Severity policy on `system_config_hash`?

PRD §5.3 currently picks `warn` (capital path edit is benign for research-mode evidence). Counter-argument: capital edits should be deliberate and pinned for the duration of forward window. Codex / user input welcome.

### Q4 — Is `config/regime.yaml` actually safe to omit?

PRD currently omits regime config because regime detection happens *outside* the candidate's signal/execution decision (it feeds `MultiFactorStrategy(regime_scale=...)` whose regime_series is computed from price data, not from yaml). But if regime threshold yaml drives the regime series construction, that should be in scope. Need codex / user to confirm regime detection's exact code path before finalizing.

### Q5 — Do we want a `config_drift_event_streak` style throttle?

Edge case: researcher does a refactor sweep editing 5 yamls in 30 minutes; each `forward observe` during that window emits 5 separate halt events. Single observe per day naturally throttles this, but if observation cadence intensifies later (multi-intraday), we may want a per-event-class debounce. Out of scope for v1; flagging as a future v2 concern.

---

## 11. Sequencing (when this lands)

Per codex round-12 dependency analysis:

```
F (this PRD) → J (PIT vendor PRD)
```

This PRD is **independent** of the threshold-unification PRD and the fleet allocator PRD. It can be implemented in parallel with either.

- **Now**: PRD draft committed; pushed to `review/claude-collab` for codex round-14 review (alongside fleet allocator PRD).
- **After codex sign-off**: implementation in 5-step sequence per §7.
- **Before implementation**: pause for user explicit-go signal (CLAUDE.md "MUST PAUSE: changing core constraints" — this PRD adds a new event class + a new halt path; structural change in evaluation surface).

---

## 12. Pointer summary

- **Codex round-11 §B3** (PRD origin): `docs/audit/20260428-codex_round_11_review.md`
- **Codex round-12 §P1** (round-12 elevation + sequencing): `docs/audit/20260428-codex_round_12_priority_status.md`
- **Forward evidence v2.1.3 PRD** (sister artifact): `docs/prd/20260427-forward_evidence_hardening_prd.md`
- **Forward observe evidence note** (live state reference): `docs/memos/20260428-forward_observe_first_real_after_v2_1_3.md`
- **R6 audit memo** (S25 + adversarial baseline): `docs/audit/20260428-ralph_audit_round_06.md`
- **Codex round-11 Q4 §5** (the original "config drift vs data revision" gap call-out): same round-11 doc

End of PRD draft.
