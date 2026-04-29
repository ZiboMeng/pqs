---
title: PRD — Temporal Split & Holdout Discipline (Track A v1)
date: 2026-04-29
version: v1.0
status: draft_for_codex_review
authority_required: user explicit (zibo) — implementation NOT authorized by this PRD; PRD-level codex sign-off requested
parent_context:
  - docs/memos/20260429-post_audit_strategic_roadmap.md (v2; 12-item checklist §11)
  - docs/audit/20260429-codex_round_19_strategic_redirection_review.md
  - docs/prd/20260427-forward_evidence_hardening_prd.md (v2.1.3, related — forward evidence)
  - docs/prd/20260428-config_universe_snapshot_hardening_prd.md (F PRD, related — config snapshot)
  - docs/memos/20260426-research-cycle-2026-04-26-01_close.md (last 0-nominee close)
lineage_tag_when_committed: temporal-split-holdout-v1-2026-04-29
related_open_decisions:
  - track_a_prd_draft_codex_review (this doc)
  - d7_forward_decay_detection_in_track_d (deferred, listed §13)
  - d8_dividend_5yr_4pct_margin (Claude proposed, codex review needed)
---

# PRD — Temporal Split & Holdout Discipline (Track A v1)

## 1. Why this PRD

### 1.1 Problem statement

Project's last real mining run (`research-cycle-2026-04-26-01`, 200 trials TPE on the post-fix codebase) produced **0 nominee** under newly-tightened gates (G2.A 30% concentration ceiling). Latest archive (`post-2026-04-23-feat-v1-expanded`) shows **65 trials / 0 OOS pass / best OOS IR = -0.119** (negative). RCMv1 + Cand-2 forward observation continues but both candidates were nominated under the OLD gate framework — they would not re-pass current gates.

Two strategic conclusions follow (`docs/memos/20260429-post_audit_strategic_roadmap.md` §2):

1. The next mining cycle must run on a **truly out-of-sample evaluation framework**, not pseudo-OOS walk-forward over a single contiguous panel.
2. Continued tweaking of gates / weights without an honest holdout is the failure mode the project keeps hitting.

This PRD lands the framework. Its **only** purpose is research-discipline infrastructure: temporal split + label-purge + sealed-eval ledger + role-locked gates + F1/F2 fork criteria.

### 1.2 What this PRD is NOT

- **Not a new mining run.** Track C handles that.
- **Not a new factor library.** F2 fork (if triggered) handles that.
- **Not a gate recalibration.** F1 fork (if triggered) handles that.
- **Not a fleet allocator.** Track B handles step 1-4 (synthetic input); Track D handles step 5.
- **Not a forward decay detector.** Track D D.7 handles that.
- **Not a dividend correction implementation.** Schema only (M8); Track D enforces.

---

## 2. Constraints

### 2.1 Hard constraints (cannot violate)

- **CLAUDE.md invariants**: long-only / no-margin / no-short / SQQQ blacklist / SPY+QQQ benchmark dual / MaxDD 15-20% / Chinese reporting / English code naming.
- **Pricing semantics** (`CLAUDE.md` §"Pricing and Valuation Semantics"): adjusted prices via `BarStore.load(adjusted=True)` cascade; no vendor swap regression test must exist before this PRD ships.
- **PRD M1 single source of truth**: `config/production_strategy.yaml` remains the only authoritative production strategy spec; this PRD does not modify it.
- **No code-level hardcoding**: every year, threshold, role, and gate must be readable from `config/temporal_split.yaml`. Python code reads schema, never duplicates values.

### 2.2 Soft constraints (best practice, deviations require memo)

- Determinism: split YAML hash must be reproducible across machines (sorted keys, list-order preserved per F PRD).
- Backward compatibility: existing archive trials (pre-temporal-split) must remain readable; their fingerprints lack `split_sha256` and that's expected.
- F PRD compatibility: PRD-F config snapshot already hashes `config/*.yaml`; `temporal_split.yaml` will be picked up automatically by `_canonical_yaml_sha`.

---

## 3. Scope (in / out)

### 3.1 In scope

| In | Description |
|---|---|
| Temporal split YAML schema | `config/temporal_split.yaml` (M1-M9 12 items) |
| Loader / validator | `core/research/temporal_split.py` pydantic v2 model + fail-closed validation |
| Mining panel constructor wiring | `core/mining/*` reads `split_config`, restricts panel to train years |
| Acceptance pack wiring | Per-validation-year + per-stress-slice + 2025 hard-gate + role-gate aggregation |
| Sealed-eval ledger | `core/research/sealed_ledger.py` parquet + fail-closed-on-repeat |
| Regime auto-classifier integration | Calls `core/diagnostics/regime_detector.py` per year, writes `auto_classifier_tag` to YAML at PRD-implementation time |
| Leak detection tests | 6+ tests covering 2026-row-in-train / validation-signal-in-train / role-unset-at-mining / regime-tag-missing / forward-label-cross-boundary / sealed-ledger-repeat |
| Documentation sync | README + CLAUDE.md + INDEX.md pointers |

### 3.2 Out of scope

| Out | Defer to |
|---|---|
| Mining loop / Optuna integration changes | Track C (uses Track A schema) |
| New factor library | F2 fork PRD (post-smoke) |
| Gate recalibration values | F1 fork PRD (post-smoke) |
| Fleet allocator step 5 live wiring | Track D |
| Forward decay detector | Track D D.7 |
| Dividend correction code | Track D D.5 |
| 2026 actual sealed-test execution | Track C step C.4 (one-shot post-acceptance) |

---

## 4. Design — Temporal split structure (M1, M3)

### 4.1 Year partition (Claude M1 modification of auditor 2's split)

| Year | Role | Regime tag (manual) | Notes |
|---|---|---|---|
| 2007-2008 | reference (excluded from alpha) | financial_crisis | Available but not weighted in alpha selection |
| 2009-2017 | train | mixed | Bulk of historical training data |
| 2018 | **validation** (M1: moved from train) | rate_hike_bear | Adjacent bear-regime check |
| 2019 | validation | normal_bull | |
| 2020 (full) | train | covid_v_recovery | COVID flash slice borrowed (see §4.3) |
| 2021 | validation | liquidity_mania | |
| 2022 (full) | train | rate_hike_bear_full | Q3-Q4 stress slice borrowed (see §4.3) |
| 2023 | validation | ai_narrow | |
| 2024 | train | ai_continuation | |
| 2025 | validation | current_market | **Hard gate for core role** (M2) |
| 2026 | sealed final test | unseen | Single-shot evaluation only |

### 4.2 Factor warmup boundary (M3)

Factor lookback windows MAY cross train→validation boundary (rolling 252-day momentum on 2019-01-15 reads 2018 data — this is rolling factor semantics, not leakage). The PRD enforces:

- `factor_warmup_may_cross_boundary: true`
- `factor_warmup_max_lookback_days: 504` (cap; factor registry rejects longer at registration time)
- `validation_signal_dates_must_be_in: ["validation"]` — signal dates must fall inside validation year, even if their lookback reaches into train

Each candidate's actual `max_factor_lookback_days_used` is recorded in archive metadata (codex R19 #5).

### 4.3 Stress slices (M1 supplement)

Two named slices borrowed from train years for **MaxDD sanity check only** (do NOT participate in alpha selection or validation aggregation):

| Name | Range | Source year | Purpose |
|---|---|---|---|
| `covid_flash` | 2020-02-15 → 2020-04-30 | 2020 | COVID crash MaxDD check |
| `rate_hike_2022` | 2022-08-15 → 2022-10-15 | 2022 | 2022 H2 acceleration drawdown check |

Stress slice MaxDD threshold = 0.25 (looser than validation year 0.20 — these are real crisis windows).

---

## 5. Design — Discipline rules (M4 purge / M5 ledger / M9 regime dual tag)

### 5.1 Purged label / forward-return boundary (M4)

Standard financial-ML purging+embargo (Marcos Lopez de Prado). Policy:

- `label_horizon_days_max: 21` — any forward-return label longer than 21d rejected at mining configuration time.
- `purge_at_split_boundary: true` — labels whose horizon crosses train→validation or validation→sealed boundary must be **dropped from the affected year's evaluation set**, not silently truncated.
- `embargo_days: 0` — v1 does not add a buffer between train and validation; recorded as a config option for v2 (codex R19 follow-up may request).

Concrete examples:
- 21d forward return computed on 2018-12-15 (train→validation boundary 2018-12-31 = end of train if 2019 is validation): **drop**, because the label window crosses into validation year. (In our v1 split 2018 IS validation, so this specific example would not arise; but boundary is between 2017→2018 and 2018→2019 etc.)
- 21d forward return computed on 2025-12-20 (validation→sealed boundary 2025-12-31): **drop**.

### 5.2 Machine-auditable sealed-eval ledger (M5)

`data/research_candidates/sealed_eval_ledger.parquet`. Append-only. Fields:

| Field | Type | Why |
|---|---|---|
| `split_name` | str | Detect cross-split contamination |
| `split_sha256` | str | Detect intra-split YAML drift |
| `candidate_spec_sha256` | str | Detect candidate spec mutation |
| `git_sha` | str | Detect codebase drift |
| `panel_max_date` | date | Detect data drift |
| `evaluation_timestamp_utc` | datetime | Audit trail |
| `result_metrics_sha256` | str | Detect result mutation |

**Fail-closed-on-repeat rule**: if a row already exists with the same `(split_name, candidate_spec_sha256)` tuple, the next sealed evaluation MUST abort with a clear message ("This candidate has already been evaluated against split X. To re-evaluate after intentional gate change, bump split_name to a new version."). This prevents silent retries that would consume the holdout multiple times.

### 5.3 Regime tag dual-source (M9)

Each validation year YAML row has TWO tag fields:

```yaml
- year: 2025
  manual_regime_tag: "current_market"     # Human label
  auto_classifier_tag: null               # Filled by core/diagnostics/regime_detector.py at PRD impl time
```

PRD implementation Step A.8 runs `regime_detector` on each year and fills `auto_classifier_tag`. At fail-closed validation:

- Both fields must be non-null after Step A.8 commits.
- If `manual_regime_tag != auto_classifier_tag`, PRD must include an explicit reconciliation memo entry (e.g., "manual = current_market, auto = late_cycle_bull; manual chosen because auto detector is regime-binary while we want regime-narrative").

This makes the "alternating split forces multi-regime exposure" claim defensible.

---

## 6. Design — Role-locked gates (M2 + M6 — Claude's added constraint)

### 6.1 Why role lock matters

Codex R19 + auditor agreed: 2025 hard gate applies to first active/core role; future diversifier may have role-specific exception. Claude adds 4 hard constraints to prevent abuse:

- **C1**: Roles defined in YAML pre-mining; role list immutable per `split_name`.
- **C2**: A candidate's role is assigned BEFORE the candidate enters mining; **no post-hoc reclassification** ("this failed core but I'll call it diversifier").
- **C3**: Each role-specific weakening of a gate must be paired with a compensating constraint (e.g., diversifier weak 2025 gate but stricter MaxDD AND must satisfy `vs_existing_core_correlation < 0.40`).
- **C4**: Modifying any role gate post-lock requires bumping `split_name` to a new version.

### 6.2 Roles and gates (v1 schema)

```yaml
roles:
  core:
    description: "First active/leading allocator; full gate"
    eligibility_constraint: []                      # Any candidate may apply
    validation_gates:
      - {field: "validation.2025.excess_vs_qqq", op: ">",  value: 0.0,  action: "kill_candidate"}
      - {field: "validation.2025.maxdd",         op: "<=", value: 0.20, action: "kill_candidate"}
  diversifier:
    description: "Role-locked at mining start; not a fallback for failed core"
    eligibility_constraint:
      - {field: "vs_existing_core_correlation",  op: "<",  value: 0.40}
      - {field: "vs_existing_core_overlap",      op: "<",  value: 0.30}
    validation_gates:
      - {field: "validation.2025.excess_vs_qqq", op: ">",  value: -0.05, action: "kill_candidate"}
      - {field: "validation.2025.maxdd",         op: "<=", value: 0.18,  action: "kill_candidate"}
```

(Future roles `hedge` / `satellite` deferred to v2 of the split YAML, which would require new `split_name`.)

---

## 7. Design — F1/F2 fork criteria (M7 — Claude's correction of codex's "default bias")

Codex R19 suggested defaulting to F2 unless smoke shows broad near-threshold positive evidence. Claude rejects narrative default bias; replaces with quantitative thresholds locked **before** smoke runs:

```yaml
acceptance:
  fork_criteria:
    smoke_trial_count: 100
    smoke_universe: "current_64_research_factors_unchanged"
    smoke_split_yaml: "alternating_regime_holdout_v1"
    smoke_run_command: "scripts/run_mining.py --smoke --trials 100 --split alternating_regime_holdout_v1"
    rules:
      - if:
          all:
            - {metric: "smoke.IR_p90", op: ">", value: 0.15}
            - {metric: "smoke.fraction_above_0.10", op: ">=", value: 0.20}
        then: "F1_gate_recalibration"
        new_oos_ir_threshold: "smoke.IR_p75"
        explicit_rationale_required: true
        explicit_rationale_template: |
          降 OOS IR threshold from 0.20 to {smoke.IR_p75:.3f} 因 100-trial smoke
          显示 alpha 在 (IR_p90={smoke.IR_p90:.3f}, fraction>0.10={...}%) 但当前
          阈值过严. 此校准只对 split_name='alternating_regime_holdout_v1' 有效.
      - if:
          all:
            - {metric: "smoke.IR_p90", op: "<", value: 0.05}
            - {metric: "smoke.IR_p50", op: "<", value: -0.05}
        then: "F2_new_factor_family"
        explicit_rationale_template: |
          Current 64 research factors 不足以在新 split 下产生 IR>0 alpha
          (IR_p90={smoke.IR_p90:.3f}, IR_p50={smoke.IR_p50:.3f}). 必须扩
          factor library; LLM funnel 启动条件: ...
      - else: "escalate_to_user_explicit_decision"
        memo_template: |
          Smoke ambiguous: IR_p90={smoke.IR_p90:.3f}, IR_p50={smoke.IR_p50:.3f},
          fraction>0.10={...}%. Neither F1 nor F2 trigger fired. 用户决定:
          (a) 降阈值至 IR_p75 走 F1; (b) 引入新因子家族走 F2; (c) 调整 split.
```

The fork is committed BEFORE smoke. After smoke runs, the result is compared against the rules; the chosen fork MUST be the rule-determined one (or escalate, which is also rule-determined).

---

## 8. Design — Dividend safety (M8 schema only; Track D enforces)

```yaml
acceptance:
  dividend_safety:
    enforce_at: "track_d_promotion"
    required_excess_margin_5yr: 0.04
    fallback: "must_add_dividend_correction_before_promotion"
    rationale: |
      SPY historical dividend yield ~1.3%/yr, QQQ ~0.6%/yr. 5-year cumulative
      div diff ~3.5-4%. If strategy 5y excess vs QQQ < 4%, dividend omission
      could flip the QQQ outperformance gate. Therefore a candidate must
      either (a) clear 4% margin without dividend correction, OR (b) add
      dividend correction before Track D promotion.
```

Track A only ships the schema field. Track D enforces at promotion time.

---

## 9. Full YAML schema

`config/temporal_split.yaml` skeleton (full schema; loader: `core/research/temporal_split.py`):

```yaml
schema_version: "1.0"
split_name: "alternating_regime_holdout_v1"
created_at: "2026-04-29"
locked_after_first_use: true

partition:
  reference_years:
    - {range: [2007, 2008], purpose: "crisis_reference_only", excluded_from_alpha: true}
  train_years:
    - {range: [2009, 2017]}
    - {year: 2020}
    - {year: 2022}
    - {year: 2024}
  validation_years:
    - {year: 2018, manual_regime_tag: "rate_hike_bear",       auto_classifier_tag: null, weight: 1.0}
    - {year: 2019, manual_regime_tag: "normal_bull",          auto_classifier_tag: null, weight: 1.0}
    - {year: 2021, manual_regime_tag: "liquidity_mania",      auto_classifier_tag: null, weight: 1.0}
    - {year: 2023, manual_regime_tag: "ai_narrow",            auto_classifier_tag: null, weight: 1.0}
    - {year: 2025, manual_regime_tag: "current_market",       auto_classifier_tag: null, weight: 2.0}
  stress_slices:
    - {name: "covid_flash",    start: "2020-02-15", end: "2020-04-30", source_year: 2020, mode: "stress_check_only", maxdd_threshold: 0.25}
    - {name: "rate_hike_2022", start: "2022-08-15", end: "2022-10-15", source_year: 2022, mode: "stress_check_only", maxdd_threshold: 0.25}
  sealed_test_years:
    - {year: 2026, mode: "single_shot_evaluation"}

access_rules:
  miner_may_access: ["train"]
  selector_may_access: ["train", "validation"]
  factor_warmup_may_cross_boundary: true
  factor_warmup_max_lookback_days: 504
  validation_signal_dates_must_be_in: ["validation"]
  sealed_test_access: "final_only_single_shot"

roles:
  core:        {... see §6.2}
  diversifier: {... see §6.2}

acceptance:
  validation_year_pass:
    excess_vs_spy_positive_min: 4
    excess_vs_qqq_positive_min: 3
    maxdd_per_year_max: 0.20
  stress_slice_pass:
    maxdd_per_slice_max: 0.25
  cost_robustness:
    multiplier_2x_must_remain_positive: true
  concentration:
    top1_max: 0.40
    top3_max: 0.70
    no_leveraged_etf_dependency: true
  beta:
    beta_to_qqq_max: 0.85
  purge_rules:
    label_horizon_days_max: 21
    purge_at_split_boundary: true
    embargo_days: 0
  dividend_safety:
    enforce_at: "track_d_promotion"
    required_excess_margin_5yr: 0.04
    fallback: "must_add_dividend_correction_before_promotion"
  fork_criteria:
    {... see §7}

audit:
  config_sha256_recorded_in_archive: true
  panel_max_date_recorded_per_run: true
  fail_closed_if_2026_row_in_train_panel: true
  fail_closed_if_validation_year_in_train_panel: true
  fail_closed_if_role_unspecified_at_mining_start: true
  fail_closed_if_regime_tag_missing_either_source: true
  fail_closed_if_label_crosses_split_boundary: true
  fail_closed_if_factor_lookback_exceeds_cap: true
  record_actual_max_lookback_per_candidate: true
  sealed_eval_ledger:
    enabled: true
    path: "data/research_candidates/sealed_eval_ledger.parquet"
    fields: [split_name, split_sha256, candidate_spec_sha256, git_sha, panel_max_date, evaluation_timestamp_utc, result_metrics_sha256]
    fail_closed_on_repeat:
      key: ["split_name", "candidate_spec_sha256"]
      action: "abort_with_message"
```

---

## 10. Implementation steps

| Step | Content | Estimate |
|---|---|---|
| A.1 | `config/temporal_split.yaml` schema + `core/research/temporal_split.py` pydantic v2 loader/validator (extra="forbid" on all sub-models) | 0.5 day |
| A.2 | Mining panel constructor: `core/mining/*` accepts `split_config` parameter; panel restricted to train years; emits `panel_max_date` to archive metadata | 1 day |
| A.3 | Acceptance pack wiring: per-validation-year + per-stress-slice + 2025 hard gate + role gate aggregation; output per-year + per-slice tables in candidate report | 1 day |
| A.4 | Archive metadata: `split_sha256`, `panel_max_date`, `max_factor_lookback_used`, `assigned_role` fields added; evaluator startup checks fail-closed | 0.5 day |
| A.5 | Leak-detection pytest suite: 8 tests (M1-M9 enforcement, plus role pre-mining lock, plus regime-tag dual-source, plus label-purge boundary, plus sealed-ledger repeat) | 1 day |
| A.6 | This PRD doc itself + companion `docs/memos/20260429-track_a_implementation_log.md` | 0.5 day |
| A.7 | M5 sealed-eval ledger: `core/research/sealed_ledger.py` parquet + fail-closed-on-repeat check + 4 unit tests | 0.5 day |
| A.8 | M9 regime auto-classifier integration: call `core/diagnostics/regime_detector.py` per year; fill `auto_classifier_tag` in YAML; reconciliation memo for any disagreement | 0.5 day |
| A.9 | README + CLAUDE.md + INDEX.md sync: pointer to PRD + RCMv1/Cand-2 reclassification + alternating-split chart | 0.5 day |
| A.10 | F1/F2 fork-criteria one-page memo (separate doc, locked pre-smoke); 100-trial smoke runs in Track C entry, NOT in Track A | 0.5 day (memo only; smoke runs in C) |

**Total**: ~6.5 days for Track A (PRD + impl + tests + docs sync). Smoke run is Track C entry (1 day separately).

---

## 11. Acceptance criteria

| # | Test | Verifies |
|---|---|---|
| 1 | Inject 2026 row into train panel → mining startup ABORTS with clear message | M1, audit.fail_closed_if_2026_row_in_train_panel |
| 2 | Inject 2018 (validation) row into train panel → mining startup ABORTS | M1, audit.fail_closed_if_validation_year_in_train_panel |
| 3 | Acceptance pack with validation 2019 signal date 2018-12-30 → ABORTS | M3, validation_signal_dates_must_be_in |
| 4 | 2025 single-year hard gate kills candidate that passes 2018/2019/2021/2023 but fails 2025 vs-qqq | M2 |
| 5 | Stress slice MaxDD computed independently from validation aggregation; failing stress slice but passing all 5 validation years → still kill | M1 supplement |
| 6 | YAML `split_name` v1 → v2: old archive trials remain readable; evaluator refuses to mix v1 + v2 results in same comparison | locked_after_first_use |
| 7 | No year, threshold, or role string hardcoded in Python (`grep -rn '2025\|0.20\|core' core/research/`) — all reads via loader | "config-driven" hard rule |
| 8 | 21d forward return label crossing 2025-12-20 → 2026-01-15 boundary → row dropped from 2025 evaluation set | M4 |
| 9 | Sealed-eval ledger: same `(split_name, candidate_spec_sha256)` re-evaluation → ABORTS | M5 |
| 10 | Mining startup with no role assigned in candidate spec → ABORTS | M6 C1+C2 |
| 11 | F1/F2 fork rule applied to 3 synthetic smoke distributions (high IR / flat / negative): produces F1, escalate, F2 respectively | M7 |
| 12 | `auto_classifier_tag` null after Step A.8 → ABORTS | M9 |
| 13 | Factor lookback > 504 days → factor registry rejects at registration | M3 + codex R19 #5 |
| 14 | `max_factor_lookback_used` recorded per candidate in archive | codex R19 #5 |

---

## 12. Failure modes (what each fail-closed protects against)

| Mode | Scenario | Guard |
|---|---|---|
| 2026 leakage | Mining accidentally reads 2026 panel rows | A.2 panel constructor + audit guard #1 |
| Validation contamination | Mining reads 2018/2021/2023/2025 validation row | audit guard #2 |
| Stale signal date | Acceptance evaluates signal generated outside validation year | audit guard #3 |
| Role abuse | Failed core candidate reclassified as diversifier post-hoc | M6 C1+C2 |
| Sealed test repeated use | Same candidate evaluated against 2026 multiple times to tune gate | M5 ledger |
| Fork criteria post-hoc tuning | Default-bias narrative replaces quantitative threshold | M7 schema-locked rules |
| Label boundary leakage | 21d forward return label crosses train→validation | M4 purge |
| Regime tag drift | Manual tag silently changed without auto-classifier check | M9 dual-source |
| Long lookback bypass | Factor with 1000-day lookback effectively reads 2 years of train data when generating validation signal | A.5 cap + factor registry rejection |
| Cross-split mixing | Old archive (split v1) compared with new archive (split v2) in same gate evaluation | locked_after_first_use + split_name fingerprint |

---

## 13. Open decisions / risks (for codex round 19+ review)

### 13.1 Decisions deferred to user explicit-go before implementation

| # | Decision | Claude proposal |
|---|---|---|
| D7 | Track D include forward decay detection submodule? | YES — current forward only checks data integrity, not alpha decay; needs per-TD rolling cum_ret gate |
| D8 | Dividend safety margin 5y cumulative 4%? | YES — based on SPY-QQQ div yield ~0.7%/yr × 5 = ~3.5% + buffer |

### 13.2 Risks that may surface post-implementation

| Risk | Mitigation |
|---|---|
| `regime_detector` outputs binary regime classes that don't match narrative tags (e.g., 2025 = "bull" but manual = "current_market") | Step A.8 reconciliation memo; user override allowed if rationale documented |
| 100-trial smoke too small to populate IR distribution percentiles reliably | Bump to 200 if smoke fails to converge; PRD allows `smoke_trial_count` configurable |
| Diversifier role's `vs_existing_core_correlation` requires an existing core — circular dependency | v1 schema only; v2 (post-first-core) writes new split_name with diversifier eligibility computed |
| Embargo days = 0 may be insufficient for autocorrelated returns | Recorded as `embargo_days` config option; codex may request bump in review |
| F1 fork might recalibrate gate to a level that subsequent forward TD60 quickly invalidates | Track D D.7 forward decay detector closes this loop |

### 13.3 Items that codex round 19 explicitly asked about

| Codex R19 ask | Where addressed |
|---|---|
| #1 Purged label / forward-return boundary | §5.1 + M4 + audit guard #8 |
| #2 Sealed-eval ledger | §5.2 + M5 + audit guard #9 |
| #3 2025 hard gate role-specific | §6 + M2 + M6 |
| #4 2018 validation + stress sanity-only | §4.1 + §4.3 + M1 |
| #5 504-day cap + record actual lookback | §4.2 + audit fields + test #13/#14 |
| #6 Dividend pass margin Track C/D | §8 + M8 (schema in A; enforcement in D) |
| #7 Pointer hygiene (push main) | DONE — c62b1d8 pushed before this PRD draft |

### 13.4 Items where Claude diverged from codex

| Codex R19 position | Claude position | Where written |
|---|---|---|
| "Default bias to F2 unless smoke shows broad near-threshold positive evidence" | Quantitative percentile thresholds locked pre-smoke; no narrative default bias | §7 + M7 |
| (No explicit position on dividend margin number) | 5y cumulative excess vs QQQ ≥ 4% | §8 + M8 |
| (No explicit position on regime tag double-source) | Manual tag + auto-classifier tag both required, reconciliation memo on disagreement | §5.3 + M9 |
| (No explicit position on role pre-mining lock) | Role assignment pre-mining mandatory; post-hoc reclassification fail-closed | §6.1 C1+C2 + audit guard #10 |

---

## 14. Pointers

- Roadmap (this PRD's parent): `docs/memos/20260429-post_audit_strategic_roadmap.md` v2 (commit c62b1d8 + 26ab0ff)
- Codex round 19 review: `docs/audit/20260429-codex_round_19_strategic_redirection_review.md` (origin/review/claude-collab)
- Forward evidence v2.1.3 PRD (related, not modified): `docs/prd/20260427-forward_evidence_hardening_prd.md`
- F PRD config snapshot (related, automatic pickup of this YAML): `docs/prd/20260428-config_universe_snapshot_hardening_prd.md`
- Last 0-nominee close (motivating evidence): `docs/memos/20260426-research-cycle-2026-04-26-01_close.md`
- M12 weighted thin-data (RCMv1 frozen at extreme tier — why it can't calibrate new gates): `docs/memos/20260425-m12_review_decision.md`
- Production strategy SoT (still conservative_default; Track A doesn't change it): `config/production_strategy.yaml`

---

## End of PRD

Implementation does NOT start until codex round 19+ sign-off + user explicit-go. Acceptance criteria #1-#14 must all be green before Track A is declared shipped.
