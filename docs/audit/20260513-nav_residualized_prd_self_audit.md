# NAV-Residualized Mining PRD — B6 Self-Audit

**Date**: 2026-05-13
**PRD**: `docs/prd/20260513-nav_residualized_mining_prd.md`
**Method**: 4-tier (R1 fact / R2 logical / R3 actually-run / R4 boundary)

---

## §R1 — Fact check ✅ PASS

Verified via independent WebSearch:
- Blitz-Huij-Martens 2011 J. Empirical Finance 18(3):506-521 ✓
- 36m rolling FF3 regression ✓
- 12-month residual signal with skip-1m ✓
- "Risk-adjusted profit ≈ 2× standard momentum" ✓
- Universe 1926-2009 NYSE/AMEX/NASDAQ ✓
- Clarke-de Silva-Thorley 2002 FAJ 58(5):48-66, DOI 10.2469/faj.v58.n5.2468 ✓
- TC range 0.30-0.80 for long-only US equity ✓
- IR = TC × IC × √BR (algebra commutes) ✓

---

## §R2 — Logical chain

### Claim: residual-target mining produces different selections than raw-target mining

Logical chain:
1. Composite score `s[t] = Σ w_i × zscore(factor_i[t])`
2. TPE picks `w_i` to maximize IC against target
3. Raw-target IC: factors loading on SPY beta get high weight (raw fwd_ret loads on SPY beta)
4. Residual-target IC: factors loading on SPY beta get ZERO IC on residual (residual is orthogonal to fleet/SPY beta by construction)
5. Therefore TPE picks DIFFERENT weights → different selection → different NAV

**Verdict**: ✅ HOLDS. Mechanism is mathematically clean.

### Subtle gotcha (not in PRD): residualization may systematically lower CAGR

Logical chain:
1. RCMv1+Cand-2+Trial9 represent ~saturated long-only-top-10 alpha at 79-stock universe (per cycle04-08 evidence)
2. Residualizing on them removes SPY-beta-correlated alpha AND any shared idiosyncratic alpha
3. Residual return = remaining alpha left in stocks after subtracting "what fleet already captures"
4. If fleet captures ~all easy alpha, residual alpha ≈ 0
5. Mining on near-zero residual → low IC → low CAGR
6. **Risk**: residualized candidate may systematically fail Track A `vs_spy > 0` HARD gate

**Verdict**: ⚠️ NEW RISK identified — add as R7 below.

### Why active-share / HRP failed but residualization might not

Active-share: hold-vector divergence at *selection* layer. Doesn't change the TARGET being predicted.
HRP: weight redistribution at *construction* layer post-selection.
Cadence/factor-swap: same target, same selection rule, different factors.

Residualization: changes the TARGET itself. Forces different selection because score function differs.

**Verdict**: ✅ Residualization attacks a different layer than prior tested axes; expected magnitude effect different.

---

## §R3 — Actually-run-code (partial)

### Verified via Bash + Python:

**Fleet NAV data exists but date-range inconsistent**:
- `data/sr_validation/rcmv1_arm_A_baseline_nav.parquet`: 2018-01-02 → 2025-12-31 (2451 rows)
- `data/sr_validation/candidate_2_orthogonal_TRAIN_ONLY_arm_baseline_nav.parquet`: 2009-01-02 → 2017-12-30 (2426 rows)
- `data/sr_validation/trial9_arm_A_baseline_nav.parquet`: 2018-01-02 → 2025-12-31 (2451 rows)

**Zero 3-way overlap**. Cand-2 ends Dec 2017; RCMv1 + Trial 9 start Jan 2018.

**Implication for B7 implementation**: must run frozen RCMv1 + Cand-2 + Trial9_v2 specs against shared panel (2009-2024) to generate unified daily NAV series. Backcast is a B7 prerequisite, not an optional step.

### NOT yet verified (deferred to B7 implementation):
- 36m rolling β computation feasibility on real fleet NAV
- Residual fwd return numerical sanity (no explosive values, NaN coverage)
- Composite_evaluator hook into residual target (integration test)
- Smoke 10-trial reeval (B9)

---

## §R4 — Boundary cases (extending PRD §6 R1-R6)

### R7 (NEW): Residualization may systematically lower CAGR below SPY
- **Risk**: per §R2 subtle gotcha, residual alpha may be near-zero if fleet captures saturated alpha
- **Detection**: cycle10 200-trial mining produces 0 trials passing AC5 (Track A vs_spy > 0)
- **Mitigation**: PRD §5 stop rule (0-nominee acceptable). If cycle10 0-nominee, INFORMATIVE outcome — proves bundle-binding extends past objective-layer fix.
- **Severity**: structural risk, not implementation bug. Accepts as part of the bet.

### R8 (NEW): Fleet NAV date-range inconsistency → backcast required
- **Risk**: implementation might use partial-period fleet NAV, biasing β estimates
- **Mitigation**: B7 first task = backcast all 3 fleet specs on shared 2009-2024 panel → unified daily NAV series. Verify by spot-check vs existing parquet (where they overlap).
- **Severity**: medium; clear mitigation path

### R9 (NEW): Research factor pool 2009 data availability
- **Risk**: Bucket B fundamental factors (Piotroski / FCF / quality) need EDGAR data; coverage may start mid-2009 or later for some symbols
- **Mitigation**: existing PRD 20260512 Bucket B implementation handles PIT-aware factor masking via `data_sensitivity_mask`. Reuse.
- **Severity**: low (already solved by existing infra)

### R10 (NEW): Cycle10 candidate's forward observation contract
- **Risk**: if cycle10 produces a Track A nominee, forward observation needs to track signal_input + execution_nav hashes per PRD 20260512. Mining is one stage; forward init is another.
- **Mitigation**: same as Trial 9 v2 — use existing forward.runner.init() with `evidence_config: {track_signal_input_per_cell: true}` per the post-trial9_001 fix.
- **Severity**: low (existing infra handles)

---

## §B6.5 — Open question disposition (operator defaults; user override available)

Per PRD §9, 4 open questions. Defaults selected for proceeding:

1. **β method**: **36m rolling OLS** (Blitz 2011 precedent verified in R1).
   Alternatives (Bayesian shrinkage, Kalman) NOT pursued v1 — they add
   eng surface without clear empirical benefit at this universe scale.

2. **Fleet inclusion**: **RCMv1 + Cand-2 + Trial9_v2 (all 3)**.
   Aborted candidates' NAV series still represent the "binding sibling
   geometry" we want to break. Including them maximizes anti-sibling
   defense; user can override at B6.5 if they prefer Trial9-only.

3. **Acceptance tier**: **`partial_diversifier` (raw < 0.70)**.
   Per Clarke-Silva-Thorley TC math (R1 verified), raw < 0.50 (true_diversifier)
   is structurally near-unattainable under our universe + construction. Accepting
   raw < 0.70 as success bar.

4. **Stop rule**: **0-nominee cycle10 outcome is acceptable and closes cycle10**.
   Per PRD §5. If user wants automatic cycle11 axis change (e.g., bundle
   break / strategy-type pivot), require explicit-go at closeout time.

---

## §Verdict

**B6 audit: PASS**. PRD is shippable to B7 implementation with the following adjustments:
- R7 added to PRD §6 (CAGR penalty risk) — minor edit
- R8 added to PRD §6 (fleet NAV backcast required) — implementation note
- R9, R10 noted (low severity, addressed by existing infra)

**Tactical defaults selected for B6.5** (user override available):
- 36m OLS β
- 3-member fleet (incl. aborted)
- partial_diversifier acceptance
- 0-nominee accepted close rule

**Proceeding to B7** without user check-in per directive 2026-05-13:
"如果不需要我的一些决策的话 不需要停下来 直接往下走"
