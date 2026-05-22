"""S4 (supplement PRD 2026-05-22) — config-vs-code drift cross-check.

Audit finding D1: `config/ml_allocation.yaml` declared risk controls
(sector cap, turnover cap, min-edge-to-trade, exit_policy) that NO code
path enforced — a config that "looks like it has risk controls" but is
hollow. S4 adds an explicit `enforcement_status` registry. This test is
the S4 gate: every control is registered, and every control marked
`enforced` has a real code path that demonstrably enforces it.
"""
import numpy as np
import pandas as pd
import pytest
import yaml

from core.research.allocation.constraints import apply_turnover_cap
from core.research.allocation.exit_policy import apply_signal_decay_exit
from core.research.allocation.score_to_weight import score_to_weight
from core.research.allocation.vol_target import apply_vol_target_overlay

PROJ = __import__("pathlib").Path(__file__).resolve().parents[4]
_ALLOC = yaml.safe_load((PROJ / "config/ml_allocation.yaml").read_text())
_STATUS = _ALLOC["enforcement_status"]
_VALID = {"enforced", "pending_S4", "roadmap", "disabled"}


class TestEnforcementRegistryWellFormed:
    def test_every_status_value_is_valid(self):
        bad = {k: v for k, v in _STATUS.items() if v not in _VALID}
        assert not bad, f"invalid enforcement_status values: {bad}"

    def test_every_declared_control_is_registered(self):
        """No control in constraints / risk_scaling / min_edge_to_trade /
        exit_policy may be absent from enforcement_status — that would be
        a silently-declared control (the D1 drift)."""
        declared = set(_ALLOC["constraints"].keys())
        declared |= set(_ALLOC.get("risk_scaling", {}).keys())
        declared |= {"min_edge_to_trade", "exit_policy"}
        # `note` is free text, not a control
        declared -= {"note"}
        missing = declared - set(_STATUS.keys())
        assert not missing, (
            f"controls declared but NOT in enforcement_status (silent "
            f"drift — D1): {sorted(missing)}")


class TestEnforcedControlsHaveRealCodePath:
    """Each control marked `enforced` must demonstrably bind."""

    def test_long_only_enforced(self):
        if _STATUS.get("long_only") != "enforced":
            pytest.skip("long_only not marked enforced")
        w = score_to_weight(pd.Series({"A": 0.9, "B": 0.5, "C": 0.1}),
                             mode="top_k_capped", top_k=3,
                             max_single_weight=1.0)
        assert (w >= 0.0).all()

    def test_no_margin_enforced(self):
        if _STATUS.get("no_margin") != "enforced":
            pytest.skip("no_margin not marked enforced")
        w = score_to_weight(pd.Series({"A": 0.9, "B": 0.5, "C": 0.1}),
                             mode="top_k_capped", top_k=3,
                             max_single_weight=1.0)
        assert w.sum() <= 1.0 + 1e-9

    def test_max_single_name_weight_enforced(self):
        if _STATUS.get("max_single_name_weight") != "enforced":
            pytest.skip("max_single_name_weight not marked enforced")
        cap = float(_ALLOC["constraints"]["max_single_name_weight"])
        w = score_to_weight(pd.Series({"A": 0.9, "B": 0.6}),
                             mode="top_k_capped", top_k=2,
                             max_single_weight=cap)
        assert w.max() <= cap + 1e-9

    def test_turnover_cap_enforced(self):
        if _STATUS.get("turnover_cap_daily") != "enforced":
            pytest.skip("turnover_cap_daily not marked enforced")
        cap = float(_ALLOC["constraints"]["turnover_cap_daily"])
        idx = pd.bdate_range("2022-01-03", periods=3)
        # a full reshuffle (turnover 2.0) on bar 1+2
        w = pd.DataFrame([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]],
                         index=idx, columns=["A", "B"])
        out = apply_turnover_cap(w, cap)
        per_bar = out.diff().abs().sum(axis=1).iloc[1:]
        assert (per_bar <= cap + 1e-9).all()

    def test_exit_policy_enforced(self):
        if _STATUS.get("exit_policy") != "enforced":
            pytest.skip("exit_policy not marked enforced")
        thr = float(_ALLOC["exit_policy"]["signal_decay"]["exit_when_rank_below"])
        idx = pd.bdate_range("2022-01-03", periods=1)
        w = pd.DataFrame([[0.5, 0.5]], index=idx, columns=["A", "B"])
        rank = pd.DataFrame([[0.9, thr - 0.1]], index=idx, columns=["A", "B"])
        out = apply_signal_decay_exit(w, rank, exit_threshold=thr)
        assert out.iloc[0]["A"] == 0.5        # A above threshold — held
        assert out.iloc[0]["B"] == 0.0        # B decayed — exited

    def test_target_vol_enforced(self):
        if _STATUS.get("target_vol") != "enforced":
            pytest.skip("target_vol not marked enforced")
        rng = np.random.default_rng(0)
        idx = pd.bdate_range("2021-01-04", periods=200)
        syms = ["A", "B", "C"]
        close = pd.DataFrame(
            100 * np.cumprod(1 + rng.normal(0, 0.035, (200, 3)), axis=0),
            index=idx, columns=syms)
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        scaled = apply_vol_target_overlay(w, close, target_vol=0.15)
        assert scaled.iloc[80:].sum(axis=1).max() < 0.99   # de-risked


class TestPendingControlsAreExplicit:
    def test_s4_pending_set_resolved(self):
        """S4 closeout: no control may remain `pending_S4`. turnover +
        exit_policy were implemented & enforced; min_edge_to_trade was
        attempted, root-caused as whipsaw-prone, and moved to `roadmap`
        (S4 R12) — every control now has a terminal status."""
        pending = {k for k, v in _STATUS.items() if v == "pending_S4"}
        assert pending == set()
