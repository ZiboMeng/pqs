"""Codex round-16 follow-up regression tests.

Verifies that ``cfg.acceptance`` flows into ``MiningEvaluator``'s internal
``WindowAnalyzer`` construction. Without this wire, a researcher who edits
``config/acceptance.yaml`` would not see Tier D / walk-forward gate
behavior change in the mining pipeline.

Reverse-validation: revert
``core/mining/evaluator.py:_run_walk_forward`` to construct
``WindowAnalyzer(engine=engine)`` (without the ``thresholds`` kwarg) and
``test_mining_evaluator_passes_thresholds_to_window_analyzer`` will fail.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from core.config.schemas import (
    AcceptanceThresholds,
    TierDThresholds,
)
from core.config.schemas.cost_model import CostModelConfig, CostTierConfig
from core.execution.cost_model import CostModel
from core.mining.evaluator import MiningEvaluator


def _make_cost_model() -> CostModel:
    cfg = CostModelConfig(
        tiers={
            "default": CostTierConfig(
                symbols=[], commission_bps=0.5,
                slippage_interday_bps=3.0, slippage_intraday_bps=5.0,
            )
        }
    )
    return CostModel(cfg)


def test_mining_evaluator_stores_acceptance_thresholds():
    """Construction stores the kwarg; default is None."""
    ev_default = MiningEvaluator(cost_model=_make_cost_model())
    assert ev_default._acceptance_thresholds is None

    custom = AcceptanceThresholds(tier_d=TierDThresholds(min_ir_vs_spy=0.55))
    ev_with = MiningEvaluator(
        cost_model=_make_cost_model(),
        acceptance_thresholds=custom,
    )
    assert ev_with._acceptance_thresholds is custom


def test_mining_evaluator_passes_thresholds_to_window_analyzer():
    """``_run_walk_forward`` must build WindowAnalyzer with the injected
    thresholds. We patch WindowAnalyzer so the body short-circuits without
    needing a full panel; we only care about the constructor kwargs.

    Reverse-validation cue: revert evaluator.py to ``WindowAnalyzer(engine=engine)``
    and the captured kwargs will not contain ``thresholds``, failing the assert.
    """
    custom = AcceptanceThresholds(tier_d=TierDThresholds(min_ir_vs_spy=0.77))
    ev = MiningEvaluator(
        cost_model=_make_cost_model(),
        acceptance_thresholds=custom,
    )

    captured_kwargs = {}

    def _fake_window_analyzer(*args, **kwargs):
        captured_kwargs.update(kwargs)
        # Return a mock that lets the rest of _run_walk_forward short-
        # circuit cleanly: walk_forward returns []; the "no windows" branch
        # then returns an early metrics dict. Calling this short branch is
        # enough — we never invoke private code with real data.
        m = MagicMock()
        m.walk_forward.return_value = []
        return m

    # Path that builds WindowAnalyzer is _run_walk_forward. Provide
    # minimal args so the call reaches the WindowAnalyzer line: spec,
    # price_df, regime_series, benchmark_series, risk/def universes.
    import pandas as pd
    from core.mining.strategy_space import StrategySpec

    spec = StrategySpec(
        strategy_type="multi_factor",
        params={
            "features": ("ret_5d", "rs_vs_spy_126d", "hl_range"),
            "weights":  (1.0, 1.0, 1.0),
            "lag":      1,
            "top_n":    10,
        },
    )
    import numpy as np
    n = 1000
    idx = pd.bdate_range("2018-01-02", periods=n)
    syms = ["SPY", "QQQ", "AAPL", "MSFT"]
    price_df = pd.DataFrame(
        {s: 100.0 * np.power(1.0001, np.arange(n)) for s in syms},
        index=idx,
    )
    regime = pd.Series("BULL", index=idx)
    benchmark = price_df["SPY"]

    # WindowAnalyzer is imported inside _run_walk_forward, so we patch
    # the source module attribute (which the local `from ... import` resolves
    # at call time).
    captured_exc: list = []
    with patch(
        "core.backtest.window_analyzer.WindowAnalyzer",
        side_effect=_fake_window_analyzer,
    ):
        try:
            ev._run_walk_forward(  # type: ignore[attr-defined]
                spec, price_df, regime, benchmark,
                risk_universe=syms, def_universe=[],
            )
        except Exception as exc:
            # _run_walk_forward may raise downstream of the short-
            # circuited analyzer; the assert below is the contract we
            # care about. Capture exception for diagnostic if assertion fails.
            captured_exc.append(exc)

    assert "thresholds" in captured_kwargs, (
        f"WindowAnalyzer must be constructed with `thresholds=` kwarg; "
        f"got kwargs={list(captured_kwargs.keys())}; "
        f"upstream exception (if any): {captured_exc!r}"
    )
    assert captured_kwargs["thresholds"] is custom, (
        f"thresholds kwarg must be the injected AcceptanceThresholds "
        f"instance; got {captured_kwargs['thresholds']!r}"
    )
