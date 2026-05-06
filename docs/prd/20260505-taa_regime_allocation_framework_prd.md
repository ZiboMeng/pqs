# PRD: TAA / Regime Allocation Framework

**Lineage tag**: `taa-regime-allocation-2026-05-05`  
**Authored**: 2026-05-05  
**Status**: DRAFT — awaiting user signoff before implementation  
**Authority**: User explicit-go 2026-05-05 ("ACE 都做"); cycle #04 close memo
strategic pivot path §"Change strategy type"; this is independent of
cycle path (cycle #06 stop rule is about factor mining, TAA is separate
framework).

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

### 4.1 Reusable infrastructure (verified in R3-E-1/2)

| Component | Path | Reuse rate |
|---|---|---|
| Regime classifier | `core/regime/regime_detector.py::RegimeDetector` (BULL/RISK_ON/NEUTRAL/CAUTIOUS/RISK_OFF/CRISIS) | 100% |
| Manual regime labels | `core/research/regime_classifier.py` (M9 disagreement policy) | 100% |
| Asset class mapping | `core/research/risk_cluster_map.py::ASSET_CLASS_BY_CLUSTER` (equities/bonds/commodities/cash_anchor) | 100% |
| Cap-aware allocator (cluster-level) | `core/research/harness/composite_evaluator.py::cap_aware_cross_asset` | 70% (mechanism reusable, regime-driven path 需重写) |
| BarStore SPY/QQQ + bond ETFs | `core/data/bar_store.py` (TLT/IEF/SHY/GLD/BIL/SHV in cycle #04 universe) | 100% |
| BacktestEngine T+1 open + cost model | `core/backtest/backtest_engine.py` | 100% |
| Train-only filter | `core/research/temporal_split.py::partition_for_role` | 100% |

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

# Default v1 rule set (informed by 60/40 + Permanent Portfolio + David Swensen)
DEFAULT_TAA_RULES_V1 = {
    RegimeState.BULL:     RegimeAllocation(BULL,     0.70, 0.20, 0.05, 0.05),
    RegimeState.RISK_ON:  RegimeAllocation(RISK_ON,  0.60, 0.30, 0.05, 0.05),
    RegimeState.NEUTRAL:  RegimeAllocation(NEUTRAL,  0.40, 0.40, 0.10, 0.10),
    RegimeState.CAUTIOUS: RegimeAllocation(CAUTIOUS, 0.30, 0.50, 0.10, 0.10),
    RegimeState.RISK_OFF: RegimeAllocation(RISK_OFF, 0.20, 0.55, 0.05, 0.20),
    RegimeState.CRISIS:   RegimeAllocation(CRISIS,   0.05, 0.65, 0.00, 0.30),
}
```

Within asset class: equal-weight across symbols in that class (per
`ASSET_CLASS_BY_CLUSTER` mapping).

**Versioned rule sets**: `v1` is default; future tuning bumps to `v2` etc.

### 4.4 TAA backtest harness

```python
def run_taa_backtest(
    panel,                              # OHLCV panel from existing data layer
    regime_labels: pd.Series,           # date → RegimeState  
    rule_set: dict,                     # {RegimeState: RegimeAllocation}
    rebalance_cadence: str = "monthly",
    cost_model=None,
    initial_capital: float = 10000.0,
) -> TaaBacktestResult:
    """
    Sequence:
      1. for each rebalance date:
         a. read regime label at that date
         b. lookup target allocation per asset class
         c. equal-weight within asset class (using ASSET_CLASS_BY_CLUSTER)
         d. produce target_wts for that date
      2. fold target_wts time series → BacktestEngine T+1 open exec
      3. compute NAV + per-regime NAV slice + per-year metrics
    """
```

Reuses BacktestEngine; only adds regime-conditional target_wts construction.

### 4.5 TAA acceptance criteria (PRD-E specific)

Different from factor mining acceptance (no IC_IR check; no cross-sectional
rank correlation). New criteria:

| Criterion | Threshold | Rationale |
|---|---|---|
| Full-period CAGR > buy-hold SPY | strict | Must add value over passive |
| MaxDD ≤ 18% | hard | Diversifier role threshold |
| Stress slice MaxDD ≤ 25% (covid_flash + rate_hike_2022) | hard | Crisis resilience |
| Beta to SPY in BULL ≤ 0.85 | hard | Should NOT mimic SPY |
| **Regime-conditional MaxDD** in CRISIS regime ≤ 10% | hard | Regime detection 价值: 在 CRISIS 期间 DD 应小 |
| Per-validation-year vs SPY positive in ≥3/5 years | hard | Tracks SPY at minimum |
| Regime classifier agreement: manual vs auto disagreement < 30 days/year | soft warn | Per M9 |

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

### 5.2 New deliverables

**Phase 1 (regime label sanity)**:
- Manual regime labels on SPY 2009-2024-12-31 → 6 regime distribution合理
  (BULL ≥ 30%; CRISIS ≤ 5%)
- Auto regime classifier (RegimeDetector) on same panel → agreement ≥ 60%
  with manual

**Phase 2 (TAA backtest)**:
- Full-period train-only TAA backtest CAGR ≥ buy-hold SPY CAGR
- MaxDD ≤ 18%
- Per-regime-conditional NAV slice: CRISIS regime DD ≤ 10%

**Phase 3 (validation acceptance)**:
- Validation years (2018/2019/2021/2023/2025) replay
- Per-year vs SPY positive ≥ 3/5
- 2025 vs SPY positive (HARD per CLAUDE.md core role gate)
- Beta to SPY in BULL ≤ 0.85

If 5.2 全 pass → TAA candidate eligible for forward observation freeze.
If fail → close PRD-E with closeout memo; not viable; pivot to PRD-AC
(or other strategic pivot).

---

## 6. Implementation plan

### Phase 1: Regime + asset class rules + tests (1 周)

1. `regime_rules.py` data class + DEFAULT_TAA_RULES_V1 + tests
2. Regime label generator (reuse manual_regime_labels + RegimeDetector)
3. ASSET_CLASS_BY_CLUSTER → equal-weight target_wts builder + tests

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

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Default rule set v1 over-fit to known regimes (esp. 2008/2020) | Phase 2 backtest验证; 加 v2/v3 rule set 备选; sensitivity analysis |
| Regime classifier 标错 (e.g. 2020 covid 没及时 detect) | M9 manual + auto disagreement check; 不可调和则 user-go |
| TAA 在长期 BULL (e.g. 2010-2020) underperform SPY | 这是 TAA 经典局限; CAGR ≥ SPY 是 hard gate, 如 fail 则 PRD-E rejected |
| Bond + commodity ETF 历史短 (TLT 2002+, GLD 2004+) | Limit panel start to max(panel_start, ETF_min_inception) |
| Regime label 用 lookahead bias (e.g. 252d max 看未来) | Strict T-day-only computation; no future window in regime label |
| Cash anchor 30% in CRISIS 太保守 | Phase 2 sensitivity sweep on cash_anchor_pct |

---

## 8. Out of scope (gated on Phase 3 success)

- Forward observation runner integration
- TAA + factor sleeve combination
- Auto rule weight tuning via mining
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
