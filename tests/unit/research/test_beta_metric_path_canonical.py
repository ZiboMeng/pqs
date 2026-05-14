"""Regression test for P0 wiring bug 2026-05-07.

Bug: cycle06/07a/08 Track A evaluator scripts built ``metrics["beta_to_qqq"]``
at top level, but ``_eval_beta_gate`` in
``core/research/temporal_split_acceptance.py`` resolves
``"beta.beta_to_qqq"`` (nested under ``"beta"`` key, mirroring yaml schema
``acceptance.beta.beta_to_qqq_max``).

Pre-fix: ``_resolve_metric(metrics, "beta.beta_to_qqq")`` returned _MISSING
sentinel for all 3 cycle07a trials with actual betas 0.534 / 0.566 /
-0.009 (well under 0.85 cap). The gate fail-closed → false-negative
"beta_to_qqq fail" verdict for all 3 cycle06/07a/08 trials evaluated
to date.

This test pins the canonical metrics schema.

Postmortem: ``docs/audit/20260507-beta_metric_path_bug_postmortem.md``.
"""

from __future__ import annotations

from datetime import date

from core.research.temporal_split_acceptance import (
    _MISSING,
    _resolve_metric,
    run_split_acceptance,
)


def _build_canonical_metrics(beta_value: float = 0.534) -> dict:
    """Mirror the post-fix schema produced by cycle06/07a/08 evaluator
    scripts. _eval_beta_gate looks for ``beta.beta_to_qqq``."""
    return {
        "validation": {
            2018: {"maxdd": -0.176, "excess_vs_spy": 0.059, "excess_vs_qqq": 0.017},
            2019: {"maxdd": -0.071, "excess_vs_spy": 0.010, "excess_vs_qqq": -0.076},
            2021: {"maxdd": -0.060, "excess_vs_spy": -0.007, "excess_vs_qqq": -0.005},
            2023: {"maxdd": -0.158, "excess_vs_spy": 0.020, "excess_vs_qqq": -0.300},
            2025: {"maxdd": -0.100, "excess_vs_spy": 0.100, "excess_vs_qqq": 0.050},
        },
        "stress_slice": {
            "covid_flash": {"maxdd": -0.100},
            "rate_hike_2022": {"maxdd": -0.150},
        },
        "concentration": {
            "top1_max": 0.30, "top3_max": 0.55,
            "leveraged_etf_dependency": False,
        },
        "beta": {"beta_to_qqq": beta_value},
        "cost": {"multiplier_2x_remains_positive": True},
    }


def _build_pre_fix_buggy_metrics(beta_value: float = 0.534) -> dict:
    m = _build_canonical_metrics(beta_value)
    m["beta_to_qqq"] = m.pop("beta")["beta_to_qqq"]
    return m


def test_canonical_beta_path_resolves():
    metrics = _build_canonical_metrics(0.534)
    resolved = _resolve_metric(metrics, "beta.beta_to_qqq")
    assert resolved == 0.534, (
        "_resolve_metric must find beta.beta_to_qqq under canonical "
        "{'beta': {'beta_to_qqq': float}} schema"
    )


def test_pre_fix_top_level_path_misses():
    """The 2026-05-07 P0 bug: top-level beta_to_qqq fails to resolve."""
    metrics_buggy = _build_pre_fix_buggy_metrics(0.534)
    resolved = _resolve_metric(metrics_buggy, "beta.beta_to_qqq")
    assert resolved is _MISSING, (
        "Top-level beta_to_qqq (pre-fix) must NOT silently resolve "
        "via beta.beta_to_qqq; this is the bug we're regressing against."
    )


def test_canonical_beta_passes_role_gate_v1():
    """Beta 0.534 < 0.85 cap → beta_to_qqq gate PASS under v1 yaml.

    Pre-fix this gate fail-closed for all 3 cycle07a trials despite
    beta well under cap.
    """
    metrics = _build_canonical_metrics(0.534)
    verdict = run_split_acceptance(metrics, role="core", freeze_date=date(2026, 4, 30))
    beta_gate = verdict.gate_named("beta_to_qqq")
    assert beta_gate is not None, "beta_to_qqq gate must be present"
    assert beta_gate.passed, (
        f"beta=0.534 must pass beta_to_qqq<=0.85 gate; "
        f"actual gate.values={beta_gate.values}"
    )


def test_canonical_beta_passes_role_gate_v3():
    """Beta 0.534 < 0.85 cap → beta_to_qqq gate STILL PASS under v3.

    v3 makes vs_qqq aggregate diagnostic but keeps beta_to_qqq <=0.85
    as hard gate (independent invariant: long-only no-margin downside
    risk constraint, not a benchmark outperformance gate).
    """
    metrics = _build_canonical_metrics(0.534)
    verdict = run_split_acceptance(metrics, role="core", freeze_date=date(2026, 5, 7))
    beta_gate = verdict.gate_named("beta_to_qqq")
    assert beta_gate is not None
    assert beta_gate.passed, (
        f"v3 dispatch must keep beta_to_qqq HARD; beta=0.534 must PASS. "
        f"gate.values={beta_gate.values}"
    )


def test_high_beta_still_fails_v3():
    """Beta 0.95 > 0.85 cap → still HARD FAIL even under v3 (QQQ
    deprecation does not soften beta gate)."""
    metrics = _build_canonical_metrics(0.95)
    verdict = run_split_acceptance(metrics, role="core", freeze_date=date(2026, 5, 7))
    beta_gate = verdict.gate_named("beta_to_qqq")
    assert beta_gate is not None
    assert not beta_gate.passed, (
        "beta=0.95 must FAIL beta_to_qqq<=0.85 even under v3"
    )


def test_v3_makes_vs_qqq_aggregate_diagnostic():
    """Under v3, validation_aggregate_excess_vs_qqq returns passed=True
    regardless of count, with diagnostic_actual_passed in values."""
    # Set 2025 vs_qqq positive but other years negative → only 1 of 5 positive
    # (well below positive_min=3); v3 should still PASS the aggregate gate.
    metrics = _build_canonical_metrics(0.534)
    metrics["validation"][2018]["excess_vs_qqq"] = -0.10
    metrics["validation"][2019]["excess_vs_qqq"] = -0.10
    metrics["validation"][2021]["excess_vs_qqq"] = -0.10
    metrics["validation"][2023]["excess_vs_qqq"] = -0.10
    metrics["validation"][2025]["excess_vs_qqq"] = 0.05
    verdict_v3 = run_split_acceptance(
        metrics, role="core", freeze_date=date(2026, 5, 7)
    )
    agg_gate = verdict_v3.gate_named("validation_aggregate_excess_vs_qqq")
    assert agg_gate is not None
    assert agg_gate.passed, "v3 aggregate vs_qqq must report passed=True (diagnostic)"
    assert agg_gate.values.get("diagnostic_actual_passed") is False, (
        f"diagnostic_actual_passed must record real outcome; "
        f"values={agg_gate.values}"
    )

    # Same metrics on v1 dispatch (freeze pre-2026-05-02):
    # Pre-P0.a (Codex 2026-05-14): HARD fail since yaml action=kill_candidate.
    # Post-P0.a: config/evaluation_policy.yaml demotes ALL QQQ gates to
    # diagnostic_only at runtime, including v1's. So v1 gate ALSO passes
    # with diagnostic_actual_passed=False. This is the governance fix —
    # v1 yaml content unchanged (locked_after_first_use), runtime layer
    # applies deprecation uniformly.
    verdict_v1 = run_split_acceptance(
        metrics, role="core", freeze_date=date(2026, 4, 30)
    )
    agg_gate_v1 = verdict_v1.gate_named("validation_aggregate_excess_vs_qqq")
    assert agg_gate_v1 is not None
    assert agg_gate_v1.passed, (
        "Post-P0.a: v1 aggregate vs_qqq demoted to diagnostic by policy; "
        "passes regardless. diagnostic_actual_passed records real outcome."
    )
    assert agg_gate_v1.values.get("diagnostic_actual_passed") is False
    assert agg_gate_v1.values.get("diagnostic_source") in (
        "policy_demote", "yaml_v3+policy"
    ), f"diagnostic source must indicate policy demote; values={agg_gate_v1.values}"
