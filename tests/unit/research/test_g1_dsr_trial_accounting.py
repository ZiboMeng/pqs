"""G1-A4 — DSR honest trial-count accounting + ONC + recompute tests.

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G1.
"""
import numpy as np
import pytest

from core.research.dsr_trial_accounting import (
    ML_REDO_CHART_NATIVE_ARMS,
    ML_REDO_P2_RECHECK_K_SWEEP,
    assert_honest_n,
)
from core.research.overfit_metrics import (
    deflated_sharpe_ratio,
    effective_n_trials_onc,
    recompute_dsr,
)


def test_accounting_constants_documented_values():
    # ralph-loop PRD §3: arms = {mae_probe, gaf_tree}; K-sweep ∈ {6,8,12}
    assert ML_REDO_CHART_NATIVE_ARMS == 2
    assert ML_REDO_P2_RECHECK_K_SWEEP == 3


def test_assert_honest_n_guard():
    assert assert_honest_n(2, source="t") == 2
    assert assert_honest_n(200, source="t") == 200
    for bad in (1, 0, -3, 3.0, "3", None):
        with pytest.raises(ValueError):
            assert_honest_n(bad, source="t")  # type: ignore[arg-type]


def test_onc_correlated_configs_reduce_effective_n():
    rng = np.random.default_rng(42)
    base = rng.standard_normal((300, 1))
    # 8 configs that are 4 near-duplicate pairs → ~4 independent clusters
    cols = []
    for i in range(4):
        b = rng.standard_normal((300, 1))
        cols += [b + 0.01 * rng.standard_normal((300, 1)),
                 b + 0.01 * rng.standard_normal((300, 1))]
    M = np.hstack(cols)
    r = effective_n_trials_onc(M)
    assert r["n_configs"] == 8
    assert 2 <= r["effective_n"] <= 6  # well below 8 (dup pairs collapse)


def test_onc_degenerate_inputs():
    assert effective_n_trials_onc(np.zeros((100, 1)))["effective_n"] == 1
    one_d = effective_n_trials_onc(np.zeros(50))
    assert one_d["effective_n"] == 1


def test_recompute_dsr_higher_n_not_higher_dsr():
    rng = np.random.default_rng(7)
    rets = 0.001 + 0.01 * rng.standard_normal(500)
    out = recompute_dsr(rets, honest_n_trials=200, prior_n_trials=3)
    assert out["honest_n_trials"] == 200
    assert out["prior_n_trials"] == 3
    # more honest trials ⇒ stronger selection-bias haircut ⇒ DSR ≤ prior
    assert out["dsr_honest"] <= out["dsr_prior_placeholder"] + 1e-9
    assert out["direction_ok"] is True


def test_recompute_dsr_matches_deflated_for_same_n():
    rng = np.random.default_rng(11)
    rets = 0.0005 + 0.008 * rng.standard_normal(400)
    direct = deflated_sharpe_ratio(rets, 5)["deflated_sharpe"]
    via = recompute_dsr(rets, honest_n_trials=5)["dsr_honest"]
    assert via == pytest.approx(direct, rel=1e-12)


def test_recompute_dsr_degenerate_returns_graceful():
    out = recompute_dsr([0.0] * 4, honest_n_trials=2)
    assert np.isnan(out["dsr_honest"])
