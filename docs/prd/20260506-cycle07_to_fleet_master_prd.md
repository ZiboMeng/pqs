# PRD: Cycle 07 → Fleet Master Roadmap (Orthogonal Factor Mining + Regime-Aware + Deployable Strategy)

**Lineage tag**: `cycle07-to-fleet-master-2026-05-06`
**Authored**: 2026-05-06
**Authority**: User explicit-go 2026-05-06 ("把整个 prd 准备一下 这个 prd 会用作 ralph-loop
的基准"); operator self-audit findings (this session, 6 issues identified
+ revised); cycle04/05/06 sibling evidence + PRD-E TAA Phase 3 evidence
**Predecessor PRDs**:
- `docs/prd/20260505-mining_objective_nav_based_plus_execution_policy_prd.md` (PRD-AC v1.1)
- `docs/prd/20260505-taa_regime_allocation_framework_prd.md` (PRD-E v1.1)
- `docs/prd/20260501-two_stage_allocation_architecture_prd.md` (Phase C PRD)
- `docs/prd/20260428-candidate_fleet_allocator_prd.md` (Track B Step 1-5; Step 6+ paused)

**Status**: DRAFT — awaiting user signoff before Phase A starts
**Use case**: Ralph-loop baseline. Each phase below is a discrete
ralph-loop checkpoint with explicit acceptance gates + branch logic.

---

## 1. Background

### 1.1 Current state (2026-05-06)

| Workstream | Status | Evidence |
|---|---|---|
| Cycle04 cap_aware_cross_asset | 0 nominee, 10/10 Tier 2 sibling-by-NAV | `docs/memos/20260501-track_c_cycle_2026-05-01-04_close.md` |
| Cycle05 anchor sensitivity | 0 nominee, 7 Tier 1 R41 but invariant fail | `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md` |
| Cycle06 v2_nav_based | 0 nominee, top-1 sibling-anchored | `docs/memos/20260506-cycle06_closeout.md` |
| PRD-E TAA Phase 3 | 5/7 PASS — defensive sleeve, not standalone | `docs/memos/20260506-prd_e_phase3_closeout.md` |
| Trial9 forward | TD003 / +8.02% / in_progress | `data/research_candidates/trial9_diversifier_001_forward_manifest.json` |
| RCMv1 / Cand-2 forward | status=aborted, legacy decay verification | per CLAUDE.md |
| Fleet allocator (Track B 6+) | HARD PAUSED until ≥2 candidates pass Track A + NAV pair < 0.85 | per CLAUDE.md |
| RESEARCH_FACTORS | 67 factors (no RSI / KDJ / MACD) | `core/factors/factor_registry.py` grep |
| SR defer mining integration | Phase 3 round 1 stub (forced False); round 2 deferred | per `cb1e3dd` commit message |

### 1.2 Sibling problem (root cause for 4 user goals)

3 mining cycles + 1 TAA framework converged to:
- **Cycle04/05/06**: drawup_from_252d_low + ret_2d / mom_* anchor → universe-bound diversifier floor → R41 Tier 2 by NAV correlation 0.85+ vs RCMv1+Cand-2
- **TAA**: defensive sleeve (5/5 defensive gates pass) but not standalone alpha (G2 + G6 fail)
- **Trial9**: TD003 forward; per-day +4% on 2026-05-06 promising but N=3 too thin

The structural binding constraint is:
1. **Universe**: 53 stocks + 6 cross-asset ETFs is small enough that any
   long-only top-N spec inherits ~85% pooled NAV correlation with RCMv1
   anchor by construction
2. **Factor space**: 67 RESEARCH_FACTORS is mostly mom/reversal/vol/range
   variants; lacks oscillator (RSI/KDJ/MACD) + structural-S/R signal
   diversity
3. **Mining objective**: cycle06 v2_nav_based weights 0.7/0.15 IR/NAV-sharpe
   were too IR-heavy to materially differentiate v2 from v1 (H1 Spearman
   0.89 + H3 Pareto regression)
4. **Anchor**: cycle06 H4 used universe-equal-weight residual anchor →
   100% trials < 0.50 → suspiciously clean, low discriminative power
5. **Regime-blindness**: mining IC computed all-time, not regime-conditional;
   alpha that's strong in BEAR but weak in BULL gets diluted

### 1.3 Why a master PRD (not 4 separate PRDs)

User intent ("把整个 prd 准备一下"): single document covering all 4
phases as ralph-loop baseline so:
- Cross-phase dependencies are explicit (Phase D gated on Phase B/C
  candidates)
- Branch decisions on Phase A results don't require new PRDs
- Single audit trail; single sha256 for immutability of plan

Per operator self-audit (this session, Issue 5): "use ex-post overlay"
recommendation contradicted user's PRD-AC §1.3 explicit-go. This PRD
**honors that explicit-go** by including SR defer FULL mining
integration (Phase B.2) as part of the plan.

---

## 2. Goals (user-stated, 2026-05-06)

### G1 — 因子池扩展（包括 swing 开关）

Add new daily-resolution factors to RESEARCH_FACTORS:
- RSI (Wilder's 14-period; bounded oscillator)
- KDJ (Stochastic %K + %D + J line; range-position oscillator)
- MACD (EMA(12) - EMA(26) + signal line; trend-divergence)
- SR/swing: PRD-AC v1.1 Phase 3 round 2 SR defer **FULL mining
  integration** (NOT ex-post overlay). Sampling `enable_sr_defer ∈
  {False, True}` becomes a real search dimension that affects NAV
  during mining (PRD-AC §1.3 user explicit-go).

**Acceptance**: cycle08+ mining pool has 67 + 3 = 70 factors (assuming
RSI/KDJ/MACD pass IC screening at < 0.6 correlation with existing); SR
defer search dim is real (mining objective sees with vs without
filter NAV difference; not just stamping a frozen_spec field).

### G2 — Regime-aware 机制实现

Implement **regime-conditional factor mining**: IC computed stratified
by regime (BULL / RISK_ON / NEUTRAL / CAUTIOUS / RISK_OFF / CRISIS),
mining objective aggregates regime-conditional IC with user-tunable
weights (e.g., w_BEAR=2.0 to favor BEAR-conditional alpha).

This is **NOT** TAA (which is asset-class allocation), and **NOT**
fleet allocator (which switches sleeves at portfolio level). It's
factor-mining with regime stratification — same mining paradigm,
new objective.

**Acceptance**: cycle08 mining produces specs with measurable IC
differential across regimes (BEAR-IC > 1.5× BULL-IC for at least 1
top-10 spec).

### G3 — Orthogonal factor mining

Mine for specs whose NAV is orthogonal to **existing fleet candidates**
(RCMv1 + Cand-2 + Trial9), not just universe-equal-weight residual
(cycle06 anchor was too clean).

Implementation: build composite anchor from (RCMv1 NAV + Cand-2 NAV +
Trial9 NAV) replayed on train-only panel via existing harness; pass
to ResearchMiner constructor as `anchor_residual_returns`.

**Note on CLAUDE.md invariant**: "RCMv1 + Cand-2 will not calibrate
new-framework gates". This PRD uses RCMv1+Cand-2+Trial9 as **objective
TERM** (TPE penalty) NOT as **HARD acceptance gate** — distinction
is operationally meaningful (gate would fail-closed; term is soft
preference). Operator interpretation: invariant constrains gates, not
objective terms. If user disputes this reading, clarify before Phase C.

**Acceptance**: cycle08 top-3 trials' NAV correlation vs (RCMv1 +
Cand-2 + Trial9) blend < 0.70 (residual after stripping SPY beta);
ideally < 0.50 (true diversifier band).

### G4 — Stable profitability (deployable strategy)

Ship **fleet allocator** combining:
- 1+ stock-alpha sleeve (cycle07a/cycle08 nominees, IF produced)
- 1 defensive sleeve (TAA V1, currently dormant per PRD-E close)
- 1+ existing forward candidate (Trial9, post-TD60 graduation)

Regime-conditional sleeve switching:
- BULL/RISK_ON → 70% high-beta sleeve / 20% defensive / 10% Trial9
- NEUTRAL/CAUTIOUS → 40/40/20
- CRISIS/RISK_OFF → 10% high-beta / 70% defensive / 20% Trial9

**Acceptance**: fleet allocator passes Track A acceptance ON SELECTOR
PANEL (train + validation) with overall PASS verdict (CLAUDE.md core
role gates). Sealed 2026 single-shot evaluation occurs ONLY after
selector-panel success.

---

## 3. Non-goals

- Not breaking PRD-AC v1.1 / PRD-E v1.1 archives (cycle04/05/06
  archives + TAA modules preserved per Issue 6 audit)
- Not unifying mining objective across PRD-AC and PRD-E (PRD-E TAA
  remains separate framework)
- Not consuming sealed 2026 panel (5.4 OOS discipline preserved)
- Not changing CLAUDE.md invariants (long-only / no-margin / no-short /
  fleet 2-candidate gate / sealed single-shot)
- Not deploying fleet allocator on real broker (paper-only;
  forward-runner integration is separate gated PRD)
- Not auto-promoting cycle07/cycle08 nominees to fleet without R41 +
  NAV pair correlation check

---

## 4. Phase architecture (execution order = 2 → 3 → 4 → 1)

### 4.1 Phase A: cycle07a reweight + RSI/KDJ/MACD IC screening (parallel, ~1-2 days)

#### Phase A.1 — cycle07a reweight mining

**Single-axis diff vs cycle06**: objective_weights ratio. ALL OTHER
fields identical to cycle06 yaml (universe / construction / holding_freq /
explicit_exclusions / hard_blockers / R41 anchors).

New `mining_config.objective_weights`:
```yaml
objective_version: v2_nav_based
objective_weights:
  w_ir:                    0.40   # was 0.70
  w_turnover:              0.05
  w_corr_conc:             0.05
  w_bench_excess:          0.0
  w_regime_stddev:         0.0
  w_nav_sharpe:            0.20   # was 0.15
  w_nav_max_dd_penalty:    0.10   # was 0.05
  w_nav_orthogonality:     2.00   # was 0.0
  w_vs_qqq_excess:         0.20   # was 0.0
```

**Anchor source**: keep cycle06's universe-equal-weight residual (NOT
yet RCMv1+Cand-2+Trial9 — that's Phase C). Phase A.1's hypothesis is
"cycle06 0-nominee was caused by weight ratio, not anchor source";
test it before incurring Phase C complexity.

**Yaml**: `data/research_candidates/track-c-cycle-2026-05-07-01_promotion_criteria.yaml`
- Lineage tag: `track-c-cycle-2026-05-07-01`
- sha256 recorded in commit message (immutable)

**Mining**: 200 trials, ~65 min wall-clock per Phase 2 round 2
benchmark (no SR defer or new factors yet).

**Acceptance gates** (PRD-AC §5.2 + cycle06 H1+H3 lessons):
- H1 v2 vs v1 Spearman < 0.7 (cycle06 was 0.89 — fail; with 4× higher
  NAV weights expect Spearman < 0.6)
- H2 SAMPLED holding_freq distribution ≥ 50 per cell (corrected from
  cycle06 yaml's "30 archived" mis-spec)
- H3 v2 top-1 nav_sharpe ≥ v1 top-1 nav_sharpe (Pareto improvement;
  cycle06 was -0.099)
- Track A acceptance on top-3 trials: at least 1 PASS
- R41 informational: at least 1 trial in top-10 with raw NAV
  correlation < 0.70 vs RCMv1+Cand-2

**Verdict logic**:
- All 4 gates PASS → Phase A.1 SUCCESS, candidate ready for Track A
  acceptance + R41 sibling check; Phase D PRD writing can start
- 1+ gate FAIL but H1+H3 PASS → cycle07a evidence of weight ratio
  effect; Phase C still needed for orthogonality
- All 4 gates FAIL → cycle07a 0 nominee; Phase C urgent; structural
  evidence for sibling problem stronger

#### Phase A.2 — RSI/KDJ/MACD IC screening

**Lightweight dev script** (no production code yet):
`dev/scripts/factor_screening/run_rsi_kdj_macd_ic_screen.py`

Steps:
1. Implement 3 factors as inline functions (~50 lines each):
   - `rsi_14d(close)`: Wilder's RSI, 14-period
   - `kdj_9d(close, high, low)`: Stochastic %K(9) + %D(3) + J=3K-2D
   - `macd_12_26_9(close)`: EMA(12)-EMA(26), signal line EMA(9)
2. Compute panel-wide on partition_for_role(role="miner") panel
3. Compute IC time-series vs forward returns (21d horizon, lag=1) per
   each new factor
4. Compute IC time-series Pearson correlation: 3 new factors × 67
   existing factors = 201 pairwise cor
5. Output JSON: per-factor mean_IC, IR, max correlation with existing,
   list of top-5 most-correlated existing factors

**Acceptance per new factor**:
| Max IC corr with existing | Verdict |
|---|---|
| < 0.6 | ELIGIBLE — promote to RESEARCH_FACTORS in Phase B.1 |
| 0.6 - 0.7 | CONDITIONAL — promote IFF mean_IR > 1.5× max-cor-existing IR |
| > 0.7 | REJECT — sibling, do not promote |

Phase A.2 wall-clock: ~half day eng + 30 sec compute.

#### Phase A parallelism

A.1 and A.2 are independent (different infrastructure) and can be
launched in parallel:
- A.1: mining run in background (~65 min)
- A.2: factor screening dev script (interactive, ~half day)

**End of Phase A**: 1-2 days from PRD signoff, both A.1 and A.2 done
with explicit verdicts.

### 4.2 Phase B: factor pool expansion + SR defer mining integration (~1-2 weeks)

#### Phase B.1 — Promote RSI/KDJ/MACD per A.2 verdict

**For each ELIGIBLE factor**:
1. Production-quality factor implementation in
   `core/factors/factor_<name>.py` or appended to existing module
2. Add to `core/factors/factor_registry.py::RESEARCH_FACTORS`
3. Categorize into a `FAMILIES_V2` family:
   - RSI → likely Family C (liquidity/cost-proxy/risk-state) or new
     Family G (oscillators) if 2+ oscillators land
   - KDJ → likely Family B (position/breakout/path-shape; KDJ %K is
     position-in-range)
   - MACD → likely Family D (trend-quality)
4. Update `tests/unit/mining/test_research_miner.py
   ::test_aplusplus_families_v2_union_equals_research_factors` count
5. Tests: per-factor unit test (synthetic input → expected output;
   schema check)
6. Verify `factor_panel_map` build path includes new factors when
   `factor_registry_pool=RESEARCH_FACTORS`

**Wall-clock**: ~1 day per factor × N eligible (max 3 → max 3 days).

#### Phase B.2 — PRD-AC Phase 3 round 2 SR defer mining integration

**Honors PRD-AC §1.3 user explicit-go**: "C 之前的问题是因为在已经选好
的 strategy 上加了 SR 开关才导致的。我希望他能够加入到 mining 的过程中
来决定是否需要 turn on or off"

**Architecture**: Cycle through SR defer in mining:
1. ResearchMiner constructor loads 60m bars at instantiation:
   - Use `BarStore.load(sym, freq='60m')` for tradable universe
   - Cache `intraday_bars_60m: Dict[str, pd.DataFrame]` on miner
2. Sampler: `enable_sr_defer_choices = (False, True)` (no longer
   forced False; PRD-AC Phase 3 round 1 stub)
3. evaluate_composite NAV path:
   - Always run baseline harness eval (compute target_wts, run
     BacktestEngine → get NAV_baseline + result.weights)
   - If `spec.enable_sr_defer == True`:
     - `apply_sr_defer_filter(result.weights, intraday_bars_60m,
       config=SRDeferConfig(...))` → filtered_weights + activation_stats
     - Run BacktestEngine SECOND TIME on filtered_weights → NAV_filtered
     - Use NAV_filtered for nav_sharpe / nav_max_dd / nav_corr_anchor
       computation
   - Else: use NAV_baseline (no second run)
4. **I6 prefilter**: Phase 3 round 1 stub had `enable_sr_defer_choices`;
   round 2 adds **per-spec eligibility check**:
   - Compute `defer_activation_rate = stats.n_defers / stats.n_evaluated`
     on baseline target_wts
   - If activation_rate < 5%: force `enable_sr_defer = False` for this
     spec (skip second BacktestEngine run; sample efficiency)
   - Else: TPE samples both branches normally
5. Archive: `enable_sr_defer` already in `_serialize_spec` per Phase 3
   round 1 (`cb1e3dd` commit); no schema change needed

**Wall-clock impact**:
- Per-trial baseline harness: ~19s (per Phase 2 round 2 benchmark)
- Per-trial second harness (when SR defer fires): +~19s
- Expected SR defer fire rate ~50% (pre-filter cuts ~half) → median
  trial wall-clock ~28s
- 200 trials × 28s ≈ 95 min per cycle (vs 65 min cycle06)

**Tests**:
- Unit test: SR defer applied to 1 known spec on synthetic 60m panel →
  filtered_weights match expected
- Integration test: full evaluate_composite NAV path with
  `enable_sr_defer=True` produces non-NaN nav_sharpe (with synthetic
  60m bars in repo's test fixture)
- Regression: cycle04/05/06 archived trials' replay (without SR defer)
  unchanged

**Wall-clock estimate**: ~3-5 days eng (60m bar loading + harness mod
+ second-run path + tests + integration with cycle07b yaml).

#### Phase B.3 — Phase A branch decision

After Phase A.1 + A.2 verdicts land, branch:

| Phase A.1 result | Phase A.2 result | Phase B priority |
|---|---|---|
| Nominee (gates PASS) | ≥1 ELIGIBLE | Run Track A acceptance on cycle07a nominee; Phase B.1 in parallel; Phase B.2 next |
| Nominee | 0 ELIGIBLE | Track A acceptance on cycle07a nominee; skip B.1; Phase B.2 next |
| 0 nominee | ≥1 ELIGIBLE | Phase B.1 + B.2 BOTH; Phase C needed |
| 0 nominee | 0 ELIGIBLE | Phase B.2 only; Phase C urgent + universe expansion consideration |

**Phase B end**: ~2 weeks from PRD signoff. Factor pool potentially
70 factors; SR defer mining integration tested; cycle07a nominee
either advanced to forward or marked for fleet integration.

### 4.3 Phase C: regime-conditional mining (cycle08, ~2-3 weeks)

#### Phase C.1 — Design

**Mining objective extension**:
```python
# core/mining/research_miner.py compute_objective extension
def compute_objective_v3_regime_conditional(
    metrics_per_regime: Dict[RegimeState, CompositeMetrics],
    weights: ObjectiveWeightsV3,
) -> float:
    """Aggregate regime-conditional IC + NAV via weighted sum.

    metrics_per_regime: per-regime CompositeMetrics (IC + NAV computed
        on regime-stratified panel)
    weights: ObjectiveWeightsV3 with regime weights:
        w_ir_BULL, w_ir_BEAR, w_ir_NEUTRAL, ...
        w_nav_sharpe_BULL, w_nav_sharpe_BEAR, ...
    """
```

**ObjectiveWeightsV3 default** (regime-aware):
```python
@dataclass(frozen=True)
class ObjectiveWeightsV3:
    # IR weights per regime (favor BEAR-conditional alpha)
    w_ir_BULL:     float = 0.5
    w_ir_RISK_ON:  float = 0.5
    w_ir_NEUTRAL:  float = 0.5
    w_ir_CAUTIOUS: float = 1.0
    w_ir_RISK_OFF: float = 1.5
    w_ir_CRISIS:   float = 2.0
    # NAV-Sharpe weights per regime (favor BEAR-conditional defense)
    w_nav_sharpe_BULL:     float = 0.10
    w_nav_sharpe_BEAR:     float = 0.30  # umbrella across CAUTIOUS/RISK_OFF/CRISIS
    # Anchor + qqq excess (full-period, not regime-stratified)
    w_nav_orthogonality:   float = 2.0
    w_vs_qqq_excess:       float = 0.20
```

**evaluate_composite extension**:
```python
def evaluate_composite_regime_conditional(
    spec, factor_panel_map, fwd_returns,
    daily_regime_labels: pd.Series,  # NEW
    ...,
) -> Dict[RegimeState, CompositeMetrics]:
    """Compute IC + NAV stratified by regime.

    For each regime:
      1. Mask fwd_returns to regime-only days (regime_label == regime)
      2. Run evaluate_composite on regime-restricted sample
      3. Return per-regime metrics
    """
```

**Regime label source**: Reuse PRD-E TAA's `daily_regime_labels`
generator (`core/research/taa/regime_label_generator.py`) — NO new
regime detection infra needed.

#### Phase C.2 — Cycle08 yaml + 200-trial mining

**Cycle08 yaml** (`data/research_candidates/track-c-cycle-2026-05-XX-01_promotion_criteria.yaml`):
- Lineage tag: `track-c-cycle-2026-05-XX-01` (date TBD post-Phase-B)
- Single-axis diff vs cycle07a/b: regime-conditional mining objective
- All other fields identical (universe = cycle06; construction =
  cap_aware_cross_asset; holding_freq_choices = [monthly, weekly, daily];
  enable_sr_defer_choices = [false, true] IF Phase B.2 landed;
  factor_registry_pool = RESEARCH_FACTORS post-Phase-B.1)

**Mining**: 200 trials. Wall-clock estimate:
- Without SR defer: ~95 min (regime-stratified IC adds ~20% overhead;
  panel masking is light)
- With SR defer Phase B.2 landed: ~130 min (combined effect)

#### Phase C.3 — Track A acceptance + R41 sibling check + G3 orthogonality check

For top-3 cycle08 trials:
1. **Track A acceptance**: same gates as cycle06 (per-year vs SPY ≥
   4/5; per-year MaxDD ≤ 20%; 2025 hard gate; stress slices ≤ 25%;
   cost robustness; concentration; beta to QQQ ≤ 0.85)
2. **R41 informational**: pooled raw + residual NAV correlation vs
   RCMv1 + Cand-2 (existing R41 anchor pool). Tier classification.
3. **NEW: G3 orthogonality check** (PRD-E composite anchor):
   - Compute (RCMv1 + Cand-2 + Trial9) NAV blend on selector panel
   - Compute pooled raw + residual (vs SPY) NAV correlation per top-3
     spec
   - Acceptance: ≥1 trial with raw < 0.70 AND residual < 0.50 → G3
     PASS

#### Phase C.4 — Closeout

`docs/memos/20260520-cycle08_closeout.md` (date TBD). Outcomes:
| Outcome | Action |
|---|---|
| ≥1 nominee passing Track A + R41 + G3 | Phase D fleet allocator unblocks; PRD-D-PRD writing starts |
| ≥1 nominee passing Track A + R41 but G3 FAIL | Surface to user; decide whether to soften G3 (sibling but standalone good) |
| 0 nominee | Phase E structural pivot (universe expansion / longer horizon / cross-cycle ensemble / etc.) |

**Phase C end**: ~5 weeks from PRD signoff (cumulative).

### 4.4 Phase D: fleet allocator (~4-6 weeks; gated)

#### Phase D.0 — Hard gate: ≥2 candidates exist

Per CLAUDE.md "Track B Step 6+ HARD PAUSED until ≥2 candidates exist
that BOTH pass Track A acceptance AND have realized-NAV pair
correlation < 0.85":

Phase D.0 START prerequisite (BOTH must hold):
- (a) Phase B.3 cycle07a OR Phase C.4 cycle08 produced ≥1 nominee
  passing Track A acceptance
- (b) Trial9 forward observation has reached TD60 GREEN verdict
  (~2026-07-30 calendar)

If neither (a) nor (b) holds at week 5, Phase D.1 (PRD writing) STILL
can start (PRD doesn't deploy code; can be ready for when (a)+(b)
land). Phase D.2-D.4 do NOT start until (a)+(b) both true.

#### Phase D.1 — Fleet allocator PRD (Phase C-PRD-3)

`docs/prd/2026XXXX-fleet_allocator_prd.md` (date TBD).

Scope:
- Sleeve definition (alpha sleeves: cycle07a/cycle08 nominees + Trial9;
  defensive sleeve: TAA V1)
- Regime-conditional sleeve switching rules
- Smoothing logic (avoid hard switching at regime boundaries; e.g.,
  EMA(20-day) of regime label)
- Cost model (sleeve-switching turnover)
- Forward runner integration schema (separate PRD-E2 territory but
  must be designed-for)
- Acceptance criteria (Track A on selector panel; sealed 2026
  single-shot final)

**Wall-clock**: ~1 week.

#### Phase D.2 — Implementation

`core/research/fleet/fleet_allocator.py` (new module).

Components:
1. `Sleeve` dataclass: candidate_id + spec + regime_weight_function
2. `FleetAllocator` class: regime-driven sleeve weight blending
3. `run_fleet_backtest`: integrates BacktestEngine across sleeves
4. `evaluate_fleet_acceptance`: Track A acceptance on fleet NAV

Tests:
- Synthetic 3-sleeve fleet on synthetic panel
- Regime-switching boundary test (no sleeve weight discontinuity)
- Single-sleeve degenerate case (fleet = standalone sleeve)
- 2-sleeve correlation check (fleet NAV vs each sleeve)

**Wall-clock**: ~2-3 weeks.

#### Phase D.3 — Tests + integration

- 30+ unit tests (sleeve / allocator / backtest / acceptance)
- Integration test: fleet on real selector panel with 2 known sleeves
  (TAA V1 + Trial9 spec replay)
- Regression: existing cycle04/05/06 + TAA tests still PASS

**Wall-clock**: ~3-5 days.

#### Phase D.4 — Smoke + deploy

- Smoke run on selector panel: full Track A acceptance verdict
- If PASS → forward observation runner integration scoped (PRD-E2
  separate)
- If FAIL → revisit sleeve selection / regime weights / closeout

**Wall-clock**: ~half day smoke + ~1 week if PRD-E2 integration kicks in.

**Phase D end**: ~10-12 weeks from PRD signoff (cumulative; depends on
Trial9 TD60 calendar).

---

## 5. Acceptance criteria

### 5.1 Per-phase explicit gates

See §4.1-§4.4 for per-phase acceptance gates. Summary:

| Phase | Gate | Pass criterion |
|---|---|---|
| A.1 | cycle07a mining | H1 Spearman < 0.7 + H2 sampled cells ≥ 50 + H3 Pareto + Track A 1+ PASS + R41 1+ trial < 0.70 |
| A.2 | IC screening | per-factor max-cor < 0.7 verdict |
| B.1 | factor promotion | 1+ ELIGIBLE factor lands in RESEARCH_FACTORS + tests PASS |
| B.2 | SR defer round 2 | per-trial wall-clock < 35s + integration test + cycle04/05/06 regression unchanged |
| C.2 | cycle08 mining | regime-stratified IC computed; G2 evidence (BEAR-IC > 1.5× BULL-IC for 1+ top-10 spec) |
| C.3 | cycle08 acceptance | ≥1 trial pass Track A + G3 (NAV blend cor < 0.70) |
| D.0 | gate prerequisite | ≥2 candidates pass Track A AND Trial9 TD60 GREEN |
| D.4 | fleet smoke | full Track A acceptance on selector panel |

### 5.2 Goal-level (G1-G4) success metrics

| Goal | Success metric |
|---|---|
| G1 — Factor pool expansion | RESEARCH_FACTORS count grows by 1+ (RSI/KDJ/MACD post-screening) AND SR defer mining integration shipped (Phase B.2 PASS) |
| G2 — Regime-aware mechanism | cycle08 produces ≥1 spec with BEAR-IC > 1.5× BULL-IC (regime-conditional alpha) |
| G3 — Orthogonal mining | cycle08 top-3 has ≥1 trial with raw NAV cor < 0.70 vs (RCMv1+Cand-2+Trial9) blend |
| G4 — Stable profitability | Fleet allocator passes Track A on selector panel |

### 5.3 Final deployable strategy criterion

Beyond G1-G4, the **deployable strategy** = fleet allocator passing
Track A on selector panel AND surviving 2026 sealed single-shot
evaluation (CLAUDE.md core role HARD gate).

Sealed 2026 evaluation is **post-PRD scope**; this PRD ships through
Phase D.4 selector-panel acceptance.

---

## 6. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Phase A.1 0-nominee → cycle07a + cycle06 both fail; weight ratio NOT the cause | Phase C still runs (regime-conditional is independent axis) |
| Phase A.2 all 3 factors REJECT (sibling) | Skip B.1; cycle08 uses 67-factor pool; no harm done |
| Phase B.2 SR defer wall-clock blowup (>2× per-trial) | I6 prefilter; if blowup persists, defer to Phase E with explicit user-go |
| Phase C cycle08 0-nominee | Universe expansion / longer-horizon factors / cross-cycle ensemble (Phase E options) |
| Trial9 TD60 RED (<2026-07-30) | Phase D.0 gate (a) still possible IF cycle07a/cycle08 produced nominee; otherwise Phase D BLOCKED |
| RCMv1+Cand-2+Trial9 anchor as objective term controversial vs CLAUDE.md | Phase C kickoff requires user clarification on whether anchor-as-term is acceptable |
| Sealed 2026 contamination | OOS discipline §7 below; no sealed reads in any phase |
| Ralph-loop drift / phase gating ambiguity | Per-phase acceptance gates + branch decision table at end of each phase ensure ralph-loop knows when to advance |
| Factor implementation bugs (RSI/KDJ/MACD) | Per-factor unit test against 1 known case (e.g., AAPL 2024-Q1 expected RSI value) |
| Regime-conditional mining wallclock (~95-130 min) | Acceptable per existing 65 min benchmark; no special mitigation |
| PRD-D-PRD writing without candidate evidence | Phase D.1 can start at week 5; impl gated on D.0 prereqs to avoid wasted code |

---

## 7. OOS discipline

- All mining (Phase A.1 + Phase C.2) uses
  `partition_for_role(role="miner")` (train years only)
- All acceptance evaluation (Phase A.1 Track A on top-3 + Phase C.3 +
  Phase D.4) uses `partition_for_role(role="selector")` (train +
  validation; sealed excluded)
- All forward observation (Trial9 + future cycle07a/08 nominees) uses
  forward runner with `source_mix=True` flag (yfinance frontier vs
  polygon canonical)
- Sealed 2026: NEVER read in any phase. No code path consumes sealed
  data. CLAUDE.md sealed_test_runner role NOT invoked anywhere in this
  PRD.
- 5.4+ data: 0 consumption (mining train_years end 2024-12-31)

---

## 8. Reversibility

Each phase is reversible without affecting prior phases or other
workstreams:

- Phase A.1 cycle07a archive: immutable per yaml hash; if numerically
  uninformative, archive marker yaml only
- Phase A.2 IC screening: dev script outputs JSON; no production code
  changed
- Phase B.1 factor promotion: pure addition to RESEARCH_FACTORS;
  removal = revert single commit + bump test count
- Phase B.2 SR defer round 2: add `enable_sr_defer_choices=[False]`
  flag to bypass; cycle04/05/06 archives unaffected
- Phase C cycle08 archive: immutable per yaml hash
- Phase D fleet allocator: pure new module; revocation = delete `core/
  research/fleet/`; cycle archives + Trial9 forward + TAA modules
  unaffected

No data destruction, no manifest mutation, no invariant change in any
phase.

---

## 9. Ralph-loop checkpoints

Each phase has a discrete commit + push checkpoint:

| Phase | Commit message convention | Branch decision |
|---|---|---|
| A.1 | `Cycle07a mining: <verdict>` | Branch on H1+H2+H3+TrackA+R41 |
| A.2 | `RSI/KDJ/MACD IC screening: <eligible_count>/3 pass` | Branch on per-factor cor |
| B.1 | `Factor promotion: <factor_name> → RESEARCH_FACTORS` | Repeat per factor |
| B.2 | `PRD-AC Phase 3 round 2 SR defer mining integration` | Single-commit landing |
| C.1 | `PRD-D regime-conditional mining design` | Implementation kickoff |
| C.2 | `Cycle08 regime-conditional mining: <verdict>` | Branch on G2+G3+TrackA |
| C.3 | `Cycle08 closeout` | Branch on Phase D.0 prerequisite |
| D.1 | `Fleet allocator PRD draft` | Implementation kickoff |
| D.2-D.4 | per-step incremental commits | Final acceptance verdict |

Between phases, ralph-loop should:
1. Display the verdict (PASS / FAIL / branch outcome)
2. Surface to user the next phase's expected actions
3. Wait for user explicit-go IF directional decision needed (e.g., G3
   anchor controversy in Phase C kickoff; universe expansion in Phase E)
4. Auto-advance IF tactical decision (e.g., per-factor IC screening
   verdict; per-trial Track A failure)

Per memory `feedback_decision_authority_operator_audit_split.md`:
tactical decisions auto-advance; directional decisions pause for user
input.

Per memory `feedback_per_round_close_ritual.md`: each phase closes with
commit + push + 4-layer self-audit (R1+R2+R3+R4) + TODO update.

---

## 10. Authorization markers

- User explicit-go 2026-05-06: "把整个 prd 准备一下 这个 prd 会用作
  ralph-loop 的基准 prd 里面要写清楚 2 3 4 1 的执行顺序和执行内容 把
  细节都写清楚 目标也写清楚 我们的目标是希望能够把factor都加进去 包括
  swing开关 另外 regime aware的机制 也希望能够实现orghogonal的factor
  的mining 还有实现稳定的盈利"
- Predecessor PRDs: PRD-AC v1.1 + PRD-E v1.1 (both shipped
  predecessor work this session)
- Operator self-audit (this session, 6 issues identified + 6 revisions
  applied to estimates and recommendations)
- CLAUDE.md invariants: long-only / no-margin / no-short / sealed
  single-shot / fleet 2-candidate gate (all preserved)

---

## 11. Calendar timeline (estimated)

```
Week 0 (today, 2026-05-06):
  - PRD signoff (this document)
  - Phase A starts (parallel A.1 + A.2)

Week 1 (2026-05-07 to 2026-05-13):
  - Phase A.1 cycle07a mining + Track A on top-3 → verdict
  - Phase A.2 IC screening → verdict
  - Phase A.3 branch decision
  - Phase B.1 factor promotion (if A.2 ELIGIBLE)
  - Phase B.2 SR defer mining integration kickoff

Week 2-3 (2026-05-14 to 2026-05-27):
  - Phase B.1 factor promotion completes
  - Phase B.2 SR defer round 2 lands
  - Phase C.1 regime-conditional mining design + impl

Week 4-5 (2026-05-28 to 2026-06-10):
  - Phase C.2 cycle08 200-trial mining
  - Phase C.3 acceptance + G3 orthogonality check
  - Phase C.4 closeout
  - Phase D.1 fleet allocator PRD start (parallel; not gated)

Week 6-9 (2026-06-11 to 2026-07-08):
  - Phase D.1 fleet allocator PRD complete
  - Phase D.2 fleet allocator impl (gated on D.0 prereqs)

Week 10-12 (2026-07-09 to 2026-07-29):
  - Trial9 forward TD60 milestone (~2026-07-30)
  - Phase D.0 gate (a)+(b) check
  - Phase D.3 tests + integration

Week 13-14 (2026-07-30 onwards):
  - Phase D.4 smoke + Track A acceptance verdict
  - If PASS: forward observation runner integration (PRD-E2 separate)
  - If FAIL: revisit / Phase E

Total: ~14 weeks from PRD signoff to deployable strategy verdict.
```

Calendar is **estimated**; actual timing depends on:
- Per-phase 0-nominee outcomes triggering Phase E
- Trial9 forward observation outcome (TD60 GREEN/YELLOW/RED)
- User-go pauses on directional decisions
- Background mining wall-clock (1-2 days slip across 4 mining runs)

---

## 12. Appendix: phase-by-phase work summary table

| Phase | Eng days | Wall-clock | Output |
|---|---|---|---|
| A.1 cycle07a | 0.5 | 65 min mining | cycle07a yaml + closeout |
| A.2 IC screen | 0.5 | 30 sec compute | IC report JSON |
| B.1 factor promotion | 2-3 | none | RESEARCH_FACTORS + tests |
| B.2 SR defer round 2 | 3-5 | none | mining integration |
| C.1 regime PRD + impl | 5-7 | none | mining objective v3 |
| C.2 cycle08 mining | 1 | 95-130 min mining | cycle08 archive |
| C.3 cycle08 acceptance | 1 | 1-2 hrs eval | top-3 verdict |
| C.4 closeout | 1 | none | memo |
| D.1 fleet PRD | 5 | none | PRD-D draft |
| D.2 fleet impl | 10-15 | none | core/research/fleet/ |
| D.3 fleet tests | 3-5 | none | 30+ unit tests |
| D.4 fleet smoke | 0.5 | 1 hr smoke | Track A verdict |

Total: ~30-50 eng days across ~14 calendar weeks.

---

End of PRD.
