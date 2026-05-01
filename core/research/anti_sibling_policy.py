"""Anti-sibling policy for R41 5-tier classification (cycle #05+).

POLICY_VERSION = 'v2.0_conditional_review_2026-05-01'

Pre-registered conditional-review thresholds for factor-overlap=2 with
legacy/historical anchors. **NOT applied retroactively to cycle #04**
(data dredging). Effective from cycle #05 (track-c-cycle-2026-05-01-05).

Anchor status taxonomy:
- ``active_core``: promoted via Track A acceptance + currently in fleet.
  Strictest gating — overlap >= 2 hard-rejects with no conditional review path.
  (Empty as of 2026-05-01; no candidate has been promoted via the
  current-framework acceptance.)
- ``active_legacy_decay``: RCMv1 + Cand-2. Pre-G2.A 30% concentration ceiling +
  pre-M12 weighted thin-data fix. Forward-observed in decay-verification
  mode only; not eligible for new-framework promotion. Conditional review
  PATH eligible at overlap = 2 (sibling-by-factor signal weakened by
  legacy status).
- ``historical_failed``: cycle 01/02/03 top trials. Failed prior acceptance.
  Conditional review eligible at overlap = 2 (these are not deployed, so
  factor-overlap with them is informational not operational).

Tier definitions:
- Tier 1: ``non-sibling`` — max(factor_overlap) < 2 AND
          max(raw_NAV) < 0.85 AND max(residual_NAV) < 0.70.
- Tier 1-conditional: factor_overlap = 2 with a non-active anchor AND all of:
  * raw_NAV vs that anchor < 0.70 (strictly tighter than tier-2's 0.85)
  * residual_NAV vs SPY+QQQ stripping < 0.50 (strictly tighter than 0.70)
  * MaxDD strictly better than that anchor's MaxDD on shared window
  * 2025 vs_qqq strict pass (excess > 0; soft-miss does NOT qualify)
- Tier 2: ``sibling`` — failed any of the above:
  * factor_overlap >= 3 with anyone, OR
  * factor_overlap = 2 with an ``active_core`` anchor, OR
  * factor_overlap = 2 with non-active anchor + conditional review failed, OR
  * raw_NAV >= 0.85 (sibling-by-NAV) regardless of factor overlap, OR
  * residual_NAV >= 0.70 (sibling-by-NAV-residual) regardless of factor overlap.
- Tier 5: non-evaluable (NaN cum_ret).

Operator rationale (cycle #04 closeout 2026-05-01):
The pre-#05 binary rule (factor_overlap >= 2 → Tier 2) was a coarse
pre-NAV gate. Cycle #04 Cluster A trial 8 (factor_overlap = 2 with RCMv1)
demonstrated raw_NAV ~0.66-0.70 + residual_NAV positive Sharpe + 2025
strict pass — strong NAV evidence overriding factor-overlap signal.
Conditional review path captures that case formally with PRE-REGISTERED
thresholds. Active-core overlap remains hard reject because deployed
alpha cannot be partially shadowed.

Governance:
- POLICY_VERSION must increment on any threshold change.
- Yaml `anti_sibling_policy_version` field MUST match POLICY_VERSION at
  evaluation time, else raise.
- Active-core anchor list change requires Track A acceptance promotion +
  CLAUDE.md inventory update. Module is read-only for that list at runtime.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple


POLICY_VERSION = "v2.0_conditional_review_2026-05-01"


# ─── Anchor status registry (compile-time constants) ────────────────────


# Active core: candidates promoted via Track A acceptance and currently
# deployed in fleet. Empty as of 2026-05-01.
ACTIVE_CORE_ANCHORS: Tuple[str, ...] = ()


# Active legacy-decay: nominated pre-G2.A + pre-M12-fix; forward-observed
# in decay-verification mode only. Not eligible for new-framework promotion.
ACTIVE_LEGACY_DECAY_ANCHORS: Tuple[str, ...] = ("rcm_v1", "cand_2")


# Historical failed: top trials from prior cycles that failed acceptance.
HISTORICAL_FAILED_ANCHORS: Tuple[str, ...] = (
    "cycle_01_top",
    "cycle_02_top",
    "cycle_03_top",
)


def get_anchor_status(anchor_name: str) -> str:
    """Return one of ``active_core`` / ``active_legacy_decay`` /
    ``historical_failed`` / ``unknown``.

    Active-core anchors are subject to strictest gating; the other two
    categories are eligible for conditional review at factor_overlap = 2.
    """
    if anchor_name in ACTIVE_CORE_ANCHORS:
        return "active_core"
    if anchor_name in ACTIVE_LEGACY_DECAY_ANCHORS:
        return "active_legacy_decay"
    if anchor_name in HISTORICAL_FAILED_ANCHORS:
        return "historical_failed"
    return "unknown"


# ─── Threshold constants (PRE-REGISTERED) ───────────────────────────────


# Tier 2 sibling thresholds (raw / residual NAV correlation pooled Pearson)
TIER2_RAW_NAV_PEARSON_MAX: float = 0.85
TIER2_RESIDUAL_NAV_PEARSON_MAX: float = 0.70


# Tier 1-conditional thresholds (strictly tighter than tier-2 floor)
COND_RAW_NAV_PEARSON_MAX: float = 0.70
COND_RESIDUAL_NAV_PEARSON_MAX: float = 0.50


# Factor-overlap thresholds
FACTOR_OVERLAP_HARD_REJECT: int = 3   # >= 3 with anyone → Tier 2
FACTOR_OVERLAP_CONDITIONAL: int = 2   # == 2 routes via conditional review
FACTOR_OVERLAP_TIER1_MAX: int = 1     # <= 1 considered non-sibling on factor axis


# ─── Result type ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class R41Result:
    """Structured R41 classification output.

    ``tier`` ∈ {1, "1-conditional", 2, 5}; tier 1-conditional is encoded
    as the string ``"1-conditional"`` to be JSON-serializable as-is and
    surface clearly in reports.

    ``policy_version`` MUST be propagated to JSON eval output for audit.
    """

    tier: object  # int or "1-conditional"
    reason: str
    factor_overlap_max: int
    factor_overlaps_per_anchor: Dict[str, int]
    raw_pearson_max: Optional[float]
    residual_pearson_max: Optional[float]
    sibling_by_factor_anchor: Optional[str]
    sibling_by_nav_anchor: Optional[str]
    conditional_review_details: Optional[Dict[str, object]]
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> Dict[str, object]:
        return {
            "tier": self.tier,
            "reason": self.reason,
            "factor_overlap_max": self.factor_overlap_max,
            "factor_overlaps_per_anchor": dict(self.factor_overlaps_per_anchor),
            "raw_pearson_max": self.raw_pearson_max,
            "residual_pearson_max": self.residual_pearson_max,
            "sibling_by_factor_anchor": self.sibling_by_factor_anchor,
            "sibling_by_nav_anchor": self.sibling_by_nav_anchor,
            "conditional_review_details": self.conditional_review_details,
            "policy_version": self.policy_version,
        }


# ─── Helpers ────────────────────────────────────────────────────────────


def _is_finite(x) -> bool:
    if x is None:
        return False
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _pearson_for_anchor(
    nav_corr: Mapping[str, object], anchor: str, key_suffix: str
) -> Optional[float]:
    """Pull pooled-pearson value for an anchor; None if missing/non-finite."""
    v = nav_corr.get(f"{anchor}_pooled_pearson_{key_suffix}")
    if not _is_finite(v):
        return None
    return float(v)


def _max_residual_across_benchmarks(
    nav_corr: Mapping[str, object], anchor: str
) -> Optional[float]:
    """Residual is computed vs SPY and vs QQQ separately; take max for
    sibling determination — this is the worst-case residual co-movement."""
    cands = []
    for suf in ("residual_vs_spy", "residual_vs_qqq"):
        v = _pearson_for_anchor(nav_corr, anchor, suf)
        if v is not None:
            cands.append(v)
    return max(cands) if cands else None


# ─── Conditional review evaluation ──────────────────────────────────────


def _evaluate_conditional_review(
    anchor: str,
    candidate_max_dd: Optional[float],
    anchor_max_dd: Optional[float],
    candidate_2025_excess_qqq: Optional[float],
    raw_nav: Optional[float],
    residual_nav: Optional[float],
) -> Tuple[bool, Dict[str, object]]:
    """Return (passes_conditional_review, details).

    All four conditions must hold:
    1. raw_nav < COND_RAW_NAV_PEARSON_MAX (0.70)
    2. residual_nav < COND_RESIDUAL_NAV_PEARSON_MAX (0.50)
    3. candidate_max_dd strictly better (less negative) than anchor_max_dd
    4. candidate_2025_excess_qqq > 0 (strict pass)

    Each condition reported individually so closeout audit can trace which
    one(s) failed.
    """
    checks: Dict[str, object] = {}

    # 1. raw NAV
    if raw_nav is None:
        c1 = False
        checks["c1_raw_nav"] = {"value": None, "threshold": COND_RAW_NAV_PEARSON_MAX,
                                "pass": False, "note": "missing"}
    else:
        c1 = raw_nav < COND_RAW_NAV_PEARSON_MAX
        checks["c1_raw_nav"] = {"value": raw_nav, "threshold": COND_RAW_NAV_PEARSON_MAX,
                                "pass": c1}

    # 2. residual NAV
    if residual_nav is None:
        c2 = False
        checks["c2_residual_nav"] = {"value": None, "threshold": COND_RESIDUAL_NAV_PEARSON_MAX,
                                     "pass": False, "note": "missing"}
    else:
        c2 = residual_nav < COND_RESIDUAL_NAV_PEARSON_MAX
        checks["c2_residual_nav"] = {"value": residual_nav,
                                     "threshold": COND_RESIDUAL_NAV_PEARSON_MAX, "pass": c2}

    # 3. MaxDD strictly better
    if not _is_finite(candidate_max_dd) or not _is_finite(anchor_max_dd):
        c3 = False
        checks["c3_max_dd_strictly_better"] = {
            "candidate_max_dd": candidate_max_dd, "anchor_max_dd": anchor_max_dd,
            "pass": False, "note": "missing one or both",
        }
    else:
        # max_dd is negative; "strictly better" = less negative (greater value)
        c3 = float(candidate_max_dd) > float(anchor_max_dd)
        checks["c3_max_dd_strictly_better"] = {
            "candidate_max_dd": float(candidate_max_dd),
            "anchor_max_dd": float(anchor_max_dd), "pass": c3,
        }

    # 4. 2025 vs_qqq strict pass
    if not _is_finite(candidate_2025_excess_qqq):
        c4 = False
        checks["c4_2025_qqq_strict_pass"] = {
            "value": candidate_2025_excess_qqq, "threshold": 0.0,
            "pass": False, "note": "missing",
        }
    else:
        c4 = float(candidate_2025_excess_qqq) > 0.0
        checks["c4_2025_qqq_strict_pass"] = {
            "value": float(candidate_2025_excess_qqq), "threshold": 0.0, "pass": c4,
        }

    passes = c1 and c2 and c3 and c4
    return passes, {"anchor": anchor, "checks": checks, "all_pass": passes}


# ─── Main classifier ────────────────────────────────────────────────────


def classify(
    candidate_features: List[str],
    anchor_features: Mapping[str, List[str]],
    nav_correlation: Mapping[str, object],
    candidate_metrics_full_period: Mapping[str, object],
    candidate_metrics_2025: Optional[Mapping[str, object]],
    anchor_max_dd_lookup: Optional[Mapping[str, float]] = None,
) -> R41Result:
    """Classify a candidate into R41 tier per POLICY_VERSION.

    Args:
        candidate_features: this candidate's factor list.
        anchor_features: dict {anchor_name: [factor_names]} for each known
            anchor (cycle 01/02/03 top, RCMv1, Cand-2, future active core).
        nav_correlation: dict with keys ``{anchor}_pooled_pearson_{raw,
            residual_vs_spy, residual_vs_qqq, n_overlap_days}``. Same schema
            as cycle04 evaluator.
        candidate_metrics_full_period: candidate's full-period metrics
            (must have ``cum_ret`` for evaluability check; ``max_dd`` for
            conditional review).
        candidate_metrics_2025: candidate's 2025 validation-year metrics
            (must have ``vs_qqq`` for conditional review). May be None
            if candidate has no 2025 data — that auto-fails c4.
        anchor_max_dd_lookup: optional ``{anchor: max_dd}`` for conditional
            review c3. Anchors not present yield c3 fail. None means no
            conditional review can pass (degenerate strict mode).

    Returns:
        R41Result with all fields populated.
    """
    feats = set(candidate_features)
    overlaps: Dict[str, int] = {
        name: len(feats & set(fac_list)) for name, fac_list in anchor_features.items()
    }
    max_overlap = max(overlaps.values()) if overlaps else 0
    overlap_anchor = max(overlaps, key=overlaps.get) if overlaps else None

    # NAV correlation aggregates
    raw_per_anchor: Dict[str, float] = {}
    residual_per_anchor: Dict[str, float] = {}
    for name in anchor_features.keys():
        rv = _pearson_for_anchor(nav_correlation, name, "raw")
        if rv is not None:
            raw_per_anchor[name] = rv
        rs = _max_residual_across_benchmarks(nav_correlation, name)
        if rs is not None:
            residual_per_anchor[name] = rs

    raw_max = max(raw_per_anchor.values()) if raw_per_anchor else None
    residual_max = max(residual_per_anchor.values()) if residual_per_anchor else None

    # Tier 5 evaluability check
    cum_ret = candidate_metrics_full_period.get("cum_ret") \
        if candidate_metrics_full_period else None
    if not _is_finite(cum_ret):
        return R41Result(
            tier=5, reason="non-evaluable cum_ret",
            factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
            raw_pearson_max=raw_max, residual_pearson_max=residual_max,
            sibling_by_factor_anchor=None, sibling_by_nav_anchor=None,
            conditional_review_details=None,
        )

    # Tier 2 by NAV (raw or residual exceed sibling thresholds; bypasses
    # factor overlap entirely — NAV evidence is the dispositive signal).
    nav_sibling_anchor = None
    nav_sibling_reason_parts = []
    if raw_max is not None and raw_max >= TIER2_RAW_NAV_PEARSON_MAX:
        nav_sibling_anchor = max(raw_per_anchor, key=raw_per_anchor.get)
        nav_sibling_reason_parts.append(
            f"raw_pearson max={raw_max:.3f} (anchor={nav_sibling_anchor}) "
            f">= {TIER2_RAW_NAV_PEARSON_MAX}"
        )
    if residual_max is not None and residual_max >= TIER2_RESIDUAL_NAV_PEARSON_MAX:
        if nav_sibling_anchor is None:
            nav_sibling_anchor = max(residual_per_anchor, key=residual_per_anchor.get)
        nav_sibling_reason_parts.append(
            f"residual_pearson max={residual_max:.3f} >= {TIER2_RESIDUAL_NAV_PEARSON_MAX}"
        )
    if nav_sibling_anchor is not None:
        return R41Result(
            tier=2, reason="sibling-by-NAV: " + "; ".join(nav_sibling_reason_parts),
            factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
            raw_pearson_max=raw_max, residual_pearson_max=residual_max,
            sibling_by_factor_anchor=None, sibling_by_nav_anchor=nav_sibling_anchor,
            conditional_review_details=None,
        )

    # Factor-overlap dispatch
    if max_overlap >= FACTOR_OVERLAP_HARD_REJECT:
        return R41Result(
            tier=2,
            reason=f"sibling-by-factor: overlap={max_overlap} (anchor={overlap_anchor}) "
                   f">= {FACTOR_OVERLAP_HARD_REJECT} hard-reject",
            factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
            raw_pearson_max=raw_max, residual_pearson_max=residual_max,
            sibling_by_factor_anchor=overlap_anchor, sibling_by_nav_anchor=None,
            conditional_review_details=None,
        )

    if max_overlap == FACTOR_OVERLAP_CONDITIONAL:
        # If ANY anchor with overlap=2 is active_core, hard reject.
        # Active core requires strict orthogonality regardless of which other
        # anchors also tie at overlap=2. Scan first; pick a routing anchor only
        # after the active_core check.
        active_core_overlap2 = [
            name for name, ov in overlaps.items()
            if ov == FACTOR_OVERLAP_CONDITIONAL and get_anchor_status(name) == "active_core"
        ]
        if active_core_overlap2:
            ac_anchor = active_core_overlap2[0]
            return R41Result(
                tier=2,
                reason=f"sibling-by-factor: overlap=2 with active_core "
                       f"anchor={ac_anchor} hard-reject "
                       f"(active core requires strict orthogonality)",
                factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
                raw_pearson_max=raw_max, residual_pearson_max=residual_max,
                sibling_by_factor_anchor=ac_anchor, sibling_by_nav_anchor=None,
                conditional_review_details=None,
            )

        # Conditional review path (active_legacy_decay or historical_failed).
        # Pick the anchor with overlap=2 that yields the WORST conditional
        # review evidence (worst raw_NAV first, then worst residual). This
        # ensures a candidate routed via conditional review is judged against
        # the most adversarial overlap-2 anchor it has, not an arbitrary one.
        candidates_overlap2 = [n for n, ov in overlaps.items()
                               if ov == FACTOR_OVERLAP_CONDITIONAL]
        # Sort: highest raw_pearson first (worst evidence); None pearson sorts last
        candidates_overlap2.sort(
            key=lambda n: (raw_per_anchor.get(n) is None,
                           -(raw_per_anchor.get(n) or 0.0))
        )
        overlap_anchor = candidates_overlap2[0]
        anchor_status = get_anchor_status(overlap_anchor)

        anchor_max_dd = (
            (anchor_max_dd_lookup or {}).get(overlap_anchor)
            if anchor_max_dd_lookup else None
        )
        cand_max_dd = candidate_metrics_full_period.get("max_dd")
        cand_2025_excess_qqq = (
            candidate_metrics_2025.get("vs_qqq") if candidate_metrics_2025 else None
        )
        raw_for_anchor = raw_per_anchor.get(overlap_anchor)
        residual_for_anchor = residual_per_anchor.get(overlap_anchor)
        passes, details = _evaluate_conditional_review(
            anchor=overlap_anchor,
            candidate_max_dd=cand_max_dd,
            anchor_max_dd=anchor_max_dd,
            candidate_2025_excess_qqq=cand_2025_excess_qqq,
            raw_nav=raw_for_anchor,
            residual_nav=residual_for_anchor,
        )
        details["anchor_status"] = anchor_status

        if passes:
            return R41Result(
                tier="1-conditional",
                reason=f"factor-overlap=2 with non-active anchor={overlap_anchor} "
                       f"({anchor_status}) PASSED conditional review",
                factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
                raw_pearson_max=raw_max, residual_pearson_max=residual_max,
                sibling_by_factor_anchor=overlap_anchor, sibling_by_nav_anchor=None,
                conditional_review_details=details,
            )
        else:
            failed_checks = [k for k, v in details["checks"].items()
                             if isinstance(v, dict) and not v.get("pass")]
            return R41Result(
                tier=2,
                reason=f"sibling-by-factor: overlap=2 with anchor={overlap_anchor} "
                       f"({anchor_status}); conditional review FAILED on "
                       f"{', '.join(failed_checks)}",
                factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
                raw_pearson_max=raw_max, residual_pearson_max=residual_max,
                sibling_by_factor_anchor=overlap_anchor, sibling_by_nav_anchor=None,
                conditional_review_details=details,
            )

    # Tier 1 default: max_overlap <= 1, NAV below sibling thresholds
    return R41Result(
        tier=1, reason="non-sibling pending Track A acceptance verification",
        factor_overlap_max=max_overlap, factor_overlaps_per_anchor=overlaps,
        raw_pearson_max=raw_max, residual_pearson_max=residual_max,
        sibling_by_factor_anchor=None, sibling_by_nav_anchor=None,
        conditional_review_details=None,
    )


def assert_policy_version_matches(yaml_declared_version: str) -> None:
    """Yaml must declare ``anti_sibling_policy_version: <POLICY_VERSION>``
    matching this module's POLICY_VERSION at evaluation time."""
    if yaml_declared_version != POLICY_VERSION:
        raise ValueError(
            f"Yaml anti_sibling_policy_version={yaml_declared_version!r} does "
            f"not match anti_sibling_policy.POLICY_VERSION={POLICY_VERSION!r}. "
            f"This guards against silent threshold drift between yaml + module."
        )
