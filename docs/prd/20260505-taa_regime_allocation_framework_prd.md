# PRD: TAA / Regime Allocation Framework

**Lineage tag**: `taa-regime-allocation-2026-05-05`  
**Authored**: 2026-05-05  
**Revision**: v1.1 — 2026-05-05 (post-critique; 7 issues addressed per
`docs/memos/20260505-prd_ac_e_critique_log.md`)  
**Status**: DRAFT — awaiting user signoff before implementation  
**Authority**: User explicit-go 2026-05-05 ("ACE 都做"); cycle #04 close memo
strategic pivot path §"Change strategy type"; this is independent of
cycle path (cycle #06 stop rule is about factor mining, TAA is separate
framework).

**Scope clarification** (per critique I11): This PRD = **PRD-E1
(research framework)**. Forward observation runner integration is
**PRD-E2 (separate, gated on PRD-E1 success)**. PRD-E1 deliverable =
TAA candidate eligible for forward freeze; PRD-E1 does NOT itself ship
forward integration code.

---

## 1. Background

### 1.1 Why TAA as separate strategy type

Existing PQS framework is **factor mining** based:
- IC_IR optimization on cross-sectional composite of factor scores
- Long-only top-N stock selection
- Monthly / weekly rebalance
- Universe = 53 stocks + 6 cross-asset ETFs

TAA / regime allocation is structurally different:
- **Regime detection** (BULL / RISK_ON / NEUTRAL / CAUTIOUS / RISK_OFF / CRISIS)
- **Asset class allocation** (e.g. CRISIS → 80% bonds + 20% cash; BULL → 70%
  equities + 20% bonds + 10% commodities) — NOT individual stock selection
- **Top-down** instead of bottom-up
- Driven by macro signals (vol, drawdown, trend) not factor IC

### 1.2 Why now

- Factor mining (cycle #02-#05) repeatedly produces sibling space (universe-bound + IC_IR objective)
- cycle #04 close pre-committed: "no cycle #06 without strategic pivot,
  options include 'Change strategy type (regime allocation / TAA)'"
- TAA fundamentally avoids universe-bound floor: regime-driven asset class
  allocation is not constrained by 53-stock universe sibling structure
- 5.4+ OOS-only discipline: TAA backtest train-only fully compatible

### 1.3 Why TAA may break sibling

- RCMv1+Cand-2 are stock factor composites → high SPY beta inevitable
- TAA in CRISIS regime → 80% bonds → SPY beta ~0 (inverse if rates fall)
- TAA in BULL regime → 70% equities → SPY beta ~0.7
- → **Regime-conditional beta** instead of always-on beta
- This is structurally diverse from any factor-mined long-only top-N spec,
  not a tweak of same framework

---

## 2. Goal

Ship a **TAA / regime allocation backtest framework** as new strategy
type, gated under `strategy_type=tactical_asset_allocation` flag.
First deliverable: regime-driven asset class allocator with backtest
on train-only panel, evidence-based PRD-E candidate (or rejection).

---

## 3. Non-goals

- 不改 factor mining infra (research_miner / composite_evaluator stay for
  PRD-AC track)
- 不 ship 给 forward observation runner (forward observation 路径需 PRD-E
  shipped → 然后单独 wire forward runner; out of this PRD scope)
- 不 unify with PRD-AC mining objective (TAA 是 separate 框架, 不进 IC_IR
  search space)
- 不破坏 invariant (long-only / no-margin / no-short hold; bond ETFs OK)
- 不 read sealed (2026)

---

## 4. Design

### 4.1 Reusable infrastructure (verified in R3-E-1/2) — REVISED I14

| Component | Path | Reuse rate |
|---|---|---|
| Regime classifier | `core/regime/regime_detector.py::RegimeDetector` (BULL/RISK_ON/NEUTRAL/CAUTIOUS/RISK_OFF/CRISIS) | **High (with thin wrapper, ~30 lines)** |
| Manual regime labels | `core/research/regime_classifier.py` (M9 disagreement policy) | 100% (matches `manual_regime_labels` heuristic in trial9_historical_walkforward_prior.py) |
| Asset class mapping | `core/research/risk_cluster_map.py::ASSET_CLASS_BY_CLUSTER` (equities/bonds/commodities/cash_anchor) | 100% |
| Cap-aware allocator (cluster-level) | `core/research/harness/composite_evaluator.py::cap_aware_cross_asset` | 70% (mechanism reusable, regime-driven path 需重写) |
| BarStore SPY/QQQ + bond ETFs | `core/data/bar_store.py` (TLT/IEF/SHY/GLD/BIL/SHV in cycle #04 universe) | 100% |
| BacktestEngine T+1 open + cost model | `core/backtest/backtest_engine.py` | 100% |
| Train-only filter | `core/research/temporal_split.py::partition_for_role` | 100% |

**I14 fix**: `RegimeDetector.classify_series` schema (output type, index
alignment) NOT hands-on verified at PRD draft time. Phase 1 includes
explicit verification task + thin wrapper module if schema needs
alignment with `manual_regime_labels` series output.

### 4.2 New components (verified ~400 lines new code)

| Component | Path | Approx lines |
|---|---|---|
| Regime → asset class rules | `core/research/taa/regime_rules.py` | ~150 |
| TAA backtest harness | `core/research/taa/taa_harness.py` | ~200 |
| TAA acceptance evaluator | `core/research/taa/taa_acceptance.py` | ~80 |
| Tests | `tests/unit/research/taa/test_*.py` | ~150 |

### 4.3 Regime → asset class rules (data + policy)

**Rule format** (`core/research/taa/regime_rules.py`):
```python
@dataclass(frozen=True)
class RegimeAllocation:
    regime: RegimeState
    equities_pct: float
    bonds_pct: float
    commodities_pct: float
    cash_anchor_pct: float
    
    def __post_init__(self):
        total = (self.equities_pct + self.bonds_pct +
                 self.commodities_pct + self.cash_anchor_pct)
        assert abs(total - 1.0) < 1e-6, f"Allocation must sum to 1.0, got {total}"

# Default v1 rule set
# Sources: 60/40 portfolio (Vanguard / Modern Portfolio Theory),
# Permanent Portfolio (Harry Browne — 25/25/25/25 stocks/bonds/gold/cash),
# David Swensen "Unconventional Success" (30% equities / 30% bonds /
# 20% real estate / 20% TIPS for individual investor; adapted to
# our 4-class equities/bonds/commodities/cash_anchor framework).
# v1 numbers are informed averaging of these 3 conventions, NOT mined.
DEFAULT_TAA_RULES_V1 = {
    RegimeState.BULL:     RegimeAllocation(BULL,     0.70, 0.20, 0.05, 0.05),
    RegimeState.RISK_ON:  RegimeAllocation(RISK_ON,  0.60, 0.30, 0.05, 0.05),
    RegimeState.NEUTRAL:  RegimeAllocation(NEUTRAL,  0.40, 0.40, 0.10, 0.10),
    RegimeState.CAUTIOUS: RegimeAllocation(CAUTIOUS, 0.30, 0.50, 0.10, 0.10),
    RegimeState.RISK_OFF: RegimeAllocation(RISK_OFF, 0.20, 0.55, 0.05, 0.20),
    RegimeState.CRISIS:   RegimeAllocation(CRISIS,   0.05, 0.65, 0.00, 0.30),
}

# I13 fix: Minimum viable variant (sanity baseline) — only 2 regime states,
# fewer DOF, easier to interpret if v1 over-engineered.
DEFAULT_TAA_RULES_V0_MINIMAL = {
    RegimeState.BULL:     RegimeAllocation(BULL,     0.60, 0.40, 0.00, 0.00),  # 60/40
    RegimeState.RISK_ON:  RegimeAllocation(RISK_ON,  0.60, 0.40, 0.00, 0.00),
    RegimeState.NEUTRAL:  RegimeAllocation(NEUTRAL,  0.50, 0.50, 0.00, 0.00),
    RegimeState.CAUTIOUS: RegimeAllocation(CAUTIOUS, 0.30, 0.70, 0.00, 0.00),
    RegimeState.RISK_OFF: RegimeAllocation(RISK_OFF, 0.30, 0.70, 0.00, 0.00),
    RegimeState.CRISIS:   RegimeAllocation(CRISIS,   0.30, 0.70, 0.00, 0.00),
}
```

Within asset class: equal-weight across symbols in that class (per
`ASSET_CLASS_BY_CLUSTER` mapping).

**Versioned rule sets**: `v1` is default; future tuning bumps to `v2` etc.

**Phase 2 sanity**: Run TAA backtest on BOTH `DEFAULT_TAA_RULES_V1` AND
`DEFAULT_TAA_RULES_V0_MINIMAL` to verify v1's added complexity (24
free numbers vs 12) actually improves performance. If v0_minimal NAV
≥ v1 NAV (simpler beats complex), accept v0_minimal as default and
deprecate v1 (Occam's razor; simpler rule set is preferable when
performance equivalent).

### 4.4 TAA backtest harness — REVISED I16

**Regime detection cadence design choice (I16 fix)**: regime label
computed **monthly** (at month-start, T-day-only — looks back, not
forward). Rationale:
- Daily cadence = mid-month regime change immediate response, but high
  turnover on transition days (TAA portfolio rebalance every regime
  change, not every month-start)
- Monthly cadence = align with rebalance cycle, low turnover, but
  mid-month regime change DELAYED to next month-start
- Monthly cadence chosen as primary (operational simplicity + low cost);
  daily cadence variant 留作 Phase 2 sensitivity check (per §7 risks)

```python
def run_taa_backtest(
    panel,                              # OHLCV panel from existing data layer
    regime_labels: pd.Series,           # date → RegimeState (monthly cadence)
    rule_set: dict,                     # {RegimeState: RegimeAllocation}
    rebalance_cadence: str = "monthly",
    cost_model=None,
    initial_capital: float = 10000.0,
) -> TaaBacktestResult:
    """
    Sequence:
      1. for each rebalance date (month-start):
         a. read regime label at that date (monthly classifier)
         b. lookup target allocation per asset class from rule_set
         c. equal-weight within asset class (using ASSET_CLASS_BY_CLUSTER)
         d. produce target_wts for that date
      2. fold target_wts time series → BacktestEngine T+1 open exec
      3. compute NAV + per-regime NAV slice + per-year metrics +
         per-cadence-variant comparison
    """
```

Reuses BacktestEngine; only adds regime-conditional target_wts construction.

### 4.5 TAA acceptance criteria (PRD-E specific) — REVISED I10 + I15

Different from factor mining acceptance (no IC_IR check; no cross-sectional
rank correlation). **Risk-adjusted hard gates** (per critique I10 BLOCKER:
TAA in long BULL years (2019/2021/2023) almost always underperforms SPY
in raw return; using "vs SPY positive ≥ 3/5" as hard gate is structurally
~90% likely to fail — wrong metric for the strategy class):

| Criterion | Threshold | Rationale |
|---|---|---|
| **Calmar ≥ buy-hold SPY Calmar** (CAGR / \|MaxDD\|) | hard | I15 fix: primary risk-adjusted metric; TAA's diversifier value is DD control, Calmar directly captures it |
| MaxDD < SPY MaxDD across full period | hard | Must improve DD over passive (TAA's whole point) |
| MaxDD ≤ 18% | hard | Diversifier role threshold (CLAUDE.md per-validation-year MaxDD ≤ 20% with -2pp buffer) |
| Stress slice MaxDD ≤ 25% (covid_flash + rate_hike_2022) | hard | CLAUDE.md crisis resilience gate |
| **Regime-conditional MaxDD** in CRISIS regime ≤ 10% | hard | Regime detection 价值: 在 CRISIS 期间 DD 应小 |
| Beta to SPY in BULL ≤ 0.85 | hard | Should NOT mimic SPY (otherwise just leveraged passive) |
| Per-validation-year vs SPY positive ≥ 2/5 in BEAR/RISK_OFF regime years (2018, 2022 stress) | hard | I10 fix: regime-conditional outperform (TAA expected to outperform in non-bull); BULL years skipped from this gate |
| **Sharpe ≥ buy-hold SPY Sharpe** | secondary informational | I15 fix: secondary metric — Sharpe rewards low vol but TAA's value is DD-controlled compounding (Calmar more aligned) |
| Regime classifier agreement: manual vs auto KL divergence < 0.5 OR Hamming distance < 30% across full period | soft warn | I12 fix: distributional similarity + label-day disagreement (instead of arbitrary "≥60% agreement"); high disagreement triggers user-go review, not Phase 2 abort |

### 4.6 5.4 OOS discipline

- Regime labels computed train-only (panel filtered via partition_for_role(role="miner"))
- Asset class symbol prices loaded train-only
- BacktestEngine on train-only (2009-2017 + 2020/2022/2024)
- Validation acceptance separately: load validation years (selector role)
  + replay → check 5 hard criteria
- Sealed 2026: 0 read

### 4.7 NOT in this PRD (future extensions)

- Forward observation runner integration (separate PRD when TAA candidate
  freezes for paper deployment)
- TAA + factor sleeve combination (Phase C-PRD-3 territory)
- Auto rule tuning via mining (treats rule weights as hyperparameters; large
  effort, defer)

---

## 5. Acceptance criteria

### 5.1 Regression / backward compat

- 不 break 现有 mining infrastructure (cycle #04/#05 archive 仍 readable)
- 不破坏 invariant (long-only across asset classes; no margin; no short)

### 5.2 New deliverables — REVISED I10 + I12 + I13 + I15

**Phase 1 (regime label sanity)** — I12 fix:
- Manual regime labels on SPY 2009-2024-12-31 → 6 regime distribution
  reasonable (BULL ≥ 30%; CRISIS ≤ 5%)
- **I12 fix**: Auto regime classifier (RegimeDetector) vs manual:
  - KL divergence of regime label distributions < 0.5, OR
  - Hamming distance (day-by-day disagreement rate) < 30%
  - High disagreement (failing both metrics) does NOT abort Phase 2;
    triggers user-go review per M9 disagreement policy

**Phase 2 (TAA backtest, train-only)** — I13 + I15 fix:
- **I13 fix**: Run BOTH `DEFAULT_TAA_RULES_V1` (24 free numbers) AND
  `DEFAULT_TAA_RULES_V0_MINIMAL` (12 free numbers; sanity baseline).
  If v0_minimal NAV ≥ v1 NAV (Occam's razor), accept v0_minimal as
  default; document v1 deprecation in closeout memo
- Full-period train-only TAA backtest deliverables:
  - **I15 fix**: Calmar ≥ buy-hold SPY Calmar (primary metric)
  - MaxDD ≤ 18%
  - Per-regime-conditional NAV slice: CRISIS regime DD ≤ 10%
  - Sharpe ≥ buy-hold SPY Sharpe (informational, secondary)
- Sensitivity check: daily-cadence regime detector variant (I16); compare
  NAV vs monthly-cadence default; if material difference, document trade-
  off; default monthly retained

**Phase 3 (validation acceptance, selector role)** — I10 + I17 fix:
- Validation years (2018/2019/2021/2023/2025) replay via partition_for_role(role="selector")
- **I17 BLOCKER fix**: validation set regime composition (per `config/temporal_split.yaml`):
  - 2018: rate_hike_bear (BEAR)
  - 2019: normal_bull (BULL)
  - 2021: liquidity_mania (BULL)
  - 2023: ai_narrow (BULL)
  - 2025: current_market (mixed/BULL trend at freeze)
  → validation set has only 1 explicit BEAR/RISK_OFF year (2018) and 0
  CRISIS years; "≥ 2/5 in BEAR/RISK_OFF" 数学不 well-defined.

  **Replacement gates** (BEAR/RISK_OFF coverage extended via stress slices):
  - **2018 vs SPY positive (HARD)** — single BEAR validation year; TAA's
    primary value is in this regime, must outperform
  - 2025 vs SPY positive (HARD per CLAUDE.md core role gate)
  - covid_flash + rate_hike_2022 stress slice MaxDD ≤ 25% (HARD per
    CLAUDE.md 2008-style scenario gate); both stress slices are BEAR/
    RISK_OFF analogues borrowed from train years
  - Per-validation-year MaxDD ≤ 20% (HARD; CLAUDE.md core role gate)
  - **No** raw "vs SPY positive ≥ N/5 across BULL years" gate (TAA
    structurally underperforms SPY in BULL; this is acknowledged in §7)

- Beta to SPY in BULL ≤ 0.85 (HARD)
- **Risk-adjusted gates**: Calmar ≥ SPY Calmar; MaxDD < SPY MaxDD (HARD)
- **Eligibility verdict** (not freeze):
  - All hard gates pass → candidate **ELIGIBLE for forward observation
    freeze** (eligibility ≠ frozen; see I11 fix in §3 + §10 + below)
  - Fail → close PRD-E with closeout memo; not viable; pivot to PRD-AC
    (or other strategic pivot)

**I11 fix — eligibility vs freeze**:
- PRD-E1 (this PRD) deliverable = "candidate ELIGIBLE for forward
  observation freeze" upon Phase 3 pass
- Actual freeze (forward observation runner integration) = **PRD-E2**,
  separate scope, gated on PRD-E1 success + user explicit-go for E2 PRD
- Phase 3 closeout memo = nominee evidence for PRD-E2 trigger; does NOT
  itself wire forward runner

---

## 6. Implementation plan

### Phase 1: Regime + asset class rules + tests (1 周)

1. `regime_rules.py` data class + DEFAULT_TAA_RULES_V1 + DEFAULT_TAA_RULES_V0_MINIMAL + tests
2. **I14 verification task**: hands-on verify `RegimeDetector.classify_series`
   schema (output type, index alignment, label values vs `manual_regime_labels`).
   Write thin wrapper module (~30 lines) if schema needs alignment
3. Regime label generator (manual + auto, monthly cadence per I16) + tests
4. KL divergence + Hamming distance helper for Phase 1 acceptance §5.2
5. ASSET_CLASS_BY_CLUSTER → equal-weight target_wts builder + tests

### Phase 2: TAA harness + train-only backtest (1 周)

1. `taa_harness.py::run_taa_backtest` + integration with BacktestEngine
2. Train-only smoke run on 2009-2017 + 2020/2022/2024
3. Per-regime NAV slice analysis + plot (regime → NAV trajectory)
4. Compare TAA NAV vs buy-hold SPY NAV (CAGR / Sharpe / MaxDD)

### Phase 3: Validation acceptance + memo (1 周)

1. `taa_acceptance.py` 5 hard criteria evaluator
2. Run on validation years (2018/2019/2021/2023/2025)
3. Pass/fail verdict
4. Closeout memo: pass → forward observation freeze candidate; fail →
   close PRD-E

**Total: 3 周 (R3 verified estimate)**

---

## 7. Risks + mitigations — REVISED I10 + I16

| Risk | Mitigation |
|---|---|
| Default rule set v1 over-fit to known regimes (esp. 2008/2020) | Phase 2 backtest验证 with V0_MINIMAL fallback (I13); add v2/v3 rule sets; sensitivity analysis |
| Regime classifier 标错 (e.g. 2020 covid 没及时 detect) | M9 manual + auto disagreement check (I12 KL + Hamming); 不可调和则 user-go review (Phase 2 不 abort) |
| **I10 fix**: TAA 在长期 BULL (2010-2020) underperform SPY in raw return | TAA 不 claim raw return outperform SPY in BULL; acceptance §5.2 改用 risk-adjusted (Calmar / MaxDD); regime-conditional vs SPY only in BEAR/RISK_OFF years |
| Bond + commodity ETF 历史短 (TLT 2002+, GLD 2004+) | Limit panel start to max(panel_start, ETF_min_inception); train_years 2009+ all 6 ETFs available (verified cycle04 universe) |
| Regime label 用 lookahead bias (e.g. 252d max 看未来) | Strict T-day-only computation; no future window in regime label; Phase 1 explicit verification: regime_labels[t] uses ONLY data through t |
| Cash anchor 30% in CRISIS 太保守 | Phase 2 sensitivity sweep on cash_anchor_pct in {0.20, 0.30, 0.40} |
| **I16 NEW: Mid-month regime change 不立即响应 (monthly cadence)** | Phase 2 sensitivity check: run TAA with daily-cadence regime detector variant; compare NAV; if material difference (Calmar > 5% Δ), document trade-off; default monthly retained for low turnover; daily variant 留作 Phase 3 follow-up |
| Regime change 触发 mid-month rebalance → high turnover when regime flips frequently | Monthly cadence (default) bounds turnover to month-start only; cost_model captures realistic transaction cost |

---

## 8. Out of scope (gated on Phase 3 success) — REVISED I11

- **PRD-E2: Forward observation runner integration** (separate PRD,
  gated on PRD-E1 success + user explicit-go) — wires TAA candidate
  output schema to forward runner manifest, attention check report,
  recovery CLI. Eligibility ≠ frozen; Phase 3 closeout = nominee
  evidence triggering PRD-E2
- TAA + factor sleeve combination (Phase C-PRD-3 territory)
- Auto rule weight tuning via mining (treats rule weights as
  hyperparameters; large effort, defer)
- Multi-period dynamic rules (e.g. rebalance freq decisions)

---

## 9. OOS discipline

- All Phase 1-3 work train-only via `partition_for_role(role="miner")` for
  rule design; `partition_for_role(role="selector")` for validation
  acceptance
- Sealed 2026: 0 read
- 5.4+ data: 0 consumption

---

## 10. Reversibility

If TAA proves harmful or non-viable:
- Phase 1 modules `core/research/taa/` 可整体删除
- 不影响 factor mining (PRD-AC) 路径
- 不影响 forward observation (trial9 manifest 不动)
- Asset class mapping (`ASSET_CLASS_BY_CLUSTER`) 仍保留, 用于 cycle04 cap_aware_cross_asset
- 关闭 PRD-E with rejection memo + lesson learned
