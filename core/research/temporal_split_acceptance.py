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
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from core.research.temporal_split import (
    TemporalSplitConfig,
    load_temporal_split,
    validation_year_set,
)
from core.research.evaluation_policy import (
    get_policy,
    is_qqq_field,
    should_demote_qqq_gate,
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


def _as_float_or_none(value: Any) -> Optional[float]:
    """Audit BUG #3 fix (2026-04-29 R1): coerce a metric value to float, or
    return None if it isn't numeric (string / dict / etc).

    bool is intentionally rejected here — concentration.leveraged_etf_dependency
    and cost.multiplier_2x_remains_positive are bool by design and consumed
    via dedicated bool gates; they should NOT be silently coerced to 0.0/1.0
    by these numeric gates.
    """
    if value is _MISSING or value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    import math as _math
    if _math.isnan(f):
        return None
    return f


def _as_bool_or_none(value: Any) -> Optional[bool]:
    """Codex R21 P0.2 fix (2026-04-29): strict bool acceptance for the
    dedicated bool gates (concentration.leveraged_etf_dependency,
    cost.multiplier_2x_remains_positive).

    Generic ``bool(value)`` is dangerous here:
      - ``bool("False")`` is True (non-empty string)
      - ``bool("ERR_NO_DATA")`` is True
      - ``bool(1)`` / ``bool(0)`` mask integer 0/1 as boolean evidence

    The cost-robustness and leverage-dependency gates are the few places
    that protect against a beautiful backtest dying in real fills. A
    string error code from upstream measurement code MUST fail closed,
    not silently coerce to True via Python truthiness.

    Audit-pass extension (2026-04-29 R-AUDIT.1): also accept ``numpy.bool_``
    since pandas/numpy reductions (``df.any()``, ``arr.all()``) return
    numpy bool, not Python bool — that's a legitimate bool type, not
    truthiness coercion. Strings, ints, floats, ndarrays, None, etc.
    remain rejected.
    """
    if value is _MISSING or value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        import numpy as _np
        if isinstance(value, _np.bool_):
            return bool(value)
    except ImportError:  # pragma: no cover
        pass
    return None


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
        excess_spy = _as_float_or_none(_resolve_metric(metrics, f"validation.{year_key}.excess_vs_spy"))
        excess_qqq = _as_float_or_none(_resolve_metric(metrics, f"validation.{year_key}.excess_vs_qqq"))
        maxdd      = _as_float_or_none(_resolve_metric(metrics, f"validation.{year_key}.maxdd"))
        if maxdd is None:
            out.append(SplitGateResult(
                name=f"validation_year_{year_key}_maxdd",
                passed=False,
                values={"missing_or_invalid": f"validation.{year_key}.maxdd"},
                threshold={"maxdd_per_year_max": maxdd_max},
                notes=f"validation year {year_key} maxdd missing or non-numeric; fail-closed",
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
                "maxdd": maxdd,
                "excess_vs_spy": excess_spy,
                "excess_vs_qqq": excess_qqq,
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
    spy_missing_years: List[int] = []
    qqq_missing_years: List[int] = []
    spy_per_year: Dict[int, Optional[float]] = {}
    qqq_per_year: Dict[int, Optional[float]] = {}
    for y in val_years:
        spy = _as_float_or_none(_resolve_metric(metrics, f"validation.{y}.excess_vs_spy"))
        qqq = _as_float_or_none(_resolve_metric(metrics, f"validation.{y}.excess_vs_qqq"))
        spy_per_year[y] = spy
        qqq_per_year[y] = qqq
        # Audit BUG #4 (2026-04-29 R1): missing/non-numeric/NaN values are
        # NOT silently treated as "not positive" — they're flagged so the
        # operator can see *why* the gate didn't accept that year. Aggregate
        # gate still requires a strict positive count; missing years cannot
        # contribute, but they're explicitly reported.
        if spy is None:
            spy_missing_years.append(y)
        elif spy > 0:
            spy_pos_count += 1
        if qqq is None:
            qqq_missing_years.append(y)
        elif qqq > 0:
            qqq_pos_count += 1

    # QQQ aggregate gate — apply BOTH yaml-level `excess_vs_qqq_diagnostic_only`
    # AND runtime policy `qqq_demote_kill_to_diagnostic`. Runtime policy
    # (config/evaluation_policy.yaml) supersedes yaml content for v1/v2
    # back-compat per P0.a (Codex 2026-05-14 governance drift fix).
    _yaml_diagnostic = vy_pass.excess_vs_qqq_diagnostic_only
    _policy_demote = should_demote_qqq_gate("validation_aggregate.excess_vs_qqq")
    _is_diagnostic_qqq = _yaml_diagnostic or _policy_demote

    return [
        SplitGateResult(
            name="validation_aggregate_excess_vs_spy",
            passed=(spy_pos_count >= vy_pass.excess_vs_spy_positive_min),
            values={"positive_count": spy_pos_count, "per_year": spy_per_year,
                    "missing_or_invalid_years": spy_missing_years},
            threshold={"min_positive_years": vy_pass.excess_vs_spy_positive_min,
                       "total_years": len(val_years)},
            notes=("missing/non-numeric: " + ",".join(str(y) for y in spy_missing_years))
                  if spy_missing_years else "",
        ),
        SplitGateResult(
            name="validation_aggregate_excess_vs_qqq",
            passed=(
                True
                if _is_diagnostic_qqq
                else (qqq_pos_count >= vy_pass.excess_vs_qqq_positive_min)
            ),
            values={
                "positive_count": qqq_pos_count, "per_year": qqq_per_year,
                "missing_or_invalid_years": qqq_missing_years,
                **(
                    {"diagnostic_actual_passed":
                        qqq_pos_count >= vy_pass.excess_vs_qqq_positive_min,
                     "diagnostic_source": (
                         "yaml_v3+policy" if (_yaml_diagnostic and _policy_demote)
                         else "yaml_v3" if _yaml_diagnostic
                         else "policy_demote"
                     )}
                    if _is_diagnostic_qqq else {}
                ),
            },
            threshold={"min_positive_years": vy_pass.excess_vs_qqq_positive_min,
                       "total_years": len(val_years),
                       "diagnostic_only": _is_diagnostic_qqq},
            notes=(
                ("diagnostic_only mode (per QQQ deprecation 2026-05-02); "
                 "does not block; ")
                if _is_diagnostic_qqq else ""
            ) + (
                "missing/non-numeric: " + ",".join(str(y) for y in qqq_missing_years)
                if qqq_missing_years else ""
            ),
        ),
    ]


def _eval_stress_slice_gates(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> List[SplitGateResult]:
    """Per-stress-slice MaxDD sanity check (does NOT participate in alpha selection)."""
    out: List[SplitGateResult] = []
    for slc in cfg.partition.stress_slices:
        maxdd = _as_float_or_none(_resolve_metric(metrics, f"stress_slice.{slc.name}.maxdd"))
        if maxdd is None:
            out.append(SplitGateResult(
                name=f"stress_slice_{slc.name}_maxdd",
                passed=False,
                values={"missing_or_invalid": f"stress_slice.{slc.name}.maxdd"},
                threshold={"maxdd_threshold": slc.maxdd_threshold},
                notes=f"stress slice {slc.name} maxdd missing or non-numeric; fail-closed",
            ))
            continue
        passed = bool(maxdd <= slc.maxdd_threshold)
        out.append(SplitGateResult(
            name=f"stress_slice_{slc.name}_maxdd",
            passed=passed,
            values={"slice": slc.name, "maxdd": maxdd,
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
        raw = _resolve_metric(metrics, gate.field)
        value = _as_float_or_none(raw)
        gate_name = f"role_{role}__{gate.field.replace('.', '__')}"
        # Apply runtime policy: demote QQQ-related kill_candidate to
        # diagnostic_only per config/evaluation_policy.yaml. Supersedes
        # yaml-level action for v1/v2 back-compat (P0.a fix).
        is_diagnostic = (
            gate.action == "diagnostic_only"
            or should_demote_qqq_gate(gate.field)
        )
        if value is None:
            # Diagnostic-only gates with missing data don't block — they
            # just record "missing". Hard gates (kill_candidate / soft_warn)
            # still fail-closed on missing.
            out.append(SplitGateResult(
                name=gate_name,
                passed=True if is_diagnostic else False,
                values={"missing_or_invalid": gate.field,
                        "raw": (None if raw is _MISSING else repr(raw)),
                        **({"diagnostic_actual_passed": False} if is_diagnostic else {})},
                threshold={"op": gate.op, "value": gate.value, "action": gate.action},
                notes=(
                    f"diagnostic gate field {gate.field} missing or non-numeric; "
                    "reported as actual_passed=False but does not block"
                    if is_diagnostic else
                    f"role gate field {gate.field} missing or non-numeric; fail-closed"
                ),
            ))
            continue
        actual_passed = _eval_op(gate.op, value, gate.value)
        out.append(SplitGateResult(
            name=gate_name,
            # Diagnostic-only: passed=True regardless; record actual outcome
            # in values.diagnostic_actual_passed for reporter / audit.
            passed=True if is_diagnostic else actual_passed,
            values={
                "role": role, "field": gate.field, "actual": value,
                **({"diagnostic_actual_passed": actual_passed} if is_diagnostic else {}),
            },
            threshold={"op": gate.op, "value": gate.value, "action": gate.action},
            notes=(
                f"diagnostic_only gate (per QQQ deprecation 2026-05-02): "
                f"actual_passed={actual_passed} but does not block candidate"
                if is_diagnostic else ""
            ),
        ))
    return out


def _eval_concentration_gates(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> List[SplitGateResult]:
    """Concentration: top1 / top3 / leveraged-ETF dependency."""
    cc = cfg.acceptance.concentration
    out: List[SplitGateResult] = []

    top1 = _as_float_or_none(_resolve_metric(metrics, "concentration.top1_max"))
    out.append(SplitGateResult(
        name="concentration_top1",
        passed=(top1 is not None and top1 <= cc.top1_max),
        values={"top1_max": top1},
        threshold={"top1_ceiling": cc.top1_max},
        notes=("missing or non-numeric → fail-closed" if top1 is None else ""),
    ))

    top3 = _as_float_or_none(_resolve_metric(metrics, "concentration.top3_max"))
    out.append(SplitGateResult(
        name="concentration_top3",
        passed=(top3 is not None and top3 <= cc.top3_max),
        values={"top3_max": top3},
        threshold={"top3_ceiling": cc.top3_max},
        notes=("missing or non-numeric → fail-closed" if top3 is None else ""),
    ))

    if cc.no_leveraged_etf_dependency:
        raw = _resolve_metric(metrics, "concentration.leveraged_etf_dependency")
        lev_dep = _as_bool_or_none(raw)
        out.append(SplitGateResult(
            name="concentration_no_leveraged_etf",
            # Codex R21 P0.2: strict bool only. None (missing or non-bool)
            # fail-closes; True (has dependency) fails; only False passes.
            passed=(lev_dep is False),
            values={"leveraged_etf_dependency": lev_dep,
                    "raw": (None if raw is _MISSING else repr(raw))},
            threshold={"required": False},
            notes=("missing or non-bool → fail-closed" if lev_dep is None else ""),
        ))
    return out


def _eval_beta_gate(
    metrics: Dict[str, Any],
    cfg: TemporalSplitConfig,
) -> SplitGateResult:
    beta = _as_float_or_none(_resolve_metric(metrics, "beta.beta_to_qqq"))
    cap = cfg.acceptance.beta.beta_to_qqq_max
    if beta is None:
        return SplitGateResult(
            name="beta_to_qqq",
            passed=False,
            values={"missing_or_invalid": "beta.beta_to_qqq"},
            threshold={"beta_to_qqq_max": cap},
            notes="beta missing or non-numeric → fail-closed (prevents QQQ-proxy candidates)",
        )
    return SplitGateResult(
        name="beta_to_qqq",
        passed=bool(beta <= cap),
        values={"beta_to_qqq": beta},
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
    raw = _resolve_metric(metrics, "cost.multiplier_2x_remains_positive")
    flag = _as_bool_or_none(raw)
    if flag is None:
        # Codex R21 P0.2: strict bool only. A string error code, "False",
        # "ERR_NO_DATA", int 1/0, or missing all fail-close. The 2x-cost
        # gate is one of the few that protects against a beautiful
        # backtest dying in real fills — Python truthiness is too loose.
        return SplitGateResult(
            name="cost_robustness_2x",
            passed=False,
            values={"missing_or_invalid": "cost.multiplier_2x_remains_positive",
                    "raw": (None if raw is _MISSING else repr(raw))},
            threshold={"required": True},
            notes="2x-cost flag missing or non-bool → fail-closed",
        )
    return SplitGateResult(
        name="cost_robustness_2x",
        passed=flag,
        values={"multiplier_2x_remains_positive": flag},
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
        raw = _resolve_metric(metrics, ec.field)
        value = _as_float_or_none(raw)
        if value is None:
            reason = "missing" if raw is _MISSING else "non-numeric"
            failures.append({"field": ec.field, "reason": reason,
                             "raw": (None if raw is _MISSING else repr(raw))})
            actuals[ec.field] = None
            continue
        actuals[ec.field] = value
        if not _eval_op(ec.op, value, ec.value):
            failures.append({"field": ec.field, "actual": value,
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
    freeze_date: Optional[date] = None,
) -> SplitAcceptanceResult:
    """Convenience driver: load split YAML + evaluate.

    When ``split_path`` is None, dispatches between v1 and v2 yaml using
    ``resolve_split_path(role, freeze_date)``: role=diversifier candidates
    frozen on/after 2026-05-01 read v2 thresholds (PRD §6.2 evidence-derived);
    everything else reads v1 (immutability for pre-PRD candidates).

    Explicit ``split_path`` always wins over dispatch (test/eval scripts
    that pin a specific yaml for reproducibility).
    """
    from pathlib import Path as _P
    from core.research.temporal_split import resolve_split_path
    if split_path:
        path = _P(split_path)
    else:
        path = resolve_split_path(role=role, freeze_date=freeze_date)
    cfg = load_temporal_split(path)
    return evaluate_candidate(metrics, cfg, role)
