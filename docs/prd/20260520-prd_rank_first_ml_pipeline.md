# PRD: Rank-First ML Model Training Pipeline (Cross-Sectional + Sign-Vote Sidecar)

**Status**: DRAFT v1
**Author**: operator (Claude Opus 4.7), per user request 2026-05-20
**Triggered by**: auditor methodology suggestion 2026-05-20 + PRD-X
v2 §9.0 post-fix constraint + classifier_voter wiring in
`core/research/decision/ml_voters.py` (built but not yet wired to a
real model)
**Estimated work**: 3-4 work cycles
**Distinct from**: PRD-X v2 implementation loop (DONE); PRD
trigger-first canonical promotion (separate track)

---

## 1. Goal

Replace the `weak_factor_filter` heuristic voter with a **trained
ML model output** that respects §9.0 post-fix invariant:
ML produces DISCRETE outputs (rank score → sign-vote), **never
continuous magnitude as size weight**.

Two-stage architecture per auditor 2026-05-20 methodology + Gu-Kelly-
Xiu (Empirical Asset Pricing via Machine Learning, 2020) + the
learning-to-rank literature (e.g. Building Cross-Sectional
Systematic Strategies by Learning to Rank, Zhang et al.):

```
Stage 1 (RANK):   cross-sectional ranking / percentile score per
                  bar. Output ∈ [0, 1] interpretable as "this
                  symbol's relative attractiveness at this bar."
Stage 2 (SIGN):   binary classifier on TOP-decile of Stage 1 →
                  VETO / NO_VOTE / CONFIRM SignVote. This is the
                  sidecar overlay the system already supports.
```

Stage 1 output IS NOT used directly as a size weight (per §9.0).
Stage 2 output IS used as a binary gate. The size comes from the
rule-based policy (`base_position_size * strength` in the rule-
based path, or from MultiFactorStrategy weights in the overlay path).

## 2. Out-of-scope

- Replacing rule-based DecisionPolicy entirely (architecture decision
  separate from ML)
- Deep learning / sequence models (Stage 1 may use tabular methods
  like XGB / LightGBM / linear baseline; LSTM/Transformer is a v2
  decision)
- Multi-asset alpha (this PRD is single-name equities; cross-asset
  diversifier role is separate)
- Real-time inference / latency optimization (research / paper /
  backtest cycle only for this PRD)

## 3. Phases

### P4.1 — Cross-sectional ranking model (Stage 1)

**Goal**: train a model that predicts cross-sectional rank /
percentile of forward returns per bar, from a feature vector built
per-symbol-per-bar.

**Method**:
- Use existing 113-factor research panel from cycle06 pipeline
  (`core/factors/factor_generator.generate_all_factors`) as feature
  source
- Target: `(forward_return - cross_sectional_mean) / cross_sectional_std`
  ranked to percentile [0, 1] (avoids absolute return bias)
- Model class options (operator preference XGB classifier per §9.0
  guidance):
  - `XGBRegressor` predicting rank (1d output)
  - `XGBRanker` (rank objective, formally learning-to-rank)
  - `LightGBM` ranker (faster training)
  - Linear baseline (Pareto floor)

**Training discipline (mandatory)**:
- Strict-chronological walk-forward training (per Track-A R1
  temporal-leakage discipline)
- Per-fold rolling window (e.g. train on 2008-2017, validate 2018,
  retrain 2008-2018, validate 2019, ...)
- Sealed 2026 永不读
- Cross-sectional standardization per bar BEFORE feature
  ingestion (avoids absolute-magnitude information leakage)

**Deliverables**:
- `core/research/ml/rank_model.py` with `RankModel` class
- `dev/scripts/ml/train_rank_model.py` training driver
- Model artifact at `data/ml/rank_model_<lineage_tag>.pkl`
- Walk-forward fold metrics: per-fold rank-IC, rank-IR

**AC**:
- ✅ Mean rank-IC > 0.02 across folds (rank-based, not raw-IC poison)
- ✅ Rank-IR > 0.30 (Grinold-Kahn-equivalent for ranking)
- ✅ No leakage: per-bar standardization confirmed; no future data
   in features
- ✅ Reproducible: fixed seed + version artifact
- 🟡 Non-blanket failure: if rank-IC < 0.02, record per-fold
   verdict + root-cause, don't declare "ML doesn't work"

**Estimated effort**: 1.5 cycles.

### P4.2 — Sign-vote binary classifier (Stage 2)

**Goal**: a binary classifier {VETO, NO_VOTE} per §9.0 post-fix
invariant. Input: Stage 1 rank score + context features (regime, vol,
multi-TF). Output: SignVote enum.

**Method**:
- Train on top-decile of Stage 1 rank per bar (the entry-eligible
  candidate set per rule-based policy)
- Target: was the entry a winner (forward 21-day return > 0) or
  loser (≤ 0)?
- Model class: `XGBClassifier(num_class=2)` or `LogisticRegression`
  baseline
- Output mapping: predicted class 0 → VETO, class 1 → NO_VOTE
  (asymmetric, conservative per `binary_classifier_voter` already
  in `core/research/decision/ml_voters.py`)
- Optional 3-class variant: -1 / 0 / +1 → VETO / NO_VOTE / CONFIRM
  using `classifier_voter`

**Discipline**:
- Trained on Stage-1-output decile → reproduces ARMED-set selection
- Per §9.0: classifier MUST output discrete labels; runtime
  enforcement already in `MLSidecarPolicy.vote()` (TypeError on
  non-SignVote return)
- Walk-forward retraining cadence (e.g. quarterly)

**Deliverables**:
- `core/research/ml/sign_classifier.py` with `SignClassifier` class
- `dev/scripts/ml/train_sign_classifier.py` training driver
- Model artifact at `data/ml/sign_classifier_<lineage_tag>.pkl`
- Walk-forward fold metrics: precision, recall, F1 on VETO class

**AC**:
- ✅ Walk-forward F1(VETO) > F1(NO_VOTE-baseline = always abstain)
- ✅ Precision(VETO) > 0.55 (VETOs should be mostly correct losers)
- ✅ Output is SignVote enum (runtime invariant; existing
   `MLSidecarPolicy.vote()` enforces TypeError on non-SignVote)
- 🟡 Non-blanket: if F1 ≤ baseline, record per-fold verdict

**Estimated effort**: 1 cycle.

### P4.3 — Multi-TF context features (optional but recommended)

Per auditor 2026-05-20 + CLAUDE.md multi-TF framework:
- Daily context features: regime state, 252d trend, SPY drawdown
- Intraday context features: 60m / 30m / 15m timing signals (already
  in `core/intraday/`)
- Overnight gap / open-range features

Add to both Stage 1 and Stage 2 feature vectors. **No specific TF
combination is mandated** — the PRD explicitly leaves cadence to
research choice per the auditor's note that "15m→30m is not
established academic standard."

Optional structures to try in P4.5 acceptance experiments:
- daily context + monthly rebalance (R10/R12/R16 baseline)
- daily context + weekly trigger
- 60m context + 30m setup + 15m execution (more aggressive)

**AC**:
- ✅ Feature ablation: rank-IC delta when adding multi-TF context
   features recorded per ablation run

**Estimated effort**: 0.5 cycle (feature engineering only;
acceptance is folded into P4.5).

### P4.4 — Training pipeline + temporal-split + artifact persistence

**Goal**: a reproducible pipeline that:
- Loads features (post-X0 TR panel, sealed-2026 守)
- Per-fold trains Stage 1 + Stage 2
- Persists artifacts with deterministic spec_id + lineage_tag

**Deliverables**:
- `core/research/ml/pipeline.py` orchestrating the full train/eval
- `core/research/ml/artifact.py` for save/load (pickle + metadata
  JSON)
- Walk-forward driver: `dev/scripts/ml/walk_forward_rank_sign.py`

**Discipline**:
- Per `feedback_temporal_split_discipline`: strict-chronological,
  no interleaved partition
- Per `feedback_websearch_sealed_data_discipline`: no current-year
  market data in features
- Audit trail: each artifact has metadata (training window, feature
  list, hyperparams, fold metrics)

**AC**:
- ✅ Pipeline reproducible from seed + config
- ✅ Artifacts loadable by `classifier_voter()` /
   `binary_classifier_voter()` from `ml_voters.py`
- ✅ No future data leakage (cross-bar standardization audited)

**Estimated effort**: 1 cycle.

### P4.5 — Acceptance experiments + production integration

**Goal**: prove the trained models beat heuristics in the existing
PRD-X stack.

**Experiments**:
- **R-ML-A**: trigger-first stack + `weak_factor_filter_voter`
  (R10 baseline reproduce)
- **R-ML-B**: trigger-first stack + trained `classifier_voter`
  (Stage 2 only, Stage 1 used to gate candidate set)
- **R-ML-C**: trigger-first stack + Stage 1 rank score as
  `factor_score` input to `FactorEntryTrigger` + trained Stage 2
  classifier
- **R-ML-D**: cap_aware harness (R16 Path A) + trained ML overlay

**Comparison metrics**:
- cum_ret / Sharpe / MaxDD / turnover (R10/R14/R16 framework)
- vs SPY excess
- §6.4 invariant compliance per-year MaxDD
- §9.0 invariant: outputs verified discrete

**Voter integration**:
- `config/production_strategy.yaml::decision_stack.ml_sidecar.voter_kind
  = "classifier_voter"`
- `voter_params.model_path = "data/ml/sign_classifier_<lineage>.pkl"`
- `voter_params.feature_extractor = "rank_score_and_context"`
- Extend `_resolve_voter_from_config()` in `scripts/run_backtest.py`
  to support classifier loading from artifact path (currently raises
  ValueError with hint — auditor F8 closure leaves this as
  "explicit wiring required")

**AC**:
- ✅ At least one of R-ML-B/C/D beats R-ML-A on Sharpe AND MaxDD
- ✅ §9.0 invariant verified: ML output never magnitude scaler
- ✅ Reproducible via seeded pipeline
- 🟡 Non-blanket: if NONE of B/C/D beats A, record FAIL with root
   cause (e.g. "heuristic was already at noise ceiling" /
   "feature engineering didn't add signal")

**Estimated effort**: 1 cycle (driver + 4 paths + verdict).

## 4. Dependencies

- PRD-X v2 implementation loop ✅ (modules + voter wiring shipped)
- `core/research/decision/ml_voters.py` ✅ (4 voter factories exist)
- `core/research/decision/ml_sidecar.py` ✅ (§9.0 runtime enforced)
- `core/factors/factor_generator.py` ✅ (113-factor panel available)
- Temporal-split discipline ✅
- 训练计算资源: 单 GPU 串行 (per `feedback_heavy_training_serial_wsl`)

## 5. Risks

1. **Magnitude-IC poisoning** (from
   `docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md`):
   3-model-class A/B FORCED universal poison was the post-fix
   conclusion. **Mitigation**: PRD enforces RANK-based output for
   Stage 1 (not magnitude prediction) and SIGN-based binary
   classifier for Stage 2. §9.0 runtime check on Stage 2 output is
   the runtime safety net.
2. **OOS rank-IC ≤ 0**: training noise. **Mitigation**: walk-
   forward per-fold transparency, non-blanket failure verdict, fall
   back to heuristic voter.
3. **Multi-TF feature data integrity**: per `feedback_bar_level_data_integrity_smoke`
   the multi-TF features must pass bar-integrity smoke (weekend rows
   / monotone / sealed-year guard). **Mitigation**: smoke test in
   P4.4 pipeline pre-train hook.
4. **§6.4 invariant indirectly broken**: trained classifier might
   recommend a high-MaxDD allocation by accident (e.g. high-vol
   universe). **Mitigation**: §6.4 6-layer guard already runtime-
   enforces (`ActionDecision`, `EntryEvent`, `RuleBasedDecisionPolicy`,
   `DeferredExecutionAdapter`, `PartialRebalancePolicy`,
   `MLSidecarPolicy`); ML can't override invariants at any layer.
5. **§9.0 violation accidentally**: a developer wires a regressor
   that returns float. **Mitigation**: `MLSidecarPolicy.vote()`
   raises TypeError if vote_fn returns non-SignVote — runtime
   safety net.

## 6. Anti-goals (explicit)

- NOT predict "absolute market direction" (cross-sectional
  ranking only)
- NOT predict "position size" (size from rule-based or overlay
  upstream; ML is gate not sizer)
- NOT use continuous magnitude scores as weight (§9.0 hard禁)
- NOT deep learning v1 (start with tabular; LSTM/Transformer is v2
  decision)
- NOT bypass §6.4 invariants (ML overlay is sidecar not core)
- NOT replace rule-based DecisionPolicy as primary alpha (this PRD
  layers on top of existing rule-based path)

## 7. Estimated total work

**3-4 work cycles**:
- P4.1 Stage 1 rank model: 1.5 cycles
- P4.2 Stage 2 sign classifier: 1 cycle
- P4.3 Multi-TF features: 0.5 cycle
- P4.4 Pipeline + artifact: 1 cycle
- P4.5 Acceptance experiments + integration: 1 cycle

Total ≈ 5 cycles. Can compress to 3 cycles if Stage 1 + Stage 2 are
trained in parallel after feature pipeline (P4.4) is shipped.

## 8. References

**Internal**:
- PRD-X v2 main: `docs/prd/20260519-trigger_threshold_first_rebalance_architecture.md`
- Post-fix REVISION: `docs/memos/20260519-strategic_close_out_REVISION_post_audit_fix.md`
- ml_voters wiring: `core/research/decision/ml_voters.py`
- ml_sidecar runtime gate: `core/research/decision/ml_sidecar.py`
- Temporal-split discipline: `core/research/temporal_split.py` +
  `feedback_temporal_split_discipline` memory

**External (auditor 2026-05-20 + operator extension)**:
- Gu, Kelly, Xiu (2020) "Empirical Asset Pricing via Machine
  Learning" — establishes tabular ML for cross-sectional return
  prediction, with the rank-IC framing this PRD inherits
- Zhang et al. "Building Cross-Sectional Systematic Strategies by
  Learning to Rank" — direct learning-to-rank application for
  stock selection
- Alekseenko et al. "Empirical Asset Pricing via Learning-to-Rank"
  — pairwise/listwise ranking objectives
- Lopez de Prado (2018) "Advances in Financial Machine Learning" —
  triple-barrier labeling + meta-labeling (Stage 2's binary-classifier
  framing matches this pattern)
- Multi-TF framework (auditor 2026-05-20): higher-TF context
  filter + lower-TF execution timing — used as feature design
  guidance in P4.3, not as fixed cadence

## 9. DONE condition

P4.5 acceptance experiments produce at least one ML-driven path
that beats the heuristic baseline on Sharpe AND MaxDD on the
canonical 2018-2024 strict-chronological window, with:
- §9.0 sign-vote invariant verified
- Walk-forward rank-IC > 0.02 + F1(VETO) > baseline
- Reproducible artifact lineage
- Voter wired into config schema (`voter_kind: "classifier_voter"`
  loadable)

At that point the rank-first ML pipeline is **research-validated**.
Production integration (status flip to active using ML overlay)
follows via the **separate** trigger-first canonical promotion
PRD (`docs/prd/20260520-prd_trigger_first_canonical_promotion.md`).

## 10. Honest staging note

This PRD is the **research / training pipeline**, NOT the
production deployment. Even after P4.5 PASS, deploying
classifier_voter into live trading requires:
- Stable artifact lineage + version control (no model drift)
- Retraining cadence + alignment-check discipline
- Monitoring (rank-IC drift, classifier calibration drift)
- The trigger-first canonical promotion PRD's P3.2 walk-forward +
  P3.3 alignment + P3.6 M2 promote sequence with this ML config
  baked in

Per `feedback_audit_surfaces_not_thorough`: "training a model" ≠
"production deployment." This PRD covers the former.
