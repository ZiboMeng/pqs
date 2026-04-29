# PRD — Acceptance Threshold Unification (F01 + F02 closure)

**Status**: v1.1 — 2026-04-28. v1.0 drafted; v1.1 folds codex round-13 sign-off + 3 design decisions per `docs/audit/20260428-codex_round_13_acceptance_threshold_answers.md`. **Implementation authorized after user explicit-go**.
**Author**: zibo (drafted by Claude based on R4 / R10 audit findings + codex round-11 priority #2 + codex round-13 design decisions)
**Authority required**: user explicit (zibo) — codex sign-off received; user go-signal still required because deletion of `ValidationConfig` is a structural change to evaluation surface (CLAUDE.md "MUST PAUSE: changing evaluation criteria definitions").
**Lineage tag (when committed)**: `acceptance-threshold-unification-2026-04-28`
**Parent context**:
- R4 (B1 static lens) finding F01 — `WindowAnalyzer.TIER_D_*` documented as "consistent with `BacktestConfig.ValidationConfig`" but unwired
- R4 finding F02 — `MiningEvaluator` thresholds as constructor kwargs with hardcoded defaults; no schema source
- R10 deferral memo `docs/memos/20260428-r10_threshold_drift_deferral.md` — recommended fix shape
- Codex round-11 review priority #2 — "短期合理 defer implementation, 不可以 defer prioritization"

---

## 1. Why this PRD

### 1.1 The R4 findings (F01 + F02) understated the scope

A more complete audit at draft time discovered the codebase has **8 distinct threshold anchors**, not 3. The R10 deferral memo was based on an incomplete inventory. Critical new finding:

> **`core/config/schemas/backtest.py::ValidationConfig` (9 fields) has NO active consumer in core code today.** It is pure dead config. Two docstrings in `WindowAnalyzer` and `factor_evaluator` reference it as "consistent with" but neither actually reads it. `core/config/production_strategy.py::validation.all_passed` uses a *different* `ValidationStatus` model (just 4 boolean flags), not the threshold model.

This means the fix is not just "wire A → B"; it is "decide what `ValidationConfig` is supposed to do, then wire it (or delete it)".

### 1.2 Why this matters

Codex round-11 review (`docs/audit/20260428-codex_round_11_review.md`) framed it precisely:

> 这不是 UI/文档小 drift；这是 **acceptance threshold governance drift**；它不会马上炸，但会慢慢污染研究流程，让你：错拒好候选 / 错放坏候选 / 让不同入口用不同标准评价同一个策略。对个人量化系统来说，这类 drift 的伤害不是爆炸式，而是**持续消耗研究资本**。

Concretely the failure shape: a researcher edits `config/backtest.yaml::validation.min_excess_return_vs_spy=0.07` to tighten Tier D, then runs `WindowAnalyzer.evaluate_tier_d`, gets a Tier D pass at the *unchanged* 0.05 threshold, and never knows the yaml edit had no effect. That edit might also miss `acceptance_pack._THRESHOLDS` (which is intentionally frozen — but the researcher might not realize that is the design intent).

### 1.3 What this PRD is NOT

- **Not a research-criteria change**: every threshold value stays at its current numeric default. This PRD is plumbing only.
- **Not a touch on `acceptance_pack._THRESHOLDS`**: that anchor is **intentionally** frozen and decoupled from yaml (per its own line-89 comment: "mirror config/backtest.yaml::mining but hardcoded here so the pack has a stable contract independent of config drift"). It is a versioned snapshot of acceptance contracts, not a tuneable parameter.
- **Not a touch on `core/research/concentration/report.py`** WARNING/EXTREME constants: those are derived from PRD v3 §C lines 281-294 and live under their own spec; conflating them with acceptance thresholds creates *worse* drift, not less.
- **Not a touch on robustness window thresholds** in `core/research/robustness/`: their thresholds are emitted from runner logic, not loaded as static defaults.

---

## 2. Threshold anchor inventory (full)

| ID | Location | Fields | Active consumer | Class |
|----|----------|--------|-----------------|-------|
| A1 | `core/config/schemas/backtest.py::ValidationConfig` | 9 (min_excess_return_vs_spy, min_ir_vs_spy, max_drawdown_vs_spy_multiplier, max_crisis_drawdown_abs, min_oos_vs_is_return_ratio, min_windows_positive_excess_pct, auto_fail_single_period_contribution, auto_fail_single_asset_contribution, auto_fail_crisis_vs_benchmark_multiplier) | **NONE** | dead |
| A2 | `core/backtest/window_analyzer.py::TIER_D_*` (class attrs) | 3 (TIER_D_MIN_EXCESS_RETURN, TIER_D_MIN_IR, TIER_D_MAX_DD_MULTIPLIER) | `WindowAnalyzer.evaluate_tier_d` (line 484-489) | unwired-from-yaml |
| A3 | `core/mining/evaluator.py::MiningEvaluator.__init__` kwargs | 12 (quick / oos / param / diversity / qqq / oos-vs-is) | `MiningEvaluator.evaluate` | **wired** via `scripts/run_mining.py:235-251` from yaml |
| A4 | `core/mining/acceptance_pack.py::_THRESHOLDS` | 10 (quick / oos / maxdd / qqq) | `build_acceptance_pack` | **intentionally frozen** (line 89 comment) |
| A5 | `core/factors/factor_evaluator.py::_auto_tier` | 4 inline (0.8 / 0.5 / 0.3 / 0.1 IR cuts for S/A/B/C) | `_auto_tier` | hardcoded |
| A6 | `core/research/concentration/report.py` | 8 (WARNING_TOP1/TOP3/THIN_DATA/WATCH_SINGLE + EXTREME_*) | concentration gate | hardcoded (PRD v3 §C derived — out of scope) |
| A7 | `config/backtest.yaml::validation` | 9 fields (mirror A1) | **NONE** (loaded into `ValidationConfig` but ValidationConfig has no consumer) | dead yaml |
| A8 | `config/backtest.yaml::mining` | 12 fields (source for A3) | `run_mining.py` | live |

**In scope for this PRD: A1 + A2 + A5 + A7. Out of scope: A3 (already wired correctly), A4 (intentionally frozen), A6 (separate spec), A8 (already-live source for A3).**

---

## 3. Constraints

### 3.1 Hard constraints (cannot violate)

- **No numeric value change**: every threshold stays at its current default. This PRD is structural; any new value debate should run as a separate `prd_threshold_recalibration.md` after this is shipped.
- **Long-only / SQQQ blacklist / SPY+QQQ benchmark / pricing semantics** all hold (CLAUDE.md "Invariant Constraints").
- **`acceptance_pack._THRESHOLDS` stays untouched**. It is a versioned contract for already-promoted artifacts; coupling it to yaml would re-introduce the very drift the comment at line 89 is preventing.
- **Hard rule: no silent drop of consumers**. If A1 has no consumer today, the fix is either to (a) add a real consumer at `WindowAnalyzer` / `factor_evaluator`, or (b) delete `ValidationConfig` and `validation:` from `config/backtest.yaml` (after auditing for any external readers). Half-fixing — leaving dead config in place "for future use" — is exactly the drift this PRD exists to remove.

### 3.2 Reverse-validation requirement (PRD §3.2 of ralph-audit cycle still applies)

Per the audit cycle's hard rule: every fix must reverse-validate. For this PRD, the regression test (per design §6.4) IS the reverse-validation: a test that constructs `BacktestConfig(validation=ValidationConfig(min_ir_vs_spy=0.55))` and asserts `WindowAnalyzer.evaluate_tier_d` actually applies 0.55 must FAIL under current code and PASS after the fix.

### 3.3 No half-finished implementation

Per CLAUDE.md "Doing tasks": "No half-finished implementations either." If implementation lands, all 4 in-scope anchors (A1 / A2 / A5 / A7) are addressed in the same change-set. No "wire A2 first, leave A5 for later" — that creates a new drift window.

---

## 4. Proposed design

### 4.1 Single source of truth (nested submodel shape per codex round-13)

Create `core/config/schemas/acceptance.py` with three **nested submodels** under `AcceptanceThresholds`. The nested shape is mandated by codex round-13 §"Decision 1" + §"Decision 2": one policy surface, three semantic groups (Tier D / walk-forward / factor tiers), no flat 12-field bag.

```python
# core/config/schemas/acceptance.py (new file)

from pydantic import BaseModel, Field


class TierDThresholds(BaseModel):
    """Tier D acceptance thresholds (WindowAnalyzer.evaluate_tier_d)."""
    min_excess_return_vs_spy: float = Field(default=0.05, ge=0)
    min_ir_vs_spy: float = Field(default=0.30, ge=0)
    max_dd_vs_spy_multiplier: float = Field(default=1.50, ge=1.0)


class WalkForwardThresholds(BaseModel):
    """Walk-forward / OOS validation thresholds (currently dead in
    `ValidationConfig`; this is their new live home).

    Codex round-13 §"Decision 1": these are governance thresholds; they
    belong here (one policy surface) rather than in `MiningEvaluator`,
    which is the consumer not the owner. `MiningEvaluator` may later
    read from `cfg.acceptance.walk_forward` but it does NOT define
    these defaults.
    """
    min_oos_vs_is_return_ratio: float = Field(default=0.50, ge=0)
    min_windows_positive_excess_pct: float = Field(default=0.60, ge=0, le=1.0)
    auto_fail_single_period_contribution: float = Field(default=0.50, ge=0, le=1.0)
    auto_fail_single_asset_contribution: float = Field(default=0.40, ge=0, le=1.0)
    auto_fail_crisis_vs_benchmark_multiplier: float = Field(default=2.0, ge=1.0)
    max_crisis_drawdown_abs: float = Field(default=0.25, ge=0, le=1.0)


class FactorTierThresholds(BaseModel):
    """Factor auto-tier IR cuts (`factor_evaluator._auto_tier`).

    Codex round-13 §"Decision 2": separate submodel because factor-tier
    semantics are adjacent to but not identical to strategy-tier
    semantics (the letter overlap S/A/B/C/D between Tier D and factor
    tiers is coincidental).
    """
    s_min_ir: float = Field(default=0.80, ge=0)
    a_min_ir: float = Field(default=0.50, ge=0)
    b_min_ir: float = Field(default=0.30, ge=0)
    c_min_ir: float = Field(default=0.10, ge=0)


class AcceptanceThresholds(BaseModel):
    """Single source of truth for acceptance-tier thresholds.

    These thresholds gate Tier D promotion (WindowAnalyzer), walk-
    forward / OOS pass criteria, and factor auto-tier classification
    (factor_evaluator). Tunable via `config/acceptance.yaml`.

    NOT in scope: mining gates (see `config/backtest.yaml::mining`,
    consumed by `MiningEvaluator`), `acceptance_pack._THRESHOLDS`
    (intentionally frozen contract for promoted artifacts — codex
    round-13 §"Decision 3"), concentration gate (PRD v3 §C derived).
    """
    tier_d:        TierDThresholds        = Field(default_factory=TierDThresholds)
    walk_forward:  WalkForwardThresholds  = Field(default_factory=WalkForwardThresholds)
    factor_tiers:  FactorTierThresholds   = Field(default_factory=FactorTierThresholds)
```

**Field rename note (vs v1.0 PRD draft)**: when nesting, the field names drop the subgroup prefix (e.g. `tier_d_min_ir_vs_spy` → `acceptance.tier_d.min_ir_vs_spy`). Old flat names from the v1.0 draft are retired before any code is written; only the nested shape ships.

### 4.2 Yaml location: new `config/acceptance.yaml` (nested shape)

A new file, separate from `config/backtest.yaml::validation`. Rationale: the legacy `validation:` yaml block has been dead for an unknown duration; renaming + relocating signals "this is the new live thing", and migration is more visible than in-place mutation. Old `config/backtest.yaml::validation` block is **deleted** in the same change-set (no half-finished migration).

The yaml mirrors the nested submodel shape from §4.1.

```yaml
# config/acceptance.yaml (new file)
# Acceptance-tier thresholds — single source of truth.
# Loaded into core.config.schemas.acceptance.AcceptanceThresholds.
# Consumers: core/backtest/window_analyzer.py + core/factors/factor_evaluator.py.
# NOT for: mining gates (see backtest.yaml::mining; MiningEvaluator
# consumes those, not these); acceptance_pack (intentionally frozen
# contract — codex round-13 §"Decision 3"); concentration (PRD v3 §C).

tier_d:
  min_excess_return_vs_spy: 0.05
  min_ir_vs_spy: 0.30
  max_dd_vs_spy_multiplier: 1.50

walk_forward:
  min_oos_vs_is_return_ratio: 0.50
  min_windows_positive_excess_pct: 0.60
  auto_fail_single_period_contribution: 0.50
  auto_fail_single_asset_contribution: 0.40
  auto_fail_crisis_vs_benchmark_multiplier: 2.0
  max_crisis_drawdown_abs: 0.25

factor_tiers:
  s_min_ir: 0.80
  a_min_ir: 0.50
  b_min_ir: 0.30
  c_min_ir: 0.10
```

### 4.3 Loader integration

`core/config/loader.py::load_config` adds an `acceptance: AcceptanceThresholds` field to the top-level config object:

```python
class Config(BaseModel):
    system: SystemConfig
    backtest: BacktestConfig
    risk: RiskConfig
    cost_model: CostModelConfig
    universe: UniverseConfig
    regime: RegimeConfig
    reporting: ReportingConfig
    notify: NotifyConfig
    acceptance: AcceptanceThresholds = Field(default_factory=AcceptanceThresholds)  # NEW
```

`load_config` reads `config/acceptance.yaml` (or uses defaults if absent — the model has all defaults populated). Missing file is non-fatal during the migration grace period.

### 4.4 Consumer rewires

#### 4.4.1 `WindowAnalyzer` (A2 → AcceptanceThresholds)

```python
# core/backtest/window_analyzer.py

class WindowAnalyzer:
    def __init__(
        self,
        engine: BacktestEngine,
        window_size: int = 252,
        step_size: Optional[int] = None,
        thresholds: Optional[AcceptanceThresholds] = None,  # NEW
    ):
        self._engine = engine
        self._window_size = window_size
        self._step_size = step_size or window_size
        self._thresholds = thresholds or AcceptanceThresholds()  # default-fallback safe

    # evaluate_tier_d body uses self._thresholds.tier_d.min_excess_return_vs_spy etc.
    # (nested submodel access; class-level TIER_D_* constants are REMOVED.)
```

Callers of `WindowAnalyzer(engine)` continue to work; new optional kwarg.

#### 4.4.2 `factor_evaluator._auto_tier` (A5 → AcceptanceThresholds.factor_tiers)

Function gains an optional `thresholds: AcceptanceThresholds = None` kwarg with a default that constructs one. Hardcoded 0.8/0.5/0.3/0.1 in the function body are replaced with `thresholds.factor_tiers.s_min_ir` / `.a_min_ir` / `.b_min_ir` / `.c_min_ir` (nested-submodel access).

#### 4.4.3 `ValidationConfig` (A1) — DELETE

`ValidationConfig` and its `validation:` field on `BacktestConfig` are **removed** in the same commit. `config/backtest.yaml::validation` block is deleted. Any docstring references in `WindowAnalyzer` and `factor_evaluator` redirect to `AcceptanceThresholds`.

Pre-removal grep confirms no consumer (the audit done at draft time confirmed this; the regression in §6.4 will re-confirm at impl time).

### 4.5 What stays unchanged

- `MiningEvaluator` (A3) — already wired correctly via `run_mining.py:235-251`. Optional follow-up: rename its kwargs to mirror `AcceptanceThresholds.walk_forward` so a future researcher can pass either, but **not in this PRD's scope**. (If pursued, a separate sub-PRD.) Per codex round-13 §"Decision 1": `MiningEvaluator` may later read from `cfg.acceptance.walk_forward` but it does NOT become the canonical home of those definitions.
- `acceptance_pack._THRESHOLDS` (A4) — **kept frozen**. Per codex round-13 §"Decision 3" rule: `_THRESHOLDS` does NOT auto-sync from `AcceptanceThresholds`. Future divergence is allowed; only an explicit versioned recalibration PRD with (a) version bump, (b) contract migration rationale, (c) backward-compat stance, (d) changelog entry is permitted to update `_THRESHOLDS`. Add a one-line docstring update at line 89 of `acceptance_pack.py` capturing this codex round-13 rule.
- `core/research/concentration/report.py` (A6) — out of scope.
- `config/backtest.yaml::mining` (A8) — out of scope.

---

## 5. Acceptance criteria

A change-set passes this PRD if and only if all of the following hold:

1. **`AcceptanceThresholds` model exists** at `core/config/schemas/acceptance.py` with the 3 nested submodels per §4.1 (`TierDThresholds`, `WalkForwardThresholds`, `FactorTierThresholds`).
2. **`config/acceptance.yaml` exists** with the 3 nested sections at their current default values (per §4.2).
3. **`load_config` reads it** and exposes it as `cfg.acceptance` (per §4.3).
4. **`WindowAnalyzer.TIER_D_*` constants are removed** and `evaluate_tier_d` reads from `self._thresholds` (per §4.4.1).
5. **`factor_evaluator._auto_tier` reads thresholds from `AcceptanceThresholds`** (per §4.4.2). Public callers continue to work via the default-fallback kwarg.
6. **`ValidationConfig` is removed** from `core/config/schemas/backtest.py`; `validation:` field removed from `BacktestConfig`; `config/backtest.yaml::validation` block removed (per §4.4.3).
7. **All numeric values stay identical** to current defaults (§3.1).
8. **`acceptance_pack._THRESHOLDS` is unchanged** in the diff. Per codex round-13 §"Decision 3", a one-line docstring update at `acceptance_pack.py:89` captures the rule "future divergence requires an explicit versioned recalibration PRD; no auto-sync from `AcceptanceThresholds`".
9. **Regression tests added** (§6.4): a) `WindowAnalyzer` honors a non-default `tier_d_min_ir_vs_spy=0.55` injected via `AcceptanceThresholds`; b) `_auto_tier` honors a non-default `factor_tier_s_min_ir=0.95`; c) absence of `config/acceptance.yaml` falls back to schema defaults without error.
10. **Full pytest suite green** (1838+ passed; new tests included).
11. **Reverse-validation evidence in commit message**: PRD §3.2 hard rule — show that reversing the change reproduces the pre-fix "yaml edit ignored" behavior (e.g. test variant b fails on pre-fix).
12. **README + CLAUDE.md updated**: README §1.4 / §10 references to threshold sources updated to point at `config/acceptance.yaml`. CLAUDE.md "Framework Completion PRD" closes F01 + F02 with this PRD reference.

---

## 6. Implementation steps (when authorized)

Each step is a separate commit so a partial revert is clean.

### 6.1 Step 1 — schema + yaml (no consumers wired yet)

- Add `core/config/schemas/acceptance.py` with 4 classes: `TierDThresholds`, `WalkForwardThresholds`, `FactorTierThresholds`, `AcceptanceThresholds` (nested per §4.1).
- Add `core/config/schemas/__init__.py` re-export.
- Add `config/acceptance.yaml` with the 3 nested sections at current defaults.
- Add `cfg.acceptance` field to top-level Config + loader plumbing.
- Add unit tests: (a) `test_acceptance_thresholds_loads_from_yaml` — full nested override works; (b) `test_acceptance_thresholds_partial_yaml` — overriding only `tier_d.min_ir_vs_spy` keeps other submodels at default; (c) `test_acceptance_thresholds_missing_yaml_falls_back_to_defaults` — no-file case.

After this step the codebase has the new model loaded but nobody reads it yet. Reversible.

### 6.2 Step 2 — wire WindowAnalyzer (A2)

- Add `thresholds: Optional[AcceptanceThresholds] = None` kwarg.
- Remove `TIER_D_*` class attrs.
- Replace usage in `evaluate_tier_d`.
- Add regression test: `test_window_analyzer_honors_yaml_threshold_override`.

### 6.3 Step 3 — wire factor_evaluator (A5)

- Add `thresholds` kwarg to `_auto_tier` (with default fallback).
- Replace 4 inline cuts.
- Add regression test: `test_auto_tier_honors_yaml_threshold_override`.

### 6.4 Step 4 — delete A1 + A7

- Remove `ValidationConfig` from schema.
- Remove `validation:` from `BacktestConfig`.
- Remove `config/backtest.yaml::validation:` block.
- Update 2 docstring references (WindowAnalyzer comment line 134; factor_evaluator docstring line 303) to point at `AcceptanceThresholds`.
- Run full pytest. Any test referencing `cfg.backtest.validation` should already be migrated by step 1-3.

### 6.5 Step 5 — docs

- README §1.4 / §10 update for new threshold source.
- CLAUDE.md "Framework Completion PRD" — add F01 + F02 to closed list.
- This PRD's status header: Draft v1.0 → Shipped v1.0 + commit refs.
- INDEX.md add to §"PRDs".

### 6.6 Step 6 — codex review handoff

Push the implementation memo + cycle PRD update to `review/claude-collab` for codex sign-off. Defer to user / codex on whether to follow with the optional A3 kwarg-rename sub-PRD.

---

## 7. Risk

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| External (out-of-tree) consumer reads `cfg.backtest.validation` | low (single-user repo) | breakage | grep -r in this repo confirms zero consumer at draft time; impl-time grep before delete |
| `config/acceptance.yaml` missing in a fresh checkout | medium | startup fails | schema has `default_factory` so missing file → defaults; `load_config` warns once but does not fail |
| Researcher edits old `config/backtest.yaml::validation` block | medium during transition | edit is ignored | step 4 deletes the block; trying to edit a deleted file is a loud error |
| Step 4 (delete) merged before step 2-3 (wires) | low (gated by acceptance criteria) | runtime AttributeError on `cfg.backtest.validation` | step ordering enforced by §6 sequence; full pytest at end of step 4 catches |
| Future numeric recalibration drift | medium | divergence from `acceptance_pack._THRESHOLDS` | future recalibration PRD must explicitly state whether to lockstep update `_THRESHOLDS` (versioned bump) or keep the contract frozen — this PRD does NOT address recalibration semantics |

---

## 8. Out of scope (explicit)

- Numeric threshold recalibration (e.g. raising `min_ir_vs_spy` from 0.30 → 0.40). Separate PRD.
- `acceptance_pack._THRESHOLDS` redesign. Separate PRD (would require versioning semantics).
- `core/research/concentration/report.py` thresholds. Separate spec (PRD v3 §C).
- `core/research/robustness/runner.py` runtime thresholds. Different design pattern (runtime emission, not static defaults).
- `MiningEvaluator` constructor kwarg renames (A3 cosmetic). Optional follow-up sub-PRD.
- Adding any new threshold field. This PRD only relocates existing ones.

---

## 9. Sequencing (when this lands)

Codex round-11 review priority queue places this at #2 (after the now-completed first-real-forward-observe). Suggested sequencing:

- **Now**: PRD draft committed and pushed to `review/claude-collab` for codex sign-off.
- **After codex sign-off**: implementation in 4-step sequence per §6, single change-set per step.
- **Before implementation**: pause for user explicit-go signal (per CLAUDE.md "Autonomous Decision Authority — MUST PAUSE: changing core constraints / changing evaluation criteria definitions"). The model relocation alone is sub-threshold for autonomy, but since the dead config (`ValidationConfig`) gets DELETED, that's a structural change in evaluation surface.

---

## 10. Open questions — RESOLVED by codex round-13

All 3 v1.0 open questions were answered by codex round-13
(`docs/audit/20260428-codex_round_13_acceptance_threshold_answers.md`).
Answers folded into v1.1 design above:

1. **Q1 — A1 walk-forward fields location**: keep under `AcceptanceThresholds`, but **nested** — `AcceptanceThresholds.walk_forward`. Do NOT migrate to `MiningEvaluator`. (codex §"Decision 1") → folded into §4.1 + §4.2.

2. **Q2 — `factor_tier_*_min_ir` placement**: separate nested submodel `FactorTierThresholds`, mounted at `AcceptanceThresholds.factor_tiers`. Do NOT split into a separate root yaml. (codex §"Decision 2") → folded into §4.1 + §4.2.

3. **Q3 — `acceptance_pack._THRESHOLDS` auto-sync**: NO automatic sync. `_THRESHOLDS` stays frozen by default; only an explicit versioned recalibration PRD with version bump + contract migration rationale + backward-compat stance + changelog entry can update it. (codex §"Decision 3") → folded into §4.5 + new acceptance criterion §6.8.

No new open questions in v1.1. Implementation may proceed after user explicit-go.

---

## 11. Pointer summary

- **R10 deferral memo** (parent): `docs/memos/20260428-r10_threshold_drift_deferral.md`
- **Codex round-11 review** (priority): `docs/audit/20260428-codex_round_11_review.md`
- **Codex round-13 sign-off + 3 decisions** (folded into v1.1): `docs/audit/20260428-codex_round_13_acceptance_threshold_answers.md`
- **R4 audit memo** (F01 + F02 origin): `docs/audit/20260428-ralph_audit_round_04.md`
- **Cycle summary** (codex review handoff): `docs/audit/20260428-ralph_audit_cycle_summary_for_codex_review.md`

End of PRD v1.1.
