"""Tests for core.research.temporal_split_acceptance.

PRD: docs/prd/20260429-temporal_split_holdout_discipline_prd.md (v1.1)
Step A.3 — per-validation-year + per-stress-slice + 2025 hard gate +
role-gate aggregation. Acceptance criteria #4 (2025 hard gate kills
candidate that passes 2018/2019/2021/2023 but fails 2025), #5 (stress
slices independent), #11 (production-behavior yaml-swap).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from core.research.temporal_split import load_temporal_split
from core.research.temporal_split_acceptance import (
    check_role_eligibility,
    evaluate_candidate,
    run_split_acceptance,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_YAML = REPO_ROOT / "config" / "temporal_split.yaml"


# ---------------------------------------------------------------------------
# Synthetic metrics builder — produces a "passing core" candidate by default
# ---------------------------------------------------------------------------


def _passing_core_metrics() -> dict:
    """A metrics dict that passes ALL core-role gates."""
    return {
        "validation": {
            2018: {"excess_vs_spy": 0.02, "excess_vs_qqq": 0.01,  "maxdd": 0.18},
            2019: {"excess_vs_spy": 0.04, "excess_vs_qqq": 0.02,  "maxdd": 0.10},
            2021: {"excess_vs_spy": 0.03, "excess_vs_qqq": 0.01,  "maxdd": 0.12},
            2023: {"excess_vs_spy": 0.06, "excess_vs_qqq": 0.03,  "maxdd": 0.15},
            2025: {"excess_vs_spy": 0.05, "excess_vs_qqq": 0.02,  "maxdd": 0.14},
        },
        "stress_slice": {
            "covid_flash":    {"maxdd": 0.22},
            "rate_hike_2022": {"maxdd": 0.18},
        },
        "concentration": {"top1_max": 0.30, "top3_max": 0.55,
                          "leveraged_etf_dependency": False},
        "beta":  {"beta_to_qqq": 0.70},
        "cost":  {"multiplier_2x_remains_positive": True},
        # Diversifier-only fields (ignored when role=core):
        "vs_existing_core_correlation": 0.20,
        "vs_existing_core_overlap":     0.15,
    }


# ---------------------------------------------------------------------------
# Happy path: passing core candidate
# ---------------------------------------------------------------------------


def test_passing_core_candidate_passes_overall():
    cfg = load_temporal_split()
    res = evaluate_candidate(_passing_core_metrics(), cfg, "core")
    assert res.overall_passed
    assert res.role == "core"
    assert res.split_name == "alternating_regime_holdout_v1"
    # Eligibility + 5 per-year + 2 aggregate + 2 stress + 2 role + 3 concentration + 1 beta + 1 cost = 17
    assert len(res.gates) == 17


def test_passing_core_candidate_summary_format():
    cfg = load_temporal_split()
    res = evaluate_candidate(_passing_core_metrics(), cfg, "core")
    summary = res.summary_line()
    assert "PASS" in summary
    assert "17/17" in summary


# ---------------------------------------------------------------------------
# PRD acceptance test #4 — 2025 single-year hard gate
# ---------------------------------------------------------------------------


def test_2025_hard_gate_kills_when_qqq_excess_negative():
    """Codex R20 + M2: passes 2018/2019/2021/2023 but fails 2025 vs-qqq → kill."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["excess_vs_qqq"] = -0.01
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    role_gate = res.gate_named("role_core__validation__2025__excess_vs_qqq")
    assert role_gate is not None
    assert not role_gate.passed
    # Other validation years' MaxDD gates should still pass (only the 2025
    # role gate failed):
    for y in (2018, 2019, 2021, 2023):
        gate = res.gate_named(f"validation_year_{y}_maxdd")
        assert gate is not None and gate.passed


def test_2025_hard_gate_kills_when_maxdd_too_high():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["maxdd"] = 0.25  # > core 0.20 ceiling
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    # Both the per-year MaxDD AND the role-locked MaxDD gate fail:
    py_gate = res.gate_named("validation_year_2025_maxdd")
    role_gate = res.gate_named("role_core__validation__2025__maxdd")
    assert py_gate is not None and not py_gate.passed
    assert role_gate is not None and not role_gate.passed


def test_2025_hard_gate_active_only_for_core_role_qqq_threshold():
    """Diversifier role allows excess_vs_qqq down to -0.05."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["excess_vs_qqq"] = -0.03  # within diversifier band
    # Core: fails
    res_core = evaluate_candidate(metrics, cfg, "core")
    role_gate_core = res_core.gate_named("role_core__validation__2025__excess_vs_qqq")
    assert not role_gate_core.passed
    # Diversifier: passes (-0.03 > -0.05)
    res_div = evaluate_candidate(metrics, cfg, "diversifier")
    role_gate_div = res_div.gate_named("role_diversifier__validation__2025__excess_vs_qqq")
    assert role_gate_div.passed


# ---------------------------------------------------------------------------
# Per-validation-year MaxDD gate (5 gates, one per year)
# ---------------------------------------------------------------------------


def test_per_year_maxdd_violation_kills_overall():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2019]["maxdd"] = 0.30  # > 0.20 ceiling
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    gate = res.gate_named("validation_year_2019_maxdd")
    assert gate is not None and not gate.passed
    assert gate.values["maxdd"] == 0.30


def test_missing_validation_year_metric_fails_closed():
    """Missing metric = fail-closed (do not silently pass)."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    del metrics["validation"][2021]
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    gate = res.gate_named("validation_year_2021_maxdd")
    assert gate is not None and not gate.passed
    # Audit BUG #3 fix (2026-04-29 R1) renamed "missing" → "missing_or_invalid"
    # because the same code path now covers non-numeric metrics too.
    assert "missing_or_invalid" in gate.values



# ---------------------------------------------------------------------------
# PRD acceptance test #5 — stress slice independent of validation
# ---------------------------------------------------------------------------


def test_stress_slice_failure_kills_even_when_validation_passes():
    """All 5 validation years pass + 2025 role gate passes, but stress fails."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["stress_slice"]["covid_flash"]["maxdd"] = 0.30  # > 0.25 ceiling
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    stress_gate = res.gate_named("stress_slice_covid_flash_maxdd")
    assert stress_gate is not None and not stress_gate.passed
    # All validation MaxDDs still pass (independence):
    for y in (2018, 2019, 2021, 2023, 2025):
        gate = res.gate_named(f"validation_year_{y}_maxdd")
        assert gate is not None and gate.passed


def test_missing_stress_slice_metric_fails_closed():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    del metrics["stress_slice"]["rate_hike_2022"]
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    gate = res.gate_named("stress_slice_rate_hike_2022_maxdd")
    assert gate is not None and not gate.passed


# ---------------------------------------------------------------------------
# Validation aggregate: ≥4/5 SPY positive, ≥3/5 QQQ positive
# ---------------------------------------------------------------------------


def test_aggregate_spy_3_of_5_fails():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    # Set 2 years to negative SPY (fails ≥4 requirement)
    metrics["validation"][2018]["excess_vs_spy"] = -0.01
    metrics["validation"][2019]["excess_vs_spy"] = -0.02
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("validation_aggregate_excess_vs_spy")
    assert gate is not None and not gate.passed
    assert gate.values["positive_count"] == 3


def test_aggregate_qqq_2_of_5_fails():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    # Set 3 years to negative QQQ (fails ≥3 requirement)
    metrics["validation"][2018]["excess_vs_qqq"] = -0.01
    metrics["validation"][2019]["excess_vs_qqq"] = -0.02
    metrics["validation"][2021]["excess_vs_qqq"] = -0.03
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("validation_aggregate_excess_vs_qqq")
    assert gate is not None and not gate.passed
    assert gate.values["positive_count"] == 2


def test_aggregate_qqq_min_3_threshold():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2018]["excess_vs_qqq"] = -0.01
    metrics["validation"][2019]["excess_vs_qqq"] = -0.02
    # Now exactly 3 of 5 positive (2021/2023/2025)
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("validation_aggregate_excess_vs_qqq")
    assert gate is not None and gate.passed
    assert gate.values["positive_count"] == 3


# ---------------------------------------------------------------------------
# Diversifier role + eligibility constraint (M6 C3)
# ---------------------------------------------------------------------------


def test_diversifier_eligibility_passes_with_low_correlation():
    cfg = load_temporal_split()
    res = evaluate_candidate(_passing_core_metrics(), cfg, "diversifier")
    elig = res.gate_named("role_diversifier_eligibility")
    assert elig is not None and elig.passed


def test_diversifier_eligibility_fails_high_correlation():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["vs_existing_core_correlation"] = 0.50  # > 0.40 threshold
    res = evaluate_candidate(metrics, cfg, "diversifier")
    elig = res.gate_named("role_diversifier_eligibility")
    assert elig is not None and not elig.passed
    failures = elig.values["failures"]
    assert any(f["field"] == "vs_existing_core_correlation" for f in failures)


def test_diversifier_eligibility_fails_high_overlap():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["vs_existing_core_overlap"] = 0.40  # > 0.30 threshold
    res = evaluate_candidate(metrics, cfg, "diversifier")
    elig = res.gate_named("role_diversifier_eligibility")
    assert elig is not None and not elig.passed


def test_core_eligibility_always_passes_no_constraints():
    """Core has empty eligibility_constraint → always passes."""
    cfg = load_temporal_split()
    res = evaluate_candidate(_passing_core_metrics(), cfg, "core")
    elig = res.gate_named("role_core_eligibility")
    assert elig is not None and elig.passed


def test_diversifier_has_stricter_maxdd_than_core():
    """M6 C3 compensating constraint: diversifier maxdd ceiling 0.18 < core 0.20."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["maxdd"] = 0.19  # passes core (≤ 0.20), fails diversifier (≤ 0.18)
    res_core = evaluate_candidate(metrics, cfg, "core")
    res_div  = evaluate_candidate(metrics, cfg, "diversifier")
    assert res_core.gate_named("role_core__validation__2025__maxdd").passed
    assert not res_div.gate_named("role_diversifier__validation__2025__maxdd").passed


# ---------------------------------------------------------------------------
# Concentration / beta / cost gates
# ---------------------------------------------------------------------------


def test_concentration_top1_violation_kills():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["top1_max"] = 0.45  # > 0.40 ceiling
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("concentration_top1")
    assert gate is not None and not gate.passed


def test_concentration_top3_violation_kills():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["top3_max"] = 0.75  # > 0.70 ceiling
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("concentration_top3")
    assert gate is not None and not gate.passed


def test_leveraged_etf_dependency_kills():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["leveraged_etf_dependency"] = True
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("concentration_no_leveraged_etf")
    assert gate is not None and not gate.passed


def test_beta_to_qqq_ceiling_kills():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["beta"]["beta_to_qqq"] = 0.95  # > 0.85 ceiling
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("beta_to_qqq")
    assert gate is not None and not gate.passed


def test_cost_2x_failure_kills():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = False
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("cost_robustness_2x")
    assert gate is not None and not gate.passed


# ---------------------------------------------------------------------------
# Unknown role rejection + run_split_acceptance driver
# ---------------------------------------------------------------------------


def test_unknown_role_rejected():
    cfg = load_temporal_split()
    with pytest.raises(ValueError, match="not declared"):
        evaluate_candidate(_passing_core_metrics(), cfg, "hedge")


def test_run_split_acceptance_loads_default_path():
    res = run_split_acceptance(_passing_core_metrics(), role="core")
    assert res.overall_passed


# ---------------------------------------------------------------------------
# PRD acceptance test #7 (codex R20 B3) — production-behavior yaml-swap
# ---------------------------------------------------------------------------


def test_yaml_swap_changes_2025_gate_outcome(tmp_path):
    """Demonstrates value comes from yaml at runtime, not hardcoded.

    Codex R20 B3: the brittle grep-based "no hardcoding" test #7 is
    replaced with a behavioral swap. We mutate the yaml's 2025 excess
    threshold and confirm the same candidate flips between pass/fail.
    """
    raw = yaml.safe_load(DEFAULT_YAML.read_text())
    yaml_path = tmp_path / "split.yaml"

    # v1: 2025 excess_vs_qqq threshold = 0.0 (default core)
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["excess_vs_qqq"] = -0.01

    res_v1 = run_split_acceptance(metrics, role="core", split_path=str(yaml_path))
    role_gate_v1 = res_v1.gate_named("role_core__validation__2025__excess_vs_qqq")
    assert not role_gate_v1.passed, "v1 (threshold=0.0) should fail at -0.01"

    # v2: lower the threshold to -0.05; same candidate now passes
    raw_v2 = deepcopy(raw)
    raw_v2["roles"]["core"]["validation_gates"][0]["value"] = -0.05
    raw_v2["split_name"] = "alternating_regime_holdout_v2_test_only"
    yaml_path.write_text(yaml.safe_dump(raw_v2, sort_keys=False))

    res_v2 = run_split_acceptance(metrics, role="core", split_path=str(yaml_path))
    role_gate_v2 = res_v2.gate_named("role_core__validation__2025__excess_vs_qqq")
    assert role_gate_v2.passed, "v2 (threshold=-0.05) should pass at -0.01"


# ---------------------------------------------------------------------------
# Audit BUG #3 + #4 regressions (2026-04-29 R1) — non-numeric / NaN inputs
# ---------------------------------------------------------------------------


def test_non_numeric_metric_fails_closed_without_typeerror():
    """BUG #3: prior implementation called float(value) directly on
    _resolve_metric output and crashed with TypeError when miner returned
    a string error code instead of a number. Now must fail-closed gracefully.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2021]["maxdd"] = "ERR_NO_DATA"
    res = evaluate_candidate(metrics, cfg, "core")
    assert not res.overall_passed
    gate = res.gate_named("validation_year_2021_maxdd")
    assert gate is not None and not gate.passed
    assert "missing_or_invalid" in gate.values
    assert "non-numeric" in gate.notes or "missing or non-numeric" in gate.notes


def test_non_numeric_beta_fails_closed():
    """BUG #3 sister site: beta_to_qqq cannot be coerced from string."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["beta"]["beta_to_qqq"] = "n/a"
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("beta_to_qqq")
    assert gate is not None and not gate.passed
    assert "missing_or_invalid" in gate.values


def test_nan_aggregate_excess_reports_missing_years():
    """BUG #4: NaN aggregate excess no longer silently filtered — operator
    sees which years contributed missing/non-numeric values.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2018]["excess_vs_spy"] = float("nan")
    metrics["validation"][2019]["excess_vs_spy"] = float("nan")
    res = evaluate_candidate(metrics, cfg, "core")
    spy_gate = res.gate_named("validation_aggregate_excess_vs_spy")
    assert spy_gate is not None
    missing = spy_gate.values.get("missing_or_invalid_years", [])
    assert 2018 in missing and 2019 in missing
    assert "missing/non-numeric" in spy_gate.notes


def test_bool_not_silently_coerced_to_numeric():
    """BUG #3 design: bool-valued fields (leveraged_etf_dependency,
    cost.multiplier_2x_remains_positive) are consumed by dedicated bool
    gates. They must not be silently coerced to 0.0/1.0 by numeric gates.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    # If someone accidentally passes bool to a numeric field, the numeric
    # gate must fail-closed rather than treat True == 1.0.
    metrics["validation"][2021]["maxdd"] = True  # type confusion
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("validation_year_2021_maxdd")
    assert gate is not None and not gate.passed
    assert "missing_or_invalid" in gate.values
