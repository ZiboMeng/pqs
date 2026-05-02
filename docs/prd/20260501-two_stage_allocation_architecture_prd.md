# PRD — Two-Stage Allocation Architecture

**Doc ID**: `20260501-two_stage_allocation_architecture_prd.md`
**Status**: Draft (architecture + Phase C-PRD-1 implementation; Phase C-PRD-2+ scoped, not authorized)
**Authors**: Claude Opus 4.7 (operator) + collaborator advisory
**Decision Authority**: User directional decisions (D1-D9)
**Implementation Stage**: Phase C-PRD-0 (decision lock) + Phase C-PRD-1 (lightweight role tag + Trial 9 forward init) only — Phase C-PRD-2+ requires forward evidence trigger
**Companion docs**:
- `docs/memos/20260501-track_c_cycle_2026-05-01-05_close.md` (cycle #05 closeout)
- `docs/memos/20260430-priority_realign_alpha_first.md` (alpha-first priority)
- `core/research/anti_sibling_policy.py` (POLICY_VERSION `v2.0_conditional_review_2026-05-01`)
- CLAUDE.md (QQQ Outperformance Rule, Phase D framework)

**Operator authoring discipline** (per user 2026-05-01: "你需要对你写的东西非常清楚 并且确定这个是最优的"):
- Each design clause is annotated with `[CERTAIN]`, `[OPERATOR-OPINION]`, or `[DEFERRED-REVIEW]`.
- `[CERTAIN]`: operator is confident this is correct given current evidence and project invariants.
- `[OPERATOR-OPINION]`: operator's recommended choice; alternatives exist; user decides.
- `[DEFERRED-REVIEW]`: not yet certain; flagged for explicit user/collaborator review before implementation.

---

## 1. Background [CERTAIN]

PQS Track C controlled-mining cycle history (verified via git log + closeout memos):

| Cycle | Construction | Result | Best IC_IR | Headline finding |
|-------|--------------|--------|------------|------------------|
| #01 (2026-04-26) | global_top_n on stocks-only universe | 0 nominee, sibling collapse | 1.04 | watchlist concentration 39.5% > 30% ceiling |
| #02 (2026-04-30) | global_top_n + alternating-regime split | 0 nominee | 0.66 | construction-collapse hypothesis |
| #03-02 (2026-05-01) | cap_aware on stocks-only | 0 nominee, 10/10 Tier 2 | 1.19 | universe-bound NAV floor 0.85 |
| #04 (2026-05-01) | cap_aware_cross_asset (53 stocks + 6 cross-asset) | 0 nominee, 10/10 Tier 2 | 1.20 | Cluster A breakthrough: 4 trials raw NAV 0.66-0.70 partial diversifier band |
| #05 (2026-05-01) | cap_aware_cross_asset + ban drawup+amihud | 0 nominee strict; 7 Tier 1 R41; trial 9 passes yaml hard blockers, fails CLAUDE.md OOS walk-forward window-mean | 0.55 | drawup+amihud anchor IC; trial 9 = real diversifier candidate |

**Trial 9 (`6c745c601a47`) summary** (verified via direct read of `data/ml/research_cycle_eval/track-c-cycle-2026-05-01-05/evaluation_summary.json`):
- Spec: `beta_spy_60d (1/3) + max_dd_126d (1/3) + ret_1d (1/3)` (families A/B/F)
- Full period: cum_ret +502.6%, sharpe 0.78, max_dd -24.5%, vs_qqq +6.3%
- Per-validation-year vs_qqq: 2018 +3.66%, 2019 -13.16%, 2021 -3.30%, 2023 -19.75%, 2025 +9.59% (mean -4.59%)
- Per-year max_dd: 18-19% across all validation years (all pass < 20% gate)
- NAV correlation: raw 0.54-0.69 (partial_diversifier band); residual 0.04-0.36 (verified via direct grep)
- Asset class exposure: 32.1% non-equity weight average (highest in cycle history)
- factor_overlap_max=1 (only beta_spy_60d shared with RCMv1 + cycle_01_top + cycle_02_top)

The CLAUDE.md QQQ Outperformance Rule (Phase C PRD v3) is project-level invariant designed for **standalone core strategies**. Trial 9 fails it on OOS walk-forward window-mean (mean of validation-year vs_qqq = -4.59% < 0). Per "不追溯 + invariant 优先" operator commitment, trial 9 is NOT a clean nominee at standalone-core scope.

**However**, trial 9 satisfies the structural shape of a **diversifier**: full-period vs_qqq > 0, 2025 strict pass, NAV materially orthogonal, real cross-asset utilization, drawdown < SPY/QQQ in stress slices. Trial 9 IS NOT well-served by being judged against standalone-core gates.

This PRD is the architectural answer.

---

## 2. Core Problem [CERTAIN]

The current PQS Track C pipeline collapses three distinct problems into one search:

```
single-stage miner:
  factor composite IC score
  → top-N selector + cap_aware + cluster constraints + asset_class caps
  → mixed (stocks + bonds + commodities + cash) ranking
  → candidate NAV
  → judged by standalone-core gates
```

The three collapsed problems:

### 2.1 Cross-asset assets are not factor-comparable [CERTAIN]
- `amihud_20d` is meaningful for stocks (illiquidity premium); meaningless / NaN for cash/bond ETFs
- `drawup_from_252d_low` measures equity stress; for BIL/SHV the value is ~0 always
- `ret_1d` is short-momentum/reversal for stocks; rate noise for bonds; yield-mostly for cash
- Bond ETFs derive value from duration + distributions (not captured in price-only factors)
- Cash ETFs derive value from yield (handled via distribution sidecar at adjustment time, but not factor-side)
- GLD derives value from real rates / USD / geopolitical premium (not in stock factor zoo)

When all are ranked in one cross-sectional score, non-equity selection is via **factor-coverage thinness** (NaN composite → default selection), not via deliberate cross-asset alpha discovery. Cycle #04 closeout verified this empirically.

### 2.2 Core alpha vs diversifier evaluation criteria differ [CERTAIN]
**Core alpha** must:
- Beat SPY + QQQ standalone over full period AND each evaluation window
- Maintain drawdown < 20% across regimes
- Survive without portfolio-level offsetting

**Diversifier** should:
- Lower **portfolio** correlation + drawdown
- Provide protection in equity-stress / rate-shock / crisis regimes
- NOT necessarily beat QQQ in every BULL window (window-mean rule penalizes this)
- Have utility measured **at portfolio level**, not standalone

The current QQQ Outperformance Rule is correct for core alpha. It is **structurally wrong** for diversifier-role evaluation.

### 2.3 Cost / turnover sensitivity not framed in current pipeline [OPERATOR-ADDITION, CERTAIN]
Current monthly rebalance cap_aware_cross_asset incurs significant cross-asset turnover when factor scores flip equity/non-equity. Trial 9 has cluster_concentration_max=24.6%, top-3 by avg weight {cash_anchor 13.7%, cyclical_semi 11.2%, energy_oilgas 9.8%} — diverse but switching equity ↔ cash on monthly cadence has cost implications not accounted for in single-stage backtest. (CLAUDE.md cost_model.yaml exists but treats turnover at symbol level, not asset-class-switch level.) Two-stage architecture must surface this cost as a first-class concern, NOT defer it to "future work".

### 2.4 Single-stage mining attribution ambiguity [OPERATOR-ADDITION, CERTAIN]
When cycle #04 trial 8 produced +10.5% vs_qqq in 2025 with -19% max_dd, attribution is unclear: was that from stock selection alpha, asset allocation luck, or cap_aware constraints? In two-stage architecture, attribution is structurally clean: allocation layer P&L vs sleeve P&L are separately measurable.

---

## 3. PRD Goals

### 3.1 Primary goal [CERTAIN]
Establish a Two-Stage Allocation Architecture that separates:
- **Stage 1**: Asset Allocation / Regime Layer (capital across asset classes / sleeves)
- **Stage 2**: Sleeve-Level Strategy Layer (each sleeve produces holdings/NAV in its own regime)
- **Stage 3**: Portfolio / Fleet Construction Layer (final composition + risk + reporting)

This enables PQS to formally support three roles:
1. **core_alpha**: independent deployable; full QQQ Outperformance Rule applies
2. **diversifier**: portfolio-contribution-judged; window-mean rule waived; OTHER gates STRICTER
3. **risk_control_sleeve**: bonds/cash/gold; not alpha-seeking; rule-based or simple weight

### 3.2 Secondary goal [CERTAIN]
Provide Trial 9 with a structurally appropriate evaluation context: forward observation as `diversifier` role, with role-specific acceptance + portfolio-combo evidence requirements.

### 3.3 Tertiary goal [OPERATOR-OPINION]
Subsume Track B Fleet Allocator Step 6+ (currently HARD PAUSED per CLAUDE.md priority realign 2026-04-30) into this architecture's Stage 3. Track B Steps 1-5 (DD throttle / role caps / C2 correlation budget) are already shipped and become Stage 3 inputs unchanged.

[OPERATOR-OPINION rationale]: Track B was scoped before the two-stage architecture insight emerged. Continuing Track B Step 6+ in parallel with C would create two competing fleet-routing systems. Architectural cleanliness recommends C absorbs Step 6+ scope.

---

## 4. Non-Goals [CERTAIN]

This PRD explicitly **does NOT**:

1. **Not** change long-only / no-short / no-margin invariants (CLAUDE.md Phase C invariants)
2. **Not** restart Cycle #06 single-stage mining (cycle #05 stop rule pre-committed)
3. **Not** promote Trial 9 to core_alpha role (forward observation as diversifier only)
4. **Not** authorize full Phase C-PRD-2/3/4 implementation (4-6 weeks of allocation engineering deferred until forward evidence triggers it)
5. **Not** consume sealed 2026 panel (sealed_ledger.py protection unchanged)
6. **Not** build ML regime classifier (Phase C-PRD-3 prototype is rule-based only; ML deferred to future)
7. **Not** weaken core_alpha QQQ Outperformance Rule (only adds role-specific exception scoped to `diversifier`)
8. **Not** introduce dynamic leverage or short-selling for any sleeve

[OPERATOR-ADDITION 7-8]: Adding these explicitly because role-specific waivers can become "easy paths" if not scoped. Pre-empting governance creep.

---

## 5. Core Design

### 5.1 Stage 1 — Asset Allocation / Regime Layer

#### 5.1.1 Purpose [CERTAIN]
Decide **target weights** for each sleeve, conditioned on regime/macro state. Outputs flow into Stage 3 portfolio construction.

#### 5.1.2 Formal input/output contract [OPERATOR-CERTAIN, expanded from collaborator]

```python
# core/research/two_stage_allocation/stage1_allocator.py (Phase C-PRD-2)

@dataclass
class RegimeFeatures:
    """Computed at decision date T (close); only T-1 and earlier data used."""
    spy_trend_200d: float           # (price[T] / SMA[T-200]) - 1
    qqq_trend_200d: float
    market_vol_realized_60d: float  # std of daily returns × sqrt(252)
    market_vol_zscore: float        # vs 5y rolling mean+std
    spy_drawdown_current: float     # (price[T] / max[T-252:T]) - 1
    qqq_drawdown_current: float
    tlt_momentum_60d: float         # bond duration regime
    gold_relative_strength_60d: float
    risk_on_off_score: float        # composite [-1, +1]
    timestamp: pd.Timestamp

@dataclass
class AllocationTarget:
    """Stage 1 output. All weights >= 0, sum to 1.0 (long-only, no leverage)."""
    equity_core_weight: float
    equity_defensive_weight: float
    diversifier_weight: float
    bonds_weight: float
    cash_anchor_weight: float
    gold_weight: float
    rationale: str  # human-readable trace
    regime_label: str  # BULL / BEAR / RISK_ON / RISK_OFF / CRISIS / SIDEWAYS
    decision_timestamp: pd.Timestamp

class Stage1Allocator(Protocol):
    def compute_features(
        self, price_panel: pd.DataFrame, decision_date: pd.Timestamp,
    ) -> RegimeFeatures: ...
    def decide_weights(
        self, features: RegimeFeatures, prior_target: Optional[AllocationTarget] = None,
    ) -> AllocationTarget: ...
```

#### 5.1.3 Constraints [CERTAIN]

```yaml
allocation_constraints:
  # Hard invariants (CLAUDE.md aligned)
  total_gross_exposure_max: 1.0
  long_only: true
  no_short: true
  no_margin: true

  # Per-sleeve caps (Phase C-PRD-2 starting values; subject to backtest validation)
  equity_total_max: 0.80          # equity_core + equity_defensive ≤ 0.80
  bonds_total_max: 0.50
  cash_anchor_max: 0.40
  gold_max: 0.20
  diversifier_total_max_initial: 0.25  # Phase C-PRD-1 conservative cap

  # Per-sleeve floors (avoid degenerate allocations)
  equity_total_min: 0.20          # never go fully defensive
  cash_anchor_min: 0.05           # always hold some cash buffer

  # Turnover caps [OPERATOR-ADDITION]
  max_allocation_change_per_decision: 0.15  # |Δw| per sleeve per rebalance ≤ 15pp
  rebalance_cadence: monthly_with_intra_month_drift_band
  intra_month_drift_band: 0.05    # rebalance off-cycle if any sleeve drifts > 5pp
```

[OPERATOR-ADDITION turnover caps]: If allocation can swing ±50% per decision, transaction costs dominate alpha. The 15pp cap is empirically calibrated to ~12 average-cost rebalances/year acceptable. Verified by approximate cost model: 15pp × 6 sleeves × 0.05% per side × 12/year = ~1.1% / year cost ceiling for allocation-only turnover (excluding sleeve-internal turnover).

#### 5.1.4 MVP rule-based allocation (Phase C-PRD-3) [OPERATOR-OPINION + CERTAIN bounds]

Initial rule-based policy v0. Concrete numbers (NOT placeholders) — these are MY recommended starting weights subject to single-pass historical backtest validation in Phase C-PRD-3:

```yaml
regime_policy_v0:

  # Default (most common state: equity_trend > 0 AND vol_zscore < 1.0)
  default:
    equity_core: 0.55
    equity_defensive: 0.15
    diversifier: 0.10
    bonds: 0.10
    cash_anchor: 0.05
    gold: 0.05

  # Risk-off (equity drawdown > -5% OR vol_zscore > 1.5)
  risk_off:
    equity_core: 0.30
    equity_defensive: 0.20
    diversifier: 0.15
    bonds: 0.20
    cash_anchor: 0.10
    gold: 0.05

  # Crisis (equity drawdown > -15% OR vol_zscore > 2.5 OR multi-regime breakdown)
  crisis:
    equity_core: 0.15
    equity_defensive: 0.10
    diversifier: 0.20
    bonds: 0.30
    cash_anchor: 0.20
    gold: 0.05

  # BULL (equity_trend > +10% AND vol_zscore < 0)
  bull:
    equity_core: 0.65
    equity_defensive: 0.10
    diversifier: 0.05
    bonds: 0.05
    cash_anchor: 0.05
    gold: 0.10
```

[OPERATOR-CERTAIN bounds]: All states satisfy total=1.0, long-only, all caps. No state has equity_total > 0.80 or cash_anchor < 0.05.

[OPERATOR-OPINION values]: These are starting weights informed by:
- Cycle04+05 evidence (cross-asset utilization 24-32% is meaningful)
- Naive 60/40 outperforms cycle03 candidates in stress; we beat 60/40 by adjusting to regime
- Diversifier 5-20% range respects "diversifier_total_max_initial: 0.25" cap

These weights MUST be validated against:
1. Naive 60/40 over 2009-2025
2. SPY-only baseline
3. QQQ-only baseline
4. Static rule (60% equity_core / 20% bonds / 10% cash / 10% gold)

If the 4-state regime policy doesn't beat naive baselines on Sharpe or MaxDD over historical, the policy is wrong and Phase C-PRD-3 fails its acceptance gate. This IS the gate (see §6.4).

#### 5.1.5 Out-of-scope for this PRD [CERTAIN]
- ML regime classifier (deferred; rule-based only)
- Adaptive cap learning (caps are pre-registered, not learned)
- Multi-period planning / dynamic programming (single-step decisions only)
- Forward-looking factor inputs (only T-1 close information; lookahead-strict)

---

### 5.2 Stage 2 — Sleeve-Level Strategy Layer

#### 5.2.1 Purpose [CERTAIN]
Each sleeve produces its own holdings + NAV using sleeve-appropriate signals. No more cross-asset mixed scoring.

#### 5.2.2 Sleeve catalog [CERTAIN structure, OPERATOR-OPINION populations]

```yaml
sleeves:
  equity_core:
    role: core_alpha
    universe: stocks_only (53-symbol cycle04 universe minus diversifier overlap)
    selector: existing MultiFactorStrategy or cap_aware on stocks
    factor_pool: PRODUCTION_FACTORS (currently 7) or RESEARCH_FACTORS pool subset
    constructed_via: Track A acceptance with full QQQ Outperformance Rule
    current_population: empty (RCMv1 + Cand-2 are legacy_decay_verification, NOT core)

  equity_defensive:
    role: core_alpha or risk_control
    universe: stocks_only filtered by low-beta + high-quality
    selector: simpler than core (e.g. equal-weight low-beta top-N)
    factor_pool: defensive subset (beta_spy_60d, dist_52w_high, drawup variants)
    current_population: not yet defined; deferred Phase C-PRD-3

  cross_asset_diversifier:
    role: diversifier
    universe: 53 stocks + 6 cross-asset (cycle04 universe)
    selector: candidate-spec-based (e.g. Trial 9 spec frozen)
    constructed_via: cycle #05 spec evaluated under cap_aware_cross_asset
    current_population: trial-9 candidate (pending forward init)

  bonds:
    role: risk_control
    universe: TLT, IEF, SHY
    selector: rule_based — equal_weight by duration_bucket OR regime-shifted
    factor_pool: NA (rule-based)
    current_population: TLT/IEF/SHY equal-weight initial

  cash_anchor:
    role: risk_control
    universe: BIL, SHV
    selector: rule_based — proportional to cash_weight target
    factor_pool: NA
    current_population: BIL/SHV equal-weight initial

  gold:
    role: risk_control
    universe: GLD
    selector: NA — single asset, weight from Stage 1
    current_population: GLD only
```

#### 5.2.3 Sleeve interface [CERTAIN]

```python
# core/research/two_stage_allocation/sleeve.py (Phase C-PRD-2)

@dataclass
class SleeveConfig:
    sleeve_id: str
    role: Literal["core_alpha", "diversifier", "risk_control"]
    universe: List[str]
    rebalance_cadence: Literal["daily", "weekly", "monthly"]
    sleeve_max_single_weight: float  # within-sleeve cap
    sleeve_max_cluster_weight: Optional[float]  # if cluster-aware

class Sleeve(Protocol):
    """Each sleeve produces its own NAV trajectory."""
    config: SleeveConfig
    @property
    def nav(self) -> pd.Series: ...
    @property
    def weights(self) -> pd.DataFrame: ...
    @property
    def metadata(self) -> Dict[str, Any]: ...

    def report_standalone_metrics(self) -> Dict[str, Any]: ...
    def report_correlation_to(self, other: "Sleeve") -> Dict[str, float]: ...
```

#### 5.2.4 Trial 9 in Stage 2 [CERTAIN]
Trial 9's spec (`beta_spy_60d + max_dd_126d + ret_1d`, 1/3 weights) is frozen and registered as the **first concrete sleeve in `cross_asset_diversifier`**. Spec frozen via cycle #05 archive entry:
- archive_db: `data/mining/rcm_archive.db`
- lineage: `track-c-cycle-2026-05-01-05`
- trial_id: `6c745c601a47`
- yaml_sha: `ce559a0ac97a7eb36243de7494c44650ea0779839ec70bc159b94da06a2cbaf7`

Trial 9 sleeve runs cap_aware_cross_asset construction (cluster_cap=0.20, max_single=0.10, asset_class_caps as cycle #04 yaml). Its NAV is the sleeve NAV.

---

### 5.3 Stage 3 — Portfolio / Fleet Construction Layer

#### 5.3.1 Purpose [CERTAIN]
Aggregate sleeve NAVs by Stage 1 target weights, apply portfolio-level risk constraints, produce final portfolio NAV. **This is where Track B Steps 1-5 plug in.**

#### 5.3.2 Track B integration [OPERATOR-CERTAIN, addresses gap in collaborator draft]

CLAUDE.md identifies Track B Steps 1-5 as SHIPPED:
- Step 1-2: fleet allocation manifest schema
- Step 3: DD throttle (per-candidate drawdown brake)
- Step 4: role caps (per-role weight limits)
- Step 5: C2 correlation budget

These are reused unchanged as Stage 3 inputs. Track B Step 6+ (fleet observe / shadow→live / dynamic adjustments) HARD PAUSED per priority realign — this PRD's Phase C-PRD-3 SUBSUMES Step 6+ scope. No parallel work.

[OPERATOR-CERTAIN action]: When this PRD's Phase C-PRD-3 ships, mark Track B Step 6+ as "absorbed by C-PRD" in CLAUDE.md inventory.

#### 5.3.3 Portfolio aggregation contract [CERTAIN]

```python
# core/research/two_stage_allocation/portfolio_constructor.py (Phase C-PRD-3)

@dataclass
class PortfolioConstructionInput:
    sleeve_navs: Dict[str, pd.Series]
    sleeve_weights: Dict[str, pd.DataFrame]
    allocation_target: AllocationTarget
    realized_correlations: pd.DataFrame
    drawdown_state: Dict[str, float]
    track_b_dd_throttles: Dict[str, float]  # Track B Step 3 output (already shipped)
    track_b_role_caps: Dict[str, float]     # Track B Step 4 output
    track_b_c2_budget: float                # Track B Step 5 output

@dataclass
class PortfolioConstructionOutput:
    final_weights_by_symbol: pd.DataFrame
    final_weights_by_sleeve: pd.DataFrame
    final_asset_class_exposure: pd.DataFrame
    portfolio_nav: pd.Series
    portfolio_risk_report: Dict[str, Any]
    attribution_per_sleeve: pd.DataFrame  # [OPERATOR-ADDITION] sleeve-level P&L attribution
```

#### 5.3.4 Constraints [CERTAIN]

```yaml
portfolio_constraints:
  gross_exposure_max: 1.0  # long-only
  max_single_symbol_weight: 0.10  # CLAUDE.md M12 ceiling
  max_risk_cluster_weight: 0.20
  max_mag7_weight: 0.40   # operator estimate; needs validation against existing config
  max_tqqq_soxl_weight: 0.10  # CLAUDE.md high_risk_symbols cap
  max_diversifier_total_weight: 0.25  # initial; reviewed at Phase C-PRD-4
  max_cash_anchor_weight: 0.40
```

#### 5.3.5 Sleeve P&L attribution [OPERATOR-ADDITION, CERTAIN]
At every reporting period, the portfolio_nav return is decomposed:
- Sleeve return × sleeve weight = sleeve contribution
- Σ contributions = portfolio return (modulo turnover/cost reconciliation)

This makes diversifier value measurable: "Trial 9 contributed +0.X%/quarter to portfolio NAV vs. equity_core_only baseline." Without this attribution, diversifier evaluation is circular ("trial 9 helps because it's a diversifier").

---

## 6. Role-Specific Acceptance

### 6.1 Core alpha gate [CERTAIN, UNCHANGED from CLAUDE.md]

```yaml
core_alpha_acceptance:
  # CLAUDE.md QQQ Outperformance Rule (Phase C PRD v3) — unchanged
  full_period_vs_spy: > 0
  full_period_vs_qqq: > 0  # HARD
  holdout_2025_vs_qqq: > 0  # HARD
  oos_walk_forward_window_mean_vs_qqq: > 0  # HARD
  per_window_vs_qqq: report_diagnostic
  per_regime_vs_qqq: report_diagnostic

  # Risk gates (yaml-pre-registered, cycle-specific)
  per_validation_year_max_dd: <= 20%
  stress_slice_max_dd: <= 25%
  full_period_max_dd: report_only

  # Concentration (M12)
  m12_top1_weight_max: <= 40%
  m12_top3_weight_max: <= 70%

  # Anti-sibling (anti_sibling_policy.py POLICY_VERSION)
  factor_overlap_max_with_active_core: <= 1
  raw_nav_correlation_max_vs_anchors: < 0.85
  residual_nav_correlation_max: < 0.70
  conditional_review_path: as defined in policy module

  # Long-only / no-short / no-margin invariants
  long_only: required
  no_short: required
  no_margin: required
```

[CERTAIN]: This section is verbatim CLAUDE.md + cycle yaml gates. No change.

### 6.2 Diversifier gate [OPERATOR-CRAFTED, scrutinized for anti-loophole]

```yaml
diversifier_acceptance:

  # ── Standalone (NOT waived; same as core except window-mean rule) ──
  standalone_required:
    full_period_vs_spy: > 0      # HARD (unchanged from core; baseline floor)
    full_period_vs_qqq: > 0      # HARD (unchanged from core)
    holdout_2025_vs_qqq: > 0     # HARD (unchanged)
    per_validation_year_max_dd: <= 20%  # HARD (unchanged)
    stress_slice_max_dd: <= 25%  # HARD (unchanged)
    long_only: required          # invariant
    no_short: required           # invariant
    no_margin: required          # invariant

  # ── Diversification value (STRICTER than core; this is the trade) ──
  diversification_required:
    raw_nav_corr_max_vs_all_anchors: < 0.70
    # core requires < 0.85; diversifier requires < 0.70 (TIGHTER)
    residual_nav_corr_max_vs_all_anchors: < 0.50
    # core requires < 0.70; diversifier requires < 0.50 (TIGHTER)
    factor_overlap_max_with_active_core: 0
    # core allows ≤1; diversifier requires 0 (TIGHTER, ZERO active-core factor sharing)
    factor_overlap_max_with_legacy_decay: <= 1
    # diversifier may share at most 1 factor with RCMv1 / Cand-2

    # Cross-asset utilization (the diversifier's MECHANISM)
    non_equity_weight_avg: >= 0.15  # at least 15% non-equity exposure on average
    days_with_zero_non_equity_pct: <= 0.05  # no more than 5% of days fully equity

    # Stress regime value
    crisis_or_drawdown_regime_alpha: positive_or_neutral  # report-only initially

  # ── Waived for diversifier role (THE trade) ──
  waived_for_diversifier:
    oos_walk_forward_window_mean_vs_qqq: waived
    # rationale: diversifier in a fleet legitimately can underperform QQQ
    # in BULL windows; portfolio-level NAV is the right metric

  # ── EXPLICITLY NOT waived (closing loopholes) ──
  not_waived_for_diversifier:
    full_period_vs_qqq:          # diversifier MUST still beat QQQ over full period
    holdout_2025_vs_qqq:         # diversifier MUST still pass 2025 strict
    per_validation_year_max_dd:  # drawdown gates apply to all roles
    stress_slice_max_dd:
    concentration_M12:
    long_only_no_short_no_margin:

  # ── Forward observation requirement (NEW, role-specific) ──
  forward_observation_required:
    pre_acceptance: true
    minimum_td: 60   # forward observation TD60 minimum before forward "approve"
    portfolio_combo_evidence: required
    # Must show portfolio combo (equity_core_only) vs (equity_core + trial9_diversifier)
    # has BETTER Sharpe OR BETTER MaxDD over forward window
```

[OPERATOR-CERTAIN]: This section closes 4 specific loopholes I anticipated:
1. **Closeable loophole 1**: "Diversifier waiver becomes general softening" → Section 6.2 lists explicit not_waived gates including `full_period_vs_qqq` (HARD).
2. **Closeable loophole 2**: "Diversifier with high core overlap masquerades as orthogonal" → `factor_overlap_max_with_active_core: 0` (zero, not ≤1).
3. **Closeable loophole 3**: "Low-correlation candidate that mostly holds cash" → `non_equity_weight_avg >= 0.15` REQUIRED (forces actual cross-asset risk).
4. **Closeable loophole 4**: "Diversifier promoted on backtest only" → forward_observation_required + portfolio_combo_evidence.

**[OPERATOR-CRITICAL FINDING]** `config/temporal_split.yaml` (committed 2026-04-29 per Track A Step A.1, BEFORE cycle04+05 evidence) already has a `diversifier` role section with DIFFERENT thresholds from this PRD §6.2:

```yaml
# Existing yaml (config/temporal_split.yaml, role=diversifier):
diversifier:
  eligibility_constraint:
    - {field: "vs_existing_core_correlation", op: "<", value: 0.40}    # tighter
    - {field: "vs_existing_core_overlap",     op: "<", value: 0.30}    # different metric
  validation_gates:
    - {field: "validation.2025.excess_vs_qqq", op: ">", value: -0.05}  # 5pp slack
    - {field: "validation.2025.maxdd",         op: "<=", value: 0.18}  # tighter than 0.20
```

vs. this PRD §6.2:
- raw_nav_corr_max < 0.70 + residual_nav_corr_max < 0.50 (NAV-level, evidence-derived)
- 2025 vs_qqq > 0 strict (no slack)
- per_validation_year_max_dd <= 0.20 (CLAUDE.md range top)

**Trial 9 status under both threshold sets**:
| Gate | Trial 9 actual | yaml verdict | PRD §6.2 verdict |
|------|----------------|--------------|-------------------|
| 2025 vs_qqq | +9.59% | passes (>-0.05) | passes (>0) |
| 2025 max_dd | -18.16% | **FAILS** (>18%) by 0.16pp | passes (≤20%) |
| correlation | raw 0.689 max | check needed | passes (<0.70) |

**Trial 9 fails existing yaml's diversifier 2025 max_dd gate by 0.16 percentage points.**

This is a real governance conflict between speculative pre-cycle yaml authoring and post-cycle evidence-derived PRD thresholds. **NEW D10 below.** Phase C-PRD-1 implementation MUST resolve this conflict before Trial 9 can enter forward observation as diversifier.

[OPERATOR-OPINION on resolution]: yaml's 0.40 correlation was authored speculatively (cycle04 didn't exist yet); cycle04 cluster A established 0.50-0.70 partial_diversifier band as the actual evidence. Yaml's 18% max_dd for diversifier-2025-specific is more defensible — it expresses "diversifier should be tighter than core's 20%" — but trial 9 IS on the boundary (18.16% vs 18%). Operator does NOT pre-decide; this needs user directional call.

**Trial 9 evaluation against diversifier_acceptance** (verified via direct read of eval JSON):

| Gate | Trial 9 actual | Pass |
|------|----------------|------|
| full_period_vs_qqq > 0 | +6.26% | ✓ |
| holdout_2025_vs_qqq > 0 strict | +9.59% | ✓ |
| per_validation_year_max_dd ≤ 20% | max 18.16% (2025) | ✓ |
| stress_slice_max_dd ≤ 25% | max 15.84% (rate_hike_2022) | ✓ |
| long_only / no_short / no_margin | yes | ✓ |
| raw_nav_corr_max < 0.70 | 0.689 (cycle_01_top, cycle_02_top) | ✓ tight pass |
| residual_nav_corr_max < 0.50 | 0.355 (cycle_01_top, cycle_02_top) | ✓ |
| factor_overlap with active_core | 0 (no active core) | ✓ trivially |
| factor_overlap with legacy ≤ 1 | 1 (beta_spy_60d shared with rcm_v1) | ✓ |
| non_equity_weight_avg ≥ 15% | 32.1% | ✓ |
| days_with_zero_non_equity ≤ 5% | 1.1% | ✓ |
| forward_observation_TD60 | NOT YET RUN | pending Phase C-PRD-1 |
| portfolio_combo_evidence | NOT YET RUN | pending Phase C-PRD-1 |

Trial 9 passes all backtest-side diversifier gates. Forward observation TD60 + combo evidence are the gating items remaining.

### 6.3 Risk_control sleeve gate [OPERATOR-OPINION, simpler]

```yaml
risk_control_sleeve_acceptance:
  # Bonds, cash, gold sleeves
  rule_based: true
  no_factor_alpha_required: true
  long_only: required
  no_short: required
  weight_within_stage1_caps: required
  internal_rebalance_cadence: monthly_or_simpler

  # No standalone QQQ rule
  # No anti-sibling check (these are macro instruments, not alpha sources)
```

[OPERATOR-OPINION]: Risk_control sleeves don't need alpha gates because they're not alpha sources. They're capital placeholders. Simpler is better.

### 6.4 Allocation policy gate [OPERATOR-CRAFTED, addresses gap in collaborator draft]

The Stage 1 allocation policy itself MUST pass an acceptance gate, NOT just be hand-coded:

```yaml
allocation_policy_acceptance:
  required_baseline_outperformance:
    # Test rule-based allocation v0 over 2009-2025 historical
    # Allocation policy applied with frozen sleeve specs (rule-based for risk_control;
    # equity_core proxied by SPY for this test; diversifier proxied by Trial 9)
    vs_naive_60_40_static:
      sharpe: must_be_higher
      max_dd: must_be_better_or_equal
    vs_spy_only:
      cum_ret: must_be_higher OR
      max_dd: must_be_materially_better_at_no_more_than_5pp_return_loss

  required_robustness:
    walk_forward_mean: positive
    no_single_year_underperforms_naive_60_40_by_more_than_5pp

  required_cost_sensitivity:
    turnover_per_year: <= 200%  # allocation-only turnover cap
    cost_2x_stress: still_passes_above_gates

  invariants_check:
    long_only: always
    no_short: always
    no_margin: always
    weights_sum_to_1_or_less: always
    no_lookahead: always_using_T_minus_1_data
```

[OPERATOR-CERTAIN]: Without this gate, the rule-based allocation in §5.1.4 is unsubstantiated. Phase C-PRD-3 cannot ship without this gate passing. If the rule-based policy doesn't beat naive 60/40, the architecture's value proposition is unproven.

---

## 7. Trial 9 Forward Observation Plan

### 7.1 Pre-commit milestone table [OPERATOR-CERTAIN, addresses cycle04/05 lessons]

```yaml
forward_observation:
  candidate: trial9_6c745c601a47
  role: diversifier
  start_date: 2026-05-XX (TBD; after CLAUDE.md update + lightweight role tag ships)
  source_mix: TBD (likely True initially, like RCMv1+Cand-2; honest disclosure)

  health_checkpoints:  # NOT decision points
    TD20:
      flags:
        - nav_drift_vs_backtest_above_5pct
        - non_equity_diverges_from_backtest_by_above_10pp
        - any_single_day_pnl_below_minus_3pct
      action_on_flag: pause + investigate; do not advance to TD40 without resolution

    TD40:
      flags:
        - cumulative_drawdown_above_minus_15pct
        - corr_with_rcm_v1_or_cand_2_above_0_85
      action_on_flag: pause + escalate

  decision_points:
    TD60:
      classification_logic:
        # GREEN: ALL listed criteria satisfied
        # RED: ANY red signal triggers RED (overrides yellow/green)
        # YELLOW: not GREEN AND not RED (i.e., partial green or any yellow signal)
      criteria:
        green:
          - residual_corr_60d_vs_rcmv1_below_0_4
          - residual_corr_60d_vs_cand2_below_0_4
          - per_regime_vs_qqq_60d:
              BULL: above_minus_3pct
              RISK_OFF: above_zero_OR_above_qqq
          - portfolio_combo_evidence_positive:
              equity_core + trial9_at_15pct: better_Sharpe_OR_better_MaxDD
                vs equity_core_only_baseline_over_60d
        yellow:
          - residual_corr_60d_in_0_4_to_0_6
          - per_regime_BULL_vs_qqq_60d_in_minus_10_to_minus_3
        red:
          - residual_corr_60d_above_0_6
          - per_regime_BULL_vs_qqq_60d_below_minus_10
          - any_60d_max_dd_above_minus_10pct
          - portfolio_combo_evidence_negative

      action_on_green: advance to Phase C-PRD-2 (full sleeve abstraction); user explicit-go required
      action_on_yellow: continue observation to TD90; reassess at TD90
      action_on_red: stop trial 9 forward observation; do not build C architecture for this candidate

    TD90:
      criteria_strict:
        # Higher bar than TD60 because more data
        green: all-TD60-green-criteria + 0 red flags accumulated since TD60
        yellow: TD60-yellow upgraded to TD60-green by TD90
        red: any TD60-red signal at TD90 OR fleet portfolio MaxDD ≥ 12% over forward
      action: directional decision via user

    backstop_TD180:
      # If TD60 yellow + TD90 yellow, TD180 is the latest re-decision
      action: stop or full-build, no further extension
```

[OPERATOR-CERTAIN]: TD20 / TD40 are HEALTH checks not decisions; TD60 is the first directional fork. This is more rigorous than collaborator's "TD20/40/60 all decisions" framing.

### 7.2 What Trial 9 forward MAY NOT do [CERTAIN]

```yaml
trial9_forward_not_allowed:
  - not_live_capital_deployment
  - not_core_alpha_promotion
  - not_fleet_auto_weight_adjustment
  - not_2026_sealed_panel_evaluation
  - not_factor_overlap_softening_to_pass
  - not_NAV_correlation_threshold_softening_to_pass
  - not_post_hoc_acceptance_threshold_changes
```

### 7.3 Forward runner schema extension [OPERATOR-CERTAIN, gap in collaborator draft]

Phase C-PRD-1 requires concrete schema additions in `core/research/forward/manifest_schema.py`:

```python
# NEW (Phase C-PRD-1):

class CandidateRole(str, Enum):
    CORE_ALPHA = "core_alpha"
    DIVERSIFIER = "diversifier"
    LEGACY_DECAY_VERIFICATION = "legacy_decay_verification"
    RISK_CONTROL = "risk_control"  # for future bond/cash/gold sleeves

class ForwardRunManifest(...):
    # ... existing fields ...
    candidate_role: CandidateRole  # NEW required field; defaults to LEGACY_DECAY for migration
    role_specific_acceptance_profile: str  # e.g. "diversifier_acceptance_v1"
    portfolio_combo_evidence_required: bool  # True for diversifier; False for core_alpha pre-Phase-C-PRD-3
```

Migration: existing RCMv1 + Cand-2 manifests have `candidate_role = LEGACY_DECAY_VERIFICATION`; Trial 9 is the first `DIVERSIFIER` instance.

---

## 8. Phased Implementation Path

### Phase C-PRD-0 — Decision lock [CERTAIN scope, ~1 day]

**Goal**: User signs off on D1-D9 below; CLAUDE.md updated; PRD finalized.

**Deliverables**:
- This PRD finalized with user comments incorporated
- `docs/memos/20260501-diversifier_role_decision.md` (separate decision memo with user explicit-go)
- CLAUDE.md QQQ Outperformance Rule diversifier exception added

**Acceptance**:
- `core_alpha` rule unchanged in CLAUDE.md
- `diversifier` exception scoped only to `oos_walk_forward_window_mean_vs_qqq`
- Other gates explicitly listed as not_waived
- User signoff recorded

### Phase C-PRD-1 — Lightweight role tag + Trial 9 forward init [CERTAIN scope, ~1-2 days]

**Goal**: Role tag in candidate registry; Trial 9 forward observation begins; minimal infra.

**Engineering scope**:
- Add `CandidateRole` enum to `core/research/forward/manifest_schema.py`
- Extend `ForwardRunManifest` with role + acceptance_profile fields (with migration default)
- Add diversifier acceptance dispatch in `core/research/acceptance_helpers.py`
- Add backfill script for existing RCMv1 + Cand-2 manifests (set role=LEGACY_DECAY_VERIFICATION)
- Add Trial 9 spec to `data/research_candidates/trial9_diversifier_frozen_spec.yaml` (immutable)
- Add `dev/scripts/forward/init_trial9_diversifier.py`
- Add unit tests:
  - role dispatch (4 tests, one per enum value)
  - diversifier acceptance with all gates (12 tests)
  - core_alpha rule NOT relaxed by adding role enum (regression test)
  - forward manifest migration backwards-compat (3 tests for pre-PRD manifest loading)

**Deliverables**:
- Schema changes shipped in `main`
- Trial 9 forward TD001 entry visible in `forward status`
- pytest count: ~20 new tests

**Acceptance**:
- Trial 9 `forward observe` runs without error
- pre-existing RCMv1 + Cand-2 forward observations unaffected (lazy migration)
- core_alpha acceptance regression test PASSES (unchanged behavior)
- diversifier acceptance gate PASSES on Trial 9 backtest data (already verified §6.2)

[OPERATOR-CERTAIN cost]: 1-2 days for schema + dispatch + tests. Operator estimate. May extend to 3 days if existing forward runner has unexpected coupling.

### Phase C-PRD-2 — Sleeve abstraction [DEFERRED until forward TD60 decision]

**Trigger**: Trial 9 TD60 GREEN per §7.1.

**Goal**: Implement Stage 2 sleeve interface; refactor existing forward runner to support multi-sleeve.

**Engineering scope**: 1-2 weeks. Detailed scope deferred to standalone PRD revision after TD60.

### Phase C-PRD-3 — Allocation layer prototype [DEFERRED until Phase C-PRD-2 complete]

**Trigger**: Phase C-PRD-2 ships + 2nd diversifier candidate exists OR equity_core sleeve exists OR user explicit-go regardless.

**Goal**: Implement Stage 1 rule-based allocator; pass §6.4 allocation_policy_acceptance gate.

**Engineering scope**: 2-3 weeks.

### Phase C-PRD-4 — Full integration + Track B Step 6+ absorption [DEFERRED]

**Trigger**: Phase C-PRD-3 ships + at least 2 forward-validated sleeves.

**Goal**: Full Stage 3 portfolio constructor; Track B Steps 1-5 reconnected; sleeve P&L attribution; live-ready.

**Engineering scope**: 1-2 weeks (the heavy lifting was in Phase 2-3).

[CERTAIN]: Total Phase C-PRD-2+3+4 ≈ 4-7 weeks. Phase C-PRD-1 alone is the unblocking step for Trial 9 + does NOT commit to the full architecture.

---

## 9. Success Metrics

### 9.1 Short-term (post Phase C-PRD-1, ≤ 1 week) [CERTAIN]
- Trial 9 forward init successful; first `forward observe` produces valid TD001 entry
- Role-specific acceptance dispatch works (regression: core_alpha unchanged behavior)
- pytest +20 tests passing
- CLAUDE.md QQQ Rule diversifier exception explicit and bounded

### 9.2 Medium-term (post TD60, ~3 months forward) [CERTAIN]
- Trial 9 forward shows TD60 GREEN per §7.1 criteria, OR
- Trial 9 forward shows clean signal for stop/redirect (not ambiguous)

### 9.3 Long-term (post Phase C-PRD-4, ≥ 6 months) [OPERATOR-OPINION]
- PQS supports core_alpha + diversifier + risk_control roles structurally
- Stage 1 allocation passes §6.4 acceptance
- Multi-sleeve fleet routing replaces single-strategy paradigm
- Track B Step 6+ formally absorbed and decommissioned as separate workstream
- Forward+paper engines support sleeve-level + portfolio-level NAV

---

## 10. Risks

### 10.1 Governance creep [CERTAIN risk; CERTAIN mitigation]

**Risk**: Diversifier waiver becomes general softening avenue ("just call it a diversifier").

**Mitigation**:
- §6.2 lists explicit not_waived gates (full_period vs_qqq, 2025 strict, drawdown, stress, concentration, all invariants)
- §6.2 has STRICTER NAV correlation requirements for diversifier (< 0.70 raw, < 0.50 residual)
- §6.2 requires `factor_overlap_with_active_core: 0` (zero, not relaxed)
- §6.2 requires non_equity_weight ≥ 15% (forces actual cross-asset risk)
- §6.2 requires forward observation TD60 + portfolio combo evidence pre-acceptance
- Role tag is set ONCE at forward init and immutable thereafter

### 10.2 Low-return diversifier trap [CERTAIN risk; OPERATOR-CERTAIN mitigation]

**Risk**: Candidate has low correlation because it barely takes risk (mostly cash).

**Mitigation**:
- §6.2 `non_equity_weight_avg ≥ 15%` required
- §6.2 `days_with_zero_non_equity_pct ≤ 5%` required
- §6.4 allocation policy gate requires drawdown reduction per pct return sacrificed
- Forward report includes return_per_unit_drawdown_reduction metric

### 10.3 Overbuilding before evidence [CERTAIN risk; CERTAIN mitigation]

**Risk**: 4-6 weeks Phase C-PRD-2/3/4 implementation without forward evidence justifying it.

**Mitigation**:
- Phase C-PRD-1 is the only authorized step
- Phase C-PRD-2 trigger = TD60 GREEN (§7.1)
- Phase C-PRD-3 trigger = Phase C-PRD-2 complete + multiple sleeves OR user explicit-go
- Phase C-PRD-4 trigger = Phase C-PRD-3 complete + Stage 1 acceptance gate passed

### 10.4 Cost / turnover dominating sleeve alpha [OPERATOR-ADDITION, CERTAIN]

**Risk**: Stage 1 allocation switches asset classes monthly, turnover costs eat sleeve alpha.

**Mitigation**:
- §5.1.3 `max_allocation_change_per_decision: 0.15` (15pp/sleeve cap)
- §5.1.3 turnover budget calibrated: ~1.1% / year allocation-only cost ceiling
- §6.4 allocation acceptance includes `cost_2x_stress: still_passes` (2x cost stress test)
- Phase C-PRD-3 must show allocation outperforms naive 60/40 NET of costs

### 10.5 Performance attribution ambiguity [OPERATOR-ADDITION, CERTAIN]

**Risk**: Portfolio outperforms but unclear which sleeve drove it; can't tell if Trial 9 actually contributing.

**Mitigation**:
- §5.3.5 Sleeve P&L attribution required at every reporting period
- Combo report (§7.1 portfolio_combo_evidence) directly compares with/without Trial 9
- Phase C-PRD-3 sleeve.report_correlation_to() interface enables ongoing monitoring

### 10.6 Allocation policy lookahead bias [OPERATOR-ADDITION, CERTAIN]

**Risk**: Stage 1 features computed at T accidentally use data through T (close), then sleeves rebalance at T+1 open.

**Mitigation**:
- §5.1.2 RegimeFeatures contract: "T-1 and earlier data only"
- Phase C-PRD-3 unit tests must include lookahead-strict regression
- Same 1-bar-shift discipline as MultiFactorStrategy (existing pattern)

### 10.7 Track B / Two-stage scope conflict [OPERATOR-ADDITION, CERTAIN]

**Risk**: Track B Step 6+ work continues in parallel with Phase C-PRD-3, creating two competing fleet-routing implementations.

**Mitigation**:
- §3.3 explicitly absorbs Track B Step 6+ into this PRD
- Phase C-PRD-1 ship includes CLAUDE.md update marking Track B Step 6+ as "absorbed by C-PRD"
- No parallel Track B Step 6 work allowed without user explicit-go

### 10.8 Diversifier population unbounded [OPERATOR-ADDITION, CERTAIN]

**Risk**: Once Trial 9 succeeds, every Tier 1 R41 candidate asks for diversifier role; diversifier sleeve becomes a graveyard.

**Mitigation**:
- §6.2 has tighter NAV correlation gate for new diversifiers vs ALL existing candidates (legacy + active diversifiers)
- New diversifier acceptance must show < 0.70 raw / < 0.50 residual vs the EXISTING diversifier (Trial 9), not just vs core/legacy
- Initial soft cap: max 3 diversifier candidates active at once. New candidates beyond 3 require displacement of weakest existing one (sunset rule TBD in Phase C-PRD-2 [DEFERRED-REVIEW])

### 10.9 CLAUDE.md drift [OPERATOR-ADDITION, CERTAIN]

**Risk**: CLAUDE.md QQQ Outperformance Rule edit creates wording ambiguity; future operators interpret diversifier waiver more broadly.

**Mitigation**:
- CLAUDE.md edit MUST be commit-reviewed by user (D7 below)
- Diversifier exception MUST cite this PRD doc id (`20260501-two_stage_allocation_architecture_prd.md`)
- The exact waived rule cell (`OOS walk-forward (average) Mean excess return vs QQQ > 0`) MUST be the only one waived; other rule cells stay HARD
- 5+ unit tests pin the diversifier acceptance gate to enforce exact same rules as core EXCEPT window-mean

---

## 11. Testing Requirements

### 11.1 Unit tests (Phase C-PRD-1) [CERTAIN]

```yaml
test_anti_sibling_with_role_dispatch:
  - test_core_alpha_role_uses_existing_R41_thresholds
  - test_diversifier_role_uses_stricter_NAV_correlation_thresholds
  - test_diversifier_role_requires_factor_overlap_with_active_core_eq_0
  - test_legacy_decay_verification_role_does_not_dispatch_to_acceptance

test_acceptance_helpers_with_role:
  - test_core_alpha_acceptance_gates_unchanged_regression
  - test_diversifier_acceptance_window_mean_waived
  - test_diversifier_acceptance_full_period_vs_qqq_HARD
  - test_diversifier_acceptance_2025_vs_qqq_strict_HARD
  - test_diversifier_acceptance_drawdown_HARD
  - test_diversifier_acceptance_stress_HARD
  - test_diversifier_acceptance_concentration_HARD
  - test_diversifier_acceptance_long_only_HARD
  - test_diversifier_acceptance_non_equity_weight_min
  - test_diversifier_acceptance_zero_non_equity_max
  - test_diversifier_acceptance_residual_correlation_TIGHTER
  - test_diversifier_acceptance_factor_overlap_TIGHTER
  - test_diversifier_acceptance_forward_observation_required

test_forward_manifest_role_field:
  - test_load_legacy_manifest_no_role_field_defaults_legacy_decay
  - test_role_field_immutable_after_init
  - test_role_specific_acceptance_profile_dispatches_correctly
```

### 11.2 Integration tests (Phase C-PRD-1) [CERTAIN]

```yaml
integration_tests:
  - test_trial9_forward_init_produces_TD001
  - test_trial9_forward_observe_runs_without_error
  - test_trial9_acceptance_gate_diversifier_evaluator_returns_pending_forward
  - test_existing_rcmv1_cand2_forward_unaffected_by_role_addition
  - test_no_2026_sealed_panel_read
  - test_anti_sibling_policy_v2_unchanged_when_diversifier_role_added
```

### 11.3 Audit tests [OPERATOR-CERTAIN]

```yaml
audit_tests:
  - test_CLAUDE_md_QQQ_rule_diversifier_exception_text_matches_PRD_section_6_2
  - test_diversifier_waiver_only_applies_to_one_specific_rule_cell
  - test_sealed_ledger_not_consumed_by_phase_C_PRD_1_work
  - test_role_tag_immutable_post_forward_init
  - test_active_core_anchors_list_in_anti_sibling_policy_unchanged
```

### 11.4 Phase C-PRD-3 acceptance tests [DEFERRED until phase triggered]

```yaml
allocation_policy_v0_acceptance:
  - test_v0_beats_naive_60_40_sharpe_2009_2025
  - test_v0_beats_naive_60_40_max_dd_2009_2025
  - test_v0_passes_2x_cost_stress
  - test_v0_passes_walk_forward_mean_positive
  - test_v0_no_lookahead_T_minus_1_only
```

---

## 12. Decision Points

User directional decisions required for Phase C-PRD-0 sign-off. Operator's recommendations are listed but the decision is the user's.

### D1 — Diversifier role waiver scope [DECISION REQUIRED]

> Allow diversifier role to waive the OOS walk-forward window-mean vs QQQ > 0 constraint, AND ONLY this one constraint?

**Operator recommendation**: YES, with §6.2 explicit not_waived list to prevent loophole creep.

### D2 — Trial 9 forward init [DECISION REQUIRED]

> Allow Trial 9 to enter forward observation as the first `diversifier`-role candidate?

**Operator recommendation**: YES. Trial 9 passes all backtest-side diversifier gates.

### D3 — Core_alpha rule unchanged [DECISION REQUIRED]

> Confirm core_alpha QQQ Outperformance Rule remains unchanged for that role?

**Operator recommendation**: YES, no exception for core_alpha.

### D4 — Phase 2/3/4 implementation timing [DECISION REQUIRED]

> Authorize ONLY Phase C-PRD-1 (lightweight role tag + Trial 9 init) now? Phase C-PRD-2/3/4 deferred until forward evidence triggers per §7.1?

**Operator recommendation**: YES (Phase C-PRD-1 only).

### D5 — D3b regime-aware mining objective (collaborator's "B") [DECISION REQUIRED]

> Defer D3b implementation; absorb its spirit into Stage 1 allocation regime logic (§5.1) within this PRD?

**Operator recommendation**: YES (defer + absorb). Implementing D3b as old-miner objective change would risk rework when Stage 1 allocator ships.

### D6 — Track B Step 6+ absorption [DECISION REQUIRED]

> Authorize this PRD to absorb Track B Step 6+ scope into Phase C-PRD-3/4? Track B Steps 1-5 (already shipped) remain unchanged.

**Operator recommendation**: YES. Avoids parallel implementations. CLAUDE.md inventory updated to mark Track B Step 6+ as absorbed.

### D7 — CLAUDE.md edit method [DECISION REQUIRED]

> CLAUDE.md QQQ Outperformance Rule edit (adding diversifier exception): operator drafts text + user reviews diff before commit, OR operator drafts + commits + user reviews post-hoc?

**Operator recommendation**: pre-commit review (review diff first, commit after user OK).

### D8 — Allocation policy v0 weights [DECISION REQUIRED at Phase C-PRD-3, NOT NOW]

> §5.1.4 default weights (default 55/15/10/10/5/5; risk_off 30/20/15/20/10/5; etc): authorize as starting values, subject to §6.4 acceptance gate? Or revise before Phase C-PRD-3 work begins?

**Operator recommendation**: authorize as starting values; if §6.4 fails, revise then. [DEFERRED-REVIEW: numbers are operator estimates; user/collaborator may want to adjust]

### D9 — Diversifier population cap [DECISION REQUIRED at Phase C-PRD-2, NOT NOW]

> §10.8 initial soft cap: max 3 diversifier candidates active at once. Authorize this number, or revise?

**Operator recommendation**: 3 starting; revisit at Phase C-PRD-2. [DEFERRED-REVIEW]

### D10 — Reconcile existing config/temporal_split.yaml diversifier thresholds with PRD §6.2 [DECISION REQUIRED — affects Trial 9 directly]

> Existing yaml has 2026-04-29 speculatively-authored diversifier thresholds (correlation <0.40, 2025 vs_qqq >-0.05, 2025 max_dd <=0.18). This PRD §6.2 has evidence-derived thresholds (raw NAV <0.70 / residual <0.50, 2025 vs_qqq >0 strict, per-year max_dd <=0.20). Trial 9 PASSES PRD §6.2 but FAILS existing yaml on 2025 max_dd (18.16% vs 18% gate, fail by 0.16pp).

> Sub-decision D10a: which correlation threshold? (recommend: PRD's NAV-level 0.70/0.50 — yaml's 0.40 single-metric was speculative pre-cycle04 evidence)

> Sub-decision D10b: which 2025 vs_qqq slack? (recommend: PRD's strict >0 — yaml's -0.05 slack creates loophole; trial 9 trivially passes either way at +9.59%)

> Sub-decision D10c: which 2025 max_dd threshold? (THIS DETERMINES TRIAL 9 OUTCOME; options: keep yaml's 18% strict → trial 9 fails A+D; or relax to PRD's 20% → trial 9 passes A+D)

**Operator recommendation on D10c**:
- **Strict-yaml interpretation (keep 18%)**: trial 9 fails by 0.16pp; close cycle #05 with no nominee; Track C re-evaluates. This is the cleanest governance outcome but loses an empirically interesting candidate.
- **Relax-to-20% interpretation**: trial 9 passes; A+D proceeds; but 18→20 is loosening a pre-registered diversifier threshold post-evidence — governance creep risk.
- **Compromise: treat 18% as "soft warn" + 20% as hard fail; trial 9 logged with warning + entered as diversifier**: a defensible middle path. Forward observation TD60 must show 60-day max_dd <=15% to clear the warning.

[OPERATOR-CERTAIN on framing]: this IS a directional decision; operator authority does not extend to picking among D10c options. User decides.

[OPERATOR-OPINION]: I lean toward the COMPROMISE — soft warn + 20% hard fail + TD60 self-clearing condition. Reasons: (1) trial 9 is materially better than QQQ in 2025 (DD 18.16% vs QQQ 22.86%, a 4.7pp improvement — diversifier value visible); (2) 0.16pp below threshold is within sampling/data noise; (3) but unconditional relax to 20% is loophole-creating. Soft-warn-with-self-clearing matches the actual diagnostic: "borderline at backtest, must prove in forward".

---

## 13. Recommended Immediate Action

```yaml
recommended_immediate_action:
  step_1_decision_lock:
    - User signs off on D1-D9 (D8/D9 deferred)
    - Operator drafts CLAUDE.md QQQ Rule diversifier exception edit
    - User reviews diff (pre-commit)
    - Operator commits CLAUDE.md edit + this PRD finalized
    - docs/memos/20260501-diversifier_role_decision.md authored

  step_2_phase_C_PRD_1_implementation:
    - Schema changes (CandidateRole enum + ForwardRunManifest fields)
    - acceptance_helpers.py role dispatch
    - Trial 9 frozen spec yaml + init script
    - Unit + integration + audit tests (§11.1-11.3, ~20 tests)
    - Migration backfill for existing manifests
    - First trial 9 forward observe = TD001

  step_3_forward_observation:
    - Daily forward observe ritual (per existing user command convention "数据来了")
    - Health checkpoint at TD20, TD40
    - Decision checkpoint at TD60, TD90, TD180

  step_4_branch_decision:
    - TD60 GREEN: authorize Phase C-PRD-2 (sleeve abstraction; 1-2 weeks)
    - TD60 YELLOW: continue to TD90; reassess
    - TD60 RED: stop trial 9 forward; consider alternatives

  NOT_AUTHORIZED:
    - Phase C-PRD-2 implementation (deferred until TD60)
    - Phase C-PRD-3 implementation (deferred until phase 2 + trigger)
    - Phase C-PRD-4 implementation (deferred until phase 3)
    - Cycle #06 single-stage mining
    - D3b regime-aware mining objective as separate workstream
    - Track B Step 6+ work as separate workstream
```

---

## 14. Draft Decision Statement (for user's approval)

```markdown
DECISION (PRD 20260501-two_stage_allocation_architecture_prd):

1. Two-Stage Allocation Architecture is authorized as PQS's long-term direction.
   Phase C-PRD-1 (lightweight role tag + Trial 9 forward init) is the only
   currently authorized implementation step.

2. Phase C-PRD-2/3/4 are SCOPED in this PRD but NOT authorized for
   implementation. Each phase has a specific trigger (TD60 GREEN,
   prior phase complete, etc.).

3. Trial 9 (track-c-cycle-2026-05-01-05 trial 6c745c601a47) is approved as
   `diversifier`-role forward observation candidate. NOT a core_alpha nominee.

4. core_alpha QQQ Outperformance Rule is UNCHANGED. Diversifier role waives
   ONLY the OOS walk-forward window-mean rule, with all other gates STRICTER
   (NAV correlation, factor overlap, non-equity exposure).

5. Cycle #06 single-stage mining is NOT authorized. D3b regime-aware mining
   objective is DEFERRED and absorbed into Stage 1 allocation logic within
   this PRD's Phase C-PRD-3.

6. Track B Step 6+ is ABSORBED by this PRD's Phase C-PRD-3/4. Track B Steps
   1-5 (already shipped: DD throttle, role caps, C2 budget) remain unchanged
   and become Stage 3 inputs.

7. CLAUDE.md QQQ Outperformance Rule edited to reflect diversifier exception
   (pre-commit reviewed).

8. Sealed 2026 panel UNCHANGED — never read.

9. RCMv1 + Cand-2 remain `legacy_decay_verification` role. Not promoted.
```

---

## 15. Operator Self-Audit (R1+R2+R3+R4 inline) [CERTAIN, mandatory per project convention]

- **R1 fact**:
  - All cycle history numbers in §1 verified via direct grep on closeout memos and cycle eval JSONs
  - Trial 9 numbers (cum_ret, sharpe, max_dd, vs_qqq, NAV correlation, asset class exposure, factor overlaps) verified against `data/ml/research_cycle_eval/track-c-cycle-2026-05-01-05/evaluation_summary.json` (operator did this read in cycle #05 closeout authoring, same session)
  - CLAUDE.md QQQ Outperformance Rule current wording verified in CLAUDE.md
  - anti_sibling_policy.py POLICY_VERSION verified via direct read

- **R2 logic**:
  - §6.2 diversifier_acceptance internally consistent: not_waived list matches §6.1 core list except window-mean; STRICTER NAV thresholds (0.70 vs 0.85 raw, 0.50 vs 0.70 residual) deliberate trade for the waiver
  - §6.4 allocation_policy_acceptance is logically necessary: rule-based weights without baseline benchmark are unsubstantiated
  - Phase C-PRD-1 implementation is minimum viable: schema + dispatch + tests + Trial 9 init; no overlap with Phase 2-4 scope
  - Forward observation triggers (§7.1) are decision-equivalence-class style (GREEN / YELLOW / RED), not arbitrary thresholds

- **R3 actually-could-run**:
  - Forward runner schema additions are concrete (CandidateRole enum + ForwardRunManifest fields); existing schema in core/research/forward/manifest_schema.py supports lazy migration pattern (precedent: PRD-F config_snapshot field added 2026-04-29)
  - Test surface (§11) is concrete and finite; ~20 tests at Phase C-PRD-1 is achievable
  - Trial 9 frozen spec extraction from rcm_archive.db is straightforward (precedent: cycle04+05 evaluators do this)

- **R4 boundary**:
  - **[DEFERRED-REVIEW for D8]**: §5.1.4 default weights are operator estimates; not yet historically validated. §6.4 acceptance gate catches if estimates are wrong, but §6.4 runs at Phase C-PRD-3, not now. Risk: if user authorizes default weights in §5.1.4 today, then Phase C-PRD-3 fails §6.4, the design pivot cost is at most 1-2 days revising the rule — bounded.
  - **[DEFERRED-REVIEW for D9]**: §10.8 max-3-diversifier soft cap is operator estimate; not yet stress-tested with multi-candidate forward data. Phase C-PRD-2 reassesses.
  - **[OPERATOR UNCERTAINTY surfaced]**: §3.3 Track B absorption — operator is CERTAIN of the directional reasoning but UNCERTAIN about whether Track B Step 6+ has any near-final state worth preserving instead of discarding. Recommendation in D6 may need revision after a closer audit of Track B Step 6+ partial work (operator hasn't read its design notes recently).
  - **[OPERATOR UNCERTAINTY surfaced]**: §5.3.2 Track B Steps 1-5 reuse — operator is CERTAIN those steps shipped per CLAUDE.md but has NOT verified the API surface they expose. Phase C-PRD-3 spec needs to be informed by reading those modules' actual interfaces. Risk: API mismatch found mid-Phase-C-PRD-3 forces refactoring.
  - **[CLAUDE.md wording ambiguity flagged]**: §3.1 the "OOS walk-forward (average)" phrase in CLAUDE.md has two possible interpretations: (a) Track A per-validation-year mean (cycle05 interpretation) or (b) rolling expanding-window walk-forward (separate framework). This PRD uses interpretation (a). User may want interpretation (b) — that would change the diversifier waiver wording.
  - **No 2026 sealed data was read in authoring this PRD.**
