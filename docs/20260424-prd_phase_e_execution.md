# PRD: Phase E Execution (Ralph-Loop)

> **This is the ralph-loop execution PRD** for Phase E Research Governance +
> Paper Transition.
>
> **Parent (policy) PRDs** — read first for context:
> - `docs/20260424-prd_phase_e_governance_and_paper.md` — Phase E charter
>   (the "what" and "why")
> - `docs/20260424-prd_layered_quant_architecture.md` — lifecycle S0-S5,
>   3-layer architecture
> - `docs/20260424-prd_research_to_paper_promote_standard.md` — Promote
>   Input Package + criteria
> - `docs/20260424-prd_research_composite_miner_v1.md` — RCMv1 scope (the
>   feeder for candidates)
>
> **This PRD's role**: turn the Phase E charter into a concrete per-round
> execution plan that a ralph-loop can follow. The "how" and "when".

## 0. TL;DR

Phase E has three sub-phases (E-0 / E-1 / E-2) and a buffer. Total ralph
ceiling: **14 rounds**. Completion promise: `PHASEEDONE`. Lineage tag:
`phase-e-governance-2026-04-24`. Forbidden: modifying `PRODUCTION_FACTORS`,
`config/universe.yaml`, `config/production_strategy.yaml`, auto-promote to
production, broker/live-feed integration, daemon/scheduler, new data
layer.

## 1. Absolute Scope Boundaries

### 1.1 Allowed autonomously

- New Python modules under `core/research/` and `core/paper/` (both new)
- New scripts under `scripts/` for freeze / research_promote / revoke / run_paper_candidate
- New tests under `tests/unit/research/` and `tests/integration/`
- New artifact directory `data/research_candidates/` (convention)
- Schema additions to SQLite (but NOT schema migrations on existing
  production tables — see §1.2)
- Extending `core/mining/rcm_archive.py` with read-only helpers
- Docstring / README / CLAUDE.md edits documenting Phase E
- Per-round 11-part Chinese log in `docs/20260420-ralph_loop_log.md`

### 1.2 MUST pause for user

- Any change to `PRODUCTION_FACTORS`, `config/universe.yaml`,
  `config/production_strategy.yaml`
- Any write path that reaches `scripts/promote_strategy.py` or
  `core/mining/archive.py` (production)
- Any migration of the existing `data/mining/archive.db` or
  `data/mining/rcm_archive.db` schemas (new tables OK, altering existing
  columns NOT OK)
- Any dependency addition to `pyproject.toml` / `requirements.txt`
- Any broker / live feed / scheduler / daemon integration
- Any deletion of a public function referenced elsewhere

### 1.3 Forbidden entirely (do not do even with permission this phase)

- Real production order execution
- Auto-promote candidates to S3/S4
- Pyarrow removal (scope is decouple, not remove)
- Full acceptance_pack v3 mega-merge (per PRD 1 §2.4, keep separate)

## 2. Sub-Phase Breakdown

### Phase E-0: Governance Taxonomy + Foundation (Rounds 1-3)

**Parent**: governance PRD §7.E-0.

**Deliverables**:

#### E0-R1: Candidate registry + state machine
- New SQLite table `research_candidates` (separate DB file
  `data/research_candidates/registry.db` OR new table in rcm_archive.db
  — prefer separate DB for clean governance boundary)
- Columns: `candidate_id`, `source_trial_id`, `source_lineage_tag`,
  `status`, `frozen_spec_path`, `created_at`, `promoted_at`, `revoked_at`,
  `revoke_reason`, `revoke_memo_path`, `decision_memo_path`, `updated_at`
- Status values: `S0_research_prototype`, `S1_research_candidate`,
  `S2_paper_candidate`, `S5_deprecated`
- S3 / S4 in schema enum but rejected by business logic this phase
- Module: `core/research/candidate_registry.py` (CRUD + state transitions)
- Tests: ≥ 8 (create, read, update-status, reject-invalid-transition,
  concurrent-access-safety, parent-dir-auto-create, round-trip via
  JSON serialization, status-enum-validation)

#### E0-R2: Pyarrow decouple
- `core/data/__init__.py`: drop eager imports that transit to pyarrow
- `core/data/market_data_store.py`: wrap pyarrow imports lazily inside
  the methods that actually read/write parquet
- `scripts/run_paper.py`: remove top-level `from core.data.market_data_store
  import MarketDataStore` in favor of lazy factory or DI
- Acceptance: `python -c "from core.paper_trading.paper_trading_engine
  import PaperTradingEngine"` does NOT touch pyarrow (check with
  `sys.modules` after import)
- Acceptance: run at least one paper-layer unit test that does NOT
  initialize pyarrow (e.g. kill-switch config test)
- Tests: ≥ 2 (no-pyarrow-in-sys-modules + lazy-load-on-first-parquet-call)

#### E0-R3: Revoke workflow + RCMv1 migration
- New script: `scripts/revoke_candidate.py`
  - Args: `--candidate-id` (required), `--reason` (required, choose from
    enum: `leakage_found`, `reproducibility_failed`, `benchmark_misaligned`,
    `candidate_superseded`, `spec_unreproducible`, `other`),
    `--memo-path` (optional but recommended)
  - Behavior: updates status to S5 (or S0 if reason=`reproducibility_failed`),
    writes `revoked_at` + `revoke_reason` + `revoke_memo_path`,
    creates audit memo file if none provided
- Migration: ingest `docs/20260424-rcm_v1_s1_candidate_memo.md` as
  first real S1 candidate
  - candidate_id = `rcm_v1_defensive_composite_01` (from memo §1)
  - source_trial_id = `f24aefecc91a`
  - source_lineage_tag = `post-2026-04-24-rcm-v1-lag1`
  - status = `S1_research_candidate`
  - decision_memo_path = the memo itself
  - frozen_spec_path = `data/research_candidates/rcm_v1_defensive_composite_01.yaml`
  - The frozen YAML extracted verbatim from memo §2
- Tests: ≥ 4 (revoke-changes-status, revoke-writes-reason, migration-idempotent,
  invalid-reason-rejected)

**E-0 acceptance** (all four must be true to move to E-1):
- 12+ new unit tests pass
- RCMv1 S1 candidate is queryable from registry and has valid frozen_spec_path
- `python -c "from core.paper_trading.paper_trading_engine import
  PaperTradingEngine"` loads without pyarrow
- `scripts/revoke_candidate.py --help` runs clean, can revoke a dummy
  candidate and roundtrip the audit memo

### Phase E-1: Promote Standard Code-ification (Rounds 4-7)

**Parent**: governance PRD §7.E-1.

**Deliverables**:

#### E1-R4: Frozen spec schema + Promote Input Package
- New module: `core/research/frozen_spec.py`
  - Dataclass `FrozenStrategySpec` with **8 mandatory fields** per
    auditor minimum (per PRD 1 §7.1 Promote Input Package):
    `candidate_id`, `strategy_version`, `source_trial_id`, `feature_set`,
    `benchmark_relative_summary`, `oos_holdout_summary`,
    `robustness_summary`, `decision_memo` (path or inline text)
  - Optional fields: weights, transforms, mask_rules, rebalance_rules,
    weighting_rules, risk_overlay, cost_model_version,
    alternative_weighting_variant (matches RCMv1 memo §2 verbatim)
  - `to_yaml()` / `from_yaml()` round-trip
- Tests: ≥ 6 (mandatory-field-missing-rejected, roundtrip-yaml,
  version-format-validation, feature-set-empty-rejected, alternative-weight-optional, path-resolution)

#### E1-R5: `scripts/freeze_research_candidate.py`
- Args: `--trial-id` OR (`--lineage-tag` + `--top-k-index`), `--candidate-id`
  (required), `--archive-db` (default rcm_archive)
- Reads source trial, builds `FrozenStrategySpec`, writes YAML to
  `data/research_candidates/<candidate_id>.yaml`, inserts row in
  registry with status `S0_research_prototype`
- Refuses if candidate_id already exists (use revoke-then-re-freeze to replace)
- Tests: ≥ 4 (freeze-from-trial, freeze-fails-on-duplicate-id,
  freeze-writes-frozen-spec, freeze-inserts-registry-row)

#### E1-R6: `scripts/research_promote.py`
- Args: `--candidate-id` (required), `--acceptance-json` (optional —
  defaults to latest acceptance run for this candidate),
  `--decision-memo-path` (required)
- Validates: candidate exists at S0, acceptance PASS, hard-block check,
  decision memo exists
- Transitions to `S1_research_candidate`, writes `promoted_at` +
  `decision_memo_path`
- Does NOT touch `config/production_strategy.yaml` (enforced by test)
- Tests: ≥ 5 (promote-happy-path, promote-rejects-bad-acceptance,
  promote-rejects-missing-memo, promote-does-not-touch-production-config,
  promote-idempotent-on-already-S1)

#### E1-R7: Shared acceptance evaluator + dual wrappers
- New module: `core/research/acceptance_helpers.py` — shared pure
  functions: `walkforward_ic`, `regime_stratified_ic`, `turnover_summary`,
  `benchmark_relative_summary`
- Refactor `scripts/acceptance_research_composite.py` to call the shared
  helpers (keep existing CLI interface)
- `core/mining/acceptance_pack.py` stays UNCHANGED this phase (it's
  production-path, separate layer) — optional: add a TODO comment
  pointing at the shared helpers for future refactor
- Tests: ≥ 4 on shared helpers; integration test that verifies
  `acceptance_research_composite.py` still produces same output as
  before refactor
- Full existing test suite (1386 pass) MUST still pass

**E-1 acceptance** (all must be true):
- RCMv1 candidate completes freeze → promote → (remains S1) round-trip
- `FrozenStrategySpec` with 8 mandatory fields validated
- `scripts/research_promote.py` verifiably cannot write to
  `config/production_strategy.yaml` (integration test)
- Acceptance helpers extracted and both research + production acceptance
  paths still work
- No drop in existing test pass count

### Phase E-2: Minimal Paper Layer V1 (Rounds 8-11)

**Parent**: governance PRD §7.E-2.

**Deliverables**:

#### E2-R8: `scripts/run_paper_candidate.py` scaffold
- Args: `--candidate-id` (required), `--start-date`, `--end-date`,
  `--out-dir` (default `data/paper_runs/<candidate_id>/<date>/`)
- Loads frozen spec, builds signals via the spec's feature_set + weights,
  runs via existing `PaperTradingEngine` (or adapter if needed)
- Writes: `signals_<YYYYMMDD>.csv`, `target_portfolio_<YYYYMMDD>.csv`,
  `fills_<YYYYMMDD>.csv`, `pnl_daily.csv`
- Does NOT read `config/production_strategy.yaml` (enforced by test
  + CI: grep)
- Tests: ≥ 4 (runs-on-frozen-spec, does-not-touch-production-config,
  writes-artifacts, refuses-if-candidate-not-S1-or-S2)

#### E2-R9: Paper artifacts schema
- Extend paper artifacts to include:
  - `live_like_pnl.csv` — daily NAV series
  - `benchmark_relative_paper.csv` — per-day excess vs SPY + QQQ
  - `turnover_log.csv` — daily turnover (long-only, absolute change in weights / 2)
- Document schema in `docs/20260424-paper_artifact_schema.md`
- Tests: ≥ 3

#### E2-R10: Minimal drift report
- New script: `scripts/paper_drift_report.py`
- Computes: paper NAV vs same-period backtest replay (using the spec's
  frozen feature_set / weights on historical data over the paper window)
- Produces: `drift_report_<YYYYMMDD>.md` with:
  - NAV delta (bps)
  - Position count delta per day (how many symbols held by paper vs BT)
  - Worst drift day + its driver (max absolute delta)
  - Tolerance: **informational only**: "> 50 bps mean drift or > 2% any
    single day triggers manual review" (NO auto-action this phase)
- Default window: **30 trading days** (or shorter if paper has < 30 days
  of runs)
- Tests: ≥ 3

#### E2-R11: Paper promote / revoke / placeholder
- Extend `core/research/candidate_registry.py` with `S1 → S2` (paper_enter)
  and `S2 → S5` (paper_revoke) transitions
- New script: `scripts/paper_enter.py` — S1 → S2 (requires: frozen spec
  exists, acceptance PASS, paper artifacts schema validated on at least
  1 dry-run date)
- Update `scripts/revoke_candidate.py` to allow S2 → S5 (already works
  if E0-R3 generic, but add specific test)
- `S2 → S3` explicitly rejected (raises `NotImplementedError("S3
  production transition out of Phase E scope")`)
- Tests: ≥ 4

**E-2 acceptance** (all must be true):
- RCMv1 candidate (or a fresh one) completes S1 → S2 via `paper_enter.py`
- `run_paper_candidate.py` writes artifacts for at least 5 consecutive
  business days on the RCMv1 candidate
- `paper_drift_report.py` produces a valid markdown report
- No `run_paper_candidate.py` call path reaches
  `config/production_strategy.yaml`
- `S2 → S3` transition raises `NotImplementedError`

### Phase E Buffer (Rounds 12-14)

Rounds 12-14 are buffer for:
- Bug fixes uncovered in E-0/E-1/E-2
- README + CLAUDE.md sync
- Final synthesis doc `docs/20260424-phase_e_final_synthesis.md`
- Baseline snapshot rebuild
- Emit `PHASEEDONE`

If no buffer rounds needed, emit `PHASEEDONE` earlier.

## 3. Halt Conditions

Any one triggers halt:

1. **14 rounds ceiling**
2. **Test regression > 10 tests** (baseline: 1386 pass)
3. **Core import break** (`python -c "from core.mining.research_miner
   import ResearchMiner; from core.paper_trading.paper_trading_engine
   import PaperTradingEngine"` must pass at any round end)
4. **Disk free < 10 GB**
5. **Migration blocker**: a finding requires modifying the existing
   `rcm_archive.db` schema (ALTER TABLE existing columns) — STOP and
   surface to user
6. **Write-to-production detected**: any round's changes grep-trigger
   `config/production_strategy.yaml` write path — HALT immediately
7. **User intervention requested** for any §1.2 pause-for-user action

## 4. Per-Round Deliverable Format

Each round produces:

1. Code changes (per §2 sub-phase scope)
2. Tests added (per-round minimum specified in §2)
3. Full pytest green
4. 11-part Chinese log in `docs/20260420-ralph_loop_log.md` under
   `## R-phase-e-round-NN`
5. Git commit with message: `phase-e R<N>: <sub-phase>: <short summary>`

## 5. Round-by-Round Summary Table

| Round | Sub-phase | Focus | Critical deliverable |
|---|---|---|---|
| 1 | E-0 | Candidate registry + state machine | `core/research/candidate_registry.py` + registry.db |
| 2 | E-0 | Pyarrow decouple | Lazy imports in core/data + run_paper |
| 3 | E-0 | Revoke workflow + RCMv1 migration | `scripts/revoke_candidate.py` + first real S1 record |
| 4 | E-1 | FrozenStrategySpec schema | `core/research/frozen_spec.py` + 8-field validation |
| 5 | E-1 | Freeze script | `scripts/freeze_research_candidate.py` |
| 6 | E-1 | Research promote script | `scripts/research_promote.py` (NO production write) |
| 7 | E-1 | Shared acceptance helpers | `core/research/acceptance_helpers.py` |
| 8 | E-2 | Paper candidate runner | `scripts/run_paper_candidate.py` |
| 9 | E-2 | Paper artifact schema | `docs/20260424-paper_artifact_schema.md` |
| 10 | E-2 | Drift report | `scripts/paper_drift_report.py` |
| 11 | E-2 | Paper enter + S2→S5 revoke | `scripts/paper_enter.py` + S3 NotImplementedError |
| 12-14 | Buffer | Bug fix / README / synthesis / emit promise | `docs/20260424-phase_e_final_synthesis.md` |

## 6. Completion Promise

`PHASEEDONE` — emitted only when ALL of the following are simultaneously
true:

- Rounds 1-11 deliverables all shipped (or explicit "done early" in log)
- Full test suite passes (1386 + new tests, 0 regressions)
- RCMv1 candidate has gone S0 → S1 → S2 through the new tooling
- `paper_drift_report.py` has produced at least 1 real report on the
  RCMv1 candidate with ≥ 5 days of paper runs
- README.md + CLAUDE.md updated to reflect Phase E completion
- `data/baseline/latest.json` regenerated
- Final synthesis doc `docs/20260424-phase_e_final_synthesis.md` exists
- No `config/production_strategy.yaml` write occurred throughout

## 7. What Phase E Explicitly Does NOT Do

Per governance PRD §8.3. Do NOT do these even if tempted:

- Production promote (S2 → S3 → S4)
- Broker adapter / live feed / order execution
- Scheduler / cron / airflow / daemon
- Monitoring / alerting automation
- New data vendor integration
- New acceptance_pack v3 mega-merge
- RCMv1 default auto-freezing (trials stay trials unless explicitly frozen)
- Any migration of existing `archive.db` production schemas

## 8. One-Sentence Summary

**14-round ralph-loop execution to turn the governance policy PRDs into
code: candidate registry + freeze/promote/revoke tooling + minimal
frozen-candidate paper runner — strictly scoped below production layer.**
