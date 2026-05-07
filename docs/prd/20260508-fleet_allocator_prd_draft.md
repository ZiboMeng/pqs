# PRD: Fleet Allocator (Phase C-PRD-3 / Master PRD §4.4 Phase D.1)

**Lineage tag**: `cycle07-to-fleet-master-2026-05-06` (this PRD is Phase D.1 deliverable; child of master PRD)
**Authored**: 2026-05-08
**Status**: DRAFT — D.1 PRD writing only; D.2-D.4 implementation HARD GATED on master PRD §4.4 D.0 prerequisites
**Authority**: Master PRD `docs/prd/20260506-cycle07_to_fleet_master_prd.md` v1.1 §4.4 Phase D.1
**Predecessor PRDs**:
- Master PRD (parent)
- `docs/prd/20260501-two_stage_allocation_architecture_prd.md` (Phase C-PRD-1 trial9 diversifier)
- `docs/prd/20260428-candidate_fleet_allocator_prd.md` v1.1 (Track B Step 1-5 shipped; Step 6+ paused)
- `docs/prd/20260505-taa_regime_allocation_framework_prd.md` (PRD-E TAA defensive sleeve preserved)

## 0. Hard gate prerequisite (D.0 status as of 2026-05-08)

Per master PRD §4.4 D.0, fleet allocator IMPLEMENTATION (D.2-D.4)
requires BOTH:

(a) **≥1 nominee passing Track A acceptance** from R2 (cycle07a) OR R8
   (cycle08).
- R2 (cycle07a): **0 nominee** per `docs/memos/20260507-cycle07a_closeout.md`
- R8 (cycle08): **PENDING** per cycle08 mining state at PRD authoring
  (40-trial smoke run in progress; 200-trial full cycle deferred)
- **Status: gate (a) NOT MET as of 2026-05-08.**

(b) **Trial9 forward TD60 GREEN verdict** per CLAUDE.md ~2026-07-30:
- Trial9 forward observation: TD003 / +8.02% as of 2026-05-06 per CLAUDE.md
- TD60 milestone: ~2026-07-30 calendar (60 trading days from
  2026-05-04 freeze)
- **Status: gate (b) NOT MET as of 2026-05-08 (TD003 only; ~57 TD remaining
  to TD60).**

**Disposition**: Both gates NOT MET → D.2-D.4 (implementation) STAYS
PAUSED. This PRD ships D.1 PRD writing only per master PRD §4.4 D.0
exception ("If neither (a) nor (b) holds at week 5, Phase D.1 PRD writing
STILL can start"). This PRD is **architectural reference for when D.0
prerequisites are satisfied**; not a directive to deploy code now.

## 1. Background

Master PRD §1.2 sibling problem (cycle04/05/06/07a + Trial9 + TAA all
hit the same 2023 BULL year vs_qqq pattern) → fleet of 1 candidate
(Trial9) cannot bypass CLAUDE.md "Track B Step 6+ HARD PAUSED until ≥2
candidates exist that BOTH pass Track A acceptance AND have realized-NAV
pair correlation < 0.85".

Master PRD §2 G4 deployable strategy = fleet allocator combining 1+
stock-alpha sleeve + 1 defensive sleeve (TAA V1) + 1+ existing forward
candidate (Trial9). Needs at least 2 candidates that pass Track A.

## 2. Scope

This PRD scopes the fleet allocator design + tests + acceptance gate
without implementing it. Implementation kicks off when D.0 gate (a) +
(b) both true.

## 3. Goals

- G1: Fleet allocator combines N sleeves with regime-conditional weights
- G2: Smooth regime transitions (no hard switches at boundary)
- G3: Each sleeve's contribution to fleet NAV is auditable
- G4: Fleet passes Track A acceptance on selector panel; survives 2026
  sealed single-shot

## 4. Non-goals

- Real-time broker integration (separate PRD-E2 territory)
- Auto-promotion of fleet to production (manual user explicit-go required)
- Modifying CLAUDE.md invariants (long-only / no-margin / no-short)
- Building >3-sleeve fleets in v1 (cap at 3 sleeves: alpha + defensive +
  forward observation)

## 5. Architecture

### 5.1 Sleeve definition

```python
@dataclass(frozen=True)
class Sleeve:
    """A single sleeve in the fleet allocator."""
    sleeve_id: str
    candidate_id: str  # references frozen_spec or candidate_registry entry
    spec: FrozenStrategySpec  # full strategy spec per Phase C-PRD-1
    role: SleeveRole  # ALPHA / DEFENSIVE / FORWARD_OBSERVATION

    def regime_weight(self, regime_state: str) -> float:
        """Per-regime allocation weight ∈ [0, 1]."""
        ...

class SleeveRole(StrEnum):
    ALPHA = "alpha"           # cycle07a/cycle08-style stock alpha
    DEFENSIVE = "defensive"   # PRD-E TAA V1
    FORWARD_OBSERVATION = "forward_observation"  # Trial9, etc.
```

### 5.2 FleetAllocator class

```python
class FleetAllocator:
    """Master PRD §2 G4 fleet allocator.

    Combines N sleeves with regime-conditional weights to produce daily
    fleet NAV. Each sleeve's underlying strategy runs independently
    (existing harness / TAA infra reused). Allocator computes:
      - Daily fleet weight per sleeve = sleeve.regime_weight(regime_t)
      - Smoothing: EMA(20) on raw weights to avoid hard switches
      - Daily fleet return = sum_sleeve fleet_weight[t, sleeve] *
                              sleeve_daily_return[t, sleeve]
      - Daily fleet NAV = cumprod(1 + fleet_return)
    """
    sleeves: list[Sleeve]
    regime_smoothing_window: int = 20  # EMA window for weight transitions
    regime_label_source: pd.Series  # daily_regime_labels per TAA gen

    def run_fleet_backtest(
        self,
        panel: dict[str, pd.DataFrame],  # OHLCV
        regime_labels: pd.Series,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> FleetEvalResult:
        """Run each sleeve's harness + combine NAVs."""
        sleeve_navs = {}
        for sleeve in self.sleeves:
            sleeve_result = self._run_sleeve(sleeve, panel, start, end)
            sleeve_navs[sleeve.sleeve_id] = sleeve_result.nav

        # Per-day fleet weight per sleeve (regime-driven, smoothed)
        weight_panel = self._compute_weight_panel(regime_labels)

        # Daily fleet return
        sleeve_rets = pd.DataFrame({
            s_id: nav.pct_change().fillna(0.0)
            for s_id, nav in sleeve_navs.items()
        })
        fleet_ret = (weight_panel * sleeve_rets).sum(axis=1)
        fleet_nav = (1 + fleet_ret).cumprod()

        return FleetEvalResult(
            fleet_nav=fleet_nav,
            sleeve_navs=sleeve_navs,
            weight_panel=weight_panel,
            ...
        )
```

### 5.3 Default regime allocation (3-sleeve fleet)

Per master PRD §2 G4 example:

| Regime | Alpha sleeve | Defensive sleeve | Forward observation |
|---|---|---|---|
| BULL | 70% | 20% | 10% |
| RISK_ON | 70% | 20% | 10% |
| NEUTRAL | 40% | 40% | 20% |
| CAUTIOUS | 40% | 40% | 20% |
| RISK_OFF | 10% | 70% | 20% |
| CRISIS | 10% | 70% | 20% |

Each row sums to 100%. Tunable per fleet config.

### 5.4 Smoothing logic (EMA)

Hard regime-boundary switches cause whipsaw + cost inflation. EMA(20)
on raw weights smooths transitions:

```python
raw_weight_panel = pd.DataFrame(...)  # per-day raw weights per sleeve
smoothed = raw_weight_panel.ewm(span=20, adjust=False).mean()
# Renormalize to sum=1.0 per day
smoothed = smoothed.div(smoothed.sum(axis=1), axis=0)
```

### 5.5 Cost model

Sleeve transitions = inter-sleeve trades = transaction cost. Use
existing `core/execution/cost_model.py::CostModel` per-sleeve, plus
inter-sleeve hand-off cost ~ 1bp per turnover (configurable).

### 5.6 Forward runner integration

Future: `core/research/forward/runner.py` extension to track fleet
candidate status. Out of D.1 PRD scope; defer to PRD-E2 separate.

## 6. Acceptance criteria

### 6.1 Sleeve-level (each sleeve passes individually)

- Each sleeve's underlying strategy passes Track A acceptance
  individually OR is a FORWARD_OBSERVATION sleeve with explicit
  `candidate_role` tag (Trial9 case: diversifier role with
  soft_warn flags)
- Each sleeve has frozen_spec with sha256 immutability

### 6.2 Fleet-level (combined NAV)

- Fleet NAV passes Track A acceptance on selector panel:
  - Per-validation-year vs SPY ≥ 4/5 PASS
  - Per-validation-year MaxDD ≤ 20% (hard) / ≤ 18% (soft warn)
  - 2025 hard gate: vs_qqq excess > 0
  - Stress slice MaxDD ≤ 25% (covid_flash + rate_hike_2022)
  - Concentration top1 ≤ 40% / top3 ≤ 70%
  - Beta to QQQ ≤ 0.85 in BULL (informational; CLAUDE.md QQQ deprecation)
  - Cost robustness: 2x cost still produces positive aggregate excess

### 6.3 Pair-correlation acceptance

Per CLAUDE.md "Track B Step 6+ HARD PAUSED until ≥2 candidates exist
that BOTH pass Track A acceptance AND have realized-NAV pair correlation
< 0.85":

- Inter-sleeve realized-NAV pair correlation < 0.85 on selector panel

### 6.4 Sealed 2026 final

After selector-panel PASS, single-shot 2026 sealed evaluation. Standard
CLAUDE.md sealed_test_runner contract.

## 7. OOS discipline

- All sleeves' strategies use `partition_for_role(role="miner")` for
  mining + `partition_for_role(role="selector")` for fleet acceptance
- Fleet NAV evaluation uses selector panel (train + validation; sealed
  excluded) until sealed final
- Sealed 2026: NEVER read in fleet design / acceptance / debug

## 8. Reversibility

- Fleet allocator = pure new module `core/research/fleet/`
- Revocation = delete `core/research/fleet/` + remove fleet test files
- Sleeve specs (cycle07a archive / cycle08 nominees / TAA modules /
  Trial9 forward) NOT touched
- CLAUDE.md invariants NOT modified
- No production config / production_strategy.yaml writes

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| D.0 gate (a) NOT MET (cycle07a + cycle08 both 0 nominee) | This PRD writing only; D.2-D.4 STAYS PAUSED. Future ralph-loop with new mining cycle (e.g., universe expansion) can revisit |
| D.0 gate (b) NOT MET (Trial9 TD60 RED) | Forward observation continues to TD90. If TD90 GREEN, gate (b) satisfied. If RED, fleet definition changes (replace Trial9 sleeve with cycle08-or-later forward candidate) |
| Cost model under-estimates inter-sleeve transition cost | Sensitivity test: 2x / 3x cost robustness in fleet acceptance gate 6.2 |
| Regime smoothing introduces lookahead | EMA on past raw weights only; no future leakage |
| Sleeve-level alpha decay over time | Forward observation runner tracks per-sleeve TD60/TD90/TD120 health metrics; fleet allocator can drop unhealthy sleeves on user explicit-go |
| Pair correlation > 0.85 (siblings) | Acceptance §6.3 explicitly blocks; cycle04/05/06+cycle07a all sibling; need cycle08 G3 PASS or universe-expansion candidate |

## 10. Implementation plan (D.2-D.4; gated on D.0)

### D.2: Implementation (~1-2 weeks per master PRD §4.4 D.2 G-revised)

1. `core/research/fleet/sleeve.py` — Sleeve dataclass + SleeveRole enum
2. `core/research/fleet/allocator.py` — FleetAllocator class
3. `core/research/fleet/run_fleet_backtest.py` — entry point
4. `core/research/fleet/evaluate_fleet_acceptance.py` — Track A on fleet NAV

Reuses existing infra:
- `core/research/harness/composite_evaluator.py` for stock-alpha sleeves
- `core/research/taa/taa_harness.py` for defensive sleeve
- `core/backtest/backtest_engine.py` for execution
- `core/research/temporal_split_acceptance.py` for Track A on fleet NAV

### D.3: Tests (~3-5 days)

- 30+ unit tests covering Sleeve / FleetAllocator / fleet backtest /
  regime weighting / smoothing / acceptance
- Integration test: 2-sleeve fleet (TAA V1 + Trial9-replay) on real
  selector panel
- Regression: cycle04/05/06 + TAA + Trial9 archives unchanged

### D.4: Smoke + acceptance verdict (~half day + ~1 week if PRD-E2 kicks in)

- Smoke run on selector panel: full Track A acceptance verdict
- If PASS → forward observation runner integration scoped (PRD-E2)
- If FAIL → revisit sleeve selection / regime weights / closeout

## 11. Authorization markers

- User explicit-go 2026-05-06: master PRD ralph-loop authorized
- Master PRD §4.4 D.1: D.1 PRD writing can start at week 5 even if
  D.0 gates not met (this PRD honors that exception)
- D.2-D.4 implementation requires NEW user explicit-go after D.0 gates
  satisfied (NOT auto-deploy on gate satisfaction)

## 12. Calendar timeline (estimated; gated)

- This PRD shipped: 2026-05-08 (D.1 done)
- D.2 implementation: TBD (gated on D.0 (a) + (b))
- D.0 (a) earliest: when next mining cycle produces a nominee passing
  Track A. Cycle07a + cycle08 (smoke) both 0 nominee as of 2026-05-08;
  could be next cycle09+ or post-universe-expansion
- D.0 (b) earliest: ~2026-07-30 (Trial9 TD60 milestone)
- D.4 smoke earliest: ~2026-08-15 (assuming D.0 satisfies by 2026-07-30
  + D.2-D.3 ~2 weeks)

---

End of D.1 PRD draft. Next: D.2-D.4 implementation when D.0 gates met.
