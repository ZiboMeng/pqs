"""Acceptance evaluator for candidates under the temporal split framework.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.3: per-validation-year + per-stress-slice + 2025 hard gate +
role-gate aggregation. Outputs per-year + per-slice tables.

This module is the **Track A** acceptance evaluator. It is intentionally
separate from ``core/mining/acceptance_pack.py`` (the post-mining
promotion contract for already-promoted candidates, frozen by codex
round 13). They serve different governance surfaces:

  ``acceptance_pack``  — stable contract for already-promoted specs;
                         consumes archive trial rows; 10 fixed gates.
  ``temporal_split_acceptance`` (this module) — gates a Track C mining
                         result before it can become a candidate, against
                         the alternating-year split + role-locked rules
                         in ``config/temporal_split.yaml``.

The evaluator consumes a pre-computed metrics dict (Track C mining is
responsible for computing per-validation-year + per-stress-slice
backtests). It does NOT run any backtest itself — keeping Step A.3
purely a discipline / aggregation layer.

Public API
----------
- ``SplitGateResult``: dataclass mirroring acceptance_pack.GateResult.
- ``SplitAcceptanceResult``: aggregate result with per-year + per-slice
  + role-gate + cross-cutting (concentration / beta / cost) gates.
- ``evaluate_candidate(metrics, cfg, role)``: pure function;
  the inputs (metrics + cfg) determine output deterministically.
- ``check_role_eligibility(metrics, role_cfg)``: pre-flight check; a
  candidate must satisfy a role's eligibility_constraint BEFORE its
  validation gates are evaluated. (Diversifier requires
  ``vs_existing_core_correlation`` etc.)

Metrics contract
----------------
The ``metrics`` dict consumed by ``evaluate_candidate`` MUST contain:

::

    {
      "validation": {
        2018: {"excess_vs_spy": float, "excess_vs_qqq": float, "maxdd": float},
        2019: {"excess_vs_spy": float, "excess_vs_qqq": float, "maxdd": float},
        2021: ...,
        2023: ...,
        2025: ...,
      },
      "stress_slice": {
        "covid_flash":    {"maxdd": float},
        "rate_hike_2022": {"maxdd": float},
      },
      "concentration": {"top1_max": float, "top3_max": float,
                        "leveraged_etf_dependency": bool},
      "beta": {"beta_to_qqq": float},
      "cost":  {"multiplier_2x_remains_positive": bool},
      "vs_existing_core_correlation": float,    # diversifier-only
      "vs_existing_core_overlap":     float,    # diversifier-only
    }

Track C mining is the source of these metrics. This module enforces
the discipline; Track C produces the inputs.
"""
from __future__ import annotations

import operator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.research.temporal_split import (
    TemporalSplitConfig,
    load_temporal_split,
    validation_year_set,
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SplitGateResult:
    """Single gate evaluation result. Mirrors acceptance_pack.GateResult."""

    name: str
    passed: bool
    values: Dict[str, Any] = field(default_factory=dict)
    threshold: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SplitAcceptanceResult:
    """Aggregate result of evaluate_candidate across all gates."""

    role: str
    split_name: str
    gates: List[SplitGateResult]
    overall_passed: bool
    evaluated_at: str
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "split_name": self.split_name,
            "gates": [g.as_dict() for g in self.gates],
            "overall_passed": self.overall_passed,
            "evaluated_at": self.evaluated_at,
            "notes": self.notes,
        }

    def gate_named(self, name: str) -> Optional[SplitGateResult]:
        """Lookup a gate by name; returns None if absent."""
        for g in self.gates:
            if g.name == name:
                return g
        return None

    def summary_line(self) -> str:
        n_pass = sum(1 for g in self.gates if g.passed)
        return (
            f"SplitAcceptance role={self.role} split={self.split_name}: "
            f"{n_pass}/{len(self.gates)} gates passed, "
            f"overall={'PASS' if self.overall_passed else 'FAIL'}"
        )


# ---------------------------------------------------------------------------
# Operator dispatch (matches op strings used in YAML schema)
# ---------------------------------------------------------------------------


_OP_MAP = {
    ">":  operator.gt,
    ">=": operator.ge,
    "<":  operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


def _eval_op(op_str: str, lhs: float, rhs: float) -> bool:
    return _OP_MAP[op_str](lhs, rhs)


# ---------------------------------------------------------------------------
# Metrics path resolution (e.g. "validation.2025.excess_vs_qqq" → 0.03)
# ---------------------------------------------------------------------------


_MISSING = object()


def _resolve_metric(metrics: Dict[str, Any], dotted_path: str) -> Any:
    """Resolve a dotted-path metric reference like 'validation.2025.excess_vs_qqq'.

    Returns ``_MISSING`` sentinel if any intermediate key is absent. The
    caller decides whether missing = fail-closed.
    """
    cur: Any = metrics
    for part in dotted_path.split("."):
        if isinstance(cur, dict):
            try:
                key_int = int(part)
                lookup = cur.get(key_int, _MISSING)
                if lookup is _MISSING:
                    lookup = cur.get(part, _MISSING)
            except ValueError:
                lookup = cur.get(part, _MISSING)
            if lookup is _MISSING:
                return _MISSING
            cur = lookup
        else:
            return _MISSING
    return cur


# ---------------------------------------------------------------------------
# Per-year + per-slice + role gate evaluation
# ---------------------------------------------------------------------------


def _eval_per_year_gates(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> List[SplitGateResult]:
    """Per-validation-year MaxDD + diagnostic excess gates.

    For each validation year, three diagnostic values are recorded:
    excess_vs_spy, excess_vs_qqq, maxdd. The MaxDD gate is hard-pass:
    any year exceeding ``acceptance.validation_year_pass.maxdd_per_year_max``
    fails the candidate. The excess values are diagnostic only at this
    layer (aggregation handled separately by ``_eval_validation_aggregate``).
    """
    out: List[SplitGateResult] = []
    maxdd_max = cfg.acceptance.validation_year_pass.maxdd_per_year_max
    for vy in cfg.partition.validation_years:
        year_key = vy.year
        excess_spy = _resolve_metric(metrics, f"validation.{year_key}.excess_vs_spy")
        excess_qqq = _resolve_metric(metrics, f"validation.{year_key}.excess_vs_qqq")
        maxdd      = _resolve_metric(metrics, f"validation.{year_key}.maxdd")
        if maxdd is _MISSING:
            out.append(SplitGateResult(
                name=f"validation_year_{year_key}_maxdd",
                passed=False,
                values={"missing": "validation.{}.maxdd".format(year_key)},
                threshold={"maxdd_per_year_max": maxdd_max},
                notes=f"validation year {year_key} maxdd missing in metrics; fail-closed",
            ))
            continue
        passed = bool(maxdd <= maxdd_max)
        out.append(SplitGateResult(
            name=f"validation_year_{year_key}_maxdd",
            passed=passed,
            values={
                "year": year_key,
                "regime": vy.manual_regime_tag,
                "weight": vy.weight,
                "maxdd": float(maxdd),
                "excess_vs_spy": (None if excess_spy is _MISSING else float(excess_spy)),
                "excess_vs_qqq": (None if excess_qqq is _MISSING else float(excess_qqq)),
            },
            threshold={"maxdd_per_year_max": maxdd_max},
        ))
    return out


def _eval_validation_aggregate(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> List[SplitGateResult]:
    """Aggregate validation: ≥N years with positive excess vs SPY / QQQ."""
    vy_pass = cfg.acceptance.validation_year_pass
    val_years = sorted(validation_year_set(cfg))

    spy_pos_count = 0
    qqq_pos_count = 0
    spy_per_year: Dict[int, Optional[float]] = {}
    qqq_per_year: Dict[int, Optional[float]] = {}
    for y in val_years:
        spy = _resolve_metric(metrics, f"validation.{y}.excess_vs_spy")
        qqq = _resolve_metric(metrics, f"validation.{y}.excess_vs_qqq")
        spy_per_year[y] = (None if spy is _MISSING else float(spy))
        qqq_per_year[y] = (None if qqq is _MISSING else float(qqq))
        if spy is not _MISSING and float(spy) > 0:
            spy_pos_count += 1
        if qqq is not _MISSING and float(qqq) > 0:
            qqq_pos_count += 1

    return [
        SplitGateResult(
            name="validation_aggregate_excess_vs_spy",
            passed=(spy_pos_count >= vy_pass.excess_vs_spy_positive_min),
            values={"positive_count": spy_pos_count, "per_year": spy_per_year},
            threshold={"min_positive_years": vy_pass.excess_vs_spy_positive_min,
                       "total_years": len(val_years)},
        ),
        SplitGateResult(
            name="validation_aggregate_excess_vs_qqq",
            passed=(qqq_pos_count >= vy_pass.excess_vs_qqq_positive_min),
            values={"positive_count": qqq_pos_count, "per_year": qqq_per_year},
            threshold={"min_positive_years": vy_pass.excess_vs_qqq_positive_min,
                       "total_years": len(val_years)},
        ),
    ]


def _eval_stress_slice_gates(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> List[SplitGateResult]:
    """Per-stress-slice MaxDD sanity check (does NOT participate in alpha selection)."""
    out: List[SplitGateResult] = []
    for slc in cfg.partition.stress_slices:
        maxdd = _resolve_metric(metrics, f"stress_slice.{slc.name}.maxdd")
        if maxdd is _MISSING:
            out.append(SplitGateResult(
                name=f"stress_slice_{slc.name}_maxdd",
                passed=False,
                values={"missing": f"stress_slice.{slc.name}.maxdd"},
                threshold={"maxdd_threshold": slc.maxdd_threshold},
                notes=f"stress slice {slc.name} maxdd missing; fail-closed",
            ))
            continue
        passed = bool(maxdd <= slc.maxdd_threshold)
        out.append(SplitGateResult(
            name=f"stress_slice_{slc.name}_maxdd",
            passed=passed,
            values={"slice": slc.name, "maxdd": float(maxdd),
                    "source_year": slc.source_year, "mode": slc.mode},
            threshold={"maxdd_threshold": slc.maxdd_threshold},
        ))
    return out


def _eval_role_gates(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
    role: str,
) -> List[SplitGateResult]:
    """Role-locked validation gates (M2 2025 hard gate + M6 role weakening).

    Each gate's ``field`` references a metrics dotted path; gate fails
    when the comparison ``metric op value`` returns False (e.g. core's
    ``validation.2025.excess_vs_qqq > 0.0`` fails when value <= 0).
    Missing metrics are fail-closed: the candidate cannot pass a role
    gate whose value cannot be computed.
    """
    out: List[SplitGateResult] = []
    role_cfg = cfg.roles[role]
    for gate in role_cfg.validation_gates:
        value = _resolve_metric(metrics, gate.field)
        gate_name = f"role_{role}__{gate.field.replace('.', '__')}"
        if value is _MISSING:
            out.append(SplitGateResult(
                name=gate_name,
                passed=False,
                values={"missing": gate.field},
                threshold={"op": gate.op, "value": gate.value},
                notes=f"role gate field {gate.field} missing in metrics; fail-closed",
            ))
            continue
        passed = _eval_op(gate.op, float(value), gate.value)
        out.append(SplitGateResult(
            name=gate_name,
            passed=passed,
            values={"role": role, "field": gate.field, "actual": float(value)},
            threshold={"op": gate.op, "value": gate.value, "action": gate.action},
        ))
    return out


def _eval_concentration_gates(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> List[SplitGateResult]:
    """Concentration: top1 / top3 / leveraged-ETF dependency."""
    cc = cfg.acceptance.concentration
    out: List[SplitGateResult] = []

    top1 = _resolve_metric(metrics, "concentration.top1_max")
    out.append(SplitGateResult(
        name="concentration_top1",
        passed=(top1 is not _MISSING and float(top1) <= cc.top1_max),
        values={"top1_max": (None if top1 is _MISSING else float(top1))},
        threshold={"top1_ceiling": cc.top1_max},
        notes=("missing metric → fail-closed" if top1 is _MISSING else ""),
    ))

    top3 = _resolve_metric(metrics, "concentration.top3_max")
    out.append(SplitGateResult(
        name="concentration_top3",
        passed=(top3 is not _MISSING and float(top3) <= cc.top3_max),
        values={"top3_max": (None if top3 is _MISSING else float(top3))},
        threshold={"top3_ceiling": cc.top3_max},
        notes=("missing metric → fail-closed" if top3 is _MISSING else ""),
    ))

    if cc.no_leveraged_etf_dependency:
        lev_dep = _resolve_metric(metrics, "concentration.leveraged_etf_dependency")
        out.append(SplitGateResult(
            name="concentration_no_leveraged_etf",
            passed=(lev_dep is not _MISSING and not bool(lev_dep)),
            values={"leveraged_etf_dependency": (None if lev_dep is _MISSING else bool(lev_dep))},
            threshold={"required": False},
            notes=("missing metric → fail-closed" if lev_dep is _MISSING else ""),
        ))
    return out


def _eval_beta_gate(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> SplitGateResult:
    beta = _resolve_metric(metrics, "beta.beta_to_qqq")
    cap = cfg.acceptance.beta.beta_to_qqq_max
    if beta is _MISSING:
        return SplitGateResult(
            name="beta_to_qqq",
            passed=False,
            values={"missing": "beta.beta_to_qqq"},
            threshold={"beta_to_qqq_max": cap},
            notes="beta missing → fail-closed (prevents QQQ-proxy candidates)",
        )
    return SplitGateResult(
        name="beta_to_qqq",
        passed=bool(float(beta) <= cap),
        values={"beta_to_qqq": float(beta)},
        threshold={"beta_to_qqq_max": cap},
    )


def _eval_cost_gate(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> SplitGateResult:
    if not cfg.acceptance.cost_robustness.multiplier_2x_must_remain_positive:
        return SplitGateResult(
            name="cost_robustness_2x",
            passed=True,
            values={},
            threshold={},
            notes="2x cost robustness gate disabled by config",
        )
    flag = _resolve_metric(metrics, "cost.multiplier_2x_remains_positive")
    if flag is _MISSING:
        return SplitGateResult(
            name="cost_robustness_2x",
            passed=False,
            values={"missing": "cost.multiplier_2x_remains_positive"},
            threshold={"required": True},
            notes="2x-cost flag missing → fail-closed",
        )
    return SplitGateResult(
        name="cost_robustness_2x",
        passed=bool(flag),
        values={"multiplier_2x_remains_positive": bool(flag)},
        threshold={"required": True},
    )


# ---------------------------------------------------------------------------
# Eligibility (M6 C3): a role's eligibility_constraint must hold BEFORE
# validation gates apply. Diversifier requires correlation/overlap to an
# existing core; failed eligibility means candidate cannot use this role.
# ---------------------------------------------------------------------------


def check_role_eligibility(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
    role: str,
) -> SplitGateResult:
    """Pre-flight: verify candidate satisfies role's eligibility_constraint.

    Empty constraint list (e.g. ``core``) → automatic pass.
    Any unsatisfied constraint → fail; the candidate cannot enter that role.
    """
    role_cfg = cfg.roles[role]
    failures: List[Dict[str, Any]] = []
    actuals: Dict[str, Any] = {}
    for ec in role_cfg.eligibility_constraint:
        value = _resolve_metric(metrics, ec.field)
        if value is _MISSING:
            failures.append({"field": ec.field, "reason": "missing"})
            actuals[ec.field] = None
            continue
        actuals[ec.field] = float(value)
        if not _eval_op(ec.op, float(value), ec.value):
            failures.append({"field": ec.field, "actual": float(value),
                             "op": ec.op, "required": ec.value})
    return SplitGateResult(
        name=f"role_{role}_eligibility",
        passed=(len(failures) == 0),
        values={"actuals": actuals, "failures": failures},
        threshold={"constraints": [ec.model_dump() for ec in role_cfg.eligibility_constraint]},
        notes=("eligibility passes (no constraints)"
               if not role_cfg.eligibility_constraint
               else f"{len(failures)} eligibility failure(s)"),
    )


# ---------------------------------------------------------------------------
# Public API: full evaluation
# ---------------------------------------------------------------------------


def evaluate_candidate(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
    role: str,
) -> SplitAcceptanceResult:
    """Evaluate a candidate's metrics against the temporal split's gates.

    Order of evaluation:
      1. Role eligibility (M6 C3).
      2. Per-year MaxDD (5 gates, one per validation year).
      3. Validation aggregate (≥N positive vs SPY / QQQ; 2 gates).
      4. Stress slice MaxDD (2 gates, sanity check only).
      5. Role-locked validation gates (M2 2025 hard gate; 2 gates per role).
      6. Cross-cutting: concentration (2-3 gates), beta (1), cost (1).

    overall_passed = AND over all gates. Eligibility failure short-
    circuits all role gates: the candidate cannot use this role.
    """
    if role not in cfg.roles:
        raise ValueError(f"role {role!r} not declared in split {cfg.split_name!r}; "
                         f"available: {sorted(cfg.roles.keys())}")

    gates: List[SplitGateResult] = []

    elig = check_role_eligibility(metrics, cfg, role)
    gates.append(elig)

    gates.extend(_eval_per_year_gates(metrics, cfg))
    gates.extend(_eval_validation_aggregate(metrics, cfg))
    gates.extend(_eval_stress_slice_gates(metrics, cfg))
    gates.extend(_eval_role_gates(metrics, cfg, role))
    gates.extend(_eval_concentration_gates(metrics, cfg))
    gates.append(_eval_beta_gate(metrics, cfg))
    gates.append(_eval_cost_gate(metrics, cfg))

    return SplitAcceptanceResult(
        role=role,
        split_name=cfg.split_name,
        gates=gates,
        overall_passed=all(g.passed for g in gates),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        notes=(
            "Track A v1 acceptance evaluator. Reads metrics dict produced "
            "by Track C mining; does NOT run any backtest. Eligibility, "
            "per-year, aggregate, stress, role-gate, concentration, beta, "
            "and cost gates are AND-composed."
        ),
    )


def run_split_acceptance(
    metrics: Dict[str, Any],
    role: str,
    split_path: Optional[str] = None,
) -> SplitAcceptanceResult:
    """Convenience driver: load split YAML + evaluate."""
    from pathlib import Path as _P
    cfg = load_temporal_split(_P(split_path) if split_path else None)
    return evaluate_candidate(metrics, cfg, role)
