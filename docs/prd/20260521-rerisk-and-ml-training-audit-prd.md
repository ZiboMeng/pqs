# PRD — Re-Risk First, Then ML Training Framework Hardening

Status: DRAFT (audited + revised 2026-05-21)  
Date: 2026-05-21  
Owner: audit / quant-research  
Lineage: `rerisk-and-ml-training-audit-2026-05-21`

> **Revision note (2026-05-21, dev-lead audit pass).** This PRD was
> independently re-audited against the live codebase. Four issues were
> folded back into the document rather than left as review comments:
> (1) the PRD did not reconcile with the pre-existing PRD #4 rank-first
> pipeline — see new §1.5; (2) the §2.1 baseline evidence was sourced
> from an ephemeral `/tmp` path with no stated window — §2.1 now carries
> the caveat + a regime-conditional correction; (3) Workstream R0 did
> not specify temporal-split discipline — see new §6.5; (4) the
> acceptance spec named no overfit-significance machinery (DSR / PBO /
> CPCV) although the repo already ships it — see new §9.6. Search the
> string `AUDIT-2026-05-21` for every inserted/edited block.

## 0. Why This PRD Exists

User ask on 2026-05-21:

1. Re-run the risk / MaxDD audit on the current project after the recent bug fixes.
2. Audit the ML training framework end-to-end and produce a detailed, implementable, auditable report / PRD.

This PRD answers two questions:

1. What should we do next: `MaxDD re-test`, `new alpha mining`, or `training framework hardening`?
2. What exact implementation plan would make the training pipeline and post-signal construction path trustworthy enough for future mining?

Short answer:

- `alpha mining` is **not** the next best action.
- The next sequence is:
  1. `re-risk / MaxDD re-test`
  2. `ML training framework hardening`
  3. only then `new alpha mining`

The reason is simple: the current production baseline still loses money badly after the recent fixes, while the current Stage-2 ML classifier still fails its own held-out precision gate.

This PRD should also be read with one additional principle:

- the project should choose model families from the trading task backward, not from model novelty forward
- the first production ML route should be a strong tabular ranking baseline, not an immediate jump to Transformer / RL / end-to-end deep trading

## 1. Decision Summary

### 1.1 Binding decision

The project should **not** start a new alpha-mining round yet.

The next work should be:

1. `R0` — finish the re-risk pack on current live / evidence candidates and baseline.
2. `R1-R4` — harden the ML training and evaluation chain so it is leakage-correct, cost-aware, and portfolio-aware.
3. `R5` — only after R0-R4 pass, start a fresh mining cycle on the hardened stack.

### 1.2 Why this decision is binding

Because the evidence says:

- The current baseline is still deeply broken after the fixes:
  - `CAGR -4.49%`
  - `MaxDD -63.95%`
  - `IR -0.38`
  - severe underperformance in `BULL` regime  
  Source: [/tmp/pqs_audit_afterfix/backtest/runs/20260521_135818_backtest/master_report.md](/tmp/pqs_audit_afterfix/backtest/runs/20260521_135818_backtest/master_report.md:10)

- The current Stage-2 walk-forward sign classifier still fails its own gate:
  - `10/10 folds successful`
  - `mean val precision(VETO) = 0.3816`
  - required threshold = `0.55`
  - verdict = `FAIL`  
  Source: [data/audit/r32_walkforward_sign_xgb_20260521T210059Z.json](/home/zibo/Documents/projects/pqs/data/audit/r32_walkforward_sign_xgb_20260521T210059Z.json:257)

That means the system is not blocked by “lack of more ideas”. It is blocked by:

- incorrect or insufficiently hardened portfolio-risk translation
- incomplete ML evaluation discipline
- weak linkage between model outputs and portfolio construction decisions

## 1.3 Model-family decision

The default model roadmap in this repository should be:

1. `GBDT ranking baseline` for daily cross-sectional stock selection
2. `GBDT + cost-aware portfolio construction` as first production candidate
3. `sequence models` only as incremental ensemble once the GBDT baseline proves stable OOS
4. `MAE / self-supervised pretraining` only as representation learning support
5. `RL` only for sizing / execution overlays after alpha is already stable

Explicit non-goals for the next phase:

- no “Transformer first” production rewrite
- no RL-based direct alpha discovery
- no deep model promotion based only on predictive metrics without portfolio-level acceptance

## 1.4 Current implementation reality check

This PRD must follow the current repository reality, not an abstract greenfield design:

- the repo already has a native `XGBoost` cross-sectional ranking implementation with `qid` grouping:
  - `core/ml/xgb_ranking.py`
- the repo did **not** have a real `LightGBM` training path wired in the active stack at audit start
- `LightGBM` is now installed in the current audit environment via the repo's `research` optional dependency, so dependency availability is no longer the blocker; implementation wiring is
- the repo already has one portfolio acceptance script for ML sidecar A/B:
  - `dev/scripts/ml/r29_acceptance_r_ml_a_vs_b.py`
- the repo already has a minimal `config/ml_labeling.yaml`, but it is still too narrow for production-grade task / label governance
- several temporal split configs still ship `embargo_days: 0`, which is too weak as the default for overlapping-horizon financial labels

Therefore:

- the immediate production-baseline implementation should be `XGBoost ranking first`
- `LightGBM` should be written in the PRD as an optional later parity target, not the first mandatory dependency
- the acceptance path should evolve from existing A/B scripts where possible, not be rebuilt from zero unless the current harness is insufficient

## 1.5 Relationship to PRD #4 (rank-first ML pipeline) — `AUDIT-2026-05-21`

This PRD is **not greenfield**. A prior PRD already built a rank-first
two-stage ML pipeline and must be treated as this PRD's input, not
re-implemented:

- `docs/prd/20260520-prd_rank_first_ml_pipeline.md` (PRD #4) delivered:
  - P4.1 — `core/research/ml/rank_model.py` (Stage-1 cross-sectional RANK)
  - P4.2 — `core/research/ml/sign_classifier.py` (Stage-2 sign vote)
  - P4.3 — multi-TF context bundles
  - P4.4 — `dev/scripts/ml/walk_forward_rank_sign.py` (walk-forward driver)
  - P4.5 — A/B/C acceptance (R-ML-C passed the P4.5 binding AC)

Binding reconciliation rules for this PRD:

1. **This PRD supersedes PRD #4 as the master spine.** PRD #4's
   deliverables are migrated/extended, never rebuilt from zero.
2. **There are already three rank-model implementations** —
   `core/ml/xgb_ranking.py` (XGBRankingModel / LambdaRankICModel,
   Phase 1.6), `core/research/ml/rank_model.py` (PRD #4 P4.1), and
   `core/ml/xgb_alpha`. Package P2 must pick **one** canonical path and
   migrate, not add a fourth. The new `train_ranker.py` /
   `walk_forward_ranker.py` in §12.1 must first be evaluated against
   renaming/extending the existing `walk_forward_rank_sign.py`.
3. **The ranking baseline already failed once.** PRD #4 P4.1's rank
   model produced rank-IR 0.10–0.14 across 4/4 configs versus the 0.30
   AC (backlog memo `docs/memos/20260520-prd4_p41_ir_threshold_backlog.md`).
   This PRD's ranking baseline therefore must state its explicit
   differentiator vs P4.1: residualized-rank labels + uniqueness
   weighting + cost-aware thresholds + **portfolio-level** acceptance
   (§9), not another bare rank-IR run. The unresolved directional
   question — whether the 0.30 rank-IR AC is itself appropriate for an
   individual-scale book — is carried into R3/Package P4 and must be
   resolved with the user, not silently re-litigated.

## 2. Evidence Collected In This Audit

## 2.1 Baseline re-risk result

Local re-run after the recent execution / constructor fixes:

- `multi_factor`
  - total return `-16.71%`
  - `CAGR -4.49%`
  - `Sharpe -0.16`
  - `MaxDD -63.95%`
  - `IR -0.38`
- `BULL` regime remains catastrophic:
  - `CAGR -39.93%`
  - `MaxDD -60.49%`

Source: [/tmp/pqs_audit_afterfix/backtest/runs/20260521_135818_backtest/master_report.md](/tmp/pqs_audit_afterfix/backtest/runs/20260521_135818_backtest/master_report.md:10)

> **Evidence caveat (`AUDIT-2026-05-21`).** This source is an ephemeral
> `/tmp` artifact and **states no backtest window** — the report has no
> start/end date; only a ~984-trading-day regime breakdown (~4 years).
> This violates this PRD's own §13 auditability rule ("every verdict
> reproducible with one checked-in command; no notebook-only state").
> Because the window is unstated, temporal-split compliance of this run
> is **unverifiable** — it cannot be confirmed whether it consumed
> validation years (2018/2019/2021/2023/2025) or sealed 2026. The run
> timestamp (13:58) is after all six 2026-05-21 execution-kernel fixes
> (committed 11:46–12:18), so the "after fixes" framing is accurate.
> **R0 (§6) must reproduce this number with a checked-in command, an
> explicit window, and a temporal-split partition declaration before it
> can carry binding weight.**

Interpretation (revised `AUDIT-2026-05-21`):

- The recent fixes were real and useful.
- The baseline is **not uniformly broken** — it is **regime-fragile**.
  A clean train-only re-run on 2009–2017 (post-fix, contiguous train
  years) gives CAGR **+12.6%**, MaxDD **−20.2%**, realized vol ~13%,
  i.e. it beats SPY. The catastrophic −63.95% / 27.7%-vol picture is a
  separate, recent ~4-year window. Same strategy, same config — the
  outcome is window/regime dependent.
- Therefore the precise bottleneck is **risk translation in high-vol
  regimes**, not a globally broken strategy: vol-targeting was repaired
  (`AUDIT-2026-05-21` P0-1, correlation-aware portfolio vol) but
  `_DEFAULT_TARGET_VOL = 0.25` still implies ~25% vol, and the
  end-to-end MaxDD improvement on the high-vol window remains
  unverified (regime-conditional; see
  `docs/audit/20260521-execution_kernel_audit_findings.md` §6).
- The `BULL` regime −39.93% figure is taken from the regime-classifier
  labels; a long-only book losing 40% in a "BULL" label is itself
  suspicious and may be a regime-mislabel artifact. R0 must report the
  regime breakdown but not treat it as settled root-cause evidence
  without checking the regime series.

## 2.2 cycle06 candidate re-risk result

Fresh local Track-A re-eval:

- lineage: `track-c-cycle-2026-05-06-01`
- top trial evaluated: `bab8cfe88af3`
- verdict: `FAIL`
- failed gates:
  - `validation_year_2018_maxdd`
  - `validation_aggregate_excess_vs_spy`
- worst validation-year MaxDD:
  - `2018 maxdd = -23.02%`

Source: [/tmp/pqs_cycle06_rerisk.json](/tmp/pqs_cycle06_rerisk.json:1)

Important note:

- This local re-risk run does **not** match the frozen evidence candidate `cycle06_31af04cf2ff9`.
- It evaluated the top trial returned by the lineage query under the current script path.
- This is enough to prove that the lineage is not “obviously safe after fixes”, but it is **not** enough to overwrite the frozen evidence candidate by itself.

Operational implication:

- cycle06-family candidates need a controlled re-risk replay against the exact frozen spec, not just lineage top-1 lookup.

## 2.3 cycle08 candidate evidence status

The full local re-run for cycle08 did not finish during this audit window, so this PRD does **not** pretend to have a fresh re-run result.

What we do have:

- frozen evidence says:
  - Track-A `PASS post-MaxDD-fix`
  - sealed 2026 single-shot `PASS`
  - `sealed_vs_spy +14.83%`
  - `sealed_max_dd -7.66%`
  - `per_year_maxdd_max -18.10%`

Source: [data/research_candidates/cycle08_3f40e3f4ed1a_evidence_v1.yaml](/home/zibo/Documents/projects/pqs/data/research_candidates/cycle08_3f40e3f4ed1a_evidence_v1.yaml:79)

Interpretation:

- cycle08 remains the strongest currently frozen positive evidence path.
- But it still needs a reproducible local re-risk replay in the current environment before any stronger decision.

## 2.4 PEAD candidate status

PEAD remains interesting, but it is not a production-core candidate yet.

Local / frozen evidence:

- full-period:
  - `Sharpe 1.055`
  - `CAGR 5.48%`
  - `MaxDD -7.64%`
- cost robustness:
  - `2x cost remains positive = true`
- Track-A:
  - `14/17 gates passed`
  - fails are mostly `aggregate excess vs SPY / QQQ`

Sources:

- [data/research_candidates/pead_sue_trial1_evidence_v1.yaml](/home/zibo/Documents/projects/pqs/data/research_candidates/pead_sue_trial1_evidence_v1.yaml:100)
- [data/audit/pead_path1_track_a_verdict.json](/home/zibo/Documents/projects/pqs/data/audit/pead_path1_track_a_verdict.json:1)

Interpretation:

- PEAD is a valid differentiated alpha source candidate.
- But it is evidence-only and does not solve the mainline construction / baseline problem.

## 2.5 ML sign-classifier status

Fresh local walk-forward result:

- model: `xgb`
- window: `2010-2024`
- train/val folds: rolling `5y / 1y`
- aggregate:
  - `mean val F1(VETO) = 0.2626`
  - `mean val precision(VETO) = 0.3816`
  - gate `precision(VETO) > 0.55` = `FAIL`

Source: [data/audit/r32_walkforward_sign_xgb_20260521T210059Z.json](/home/zibo/Documents/projects/pqs/data/audit/r32_walkforward_sign_xgb_20260521T210059Z.json:257)

Interpretation:

- The classifier is learning something nonzero.
- But it is not good enough to be used as a production entry filter.
- More importantly, the training chain is still methodologically incomplete.

## 2.6 External consensus check

The external picture is consistent with the internal audit:

- `XGBoost` officially supports learning-to-rank with query groups and `rank:ndcg`, and documents that training samples must be grouped by `qid` and sorted by group.
- `Qlib` continues to keep `forecast model -> portfolio strategy -> backtest / executor` as separate components, which matches the architecture direction this repository should keep.
- `PatchTST` and `iTransformer` remain legitimate sequence-model candidates, but both are presented as time-series forecasting backbones, not evidence that they should replace a strong tabular baseline before one exists.
- `FinRL` still frames RL as an environment + agent + backtest stack for trading, but that does not change the practical recommendation that RL should come after a stable alpha / sizing baseline.
- governance expectations have hardened further: IOSCO's February 2025 capital-markets AI report and NIST's July 26, 2024 AI RMF GenAI profile both emphasize governance, testing, monitoring, data quality, transparency, and ongoing controls.

Operational conclusion:

- this PRD should become even more explicit that the next implementation target is a trusted ranking baseline plus trusted portfolio acceptance
- not a jump to more novel architectures

## 3. Audit Findings On The ML Training Framework

## 3.0 Missing architectural statement in the current PRD

The current PRD is still too centered on “fixing the sign classifier”.

That is necessary, but this new review shows the stronger framing should be:

- define the task family first
- define the label to match the trading action
- define the portfolio mapping and constraints
- only then choose whether the model should be GBDT, sequence, Transformer, or other

For this project, the default first-class task should be:

- `daily cross-sectional stock ranking under realistic cost and portfolio constraints`

not:

- pure binary direction prediction
- pure in-sample classifier quality optimization

## 3.1 What is already good

The repository already has several strong foundations:

- strict chronological walk-forward driver  
  Source: [core/research/ml/pipeline.py](/home/zibo/Documents/projects/pqs/core/research/ml/pipeline.py:1)
- sealed-year guard
- bar-integrity smoke
- tradeable-mask application  
  Source: [core/research/ml/labels.py](/home/zibo/Documents/projects/pqs/core/research/ml/labels.py:1)
- explicit context bundles  
  Source: [core/research/ml/context_features.py](/home/zibo/Documents/projects/pqs/core/research/ml/context_features.py:1)
- ML sidecar constrained to categorical veto / no-vote semantics  
  Source: [core/research/decision/ml_sidecar.py](/home/zibo/Documents/projects/pqs/core/research/decision/ml_sidecar.py:1)

These are the right bones.

## 3.2 Main gap A — labels are still too naive in the live training path

Current Stage-2 sign training uses:

- top-decile Stage-1 cells
- label = `forward_return > 0`

Source:

- [core/research/ml/sign_classifier.py](/home/zibo/Documents/projects/pqs/core/research/ml/sign_classifier.py:68)
- [dev/scripts/ml/train_sign_classifier.py](/home/zibo/Documents/projects/pqs/dev/scripts/ml/train_sign_classifier.py:141)

Problem:

- this ignores:
  - cost hurdle
  - drawdown path
  - barrier-touch path dependency
  - overlapping-label effective sample size

The repo already contains better primitives:

- `concurrency_weights`
- `avg_uniqueness`
- `triple_barrier_labels`

Source: [core/ml/labeling.py](/home/zibo/Documents/projects/pqs/core/ml/labeling.py:1)

But those primitives are not the default path of the main Stage-2 classifier flow.

What is still missing beyond that:

- a canonical `ranking` label path for the main stock-selection task
- a canonical `residualized forward return` label path before binarization
- explicit statement that `sign` is a secondary label family for sidecars, veto layers, or event filters

Recommended task/label priority for this codebase:

1. `cross-sectional rank / quantile label`
2. `residual return magnitude`
3. `sign / binary direction`

Rationale:

- the live portfolio action is closer to `buy top names / skip weak names / size by score`
- ranking labels align better with top-k portfolio construction
- binary sign is too coarse to serve as the only canonical ML objective

## 3.3 Main gap B — uniqueness weighting is not wired into the sign-classifier training path

The latest sign-classifier training path still does:

`model.fit(X_train, y_train)`

Source: [dev/scripts/ml/train_sign_classifier.py](/home/zibo/Documents/projects/pqs/dev/scripts/ml/train_sign_classifier.py:339)

There is no canonical default-on `sample_weight` from label uniqueness in this path.

Why this matters:

- 21-day overlapping labels create severe concurrency.
- Without uniqueness weighting, the effective sample size is overstated.
- This tends to make validation statistics look more stable than they really are.

This review adds one more weighting requirement:

- sample-weight design should support at least:
  - uniqueness / concurrency correction
  - liquidity-aware weighting
  - optional freshness decay
  - optional event emphasis

The canonical path should default to:

- `sample_weight = uniqueness_weight * liquidity_weight * freshness_weight`

with `event_weight` available but opt-in and fully recorded in artifacts.

## 3.4 Main gap C — the classifier optimizes entry correctness, not portfolio usefulness

Current Stage-2 objective is basically:

- classify top-decile Stage-1 opportunities into `winner / loser`
- map output into `VETO / NO_VOTE`

This is acceptable as a sidecar architecture, but incomplete.

The missing step is:

- evaluate whether the classifier **improves actual portfolio outcomes**
  - net Sharpe
  - MaxDD
  - turnover
  - implementation shortfall tolerance
  - concentration

The current walk-forward output is still mostly classifier metrics, not portfolio metrics.

One more missing layer from the current PRD:

- model output must be evaluated in the exact portfolio mapping it will use in production

That means the acceptance loop must not stop at:

- score quality
- classifier precision
- rank IC

It must also include:

- score-to-weight mapping
- clipping / volatility scaling
- turnover budget
- sector / beta / concentration constraints
- cost sensitivity and fill realism

## 3.5 Main gap D — model output is not calibrated to cost-aware decision thresholds

Current label threshold defaults to `0.0` return.  
Source: [core/research/ml/sign_classifier.py](/home/zibo/Documents/projects/pqs/core/research/ml/sign_classifier.py:68)

That means:

- “slightly positive but below realistic trading cost + slippage + execution uncertainty” still counts as class 1.

For a production decision layer, class definitions should be aligned to:

- `net positive after expected cost`
- optionally `barrier-safe positive`
- optionally `excess vs benchmark or cash hurdle`

For the main stock-selection route, a stronger canonical target should be:

- `future residual return rank`
- or `future residual return quantile bucket`

with binary labels reserved for:

- veto layers
- event filters
- execution or participation classifiers

## 3.6 Main gap E — the training path is not yet integrated with the true rebalance kernel acceptance path

The repo has:

- `PartialRebalancePolicy`
- `MLSidecarPolicy`

Sources:

- [core/research/decision/partial_rebalance.py](/home/zibo/Documents/projects/pqs/core/research/decision/partial_rebalance.py:1)
- [core/research/decision/ml_sidecar.py](/home/zibo/Documents/projects/pqs/core/research/decision/ml_sidecar.py:1)

This is directionally correct.

But the current ML training artifacts still are not promoted through a full audited loop of:

1. train
2. walk-forward validate
3. plug into decision stack
4. portfolio backtest on the same fold schedule
5. compare against no-ML baseline
6. pass explicit portfolio-level gates

That missing loop is the single most important ML gap now.

## 4. Product Decision

## 4.1 What we will not do now

We will **not** start a new free-form alpha mining round now.

Reason:

- current baseline is still broken
- Stage-2 classifier still fails held-out precision
- label / weighting / portfolio-linkage stack is not hardened enough

## 4.2 What we will do now

We will execute two workstreams in order:

- `Workstream R0`: re-risk pack
- `Workstream R1-R4`: ML training framework hardening

Only after both pass do we start `R5 fresh mining`.

## 4.3 This PRD is the master spine

This PRD should be treated as the master product-and-research spine for:

- ML factor mining
- post-signal capital allocation
- portfolio construction
- execution-aware validation
- ongoing model governance

Everything that is essential to the end-to-end daily ML alpha pipeline belongs here.

Only the following should be deferred into supplementary PRDs:

- clearly separate intraday-only research arms
- options-only sleeves
- experimental deep sequence variants after baseline validation
- text / transcript / alternative-data feature enrichments after the data contract is stable
- RL overlays after the supervised alpha stack is already proven

## 4.4 End-state chain that this PRD must define

The target production research chain is:

1. `point-in-time data ingestion`
2. `data validation + provenance + freeze discipline`
3. `feature generation by source family`
4. `task-aligned label generation`
5. `purged / embargoed walk-forward training`
6. `model scoring`
7. `score normalization and calibration`
8. `score-to-position mapping`
9. `portfolio constraint enforcement`
10. `execution simulation with realistic costs / slippage / delay`
11. `portfolio-level acceptance`
12. `paper / forward monitoring`
13. `promotion / demotion / retirement governance`

The PRD is incomplete unless all 13 links are specified strongly enough to implement and audit.

## 4.5 Source-family architecture

The project should define its information sources in six mandatory tiers and one optional tier.

Mandatory tier A — market data:

- daily adjusted OHLCV
- benchmark prices
- sector ETFs / factor ETFs / macro reference tickers
- current project status: already present and usable

Mandatory tier B — fundamentals / accounting:

- point-in-time financial statements
- quality, profitability, leverage, accrual, asset-growth, revision-sensitive features
- current project status: partially present through `core/factors/fundamental_factors.py`

Mandatory tier C — macro / regime:

- macro time series with release-aware handling where possible
- market regime state, rates, dollar, volatility, credit / liquidity proxies
- current project status: partially present through `core/factors/macro_factors.py`

Mandatory tier D — event / calendar:

- earnings dates
- macro event windows
- split / dividend / corporate-action awareness
- current project status: partially present through PEAD and macro-event components

Mandatory tier E — execution / liquidity:

- ADV / dollar volume
- spread proxy or observed spread
- participation constraints
- volatility and turnover burden
- current project status: partially present; should become a first-class allocation input

Mandatory tier F — portfolio state:

- current holdings
- sector / factor / beta exposures
- drawdown state
- recent turnover / fill quality
- current project status: present in execution / rebalance stack, but not yet fully integrated into ML acceptance

Optional tier G — enrichment sources:

- text / news / transcript / filing embeddings
- options surface / implied volatility / skew
- alternative data
- intraday microstructure

These are useful and should be planned for now, but they should enter the production stack only through the same PIT + acceptance discipline as the base tiers.

## 4.6 Point-in-time rules for each source family

All source families must satisfy these contracts:

- every record must be attributable to a source and timestamp
- every feature must be reproducible from frozen raw inputs
- no feature may use post-publication revisions without explicit real-time / vintage handling
- no sector / benchmark / membership metadata may use future composition knowledge
- all event features must use the first tradeable timestamp after public availability

Minimum source-specific rules:

- filings / fundamentals:
  - use official or vendor-normalized point-in-time filing availability
  - SEC EDGAR is a valid canonical source for filings and submissions metadata
- macro:
  - prefer vintage-aware or release-aware handling when the strategy depends on publication timing
  - FRED / ALFRED style real-time period handling is the reference model
- news / text:
  - require publication timestamp, ticker mapping provenance, and de-duplication policy
- options:
  - require chain timestamp, contract metadata, liquidity filters, and stale-quote rules
- intraday:
  - require exchange calendar alignment, regular-session policy, and delayed / missing-bar handling

## 4.7 Task hierarchy

The master PRD should explicitly separate four ML task classes.

Task 1 — daily cross-sectional stock selection:

- target: relative ranking of names for next `h` days
- default model family: `XGBoost ranker` first, `LightGBM ranker` parity second
- role in stack: primary alpha engine

Task 2 — event filters / sidecars:

- target: accept / veto / classify catalyst-driven setups
- examples: PEAD, earnings, macro-event windows, threshold-over-cost direction
- role in stack: secondary gating or sleeve-specific engine

Task 3 — sequence / intraday / microstructure:

- target: short-horizon path-dependent or structure-dependent edges
- examples: TCN, PatchTST, iTransformer, shallow intraday XGB
- role in stack: supplementary after the daily baseline is validated

Task 4 — allocation / execution control:

- target: position sizing, participation, rebalance speed, turnover control
- default solution order:
  - deterministic policy
  - convex / heuristic optimizer
  - only later RL overlay if justified

The PRD must prohibit using one task class as a substitute for another.
For example:

- a sign classifier is not the primary solution to daily cross-sectional stock selection
- RL is not the primary solution to alpha discovery

## 4.8 Capital allocation framework

The PRD must define capital allocation as a separate layer from forecasting.

Required sub-steps:

1. transform raw model score into comparable cross-sectional signal
2. optionally residualize / neutralize vs market / sector / style
3. map score into expected edge bucket
4. apply risk scaling:
   - volatility target
   - liquidity cap
   - concentration cap
   - drawdown / regime overlay
5. apply portfolio constraints:
   - long-only invariant
   - max single-name weight
   - max sector overweight
   - beta neutrality optional
   - turnover cap
   - participation cap
6. produce target weights
7. route target weights through rebalance / execution stack

The default production allocation path should support at least three mapping modes:

- `top-k equal or capped weight`
- `score-proportional clipped weight`
- `score / volatility scaled weight`

It should also support a `cash / no-trade` outcome when predicted edge is below the net cost hurdle.

## 4.9 Exit and holding policy

The master PRD must specify exits explicitly.

Minimum exit classes:

- time-based exit
- thesis-decay / signal-decay exit
- volatility or drawdown risk-off exit
- catalyst-resolution exit for event strategies
- turnover-aware trim / rebalance-band exit

The project should not treat “rebalance every N days” as a complete exit policy.

## 4.10 Message / text / options expansion policy

Future enrichment sources should be explicitly planned now so the main architecture does not need to change later.

Text / message / filing lane:

- approved use:
  - event extraction
  - earnings / guidance deltas
  - tone / risk / litigation flags
  - management-language embeddings
- not approved as first production use:
  - direct end-to-end LLM buy/sell decisions

Options lane:

- approved use:
  - implied-volatility level / term-structure / skew features
  - event-risk proxies
  - sentiment / crowding proxies
- required controls:
  - liquidity filters
  - stale quote filters
  - contract roll rules

Both lanes belong in the master architecture, but their first production role should be:

- `feature enrichment into the same acceptance stack`

not:

- separate, weaker research standards

## 5. Scope

## 5.1 In scope

- fresh re-risk replay for current baseline and active evidence candidates
- source-family architecture for the daily ML alpha stack
- point-in-time and provenance rules for all mandatory source tiers
- task-to-model taxonomy hardening
- label hardening
- uniqueness weighting
- triple-barrier experiment path
- ranking-baseline promotion path from existing `core/ml/xgb_ranking.py`
- LightGBM parity enablement on the active research environment
- cost-aware sign thresholding
- walk-forward portfolio-level ML acceptance
- score-to-weight mapping acceptance
- capital allocation and exit-policy specification
- future message / text / options enrichment interfaces
- artifact schema upgrades
- acceptance tests and audit artifacts

## 5.2 Out of scope

- real broker integration
- full intraday deep model research arm
- external pretrained model scaling
- new factor family expansion
- changing the no-short / no-margin invariant
- end-to-end RL alpha discovery

## 6. Workstream R0 — Re-Risk Pack

## 6.1 Objective

Recompute a trustworthy risk picture for:

1. `production baseline`
2. `cycle06_31af04cf2ff9_evidence_v1`
3. `cycle08_3f40e3f4ed1a_evidence_v1`
4. `pead_sue_trial1_evidence_v1`

## 6.2 Required outputs

- `data/audit/rerisk_pack_20260521.json`
- `docs/memos/20260521-rerisk-pack.md`

Each candidate row must include:

- source spec id / candidate id
- full-period CAGR / Sharpe / MaxDD
- validation-year MaxDD table
- stress-slice MaxDD table
- beta to SPY / QQQ if applicable
- concentration metrics
- turnover if available
- verdict:
  - `GREEN`
  - `YELLOW`
  - `RED`

## 6.3 Verdict rules

- `GREEN`
  - stress MaxDD within stated cap
  - validation-year MaxDD within cap
  - no new catastrophic regression vs frozen evidence
- `YELLOW`
  - some risk deterioration but still within evidence-only tolerances
- `RED`
  - fails core drawdown gates or materially contradicts frozen evidence

## 6.4 Acceptance criteria

- baseline row present
- cycle06 exact frozen candidate replay present
- cycle08 exact frozen candidate replay present
- PEAD row present
- every row has full provenance path
- no manual spreadsheet calculation
- all metrics reproducible from checked-in code paths
- every row states its exact backtest window and the temporal-split
  partitions it touches (`AUDIT-2026-05-21`)

## 6.5 Temporal-split discipline for R0 — `AUDIT-2026-05-21`

R0 re-risk runs touch real historical data and therefore must obey
`config/temporal_split.yaml` (`alternating_regime_holdout_v1`). This is
a hard requirement, not a style note (see
`feedback_temporal_split_discipline`).

- Partitions: train = 2009–2017 + 2020 + 2022 + 2024; validation =
  2018 / 2019 / 2021 / 2023 / 2025; sealed = 2026; stress slices =
  covid_flash 2020-Q1, rate_hike 2022-Q3.
- Every re-risk row must declare its window and which partitions it
  spans. A row whose window is unstated (as in §2.1) does **not**
  satisfy R0.
- Full-period or validation-spanning MaxDD figures are **diagnostic
  only** and must be labelled as such; they consume the information
  value of the holdout and cannot later be reused as pre-promotion
  evidence.
- For crisis / high-vol MaxDD sanity, use the **designated stress
  slices** (covid_flash, rate_hike_2022) — they are explicitly
  sanctioned for "MaxDD sanity ONLY" — rather than free re-runs over
  validation years.
- The frozen evidence candidates (cycle06 / cycle08) must be replayed
  against their **exact frozen spec**, not a lineage top-1 lookup
  (per §2.2), and sealed 2026 is never re-read outside a logged
  single-shot.

R0 acceptance is not met until the §2.1 baseline number is reproduced
under these rules with an explicit, checked-in window.

## 7. Workstream R1 — Canonical Label Hardening

## 7.1 Objective

Replace “bare forward positive return” as the effective default decision label for ML experiments.

Also establish a first-class `ranking` objective for the main daily stock-selection problem.

## 7.2 Required implementation

Create a canonical label config path in `config/ml_labeling.yaml` and wire it into the sign-classifier drivers.

Modes:

- `cross_sectional_residual_rank`
- `cross_sectional_residual_quantile`
- `binary_forward_return`
- `binary_forward_return_after_cost`
- `triple_barrier`

Required fields:

- horizon_days
- cost_hurdle_bps
- residualize_vs_market
- residualize_vs_sector
- quantile_buckets
- pt_mult
- sl_mult
- vol_lookback
- min_expected_edge_bps

Current-state note:

- `config/ml_labeling.yaml` already exists and already includes `horizon_days`, concurrency-weighting, and triple-barrier knobs
- the required change is to expand it into the canonical task / label contract, not create a second competing config

## 7.3 Acceptance criteria

- every training artifact records which label mode was used
- artifacts are not comparable across different label modes without explicit note
- unit tests cover:
  - residualized-rank label determinism
  - same-date cross-sectional bucket assignment
  - cost-hurdle classification
  - triple-barrier edge cases
  - deterministic output

## 7.4 Product rule

For daily cross-sectional stock selection, the default research baseline must use:

- `cross_sectional_residual_rank` or `cross_sectional_residual_quantile`

Binary sign labels may remain in the repo, but only as:

- sidecar filters
- event-specific classifiers
- execution-support tasks

## 7.5 Data-source-aware label rule

Each label mode must declare which source tiers it depends on.

Examples:

- `cross_sectional_residual_rank`
  - depends on: market + benchmark + optional sector metadata
- `triple_barrier`
  - depends on: market + volatility inputs
- `earnings_event_after_cost`
  - depends on: market + event timestamps + cost assumptions

No label may be accepted into the canonical pipeline without an explicit source dependency declaration.

## 8. Workstream R2 — Uniqueness Weighting And Purge Default-On

## 8.1 Objective

Make overlapping-label correction mandatory in the main ML path.

## 8.2 Required implementation

- Add canonical sample-weight construction using `avg_uniqueness` / `concurrency_weights`.
- Add canonical multiplicative sample-weight schema with:
  - `uniqueness_weight`
  - `liquidity_weight`
  - `freshness_weight`
  - optional `event_weight`
- Thread `sample_weight` through:
  - Stage-2 sign classifier training
  - walk-forward rank/sign experiments where appropriate
- Add explicit purge / embargo helper use at split boundaries where the current sign path still relies only on chronological separation.

Default parameter policy:

- `purge >= horizon`
- `embargo >= horizon`
- any override below this level must require explicit flag and artifact note

Current-state note:

- `config/temporal_split.yaml`
- `config/temporal_split_v2.yaml`
- `config/temporal_split_v3.yaml`

currently set `embargo_days: 0`.

Precision note (`AUDIT-2026-05-21`): those same configs do set
`purge_at_split_boundary: true` with `label_horizon_days_max: 21`, so
the **first-order** leakage (train labels whose horizon overlaps the
test fold) is already removed by purge. `embargo_days: 0` leaves only
the **second-order** gap — serial-correlation bleed in the bars
immediately after the boundary. So this is a real but second-order
remediation item, not an unguarded-leakage emergency.

That said, it should still be treated as a concrete remediation item,
not a soft suggestion. For the current daily-horizon stack, the PRD
default should be:

- `embargo_days = horizon_days`

unless a documented exception is approved for a specific experiment.

## 8.3 Acceptance criteria

- `train_sign_classifier.py` and `walk_forward_sign_classifier.py` both emit:
  - weight mode
  - mean / min / max sample weight
- `train_ranker.py` or equivalent baseline driver emits the same metadata
- a run with weighting disabled must require explicit flag
- tests prove default path uses weighted fit

## 8.4 Weighting auditability

Every artifact must record:

- whether weights were normalized
- each weight component formula
- liquidity proxy used
- freshness half-life if enabled

## 9. Workstream R3 — Portfolio-Level ML Acceptance

## 9.1 Objective

ML models must earn their right to exist by improving portfolio behavior, not just classifier metrics.

## 9.2 Required implementation

Build a portfolio-level acceptance driver:

- baseline A:
  - existing non-ML Stage-1 composite only
- path B:
  - Stage-1 + ML veto sidecar
- path C:
  - Stage-1 + ML veto + partial rebalance stack
- path D:
  - GBDT ranking baseline mapped directly into portfolio weights

For daily cross-sectional experiments, the acceptance harness must support:

- `score -> top/bottom bucket selection`
- `score -> clipped proportional weight`
- `score -> volatility-scaled target weight`
- sector-neutral option
- beta-neutral option when configured

Evaluate all three on identical walk-forward slices.

Implementation preference:

- first extend or factor out the existing `dev/scripts/ml/r29_acceptance_r_ml_a_vs_b.py`
- only create an entirely new acceptance harness if the existing script cannot be made sufficiently general and auditable

Metrics:

- rank IC / ICIR where applicable
- net Sharpe
- net CAGR
- MaxDD
- turnover
- cost sensitivity 1x / 2x
- validation aggregate excess vs SPY
- concentration
- participation / liquidity usage if available

## 9.3 Acceptance criteria

ML path passes only if all are true:

- non-inferior MaxDD
- non-inferior turnover after cost adjustment
- improved or equal net Sharpe
- no regression in stress slices beyond tolerance

This is the first point where ML can be called “useful”.

## 9.4 Positioning rule

No model may be considered production-ready unless its artifact includes the exact score-to-position mapping used in evaluation, including:

- bucket rule
- volatility scaling rule
- clipping rule
- sector / beta neutralization rule
- turnover cap
- max single-name cap

## 9.5 Allocation acceptance rule

A model is not useful to this project unless it survives both:

- `forecast acceptance`
- `allocation acceptance`

`forecast acceptance` covers:

- rank IC / ICIR
- calibration
- stability across folds / years / regimes

`allocation acceptance` covers:

- net return after realistic costs
- MaxDD and concentration
- turnover and participation
- benchmark-relative behavior
- sensitivity to rebalance / clipping / scaling choices

## 9.6 Overfit-significance control (mandatory) — `AUDIT-2026-05-21`

Walk-forward portfolio metrics and rank-IC alone do not establish that
a model's edge is real rather than selection noise. Any model /
hyperparameter / label-mode chosen by comparing across folds or configs
must pass the project's **existing** overfit-control machinery — these
modules already ship and must be reused, not rebuilt:

- `core/research/dsr_trial_accounting.py` — Deflated Sharpe Ratio:
  deflate the selected Sharpe / IC for the true number of trials
  examined during selection.
- `core/research/mining_pbo.py` — Probability of Backtest Overfit
  (Bailey CSCV).
- `core/research/cpcv.py` / `core/research/cpcv_acceptance.py` —
  combinatorial purged cross-validation.

Rationale: this is not theoretical. Round 33 (2026-05-21) ran a
432-config XGB hyperparameter search for the Stage-2 classifier; 0/432
crossed the gate and the "best" config was demonstrably selected on the
same val folds it was scored on (search-overfit). A ranking baseline
selected the same way will hit the same wall. Wiring DSR / PBO / CPCV
into the ranker selection (Package P2) and the acceptance harness
(Package P4) also closes the 2026-05-18 grand-audit finding **P0-B**
(robustness kernels exist but have zero call sites in the binding
gate).

Acceptance rule: an ML path may be called "useful" (§9.3) only if its
reported edge survives DSR deflation at the true trial count and its
PBO is below a stated threshold recorded in the artifact.

## 10. Workstream R4 — Artifact And Governance Hardening

## 10.1 Objective

Make every ML artifact auditable enough to survive future review.

## 10.2 Required implementation

Every ML artifact JSON must include:

- task family
- source tiers used
- label mode
- sample-weight mode
- purge / embargo params
- context bundle
- training universe
- model family
- objective name
- score-to-weight mapping mode
- exit policy mode
- whether existing project-native components were reused
- benchmark-relative eval if applicable
- portfolio acceptance result path
- exact backtest / decision-stack config hash
- trial count examined during selection, DSR-deflated metric, and PBO
  (`AUDIT-2026-05-21`, per §9.6)

Portfolio-level artifacts must additionally include:

- target-weight construction mode
- risk-scaling mode
- constraint set id
- cost model id
- execution-assumption id

## 10.3 Acceptance criteria

- no ML artifact can be promoted without these fields
- docs and tests fail closed on missing metadata

## 11. Workstream R5 — Fresh Mining Gate

Fresh mining is allowed only after:

- `R0` complete
- `R1-R4` complete
- one ML sidecar portfolio-level acceptance path achieves `PASS`
  or the project explicitly decides to continue without ML and mines on hardened non-ML stack

Fresh mining should begin from this model priority:

1. `XGBoost ranking baseline` using existing native ranker path
2. `LightGBM` parity path if and when dependency / env support is deliberately added
3. `GBDT ensemble or shallow meta-model`
4. `TCN / PatchTST / iTransformer` only if the baseline shows stable OOS IC and portfolio value-add
5. `MAE / self-supervised encoder` only as feature or embedding support
6. `RL` only for sizing / execution once alpha is already stable

## 12. Concrete File-Level Implementation Plan

## 12.1 Expected code changes

- `config/ml_labeling.yaml`
  - add canonical task + label-mode schema
- `config/ml_sources.yaml`
  - canonical source-tier and PIT contract schema
- `config/ml_allocation.yaml`
  - canonical score-to-weight / exit / constraint schema
- `core/research/ml/sign_classifier.py`
  - support cost-aware binary label helper
- expand existing ranking path:
  - `core/ml/xgb_ranking.py`
  - add residualized cross-sectional rank / quantile labels
  - add weighting support where appropriate
- add LightGBM parity path:
  - `core/ml/lgbm_ranking.py`
  - `LGBMRanker` / `lambdarank` or `rank_xendcg` implementation
- `core/ml/labeling.py`
  - become canonical source for uniqueness / triple-barrier
- `core/research/ml/rank_model.py` or equivalent
  - become the canonical orchestration wrapper around the existing ranking implementations
- new allocation module:
  - `core/research/allocation/score_to_weight.py`
- new allocation policy / schema helpers:
  - `core/research/allocation/constraints.py`
  - `core/research/allocation/exit_policy.py`
- new source-contract module:
  - `core/research/data_contracts/source_tiers.py`
- `dev/scripts/ml/train_sign_classifier.py`
  - wire label mode + sample weights + metadata
- `dev/scripts/ml/walk_forward_sign_classifier.py`
  - wire sample weights + richer artifact summary
- new baseline driver:
  - `dev/scripts/ml/train_ranker.py`
- new walk-forward baseline driver:
  - `dev/scripts/ml/walk_forward_ranker.py`
- extend existing acceptance harness:
  - `dev/scripts/ml/r29_acceptance_r_ml_a_vs_b.py`
  - or factor common code into a reusable acceptance module
- optional new driver if needed after refactor:
  - `dev/scripts/ml/acceptance_portfolio_ranker.py`
- optional later enrichment drivers:
  - `dev/scripts/ml/build_text_event_features.py`
  - `dev/scripts/ml/build_options_surface_features.py`
- new report outputs:
  - `data/audit/rerisk_pack_20260521.json`
  - `data/audit/ml_sign_portfolio_acceptance_*.json`
  - `data/audit/ml_rank_portfolio_acceptance_*.json`

## 12.2 Expected test changes

- new unit tests:
  - task family / label family selection
  - source-tier contract validation
  - residualized rank label generation
  - label mode selection
  - cost-aware label threshold
  - uniqueness-weight plumbing
  - allocation-schema validation
  - artifact metadata completeness
- new integration tests:
  - ranking baseline walk-forward deterministic replay
  - ML sidecar portfolio acceptance A/B
  - ranker portfolio acceptance A/B
  - LightGBM ranker parity smoke
  - score-to-weight deterministic acceptance
  - deterministic rerun with identical outputs

## 12.3 Execution packages

The implementation should be executed in seven packages.
Each package must finish with explicit artifacts and a go / no-go gate.

### Package P0 — Source contracts and environment floor

Objective:

- freeze the minimum runnable research environment
- define source-tier contracts before expanding model complexity

Required work:

- confirm `xgboost` and `lightgbm` are available in the research environment
- create `config/ml_sources.yaml`
- define source tiers, PIT rules, freshness rules, and provenance requirements
- define canonical source ids for:
  - market bars
  - fundamentals
  - macro
  - event calendar
  - options
  - text / news

Expected outputs:

- `config/ml_sources.yaml`
- `docs/memos/20260521-ml-source-contracts.md`
- `data/audit/ml_env_floor_20260521.json`

Gate:

- every mandatory source tier has a declared contract
- environment can import `xgboost` and `lightgbm`
- no training driver remains source-agnostic in artifact metadata

### Package P1 — Canonical labels and split discipline

Objective:

- make labels task-aligned and leakage-correct by default

Required work:

- expand `config/ml_labeling.yaml`
- implement residualized rank / quantile labels
- thread cost-aware binary labels into sign-sidecar path
- make purge + embargo defaults active in main daily ML paths
- remediate `embargo_days: 0` defaults in active temporal split configs or override them explicitly in the ML drivers

Expected outputs:

- updated `config/ml_labeling.yaml`
- `data/audit/ml_label_contract_smoke_*.json`
- unit tests proving deterministic label generation and purge behavior

Gate:

- all canonical label modes emit deterministic artifacts
- all walk-forward drivers record purge / embargo parameters
- disabling purge or weighting requires explicit user-visible flags

### Package P2 — Ranker baseline training stack

Objective:

- establish the primary daily stock-selection ML baseline

Required work:

- implement `train_ranker.py`
- implement `walk_forward_ranker.py`
- wire `XGBoost` ranker as the first-class default
- wire `LightGBM` ranker as parity path
- add ranker artifact schema:
  - task family
  - label mode
  - source tiers
  - model family
  - objective
  - split params
  - weighting mode

Expected outputs:

- `data/ml/rank_*.json`
- `data/audit/walk_forward_ranker_*.json`

Gate:

- at least one `XGBoost` ranker run completes end-to-end
- at least one `LightGBM` parity smoke run completes end-to-end
- artifacts are comparable across folds and model families
- the canonical rank-model path is chosen from the three existing
  implementations (per §1.5) — no fourth is created
  (`AUDIT-2026-05-21`)
- any cross-fold / cross-config model selection records its trial
  count and runs through DSR / PBO per §9.6 (`AUDIT-2026-05-21`)

### Package P3 — Score calibration and score-to-weight mapping

Objective:

- convert model scores into controlled target weights

Required work:

- create `config/ml_allocation.yaml`
- implement:
  - score normalization
  - top-k bucket selection
  - clipped proportional sizing
  - volatility scaling
  - sector and beta neutralization options
  - min-edge-to-trade gate
- define explicit exit modes and re-entry behavior

Expected outputs:

- `config/ml_allocation.yaml`
- `data/audit/score_to_weight_smoke_*.json`

Gate:

- every portfolio acceptance run references one allocation config id
- every score-to-weight path is deterministic under fixed inputs
- no path can silently bypass risk caps

### Package P4 — Portfolio acceptance harness

Objective:

- prove that forecasts create useful portfolios

Required work:

- extend `dev/scripts/ml/r29_acceptance_r_ml_a_vs_b.py` or factor it into a reusable acceptance module
- support four paths:
  - non-ML baseline
  - ML sidecar
  - ML sidecar + partial rebalance
  - direct ranker-to-portfolio
- record cost sensitivity, concentration, participation, and benchmark-relative behavior

Expected outputs:

- `data/audit/ml_sign_portfolio_acceptance_*.json`
- `data/audit/ml_rank_portfolio_acceptance_*.json`
- `docs/memos/20260521-portfolio-acceptance-pack.md`

Gate:

- at least one ranker path completes full walk-forward portfolio acceptance
- all acceptance artifacts include score-to-weight mapping and cost assumptions
- any promoted ML path beats or ties the relevant baseline under stated gates
- the promoted path's edge survives DSR deflation at the true trial
  count and records PBO below the stated threshold (§9.6)
  (`AUDIT-2026-05-21`)

### Package P5 — Promotion governance and forward-readiness

Objective:

- connect the validated ML stack to the project's existing promotion / paper / forward governance

Required work:

- define how a validated ML spec is frozen
- define how source hashes, factor hashes, label configs, and allocation configs are frozen together
- define demotion triggers:
  - forward drift
  - data contract breach
  - allocation instability
  - cost blowout

Expected outputs:

- `docs/memos/20260521-ml-promotion-governance.md`
- artifact schema updates in forward / promotion path

Gate:

- a validated ML candidate can be frozen with one reproducible config bundle
- a forward run can detect source / factor / risk / allocation drift

### Package P6 — Expansion interfaces

Objective:

- make future enrichments additive instead of architectural rewrites

Required work:

- define extension hooks for:
  - text / filing / transcript features
  - options features
  - intraday features
  - sequence-model embeddings
- ensure each hook plugs into the same:
  - source contract
  - label contract
  - allocation contract
  - acceptance harness

Expected outputs:

- `docs/memos/20260521-ml-expansion-interfaces.md`

Gate:

- every new source family can be attached without changing the core promotion logic
- supplements are narrower than the master PRD and never override its hard controls

## 12.4 Milestone order

The required order is:

1. `P0`
2. `P1`
3. `P2`
4. `P3`
5. `P4`
6. `P5`
7. `P6`

No package may claim completion if any earlier package's hard gate is still red.

## 12.5 First implementation slice

If implementation starts immediately, the first concrete slice should be:

1. `config/ml_sources.yaml`
2. `config/ml_labeling.yaml` expansion
3. `train_ranker.py`
4. `walk_forward_ranker.py`
5. `config/ml_allocation.yaml`
6. ranker portfolio acceptance harness

That slice is the minimum viable master-spine implementation.

## 12.6 Deferred model-family roadmap

These model families should be documented in the repo roadmap, but not promoted into immediate implementation scope until the ranking baseline passes:

- `TCN / CNN / LSTM`
  - for intraday or event-path tasks
- `PatchTST / iTransformer`
  - for longer sequence modeling or factor-interaction modeling
- `MAE / TS pretraining`
  - for representation learning
- `GNN`
  - only after point-in-time relationship features prove useful
- `RL`
  - only for constrained sizing / execution overlays

Industry / research note:

- `PatchTST` remains a sensible first Transformer-family candidate because of patching and channel-independence
- `iTransformer` remains a sensible multivariate alternative because of variate-token attention
- neither changes the present implementation priority because the repo does not yet have a validated ranking-baseline-to-portfolio path on the active stack

## 13.1 External alignment notes

This PRD is aligned with external references as of:

- `July 26, 2024`: NIST AI RMF Generative AI Profile
- `February 2025`: IOSCO report “Artificial Intelligence in Capital Markets: Use Cases, Risks, and Challenges”
- current XGBoost learning-to-rank documentation
- current Qlib workflow / portfolio-strategy / backtest documentation
- `ICLR 2023` PatchTST
- `ICLR 2024` iTransformer

These sources do not force one unique design, but they do support the same high-level conclusion:

- separate modeling from portfolio construction and execution
- prefer strong baselines before more complex model families
- make validation, provenance, and ongoing controls first-class artifacts

They also support the project's next expansions:

- official filings / submissions data as a core event source
- macro data with release / vintage awareness
- ranking baselines before deep sequence models
- human-governed and auditable AI use in financial contexts

## 13. Auditability Requirements

This PRD is only considered implemented if all of the following are true:

- every decision has a machine-readable artifact
- every artifact includes config provenance
- every positive verdict can be reproduced with one checked-in command
- every negative verdict is preserved, not overwritten
- no result summary relies on notebook-only state

## 14. Final Recommendation

The next step is:

1. finish `R0 re-risk pack`
2. implement `R1-R4 ML hardening`, starting with a daily cross-sectional `LightGBM/XGBoost` ranking baseline
3. only then resume alpha mining

Current evidence does **not** justify skipping directly to new mining.

The project is now at the stage where:

- engineering parity is improving,
- risk translation still needs verification,
- ML methodology is promising but not yet trustworthy enough,
- and portfolio construction remains the binding bottleneck.

That is a good place to be honest from.

The most important revision from this review is:

- the first production ML target should be `point-in-time data -> residualized rank label -> GBDT ranking baseline -> purged walk-forward -> cost-aware portfolio mapping`

If that baseline does not produce stable OOS value, moving earlier to Transformer / MAE / GNN / RL would most likely add complexity faster than edge.
