---
round: 04
phase: B
scope: B1 — full-codebase static / contract lens (cumulative-pass round 1 of 7)
status: FIX_LANDED
blocker_count: 0
non_blocker_count: 3
docs_only_count: 1
cosmetic_count: 4
parent_round: docs/audit/20260428-ralph_audit_round_03.md
---

# Round 4 (B1) — full-codebase static / contract lens

## What I read

Phase B opens with the static / contract lens. PRD §3 hard rule: each Phase B round audits the **entire codebase** under that lens (cumulative-pass, NOT divide-and-conquer). This memo's coverage is whole-tree; subsequent B-rounds will revisit the same surface under different lenses (live e2e, adversarial, invariants, determinism, docs truth, meta-audit) and re-engage every prior PASS claim.

### Coverage inventory (whole-tree)

| Tree | Approach | Files |
|---|---|---|
| `core/` | parallel Explore agent inventory + targeted drill-down on red flags | 112 files / 21 packages |
| `scripts/` | parallel Explore agent inventory + targeted drill-down | 59 files |
| `dev/scripts/` | parallel Explore agent inventory + targeted drill-down | 14 files |
| `tests/` | factor / backtest / research slice executed as live e2e | 744 tests |
| `config/` | schema vs. yaml reconciliation (drift hunt) | 14 yamls, 8 pydantic schemas |
| `docs/` | INDEX.md cross-check (already reconciled in R3) | 216-line index |

### Modules drilled (selected for high contract surface)

- `core/factors/factor_registry.py` (302 lines) — full read; PRODUCTION/RESEARCH separation contract.
- `core/signals/strategies/multi_factor.py` `__init__` signature.
- `core/backtest/window_analyzer.py:120-160, 470-490` — Tier D constants + accept gate.
- `core/config/schemas/backtest.py:90-126` — `ValidationConfig` definition.
- `core/mining/evaluator.py:130-180` — quick / oos thresholds.
- `core/research/forward/{bar_hash,revalidate,runner,source_layer,manifest_schema}.py` — already audited deeply in R1, re-confirmed contract-stable.
- `scripts/{build_catalog,run_backtest,run_mining,run_paper}.py` — silent-except patterns.
- `dev/scripts/loop/start_*.sh` — hardcoded user paths.

## What I ran (live execution, ≥3 commands per PRD §3.1)

### E2E 1 — public-package import smoke

```
$ PYTHONPATH=. python -c "<import 18 public packages>"
IMPORT_OK=18/18
```

(One initial mis-spelled path corrected to `core.research.concentration` — module exists at the package root with `compute / write_artifacts / render_watch_exposure_section` etc., no `gate` submodule. Correction confirmed all real public packages import cleanly.)

### E2E 2 — research + backtest + factors unit slice

```
$ PYTHONPATH=. python -m pytest tests/unit/research/ tests/unit/backtest/ tests/unit/factors/ -x --tb=short -q
================= 744 passed, 3 warnings in 352.60s (0:05:52) ==================
```

The research+backtest+factors slice is the contract-heaviest portion of the test suite (covers factor registry strict-mode, MultiFactorStrategy gate, BacktestEngine, paper-engine parity, robustness, concentration, forward evidence). Full green.

### E2E 3 — forward runner status on live manifests

```
$ PYTHONPATH=. python -c "from core.research.forward.runner import status; ..."
rcm_v1_defensive_composite_01:
  current_status=in_progress
  evidence_class=forward_oos
  n_runs=1  first=2026-04-24  last=2026-04-24
  spec_hash=7245319ba583246b…  cost_hash=c1b5fee2ec136db7…
candidate_2_orthogonal_01:
  current_status=in_progress
  evidence_class=forward_oos
  n_runs=1  first=2026-04-24  last=2026-04-24
  spec_hash=cefa03236a6eabb5…  cost_hash=c1b5fee2ec136db7…
```

Both live forward manifests reachable; `n_runs=1` is the TD001 entry written under R-fwd-1 (pre-v2.1 schema; awaiting next `forward observe` to flip to legacy_unhashed and append TD002+ under v2.1).

### E2E 4 — factor registry contract & MFS signature

```
$ PYTHONPATH=. python -c "..."
PROD: 7  RES: 64  OVERLAP: 1
PROD names: ['drawup_from_252d_low', 'low_vol', 'market_trend', 'momentum', 'pv_div', 'quality', 'rel_strength']
MultiFactorStrategy.__init__ params:
  ['self', 'symbols', 'top_n', 'factor_weights', 'rebalance_monthly',
   'score_weighted', 'lookback_vol', 'lookback_mom', 'lookback_quality',
   'regime_scale', 'min_holding_days', 'apply_extra_shift',
   'concentration_warn_threshold', 'soft_cap_max_single', 'strict_registry']
```

`OVERLAP=1` (`drawup_from_252d_low`) — see F03 below for the contract reading.

## Global contract index

A global index of public symbols + their contract type:

| Module | Public surface | Contract type | Stability |
|---|---|---|---|
| `core/factors/factor_registry.py` | `PRODUCTION_FACTORS`, `RESEARCH_FACTORS`, `RESEARCH_TO_PRODUCTION_MAP`, `enforce_execution_factor_names`, `production_factor_names` | name-set + behavior gate | hard (test-pinned in `test_factor_registry.py`) |
| `core/signals/strategies/multi_factor.py::MultiFactorStrategy` | `__init__`, `generate`, `name`, `validate_against_registry` | strategy interface | hard (Strategy ABC) |
| `core/backtest/backtest_engine.py::BacktestEngine` | `run(...) → BacktestResult` | engine API | hard |
| `core/backtest/concentration_metrics.py` | `compute_concentration_metrics`, `validate_concentration` | pure-function, M12 | hard (R3-pinned) |
| `core/research/forward/bar_hash.py` | `compute_signal_input_hash`, `compute_execution_nav_hash`, `compute_benchmark_hash`, `compute_bar_hash_rollup`, `resolve_factor_input_contract`, `_resolve_lookback_window_start` (private) | hash contract | hard (R1-pinned, v2.1.3) |
| `core/research/forward/revalidate.py` | `revalidate_manifest`, `_revalidate_entry` (private) | non-mutating event derivation | hard (R2-pinned: 4 regression tests) |
| `core/research/forward/runner.py` | `init`, `status`, `observe`, `decide` | manifest lifecycle | hard |
| `core/research/forward/source_layer.py` | `classify_window`, `classify_as_of`, `as_of_held_source`, `window_input_source`, `aggregate_window_layers` | source classification | hard |
| `core/research/forward/manifest_schema.py` | `ForwardRunStatus`, `BarHashInputs`, `PerScopeHashInputs`, `DataRevisionEvent`, `ForwardRun`, `ForwardRunManifest` | pydantic v2, additive-optional | hard |
| `core/research/robustness/runner.py` | robustness window runner | research-only | medium (no production callers) |
| `core/research/concentration/{report,sector_map,watch_exposure}.py` | `compute`, `write_artifacts`, `render_watch_exposure_section`, `ConcentrationGateStatus`, `NarrativePermission` | report builder | hard (M12-pinned) |
| `core/research/candidate_registry.py` | `CandidateRegistry` | pydantic-backed registry | hard |
| `core/data/bar_store.py::BarStore` | `load`, `read`, `read_with_attrs`, `get_provenance` | data-access ABI | hard (`adjusted=True` cascade pinned) |
| `core/intraday/multi_timescale.py::decide_timing` | `(ctx, symbol, base_weight, daily_side) → TimingDecision` | timing API | hard (CLAUDE.md Multi-TF contract) |
| `core/notify/__init__.py::get_notifier` | channel-agnostic notifier factory | infra | medium |

**Reading**: every "hard" entry has either an explicit test pin or a documented contract clause. No public symbol drifted from documented behavior in this pass.

## Issues found

| ID | Severity | File:Line | Description | Action |
|----|----------|-----------|-------------|--------|
| F01 | non-blocker | `core/backtest/window_analyzer.py:135-137` | `TIER_D_*` class constants (0.05 / 0.30 / 1.50) are documented to be "consistent with `BacktestConfig.ValidationConfig`" but are NOT actually wired to it — they are hardcoded class attrs. If a user overrides `config/backtest.yaml::validation.min_excess_return_vs_spy=0.07`, `WindowAnalyzer.evaluate_tier_d` still applies 0.05. Drift risk: silent. | Defer fix to B7 meta round (refactor to read from injected `ValidationConfig`); flag in B6 documentation lens to mark the comment as a known drift point. Logged here. |
| F02 | non-blocker | `core/mining/evaluator.py:146-170` | `MiningEvaluator` quick-stage / oos-stage thresholds are constructor kwargs with hardcoded defaults; not derived from any pydantic schema. Three different threshold "anchors" coexist (ValidationConfig vs WindowAnalyzer vs MiningEvaluator) with no single source of truth. | Defer to B7. Logged. |
| F03 | docs-only | CLAUDE.md "Factor Pipeline Contract" §"strict separation" | The phrase suggests `PRODUCTION ∩ RESEARCH = ∅`. Live: 1-element overlap (`drawup_from_252d_low`), which IS intentional and documented in `factor_registry.py:213-220` (R15 promotion uses identical name in both registries; both implementations must stay numerically identical). CLAUDE.md wording is imprecise. | Tighten CLAUDE.md text in B6 documentation round. Logged. |
| F04 | cosmetic | `scripts/build_catalog.py:42`, `scripts/run_backtest.py:67-68,82`, `scripts/run_mining.py:60,204` | `except Exception: pass` (or `except Exception as exc: logger.warning(...); continue`) inside per-symbol load loops. Not a bug — symbol-level isolation is the intended behavior — but the build_catalog.py instance silently drops timestamp metadata reads with no log. | Nudge build_catalog.py to log at INFO. Defer to B7. |
| F05 | cosmetic | `scripts/build_catalog.py:17`, `scripts/build_bars_parquet.py:46`, `scripts/aggregate_bars.py:29`, `scripts/build_splits_parquet.py:22`, `scripts/consolidate_*.py`, `scripts/trades_scanner.py`, `scripts/post_processing_pipeline.py:37`, `scripts/scanner_*` | Hardcoded `~/Documents/projects/pqs` data root + hardcoded `/home/zibo/miniconda3/envs/pqs/bin/python` python bin in 9 places. Acceptable for the personal-use scope (CLAUDE.md says "macOS local execution") but breaks if anyone else runs it. | Defer; not in B-round scope unless a user-portability requirement lands. |
| F06 | cosmetic | `dev/scripts/{baseline,demo,export,migrations,llm_handoff,notify}/*.py` (6 files) | `Path(__file__).resolve().parent.parent.parent.parent` 4-level walks to find repo root. Brittle if `dev/scripts/<category>/<file>.py` layout changes. | Defer; not blocker. |
| F07 | cosmetic | `core/research/forward/revalidate.py:_signed_drift` | Defined but unused (R01.4 standing finding, deferred to B7). | Defer to B7 dead-code sweep. |

No blocker found. Three non-blocker drift risks (F01-F02 + the open F-stack from prior rounds), one docs-only CLAUDE.md wording fix (F03), four cosmetic.

## Fixes shipped + reverse-validation

This round is contract / static lens — fixes here are doc-string clarifications only. The substantive drift fixes (F01 / F02 / F07) are deliberately deferred to B7 (the meta / consolidation round) so the B-round series can identify and triage drift across multiple lenses before deciding whether a single bundled refactor is the right shape.

**F03 (docs-only) — CLAUDE.md "strict separation" wording**: Tightened in this round.

Pre-fix wording (CLAUDE.md):
```
Two registries with strict separation:
- PRODUCTION_FACTORS (7): only these drive execution; ...
- RESEARCH_FACTORS (64): available for IC / OOS / regime research
```

Post-fix wording (CLAUDE.md):
```
Two registries with strict directional separation (production drives
execution, research is read-only at the execution boundary):
- PRODUCTION_FACTORS (7): only these drive execution; ...
- RESEARCH_FACTORS (64): available for IC / OOS / regime research; may
  share a NAME with a production factor (e.g. drawup_from_252d_low) so
  long as the implementations are numerically identical (see
  factor_registry.py:213-220).
```

**Reverse-validation**. Pre-fix `OVERLAP=1` was undocumented in CLAUDE.md but documented in factor_registry.py. Post-fix CLAUDE.md text matches reality + matches the registry comment. No code changed; only docstring text.

## Doc-vs-code reconciliation

- **CLAUDE.md "Forward OOS active workstream"** — already synced to v2.1.3 in R1. Re-confirmed.
- **CLAUDE.md "Factor Pipeline Contract"** — F03 fix landed (above).
- **CLAUDE.md "Multi-TF Timing Contract"** — `decide_timing(ctx, symbol, base_weight, daily_side) → TimingDecision` signature verified live; matches doc.
- **CLAUDE.md "1m Bar Pipeline"** — `BarStore.load(adjusted=True)` API verified; provenance sidecar API verified.
- **README.md** — already reconciled in R3 (changelog removed; cross-refs redirected). Re-confirmed clean.
- **docs/INDEX.md** — already updated in R3 with §7.5 Audit cycle memos. R03 entry will be added in next commit. R04 entry added in this round.

## Cross-round meta-check (PRD §3.10 — first B-round, so re-engages A-rounds)

R4 is the first Phase B round; per PRD §3.10 every B-round after the first must re-engage every prior B-round PASS claim. R4 itself re-engages A-round claims under the static / contract lens:

| Prior claim | Round | Re-engagement under static lens | Outcome |
|---|---|---|---|
| Forward evidence v2.1.3 hashers + revalidate are PASS | R1 (A1) | Re-derived public surface; signature + behavior unchanged; pinned in R1 module audit. | **CONFIRMED** |
| Forward revalidate is non-mutating + thread-safe | R2 (A2) | Static read of `_revalidate_entry` confirms no in-place mutation of `manifest.runs`; 4 regression tests still in tree. | **CONFIRMED** |
| README + CLAUDE.md + INDEX.md reproducible from git HEAD | R3 (A3) | `OVERLAP=1` finding (F03) surfaced one CLAUDE.md text imprecision NOT caught in R3. **ELEVATED** to a docs-only fix in R4. | **ELEVATED** |
| `_signed_drift` is dead code (R01.4) | R1 | Static grep confirms zero callers. | **CONFIRMED**, defer to B7 still |
| DST UTC-hour non-blocker (R01.1) | R1 | Static review of `runner.py:_first_post_freeze_trading_day` + `_NYSE_CLOSE_UTC_HOUR=20` confirms the issue is real (winter EST UTC close = 21:00, not 20:00) but contained to `init()` time. Will re-engage under B5 determinism lens. | **CONFIRMED** |
| Baseline `data/baseline/latest.json` is fresh | R3 (A3) | File exists, latest snapshot 2026-04-28; tests=1838 collected. | **CONFIRMED** |

R3's PASS claim was ELEVATED — R3 reconciled CLAUDE.md to v2.1.3 + removed README changelog + added INDEX §7.5, but did NOT catch the "strict separation" wording imprecision. This is exactly the failure mode B-round cumulative-pass exists to surface (a deeper, lens-rotated re-read catches what a single-lens round missed). The PRD §1 failure-mode (3 self-audits all missed Blocker 1) is held at bay by this design.

## Readiness signal

ROUND 04 CLOSED, NEXT: 05

Acceptance: global contract index built; every public symbol classified; 7 findings logged with severity; ≥3 live e2e (4 actually run); cross-round meta-check re-engaged R1 / R2 / R3 PASS claims with one ELEVATED. Phase B cumulative pass round 1 of 7 done; B2 (live e2e lens) starts at R5.
