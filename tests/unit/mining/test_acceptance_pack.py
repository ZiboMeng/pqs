"""Unit tests for core/mining/acceptance_pack.py (PRD M2).

Covers:
  - gate construction from archive row
  - overall_passed aggregation
  - missing spec_id → AcceptancePackError
  - prefix match support
  - artifact write + JSON roundtrip
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.mining.acceptance_pack import (
    AcceptancePackError,
    _build_gates,
    run_acceptance_pack,
    write_acceptance_artifact,
)


# ---------------------------------------------------------------------------
# Synthetic archive fixture
# ---------------------------------------------------------------------------


_PERFECT_TRIAL = {
    "spec_id": "perfect_trial_123",
    "strategy_type": "multi_factor",
    "lineage_tag": "test_lineage",
    "params_json": json.dumps({
        "top_n": 4,
        "factor_weights": {"low_vol": 0.5, "momentum": 0.5},
        "apply_extra_shift": False,
    }),
    "quick_sharpe": 1.2,
    "quick_max_dd": 0.15,
    "quick_cagr": 0.25,
    "passed_quick": 1,
    "oos_ir": 0.35,
    "oos_pass_rate": 0.70,
    "oos_sharpe": 0.80,
    "oos_excess_return": 0.05,
    "passed_oos": 1,
    "regime_robust": 1,
    "cost_robust": 1,
    "param_robust": 1,
    "stress_passed": 1,
    "diversity_corr": 0.3,
    "passed_diversity": 1,
    "holdout_ir": 0.28,
    "holdout_excess_return": 0.08,
    "holdout_max_dd": 0.12,
    "passed_holdout": 1,
    "qqq_full_period_excess": 0.04,
    "qqq_holdout_excess": 0.06,
    "qqq_oos_avg_excess": 0.03,
    "passed_qqq_gate": 1,
}


_FAILING_TRIAL = {
    "spec_id": "failing_trial_xyz",
    "strategy_type": "multi_factor",
    "lineage_tag": "test_lineage",
    "params_json": json.dumps({
        "top_n": 4,
        "factor_weights": {"low_vol": 0.5, "momentum": 0.5},
    }),
    "quick_sharpe": 0.5,
    "quick_max_dd": 0.30,
    "quick_cagr": 0.10,
    "passed_quick": 1,
    "oos_ir": -0.09,
    "oos_pass_rate": 0.50,
    "oos_excess_return": -0.02,
    "passed_oos": 0,
    "regime_robust": 0,
    "cost_robust": 0,
    "param_robust": 0,
    "stress_passed": 0,
    "diversity_corr": None,
    "passed_diversity": 0,
    "holdout_ir": -0.10,
    "holdout_excess_return": -0.05,
    "holdout_max_dd": 0.20,
    "passed_holdout": 0,
    "qqq_full_period_excess": -0.05,
    "qqq_holdout_excess": -0.02,
    "qqq_oos_avg_excess": -0.03,
    "passed_qqq_gate": 0,
}


def _create_archive(tmp_path: Path, rows: list[dict]) -> Path:
    """Build a minimal archive.db with the given rows inserted."""
    db = tmp_path / "archive.db"
    conn = sqlite3.connect(db)
    cols = sorted({k for r in rows for k in r.keys()})
    col_defs = ", ".join(f"{c} TEXT" for c in cols)
    conn.execute(f"CREATE TABLE trials ({col_defs})")
    for r in rows:
        placeholders = ",".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO trials ({','.join(cols)}) VALUES ({placeholders})",
            tuple(r.get(c) for c in cols),
        )
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# Gate tests (using _build_gates directly)
# ---------------------------------------------------------------------------


def test_perfect_trial_all_gates_pass():
    # Pack v2: gate 10 fresh_backtest = skip-PASS when fresh_check=None
    gates = _build_gates(_PERFECT_TRIAL, fresh_check=None)
    assert len(gates) == 10
    assert all(g.passed for g in gates), f"expected all pass, got: {[(g.name, g.passed) for g in gates]}"


def test_failing_trial_multiple_gates_fail():
    gates = _build_gates(_FAILING_TRIAL, fresh_check=None)
    names_failing = [g.name for g in gates if not g.passed]
    assert "oos_walk_forward" in names_failing
    assert "robustness" in names_failing
    assert "holdout" in names_failing
    assert "qqq_hard_gate_archive" in names_failing


def test_fresh_backtest_gate_passes_when_positive_excess():
    """Gate 10 passes when fresh_check.passed=True."""
    fresh = {"strategy_cagr": 0.22, "qqq_cagr": 0.18, "excess": 0.04, "passed": True}
    gates = _build_gates(_PERFECT_TRIAL, fresh_check=fresh)
    fresh_gate = next(g for g in gates if g.name == "full_period_fresh_backtest")
    assert fresh_gate.passed
    assert fresh_gate.values["excess"] == pytest.approx(0.04)


def test_fresh_backtest_gate_fails_when_negative_excess():
    """Gate 10 catches specs where fresh run shows CAGR < QQQ, even if
    archive claimed otherwise — this is the v2 enhancement."""
    fresh = {"strategy_cagr": 0.14, "qqq_cagr": 0.176, "excess": -0.036, "passed": False}
    gates = _build_gates(_PERFECT_TRIAL, fresh_check=fresh)
    fresh_gate = next(g for g in gates if g.name == "full_period_fresh_backtest")
    assert not fresh_gate.passed


def test_fresh_backtest_gate_fails_on_error():
    """If fresh backtest errors, fail-closed rather than skip-pass."""
    fresh = {"error": "some import failure"}
    gates = _build_gates(_PERFECT_TRIAL, fresh_check=fresh)
    fresh_gate = next(g for g in gates if g.name == "full_period_fresh_backtest")
    assert not fresh_gate.passed
    assert "error" in fresh_gate.values


def test_fresh_backtest_gate_skip_pass_when_none():
    """When run_fresh_backtest=False, gate 10 is skip-pass (green)."""
    gates = _build_gates(_PERFECT_TRIAL, fresh_check=None)
    fresh_gate = next(g for g in gates if g.name == "full_period_fresh_backtest")
    assert fresh_gate.passed
    assert fresh_gate.values.get("skipped") is True


def test_gate_values_populated():
    gates = _build_gates(_PERFECT_TRIAL)
    quick_gate = next(g for g in gates if g.name == "quick")
    assert quick_gate.values["sharpe"] == pytest.approx(1.2)
    assert quick_gate.values["cagr"] == pytest.approx(0.25)

    oos_gate = next(g for g in gates if g.name == "oos_walk_forward")
    assert oos_gate.values["oos_ir"] == pytest.approx(0.35)
    assert oos_gate.threshold["min_ir"] == 0.20


def test_max_dd_gate_uses_absolute_floor():
    trial = dict(_PERFECT_TRIAL)
    trial["quick_max_dd"] = 0.30  # 30% drawdown - over -25% floor
    gates = _build_gates(trial)
    dd_gate = next(g for g in gates if g.name == "max_drawdown")
    assert not dd_gate.passed
    assert dd_gate.values["max_dd"] == pytest.approx(-0.30)


def test_diversity_gate_defaults_pass_when_missing():
    trial = dict(_PERFECT_TRIAL)
    trial["passed_diversity"] = None
    gates = _build_gates(trial)
    div_gate = next(g for g in gates if g.name == "diversity")
    assert div_gate.passed  # skip-pass semantics
    assert "SKIP-PASS" in div_gate.notes


# ---------------------------------------------------------------------------
# End-to-end run_acceptance_pack
# ---------------------------------------------------------------------------


def test_run_pack_exact_match(tmp_path):
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    # run_fresh_backtest=False to avoid expensive real-data backtest in unit test
    result = run_acceptance_pack("perfect_trial_123", archive_db=db, run_fresh_backtest=False)
    assert result.spec_id == "perfect_trial_123"
    assert result.overall_passed is True
    assert len(result.gates) == 10  # 9 archive gates + 1 fresh_backtest (skip-pass)


def test_run_pack_prefix_match(tmp_path):
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    result = run_acceptance_pack("perfect_trial_", archive_db=db, run_fresh_backtest=False)
    assert result.spec_id == "perfect_trial_123"


def test_run_pack_missing_spec_raises(tmp_path):
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    with pytest.raises(AcceptancePackError) as exc_info:
        run_acceptance_pack("nonexistent", archive_db=db, run_fresh_backtest=False)
    assert "not found" in str(exc_info.value).lower()


def test_run_pack_missing_db_raises(tmp_path):
    with pytest.raises(AcceptancePackError) as exc_info:
        run_acceptance_pack("any", archive_db=tmp_path / "nonexistent.db", run_fresh_backtest=False)
    assert "not found" in str(exc_info.value).lower()


def test_run_pack_params_roundtrip(tmp_path):
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    result = run_acceptance_pack("perfect_trial_123", archive_db=db, run_fresh_backtest=False)
    assert result.params["top_n"] == 4
    assert result.params["factor_weights"] == {"low_vol": 0.5, "momentum": 0.5}


def test_run_pack_failing_overall_false(tmp_path):
    db = _create_archive(tmp_path, [_FAILING_TRIAL])
    result = run_acceptance_pack("failing_trial_xyz", archive_db=db, run_fresh_backtest=False)
    assert result.overall_passed is False


def test_run_pack_archive_evidence_only_flag(tmp_path):
    """archive_evidence_only=True when fresh backtest skipped; False otherwise."""
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    r_skip = run_acceptance_pack("perfect_trial_123", archive_db=db, run_fresh_backtest=False)
    assert r_skip.archive_evidence_only is True


# ---------------------------------------------------------------------------
# Artifact write
# ---------------------------------------------------------------------------


def test_write_artifact_json_roundtrip(tmp_path):
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    result = run_acceptance_pack("perfect_trial_123", archive_db=db, run_fresh_backtest=False)
    out = tmp_path / "acceptance.json"
    write_acceptance_artifact(result, out)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["spec_id"] == "perfect_trial_123"
    assert loaded["overall_passed"] is True
    assert len(loaded["gates"]) == 10  # 9 archive + 1 fresh skip-pass


def test_summary_line_format(tmp_path):
    db = _create_archive(tmp_path, [_PERFECT_TRIAL])
    result = run_acceptance_pack("perfect_trial_123", archive_db=db, run_fresh_backtest=False)
    line = result.summary_line()
    assert "perfect_tria" in line  # first 12 chars
    assert "PASS" in line
    assert "10/10" in line  # v2: 10 gates total
