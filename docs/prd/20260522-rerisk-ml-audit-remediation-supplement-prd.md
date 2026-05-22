# Supplement PRD — Re-Risk / ML-Training Audit Remediation + Ranking-Baseline OOS Validation

**Status**: DRAFT — 2026-05-22
**Master PRD**: `docs/prd/20260521-rerisk-and-ml-training-audit-prd.md`
**Lineage**: `rerisk-ml-audit-remediation-2026-05-22`
**Relationship**: This is a **supplement** to the master PRD. Per master
§P6, a supplement is *narrower* than the master and **inherits all its
hard controls** — it may not override CLAUDE.md invariants, the master's
§9.0 / §9.6 / temporal-split discipline, or the §AUDIT-2026-05-21 block.

---

## §0 — Why this supplement exists

The master PRD's R0+P0-P6 were executed across a 33-round ralph-loop
(`docs/memos/20260521-ralph_loop_rerisk_ml_log.md`) and self-declared
complete. A post-implementation **exhaustive audit (2026-05-22)** —
PRD-conformance sweep + code-level bug sweep + real-run verification —
found the completion claim was **overclaimed**: real infrastructure was
built and tested (3923 unit tests pass), but several gates were closed
by relabelling red sub-items, two master workstreams were effectively
dropped, and one real lookahead-leak bug shipped.

Audit evidence:
- `data/audit/embargo_leak_quant_20260522T030257Z.json` — C1 leak,
  quantified.
- audit conformance + bug findings recorded in this session's report.

This supplement remediates those findings AND adds the **real
out-of-sample validation** of the ranking baseline that master §12.6
gates on. It is the prerequisite to unlocking §12.6 (deferred model
families).

---

## §1 — Audit findings being remediated

| # | finding | severity | evidence |
|---|---|---|---|
| C1 | `iter_folds` embargo trims `Timedelta(days=embargo_days)` (calendar) but the label horizon is in **trading days** → last train label's forward window reaches ~5 trading days into the val window. Quantified: inflated path-D Sharpe by **+0.11** (1.29→1.18), cum +84%→+74%, MaxDD −18.9%→−19.9%. | CRITICAL | `pipeline.py:198-209`; `embargo_leak_quant_*.json` |
| R4 | Master §10.2 mandates 16 fields on every ML artifact; `ArtifactMetadata` carries ~3. No fail-closed validator. R4 had no package — dropped. | CRITICAL | `core/research/ml/artifact.py` |
| R2 | Master §8.2 mandates `sample_weight = uniqueness × liquidity × volatility × freshness`, default-on. Grep: zero wiring. R2 had no package — dropped. | HIGH | `sign_classifier.py`, `pipeline.py` |
| D1 | `config/ml_allocation.yaml` declares sector cap / turnover cap / beta-neutral / min-edge-to-trade / 5-class exit_policy; `score_to_weight.py` implements **only** the single-name cap. `ml_labeling.yaml` declares `residualize_vs_sector: true`; `labels.py` does market residualization only. Config claims controls the code does not enforce → master P3 gate "no path can silently bypass risk caps" is false. | HIGH | `score_to_weight.py`, `labels.py:132` |
| O1 | §9.6 overfit control is statistically invalid: `walk_forward_rank_sign.py::_overfit_control` feeds per-fold rank-IC into `deflated_sharpe_ratio` as if a return series; P4 `n_trials=5` hardcoded (true search larger → under-deflates); P4 PBO sweep is 4 cosmetic re-skins of one ranker (collinear → optimistic). | HIGH | `walk_forward_rank_sign.py`, `portfolio_acceptance.py` |
| A1 | P2/P4 §12.3-named artifacts absent (`data/ml/rank_*.json`, `walk_forward_ranker_*.json`, `ml_sign_portfolio_acceptance_*.json`, `portfolio-acceptance-pack.md`); paths B/C never unified with A/D on one fold schedule. | MED | filesystem |
| V1 | All P4 evidence is on a **train-only smoke window** (2012-2017, cycle06, 3-fold). No validation/sealed-partition evidence exists. | MED | `ml_rank_portfolio_acceptance_*.json` |
| M1 | `portfolio_metrics` hardcodes 252-bar annualization; turnover-cost off-by-one bar; no NAV>0 guard. `evaluate_fold` `except Exception` masks code bugs as data-fold failures. `freeze_bundle` never hashes the model artifact. | MED | `portfolio_metrics.py`, `pipeline.py`, `freeze_ml_bundle.py` |

Authorized relaxations from `ralph_loop_rerisk_ml_prompt.md §〇` (NOT
findings): #1 IR-0.30, #3 driver-only embargo override, #5 P4 MaxDD
gate relaxed to "MaxDD < 20%". The §〇 #5 two open items (P4 gate
wording into PRD §12.3; promoted path-D config) are folded into S7.

---

## §2 — Remediation packages

Each package is small, test-first, and produces a machine-readable
artifact. Master §13 auditability applies.

### S1 — Embargo leak fix (remediates C1) — CRITICAL

Required work:
- `iter_folds` (and any driver passing `embargo_days`) must purge the
  train window by **trading-day position on the actual trading index**,
  not `Timedelta(days=...)`. The last retained train date `t` must
  satisfy: `t + horizon` trading bars `< val_start`.
- Keep `embargo_days` API but interpret it as bars, or add an explicit
  bar-based purge; document the unit.

Gate:
- a regression test proves, for horizon ∈ {5,10,21}, that the last
  retained train label's forward window ends strictly before
  `val_start` (zero overlap).
- `embargo_leak_quant.py` re-run shows the corrected path is now the
  production path (no buggy/correct delta remains).

### S2 — R4 artifact schema + fail-closed validator (remediates R4) — CRITICAL

Required work:
- Expand `ArtifactMetadata` to carry all master §10.2 fields: task
  family, source tiers, label mode, sample-weight mode, purge/embargo
  params, context bundle, training universe, model family, objective,
  score-to-weight mode, exit-policy mode, reuse flag, benchmark-relative
  eval, portfolio-acceptance path, config hash, trial count + DSR + PBO.
  Portfolio artifacts additionally: target-weight mode, risk-scaling
  mode, constraint-set id, cost-model id, execution-assumption id.
- A fail-closed validator: a missing mandated field raises; promotion
  is refused.
- Thread the fields through the rank / sign drivers + acceptance
  harness so emitted artifacts populate them.

Gate:
- every ML artifact JSON written by a driver carries the full §10.2
  field set; a test feeds a metadata dict missing one field and asserts
  the validator raises.

### S3 — R2 sample-weighting (remediates R2) — HIGH

Required work:
- Implement the canonical multiplicative
  `sample_weight = uniqueness × liquidity × volatility × freshness`
  (master §8.2); reuse `core/ml/labeling.py` uniqueness primitives.
- Default-on in the Stage-2 sign-classifier and the rank training
  path; disabling requires an explicit flag (master §8.3).
- Record the §8.4 weighting-auditability fields in the artifact (via S2
  schema).

Gate:
- weighting is active by default; a test confirms disabling needs the
  explicit flag; the artifact records the weighting mode + component
  summary.

### S4 — Config-vs-code drift resolution (remediates D1) — HIGH

Required work:
- For EVERY control declared in `config/ml_allocation.yaml` (sector
  cap, turnover cap, beta-neutral, min-edge-to-trade, exit_policy) and
  `config/ml_labeling.yaml` (`residualize_vs_sector`): EITHER implement
  an enforcing code path, OR delete the unbacked declaration from the
  config. **No config may declare a control the code does not enforce.**
- Recommended: implement `min_edge_to_trade` + turnover cap +
  `exit_policy` (load-bearing for real money); for sector-neutral /
  beta-neutral, either implement or explicitly mark `enabled: false`
  with a roadmap note.

Gate:
- a test cross-checks every config-declared control against an
  enforcing code path (or an explicit `enabled: false`); master P3
  gate "no path can silently bypass risk caps" becomes literally true.

### S5 — §9.6 overfit-control correctness (remediates O1) — HIGH

Required work:
- DSR must consume an actual portfolio **return series**, never
  rank-IC. Where rank-IC significance is wanted, use a rank-IC t-stat
  with the proper N.
- `n_trials` must come from a persisted trial ledger (count of model /
  hyperparameter / config variations actually examined), not a CLI
  default.
- PBO must run over genuinely independent trial configs (distinct
  feature sets / seeds / hyperparameters), not cosmetic overlays of one
  ranker.

Gate:
- DSR/PBO inputs are valid by construction; a memo documents the trial
  ledger; the freeze-bundle gate checks the overfit_control is *valid*,
  not merely present.

### S6 — Ranking-baseline real-OOS validation (the §12.6 unlock) — HIGH

Required work:
- Run the P4 path-D portfolio acceptance on the **validation
  partition** — train on `train_years` (2009-2017, 2020, 2022, 2024),
  evaluate on `validation_years` (2018, 2019, 2021, 2023, 2025) per
  `config/temporal_split.yaml`. Sealed-2026 stays untouched.
- Use the S1-fixed embargo, S2 artifact schema, S3 weighting, S5
  overfit control.
- Report per-validation-year net Sharpe / MaxDD / vs-SPY excess +
  stress-slice MaxDD (covid_flash, rate_hike_2022).

Gate (this is the gate master §12.6 keys off):
- on the validation partition, path-D net Sharpe beats the non-ML
  baseline AND per-validation-year MaxDD ≤ 20 % AND stress-slice
  MaxDD ≤ 25 %;
- the edge survives a *valid* DSR deflation + PBO (per S5);
- the result is a checked-in machine-readable artifact.

### S7 — Named-artifact + 4-path gaps + open items (remediates A1) — MED

Required work:
- Persist ranker artifacts (`data/ml/rank_*.json` /
  `walk_forward_ranker_*.json`) and the P4-named outputs
  (`ml_sign_portfolio_acceptance_*.json`, `portfolio-acceptance-pack.md`).
- Unify paths A / B / C / D in one acceptance harness on one
  walk-forward fold schedule.
- Resolve the §〇 #5 open items: fold the relaxed P4 MaxDD gate wording
  into master PRD §9.3 / §12.3; record the promoted path-D config
  (plain vs vol-target).
- Address M1 hygiene: `portfolio_metrics` `periods_per_year` param +
  turnover-cost bar alignment + NAV>0 guard; `evaluate_fold`
  distinguish code bugs from data-fold failures; `freeze_bundle` hash
  the model artifact.

Gate:
- the master §12.3 P2/P4 named outputs exist and are checked in; the
  4-path comparison runs on identical slices.

---

## §3 — §12.6 unlock condition

Master §12.6 deferred model families (`TCN/CNN/LSTM`,
`PatchTST/iTransformer`, `MAE`, `GNN`, `RL`) **may enter implementation
scope only when**:

1. S1–S6 hard gates are all green, AND
2. S6 shows the ranking baseline genuinely passes on the **validation
   partition** (not a train-only smoke window).

Until both hold, §12.6 stays **roadmap-only** — exactly as master §12.6
and §13.1 require ("not until the ranking baseline passes" / "a
validated ranking-baseline-to-portfolio path"). This supplement does
NOT authorize §12.6 implementation.

---

## §4 — Execution order

```
S1  (embargo leak — everything downstream is contaminated without it)
S2  (artifact schema — needed before any artifact is trustworthy)
S4  (config-vs-code drift — stop the config from lying)
S5  (overfit-control correctness)
S3  (sample-weighting)
S7  (named artifacts + 4-path + hygiene)
S6  (real-OOS validation — consumes S1/S2/S3/S5; the §12.6 unlock)
```

No package may claim completion while an earlier one's hard gate is
red (master §12.4 rule, applied honestly — a red sub-item is failed,
not relabelled).

---

## §5 — Auditability

Inherits master §13 verbatim: every decision a machine-readable
artifact; config provenance; one checked-in reproduce command; negative
verdicts preserved; no notebook-only state. Additionally — and as
direct correction of the audit finding — **a package is "closed" only
when its literal gate criterion is met; a red sub-item is reported as
red, never reclassified as "forward-looking" or "follow-up".**
