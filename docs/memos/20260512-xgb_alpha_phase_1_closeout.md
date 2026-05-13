# ML Phase 1 (XGBoost Alpha Mining) Closeout

**Date**: 2026-05-12
**Lineage**: `ml-xgb-alpha-phase-1-2026-05-12`
**PRD**: `docs/prd/20260512-ml_mining_pipeline_prd.md` §3
**User authorization**: 2026-05-12 "等cycle 9 完成 然后开始phase 1"

---

## §1 TL;DR

Phase 1 XGBoost alpha mining FIRES the PRD §3.9 abort condition:
**Phase 1 underperforms cycle09b linear baseline on the comparable
average per-validation-year vs SPY metric** (+7.95%/yr vs +15.31%/yr).

Strict pre-commitment: **suspend Phase 2+ pending user decision**.

However the verdict has nuance: XGBoost is **severely undertraining**
(best_iteration=0-4 across all folds, mean IC 0.012). Hyperparameter
mis-spec (early-stopping too aggressive, learning_rate too high, or
inner-val year 2017 not representative) may be masking real signal.

Three pre-authored next-step options for user decision:
- **A. Suspend Phase 2+ per pre-commitment** (strict interpretation)
- **B. Phase 1.5: hyperparameter sweep** before suspending (~2 days
  engineering, no production claim, evidence-driven re-evaluate)
- **C. Override and proceed to Phase 2 anyway** (user explicit-go
  required; demotes pre-commitment authority)

Operator recommendation: **B** — best_iter=0 is a strong signal that
the model can train more before hitting the abort flag.

---

## §2 Pipeline summary

| Step | Status | Detail |
|---|---|---|
| Panel build | ✅ | 4876 dates × 79 symbols (24s) |
| Multi-path factor build | ✅ | 159 factors (target 162; 3 missing per yaml exclusions) |
| Cross-sectional rank | ✅ | vectorized via cross_sectional_rank() (8s) |
| ML long-form panel | ✅ | 147,101 rows × 159 features (3,867 masked-out) |
| LOTYO 12-fold CV | ✅ | mean IC 0.012; 6/12 fold IC NaN (early years sparse) |
| Final model train | ✅ | best_iter=0 (early stop fires immediately) |
| Harness eval | ✅ | 5-validation-year top-10 cap_aware_cross_asset portfolio |
| Track A 17-gate | ❌ FAIL | 4 gates fail |

Wall-clock: 327s end-to-end on 79-sym × 17yr panel.

---

## §3 Detailed metrics

### 3.1 LOTYO 12-fold CV

| Fold y_test | n_test_rows | ic_mean | ic_std | best_iter |
|---|---|---|---|---|
| 2009 | (early-year sparse) | NaN | NaN | 1 |
| 2010 | (early-year sparse) | NaN | NaN | 2 |
| 2011 | (early-year sparse) | NaN | NaN | 1 |
| 2012 | (early-year sparse) | NaN | NaN | 0 |
| 2013 | (early-year sparse) | NaN | NaN | 0 |
| 2014 | (early-year sparse) | NaN | NaN | 0 |
| 2015 | 13302 | +0.0069 | 0.130 | 1 |
| 2016 | 12979 | -0.0622 | 0.132 | 1 |
| 2017 | 13153 | +0.0404 | 0.133 | (no val, inner=self) |
| 2020 | 13482 | +0.0129 | 0.125 | 0 |
| 2022 | 13482 | +0.0332 | 0.167 | 4 |
| 2024 | 12770 | +0.0405 | 0.096 | 0 |

**Mean IC across non-NaN folds**: 0.0120
**Sign**: 5/6 positive, 1 negative
**Magnitude**: very low — meaningful alpha typically requires IC > 0.05

**NaN-IC investigation (R3 audit)**: 6 folds (2009-2014) return NaN.
Likely cause: `compute_rank_ic` skips groups with fewer than 5 stocks
(line 137 in xgb_alpha.py). Early years have thinner data + fewer
mask-passing symbols per date → most dates excluded → empty per-date
IC series. **Mitigation in Phase 1.5**: relax min-group threshold or
exclude early years from train set explicitly.

### 3.2 Final model feature importance (top-15 by gain)

```
xsection_rank_63d                0.0326  (Family E momentum)
altman_re_to_assets              0.0254  (Family M solvency)
piotroski_low_warning            0.0247  (Family L quality)
sector_neutral_drawup_252d       0.0238  (Family B sector-neutral)
mom_126d                         0.0228  (Family A momentum)
piotroski_no_dilution            0.0211  (Family L quality)
magic_formula_rank_composite     0.0204  (Family L)
gross_profit_growth_yoy          0.0194  (Family N growth)
piotroski_net_income_positive    0.0192  (Family L)
fcf_to_assets_ttm                0.0185  (Family L cash flow)
dist_from_new_high_252           0.0185  (Family A momentum)
obv_norm_20d                     0.0180  (Family G volume)
drawdown_current                 0.0175  (Family B)
altman_ebit_to_assets            0.0169  (Family M)
sector_breadth_pct_5d            0.0157  (Family O sector)
```

**Diversity**: top-15 spans 7 different factor families. **Notable**:
`rd_intensity_ttm` (cycle09b's dominant factor) ranks 22nd at gain
0.0125 — XGBoost doesn't recover the linear composite's dominant
signal as the #1 driver. This suggests:
- Linear composite's heavy reliance on `rd_intensity_ttm` may be an
  overweighting artifact specific to monthly top-N construction
- XGBoost's tree-ensemble naturally spreads importance across
  correlated factors (e.g. Piotroski components)

### 3.3 Harness evaluation (validation years 2018/19/21/23/25 only)

| Metric | Value |
|---|---|
| n_observed_days | 1409 |
| cum_ret | +288.8% |
| sharpe | 1.118 |
| max_dd | -17.6% |
| vs_spy | +134.2% |
| vs_qqq | +1.8% |
| beta_vs_spy | -0.016 |
| beta_vs_qqq | +0.552 |
| raw_pearson_vs_spy | -0.021 |
| **raw_pearson_vs_qqq** | **0.770** |
| m12_top1_weight_max | 21.17% |
| m12_top3_weight_max | 45.11% |

### 3.4 Per-validation-year breakdown

| Year | max_dd | vs_spy | vs_qqq | gate |
|---|---|---|---|---|
| 2018 | -17.6% | +5.1% | +0.9% | PASS |
| 2019 | -7.9% | **-3.8%** | -10.3% | FAIL vs SPY |
| 2021 | -7.6% | +39.2% | +36.0% | PASS |
| 2023 | -10.9% | +7.6% | -19.2% | PASS |
| 2025 | -17.4% | **-8.4%** | -12.8% | **FAIL vs SPY (HARD)** |
| avg  | -12.3% | **+7.9%** | -1.1% | — |

**3/5 years vs SPY > 0** vs required ≥ 4/5 → `validation_aggregate_excess_vs_spy` FAIL.

### 3.5 Stress slices (empty)

**Process bug found**: `metrics_per_stress` is empty in result —
stress slices (covid_flash 2020-02-19 to 2020-03-23, rate_hike_2022
2022-01-03 to 2022-09-30) live in TRAIN years, but the script's
`predict_panel = panel[panel["year"].isin(predict_years)]` restricts
predictions to validation_years only. Harness then has empty score_df
for stress slice dates → no stress metrics computed → Track A
fail-closes on "stress slice maxdd" gates.

**Fix for Phase 1.5**: predict on train+validation panel (NOT sealed),
score over full selector partition; this is what cycle04-08 linear
mining does. The current script's restrict-to-validation was overly
conservative — it was intended to avoid in-sample evaluation but
stress slices need predictions too.

### 3.6 Track A 17-gate verdict

**FAIL** on 4 gates:
- `validation_aggregate_excess_vs_spy` — only 3/5 years positive
- `stress_slice_covid_flash_maxdd` — stress empty (process bug)
- `stress_slice_rate_hike_2022_maxdd` — stress empty (process bug)
- `role_core__validation__2025__excess_vs_spy` — 2025 -8.4% (hard fail)

---

## §4 vs Cycle #09b linear baseline comparison

### 4.1 Apples-to-apples per-validation-year

| Metric | Phase 1 (XGBoost) | Cycle09b Trial 1 (linear) |
|---|---|---|
| 2018 vs_spy | +5.1% | +7.2% |
| 2019 vs_spy | **-3.8%** | +9.0% |
| 2021 vs_spy | +39.2% | +7.5% |
| 2023 vs_spy | +7.6% | +35.6% |
| 2025 vs_spy | **-8.4%** | +17.2% |
| **avg vs_spy** | **+7.9%** | **+15.3%** |
| **n_pass (vs_spy > 0)** | **3/5** | **5/5** |

**Phase 1 vs SPY ½ of linear baseline** on per-year average; **3/5 vs
5/5 hard-gate compliance**. Phase 1 STRICTLY UNDERPERFORMS linear
baseline on the metric pre-committed in PRD §3.9 abort condition.

### 4.2 Other dimensions

| Dimension | Phase 1 | Cycle09b Trial 1 | Δ |
|---|---|---|---|
| raw_pearson_vs_qqq | **0.770** | 0.851 | Phase 1 better diversification |
| raw_pearson_vs_spy | -0.021 | -0.092 | Phase 1 closer to SPY-orthogonal |
| Sharpe (period varies) | 1.118 | 1.127 | tied |
| max_dd (period varies) | -17.6% | -21.7% | Phase 1 better |

**Notable**: Phase 1's raw_pearson_vs_qqq (0.770) is BELOW cycle09b's
0.851 sibling threshold. This is the FIRST candidate on the post-cycle04
trail with sub-0.85 vs QQQ — STRUCTURAL diversification win. But it
loses on the primary alpha metric.

---

## §5 Pre-committed §3.9 abort condition

PRD §3.9 quote:
> "Phase 1 XGBoost 8-yr vs SPY excess < cycle04-08 linear baseline
>  excess → ML 不优于 linear → **暂停 Phase 2+**"

Verification:
- Phase 1 avg per-year vs_spy = +7.95%
- Cycle09b Trial 1 avg per-year vs_spy = +15.31%
- 7.95 < 15.31 → **ABORT CONDITION FIRES**

**Strict interpretation**: Phase 2+ suspended; awaiting user decision.

---

## §6 Diagnosis — why XGBoost undertrains

Three hypotheses, ordered by likelihood:

### H1 (most likely): inner-val year 2017 too short for early stopping
- Train (2009-17 + 2020/22/24) = 12 years
- Inner-val (2017) = 1 year ~12,000 rows
- Default early_stopping_rounds=20 with n_estimators=200
- All folds best_iter ∈ {0, 1, 2, 4} → val IC peaks at round 0-4 then
  monotonically degrades
- This may reflect val 2017 having LOW signal-to-noise (a quiet bull
  year) where any tree depth degrades cross-sectional rank IC
- **Phase 1.5 fix**: try multi-year inner-val (rolling 2016-2017) or
  use the natural LOTYO holdout fold (y_test as val for stopping)

### H2: learning_rate=0.05 too high for noisy cross-sectional IC target
- Typical alpha-mining XGBoost: lr=0.01-0.02 with n_estimators=500-1000
- PRD §3.2 spec lr=0.03-0.10 — chosen 0.05 (middle)
- With noisy target (forward returns), low lr + many estimators
  helps tree ensemble find robust signal
- **Phase 1.5 fix**: lr=0.02, n_estimators=500

### H3: 21d horizon too noisy
- Cross-sectional rank of 21d forward returns has high variance
- Phase 1 IR  per fold std ~0.13 vs ic_mean ~0.01-0.04 → mean is in
  the noise
- **Phase 1.5 fix**: try 63d horizon (smoother medium-term signal)
  OR multi-horizon ensemble (Phase 2 idea, but as Phase 1.5 sub-study)

### Not likely H4: 162 factors over-parameterizing the model
- Sample:feature ratio 147101/159 = 925:1 — well above XGBoost's
  comfort zone
- max_depth=5 + reg_alpha=0.1 + reg_lambda=0.1 provides regularization
- Top-15 importance distribution spans 7 families — not signs of
  over-concentration

---

## §7 Three pre-authored next-step options

### Option A: STRICT — suspend Phase 2+ per pre-commitment

- Honor PRD §3.9 abort condition as written
- Pause ML workstream; do NOT touch Phase 2/3/4
- Pivot back to: forward-init cycle09b Trial 1 (subject to §5 audit
  clearance) OR alt-archetype expansion per cycle04-08 stop-rule
- **Cost**: 0 engineering; loses ML evidence not gathered yet
- **Risk**: if XGBoost was undertraining due to fixable hyperparams,
  we declare ML "doesn't work" prematurely
- **Authority**: pre-committed; this is the DEFAULT path

### Option B: PHASE 1.5 — hyperparameter sweep before suspending

- ~2 days engineering: 3 axes × 2-3 values each = 9-18 sweep configs
  - learning_rate ∈ {0.01, 0.02, 0.05}
  - n_estimators ∈ {200, 500, 1000} (with early stop)
  - inner_val_year strategy ∈ {single 2017, multi 2016-2017,
    LOTYO-fold-as-val}
- Acceptance: ANY sweep config beats cycle09b avg per-yr vs_spy = 15.3%
  → unsuspend Phase 2+; pick best config as Phase 1 final
- If all 9-18 sweeps fail to beat baseline → strong evidence ML
  approach is structurally inferior on PQS panel → respect §3.9 with
  more confidence
- **Cost**: 2 days engineering + GPU/CPU run time (each sweep config ~5 min)
- **Risk**: if no sweep config beats baseline, we spent 2 days on
  negative result
- **Authority**: user explicit-go (overrides pre-commitment with
  evidence requirement)

### Option C: OVERRIDE — proceed to Phase 2 anyway

- Skip §3.9 abort; start Phase 2 multi-horizon regression
- Hypothesis: 21d alone is too noisy; multi-horizon ensemble may show
  the alpha that single-horizon Phase 1 missed
- **Cost**: ~1 week engineering for Phase 2 + same Phase 3/4 cascade
- **Risk**: violates pre-commitment authority; if Phase 2 also fails
  we've spent 2 weeks on negative result
- **Authority**: user explicit-go REQUIRED + memo of override
  reasoning (CLAUDE.md autonomous decision rules)

**Operator recommendation**: **Option B** — best_iter=0 is too strong
a signal to ignore. The model deserves the chance to actually train
before we judge ML approach overall.

---

## §8 Process audit (4-tier per CLAUDE.md)

**R1 factual**: phase_1_summary.json contains the result; reproduced
in audit Python snippet (numbers match script log).

**R2 logical**:
- Mean IC 0.012 is positive but indistinguishable from zero with
  ic_std ~0.13 across folds
- Track A FAIL is correct per the metrics shown (3/5 years vs_spy > 0)
- §3.9 abort condition correctly applied (7.95 < 15.31)

**R3 actually-run-the-code**: 327s wall-clock, completed without
exceptions. NAV/weights/benchmark saved to data/ml/xgb_alpha_phase_1/.

**R4 boundary**:
- 6/12 LOTYO folds returning NaN IC is a process bug (compute_rank_ic
  min-group threshold); should be fixed before Phase 1.5
- Stress slices empty is a process bug (predict_years restriction);
  should be fixed before any re-evaluation
- best_iter=0 across all folds is a fragility — model is essentially
  using only the bias term + first split; any conclusion drawn from
  this config is highly sensitive to hyperparameter choice
- raw_pearson_vs_qqq 0.770 is the FIRST sub-0.85 result on the
  cycle04-09 trail — even if Phase 1 fails on alpha, this is a real
  structural finding worth recording

---

## §9 Forensic artifacts

- Summary: `data/ml/xgb_alpha_phase_1/phase_1_summary.json`
- NAV: `data/ml/xgb_alpha_phase_1/nav.csv`
- Weights: `data/ml/xgb_alpha_phase_1/weights.parquet`
- Benchmarks: `data/ml/xgb_alpha_phase_1/benchmark_{spy,qqq}.csv`
- Run log: `/tmp/xgb_full.log` (transient — not committed)
- Modules: `core/ml/{feature_panel_builder,xgb_alpha}.py`
- Driver: `scripts/run_xgb_alpha_mining.py`
- Tests: `tests/unit/ml/test_{feature_panel_builder,xgb_alpha}.py` (20 tests, 100% pass)

ML workstream paused at this boundary. Next action requires user-go
on §7 Option A/B/C.
