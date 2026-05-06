# PRD: Mining Objective NAV-Based + Execution Policy Hyperparameter

**Lineage tag**: `mining-objective-nav-2026-05-05`  
**Authored**: 2026-05-05  
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
enable_sr_defer = trial.suggest_categorical("enable_sr_defer", [False, True])

# Search dimension 2: holding frequency
holding_freq = trial.suggest_categorical(
    "holding_freq", ["daily", "weekly", "monthly"]
)

# These get baked into spec as execution_policy + rebalance.cadence
spec.execution_policy = {"enable_sr_defer": enable_sr_defer, ...}
spec.rebalance_cadence = holding_freq
```

Effect on search space:
- 200 trials with 2 SR × 3 holding = 6 hyperparameter combos
- TPE sampler will distribute 200 trials across 6 cells (sample efficient)
- 不强制每个 cell 33 trials, TPE 自己 explore

### 4.6 Anchor selection (NAV orthogonality)

R2 audit blocker: RCMv1+Cand-2 不能做 anchor (CLAUDE.md "will not
calibrate new-framework gates").

**Solution**: 用 **synthetic baseline anchor**, 不用 fleet member:

Option α (default): **universe-equal-weight long-only baseline**
- Train-only universe (53 stocks + 6 cross-asset ETFs minus drop_symbols)
- Equal weight, monthly rebalance, top-N=10
- This IS the "structural sibling space" floor — any spec strongly
  correlated with this baseline is universe-bound

Option β: **SPY beta-residual NAV space**
- 算 spec NAV residual after regressing out SPY return
- Penalize residual NAV correlation with universe-equal-weight baseline residual
- 跟 Option α 对比: 更严, 因为 SPY beta 已 strip 出, 剩下的 raw correlation
  全部是 alpha overlap

Option γ: **None** (skip orthogonality, use only NAV-Sharpe + max_dd + qqq excess)
- Fall back if both α+β anchor 选不出 nominee

**Default**: α (universe-equal-weight baseline). Phase 1 try; if 0 nominee,
fall back γ.

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
- Anchor NAV (universe-equal-weight baseline) 也用 train-only 计算
- 2026 sealed: NEVER read in mining or anchor calc
- Stamp `panel_max_date` + `split_sha256` in archive (与 cycle #04/#05 一致)

---

## 5. Acceptance criteria

### 5.1 Backward compat (regression)

- `objective_version=v1_legacy` 跑 cycle #04/#05 yaml → 原 objective 数值
  (top-1 trial 跟 archive top-1 一致, IC_IR identical to ≤ 4 decimal places)
- Old cycle04/05 archive trials remain readable + R41 verdict reproducible
- frozen_spec.execution_policy backward compat (None 仍 means legacy path)

### 5.2 New objective deliverables

- v2_nav_based smoke run on cycle #04 yaml clone (200 trials, train-only):
  - Mining wall-clock < 130 min (R3-AC-1 verified per-trial 22s)
  - 全 200 trials archive includes nav_sharpe + nav_max_dd + nav_corr_anchor
  - TPE sampling explored ≥ 4 of 6 (SR × holding) hyperparameter cells
- v2 objective rank top-10 vs v1 objective rank top-10:
  - Spearman rank correlation < 0.7 (i.e. selection materially differs)
  - At least 3 trials in v2 top-10 不在 v1 top-10
  - At least 1 trial in v2 top-10 has nav_corr_anchor < 0.50 (true diversifier)

### 5.3 Cycle #06 dry-run cycle

- Use v2 objective + cap_aware_cross_asset construction (cycle #04 config)
- 200 trials, train-only, R41 v2 verdict
- Output ≥ 1 Tier 1 (non-sibling) candidate
- Or output 0 Tier 1 → strategic pivot deeper (PRD-E or beyond)

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
3. Anchor NAV (universe-equal-weight baseline) builder
4. Per-trial wall-clock benchmarks (target ≤ 30s/trial avg)

### Phase 3: Search space extension (1 周)

1. Add `enable_sr_defer` / `holding_freq` to trial.suggest space
2. Wire `enable_sr_defer=True` to call sr_signal_filter on target_wts pre-NAV
3. Wire `holding_freq` to rebalance cadence in BacktestEngine
4. Tests covering 2 × 3 = 6 hyperparameter combos

### Phase 4: Smoke run + cycle #06 dry-run (1-2 周)

1. v2_nav_based smoke run on cycle #04 yaml clone (200 trials)
2. Acceptance criteria 5.2 verify
3. cycle #06 yaml draft (用 v2 objective + cap_aware_cross_asset)
4. cycle #06 dry-run mining + R41 verdict
5. Closeout memo + commit

**Total: 4-5 周 (R3 verified estimate, not optimistic)**

---

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Mining time 100+ min vs current 30-60 min | (1) only trigger NAV calc when w_nav_* > 0; (2) cache anchor NAV across trials |
| Anchor selection α/β/γ 都 fail | Phase 4 smoke run revealed; fall back hierarchy α → γ → strategic pivot |
| Multi-objective trade-off 调参成 art | Smoke run with grid of weight combos; document optimal in closeout |
| TPE 200 trials 不够 cover 2×3 search dim | Increase to 400 trials if smoke shows 2/6 cells empty |
| Backward compat regression | Phase 1 acceptance: v1_legacy reproduces cycle #04 top-1 to 4 decimals |
| Anchor (universe-equal-weight) is itself trivially correlated with mined spec | Phase 4 smoke verify; if true, fallback to γ (skip orthogonality) |

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
