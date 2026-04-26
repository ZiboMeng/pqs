"""Unit tests for the research-cycle close-eval decision-table layer.

Targets `dev/scripts/research_cycle/run_close_eval.py`'s
`gate_check` and `build_decision_table` helpers — the pure functions
that turn (criteria thresholds, IC summary, walk-forward folds,
concentration metrics) into the G2.A pass/fail decision table.

The hard-gate-fail path (the cycle 2026-04-26-01 outcome:
watchlist_total_share = 0.395 > 0.30 ceiling) is the most important
case to protect: a regression that returned `passed=True` when the
gate should fail would silently advance a rejected candidate. These
tests pin that path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


def _load_close_eval_module():
    spec = importlib.util.spec_from_file_location(
        "research_cycle_run_close_eval_test_import",
        ROOT / "dev" / "scripts" / "research_cycle" / "run_close_eval.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# Mirror cycle 2026-04-26-01 criteria.yaml's hard_requirements (canonical)
HARD = {
    "min_ic_ir_full_period": 0.25,
    "min_walk_forward_folds_positive": 3,
    "walk_forward_n_folds": 4,
    "m12_concentration_tier_ceiling": "warning",
    "watchlist_total_share_ceiling": 0.30,
    "thin_data_weighted_share_ceiling": 0.10,
    "top1_weight_max_ceiling": 0.40,
    "top3_weight_max_ceiling": 0.70,
}


# ── gate_check primitive ────────────────────────────────────────────


def test_gate_check_ge_passes_when_at_or_above_threshold():
    mod = _load_close_eval_module()
    r = mod.gate_check("ic_ir", 1.04, "ge", 0.25)
    assert r["passed"] is True
    r = mod.gate_check("ic_ir", 0.25, "ge", 0.25)  # equal → passes
    assert r["passed"] is True


def test_gate_check_ge_fails_when_below_threshold():
    mod = _load_close_eval_module()
    r = mod.gate_check("ic_ir", 0.24, "ge", 0.25)
    assert r["passed"] is False


def test_gate_check_le_fails_when_above_threshold():
    """Critical: this is the watchlist gate's mode. 0.395 > 0.30 must
    return passed=False."""
    mod = _load_close_eval_module()
    r = mod.gate_check("watchlist", 0.3950, "le", 0.30)
    assert r["passed"] is False
    assert r["measured"] == 0.3950
    assert r["op"] == "le"
    assert r["threshold"] == 0.30


def test_gate_check_le_passes_when_at_or_below_threshold():
    mod = _load_close_eval_module()
    assert mod.gate_check("watchlist", 0.30, "le", 0.30)["passed"] is True
    assert mod.gate_check("watchlist", 0.10, "le", 0.30)["passed"] is True


def test_gate_check_in_set_membership():
    mod = _load_close_eval_module()
    assert mod.gate_check("tier", "warning", "in_set",
                          ["pass", "warning"])["passed"] is True
    assert mod.gate_check("tier", "manual_review_required", "in_set",
                          ["pass", "warning"])["passed"] is False


def test_gate_check_none_measured_never_passes_numeric_ops():
    """A missing measurement is a hard fail, not a silent pass."""
    mod = _load_close_eval_module()
    assert mod.gate_check("ic_ir", None, "ge", 0.25)["passed"] is False
    assert mod.gate_check("watchlist", None, "le", 0.30)["passed"] is False


def test_gate_check_unknown_op_raises():
    mod = _load_close_eval_module()
    with pytest.raises(ValueError, match="unknown gate op"):
        mod.gate_check("x", 1.0, "eq", 1.0)


# ── build_decision_table — hard-gate-fail path (the cycle outcome) ──


def test_build_decision_table_cycle_2026_04_26_01_actual_failure():
    """Pin the actual cycle outcome: 6 of 7 gates pass, watchlist
    fails. Any regression that flips the watchlist row to passed=True
    would silently advance a rejected candidate."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD,
        ic_ir_full_period=1.0405,        # actual cycle measurement
        folds_positive=4,                 # actual cycle measurement
        concentration_dict={
            "tier": "warning",
            "watchlist_total_share": 0.3950,    # the binding fail
            "thin_data_weighted_share": 0.0751,
            "top1_weight_max": 0.10,
            "top3_weight_max": 0.30,
        },
    )

    assert len(rows) == 7
    by_gate = {r["gate"]: r for r in rows}
    assert by_gate["min_ic_ir_full_period"]["passed"] is True
    assert by_gate["min_walk_forward_folds_positive"]["passed"] is True
    assert by_gate["m12_concentration_tier"]["passed"] is True
    assert by_gate["watchlist_total_share"]["passed"] is False, (
        "watchlist_total_share=0.395 must FAIL the 0.30 ceiling — "
        "this is the cycle 2026-04-26-01 binding fail; a regression "
        "here would silently advance a rejected candidate"
    )
    assert by_gate["thin_data_weighted_share"]["passed"] is True
    assert by_gate["top1_weight_max"]["passed"] is True
    assert by_gate["top3_weight_max"]["passed"] is True

    # Overall pass = AND of all rows
    assert all(r["passed"] for r in rows) is False


def test_build_decision_table_all_pass_path_works():
    """Counter-case: a synthetic candidate that satisfies every gate
    must produce overall_pass=True. Without this, a regression that
    accidentally hard-codes False would not be caught by the fail
    test alone."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD,
        ic_ir_full_period=0.50,
        folds_positive=4,
        concentration_dict={
            "tier": "pass",
            "watchlist_total_share": 0.10,
            "thin_data_weighted_share": 0.05,
            "top1_weight_max": 0.20,
            "top3_weight_max": 0.50,
        },
    )
    assert all(r["passed"] for r in rows) is True
    assert len(rows) == 7


def test_build_decision_table_walk_forward_3_of_4_passes():
    """3/4 folds positive is the threshold. 2/4 should fail."""
    mod = _load_close_eval_module()
    base_conc = {
        "tier": "pass",
        "watchlist_total_share": 0.10,
        "thin_data_weighted_share": 0.05,
        "top1_weight_max": 0.20,
        "top3_weight_max": 0.50,
    }
    pass_rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=3,
        concentration_dict=base_conc,
    )
    fail_rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=2,
        concentration_dict=base_conc,
    )
    by_gate_pass = {r["gate"]: r for r in pass_rows}
    by_gate_fail = {r["gate"]: r for r in fail_rows}
    assert by_gate_pass["min_walk_forward_folds_positive"]["passed"] is True
    assert by_gate_fail["min_walk_forward_folds_positive"]["passed"] is False


def test_build_decision_table_tier_manual_review_required_blocks():
    """The M12 tier ceiling is 'warning'; tier='manual_review_required'
    must be classified as not-in-set → fail. This is a cycle-2026-04-26-01-
    aligned rule (criteria yaml hard_requirements +
    docs/memos/20260425-m12_review_decision.md §5)."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=4,
        concentration_dict={
            "tier": "manual_review_required",
            "watchlist_total_share": 0.10,
            "thin_data_weighted_share": 0.05,
            "top1_weight_max": 0.20,
            "top3_weight_max": 0.50,
        },
    )
    by_gate = {r["gate"]: r for r in rows}
    assert by_gate["m12_concentration_tier"]["passed"] is False


def test_build_decision_table_missing_concentration_metric_fails():
    """If concentration measurement is missing for a numeric gate,
    the gate must FAIL. Silent passes on missing measurements would
    let a candidate slip through if a future eval bug zeroed-out a
    metric."""
    mod = _load_close_eval_module()
    rows = mod.build_decision_table(
        hard=HARD, ic_ir_full_period=0.5, folds_positive=4,
        concentration_dict={
            "tier": "pass",
            # watchlist_total_share missing -> .get() returns None
            "thin_data_weighted_share": 0.05,
            "top1_weight_max": 0.20,
            "top3_weight_max": 0.50,
        },
    )
    by_gate = {r["gate"]: r for r in rows}
    assert by_gate["watchlist_total_share"]["measured"] is None
    assert by_gate["watchlist_total_share"]["passed"] is False
