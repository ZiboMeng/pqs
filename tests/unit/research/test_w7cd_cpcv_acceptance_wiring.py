"""P0-B W7c/d — CPCV-distribution fold acceptance wired as a BINDING
new-cycle gate in the production evaluator (G4 §4).

Rigor (no 走过场): (1) legacy byte-identical (no cpcv_inputs → None,
gates/overall unchanged — no retro mutation of cycle06/08); (2)
new-cycle strong edge → gate passes; (3) noise/insufficient/error →
fail-closed, overall_passed flips False (binding, never silent pass).
"""
import numpy as np
import pytest

import core.research.temporal_split_acceptance as tsa
from core.research.temporal_split_acceptance import (
    SplitAcceptanceResult,
    run_split_acceptance,
)


def _bare(passed=True):
    return SplitAcceptanceResult(
        role="core_alpha", split_name="x", gates=[],
        overall_passed=passed, evaluated_at="2026-05-18")


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(tsa, "evaluate_candidate",
                        lambda m, c, role: _bare(True))
    monkeypatch.setattr(tsa, "load_temporal_split", lambda p: object())


def _edge(n, edge, seed):
    rng = np.random.default_rng(seed)
    fwd = rng.standard_normal(n)
    pred = edge * fwd + rng.standard_normal(n)
    return pred.tolist(), fwd.tolist()


def test_legacy_no_cpcv_inputs_byte_identical():
    res = run_split_acceptance({"legacy": 1}, "core_alpha", split_path="d")
    assert res.cpcv_acceptance is None
    assert "cpcv_acceptance" not in res.as_dict()
    assert res.overall_passed is True
    assert len(res.gates) == 0          # no gate appended, no mutation


def test_new_cycle_strong_edge_gate_passes():
    pred, fwd = _edge(2000, 0.8, 1)
    res = run_split_acceptance(
        {"cpcv_inputs": {"pred": pred, "fwd": fwd,
                         "honest_n_trials": 200}},
        "core_alpha", split_path="d")
    assert res.cpcv_acceptance is not None
    assert "cpcv_acceptance" in res.as_dict()
    g = [x for x in res.gates if x.name == "cpcv_distribution_acceptance"]
    assert len(g) == 1 and g[0].passed is True
    assert res.overall_passed is True


def test_noise_edge_fail_closed_flips_overall():
    pred, fwd = _edge(2000, 0.0, 2)        # no real edge
    res = run_split_acceptance(
        {"cpcv_inputs": {"pred": pred, "fwd": fwd,
                         "honest_n_trials": 200,
                         "min_ic_sample_weighted": 0.05}},
        "core_alpha", split_path="d")
    g = [x for x in res.gates if x.name == "cpcv_distribution_acceptance"][0]
    assert g.passed is False
    assert res.overall_passed is False    # binding, fail-closed


def test_insufficient_folds_fail_closed():
    res = run_split_acceptance(
        {"cpcv_inputs": {"pred": [1.0, 2.0, 3.0], "fwd": [1.0, 2.0, 3.0],
                         "honest_n_trials": 50}},
        "core_alpha", split_path="d")
    g = [x for x in res.gates if x.name == "cpcv_distribution_acceptance"][0]
    assert g.passed is False
    assert res.overall_passed is False
    assert res.cpcv_acceptance.get("insufficient") is True


def test_error_path_fail_closed_not_silent():
    # pred present but malformed (non-numeric) → cpcv errors → must
    # fail-closed, NOT silently pass.
    res = run_split_acceptance(
        {"cpcv_inputs": {"pred": "garbage", "fwd": None,
                         "honest_n_trials": 50}},
        "core_alpha", split_path="d")
    assert res.overall_passed is False
    g = [x for x in res.gates if x.name == "cpcv_distribution_acceptance"][0]
    assert g.passed is False
