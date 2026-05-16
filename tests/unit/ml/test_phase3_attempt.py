"""Unit tests for the Phase 3 attempt records — chart-structure P3·R2.

Gate P3-A1: phase3_attempt_<id>.json schema validation.
Gate P3-A3: eval block declares eval_method / cost_model / turnover_penalty.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from core.ml.phase3_attempt import Phase3Attempt, load_phase3_attempt

_PROJ = Path(__file__).resolve().parents[3]
_ATTEMPT = _PROJ / "data" / "audit" / "chart_structure" / "phase3_attempt_3b_001.json"

_EVAL = dict(
    eval_method="oos rank ic", cost_model="30bp", turnover_penalty="reported",
    oos_rank_ic=0.01, vs_tabular_baseline=-0.02,
)
_BASE = dict(
    schema_version="1.0", attempt_id="t", model="3B",
    created_at="2026-05-16", representation="r", status="experimented",
    verdict="no_significant_increment", verdict_scope="config_scoped",
    config={"k": "v"}, eval=_EVAL,
    root_cause="x" * 30,
)


def test_phase3_attempt_3b_001_loads_and_validates():
    a = load_phase3_attempt(_ATTEMPT)
    assert a.attempt_id == "3b_001"
    assert a.model == "3B"
    assert a.status == "experimented"


def test_phase3_attempt_3a_001_loads_and_validates():
    a = load_phase3_attempt(
        _PROJ / "data" / "audit" / "chart_structure" / "phase3_attempt_3a_001.json")
    assert a.attempt_id == "3a_001"
    assert a.model == "3A"
    assert a.eval.eval_method and a.eval.cost_model and a.eval.turnover_penalty
    if a.verdict != "beats_tabular_baseline":
        assert a.root_cause and a.verdict_scope == "config_scoped"


def test_phase3_attempt_3c_001_loads_and_validates():
    a = load_phase3_attempt(
        _PROJ / "data" / "audit" / "chart_structure" / "phase3_attempt_3c_001.json")
    assert a.attempt_id == "3c_001"
    assert a.model == "3C"
    assert a.eval.eval_method and a.eval.cost_model and a.eval.turnover_penalty
    if a.verdict != "beats_tabular_baseline":
        assert a.root_cause and a.verdict_scope == "config_scoped"


def test_phase3_attempt_schema():
    """P3-A1 literal-named test (main PRD §5.6 names this exact test).

    PRD-audit 2026-05-16: the spec names `test_phase3_attempt_schema`;
    this asserts the schema model rejects malformed records and accepts
    all real attempt JSONs, so the named AC is satisfied literally."""
    # rejects: negative verdict without root_cause / global scope / empty config
    bad = dict(_BASE)
    bad.pop("root_cause")
    with pytest.raises(ValidationError):
        Phase3Attempt.model_validate(bad)
    with pytest.raises(ValidationError):
        Phase3Attempt.model_validate(dict(_BASE, verdict_scope="global"))
    with pytest.raises(ValidationError):
        Phase3Attempt.model_validate(dict(_BASE, config={}))
    # accepts every real attempt record
    base = _PROJ / "data" / "audit" / "chart_structure"
    for aid in ("3b_001", "3a_001", "3c_001"):
        a = load_phase3_attempt(base / f"phase3_attempt_{aid}.json")
        assert a.eval.eval_method and a.eval.cost_model
        assert a.eval.turnover_penalty
        assert isinstance(a.eval.vs_tabular_baseline, float)


def test_eval_block_declares_required_fields():
    """P3-A3: eval must declare eval_method / cost_model / turnover_penalty."""
    a = load_phase3_attempt(_ATTEMPT)
    assert a.eval.eval_method and a.eval.cost_model and a.eval.turnover_penalty
    assert isinstance(a.eval.oos_rank_ic, float)
    assert isinstance(a.eval.vs_tabular_baseline, float)


def test_negative_attempt_carries_root_cause_and_scope():
    """The real 3B attempt underperformed — it must root-cause that, and
    its verdict must be config-scoped (no blanket 'CNN/3B doesn't work')."""
    a = load_phase3_attempt(_ATTEMPT)
    assert a.verdict in ("no_significant_increment",
                         "underperforms_tabular_baseline")
    assert a.root_cause and len(a.root_cause) > 20
    assert a.verdict_scope == "config_scoped"


def test_config_records_what_was_used():
    a = load_phase3_attempt(_ATTEMPT)
    assert a.config and "epochs" in a.config and "fit_years" in a.config


def test_schema_rejects_negative_without_root_cause():
    bad = dict(_BASE)
    bad.pop("root_cause")
    with pytest.raises(ValidationError, match="root_cause"):
        Phase3Attempt.model_validate(bad)


def test_schema_rejects_global_verdict_scope():
    with pytest.raises(ValidationError):
        Phase3Attempt.model_validate(dict(_BASE, verdict_scope="global"))


def test_schema_rejects_empty_config():
    with pytest.raises(ValidationError, match="config"):
        Phase3Attempt.model_validate(dict(_BASE, config={}))


def test_positive_verdict_needs_no_root_cause():
    ok = dict(_BASE, verdict="beats_tabular_baseline")
    ok.pop("root_cause")
    Phase3Attempt.model_validate(ok)  # must not raise
