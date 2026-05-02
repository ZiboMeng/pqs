# PRD — Phase C-PRD-2: DD Throttle + Role Caps (Sleeve Abstraction)

**Status**: `DRAFT_PENDING_FORWARD_EVIDENCE` — schema + interfaces locked; all
numeric thresholds, throttle parameters, ramp curves, correlation triggers
left as `<TBD_FROM_FORWARD>`. Implementation NOT authorized until Trial 9
forward TD60 verdict = GREEN per parent PRD §11.

**Authority parent**: `docs/prd/20260501-two_stage_allocation_architecture_prd.md`
§5.3 (Stage 3 Portfolio Layer) + §6.4 (Allocation policy gate)

**Trigger condition**: `trial9_diversifier_001` TD60 verdict = GREEN (PRD
§7.1 GREEN: residual NAV corr 60d <0.4 + per-regime BULL vs_qqq 60d > -3% +
portfolio combo positive + soft_warn_flag self-cleared)

**Phase order**: C-PRD-2 (this) → C-PRD-3 (fleet observe runner) → C-PRD-4
(shadow→live transition). Each gates the next.

**Scope of this DRAFT**: 5 of 7 originally-planned items, all path-independent
from forward evidence:

| Section | Item | Status |
|---|---|---|
| §3 | Sleeve abstraction schema | DRAFT |
| §4 | Portfolio combo report schema | DRAFT |
| §5 | DD throttle interface (no params) | DRAFT |
| §6 | Forward TD20/40/60 attribution format | DRAFT |
| §7 | Stage 3 ↔ Track B Step 1-5 relationship | DRAFT |
| §8 | Correlation-aware throttle interface | **DEFERRED** — design depends on forward residual_corr time series |
| §9 | Parameter list (throttle thresholds, ramp, ceilings) | **DEFERRED** — depends on §8 + forward maxdd / drawup distribution |

---

## 1. Background [CERTAIN]

Phase C-PRD-1 shipped the lightweight diversifier role tag + Trial 9 forward
init. CLAUDE.md "Forward OOS active workstream" inventory confirms manifest
at `data/research_candidates/trial9_diversifier_001_forward_manifest.json`
with `start_date=2026-05-04` and `soft_warn_flags=['diversifier_2025_maxdd_18_20pct']`.

C-PRD-2 builds the **sleeve abstraction** that mediates between individual
candidates (RCMv1 / Cand-2 / Trial 9 / future) and a fleet-level executable
portfolio. Without it, multiple candidates passing TD60 cannot become a single
tradeable allocation — only a multi-NAV diagnostic.

## 2. Non-goals [CERTAIN]

- NOT introducing real broker integration (still `no real broker / no margin`
  invariant)
- NOT introducing a new alpha source (sleeves wrap existing candidates;
  alpha discovery remains Track C cycle workstream)
- NOT introducing dynamic leverage or short-selling for any sleeve
- NOT making allocation decisions automatic in production — every
  allocation change goes through `decide()` step with operator review until
  C-PRD-4 shadow→live runs ≥ 60 TD clean
- NOT pre-implementing the correlation-aware throttle (§8 deferred until
  forward evidence informs the trigger schema)

## 3. Sleeve abstraction schema [DRAFT — path-independent]

### 3.1 SleeveConfig

```python
# core/research/two_stage_allocation/sleeve_config.py

from datetime import date
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SleeveRoleType(str, Enum):
    """Role taxonomy at the sleeve (not candidate) layer.

    A sleeve aggregates candidates of compatible role; a candidate's
    CandidateRole determines which sleeve(s) it is eligible for.
    """
    core_alpha = "core_alpha"
    diversifier = "diversifier"
    risk_control = "risk_control"


class SleeveConfig(BaseModel):
    """Static configuration of a sleeve.

    Sleeves are LONG-LIVED entities (months/quarters), not per-decision
    concepts. Adding/removing a sleeve requires explicit config change
    + audit log entry, not a runtime decision.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    sleeve_id: str = Field(min_length=3, pattern=r"^[a-z][a-z0-9_]*$")
    role: SleeveRoleType
    description: str

    # Member candidates
    member_candidate_ids: List[str] = Field(min_length=1)

    # Within-sleeve weight constraints (Stage 2 internals)
    within_sleeve_max_single_weight: float = Field(gt=0.0, le=1.0)
    within_sleeve_max_cluster_weight: Optional[float] = Field(default=None, gt=0.0, le=1.0)

    # Sleeve-level cap as fraction of fleet NAV (Stage 3 input)
    fleet_max_weight_ceiling: float = Field(gt=0.0, le=1.0)
    fleet_min_weight_floor: float = Field(default=0.0, ge=0.0, le=1.0)

    # DD throttle config (see §5; all values TBD)
    dd_throttle_threshold: Optional[float] = Field(default=None)  # TBD
    dd_throttle_target: Optional[float] = Field(default=None)     # TBD
    dd_throttle_lookback_td: Optional[int] = Field(default=None)  # TBD
    dd_ramp_back_lookback_td: Optional[int] = Field(default=None) # TBD

    # Forward provenance
    activated_at: date
    deactivated_at: Optional[date] = None  # null = active
    activation_memo_path: str  # decision memo trail
```

### 3.2 SleeveState (runtime)

```python
class SleeveState(BaseModel):
    """Mutable runtime state for a sleeve at a point in time.

    Persisted alongside fleet manifest; updated each rebalance.
    """
    model_config = ConfigDict(extra="forbid")

    sleeve_id: str
    as_of_date: date

    # Capital allocation (Stage 1 output → Stage 3 input)
    target_weight_in_fleet: float = Field(ge=0.0, le=1.0)
    actual_weight_in_fleet: float = Field(ge=0.0, le=1.0)
    weight_drift: float  # actual - target

    # Holdings (Stage 2 output)
    holdings: dict[str, float] = Field(default_factory=dict)

    # Sleeve-internal NAV (1.0 at sleeve activation_at)
    sleeve_nav: float = Field(gt=0.0)
    sleeve_60d_max_dd: Optional[float] = Field(default=None, le=0.0)

    # Throttle status
    throttle_active: bool = False
    throttle_active_since: Optional[date] = None
    throttle_reason: Optional[str] = None  # "max_dd_breach" | "corr_breach" | "manual"
    throttle_target_weight: Optional[float] = Field(default=None, ge=0.0)
    throttle_ramp_eta: Optional[date] = None
```

### 3.3 Sleeve membership rules [CERTAIN]

| Rule | Specification |
|---|---|
| Candidate role → sleeve role | core_alpha candidate → core_alpha sleeve only; diversifier candidate → diversifier sleeve only |
| Cardinality | ≥1 candidate per sleeve at activation; sleeve auto-deactivates if all members demote |
| Member transition | A candidate may move sleeves only via formal demote/repromote (CandidateRecord.role change is impossible per current contract; would require explicit operator override + audit memo) |
| Pre-PRD candidates | RCMv1 + Cand-2 (legacy_decay_verification role) NOT eligible for any sleeve; they remain forward-observation-only |

## 4. Portfolio combo report schema [DRAFT — path-independent]

### 4.1 PortfolioComboReport

```python
# core/research/two_stage_allocation/portfolio_combo_report.py

from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SleeveContribution(BaseModel):
    """Per-sleeve attribution for a single TD."""
    model_config = ConfigDict(extra="forbid")

    sleeve_id: str
    target_weight: float
    actual_weight: float
    sleeve_daily_ret: float
    contribution_to_fleet_ret: float  # = actual_weight × sleeve_daily_ret
    is_throttled: bool


class PortfolioComboReport(BaseModel):
    """Daily fleet-level NAV + per-sleeve attribution + risk metrics.

    Persisted at `data/research_candidates/fleet_manifest.json` via
    Stage 3 portfolio_constructor (similar to ForwardRunManifest pattern).
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    generated_at_utc: datetime
    fleet_id: str  # e.g. "v1_trial9_plus_legacy"
    as_of_date: date

    # Sleeve-level
    sleeve_contributions: List[SleeveContribution]

    # Fleet-level NAV
    fleet_nav: float = Field(gt=0.0)
    fleet_cum_ret: float
    fleet_daily_ret: float

    # Risk metrics (rolling)
    fleet_60d_max_dd: Optional[float] = Field(default=None, le=0.0)
    fleet_252d_max_dd: Optional[float] = Field(default=None, le=0.0)

    # Benchmarks
    spy_60d_cum_ret: Optional[float] = None
    qqq_60d_cum_ret: Optional[float] = None
    fleet_vs_spy_60d: Optional[float] = None
    fleet_vs_qqq_60d: Optional[float] = None

    # Cross-sleeve correlation (rolling 60d)
    cross_sleeve_residual_corr_max: Optional[float] = None
    cross_sleeve_residual_corr_pairs: Dict[str, float] = Field(default_factory=dict)

    # Throttle activity
    n_sleeves_throttled: int = Field(default=0, ge=0)
    throttled_sleeve_ids: List[str] = Field(default_factory=list)

    # Cost attribution (Stage 1 turnover + Stage 2 within-sleeve turnover)
    allocation_layer_cost_bps_today: Optional[float] = None
    sleeve_layer_cost_bps_today: Optional[float] = None

    # Notes (free text from operator/decide step)
    notes: List[str] = Field(default_factory=list)
```

### 4.2 Storage convention [CERTAIN]

| Artifact | Path | Cadence |
|---|---|---|
| Latest fleet snapshot | `data/research_candidates/fleet_manifest.json` | Daily (after EOD observe) |
| Daily attribution log | `data/ml/fleet_observe/<YYYY-MM-DD>.json` | Daily append-only |
| Decision memos | `docs/memos/<YYYY-MM-DD>-fleet_<event>.md` | On rebalance / throttle activation |

### 4.3 Idempotency contract [CERTAIN]

Re-running portfolio constructor with identical inputs (same `as_of_date`,
same sleeve states, same prices) MUST produce byte-identical output JSON
(modulo `generated_at_utc` field). Same hash discipline as Phase F config
snapshot — `_canonical_yaml_sha`-equivalent function on the report dict.

## 5. DD throttle interface [DRAFT — path-independent; params TBD]

### 5.1 Throttle decision contract

```python
# core/research/two_stage_allocation/dd_throttle.py

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class ThrottleDecision:
    """Output of DD throttle evaluator for a single sleeve at a single TD.

    All thresholds + parameters are READ FROM SleeveConfig at evaluation
    time (no module-level constants). This permits A/B testing different
    throttle configs without code changes.
    """
    sleeve_id: str
    as_of_date: date
    decision: str  # "no_action" | "throttle_to" | "ramp_back" | "release"
    target_weight: Optional[float]  # None when decision == "no_action"
    reason: str  # short string for audit trail
    inputs_snapshot: dict  # {dd_observed, threshold, lookback_td, ...}


def evaluate_throttle(
    *,
    sleeve_config: SleeveConfig,
    sleeve_state: SleeveState,
    nav_series: "pd.Series",  # daily sleeve NAV history
    today: date,
) -> ThrottleDecision:
    """Decide whether to throttle / ramp back / release.

    Stateless function; reads sleeve_config (thresholds) + sleeve_state
    (current throttle status) + nav_series (history). Does NOT mutate
    state — caller (portfolio_constructor) applies the decision.

    Decision tree (logic locked; thresholds TBD per §9):

        if sleeve_state.throttle_active:
            if rolling_dd(nav_series, lookback=ramp_back_lookback_td) >= -ramp_back_threshold:
                return ThrottleDecision("ramp_back", target_weight=...)
            elif still_in_breach():
                return ThrottleDecision("no_action", reason="throttle_persists")
            else:
                return ThrottleDecision("release", target_weight=full)
        else:
            if rolling_dd(nav_series, lookback=dd_throttle_lookback_td) <= -dd_throttle_threshold:
                return ThrottleDecision("throttle_to",
                                         target_weight=dd_throttle_target,
                                         reason=f"max_dd={...} breached threshold={...}")
            else:
                return ThrottleDecision("no_action")
```

### 5.2 Throttle invariants [CERTAIN]

- Throttle decision is **always reversible** via ramp-back; no permanent
  demote at the sleeve layer (permanent demote is a candidate-layer
  decision tracked in CandidateRegistry).
- Throttle target_weight ≥ sleeve `fleet_min_weight_floor` (cannot
  throttle below floor; if floor==0 then full release possible).
- Throttle activation **must** record `throttle_active_since` date for
  later attribution.
- Re-throttle within the same calendar week as a release is allowed but
  emits a WARNING in the attribution log (potential whipsaw).

### 5.3 What this interface does NOT decide [CERTAIN]

- Cross-sleeve correlation-aware throttling (§8 deferred).
- Fleet-level (rather than sleeve-level) DD throttling — that's Stage 3
  portfolio_constructor's responsibility, separate decision.
- Whether to add/remove a sleeve from the fleet (config change, not
  throttle).
- Capital reallocation between sleeves when one throttles — Stage 1
  policy decides where the freed capital goes.

## 6. Forward TD20/40/60 attribution format [DRAFT — path-independent]

### 6.1 Per-TD attribution snapshot

```python
# Generated by dev/scripts/forward/attention_check.py (already shipped)
# at TD20 / TD40 / TD60 milestones; consumed by Stage 3 to inform sleeve
# config + throttle parameter calibration (§9 deferred).

ForwardAttributionSnapshot = {
    "td_label": "TD20",                    # checkpoint name
    "as_of_date": "2026-06-01",
    "n_observed": 20,
    "candidate_id": "trial9_diversifier_001",

    # ── Per-anchor failure-mode signals ─────────────
    "max_dd_breach_observed": False,       # trial9 60d_rolling_dd <= -10%?
    "max_dd_breach_severity": None,        # how far below -10% (e.g. -0.13)
    "residual_corr_breach_observed": False,
    "residual_corr_breach_severity": None, # max(residual_corr) - 0.6
    "combo_negative_observed": False,
    "combo_neg_magnitude": None,           # combo_cum_ret - 0 (negative if breach)

    # ── Distribution stats for §9 calibration ──────
    "rolling_60d_max_dd_distribution": {
        "min": ..., "p25": ..., "p50": ..., "p75": ..., "max": ...,
    },
    "residual_corr_distribution": {
        "min": ..., "p25": ..., "p50": ..., "p75": ..., "max": ...,
    },

    # ── Cycle #06 contingency input ─────────────────
    "dominant_red_path": None,             # "max_dd" | "residual_corr" | "combo_neg" | None
    "dominant_red_path_evidence": [],      # list of TDs where this path triggered
}
```

### 6.2 Attribution → §9 parameter calibration mapping [DRAFT logic]

| Forward signal | C-PRD-2 parameter informed | Calibration rule (TBD details) |
|---|---|---|
| `rolling_60d_max_dd_distribution.p75` | `dd_throttle_threshold` | Set threshold ≥ p75 to avoid daily false positives during normal noise |
| `rolling_60d_max_dd_distribution.min` × 1.2 | `dd_throttle_target` weight reduction | Throttle target ~50-70% of unthrottled weight; calibrated so target × normalized_dd ≈ -8% bound |
| `rolling_60d_max_dd_distribution` shape | `dd_throttle_lookback_td` | If distribution has fat right tail, shorter lookback (faster trigger); narrow → longer lookback (avoid noise) |
| `dominant_red_path` from TD60 verdict | Whether §8 (correlation-aware) gets prioritized in C-PRD-2 v1 or deferred to v2 | If `residual_corr` dominates → §8 must ship in C-PRD-2 v1 |

**This mapping is provisional; actual calibration ritual will be a
formal exercise in C-PRD-2 implementation kickoff after TD60 GREEN.**

## 7. Stage 3 ↔ Track B Step 1-5 relationship [DRAFT — path-independent]

### 7.1 Track B Step 1-5 inventory (reused as Stage 3 inputs)

Per CLAUDE.md "Track B Fleet Allocator: Steps 1-5 SHIPPED":

| Step | Module | Reused as Stage 3 input |
|---|---|---|
| 1 | `core/fleet/capital_split.py` | Sleeve weight allocation primitive |
| 2 | `core/fleet/pairwise_correlation_budget.py` | §8 correlation-aware throttle precursor (when activated) |
| 3 | `core/fleet/factor_overlap_throttle.py` | Already enforced at candidate layer; sleeve layer inherits |
| 4 | `core/fleet/core_satellite.py` | Becomes the role-cap enforcement under §3.1 SleeveConfig.fleet_max_weight_ceiling |
| 5 | `core/fleet/c2_correlation_budget.py` | Cross-sleeve realized correlation budget; Stage 3 daily check |

### 7.2 Track B Step 6+ status

CLAUDE.md: **HARD PAUSED until ≥2 candidates exist that BOTH pass Track A
acceptance AND have realized-NAV pair correlation < 0.85.**

C-PRD-2 inherits this gate. Stage 3 builds on Steps 1-5 (which are
sleeve-level / fleet-level primitives) but **does NOT** activate Step 6+
unless TD60 GREEN demonstrates Trial 9 + a future second candidate satisfy
the < 0.85 correlation gate.

If Trial 9 TD60 GREEN but no second active candidate exists, Stage 3
runs in **single-sleeve mode** (Trial 9 sleeve + risk_control sleeve
populated by RCMv1/Cand-2 read-only NAVs as benchmarks, NOT capital
recipients). Correlation guards stay armed but inactive.

### 7.3 Module reuse contract [CERTAIN]

C-PRD-2 SHALL NOT modify Track B Step 1-5 modules' public API (signatures,
return types, behavior). Modifications require either (a) Track B Step 6+
unfreeze (separate decision), or (b) C-PRD-2 wraps + extends without
mutating, exposing wrapper API in `core/research/two_stage_allocation/`
namespace.

## 8. Correlation-aware throttle interface [DEFERRED]

**Why deferred**: Option A (historical walk-forward prior) showed 50% of
RED windows triggered by `residual_corr > 0.6`, not single-candidate DD.
The correct throttle schema for this depends on:

1. Forward residual_corr time series shape (volatility + persistence)
2. Whether the breach is gradual (cluster build-up) or sudden (single-day
   shock)
3. Whether Trial 9's residual_corr against RCMv1 vs against Cand-2 move
   together or independently

None of these can be pre-evaluated from in-sample data without bias.
The §8 design will be drafted as an addendum to this PRD after TD60.

## 9. Parameter list [DEFERRED]

All `<TBD_FROM_FORWARD>` parameters consolidated for §C-PRD-2
implementation kickoff:

| Parameter | Default in DRAFT | Source signal |
|---|---|---|
| `SleeveConfig.dd_throttle_threshold` | None | Forward `rolling_60d_max_dd_distribution.p75` |
| `SleeveConfig.dd_throttle_target` | None | Forward calibration (~50-70% of unthrottled weight) |
| `SleeveConfig.dd_throttle_lookback_td` | None | Forward distribution shape |
| `SleeveConfig.dd_ramp_back_lookback_td` | None | Forward recovery time observation |
| `SleeveConfig.fleet_max_weight_ceiling` (per role) | core_alpha=0.6 / diversifier=0.4 / risk_control=0.3 [PROVISIONAL from parent PRD §5.1.3] | Backtest validation post-TD60 |
| `SleeveConfig.fleet_min_weight_floor` (per role) | core_alpha=0.3 / diversifier=0.0 / risk_control=0.0 [PROVISIONAL] | Same |
| Cross-sleeve residual_corr ceiling | None | TD60+ residual_corr distribution |
| Re-throttle whipsaw warning threshold (TDs) | 5 | Operator judgment |

## 10. Acceptance criteria [DRAFT — to be evaluated post-implementation]

| ID | Criterion | Verification |
|---|---|---|
| A1 | SleeveConfig load + validate from yaml | unit test |
| A2 | SleeveState mutate via portfolio_constructor only | unit test (no direct setter) |
| A3 | DD throttle decision identical when re-evaluated with same inputs | property test |
| A4 | Throttle target weight ≥ floor (invariant) | property test |
| A5 | PortfolioComboReport idempotent generation | byte-identical replay test |
| A6 | Single-sleeve fleet works (no second active candidate) | integration test |
| A7 | Track B Step 1-5 modules unchanged (signatures + behavior) | regression suite |
| A8 | Forward attention_check.py output is structurally compatible with §6.1 schema | integration test |
| A9 | Re-throttle within 5 TDs of release emits WARNING in attribution log | test |
| A10 | Sleeve auto-deactivates when last member demoted | integration test |
| A11+ | (additional criteria for §8 + §9 deferred items) | TBD |

## 11. Phasing within C-PRD-2 [DRAFT]

| Step | Scope | Estimated effort |
|---|---|---|
| C-PRD-2.S1 | SleeveConfig + SleeveState models + yaml loader | 2-3 days |
| C-PRD-2.S2 | DD throttle evaluator + tests (uses TBD params) | 2-3 days |
| C-PRD-2.S3 | PortfolioComboReport schema + portfolio_constructor MVP | 3-4 days |
| C-PRD-2.S4 | Track B Step 1-5 reuse adapters | 2 days |
| C-PRD-2.S5 | Single-sleeve mode integration test (Trial 9 only) | 1-2 days |
| C-PRD-2.S6 | §9 parameter calibration (post-forward-evidence) | 3-5 days |
| C-PRD-2.S7 | §8 correlation-aware throttle (if forward evidence demands) | 5-7 days |
| C-PRD-2.S8 | Acceptance pack + close memo | 1-2 days |

**Total estimated** (excluding S6+S7 dependencies): **11-16 days** active
implementation. Realistic calendar window with reviews + audits: 4-5 weeks.

## 12. Out-of-scope (explicit list) [CERTAIN]

- C-PRD-3 fleet observe runner: separate PRD post-C-PRD-2 ship
- C-PRD-4 shadow→live: separate PRD post-C-PRD-3 ship
- Real-time intraday allocation: not now, never in this PRD chain
- Long/short or leveraged sleeves: violates `long-only / no-margin`
  invariant; out of scope without separate user explicit-go
- Auto-promotion of demoted candidates back to active: requires user
  explicit-go (anti-rehab discipline)

## 13. Dependencies [CERTAIN]

| Dependency | Status | Required for |
|---|---|---|
| Trial 9 TD60 verdict = GREEN | **PENDING (~2026-07-30)** | C-PRD-2 implementation kickoff |
| Forward attention_check infrastructure | ✅ Shipped commit `7dbae10` | §6 attribution |
| temporal_split v2 dispatch | ✅ Shipped commit `60e0dfe` | role-aware acceptance |
| ≥1 candidate in core_alpha role | NOT YET (cycle #06 dependent) | Multi-sleeve mode (single-sleeve mode works without it) |
| ≥2 active candidates with NAV corr <0.85 | NOT YET | Stage 3 multi-sleeve correlation guards (Step 6+ unfreeze) |

## 14. Reversibility [CERTAIN]

C-PRD-2 implementation is fully reversible:
- All sleeve configs are versioned; rollback = revert config + redeploy
- No new candidate registry mutations (sleeve membership stored
  separately)
- No new pricing / data semantics
- Track B Step 1-5 modules unchanged (no risk to existing fleet
  primitives)

Reverting requires:
- Single PR revert of `core/research/two_stage_allocation/` namespace
- Fleet manifest + observe logs preserved (audit trail)
- No data deletion, no broker-side state to undo (no broker integration)

## 15. Self-audit checklist (R1-R4) [TBD on implementation]

- R1 (factual): all schemas conform to PRD parent §5.1-§5.3
- R2 (logical): sleeve role transitions consistent with CandidateRole
  immutability
- R3 (executed): full e2e smoke from Trial 9 forward state through
  fleet manifest output
- R4 (boundary): single-sleeve mode + zero-active-throttle case +
  whipsaw scenario all pass

---

**End of DRAFT**. Sections §8 + §9 + §11.S6+S7 + §15 to be filled in
post-Trial 9 TD60 GREEN evidence.
