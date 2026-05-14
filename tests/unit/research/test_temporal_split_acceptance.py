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
    """P0.a 2026-05-14: QQQ 2025 gate demoted to diagnostic per
    config/evaluation_policy.yaml (Codex audit governance unification).
    Pre-fix v1 yaml had `action: kill_candidate`; post-fix runtime policy
    overrides to `diagnostic_only` and the gate passes regardless of value.
    The underlying value is still computed and reported in
    `diagnostic_actual_passed` for the audit trail.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["excess_vs_qqq"] = -0.01
    res = evaluate_candidate(metrics, cfg, "core")
    role_gate = res.gate_named("role_core__validation__2025__excess_vs_qqq")
    assert role_gate is not None
    # Post-P0.a: QQQ gate now diagnostic, passes regardless
    assert role_gate.passed
    # But the underlying metric is still recorded:
    assert role_gate.values.get("diagnostic_actual_passed") is False
    # Other validation years' MaxDD gates should still pass:
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
    """Pre-P0.a: diversifier role allowed excess_vs_qqq down to -0.05 (core
    strict at 0.0). Post-P0.a 2026-05-14: BOTH roles' QQQ gates demoted to
    diagnostic_only per evaluation_policy.yaml — neither blocks.
    Diagnostic actual_passed is still computed and recorded per role's
    yaml threshold for audit trail.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2025]["excess_vs_qqq"] = -0.03
    # Core: post-P0.a passes (diagnostic mode), but actual would fail (-0.03 < 0)
    res_core = evaluate_candidate(metrics, cfg, "core")
    role_gate_core = res_core.gate_named("role_core__validation__2025__excess_vs_qqq")
    assert role_gate_core.passed
    assert role_gate_core.values.get("diagnostic_actual_passed") is False
    # Diversifier: post-P0.a passes; -0.03 > -0.05 so actual_passed True
    res_div = evaluate_candidate(metrics, cfg, "diversifier")
    role_gate_div = res_div.gate_named("role_diversifier__validation__2025__excess_vs_qqq")
    assert role_gate_div.passed
    # Note: under diagnostic mode the gate passes regardless; we don't assert
    # diagnostic_actual_passed value here because it depends on role threshold


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
    """Pre-P0.a: aggregate vs_qqq required ≥3 positive years; 2/5 → fail.
    Post-P0.a 2026-05-14: gate demoted to diagnostic_only per
    evaluation_policy.yaml — passes regardless. Actual count still recorded
    in diagnostic_actual_passed for audit.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["validation"][2018]["excess_vs_qqq"] = -0.01
    metrics["validation"][2019]["excess_vs_qqq"] = -0.02
    metrics["validation"][2021]["excess_vs_qqq"] = -0.03
    res = evaluate_candidate(metrics, cfg, "core")
    gate = res.gate_named("validation_aggregate_excess_vs_qqq")
    assert gate is not None
    # Post-P0.a: passes in diagnostic mode regardless of count
    assert gate.passed
    assert gate.values["positive_count"] == 2
    # But actual gate verdict (had it been hard) is recorded:
    assert gate.values.get("diagnostic_actual_passed") is False
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
    """Codex R20 B3 + P0.a 2026-05-14: yaml swap test originally used a
    QQQ-threshold swap. Post-P0.a, QQQ gate is demoted to diagnostic and
    won't flip on yaml threshold change. So we use the SPY threshold
    swap instead (which is the actual hard gate post-deprecation).
    """
    raw = yaml.safe_load(DEFAULT_YAML.read_text())
    yaml_path = tmp_path / "split.yaml"

    # v1: 2025 excess_vs_spy threshold = 0.0 (SPY is the real hard gate)
    yaml_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    metrics = _passing_core_metrics()
    # Set 2025 vs_spy negative; vs_qqq stays positive
    metrics["validation"][2025]["excess_vs_spy"] = -0.01

    res_v1 = run_split_acceptance(metrics, role="core", split_path=str(yaml_path))
    # The aggregate vs_spy gate should fail (3 positive years, threshold ≥4)
    agg_gate_v1 = res_v1.gate_named("validation_aggregate_excess_vs_spy")
    assert agg_gate_v1 is not None
    # Default needs 4 of 5 positive vs SPY; we made 2025 negative so 4 remain → still passes;
    # let's also flip 2018 negative to drop to 3:
    metrics["validation"][2018]["excess_vs_spy"] = -0.02
    res_v1b = run_split_acceptance(metrics, role="core", split_path=str(yaml_path))
    agg_v1b = res_v1b.gate_named("validation_aggregate_excess_vs_spy")
    assert not agg_v1b.passed, "v1 with 3/5 positive SPY years (< 4 threshold) should fail aggregate"

    # v2: lower the SPY threshold to 2 positive years; same candidate now passes
    raw_v2 = deepcopy(raw)
    raw_v2["acceptance"]["validation_year_pass"]["excess_vs_spy_positive_min"] = 2
    raw_v2["split_name"] = "alternating_regime_holdout_v2_test_only"
    yaml_path.write_text(yaml.safe_dump(raw_v2, sort_keys=False))

    res_v2 = run_split_acceptance(metrics, role="core", split_path=str(yaml_path))
    agg_v2 = res_v2.gate_named("validation_aggregate_excess_vs_spy")
    assert agg_v2.passed, "v2 (threshold=2) should pass with 3/5 positive"


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


# ---------------------------------------------------------------------------
# Codex R21 P0.2 regressions (2026-04-29) — strict bool, not Python truthiness
# ---------------------------------------------------------------------------


def test_cost_gate_string_false_fails_closed():
    """P0.2: cost.multiplier_2x_remains_positive = "False" must fail-close.
    Pre-fix `bool("False")` was True (non-empty string) and silently passed.
    """
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = "False"
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and not cost.passed
    assert "missing_or_invalid" in cost.values
    assert "non-bool" in cost.notes


def test_cost_gate_err_string_fails_closed():
    """P0.2: ERR_NO_DATA from upstream measurement must fail-close, not pass."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = "ERR_NO_DATA"
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and not cost.passed


def test_cost_gate_int_one_fails_closed():
    """P0.2: int 1 must NOT be silently treated as True via Python truthiness."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = 1
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and not cost.passed


def test_cost_gate_int_zero_fails_closed():
    """P0.2: int 0 also fails (cost gate accepts only real bool)."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = 0
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and not cost.passed


def test_cost_gate_real_bool_true_passes():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = True
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and cost.passed


def test_concentration_leveraged_etf_string_fails_closed():
    """P0.2: leveraged_etf_dependency = "True" (string) must fail-close.
    The semantically-correct value is bool False (no dependency)."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["leveraged_etf_dependency"] = "True"
    res = evaluate_candidate(metrics, cfg, "core")
    lev = res.gate_named("concentration_no_leveraged_etf")
    assert lev is not None and not lev.passed


def test_concentration_leveraged_etf_string_false_fails_closed():
    """P0.2: even string "False" fails — only literal bool False passes."""
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["leveraged_etf_dependency"] = "False"
    res = evaluate_candidate(metrics, cfg, "core")
    lev = res.gate_named("concentration_no_leveraged_etf")
    assert lev is not None and not lev.passed


def test_concentration_leveraged_etf_real_bool_passes():
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["leveraged_etf_dependency"] = False
    res = evaluate_candidate(metrics, cfg, "core")
    lev = res.gate_named("concentration_no_leveraged_etf")
    assert lev is not None and lev.passed


def test_cost_gate_accepts_numpy_bool():
    """P0.2 audit-pass extension: numpy.bool_ from pandas reductions
    (df.any(), arr.all()) IS a real bool, not truthiness coercion."""
    import numpy as np
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = np.bool_(True)
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and cost.passed


def test_concentration_leveraged_etf_accepts_numpy_bool_false():
    import numpy as np
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["concentration"]["leveraged_etf_dependency"] = np.bool_(False)
    res = evaluate_candidate(metrics, cfg, "core")
    lev = res.gate_named("concentration_no_leveraged_etf")
    assert lev is not None and lev.passed


def test_cost_gate_rejects_numpy_array_with_bool_dtype():
    """P0.2: numpy bool ARRAY (not scalar) must still fail-close — caller
    bug to pass an array where a scalar was expected."""
    import numpy as np
    cfg = load_temporal_split()
    metrics = _passing_core_metrics()
    metrics["cost"]["multiplier_2x_remains_positive"] = np.array([True])
    res = evaluate_candidate(metrics, cfg, "core")
    cost = res.gate_named("cost_robustness_2x")
    assert cost is not None and not cost.passed


# ─── v3 QQQ deprecation tests (2026-05-02) ─────────────────────────────


def test_v3_load_yields_qqq_diagnostic_only_flag():
    """v3 yaml's acceptance.validation_year_pass.excess_vs_qqq_diagnostic_only
    must be True (per QQQ deprecation 2026-05-02).
    """
    from core.research.temporal_split import (
        load_temporal_split, _DEFAULT_PATH_V3,
    )
    cfg = load_temporal_split(_DEFAULT_PATH_V3)
    assert cfg.acceptance.validation_year_pass.excess_vs_qqq_diagnostic_only is True


def test_v3_validation_aggregate_qqq_passes_regardless_of_count():
    """When excess_vs_qqq_diagnostic_only=True, the aggregate gate passes
    even when qqq_pos_count < threshold.
    """
    from core.research.temporal_split import load_temporal_split, _DEFAULT_PATH_V3
    from core.research.temporal_split_acceptance import _eval_validation_aggregate
    cfg = load_temporal_split(_DEFAULT_PATH_V3)
    # All vs_qqq = -0.10 (every year fails) but should still pass aggregate
    metrics = {
        "validation": {
            "2018": {"excess_vs_spy": 0.05, "excess_vs_qqq": -0.10},
            "2019": {"excess_vs_spy": 0.05, "excess_vs_qqq": -0.10},
            "2021": {"excess_vs_spy": 0.05, "excess_vs_qqq": -0.10},
            "2023": {"excess_vs_spy": 0.05, "excess_vs_qqq": -0.10},
            "2025": {"excess_vs_spy": 0.05, "excess_vs_qqq": -0.10},
        }
    }
    gates = _eval_validation_aggregate(metrics, cfg)
    qqq_gate = [g for g in gates if g.name == "validation_aggregate_excess_vs_qqq"][0]
    assert qqq_gate.passed is True
    # Actual outcome still recorded in values
    assert qqq_gate.values["diagnostic_actual_passed"] is False
    assert qqq_gate.values["positive_count"] == 0
    assert "diagnostic_only mode" in qqq_gate.notes


def test_v3_role_gate_diagnostic_only_passes_regardless():
    """Role gate with action=diagnostic_only sets passed=True even when
    actual evaluation fails. diagnostic_actual_passed records truth.
    """
    from core.research.temporal_split import load_temporal_split, _DEFAULT_PATH_V3
    from core.research.temporal_split_acceptance import _eval_role_gates
    cfg = load_temporal_split(_DEFAULT_PATH_V3)
    # Provide minimal metrics; vs_spy passes, vs_qqq fails
    metrics = {
        "validation": {
            "2025": {"excess_vs_spy": 0.05, "excess_vs_qqq": -0.05, "maxdd": 0.10},
        },
    }
    gates = _eval_role_gates(metrics, cfg, "core")
    # Find the vs_qqq diagnostic gate
    qqq_gates = [g for g in gates if "excess_vs_qqq" in g.name]
    assert len(qqq_gates) == 1
    g = qqq_gates[0]
    assert g.passed is True  # diagnostic_only ALWAYS passes
    assert g.values["diagnostic_actual_passed"] is False  # actual eval false
    assert "diagnostic_only" in g.notes
    # vs_spy gate is hard kill_candidate
    spy_gates = [g for g in gates if "excess_vs_spy" in g.name]
    assert len(spy_gates) == 1
    assert spy_gates[0].passed is True  # vs_spy=0.05 passes >0


def test_v3_role_gate_diagnostic_only_with_missing_data_does_not_block():
    """diagnostic_only gate with missing metric data still passes (no block);
    diagnostic_actual_passed records False for transparency.
    """
    from core.research.temporal_split import load_temporal_split, _DEFAULT_PATH_V3
    from core.research.temporal_split_acceptance import _eval_role_gates
    cfg = load_temporal_split(_DEFAULT_PATH_V3)
    # vs_spy present (passes), vs_qqq absent (would fail-closed if hard)
    metrics = {
        "validation": {
            "2025": {"excess_vs_spy": 0.05, "maxdd": 0.10},
        },
    }
    gates = _eval_role_gates(metrics, cfg, "core")
    qqq_gates = [g for g in gates if "excess_vs_qqq" in g.name]
    assert len(qqq_gates) == 1
    g = qqq_gates[0]
    assert g.passed is True  # diagnostic does not block on missing
    assert g.values["diagnostic_actual_passed"] is False
    assert "missing or non-numeric" in g.notes


def test_v3_kill_candidate_action_with_missing_data_still_fails_closed():
    """Hard kill_candidate gate with missing metric MUST still fail (regression
    check that diagnostic_only logic doesn't accidentally apply to kill_candidate).
    """
    from core.research.temporal_split import load_temporal_split, _DEFAULT_PATH_V3
    from core.research.temporal_split_acceptance import _eval_role_gates
    cfg = load_temporal_split(_DEFAULT_PATH_V3)
    # vs_spy missing — should fail-closed as hard gate
    metrics = {
        "validation": {
            "2025": {"excess_vs_qqq": -0.05, "maxdd": 0.10},
        },
    }
    gates = _eval_role_gates(metrics, cfg, "core")
    spy_gates = [g for g in gates if "excess_vs_spy" in g.name]
    assert len(spy_gates) == 1
    assert spy_gates[0].passed is False  # hard kill_candidate still fail-closed
    # diagnostic_actual_passed should NOT be in values for hard gates
    assert "diagnostic_actual_passed" not in spy_gates[0].values
