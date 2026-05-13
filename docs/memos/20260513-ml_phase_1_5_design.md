# ML Phase 1.5 — Hyperparameter Sweep Design

**Date**: 2026-05-13
**Authority**: User explicit-go 2026-05-13 ("B 立刻开 audit") authorized closeout `docs/memos/20260512-xgb_alpha_phase_1_closeout.md` §7 Option B.
**Scope**: 2-day eng — evidence-driven sweep to determine whether XGBoost can beat cycle09b linear baseline before respecting PRD §3.9 abort.
**Parent**: `docs/prd/20260512-ml_mining_pipeline_prd.md` §3 + closeout memo
**Lineage**: `ml-xgb-alpha-phase-1-5-sweep-2026-05-13`

---

## §1 TL;DR — 人话版

ML Phase 1 (XGBoost) 在 §3.9 abort 条件下失败：3/5 validation years vs SPY > 0 (vs required ≥ 4/5)，per-year avg +7.95% vs cycle09b linear baseline +15.31%。

但 closeout §6+§7 抓到一个关键信号：所有 12 个 LOTYO fold 的 **best_iter ∈ {0, 1, 2, 4}** = XGBoost 早 stopping fires 太早 = 模型几乎没真正训练。

Phase 1.5 hypothesis: 调对 hyperparameter 后 XGBoost 能学到 cycle09b linear baseline 找不到的非线性 alpha。

Sweep matrix（3 轴 × 3 值 = **27 configs**，PRD audit 后保守扩到 27 而不是 §7 提到的 9-18）:
- learning_rate ∈ {0.01, 0.02, 0.05}
- n_estimators ∈ {200, 500, 1000}
- inner_val_strategy ∈ {single_2017, multi_2016_2017, lotyo_fold_as_val}

Pre-committed acceptance:
- **PASS**: ANY 1+ sweep config 击败 cycle09b avg per-yr vs_spy = **+15.31%** → 解封 Phase 2+
- **FAIL**: 全部 27 configs 都不达标 → 强证据 ML 在 PQS panel 上结构性不行 → 永久 deprecate ML mining axis

---

## §2 Process bugs to fix before sweep (P0)

Phase 1 closeout §3.5 + §8 R4 列了 2 个 process bug；不修就 sweep 是浪费。

### §2.1 Bug 1: NaN-IC in early years (closeout §3.1)

6 of 12 LOTYO folds (2009-2014) return `ic_mean = NaN`。

**Closeout 初判**: "compute_rank_ic skips groups with fewer than 5 stocks (line 137 in xgb_alpha.py); early years thinner data → empty per-date IC series".

**R3 deeper check needed**: actually run `compute_rank_ic` on 2009 fold inputs + 观察 skip 触发的具体 dates。若每个 date 都被 < 5 nunique 或 std=0 跳过 → bug 是 mask 太激进。若部分 date 有 ≥ 5 → bug 是其他逻辑。

**Pre-committed fix path**:
- (a) Lower min-group threshold 5 → 3 → 看 NaN 比例下降
- (b) Exclude early years from train set explicitly (skip 2009-2014 if `_n_finite_dates < 100`)
- (c) Investigate model output: 若 y_pred.std() == 0 in early years → model 出 constant prediction → 是 NaN-feature propagation 触发的，需要 fillna 策略

Decision: 实施 (a) + (c) 同时尝试。Track A 评估时观察 IC 分布。

### §2.2 Bug 2: Empty stress slices (closeout §3.5)

Phase 1 driver `scripts/run_xgb_alpha_mining.py` restricts predictions to `validation_years` only (2018/19/21/23/25)。Stress slices (covid_flash 2020-02-19, rate_hike_2022 2022-01-03) 落在 TRAIN years → 没 predictions → harness fail-closed on stress maxdd gates.

**Fix**: predict on **train + validation panel** (NOT sealed)，score over full selector partition。Mirrors cycle04-08 linear mining behavior. PRD §3.3 + temporal_split discipline preserved (no sealed leakage, sealed=2026 still untouched).

### §2.3 Engineering effort

- Bug 1: ~3 hours (R3 investigation + fix + 5 unit tests)
- Bug 2: ~1 hour (script edit + integration test)
- Total: half-day

---

## §3 Sweep matrix (3 × 3 × 3 = 27 configs)

### §3.1 Axis A: learning_rate

| Value | Rationale |
|---|---|
| 0.01 | Conservative; typical alpha-mining XGBoost setting; needs many trees |
| 0.02 | Closeout-suggested fix in §6 H2 |
| 0.05 | Phase 1 default; if still slow learner this confirms structural issue |

### §3.2 Axis B: n_estimators

| Value | Rationale |
|---|---|
| 200 | Phase 1 default |
| 500 | Closeout-suggested in §6 H2 |
| 1000 | Aggressive; tests whether deep ensemble helps |

Early stopping rounds = max(20, n_estimators // 10) — gives proportional patience.

### §3.3 Axis C: inner_val_strategy

| Value | Implementation |
|---|---|
| `single_2017` | Phase 1 default; use 2017 as fixed inner-val for early stopping |
| `multi_2016_2017` | Concat 2016 + 2017 inner-val (more validation samples); reduces noise sensitivity |
| `lotyo_fold_as_val` | Use the LOTYO fold's own held-out year (Y_test from prev fold) as val — leak-safe IF strict ordering enforced; needs new harness |

`lotyo_fold_as_val` is the most invasive but addresses closeout §6 H1 hypothesis (2017 might be low-signal year).

### §3.4 Total configs

27 sweep configs × ~5 min/config = ~135 min wall-clock if sequential.

Parallelizable (each config independent). With 4 workers (CPU cores 8): ~35 min。

### §3.5 Storage budget

Each config produces: nav.csv (~1MB) + weights.parquet (~5MB) + benchmark_{spy,qqq}.csv (~0.5MB each) + summary.json (~10KB). 27 configs × ~7MB = **~190 MB total** for sweep artifacts. Acceptable.

---

## §4 Pre-committed acceptance (per closeout §7 Option B)

### §4.1 Primary metric

Phase 1's metric for §3.9 abort: **avg per-validation-year excess vs SPY**.

| Comparison target | Value |
|---|---|
| cycle09b Trial 1 (linear) | **+15.31%/yr** |
| ML Phase 1 (Phase 1 default config) | +7.95%/yr (FAIL) |
| **Phase 1.5 acceptance threshold** | **ANY sweep config > +15.31%/yr → PASS** |

### §4.2 Secondary metric (informational)

| Metric | Phase 1.5 threshold |
|---|---|
| Per-validation-year vs SPY > 0 | ≥ 4/5 years (cycle09b: 5/5; Phase 1: 3/5) |
| Track A 17-gate full PASS | 0 fail (cycle09b Trial 1: 0 fail; Phase 1: 4 fail) |
| best_iteration distribution | Median best_iter > 50 (Phase 1: 0-4) — indicates training was reached |
| Mean LOTYO IC across non-NaN folds | > 0.030 (Phase 1: 0.012) |

If primary fails BUT secondary improvement is substantial (e.g. best_iter median > 100 + Mean IC > 0.030) → discuss with user before final FAIL verdict; may be sweep-config-specific issue.

### §4.3 Stop rule (per closeout §3.9 spirit)

- PASS: pick best-performing sweep config as **Phase 1 final**; deprecate Phase 1.5 closeout; unsuspend Phase 2+
- FAIL: all 27 configs fail primary → respect PRD §3.9 with more confidence; ML mining axis paused indefinitely; document FAIL findings as evidence ML is structurally inferior on PQS 78-stock long-only top-N construction

### §4.4 Anti-sibling check (additional gate per closeout §8 R4)

Phase 1's raw_pearson_vs_qqq = 0.770 is **first sub-0.85 result** on cycle04-09 trail = structural diversification win.

Phase 1.5 acceptance must preserve or improve this: best config's raw_pearson_vs_qqq must be < 0.85 AND raw_pearson_vs_RCMv1 / Cand-2 < 0.85 on extended panel.

If best primary-metric config has 0.85+ NAV correlation with any anchor → **不能 forward-init as core_alpha** (revert to diversifier route) — same logic as cycle09b §5.1 verdict tension.

---

## §5 Implementation plan

### §5.1 Step 1 — Process bug fixes (P0, ~half day)

- `core/ml/xgb_alpha.py::compute_rank_ic`: add min-unique-stocks parameter (default 3, was hardcoded 5)
- `core/ml/xgb_alpha.py::leave_one_train_year_out_cv`: add `min_finite_dates` filter to skip years with insufficient data
- `scripts/run_xgb_alpha_mining.py`: change `predict_panel = panel[panel["year"].isin(predict_years)]` → predict on full selector partition (train+validation; document why sealed stays untouched)
- 8 unit tests in `tests/unit/ml/test_xgb_alpha_phase_1_5.py`

### §5.2 Step 2 — Sweep driver (P0, ~half day)

- `scripts/run_xgb_alpha_phase_1_5_sweep.py` — wraps Phase 1 pipeline with config grid
- Iterates 27 configs; each one trains + predicts + harness-evals + writes summary
- Saves master grid result CSV: `data/ml/xgb_alpha_phase_1_5/sweep_grid.csv`
- Each config's outputs at `data/ml/xgb_alpha_phase_1_5/{config_id}/`

### §5.3 Step 3 — Sweep execution (P1, ~1 hour wall-clock)

- Parallel via Python multiprocessing OR sequential with `--config-filter`
- All 27 configs OR early stop if 3 consecutive configs FAIL (heuristic operator stop)

### §5.4 Step 4 — Phase 1.5 closeout memo (P1, ~half day)

- `docs/memos/20260513-ml_phase_1_5_closeout.md`
- §1 best config summary
- §2 sweep grid table
- §3 per-axis sensitivity analysis (which axis moved the needle)
- §4 verdict against acceptance criteria
- §5 next-step recommendation

---

## §6 Stop rule pre-commitment + escalation

If all 27 configs fail primary metric:
1. Document findings in closeout memo (no further sweep)
2. Permanently deprecate ML mining axis (Phase 2+3+4 PRD sections moved to archived/)
3. Operator pivot recommendation:
   - cycle10 designed for construction-DOF (weekly + cross-asset + dual-horizon)
   - alt-archetype B (event-calendar) + alt-archetype C (cross-asset rotation) untested
   - Options sleeve TD60 verdict ~2026-07-30 (independent workstream)

If 1-3 configs pass primary:
1. Pick best, document tertiary metrics
2. ALL passing configs must clear §4.4 anti-sibling check; otherwise pivot to diversifier-role candidate
3. Phase 2 Multi-horizon ensemble eligible for user-go

If ≥ 4 configs pass:
1. Strong signal hyperparameter tuning matters
2. Pick best, AND fire Phase 2 Multi-horizon for evidence stacking
3. Phase 3 + Phase 4 unblocked

---

## §7 Self-audit (4-tier per CLAUDE.md)

**R1 factual**: design memo specifies 27-config sweep matrix, 2 process bugs to fix, pre-committed PASS threshold = +15.31%/yr per-year avg vs SPY.

**R2 logical**: best_iter=0-4 across 12 folds is fragility — model essentially uses bias + first split. Sweep on lr / n_estimators / inner_val_strategy directly tests whether this fragility is hyperparameter-driven or structural. Acceptance threshold aligns with PRD §3.9 abort metric definition.

**R3 actually-run-code**: TBD — sweep harness implementation + bug fixes ~1 day. NOT yet run.

**R4 boundary**:
- 27 configs is upper bound of "reasonable sweep"; if 100+ configs needed, structural issue
- If Phase 1.5 PASS but anti-sibling FAIL on extended panel → still NOT immediately deployable; same gate as cycle09b Trial 1
- If primary FAIL but best_iter > 50 + mean_ic > 0.030 → 见 §4.2 secondary path → discuss with user
- Sweep budget hardcoded; if sweep produces no PASS by config #15, operator can early-terminate per §5.3 heuristic

---

## §8 Risk register

| Risk | Mitigation |
|---|---|
| Sweep PASS but NAV anchor correlation ≥ 0.85 vs cycle04-09 candidates | §4.4 anti-sibling gate |
| Sweep PASS but best config is overfit to single fold | Multi-axis sensitivity in closeout §3 |
| Sweep FAIL across all 27 — but XGBoost on different feature transform still works | §6 escalation: if user pivots to feature engineering, that's separate scope |
| Process bug fixes change Phase 1 baseline numbers (re-test) | Re-run Phase 1 default config under bug-fixed code; if changes, document delta |
| sweep CPU cost | 27 × 5 min = 135 min sequential / 35 min parallel; CPU-bound; can run overnight |

---

## §9 Engineering estimate

| Phase | Effort |
|---|---|
| §2 bug fixes + 8 unit tests | 0.5 day |
| §5.2 sweep driver | 0.5 day |
| §5.3 sweep execution | ~1 hour wall-clock |
| §5.4 closeout memo + sensitivity analysis | 0.5 day |
| **Total** | **~1.5 day** (less than the 2-day budget) |

Reserved buffer 0.5 day for unexpected debug needs.

---

## §10 Fire timing

- §5.3 seed=123 cycle09b replication mining (in progress, ~25 min more) currently uses CPU — sweep should fire AFTER it completes to avoid contention
- Phase 1.5 sweep budget ≈ 1 hour wall-clock
- Whole Phase 1.5 (bug fix + sweep + closeout) ≈ ~1.5 day

Today's checkpoint plan:
1. cycle09b §5.3 finishes → append §5.3 verdict to amendment memo
2. cycle09b final forward-init decision (operator-tactical, but seeks user input on yaml-vs-cycle07a threshold canonical choice)
3. Phase 1.5 bug fixes commit
4. Phase 1.5 sweep driver commit
5. Phase 1.5 sweep fire (background, ~1 hour)
6. Phase 1.5 closeout memo + verdict

Sweep result expected ~tomorrow morning operator session if fired before EOD today.
