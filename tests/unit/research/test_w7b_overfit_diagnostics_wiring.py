"""P0-B W7b — SOTA overfit diagnostics wired into the production
acceptance evaluator (new-cycle-only, additive, no retro mutation).

Rigor (no 走过场): assert (1) legacy back-compat is byte-identical
(no overfit_inputs → field None, key absent), (2) new-cycle path
populates honest-N DSR + MinBTL fail-closed gate, (3) the honest-N
guard rejects a magic literal instead of silently passing.
"""
import numpy as np
import pytest

import core.research.temporal_split_acceptance as tsa
from core.research.temporal_split_acceptance import (
    SplitAcceptanceResult,
    build_overfit_diagnostics,
    run_split_acceptance,
)


def _bare_result():
    return SplitAcceptanceResult(
        role="core_alpha", split_name="x", gates=[],
        overall_passed=True, evaluated_at="2026-05-18")


def test_legacy_as_dict_byte_identical_no_overfit_key():
    r = _bare_result()
    assert r.overfit_diagnostics is None
    assert "overfit_diagnostics" not in r.as_dict()  # lazy-migration


def test_runner_no_overfit_inputs_leaves_result_unchanged(monkeypatch):
    monkeypatch.setattr(tsa, "evaluate_candidate",
                        lambda m, c, role: _bare_result())
    monkeypatch.setattr(tsa, "load_temporal_split", lambda p: object())
    monkeypatch.setattr(tsa, "resolve_split_path",
                        lambda role, freeze_date: "dummy", raising=False)
    res = run_split_acceptance({"some": "legacy_metrics"}, "core_alpha",
                               split_path="dummy")
    assert res.overfit_diagnostics is None        # cycle06/08 path


def test_runner_attaches_for_new_cycle(monkeypatch):
    monkeypatch.setattr(tsa, "evaluate_candidate",
                        lambda m, c, role: _bare_result())
    monkeypatch.setattr(tsa, "load_temporal_split", lambda p: object())
    rng = np.random.default_rng(0)
    rets = 0.0006 + 0.011 * rng.standard_normal(2500)   # ~10y daily
    metrics = {"overfit_inputs": {
        "strat_ret_d": rets.tolist(),
        "honest_n_trials": 200,
        "actual_years": 10.0}}
    res = run_split_acceptance(metrics, "core_alpha", split_path="d")
    od = res.overfit_diagnostics
    assert od is not None and "overfit_diagnostics" in res.as_dict()
    assert od["dsr_n_trials"] == 200
    assert od["dsr"] is not None
    assert "min_btl_gate" in od and "passed" in od["min_btl_gate"]
    assert od["pbo"]["pbo"] is None and "forward-only" in od["pbo"]["note"]


def test_minbtl_fail_closed_when_history_too_short():
    rng = np.random.default_rng(1)
    rets = 0.0004 + 0.012 * rng.standard_normal(400)
    od = build_overfit_diagnostics(rets, honest_n_trials=200,
                                    actual_years=1.5)   # way < MinBTL
    assert od["min_btl_gate"]["passed"] is False
    assert od["dsr_n_trials"] == 200


def test_honest_n_guard_rejects_magic_literal():
    rng = np.random.default_rng(2)
    rets = 0.001 + 0.01 * rng.standard_normal(500)
    with pytest.raises(ValueError):
        build_overfit_diagnostics(rets, honest_n_trials=1,
                                   actual_years=5.0)   # not silent pass


def test_pbo_computed_when_matrix_supplied():
    rng = np.random.default_rng(3)
    rets = 0.0005 + 0.01 * rng.standard_normal(800)
    mat = rng.standard_normal((200, 12))
    od = build_overfit_diagnostics(rets, 50, 8.0,
                                    per_trial_period_perf=mat)
    assert od["pbo"]["pbo"] is not None
    assert 0.0 <= od["pbo"]["pbo"] <= 1.0
    assert od["pbo"]["auto_kill"] is False
