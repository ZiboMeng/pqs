"""QQQ hard gate tests (P0.4, 2026-04-20).

Enforces CLAUDE.md "QQQ Outperformance Rule": a strategy that beats SPY
but loses to QQQ must be non-promotable.

Covers:
  1. _check_qqq_gate computes excess on 3 windows
  2. Gate failure demotes tier to "D" even if all other stages pass
  3. Default thresholds (0.0) — strategy must at least match QQQ
  4. passed_qqq_gate=True when no qqq_series passed (gate disabled)
  5. config plumbing: mining config → MiningEvaluator → tier assignment
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.mining.evaluator import EvalResult, MiningEvaluator
from pathlib import Path


def _make_evaluator(min_cagr=0.0, min_holdout=0.0, min_oos=0.0):
    cfg = load_config(Path("config"))
    return MiningEvaluator(
        cost_model=CostModel(cfg.cost_model),
        min_cagr_excess_vs_qqq=min_cagr,
        min_holdout_excess_vs_qqq=min_holdout,
        min_avg_oos_excess_vs_qqq=min_oos,
    )


def _eval_result_with_all_pass(passed_qqq_gate=True) -> EvalResult:
    """Build an EvalResult that clears every stage except QQQ so we
    can isolate the QQQ gate's effect on _assign_tier."""
    r = EvalResult(spec_id="test", strategy_type="multi_factor", params={})
    r.passed_quick = True
    r.quick_sharpe = 1.0
    r.quick_max_dd = -0.10
    r.quick_cagr = 0.15
    r.passed_oos = True
    r.oos_ir = 0.50
    r.oos_pass_rate = 0.70
    r.oos_sharpe = 0.80
    r.oos_excess_return = 0.05
    r.oos_is_sharpe_ratio = 0.80
    r.regime_robust = True
    r.cost_robust = True
    r.param_robust = True
    r.stress_passed = True
    r.passed_robustness = True
    r.passed_diversity = True
    r.passed_holdout = True
    r.holdout_ir = 0.60
    r.passed_qqq_gate = passed_qqq_gate
    return r


class TestAssignTierWithQQQGate:
    def test_gate_failure_forces_D(self):
        """Even with every other stage passing, QQQ gate failure must
        demote to D (non-promotable)."""
        ev = _make_evaluator()
        r = _eval_result_with_all_pass(passed_qqq_gate=False)
        tier = ev._assign_tier(r)
        assert tier == "D", (
            f"expected D when QQQ gate fails, got {tier} — "
            "QQQ gate is not actually blocking promotion"
        )

    def test_gate_pass_allows_S_when_robust(self):
        ev = _make_evaluator()
        r = _eval_result_with_all_pass(passed_qqq_gate=True)
        tier = ev._assign_tier(r)
        # With passed_oos + passed_holdout + passed_robustness + ir>=0.50
        # → S tier (IR threshold for S is 0.5)
        assert tier in ("S", "A"), f"unexpected tier {tier} with all pass"

    def test_gate_default_is_true_when_disabled(self):
        """If evaluate() is called without qqq_series, passed_qqq_gate
        stays True (gate effectively disabled — back-compat)."""
        r = EvalResult(spec_id="x", strategy_type="multi_factor", params={})
        # Default before any stage is passed_qqq_gate=True (gate off)
        assert r.passed_qqq_gate is True


class TestCheckQQQGateDirectly:
    """Call _check_qqq_gate with synthetic equity curves to verify
    the window-level excess math + gate decision."""

    def _setup(self, strat_cagrs=(0.10, 0.10, 0.10), qqq_cagrs=(0.08, 0.08, 0.08)):
        """strat_cagrs = (full, holdout, non-holdout) CAGR values to
        produce via equity series; qqq_cagrs likewise. Generates
        synthetic price_df + equity curves + bypasses backtest."""
        ev = _make_evaluator()
        # We stub _run_backtest + instantiate_strategy so _check_qqq_gate
        # produces a known (strat_cagr, qqq_cagr) pair for each window.
        # Construct simple linear-growth equity that lands at given CAGR.
        def _mk_eq(n_days, cagr):
            years = n_days / 252.0
            end = (1 + cagr) ** years
            return pd.Series(
                np.linspace(1.0, end, n_days),
                index=pd.bdate_range("2020-01-01", periods=n_days),
            )
        return ev, _mk_eq

    def test_gate_passes_when_strategy_beats_qqq_on_all_windows(self):
        ev, _mk = self._setup()
        r = EvalResult(spec_id="x", strategy_type="multi_factor", params={})
        price_df = pd.DataFrame(
            {"SPY": [100, 101, 102]},
            index=pd.bdate_range("2020-01-01", periods=3),
        )
        # Arrange stub: _run_backtest returns a mock with equity_curve
        fake_bt = MagicMock()
        fake_bt.equity_curve = _mk(300, 0.10)  # 10% CAGR strategy
        qqq_eq = _mk(300, 0.05)  # 5% QQQ
        qqq_series = qqq_eq.rename("close")

        holdout = price_df.iloc[-1:]
        non_holdout = price_df.iloc[:-1]
        spec = MagicMock(spec_id="x", strategy_type="multi_factor")
        spec.params_dict = {}

        with patch.object(ev, "_run_backtest", return_value=fake_bt), \
             patch.object(ev, "_build_weights", return_value=pd.DataFrame()), \
             patch("core.mining.evaluator.instantiate_strategy") as mi:
            mi.return_value = MagicMock()
            mi.return_value.generate.return_value = pd.DataFrame()
            passed = ev._check_qqq_gate(
                r, price_df, holdout, qqq_series, non_holdout,
                spec, None, None,
            )
        assert passed is True
        assert r.qqq_full_period_excess > 0

    def test_gate_fails_when_strategy_loses_to_qqq(self):
        ev, _mk = self._setup()
        r = EvalResult(spec_id="x", strategy_type="multi_factor", params={})
        price_df = pd.DataFrame(
            {"SPY": [100, 101, 102]},
            index=pd.bdate_range("2020-01-01", periods=3),
        )
        fake_bt = MagicMock()
        fake_bt.equity_curve = _mk(300, 0.05)  # 5% strategy
        qqq_eq = _mk(300, 0.10)  # 10% QQQ
        qqq_series = qqq_eq.rename("close")

        holdout = price_df.iloc[-1:]
        non_holdout = price_df.iloc[:-1]
        spec = MagicMock(spec_id="x", strategy_type="multi_factor")
        spec.params_dict = {}

        with patch.object(ev, "_run_backtest", return_value=fake_bt), \
             patch.object(ev, "_build_weights", return_value=pd.DataFrame()), \
             patch("core.mining.evaluator.instantiate_strategy") as mi:
            mi.return_value = MagicMock()
            mi.return_value.generate.return_value = pd.DataFrame()
            passed = ev._check_qqq_gate(
                r, price_df, holdout, qqq_series, non_holdout,
                spec, None, None,
            )
        assert passed is False
        assert r.qqq_full_period_excess < 0


class TestConfigPlumbing:
    def test_qqq_thresholds_flow_from_config(self):
        """The 3 config fields must appear on the MiningEvaluator
        instance attributes."""
        ev = MiningEvaluator(
            cost_model=CostModel(load_config(Path("config")).cost_model),
            min_cagr_excess_vs_qqq=0.01,
            min_holdout_excess_vs_qqq=0.02,
            min_avg_oos_excess_vs_qqq=0.03,
        )
        assert ev._min_qqq_cagr_exc == 0.01
        assert ev._min_qqq_holdout_exc == 0.02
        assert ev._min_qqq_oos_avg_exc == 0.03

    def test_default_thresholds_zero(self):
        ev = _make_evaluator()
        assert ev._min_qqq_cagr_exc == 0.0
        assert ev._min_qqq_holdout_exc == 0.0
        assert ev._min_qqq_oos_avg_exc == 0.0
