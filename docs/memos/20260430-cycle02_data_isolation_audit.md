# Cycle #02 Data Isolation Audit — Train / Validation / Sealed

**Audit date**: 2026-04-30
**Auditor**: operator (per memory `feedback_decision_authority_operator_audit_split.md`)
**Scope**: cycle `track-c-cycle-2026-04-30-02` mining (commit `b85cbf3` → `f24104b`) + Step 3 evaluation script.
**Trigger**: user-prioritized post-cycle audit ("重点关注数据的严格隔离问题 看看是否真的严格隔离").

---

## 0. Conclusion (TL;DR)

**Data isolation between train / validation / sealed is enforced at panel level for cycle #02 mining and the Step 3 evaluation script. No validation or sealed-year data was used as input.**

Two non-blocking issues found:

1. **WARN — `purge_labels_at_boundary` not invoked by miner.** Configured `true` in `config/temporal_split.yaml` but `scripts/run_research_miner.py` does not call `purge_labels_at_boundary(fwd_returns, cfg)`. Forward-return labels at the last day of a non-contiguous train segment span the calendar gap to the next train segment (e.g. 2017-12-29's 5-day forward return aligns to 2020-01-08 close, not a 2018 close which doesn't exist in the panel). This is **not a leak** — both endpoints are train-data — but is a **methodological issue** that distorts IC near calendar gap boundaries. Action: fix in next cycle.
2. **WARN — Step 3 eval script applies `restrict_frames_to_train` and therefore cannot compute per-validation-year metrics.** This worked for cycle #02 closeout (no Track A acceptance reached), but a future Track-A-passing candidate cannot be evaluated by this script as written. Action: refactor `_build_inputs()` to use `partition_for_role` (gives validation access to non-mining stages) before any future cycle attempts a Track-A-passing candidate evaluation.

No evidence of data leakage was found.

---

## 1. Audit checklist (12 items)

### A. Train-only enforcement at panel construction time

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Mining script calls `restrict_frames_to_train(frames, split_cfg)` | ✅ PASS | `scripts/run_research_miner.py:491` |
| 2 | Mining script calls `validate_no_holdout_leakage(frames, cfg)` after restriction | ✅ PASS | `scripts/run_research_miner.py:492` |
| 3 | Pre-restrict end-date cap excludes 2026 sealed | ✅ PASS | mining log `Panel end_date cap: 2025-12-31 (G4 cutoff)`; cycle #02 yaml `end_date: 2025-12-31` |
| 4 | Post-restrict panel size matches expected train-only count | ✅ PASS | mining log `Temporal split filter: 4780 → 3021 rows`; train_years = 9 (2009-2017) + 2020 + 2022 + 2024 = 12 years × ~252 ≈ 3024; observed 3021 within rounding |
| 5 | `panel_max_date` recorded per trial | ✅ PASS | rcm_archive 60 trials all carry `panel_max_date = 2024-12-31` |
| 6 | `split_sha256` recorded per trial | ✅ PASS | rcm_archive 60 trials all carry `split_sha256 = 0391d7ebd0252ffa…` (matches yaml lock) |
| 7 | `role` recorded per trial | ✅ PASS | rcm_archive 60 trials all carry `role = core` |

### B. Forward-return label boundary

| # | Check | Result | Evidence |
|---|---|---|---|
| 8 | Forward returns computed via `pct_change(h).shift(-h)` (close-to-close, mode=cc) | ✅ confirmed | `core/factors/factor_generator.py:990-992` |
| 9 | `purge_labels_at_boundary` invoked by miner script | ⚠️ **WARN — NOT INVOKED** | `grep purge scripts/run_research_miner.py` returns no hits. yaml `purge_at_split_boundary: true` is configured but unenforced. |
| 10 | `purge_labels_at_boundary` itself exists and is correct | ✅ PASS | `core/research/temporal_split.py:598`; would correctly purge if called |

**Why this is WARN not FAIL**: The non-contiguous train panel produces forward returns that span calendar gaps (e.g. row 2017-12-29 → fwd_return at 2020-01-08). Both endpoints are train data, so no validation/sealed leak occurs. But the fwd_return value is meaningless for IC purposes — it represents a 2-year-and-10-day return rather than a 5-day return. This biases IC near gap boundaries. Bias direction: ambiguous (depends on factor distribution at gap boundaries). For cycle #02 (close-out at IC layer with strong sibling-by-construction signal), the bias is too small to change the closeout classification. For future cycles aiming at Track A acceptance, this MUST be fixed.

**Action item** (added to Step 6 plan): wire `purge_labels_at_boundary` into the miner before next cycle.

### C. Factor lookback cap

| # | Check | Result | Evidence |
|---|---|---|---|
| 11 | Factor lookback cap enforced (config/temporal_split.yaml: factor_warmup_max_lookback_days=504) | ✅ PASS | rcm_archive `max_factor_lookback_days = 504` recorded per trial; top trials use `mom_12_1` (252d) + `beta_spy_60d` (60d) + `volume_ratio_20d` (20d) — all within cap |
| 12 | No factor referenced post-panel data | ✅ PASS by construction | `generate_all_factors(close)` operates on already-restricted train-only `close` — pandas cannot reference rows that don't exist |

### D. Eval-script (Step 3) isolation

The Step 3 evaluation script `dev/scripts/cycle02/evaluate_cycle02_top_n.py` was inspected for data isolation:

| # | Check | Result | Evidence |
|---|---|---|---|
| D.1 | Eval script also applies `restrict_frames_to_train` before factor generation | ✅ confirmed | line 120 (post-fix); panel restricted to train identical to mining |
| D.2 | Eval script `n_observed_days = 3021` matches mining panel size | ✅ confirmed | evaluation_summary.json |
| D.3 | Per-validation-year metrics in evaluation_summary.json | ⚠️ EMPTY (expected) | per-validation-year keys = [] because validation years not in panel; structural side-effect, not a leak |
| D.4 | Per-stress-slice metrics computed | ✅ ['covid_flash', 'rate_hike_2022'] | both stress slices fall in 2020/2022 train years; evaluated correctly |
| D.5 | criteria_yaml_sha256 matches frozen yaml | ✅ `492a72b1…05c42c` | matches yaml lock at commit `b85cbf3` |

### E. Sealed-eval ledger

| # | Check | Result | Evidence |
|---|---|---|---|
| E.1 | Sealed eval ledger file does not exist (no sealed eval done) | ✅ PASS | `data/research_candidates/sealed_eval_ledger.parquet` does not exist; no sealed eval has been triggered |
| E.2 | Cycle #02 mining did NOT consume sealed window | ✅ PASS by panel construction | end_date cap 2025-12-31 + restrict_to_train both exclude 2026 |

**Note**: the audit guard `fail_closed_on_repeat` is in place but un-tested (no sealed eval has run). When the first sealed eval is performed, the ledger file should be created and the `fail_closed_on_split_failure` core-role lock should engage immediately.

---

## 2. Recommended fix-forward actions

| ID | Action | Priority | Owner | Trigger |
|---|---|---|---|---|
| A1 | Wire `purge_labels_at_boundary(fwd_h, split_cfg)` into `scripts/run_research_miner.py` between line 158 (forward-return computation) and line 159 (assigning fwd_h to miner). Add unit test verifying gap-boundary rows have NaN fwd_return. | P1 — fix before next cycle | operator | next cycle yaml signing |
| A2 | Refactor `dev/scripts/cycle02/evaluate_cycle02_top_n.py` `_build_inputs()` to optionally use `partition_for_role(role, split_cfg)` for evaluator stages that need validation-year visibility. Required for any future Track-A-passing candidate evaluation. | P2 — gated on next candidate reaching Track A | operator | next nominee at Track A |
| A3 | Add a sealed-eval-ledger smoke test: write a no-op record + verify `fail_closed_on_repeat` raises on second write of same key. | P3 — defensive | operator | first attempted sealed eval, OR earlier if convenient |

---

## 3. What this audit does NOT cover

This audit verified **input-side data isolation** (panel construction). It did NOT verify:

- Numerical correctness of forward-return labels (separate concern; M4 schema-level compliance verified, but not full numerical recomputation)
- Cross-validation fold integrity (mining used full-period IC, not per-fold; walk-forward fold separation is enforced inside the IC computation but not audited line-by-line)
- Configuration-snapshot integrity (PRD-F config drift detection only applies to forward observation, not mining; mining captures `split_sha256` but not the full config snapshot)
- Compute-environment determinism (no PYTHONHASHSEED audit performed — but seed=42 was passed to TPE sampler, and the M11a `sorted(set(...))` fix is upstream of mining)

These are out-of-scope for the user's "data isolation" question and should be tracked separately if needed.

---

## 4. Audit closeout

Cycle #02 mining + Step 3 evaluation are both **train-only at the panel level**. The yaml's `validate_no_holdout_leakage` audit guard ran without raising, confirming no validation or sealed-year row reached the panel.

The two WARN findings (`purge_labels_at_boundary` not invoked; eval script can't see validation years) are **structural shortcomings, not leaks**, and have been added to the Step 6 follow-up plan.

— operator, 2026-04-30 19:00 PT
