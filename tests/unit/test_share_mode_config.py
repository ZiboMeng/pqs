"""Tests for share-mode config passthrough (P0.5, 2026-04-20).

Before this fix:
  - config/risk.yaml::position_limits.allow_fractional_shares = false
  - but BacktestEngine default integer_shares=False (fractional)
  - and PaperTradingEngine default integer_shares=True
  → paper + backtest used DIFFERENT share modes; config was ignored by
    both. A future default flip would drift semantics undetected.

This test file codifies the contract:
  - The config field is the single source of truth.
  - All engines instantiated by production scripts/evaluators derive
    integer_shares = not allow_fractional_shares.
"""

from __future__ import annotations

from pathlib import Path

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.mining.evaluator import MiningEvaluator
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.backtest.backtest_engine import BacktestEngine


class TestConfigField:
    def test_config_field_exists_and_default_false(self):
        cfg = load_config(Path("config"))
        # config/risk.yaml should currently set it false (integer mode)
        assert hasattr(cfg.risk.position_limits, "allow_fractional_shares")
        assert cfg.risk.position_limits.allow_fractional_shares is False


class TestPaperEngineAcceptsIntegerMode:
    def test_paper_engine_applies_integer_shares(self, tmp_path):
        cfg = load_config(Path("config"))
        integer = not cfg.risk.position_limits.allow_fractional_shares
        engine = PaperTradingEngine(
            cost_model=CostModel(cfg.cost_model),
            pnl_tracker=PnLTracker(initial_capital=10_000),
            db_path=str(tmp_path / "x.db"),
            initial_capital=10_000,
            integer_shares=integer,
        )
        # The paper engine stores it + propagates to its internal
        # DailyEngine in run_day_daily. The attribute is the contract.
        assert engine._integer_shares is integer

    def test_paper_engine_default_is_integer(self, tmp_path):
        """Sanity: even if a caller forgets to pass integer_shares,
        default is True (conservative, matches current config)."""
        cfg = load_config(Path("config"))
        engine = PaperTradingEngine(
            cost_model=CostModel(cfg.cost_model),
            pnl_tracker=PnLTracker(initial_capital=10_000),
            db_path=str(tmp_path / "x.db"),
            initial_capital=10_000,
        )
        assert engine._integer_shares is True


class TestBacktestEngineAcceptsIntegerMode:
    def test_backtest_engine_passes_integer_shares(self):
        cfg = load_config(Path("config"))
        integer = not cfg.risk.position_limits.allow_fractional_shares
        eng = BacktestEngine(
            cost_model=CostModel(cfg.cost_model),
            initial_capital=10_000,
            integer_shares=integer,
        )
        assert eng._int_shares is integer


class TestMiningEvaluatorPropagates:
    def test_evaluator_accepts_integer_shares(self):
        cfg = load_config(Path("config"))
        ev = MiningEvaluator(
            cost_model=CostModel(cfg.cost_model),
            integer_shares=True,
        )
        assert ev._integer_shares is True

    def test_evaluator_default_backward_compat(self):
        cfg = load_config(Path("config"))
        ev = MiningEvaluator(cost_model=CostModel(cfg.cost_model))
        # Default False for back-compat with existing mining runs;
        # production passes True via run_mining.py.
        assert ev._integer_shares is False
