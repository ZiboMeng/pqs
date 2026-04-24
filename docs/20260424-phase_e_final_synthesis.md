# Phase E Final Synthesis

> **Period**: 2026-04-24 (single day, 13 rounds R1-R13 executed via
> ralph-loop; R14 remaining for promise emission)
>
> **Scope**: Research Governance + Paper Transition layer per
> `docs/20260424-prd_phase_e_execution.md`
>
> **Status**: Rounds 1-12 complete. Full test suite green. RCMv1 real
> candidate traversed S0→S1→S2 via the new tooling. This synthesis doc
> is itself R13 (the last required PHASEEDONE precondition).

## 1. Goal recap

Per the Phase E charter (`docs/20260424-prd_phase_e_governance_and_paper.md`),
the system had a real structural gap identified in the RCMv1 R15
leakage incident: research candidates could look "promote-worthy" but
there was no formal **freeze → paper → production** pipeline to catch
post-acceptance discoveries like structural leakage. If RCMv1 had been
auto-promoted, `config/production_strategy.yaml` would now hold a
defensive composite built on a contaminated IC signal.

Phase E's goal was **not** to build a full production trading system.
It was to establish the governance primitives — candidate registry,
freeze/promote/revoke tooling, paper runner, drift report — so that
future candidates can be validated without silently writing to
production config.

## 2. Deliverables inventory (R1-R11)

### 2.1 Code

| Path | LOC | Round | Purpose |
|------|-----|-------|---------|
| `core/research/__init__.py` | 14 | R1 | package marker + overview |
| `core/research/candidate_registry.py` | 345 | R1 | SQLite state machine S0/S1/S2/S5; S3/S4 design-only rejected |
| `core/research/frozen_spec.py` | 370 | R4 | `FrozenStrategySpec` 8 mandatory fields + YAML round-trip |
| `core/research/acceptance_helpers.py` | 240 | R7 | shared `summarize_ic`/`walkforward_ic`/`regime_stratified_ic`/`turnover_summary` |
| `core/research/paper_artifacts.py` | 180 | R9 | writers for `live_like_pnl` / `benchmark_relative_paper` / `turnover_log` |
| `core/research/drift_metrics.py` | 160 | R10 | `compute_nav_drift` / `compute_position_drift` / `DriftThresholds` |
| `scripts/revoke_candidate.py` | 141 | R3 | S0-S5 revoke CLI with 6-reason enum |
| `scripts/migrate_rcm_v1_memo_to_registry.py` | 150 | R3 | one-time RCMv1 memo → registry S1 record |
| `scripts/freeze_research_candidate.py` | 295 | R5 | trial → S0 row + frozen YAML |
| `scripts/research_promote.py` | 260 | R6 | S0 → S1 gate (acceptance + memo + stub check); hard invariant tested |
| `scripts/run_paper_candidate.py` | 295 | R8 | MVP paper runner; reads frozen spec, never production config |
| `scripts/paper_drift_report.py` | 310 | R10 | paper artifacts vs replay; informational threshold only |
| `scripts/paper_enter.py` | 175 | R11 | S1 → S2 gate; S3 → `NotImplementedError` |
| `scripts/start_phase_e_loop.sh` | ~80 | pre-R1 | ralph-loop launcher |

**Total new code**: ~3,215 LOC across 14 new files.

### 2.2 Tests

| Path | Count | Round |
|------|-------|-------|
| `tests/unit/research/test_candidate_registry.py` | 26 | R1 |
| `tests/unit/research/test_revoke_and_migration.py` | 12 | R3 |
| `tests/unit/data/test_pyarrow_decouple.py` | 3 | R2 |
| `tests/unit/research/test_frozen_spec.py` | 19 | R4 |
| `tests/unit/research/test_freeze_cli.py` | 9 | R5 |
| `tests/unit/research/test_research_promote_cli.py` | 12 | R6 |
| `tests/unit/research/test_acceptance_helpers.py` | 26 | R7 |
| `tests/unit/research/test_run_paper_candidate.py` | 7 | R8 |
| `tests/unit/research/test_paper_artifacts.py` | 10 | R9 |
| `tests/unit/research/test_drift_metrics.py` | 15 | R10 |
| `tests/unit/research/test_paper_enter.py` | 11 | R11 |

**Total new tests**: 150 (1386 pre-Phase-E → 1536 post-R11).

Full suite (R12 final regression): **1536 passed / 1 skipped / 1 xfailed** in 149s. Zero regressions.

### 2.3 Documentation

| Path | Role |
|------|------|
| `docs/20260424-prd_phase_e_governance_and_paper.md` | Phase E charter (what/why) |
| `docs/20260424-prd_phase_e_execution.md` | Execution plan (how/when, 14-round schedule) |
| `docs/20260424-prd_layered_quant_architecture.md` | Upstream: long-term architecture |
| `docs/20260424-prd_research_to_paper_promote_standard.md` | Upstream: promote rules |
| `docs/20260424-paper_artifact_schema.md` | R9 paper artifact contract |
| `docs/20260424-phase_e_final_synthesis.md` | This file (R13 final) |
| `docs/20260420-ralph_loop_log.md` `R-phase-e-round-01` through `R-phase-e-round-13` | 11-part per-round Chinese reports |

### 2.4 Data state

| Path | Status |
|------|--------|
| `data/research_candidates/registry.db` | SQLite, 1 candidate: `rcm_v1_defensive_composite_01` at `S2_paper_candidate` |
| `data/research_candidates/rcm_v1_defensive_composite_01.yaml` | Frozen spec (committed) |
| `data/paper_runs/rcm_v1_defensive_composite_01/20260424T002411Z/` | 8 artifacts + 2 drift outputs (gitignored, per-run regenerable) |
| `data/baseline/latest.json` | Regenerated R12; 1538 tests collected, 7 PROD / 64 RESEARCH factors |

## 3. The RCMv1 candidate journey

The only candidate in the registry, and the first to traverse the full
governance pipeline.

```
rcm_archive.rcm_trials[trial_id=f24aefecc91a]
  │   (source: RCMv1 R17 TPE-converged 4-feature composite,
  │    post-R15 leakage fix, lineage=post-2026-04-24-rcm-v1-lag1)
  │
  ▼ scripts/migrate_rcm_v1_memo_to_registry.py (R3 one-time migration)
  │
registry[rcm_v1_defensive_composite_01]
  status = S1_research_candidate     # from pre-existing S1 memo
  frozen_spec_path = data/research_candidates/rcm_v1_defensive_composite_01.yaml
  decision_memo_path = docs/20260424-rcm_v1_s1_candidate_memo.md
  │
  ▼ scripts/run_paper_candidate.py (R8 — triggered R10 smoke)
  │
data/paper_runs/rcm_v1_defensive_composite_01/20260424T002411Z/
  signals_daily.csv, target_portfolio_daily.csv, pnl_daily.csv,
  fills.csv, run_meta.json
  + live_like_pnl.csv, benchmark_relative_paper.csv, turnover_log.csv (R9)
  (2024-01 to 2024-02 window, 49 days, 79 sym, top-10, +9.1% return)
  │
  ▼ scripts/paper_drift_report.py (R10)
  │
drift_report_20260424T002419Z.md
  (mean |delta| = 0.25 bps, max = 0.68 bps, 0/49 position differences,
   no review flags → pipeline reproducible)
  │
  ▼ scripts/paper_enter.py (R11)
  │
registry[rcm_v1_defensive_composite_01]
  status = S2_paper_candidate      ← current state
  updated_at = 2026-04-24T00:30:37Z
  │
  │ S2 → S3 blocked:
  │   InvalidTransitionError("out of scope for Phase E")
  │   Phase F (broker adapter, live feed, kill switch, monitoring)
  │   required before production transition is available
  ▼
  (future)
```

## 4. Governance invariants

Each invariant below has at least one test that would fail if the
invariant breaks.

| Invariant | Test | File |
|---|---|---|
| `research_promote.py` never writes `config/production_strategy.yaml` | `test_promote_does_not_touch_production_config` | `test_research_promote_cli.py` |
| `run_paper_candidate.py` does not import production config | `test_script_source_has_no_production_config_reads` | `test_run_paper_candidate.py` |
| `run_paper_candidate.py` runtime does not mutate production config | `test_live_run_does_not_modify_production_config` | `test_run_paper_candidate.py` |
| S3/S4 transitions via registry raise `InvalidTransitionError` | `test_s3_transition_raises_notimplementederror` | `test_paper_enter.py` |
| `paper_enter.py` S3 helper raises `NotImplementedError` | `test_paper_enter_module_has_s3_guard` | `test_paper_enter.py` |
| `pyarrow.parquet` not in `sys.modules` after paper imports | `test_paper_trading_engine_does_not_load_pyarrow_parquet` | `test_pyarrow_decouple.py` |
| `scripts/promote_strategy.py` semantics unchanged | not-modified diff check (by absence) | `git diff --stat` |
| `core/mining/rcm_archive.py` schema unchanged | not-modified diff check | `git diff --stat` |
| S0 freeze summary stubs rejected at S1 promote | `test_promote_rejects_stub_summaries` | `test_research_promote_cli.py` |
| TODO-placeholder decision memo rejected | `test_promote_rejects_todo_placeholder` | `test_research_promote_cli.py` |
| `<50`-char decision memo rejected | `test_promote_rejects_short_memo` | `test_research_promote_cli.py` |
| S2 paper run requires paper run + drift report | `test_paper_enter_refuses_no_paper_run`, `test_paper_enter_refuses_no_drift_report` | `test_paper_enter.py` |
| RCMv1 candidate is at S2 after R11 | `test_rcmv1_candidate_in_s2_after_r11` | `test_paper_enter.py` |

## 5. Design decisions (and auditor corrections applied)

All 4 auditor corrections from the Phase E charter review are in
production code:

1. **Candidate registry separate from `rcm_archive.db`** (R1)
   - Separate SQLite file at `data/research_candidates/registry.db`
   - Trial records stay immutable in `rcm_archive`
   - Candidates are governance objects with state + revoke history

2. **Three separate promote scripts, not renamed internals** (R5/R6/R11)
   - `freeze_research_candidate.py` (S0 new)
   - `research_promote.py` (S0 → S1)
   - `paper_enter.py` (S1 → S2)
   - `scripts/promote_strategy.py` unchanged (production-only)

3. **Revoke in E-0 not E-1** (R3)
   - `scripts/revoke_candidate.py` + 6-reason enum shipped in R3
   - `reproducibility_failed` reverts to S0 (not S5) for retry
   - Works for S1 and S2 candidates without paper-layer dependency

4. **No acceptance_pack v3 mega-merge** (R7)
   - Shared helpers in `core/research/acceptance_helpers.py`
   - Two top-level entries kept: `scripts/acceptance_research_composite.py`
     (research, IC-centric) and `core/mining/acceptance_pack.py`
     (production, backtest-centric, untouched this phase)
   - Byte-identical output on RCMv1 real archive verified

Plus one addition from my review (merged into PRD §E0-6):

5. **Pyarrow decouple** (R2)
   - `core/data/market_data_store.py` no longer eager-loads `pyarrow`
     at module import
   - `PaperTradingEngine` import no longer pulls `pyarrow.parquet`
   - Pandas 2.x pulls `pyarrow.lib` unconditionally — acknowledged and
     untestable; the decouple targets the actual filesystem stack

Plus one from the drift-report threshold discussion:

6. **Drift thresholds informational only** (R10 per auditor §7.3)
   - 50 bps mean / 2% worst-day thresholds flag "manual review" in
     the markdown report
   - **Do NOT** auto-hold, auto-demote, or auto-revoke
   - Action requires explicit `scripts/revoke_candidate.py`

## 6. Known limitations

Explicit out-of-scope items (per charter §8.3):

- No real broker / live feed / order routing — Phase F
- No scheduler / daemon / automated paper runs — operator runs manually
- No multi-candidate aggregation across paper runs — per-run reporting only
- No production promote (S2 → S3) — explicit `NotImplementedError`
- No RCMv1 auto-freezing of trials into candidates — always explicit CLI

Known test-hygiene debt (not blockers):

- A few R11 tests create temp paper-run dirs under the real
  `data/paper_runs/` tree and clean up in `try/finally`. Future
  improvement: `run_paper_candidate.py` could take a `--paper-root`
  flag for full `tmp_path` isolation.

Known methodology caveats inherited from RCMv1:

- Phase E pipeline's input (the RCMv1 converged spec) is only
  validated on 14-year panel with `lag=1` IC; actual S2 → S3
  production promotion would need a longer paper window or a
  different validation standard — scoped out of Phase E.

## 7. Ralph-loop execution summary

| Round | Sub-phase | Commit | Tests |
|:-:|:-:|:---|:-:|
| R1 | E-0 | `08731af` candidate registry | +26 |
| R2 | E-0 | `33d5895` pyarrow decouple | +3 |
| R3 | E-0 | `14e2493` revoke + RCMv1 migration | +12 |
| R4 | E-1 | `d434d5f` FrozenStrategySpec | +19 |
| R5 | E-1 | `76742b1` freeze_research_candidate | +9 |
| R6 | E-1 | `c8669c3` research_promote | +12 |
| R7 | E-1 | `cfebef8` acceptance_helpers | +26 |
| R8 | E-2 | `8a07d15` run_paper_candidate | +7 |
| R9 | E-2 | `18ccd68` paper_artifacts | +10 |
| R10 | E-2 | `c45162e` paper_drift_report | +15 |
| R11 | E-2 | `f434412` paper_enter | +11 |
| R12 | Buffer | `f0fb061` README + CLAUDE.md sync + baseline | 0 |
| R13 | Buffer | THIS FILE | 0 |

Each round shipped code + tests + an 11-part Chinese log in
`docs/20260420-ralph_loop_log.md`. Halt condition §3 checked after
every round; none triggered.

**R14 (remaining)**: verify all PHASEEDONE preconditions + emit
`<promise>PHASEEDONE</promise>`.

## 8. Future handoff

### 8.1 What Phase F needs to add (not built here)

- `core/production/` package (analogous to `core/research/`)
- Broker adapter (IB / Alpaca / others)
- Live data feed integration
- Kill switch live wiring
- Monitoring + alerting
- `scripts/production_promote.py` (S2 → S3) using
  `FrozenStrategySpec` schema
- `scripts/rollback_deployment.py` (S3/S4 → S5)
- PRD: to be written when needed

### 8.2 Operational cadence

Until Phase F exists, the recommended cadence is:

- **New candidate**: `freeze_research_candidate.py` → `run_paper_candidate.py`
  for at least 5-7 business days → `paper_drift_report.py` →
  `research_promote.py` → `paper_enter.py`
- **Revocation**: any candidate can be revoked at any state via
  `revoke_candidate.py` with a reason enum + memo path
- **Multiple candidates**: each gets its own `candidate_id` and
  `frozen_spec_path`; registry scales linearly

### 8.3 What to NOT do

- Do not modify `scripts/promote_strategy.py` to also do research
  promote — that's what E-0 explicitly separated
- Do not fold `acceptance_research_composite.py` into
  `core/mining/acceptance_pack.py` (auditor §4 rule)
- Do not auto-freeze trials as candidates; always explicit CLI
- Do not let drift-report thresholds auto-action anything; they are
  informational (auditor §7.3 rule)

## 9. One-sentence summary

**Phase E shipped 11 governance rounds (plus 2 buffer) that turn
research candidates into properly-layered artifacts: registry state
machine, frozen spec, freeze/promote/revoke/paper_enter CLIs, MVP
paper runner, and drift report — with test-enforced invariants that
none of it can accidentally touch production config.**
