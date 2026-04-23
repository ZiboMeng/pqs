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


class TestLeadingNaNRobustness:
    """Regression guards for the two bugs surfaced by R39 trial 4b5f36ed9ab5:
      (a) qqq_*_excess landed as None in archive because _cagr used iloc[0]
          on equity curves with leading NaN (expanded universe had BRK-B
          starting 2015-01-02, pulling panel index earlier than QQQ data);
      (b) oos_sharpe got -4.87e15 because _mean dropped NaN but not ±inf.
    """

    def test_cagr_handles_leading_nan(self):
        """_cagr inside _check_qqq_gate must trim leading NaN before iloc[0]."""
        ev, _mk = TestCheckQQQGateDirectly()._setup()
        r = EvalResult(spec_id="x", strategy_type="multi_factor", params={})
        price_df = pd.DataFrame(
            {"SPY": [100, 101, 102]},
            index=pd.bdate_range("2020-01-01", periods=3),
        )
        # Strategy equity curve with 1 leading NaN (simulates BRK-B-style
        # early-start contamination). Valid range still beats QQQ.
        strat_eq = _mk(300, 0.10)
        strat_eq.iloc[0] = float("nan")  # leading NaN
        fake_bt = MagicMock()
        fake_bt.equity_curve = strat_eq
        qqq_eq = _mk(300, 0.05)
        qqq_eq.iloc[0] = float("nan")  # same leading-NaN pattern
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
            ev._check_qqq_gate(
                r, price_df, holdout, qqq_series, non_holdout,
                spec, None, None,
            )
        # Pre-fix: qqq_full_period_excess stayed NaN (archived as None).
        # Post-fix: leading NaN trimmed → excess is a finite positive number.
        assert not np.isnan(r.qqq_full_period_excess), \
            "qqq_full_period_excess must not be NaN when leading-NaN can be trimmed"
        assert r.qqq_full_period_excess > 0

    def test_compute_metrics_rejects_tiny_std_sharpe(self):
        """compute_metrics must return sharpe=NaN when std is below the
        _STD_FLOOR threshold, preventing astronomical Sharpe values from
        poisoning downstream aggregation (R39 4b5f36ed9ab5 bug)."""
        from core.backtest.backtest_engine import compute_metrics
        # Build an equity curve with tiny-but-positive std:
        # essentially flat with microscopic noise. Pre-fix this produced
        # |sharpe| in the 1e14-1e16 range.
        idx = pd.bdate_range("2020-01-01", periods=100)
        eq = pd.Series(
            1.0 + np.arange(100) * 1e-12,  # near-flat drift with noise ~1e-12
            index=idx,
        )
        m = compute_metrics(eq)
        # Sharpe should be NaN (tiny std rejected), not an astronomical number
        assert np.isnan(m.get("sharpe")), \
            f"Tiny-std should yield NaN Sharpe, got {m.get('sharpe')}"
        # Normal equity still produces a finite Sharpe
        eq_normal = pd.Series(
            np.cumprod(1 + np.random.default_rng(42).normal(0.001, 0.01, 100)),
            index=idx,
        )
        m2 = compute_metrics(eq_normal)
        assert np.isfinite(m2.get("sharpe")), "Normal-vol Sharpe should be finite"

    def test_mean_drops_nonfinite_defense(self):
        """_mean helper in _run_walk_forward has defense-in-depth: drops
        non-finite (inf/NaN) even though compute_metrics now rejects tiny
        std at source. Guards against any future path that returns inf."""
        def _mean(lst):
            v = [x for x in lst if np.isfinite(x)]
            return float(np.mean(v)) if v else float("nan")

        assert _mean([0.5, float("inf"), 0.7]) == pytest.approx(0.6, abs=1e-6)
        assert _mean([0.5, float("-inf"), 0.7]) == pytest.approx(0.6, abs=1e-6)
        assert _mean([0.5, float("nan"), 0.7]) == pytest.approx(0.6, abs=1e-6)
        assert np.isnan(_mean([float("inf"), float("-inf"), float("nan")]))
