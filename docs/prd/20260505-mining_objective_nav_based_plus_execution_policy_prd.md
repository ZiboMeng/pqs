# PRD: Mining Objective NAV-Based + Execution Policy Hyperparameter

**Lineage tag**: `mining-objective-nav-2026-05-05`  
**Authored**: 2026-05-05  
**Revision**: v1.1 — 2026-05-05 (post-critique; 9 issues addressed per
`docs/memos/20260505-prd_ac_e_critique_log.md`)  
**Status**: DRAFT — awaiting user signoff before implementation  
**Authority**: User explicit-go 2026-05-05 ("ACE 都做"); cycle #04 close memo
strategic pivot path §"Change objective"; cycle #06 stop rule pre-committed
forbids cycle path without strategic pivot

---

## 1. Background

### 1.1 Cycle #04/#05 sibling problem

5 cycles of TPE mining (cycle #02 → cycle #05) all converged on
RCMv1/Cand-2 sibling space:
- Raw NAV correlation 0.85+ vs RCMv1+Cand-2 across 100+ archived trials
- IC_IR-ranked top-10 全 Tier 2 by R41 (factor_overlap + NAV correlation)
- cycle #04 cap_aware_cross_asset partial improvement (Cluster A 0.66-0.70)
  diagnosed as factor coverage gap side effect, NOT cross-asset alpha
- cycle #04 close memo pre-committed: "if cycle #05 also 0 nominee, NO
  cycle #06 mining without strategic pivot"
- cycle #05 = 0 nominee → stop rule triggered

### 1.2 Root cause analysis

Mining objective is currently **IC_IR-only weighted-sum**:
```
objective = w_ir × IR
          - w_turnover × turnover_proxy
          - w_corr_conc × corr_concentration
          + w_bench_excess × benchmark_excess
          - w_regime_stddev × regime_stddev
```
(per `core/mining/research_miner.py:913-944`)

**Cross-cycle IC_IR vs NAV-Sharpe rank correlation evidence** (top-10):
- cycle #04: IC_IR vs Sharpe Spearman = -0.12; vs vs_qqq = -0.12
- cycle #05: IC_IR vs Sharpe Spearman = +0.53; vs vs_qqq = **+0.05**

**Mining 选 high IC_IR 不会自动选 vs_qqq positive 的 spec** — 这正是
cycle #05 trial 9 fails CLAUDE.md QQQ outperformance rule 的根因。改
objective 加 NAV-based component 不是 vanity refactor，是 selection
mechanism 的 substantive change.

### 1.3 Execution policy 当前局限

PRD 20260505 Step 6.1-min ship 的 `frozen_spec.execution_policy.enable_sr_defer`
是 **ex-post overlay** — strategy 在 mining 后 frozen，then 在 frozen yaml
里 set `enable_sr_defer: true`。这意味着：
- Mining 没看到 SR defer 的影响
- IC_IR 计算用 composite signal × fwd return (rank correlation)
- SR defer 修改 target_wts (zero 一些 cells), 不修改 composite signal
- → IC_IR 完全 detect 不到 SR defer 影响
- → Mining objective 无法 evaluate "with SR defer" vs "without SR defer"

User explicit feedback 2026-05-05:
> "C 之前的问题是因为在已经选好的 strategy 上加了 SR 开关才导致的。我希望
> 他能够加入到 mining 的过程中来决定是否需要 turn on or off"

→ SR defer (and analogous timing modifiers, holding frequency choices)
应作为 mining hyperparameter, mining objective 自己 decide on/off, 不是
ex-post overlay.

---

## 2. Goal

扩展 mining objective 从 IC-only weighted sum 到 **multi-objective
NAV-based weighted sum**, 同时把 `execution_policy` (SR defer, holding
frequency) 作为 mining search dimension. Effect:
- Mining 同时 optimize IC_IR 和 NAV-Sharpe 和 cross-anchor NAV diversity
- SR defer / holding frequency 由 mining trial.suggest 决定, 跟 factor
  composition 一起 search
- Mining 时间 1.5-2x 增加 (R3 verified: per-trial NAV cost ~22s, 200 trials = 73 min)
- 5.4 OOS 严格保持 (mining 仍 train-only, partition_for_role(role="miner"))

---

## 3. Non-goals

- 不改 `core/research/forward/` runner (forward observation 路径不动)
- 不改 6.1-min plumbing (frozen_spec.execution_policy 字段保留, 仍是 forward
  runtime config; 但现在新 mining 输出会 stamp 该字段)
- 不破坏 cycle #04/#05 archive 兼容性 (老 trials 用 `objective_version=v1_legacy`,
  新 mining 用 `v2_nav_based`)
- 不改 sealed test access rules (2026 仍 single-shot)
- 不破坏 R41 anti-sibling policy (R41 仍 post-mining filter, 但现在 mining
  自己 minimize NAV correlation 应该减少 R41 reject rate)

---

## 4. Design

### 4.1 ObjectiveWeights extension

`core/mining/research_miner.py:902` 当前 `ObjectiveWeights` dataclass:
```python
@dataclass(frozen=True)
class ObjectiveWeights:
    w_ir: float
    w_turnover: float
    w_corr_conc: float
    w_bench_excess: float
    w_regime_stddev: float
```

**Add**:
```python
    w_nav_sharpe: float = 0.0           # default off — backward compat
    w_nav_max_dd_penalty: float = 0.0   # penalty on max_dd magnitude
    w_nav_orthogonality: float = 0.0    # penalty on raw NAV corr vs anchor
    w_vs_qqq_excess: float = 0.0        # bonus on validation-year vs_qqq positive
```

Default 全 0 → backward compat (cycle #04/#05 spec 用现有 weights 仍出原值).

### 4.2 CompositeMetrics extension

当前 `CompositeMetrics` (research_miner.py:797):
```python
@dataclass(frozen=True)
class CompositeMetrics:
    n_features: int
    n_families: int
    n_dates: int
    ic_mean: float
    ic_std: float
    ic_ir: float
    turnover_proxy: float
    corr_concentration: float
    horizon: int
```

**Add**:
```python
    nav_sharpe: float = float('nan')
    nav_max_dd: float = float('nan')
    nav_correlation_vs_anchor_pooled_raw: float = float('nan')
    nav_vs_qqq_excess_full_period: float = float('nan')
```

### 4.3 Mining-internal evaluator extension

`core/mining/research_miner.py:820-894` `evaluate_composite_spec`
(mining-internal, 与 `core/research/harness/composite_evaluator.py` 同名
不同函数) 当前只算 IC. **Add optional path**: if `objective_weights.w_nav_*`
任何 > 0, 调用 `core/research/harness/composite_evaluator.evaluate_composite_spec`
(ex-post version) 拿 NAV metrics, fold 进 CompositeMetrics:

```python
def evaluate_composite_spec(
    spec, factor_panel_map, fwd_returns,
    *,
    mask=None, horizon=21, lag=1,
    # NEW:
    price_df=None, open_df=None, spy_series=None, qqq_series=None,
    anchor_navs=None,  # dict[anchor_name → NAV series]
    compute_nav: bool = False,  # gate; only true when objective_weights need NAV
) -> CompositeMetrics:
    ic_mean, ic_std, ic_ir, turnover, corr_conc = ... (unchanged)
    
    nav_sharpe = float('nan')
    nav_max_dd = float('nan')
    nav_corr_anchor = float('nan')
    nav_vs_qqq = float('nan')
    if compute_nav:
        from core.research.harness.composite_evaluator import (
            evaluate_composite_spec as expost_eval
        )
        result = expost_eval(spec, factor_panel_map=factor_panel_map,
                              price_df=price_df, open_df=open_df,
                              spy_series=spy_series, qqq_series=qqq_series, ...)
        nav_sharpe = result.metrics_full_period.get('sharpe', float('nan'))
        nav_max_dd = result.metrics_full_period.get('max_dd', float('nan'))
        nav_vs_qqq = result.metrics_full_period.get('vs_qqq', float('nan'))
        if anchor_navs:
            nav_corr_anchor = compute_pooled_raw_correlation(result.nav, anchor_navs)
    
    return CompositeMetrics(... + nav fields)
```

### 4.4 compute_objective extension

```python
def compute_objective(metrics, ..., weights=None):
    ir_term = w.w_ir * ir
    turnover_term = -w.w_turnover * turnover
    corr_term = -w.w_corr_conc * corr_c
    bench_term = w.w_bench_excess * be
    regime_term = -w.w_regime_stddev * rs
    # NEW:
    sharpe_term = w.w_nav_sharpe * (metrics.nav_sharpe if isfinite(metrics.nav_sharpe) else 0.0)
    dd_term = -w.w_nav_max_dd_penalty * abs(metrics.nav_max_dd if isfinite(metrics.nav_max_dd) else 0.0)
    ortho_term = -w.w_nav_orthogonality * max(0, metrics.nav_correlation_vs_anchor_pooled_raw - 0.5)
    qqq_term = w.w_vs_qqq_excess * (metrics.nav_vs_qqq_excess_full_period if isfinite(...) else 0.0)
    return ir_term + turnover_term + corr_term + bench_term + regime_term \
         + sharpe_term + dd_term + ortho_term + qqq_term
```

### 4.5 Search space extension

`core/mining/research_miner.py:517-582` trial.suggest space 当前 search
features + weights. **Add**:

```python
# Search dimension 1: SR defer on/off
# I6 prefilter (revised): only enable SR defer search for specs where
# train-only NAV trajectory historically triggers ≥ 5% defer activation
# rate (sample efficiency — TPE 不会浪费 cell on equivalent trials).
sr_defer_eligible = (
    spec_baseline_defer_activation_rate(spec, train_only_panel) >= 0.05
)
enable_sr_defer_choices = [False, True] if sr_defer_eligible else [False]
enable_sr_defer = trial.suggest_categorical(
    "enable_sr_defer", enable_sr_defer_choices,
)

# Search dimension 2: holding frequency
holding_freq = trial.suggest_categorical(
    "holding_freq", ["daily", "weekly", "monthly"]
)

# Schema mapping: search dimension → frozen_spec yaml field
# (per core/research/frozen_spec.py:118 schema; I8 fix)
spec.execution_policy = {"enable_sr_defer": enable_sr_defer, "sr_defer": {...}}
spec.rebalance = {"freq": holding_freq, ...}  # NOT rebalance_cadence
```

Effect on search space:
- 200 trials with 2 SR (filtered) × 3 holding ≤ 6 hyperparameter combos
- TPE sampler distributes 200 trials across cells; sample efficiency
  improved by I6 prefilter (skip SR=true on ineligible specs)
- **Caveat (I2)**: 200 trials may not cover all cells effectively; if
  Phase 4 smoke shows < 4/6 cells explored, increase to 400 trials and
  re-run (mining time scales linearly).

**Schema mapping table** (PRD-AC search dim → frozen_spec yaml path):

| Search dim | trial.suggest | frozen_spec yaml field |
|---|---|---|
| factors | suggest_categorical | `feature_set[].name` |
| weights | suggest_float (simplex) | `feature_set[].weight` |
| enable_sr_defer | suggest_categorical (filtered) | `execution_policy.enable_sr_defer` |
| holding_freq | suggest_categorical | `rebalance.freq` |

### 4.6 Anchor selection (NAV orthogonality) — REVISED post-critique I1

R2 audit blocker: RCMv1+Cand-2 不能做 anchor (CLAUDE.md "will not
calibrate new-framework gates").

**Critique finding I1 (round 1)**: universe-equal-weight long-only
baseline is **structural sibling floor** for any long-only top-N spec
(raw NAV correlation ~0.85+ trivially). Using it as anchor → almost all
specs trip penalty → 0 archived OR mining gaming penalty by selecting
factor-coverage-thin specs.

**Revised solution** (post-critique):

**Option β (default)**: **SPY-residual NAV space**
- 算 spec NAV residual after regressing out SPY return (`r_spec - β × r_SPY`)
- **I19 fix**: β computation method = **train-only OLS regression**
  (single β across full train period; not rolling). Rationale: rolling β
  introduces look-back parameter complexity; full-period OLS is simpler
  and matches `core/research/harness/composite_evaluator._ols_beta` existing
  helper. Document β value in archive per trial.
- Penalize raw correlation between spec residual NAV and a universe-bound
  reference residual (universe-equal-weight residual NAV). The residual-
  level correlation isolates **alpha overlap** specifically, which is
  the problem worth solving (the universe-bound shared SPY beta is
  invariant given long-only constraint and not informative).
- More principled than α (universe-equal-weight raw NAV) because it
  separates structural beta from alpha overlap.
- **I20 fix — spec-class-conditional anchor**: SPY-residual approach
  assumes spec-vs-SPY beta is meaningful. For specs with significant
  cross-asset weight (>30% non-equity per `ASSET_CLASS_BY_CLUSTER`),
  spec-vs-SPY beta is low (~0.3-0.5) and residual is largely cross-asset
  alpha unrelated to SPY-bound floor. For these specs:
  - Either: skip SPY-residual orthogonality (treat as Option γ for that
    spec, retain other NAV gates)
  - Or: use cross-asset-equivalent anchor (e.g. universe-equal-weight
    cross-asset baseline residual)
  - Phase 4 smoke decides which approach; default = skip orthogonality
    for cross-asset specs (more permissive)

**Option γ (fallback)**: **None** (skip orthogonality, use only NAV-Sharpe
+ max_dd + qqq excess)
- Fall back if Phase 4 smoke shows β anchor still over-strict (e.g. >70%
  trials trip penalty even at moderate λ_orthogonality)

**Phase 4 anchor calibration smoke test**:
- Run 50 trials with β anchor at λ_orthogonality ∈ {0.0, 0.5, 1.0, 2.0}
- Plot trial count by orthogonality score (residual correlation) at each λ
- Pick λ where trial distribution shows meaningful frontier (some specs
  pass, some fail) — not "all pass" (λ=0 effective) and not "all fail"
  (γ fallback needed)
- If no λ produces meaningful frontier → fallback to γ; document in
  closeout memo as "anchor selection found over-strict in train-only
  universe-bound long-only top-N regime; orthogonality not viable
  selection mechanism in this framework"

**Risk acknowledged (per critique I1)**: ~50% probability that β anchor
falls back to γ. In that case, PRD-AC effort 4-5 周 produces
NAV-Sharpe + qqq excess optimization (similar value to (b) path
ex-post NAV ranking, but with SR defer / holding_freq in search space —
which is the user-aligned core requirement, not orthogonality).

### 4.7 Versioned objective

新增 `mining_config.objective_version: str = "v1_legacy"` field.

```yaml
mining_config:
  objective_version: v2_nav_based   # NEW
  objective_weights:
    w_ir: 0.7
    w_turnover: 0.05
    w_corr_conc: 0.05
    w_bench_excess: 0.0
    w_regime_stddev: 0.0
    # NEW:
    w_nav_sharpe: 0.15
    w_nav_max_dd_penalty: 0.05
    w_nav_orthogonality: 0.0   # off by default; smoke test 找最优
    w_vs_qqq_excess: 0.0       # off by default
  search_space_extension:
    enable_sr_defer: [false, true]
    holding_freq: [daily, weekly, monthly]
```

`v1_legacy` runs 全部 nav weights = 0 → 与 cycle #04/#05 一致 → backward
compat regression test pass. `v2_nav_based` runs 用新 weights.

### 4.8 5.4 OOS 严格保持

- Mining `--temporal-split config/temporal_split.yaml --role core` (与
  cycle #04/#05 一致)
- `partition_for_role(role="miner")` 返回 train-only ~3346 days
  (non-contiguous: 2009-2017 + 2020 + 2022 + 2024)
- Anchor NAV (SPY-residual or fallback) 也用 train-only 计算
- 2026 sealed: NEVER read in mining or anchor calc
- Stamp `panel_max_date` + `split_sha256` in archive (与 cycle #04/#05 一致)

---

## 5. Acceptance criteria

### 5.1 Backward compat (regression) — REVISED I3 + I9

- `objective_version=v1_legacy` 跑 cycle #04/#05 yaml clone:
  - **I3 fix**: top-20 trials' IC_IR Spearman rank correlation **> 0.95** vs
    cycle04/05 archive top-20 (TPE non-deterministic + factor data revision
    tolerated; rank stability is the testable invariant)
  - top-1 IC_IR / objective magnitude within ±5% of archive (looser than
    "4 decimal" original; non-determinism realistic)
- **I9 fix**: NAV path-dependence reproducibility on train-only non-
  contiguous panel:
  - v1_legacy mining cycle04 yaml clone produces NAV trajectory consistent
    with cycle04 archive trials' NAV (train_year boundary 2017-12-29 →
    2020-01-02 handle confirmed: BacktestEngine carries forward EOD
    positions across boundary OR per-segment compounded; whichever cycle04
    archive uses, v1_legacy reproduces)
  - explicit verification step in Phase 1: load 1 cycle04 archive top-1
    trial, replay its target_wts on partition_for_role(miner) panel,
    compare NAV vs archived NAV (≤ 50bps drift tolerated for floating-
    point precision; fail-closed if material drift surfaces boundary
    artifact)
- Old cycle04/05 archive trials remain readable
- frozen_spec.execution_policy backward compat (None 仍 means legacy path)

### 5.2 New objective deliverables — REVISED I2 + I4

- v2_nav_based smoke run on cycle #04 yaml clone (200 trials, train-only):
  - **I4 fix**: Mining wall-clock < **75 min** on train-only panel n≈3345
    (R3-AC-1 verified per-trial ~15s on train-only, ~22s on full panel;
    200 × 15s = 50min mining + IC overhead)
  - 全 200 trials archive includes nav_sharpe + nav_max_dd + nav_corr_anchor
    + nav_vs_qqq_excess_full_period
  - **I2 fix**: TPE sampling explored ≥ 4 of 6 (SR × holding) hyperparameter
    cells; **if explored < 4/6, increase to 400 trials and re-run mining**
- v2 objective rank top-10 vs v1 objective rank top-10:
  - Spearman rank correlation < 0.7 (selection materially differs)
  - At least 3 trials in v2 top-10 不在 v1 top-10
  - **I1 fix**: At least 1 trial in v2 top-10 has nav_correlation_vs_anchor
    (SPY-residual OR fallback baseline) below threshold (0.50 if Option β
    viable; threshold not enforced if Option γ fallback active)

### 5.3 Cycle #06 dry-run cycle — REVISED I7 (BLOCKER)

**BLOCKER fix**: Cycle #06 dry-run acceptance does NOT use R41 v2.0
verdict (R41 anchor = RCMv1+Cand-2 violates CLAUDE.md "will not
calibrate new-framework gates" invariant).

Replacement acceptance criteria:

- Use v2 objective + cap_aware_cross_asset construction (cycle #04 config
  retained for direct comparison)
- 200 trials (or 400 per I2 escalation), train-only via partition_for_role(miner)
- Acceptance gates (in order, all must pass for nominee):
  1. **Track A acceptance** per `core/research/temporal_split_acceptance.py`:
     - Per-validation-year vs SPY positive ≥ 4/5 (HARD)
     - Per-validation-year MaxDD ≤ 20% (HARD)
     - 2025 vs SPY positive (HARD per CLAUDE.md core role gate)
     - Stress slice MaxDD ≤ 25% (covid_flash + rate_hike_2022)
     - Cost robustness 2x multiplier (HARD)
     - Concentration top1 ≤ 0.40 + top3 ≤ 0.70 (HARD)
     - Beta to QQQ ≤ 0.85 (HARD)
  2. **Phase 4 smoke deliverables** (per §5.2):
     - v2 NAV-Sharpe ≥ v1 top-1 NAV-Sharpe (the spec materially better)
     - v2 NAV-vs-qqq excess > 0 (full period); validation years vs_qqq
       window-mean > 0 (per CLAUDE.md QQQ Outperformance Rule diagnostic)
  3. **Anchor orthogonality** (informational only, NOT a gate):
     - nav_correlation_vs_anchor recorded (SPY-residual or fallback);
       if Option β viable, target < 0.50; if γ fallback, skip
- Output ≥ 1 candidate passing gates 1+2 → cycle #06 nominee
- Output 0 candidate → strategic pivot deeper (PRD-E or beyond per
  cycle #04 close memo strategic options)

**Note on R41 sibling filter**: R41 v2.0 (RCMv1+Cand-2 anchor) remains
INFORMATIONAL diagnostic for cycle #06 output (recorded per cycle04/05
convention) but does NOT gate nominee status. R41 anchor revision (using
new-framework-eligible anchor pool) is OUT OF SCOPE for PRD-AC; tracked
as separate future work if anchor consensus is reached.

**I18 fix — edge case: R41 Tier 2 + Track A pass**:
- A spec passing all Track A gates + Phase 4 smoke gates BUT with R41
  v2.0 informational verdict = Tier 2 (sibling-by-NAV vs RCMv1+Cand-2)
  is structurally possible. Such a spec is "standalone good but
  NAV-correlated with legacy candidates".
- **Decision rule**: such a spec **counts as nominee** (passes acceptance)
  but the closeout memo MUST surface "R41 informational = Tier 2,
  sibling-by-NAV with RCMv1+Cand-2 raw NAV correlation [value]"
- **User directional decision** at promotion time: do we accept a Tier 2
  R41 spec as fleet member when RCMv1+Cand-2 are themselves not fleet
  members (legacy decay verification)? This is a Track D promotion
  decision, not a PRD-AC mining decision. PRD-AC delivers the
  evidence; user decides downstream.
- This treatment is consistent with PRD-E1 eligibility-not-freeze pattern
  (I11): mining produces nominee evidence; downstream Track D / forward
  observation freeze is separate gated decision.

---

## 6. Implementation plan

### Phase 1: Schema + ObjectiveWeights extension (1 周)

1. Extend `ObjectiveWeights` + `CompositeMetrics` (research_miner.py:797, 902)
2. Extend `compute_objective` weighted sum + tests
3. Schema migration: archive db `rcm_trials` 加 nav_sharpe / nav_max_dd / nav_corr_anchor cols (idempotent ALTER); `objective_version` col
4. Verify backward compat: v1_legacy reproduces cycle #04 numbers

### Phase 2: Mining-internal evaluator extension (1 周)

1. Add NAV calc gate in mining-internal `evaluate_composite_spec`
2. Reuse ex-post `core/research/harness/composite_evaluator.evaluate_composite_spec`
3. Anchor NAV builder: SPY-residual (Option β default) + fallback γ logic
4. **I9 verification task**: replay 1 cycle04 archive top-1 trial on
   partition_for_role(miner) panel via BacktestEngine, compare NAV
   trajectory vs cycle04 archive (target: ≤ 50bps drift). Verify
   train_year boundary (2017-12-29 → 2020-01-02 etc.) handle correctly.
5. Per-trial wall-clock benchmarks on train-only panel (target ≤ 20s/trial
   avg, R3-AC-1 measured 15s on train-only restricted)

### Phase 3: Search space extension (1 周)

1. Add `enable_sr_defer` / `holding_freq` to trial.suggest space
2. **I6 fix**: Implement `spec_baseline_defer_activation_rate(spec,
   train_only_panel)` prefilter — only enable SR=true cell for specs
   where historical train-only NAV trajectory triggers ≥ 5% defer
   activation rate (preserves TPE sample efficiency)
3. Wire `enable_sr_defer=True` to call sr_signal_filter on target_wts pre-NAV
4. **I8 fix**: Wire `holding_freq` to `rebalance.freq` schema field
   (NOT `rebalance_cadence`); confirm BacktestEngine accepts
5. Tests covering 2 × 3 = 6 hyperparameter combos (or fewer post-prefilter)

### Phase 4: Smoke run + cycle #06 dry-run (1-2 周)

1. **Anchor calibration smoke** (per §4.6): 50 trials at λ_orthogonality
   ∈ {0, 0.5, 1, 2}; pick λ producing meaningful frontier OR fall back γ
2. v2_nav_based smoke run on cycle #04 yaml clone (200 trials)
3. Acceptance criteria §5.2 verify (escalate to 400 trials if cells under-explored)
4. cycle #06 yaml draft (v2 objective + cap_aware_cross_asset, NO R41 gate
   per I7)
5. cycle #06 dry-run mining + Track A acceptance §5.3 verify
6. Closeout memo + commit

**Total: 4-5 周 (R3 verified; assumes anchor β viable; +1 周 if γ fallback
expedited via I1 anchor calibration smoke first)**

---

## 7. Risks + mitigations — REVISED I5 + I6

| Risk | Mitigation |
|---|---|
| Mining time 100+ min vs current 30-60 min (I4 corrected: ~75 min on train-only) | (1) only trigger NAV calc when w_nav_* > 0; (2) cache anchor NAV across trials; (3) per-trial wall-clock benchmark gate |
| Anchor selection β over-strict (50% fall back γ probability per I1) | Phase 4 smoke calibration on λ_orthogonality grid; fall back hierarchy β → γ → strategic pivot deeper |
| Multi-objective trade-off 调参成 art | Smoke run with grid of weight combos; document optimal in closeout; v1_legacy weights = 0 baseline preserved |
| TPE 200 trials 不够 cover 2×3 search dim (I2) | Acceptance §5.2 escalation to 400 trials if smoke shows < 4/6 cells explored |
| Backward compat regression (I3) | §5.1 fix: Spearman rank correlation > 0.95 over top-20 (not 4-decimal exact) |
| **I5 NEW: holding_freq=daily 高换手 + 高成本** | (1) cost_model 2x sensitivity test in Phase 4 smoke; (2) if daily cell consistently underperforms weekly/monthly across all specs, deprecate daily from search space in v2.1 follow-up |
| **I6 NEW: enable_sr_defer 在 NAV 不 enter resistance zone 的 spec 上跟 false 等价 → TPE 区分性损失** | Phase 3 prefilter `spec_baseline_defer_activation_rate ≥ 5%` (only enable SR=true cell for eligible specs) |
| **I7 NEW: cycle #06 dry-run originally used R41 verdict (anchor invariant violation)** | Acceptance §5.3 redesigned: Track A acceptance + Phase 4 smoke gates only; R41 informational diagnostic only |
| **I9 NEW: Train-only non-contiguous panel boundary artifact** | Phase 2 explicit verification task (replay cycle04 top-1 archive trial; compare NAV vs archived; ≤50bps drift gate) |
| **I8 NEW: holding_freq schema mapping ambiguity** | §4.5 schema mapping table; Phase 3 wire to `rebalance.freq` not `rebalance_cadence` |

---

## 8. Out of scope

- Track 2 PRD-E (TAA / regime allocation): independent track, separate PRD
- Cycle #06 ACTUAL mining (not dry-run): gated on Phase 4 smoke evidence
- Forward observation runner changes: no
- Sealed test runner changes: no
- Acceptance pack Gate 8 (M11 v3): independent

---

## 9. OOS discipline

- All mining train-only via `partition_for_role(role="miner")`
- Anchor NAV computed train-only
- Sealed 2026: 0 read
- Phase 4 smoke yaml records `panel_max_date`, `split_sha256`, `objective_version`,
  `objective_weights` in archive (per cycle #04/#05 convention)
- 5.4+ data: 0 consumption (mining train_years end 2024-12-31)

---

## 10. Reversibility

If v2_nav_based proves harmful:
- `objective_version=v1_legacy` still default-loadable
- Existing cycle #04/#05 archive remains readable (forever-frozen)
- `core/mining/research_miner.py` v2 code path can be deleted; v1 path preserved
- frozen_spec.execution_policy 仍 backward compat (None = legacy)

No data destruction, no manifest mutation. v2 is purely an additive
mining objective version.
