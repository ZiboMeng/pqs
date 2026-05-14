# PRD — NAV-Residualized Mining Objective (cycle10 axis)

**Authors**: operator (zibomeng@), Claude Code assist
**Date**: 2026-05-13
**Status**: DRAFT v1 (operator self-audit pending)
**Triggered by**: 12-axis WebSearch synthesis + 2-round audit + Stream A ship
**Lineage**: `nav-residualized-cycle10-2026-05-13`

---

## §1 TL;DR

Cycle04-08 + cycle09b mining all produced "sibling-by-NAV" candidates: top
trials pass IC/IR/Track A acceptance but **raw daily-return Pearson vs
existing fleet (RCMv1 / Cand-2 / Trial 9 v2) lands 0.85-0.92**. The structural
diagnosis (cycle07a Trial 3 audit + audit-of-audit chain 2026-05-13):
long-only top-10 monthly over 79-stock universe **mechanically** shares 30-50%
holdings with any other long-only top-N strategy on the same universe, and
the shared SPY beta further compresses NAV correlation. Factor-swap +
construction-zoo + universe-tilt + cadence variants tested in cycles 04-09
collectively moved raw NAV correlation by ≤ 0.05.

**Solution**: replace the mining objective from "predict forward returns" to
"predict forward returns **residualized against existing fleet NAV**". This
forces TPE to find factor composites whose IC is computed against the
**orthogonal-to-fleet** return component — by construction, the resulting
candidate's NAV is less correlated with the fleet than IC-on-raw-returns
counterparts.

**Theoretical precedent**: Blitz-Huij-Martens 2011 "Residual Momentum"
(J. Empirical Finance 18:506-521) showed that regressing forward returns
on Fama-French 3-factor (36m rolling) and mining momentum on the **residual**
produces **risk-adjusted profit ≈ 2× standard momentum**. Direct adaptation:
replace FF3 regressors with fleet NAV series.

**Expected outcome (per Grinold-Kahn ch 16 + Clarke-Silva-Thorley TC math)**:
- Best-case raw NAV correlation drop: 0.85-0.92 → 0.60-0.75
  (TC≈0.40-0.55 for long-only top-10/79 setup re-introduces ~50% benchmark
  beta into the projected weight vector; achieving < 0.50 raw NAV correlation
  is mathematically near-unattainable under our universe + construction).
- Best-case Sharpe lift vs cycle04-08 baseline: -0.05 to +0.10 (Sharpe penalty
  for mining on residual is usually small; main benefit is fleet diversification
  not standalone alpha boost).

**Cycle10 stop rule preserved**: if 0 nominees pass Track A + new NAV gate,
close as informative null result and re-evaluate axis (per cycle04 close
memo discipline).

---

## §2 Problem statement

### §2.1 Sibling-by-NAV pattern (empirical evidence ≤2024)

From `docs/audit/20260513-sibling_binding_constraint_audit.md` §1:

| Pair | raw NAV Pearson | residual vs SPY | Notes |
|---|---|---|---|
| RCMv1 ↔ Cand-2 (realized forward) | **0.898** | 0.609 | Same bundle, zero shared factors |
| cycle07a Trial 3 ↔ RCMv1 (16y panel) | **0.874** | 0.603 | Same bundle, 1 shared factor (drawup) |
| cycle07a Trial 3 ↔ Cand-2 | **0.892** | 0.688 | Same bundle, zero shared factors |
| cycle04 Cluster A ↔ RCMv1 (cross-asset) | **0.66-0.70** | n/a | Universe + construction changed |
| alt-A intraday reversal ↔ RCMv1 | **0.146** | 0.142 | Whole bundle changed (strategy type) |

**Diagnosis (audit v2)**: within long-only-daily-monthly-top-N-79-stock bundle,
all "factor / construction / cadence" axes only move raw NAV correlation by
≤ 0.05. The bundle itself is the binding constraint via mechanical universe-
coverage overlap + shared SPY beta.

### §2.2 Why NAV-residualized objective is the correct attack

The previous axes failed because they attack the wrong layer:
- **Active-share penalty** (Cremers-Petajisto): hold-vector divergence, not
  return divergence. Doesn't directly improve raw NAV correlation under
  long-only top-N (Cremers 2009 + MSCI 2014: realistic raw NAV reduction
  0.03-0.10 only).
- **HRP / ERC / MV-shrinkage**: weight-redistribution at fixed selection
  → raw NAV moves ≤ 0.05 (DeMiguel 2009 RFS: 1/N benchmark robust under
  long-only).
- **Multi-family factor mix**: changes factor IC structure but not the
  selection geometry → same sibling.

**NAV-residualized objective is different**: mining target = `forward_ret −
β × fleet_ret`. Even with identical universe + construction + selection,
candidates that maximize IC against the *residual* must by construction have
weight choices that produce orthogonal NAV. This is the academically-
sanctioned form of "diversification at the alpha layer" (Grinold-Kahn ch 16).

### §2.3 Why we believe this is not just another sibling

Blitz-Huij-Martens 2011 empirical: residual-momentum mining over FF3 produced
candidates with **substantially different stock selections** than standard
momentum, despite same universe and same monthly rebalance. The factor IC was
computed against the residual; the resulting selection diverged from beta-
loaded names. Risk-adjusted Sharpe ≈ 2× standard momentum.

We adapt this: regressors are fleet NAV series (RCMv1, Cand-2, Trial 9 v2)
instead of FF3, but the mechanism is identical.

---

## §3 Mathematical specification

### §3.1 Notation

- `ret[s,t]` = daily return of stock `s` on day `t`
- `fwd_ret[s, t→t+21]` = forward 21-day cumulative return (PQS standard horizon)
- `nav_fleet_k[t]` = daily return of fleet candidate `k` on day `t`
  - `k ∈ {RCMv1, Cand-2, Trial9_v2}` per cycle10 freeze (§4.2)
- `β[s, k, t]` = rolling 36-month regression coefficient of stock `s`'s
  daily return on fleet candidate `k`'s daily return (Blitz precedent)

### §3.2 Residual forward return target

For each `(s, t)`:

```
residual_fwd_ret[s, t→t+21]
  = fwd_ret[s, t→t+21]
    − Σ_k β[s, k, t] × cum_fleet_ret[k, t→t+21]
```

Where:
- `β[s, k, t]` = OLS coefficient from regressing `ret[s, .]` on `nav_fleet_k[.]`
  over the **trailing 36 months** ending at `t-1` (no lookahead).
- Multi-factor regression: regress on ALL fleet members simultaneously
  (single OLS with K=3 regressors).

### §3.3 Mining objective

For each TPE trial sampling composite spec `c`:

```
composite_score[s, t] = Σ_i w_i × zscore_cs(factor_i[s, t])
IC_residual[t] = corr_xs(composite_score[s, t], residual_fwd_ret[s, t→t+21])
IC_IR_residual = mean(IC_residual) / std(IC_residual)
```

**Objective to maximize**: `IC_IR_residual` (mirrors existing
`composite_evaluator` IC_IR computation, with target swapped).

### §3.4 Acceptance evaluation

After mining, top-K trials run through:

1. **Existing Track A 17-gate acceptance** (`temporal_split_acceptance.py`)
   on raw forward returns (unchanged from cycle04-08). Hard gates:
   - Full period vs_spy > 0
   - 2025 holdout vs_spy > 0 — **BUT 2025 is validation, cannot mine on**.
     Acceptance evaluator still runs on 2025 as the final holdout check.
   - Per-validation-year MaxDD ≤ 20%
   - Stress slice MaxDD ≤ 25%
   - Concentration M12 top1 ≤ 40% / top3 ≤ 70%
   - Beta to SPY ≤ 0.85 (per Track A v1 yaml)

2. **NEW: NAV correlation gate** (post-Track A):
   - Compute raw NAV Pearson + SPY-residual NAV Pearson vs each fleet member
     over training panel (≤2024)
   - Tier classification per CLAUDE.md (un-revised):
     - raw < 0.50 → `true_diversifier` (acknowledged near-unattainable per TC math)
     - raw < 0.70 → `partial_diversifier` (target)
     - raw 0.70-0.85 → `warn_label_void`
     - raw ≥ 0.85 → `reject_step5`
   - PRD acceptance: `partial_diversifier` or better.

3. **Transfer coefficient (TC) reporting** (Grinold-Kahn discipline):
   - Compute TC = correlation between unconstrained-optimal active weights
     and constrained (long-only top-10 cap_aware) realized active weights
   - Report alongside NAV correlation; if TC < 0.30, flag candidate as
     "construction-clipped" (signal mostly lost to long-only projection)

---

## §4 Implementation plan

### §4.1 Module: `core/mining/nav_residualized_evaluator.py`

```python
from typing import Sequence, Mapping
import pandas as pd
import numpy as np

def compute_rolling_beta(
    stock_returns: pd.DataFrame,   # cols=symbols, idx=daily dates
    fleet_returns: pd.DataFrame,   # cols=fleet_id, idx=daily dates
    window_months: int = 36,
) -> dict[str, dict[str, pd.Series]]:
    """Return β[sym][fleet_id] -> Series indexed by date.

    36-month rolling OLS regression of each stock on ALL fleet members
    simultaneously (multi-factor). One regression per (sym, date) endpoint.
    """
    ...

def compute_residual_forward_returns(
    fwd_returns: pd.DataFrame,     # cols=symbols, idx=date (forward 21d cum)
    fleet_fwd_returns: pd.DataFrame,  # cols=fleet_id, idx=date (forward 21d cum)
    beta_by_date: dict[str, dict[str, pd.Series]],
) -> pd.DataFrame:
    """Return residual_fwd_ret[sym, t] = fwd_ret[sym, t] - Σ_k β[sym, k, t] × fwd_fleet[k, t]."""
    ...

def evaluate_composite_residualized(
    composite_score: pd.DataFrame,    # cols=symbols, idx=date
    residual_fwd_returns: pd.DataFrame,
) -> dict:
    """Mirror composite_evaluator's IC/IR computation, on residualized target."""
    ...
```

### §4.2 Cycle10 yaml — frozen pre-mining (§4 of cycle04 mining contract)

`data/research_candidates/track-c-cycle-2026-06-XX-10_promotion_criteria.yaml`:

```yaml
cycle_id: track-c-cycle-2026-06-XX-10
lineage: nav-residualized-cycle10-2026-05-13
created_at: '2026-06-XX'   # filled when actually fired
mining_engine: tpe_with_residualized_target

# Single-axis diff vs cycle09b:
#   - mining_target: from raw_fwd_ret → residualized_fwd_ret
#   - fleet members for residualization fixed below
#   - everything else identical to cycle09b
mining_target:
  type: nav_residualized
  fleet_members:
    - rcm_v1_defensive_composite_01   # ABORTED but NAV history preserved
    - candidate_2_orthogonal_01       # ABORTED but NAV history preserved
    - trial9_diversifier_002          # ACTIVE forward
  beta:
    method: ols
    window_months: 36
    multi_factor: true
  fleet_data_path: data/research_candidates/{candidate_id}_forward_manifest.json (NAV series)
  fleet_data_strict_train_end: 2024-12-31  # do not use 2025/2026 NAV for β

mining_config:
  n_trials: 200
  sampler: TPESampler
  seed: 42
  ic_horizon_days: 21
  family_pool: FAMILIES_V2  # all 16 families per Bucket A/B/C/Macro PRD 20260512
  min_families: 3
  max_per_family: 2
  cardinality: 3
  factor_registry_pool: RESEARCH_FACTORS  # 162-factor pool

acceptance:
  policy_version: alternating_regime_holdout_v1
  track_a_17gate: same as cycle04-08
  nav_correlation_gate:
    enabled: true
    tier_required: partial_diversifier  # raw < 0.70
    measure_vs: [rcm_v1, cand_2, trial9_v2]
    panel: train_years_only_2009_to_2024
  tc_reporting:
    enabled: true
    warn_threshold: 0.30

stop_rule_post_cycle:
  if_zero_nominees: close as informative null; cycle10 axis exhausted

# Strict provenance audit (per sealed leak postmortem 20260513):
provenance_audit:
  all_design_choices_train_only: true
  no_2025_no_2026_data_in_mining: true
```

### §4.3 Test surface

`tests/unit/mining/test_nav_residualized_evaluator.py` — ≥ 15 tests:
- Rolling β computation (synthetic data with known β)
- Multi-factor regression vs single-factor (3-fleet vs 1-fleet)
- Residual target = raw target − explained component
- NaN handling at warmup (< 36mo data)
- Fleet member missing data (some dates NaN)
- Edge: fleet members perfectly collinear → handle gracefully
- IC/IR computation on residual matches existing composite_evaluator API

### §4.4 Smoke (B9): 10-trial mini cycle

Run 10 trials with residualized target on cycle04 archive's first 10 trial
specs (re-evaluate, no new mining). Compare raw NAV correlation vs fleet:
- Expected: raw NAV correlation drops materially (~0.10-0.20 reduction)
  vs cycle04 archive baseline.
- **Smoke fail criterion**: if drop < 0.05 on all 10 trials, implementation
  bug or method failure — pause + diagnose.

---

## §5 Acceptance criteria (PRD-level)

| # | Criterion | Pass condition |
|---|---|---|
| AC1 | Module ships + tests pass | ≥ 15 unit tests + integration smoke green |
| AC2 | Smoke (10-trial reeval of cycle04 archive) shows raw NAV correlation drop ≥ 0.05 on majority | ≥ 6/10 trials show drop |
| AC3 | Cycle10 yaml frozen + sha256 recorded | yaml committed, hash logged |
| AC4 | Cycle10 200-trial mining completes w/o sampler-architecture bug | n_trials ≥ 100 archived (not 100% pruned) |
| AC5 | Top-3 trials pass Track A 17-gate | ≥ 1 trial in {raw < 0.85 AND vs_spy > 0 AND MaxDD ≤ 25%} |
| AC6 | Top-3 trials NAV correlation gate verdict | ≥ 1 trial classified `partial_diversifier` (raw < 0.70) |
| AC7 | TC reporting visible | TC computed + reported for top-3, no gate enforcement v1 |

**0-nominee outcome is acceptable**: if AC5/AC6 fail for all top-3, close
cycle10 as informative null. This validates the bundle-binding hypothesis at
the strongest possible attack vector and tells us NAV-orthogonalization is
also insufficient under long-only top-10 / 79-stock constraint. Strategic
implications then point to bundle break (different strategy type / multi-
asset / event-driven).

---

## §6 Risks + mitigations

### §6.1 R1 — Residualization just shifts sibling without breaking it
- **Risk**: mining on residual produces candidates that look orthogonal in
  ε-space but reproduce same sibling NAV after long-only projection (Clarke-
  Silva-Thorley TC ≈ 0.4-0.55 reintroduces benchmark beta).
- **Mitigation**: AC6 requires `partial_diversifier` (raw < 0.70) post-projection.
  If fails systematically, evidence accumulates that bundle-binding extends
  past objective-layer fix → strategic pivot.

### §6.2 R2 — Sampler architecture bug from cycle09 (combinatoric explosion)
- **Risk**: same `family_first` sampler issue cycle09 hit when expanding to
  16-family pool.
- **Mitigation**: use shipped `sampling_mode: family_first` from `f41c7e5`.
  Smoke with 10-trial sampler sanity check before 200-trial mining.

### §6.3 R3 — Fleet NAV series quality issues
- **Risk**: aborted candidates (RCMv1, Cand-2) have only TD001-TD003 forward
  NAV. Insufficient daily-NAV history for 36m β estimation.
- **Mitigation**: use **research-period** NAV (computed by running RCMv1 /
  Cand-2 frozen specs on train panel 2009-2024) for β estimation, NOT
  forward observations. This gives full 16-year daily NAV series per fleet
  member, plenty for 36m rolling β.

### §6.4 R4 — 2025/2026 data contamination
- **Risk**: residualization needs daily fleet returns. If we accidentally
  include 2025/2026 NAV in β estimation, we contaminate.
- **Mitigation**: `fleet_data_strict_train_end: 2024-12-31` in yaml.
  Implementation must hard-assert no panel date > 2024-12-31 used in β computation.

### §6.5 R5 — Mining objective overfitting on residual
- **Risk**: residual space has lower signal-to-noise; mining might find
  noise patterns. Especially if fleet members are highly correlated (RCMv1+
  Cand-2 raw 0.898), residualization removes most of the variance.
- **Mitigation**:
  - Use multi-factor regression (3 fleet members simultaneously)
  - Track A 17-gate acceptance unchanged → catches overfit candidates
  - Smoke (B9) validates IC_IR magnitudes are reasonable (>0.3 ish, not tiny)

### §6.6 R6 — Long-only invariant under-projected
- **Risk**: implementation might inadvertently produce signals requiring
  negative weights when projecting back to portfolios.
- **Mitigation**: composite_evaluator uses `cap_aware_cross_asset` construction
  which enforces long-only by simplex projection. Already battle-tested in
  cycle04-08.

---

## §7 Audit / provenance

### §7.1 Train-only provenance check (per sealed leak rule 20260513)

All design choices in this PRD must be justifiable from train (≤2024) +
theory papers. Verification:

- ✅ Residual target formula: Blitz-Huij-Martens 2011 (J. Empirical Finance)
- ✅ 36m rolling β window: Blitz precedent
- ✅ Multi-factor OLS: Grinold-Kahn ch 16 standard
- ✅ Acceptance gates: unchanged from cycle04-08 (frozen pre-leak)
- ✅ NAV correlation tier: CLAUDE.md unchanged (sealed-leak rollback preserved)
- ✅ Bundle-binding diagnosis: cycle04-08 archived trials (all ≤2024)
- ✅ TC math expectations: Clarke-Silva-Thorley 2002 FAJ
- ⚠️ 2026 LLM paper (Hubble arXiv 2604.09601) cited for diversity-penalty
  ARCHITECTURE inspiration; no numerical claims used.

**No sealed-window market data** influenced design.

### §7.2 4-tier self-audit (per CLAUDE.md feedback_audit_per_round_methodology)

- **R1 fact check**: TBD in B6 (verify Blitz 2011 formulas, TC range)
- **R2 logical**: TBD in B6 (chain bundle-binding → residualization → expected lift)
- **R3 actually-run-code**: TBD in B7-B9 (smoke shows ≥ 0.05 drop)
- **R4 boundary**: TBD in B6 (R1-R6 above + missed-case enumeration)

### §7.3 Decision points

- **B6.5** (post-PRD self-audit): operator + (optional user) review.
  User check-in needed for:
  - β method: confirm 36m rolling (vs alternatives like full-period or
    Kalman / shrinkage)
  - Fleet definition: confirm include RCMv1 + Cand-2 + Trial9_v2 (vs
    only active forward candidates)
- **B9.5** (smoke result): if AC2 fails, pause + diagnose; else continue
- **B15.5** (cycle10 closeout): user decides forward-init of any nominee

---

## §8 Out of scope (deferred)

- LLM-driven factor candidate generation (Hubble / QuantaAlpha style) —
  separate PRD if cycle10 succeeds + warrants ML expansion
- AST-similarity diversity penalty (Hubble §3.2) — adds engineering surface;
  defer until cycle10 produces baseline result
- Active-share penalty in selection (Cremers-Petajisto) — orthogonal axis,
  not stacked v1
- Universe expansion to 200+ stocks (Task #16) — defer; cycle10 stays on
  current 79-stock + cross-asset universe (cycle04-yaml frozen)
- New strategy types (alt-archetype B PEAD / event-driven) — separate
  authorization tree

---

## §9 Open questions (for B6 self-audit + B6.5 check-in)

1. **β estimation method**: 36m rolling OLS is Blitz precedent for FF3.
   For fleet members (which are themselves portfolios with internal
   stock-level β to SPY), does 36m OLS introduce double-β estimation
   noise? Alternative: shrinkage / Bayesian β.
2. **Fleet member inclusion**: aborted RCMv1 + Cand-2 are still on disk
   with full research-period NAV (per §6.3 mitigation). But conceptually,
   they're not the binding fleet competitors going forward (terminal
   status). Including them might bias residualization toward dead alphas.
   Should fleet be only `trial9_diversifier_002`?
3. **Acceptance tier**: PRD §3.4 keeps CLAUDE.md tier unchanged
   (`partial_diversifier` = raw < 0.70). Per TC math (Clarke-Silva-Thorley),
   raw < 0.50 `true_diversifier` is structurally near-unattainable. PRD
   accepts `partial_diversifier` as success bar. Confirm.
4. **Stop rule reactivation**: cycle04 close memo committed "if cycle 05 0
   nominee, no cycle 06". We've run 06/07a/08/09 anyway. PRD §1 says "stop
   rule preserved" — does it actually fire if cycle10 0-nominee, or is
   it implicitly relaxed?

---

## §10 Sign-off

| Owner | Action | Status |
|---|---|---|
| Operator | Self-audit (R1+R2+R4) | Pending (B6) |
| Operator | B7 implementation | Pending |
| Operator | B8+B9 tests + smoke | Pending |
| User | B6.5 directional answers to §9 questions | **Required before cycle10 fire** |
| Operator | B10 cycle10 yaml freeze + sha256 | Pending |
| Operator | B12 200-trial mining | Pending |
| Operator | B15 closeout memo | Pending |

---

## Appendix A — math worked example (synthetic)

Stock S with 36-mo daily returns. Fleet has 1 member F.
- Cov(S, F) = 0.0001
- Var(F) = 0.00015
- β = Cov / Var = 0.667

If 21-day forward cumulative return of S = +5% and 21-day cumulative
return of F = +3%, residual forward return:

`residual_fwd_ret = +5% − 0.667 × +3% = +5% − 2% = +3%`

Mining factor `f` ranks S high if it predicts the +3% **residual**, not
the +5% raw. A factor purely loading on F's beta would predict +5% raw but
0% residual → would NOT rank S high in residualized mining.

This is the mechanism: factors that just replicate fleet beta get IC = 0
on residual; only factors that capture orthogonal information get rewarded.
