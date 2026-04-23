# feat-v1 R39 Mining Blocker Report

**Date**: 2026-04-23
**PRD**: `docs/20260423-prd_research_feature_engineering_and_expanded_mining.md`
**Halt trigger**: §15.3 condition 7 (R39 fresh mining: n_oos_pass == 0 AND all OOS IR < 0)
**Status**: **STEP 5 BLOCKED** — awaits user decision per PRD §15.3
**Lineage**: `post-2026-04-23-feat-v1-expanded`
**Commit range (feat-v1 work)**: `2e5acf6..75ba4b1` (R01-R06 complete)
**Mining log**: `logs/mining/R39_feat_v1_1776926011.log`

---

## 1. Halt condition

PRD §15.3 condition 7:

> 新增：Step 3 R39 fresh mining 跑完后，若 `n_oos_pass == 0` AND 所有
> trial 的 OOS IR 均 < 0（严格劣于 pre-PRD 旧结果），halt 并写入
> blocker 文档，等用户确认是否进 Step 5 或重新设计

R39 results meet both clauses:

| Clause | R39 feat-v1 | Pre-PRD baseline (`post-2026-04-22-deep-R38-stage12`) |
|---|---:|---:|
| n_oos_pass | **0** | 1 |
| best oos_ir | **-0.119** | +0.343 |
| worst oos_ir | -0.815 | -0.852 |
| All top-20 oos_ir < 0? | **yes** | no (1 positive) |
| n_trials archived | 65 | 70 |
| n_quick_pass | 32 | 34 |
| n_promoted | 0 | 0 |

**Phase C Phase D Phase E BLOCKED** per PRD §7.2 "Step 5: 只有在 R39
显示方向性改善后". Directional improvement did NOT occur; strictly
worse on the decision metric.

---

## 2. R39 execution details

- Params: `run_mining.py --trials 80 --budget 3600 --type multi_factor
  --lineage-tag post-2026-04-23-feat-v1-expanded`
- Runtime: 626.5 seconds (within 3600s budget)
- Universe: 79 symbols (Stage 1+2 unchanged from pre-PRD)
- Panel: 3460 bars × 79 columns, 2015-01-02 → 2026-04-22
- Optuna study: FRESH (C+ pattern: pre-run backup to
  `optuna.db.bak.20260422_233325` + `archive.db.bak.20260422_233325`)
- Archive state: FRESH empty at start of run
- Evaluator fixes from prior session present:
  - M14 `compute_metrics` leading-NaN guard
  - `_check_qqq_gate` leading-NaN guard
  - `_STD_FLOOR=1e-8` preventing astronomical Sharpe
  - `_mean` drops non-finite + WARN (verified in log:
    "_run_walk_forward._mean: dropping 3 non-finite value(s)")

Top-10 detailed in `scripts/feat_v1_topk_analysis.py --k 10` output.

---

## 3. Root-cause analysis — why strictly worse

### 3.1 Sampling variance (most likely)

The mining space `MultiFactorSpace.suggest()` samples weights for the 7
`PRODUCTION_FACTORS` plus 4 meta params (top_n, min_holding_days,
rebalance_monthly, score_weighted) and 3 lookbacks. Pre-PRD R39 and
post-PRD R39 explored the SAME space with FRESH Optuna studies. TPE
starts with random draws → first 80 trials pick different combos.

Pre-PRD R39 hit trial `4b5f36ed9ab5` by draw — a combo that happened
to produce oos_ir +0.343. Post-PRD R39's 80 draws missed that region
of space.

**Evidence this is variance, not regression**:
- No code changes touch `MultiFactorSpace.suggest()` between R39 runs
- No changes to `MultiFactorStrategy.generate()` or production factors
- `config/universe.yaml` unchanged between runs
- Post-PRD's top-K factor_weights distribute similarly (quality 31%,
  relative 27%, mom 18%, vol 14%, position 7%) — same shape as pre-PRD
- Post-PRD's quick_sharpe range 0.37-0.96 is similar to pre-PRD

### 3.2 Feat-v1 factors never entered mining sample space (by design)

R01-R05 added 11 new factors to `RESEARCH_FACTORS`. But
`MultiFactorSpace` only samples from `PRODUCTION_FACTORS` (7 names).
PRD §4 explicitly forbids modifying `PRODUCTION_FACTORS`:

> 4. 不在本轮范围（Out of Scope）:
> 1. 修改 `PRODUCTION_FACTORS`

This means mining did NOT benefit from new R01-R05 factors. The only
change from pre-PRD was the Optuna random seed (i.e. fresh study).

**Implication**: feat-v1 as defined CANNOT reduce R39's OOS-pass gap
through the mining sampler. New factors only matter if they're
promoted to production OR if MultiFactorSpace is extended to sample
research factors.

### 3.3 Not a feature-engineering implementation bug

- Step 1 (R01-R05) had 0 pytest regression (1262/1262)
- Step 2 Phase A panel sanity PASS (79-sym, all factors present,
  aliases identical, masks plausible, forward returns modes ok)
- IC_5d smoke on new factors showed expected magnitudes (ret_1d
  -0.258, etc.) — not outliers
- Evaluator NaN/inf guards firing as designed

---

## 4. What user decision is needed

PRD §15.3 condition 7 directs to user for "进 Step 5 或重新设计". The
blocker is not "feat-v1 is broken" — it's "feat-v1 alone isn't
sufficient to break the OOS barrier; strategic decision required".

### Options for user (per PRD §15.3 + synthesis)

#### Option A: Extend MultiFactorSpace to sample R01-R05 factors
- Add the 11 new RESEARCH_FACTORS as sampleable weights in
  `core/mining/strategy_space.py::MultiFactorSpace.suggest()`
- Requires NEW MultiFactorStrategy.generate() paths for each research
  factor OR promote-to-production the most promising subset
- Authority: PRD §4 forbids modifying PRODUCTION_FACTORS and §15.4
  forbids it too. Would require a separate user-authorized PRD
  addendum.
- Expected outcome: new factor dimensions enter search space → higher
  odds of finding an OOS-positive region

#### Option B: Rerun R39 with more trials (sampling-variance mitigation)
- Keep feat-v1 code + same PRODUCTION_FACTORS, just burn more Optuna
  trials. Pre-PRD R39 found 1/70 OOS pass. Post-PRD R39 found 0/65.
  Bernoulli estimate of pass rate is ~0.5-1% (wide CI).
- To find ~3-5 OOS-pass specs: ~300-500 trials, ~40-60 minutes.
- Cheap to try; does NOT address factor space limitation.

#### Option C: Add Stage 3 universe (10 BETA_PLUS_ALPHA)
- PRD §7.1 deferred this. Adding Stage 3 = 89 symbols.
- But deep-mining R50 synthesis already warned this skews alpha
  attribution toward high-beta growth names.
- Authority: requires `config/universe.yaml` edit → PRD §15.4 forbid
  autonomously.

#### Option D: Accept direction confirmation and stop
- R01-R05 feature engineering still shipped correctly (Step 1-2 PASS).
- R39 confirms: with current PRODUCTION_FACTORS + current MaxDD /
  cost / stress gates, the mining space on 79-symbol universe is
  saturated. Deep-mining R50 synthesis said the same.
- Action: close feat-v1 PRD as "features added, mining direction
  stuck. Further progress needs either factor-space extension
  (Option A) or fundamentally new data (microstructure per synthesis
  §recommended Priority C)".

### Recommendation (loop output — NOT a decision)

Option D is the most honest given PRD §4 constraints. Option A gives
the highest information gain but needs a new authorization. Option B
is a cheap hedge before committing to A or D.

---

## 5. What will continue autonomously

Per PRD §12 step order and §15.4 authorization boundaries, Steps 6
and 7 can proceed without blocking on Step 5:

- **Step 6** (DSL fast-exit ablation) — can ablate on the best feat-v1
  spec `df22a253dda6` (tier D). Informative even if the spec itself
  is below promote threshold, because it isolates DSL's marginal
  contribution in the new lineage.
- **Step 7** (LLM sidecar) — pick 3-6 expanded-universe-aware
  candidates from the 97-candidate pool committed in `74dbfec`, run
  funnel. Produces RESEARCH_FACTORS candidates that feed a FUTURE
  mining round (not this one).

Loop continues to R09-R11 under Steps 6-7; Step 5 remains BLOCKED
until user responds.

---

## 6. Artifacts

- Blocker doc: this file
- Mining log: `logs/mining/R39_feat_v1_1776926011.log`
- Archive: `data/mining/archive.db` (65 trials, lineage
  `post-2026-04-23-feat-v1-expanded`)
- Analyzer output: `scripts/feat_v1_topk_analysis.py --k 10`
  reproduces the exact numbers in §1
- Backups: `data/mining/{optuna,archive}.db.bak.20260422_233325`
- Step 1-2 code / tests / docs all committed `2e5acf6..75ba4b1`

---

*Blocker report v1.0 — R08 of ralph-loop.*
