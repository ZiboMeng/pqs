"""Round 7 Topic I (2026-04-20): mining cross-strategy-type invariants.

Real mining run at --trials 5 per type × 4 types produced 15 non-
multi_factor trials archived with correct lineage_tag, consistent
tier='D' (none passed OOS, same signal as Round 1). This file
codifies the underlying invariants:

  1. ALL_SPACES contains 4 registered types
  2. Every space.instantiate(minimal_params) returns a strategy
     object exposing `.generate()` so it's usable by the miner
  3. Archive schema preserves `strategy_type` across all types
  4. Each space's suggest() can be probed with a mock Optuna trial
     without crashing

Tests use light-weight stubs so this runs fast (<1s), unlike real
mining runs.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.mining.archive import MiningArchive
from core.mining.evaluator import EvalResult
from core.mining.strategy_space import (
    ALL_SPACES,
    StrategySpec,
    instantiate_strategy,
    DualMomentumSpace,
    TrendFollowingSpace,
    CrossAssetRotationSpace,
    MultiFactorSpace,
)


class _FakeTrial:
    """Minimal Optuna-trial stub: each suggest_* returns a
    deterministic value roughly in range."""

    def __init__(self):
        self._calls = 0

    def suggest_int(self, name, low, high, step=1):
        # Return the middle of the range; step-aligned
        mid = low + ((high - low) // 2 // step) * step
        self._calls += 1
        return mid

    def suggest_float(self, name, low, high, step=None):
        self._calls += 1
        return (low + high) / 2.0

    def suggest_categorical(self, name, choices):
        self._calls += 1
        return choices[0]


class TestAllSpacesRegistered:

    def test_all_spaces_has_four_entries(self):
        assert len(ALL_SPACES) == 4

    def test_all_expected_types_present(self):
        types = {s.strategy_type for s in ALL_SPACES}
        assert types == {
            "dual_momentum", "trend_following",
            "cross_asset_rotation", "multi_factor",
        }

    def test_each_type_unique(self):
        types = [s.strategy_type for s in ALL_SPACES]
        assert len(types) == len(set(types))


class TestSpaceSuggest:
    """Each space.suggest() should accept a FakeTrial without crashing
    and return a dict with the keys downstream instantiate() expects."""

    @pytest.mark.parametrize("space_cls", [
        DualMomentumSpace,
        TrendFollowingSpace,
        CrossAssetRotationSpace,
        MultiFactorSpace,
    ])
    def test_suggest_returns_dict(self, space_cls):
        space = space_cls()
        params = space.suggest(_FakeTrial())
        assert isinstance(params, dict)
        assert len(params) > 0


class TestInstantiateAllTypes:

    @pytest.mark.parametrize("space_cls", [
        DualMomentumSpace,
        TrendFollowingSpace,
        CrossAssetRotationSpace,
        MultiFactorSpace,
    ])
    def test_instantiate_produces_strategy_with_generate(self, space_cls):
        space = space_cls()
        params = space.suggest(_FakeTrial())
        strat = space.instantiate(
            params,
            risk_universe=["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "SPY"],
            def_universe=["TLT", "IEF"],
        )
        assert hasattr(strat, "generate"), (
            f"{space_cls.__name__} produced object without .generate()"
        )

    def test_instantiate_strategy_dispatch_works(self):
        """`instantiate_strategy` factory dispatch handles all 4 types."""
        for space_cls in (DualMomentumSpace, TrendFollowingSpace,
                          CrossAssetRotationSpace, MultiFactorSpace):
            space = space_cls()
            params = space.suggest(_FakeTrial())
            spec = StrategySpec.from_dict(space.strategy_type, params)
            strat = instantiate_strategy(
                spec,
                risk_universe=["AAPL", "MSFT", "SPY"],
                def_universe=["TLT", "IEF"],
            )
            assert hasattr(strat, "generate")


class TestArchivePreservesStrategyType:
    """Archive reads/writes must preserve `strategy_type` for all 4
    types so leaderboard / analysis can cross-filter correctly."""

    def _tmpdir(self):
        return Path(tempfile.mkdtemp())

    def test_all_four_types_roundtrip(self):
        d = self._tmpdir()
        arch = MiningArchive(
            db_path=d / "a.db",
            equity_curve_dir=d / "ec",
            lineage_tag="test-all-types",
        )
        for stype in ("dual_momentum", "trend_following",
                      "cross_asset_rotation", "multi_factor"):
            r = EvalResult(
                spec_id=f"{stype}_spec1",
                strategy_type=stype,
                params={"x": 1},
            )
            r.passed_quick = True
            r.tier = "D"
            r.composite_score = -1.0
            arch.save_eval(r)

        df = arch.leaderboard(n=20)
        assert set(df["strategy_type"]) == {
            "dual_momentum", "trend_following",
            "cross_asset_rotation", "multi_factor",
        }
        # lineage_tag preserved on all 4
        assert set(df["lineage_tag"]) == {"test-all-types"}


class TestTierAssignmentTypeAgnostic:
    """_assign_tier must demote trials of ANY type when passed_qqq_gate
    is False. The gate can't be bypassed by strategy type."""

    def test_gate_fail_forces_D_across_types(self):
        from core.mining.evaluator import MiningEvaluator
        from core.config.loader import load_config
        from core.execution.cost_model import CostModel

        cfg = load_config(Path("config"))
        ev = MiningEvaluator(cost_model=CostModel(cfg.cost_model))
        for stype in ("dual_momentum", "trend_following",
                      "cross_asset_rotation", "multi_factor"):
            r = EvalResult(spec_id="x", strategy_type=stype, params={})
            r.passed_quick = True
            r.passed_oos = True
            r.oos_ir = 0.5
            r.oos_is_sharpe_ratio = 0.8
            r.passed_robustness = True
            r.passed_holdout = True
            r.passed_qqq_gate = False  # THE gate flag
            tier = ev._assign_tier(r)
            assert tier == "D", (
                f"strategy_type={stype}: _assign_tier returned {tier} "
                "when passed_qqq_gate=False; gate must apply regardless "
                "of strategy type"
            )
