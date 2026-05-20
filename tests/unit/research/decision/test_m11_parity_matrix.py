"""PRD-X v2 Phase X4 — M11 parity matrix for 7 production strategies.

AC (PRD §11 X4):
  - 6 .generate()-based strategies × GenerateStrategyAdapter(mode='off')
    produces output BIT-IDENTICAL to direct .generate() call.
  - 1 intraday_reversal strategy already satisfies the 4-method
    DecisionPolicy Protocol natively (the §F.2 blueprint).
  - All 7 work with the X4 ExecutionPolicy wrapper around
    DeferredExecutionSchedule.
  - bit-identical means: same panel (DataFrame.equals == True with
    NaN handling), zero PYTHONHASHSEED dependence.

This test surfaces the X1 mock-only test gap (per
feedback_audit_surfaces_not_thorough): X1 mock had signature
``generate(date, ctx)`` but real strategies use
``generate(price_df, regime_series, [volume_df])``. The X4 fix
introduced inspect-based kwarg filtering to preserve both mock and
real-strategy parity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.research.decision import GenerateStrategyAdapter
from core.signals.strategies.confirmation_pattern import (
    ConfirmationPatternStrategy,
)
from core.signals.strategies.cross_asset_rotation import (
    CrossAssetRotationStrategy,
)
from core.signals.strategies.dual_momentum import DualMomentumStrategy
from core.signals.strategies.multi_factor import MultiFactorStrategy
from core.signals.strategies.simple_baseline import SimpleBaselineStrategy
from core.signals.strategies.trend_following import TrendFollowingStrategy


# ── synthetic fixture ───────────────────────────────────────────────
def _make_synth_panel(n_days=500, n_symbols=8, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    syms = [f"S{i:02d}" for i in range(n_symbols)]
    # synthetic prices: random-walk with drift
    rets = rng.normal(loc=0.0003, scale=0.015, size=(n_days, n_symbols))
    rets[0] = 0.0
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    price_df = pd.DataFrame(prices, index=dates, columns=syms)
    volume_df = pd.DataFrame(
        rng.uniform(1e5, 1e7, size=(n_days, n_symbols)),
        index=dates, columns=syms)
    # synthetic regime: "NEUTRAL" everywhere (string per RegimeState.value)
    regime_series = pd.Series("NEUTRAL", index=dates, dtype=str)
    return price_df, volume_df, regime_series


@pytest.fixture(scope="module")
def synth():
    return _make_synth_panel()


# ── per-strategy parity tests ───────────────────────────────────────
def _assert_panels_equal(direct: pd.DataFrame, via_adapter: pd.DataFrame,
                          strategy_name: str):
    assert direct.shape == via_adapter.shape, (
        f"{strategy_name}: shape mismatch direct {direct.shape} vs "
        f"adapter {via_adapter.shape}")
    assert list(direct.columns) == list(via_adapter.columns), (
        f"{strategy_name}: columns mismatch")
    assert direct.index.equals(via_adapter.index), (
        f"{strategy_name}: index mismatch")
    # Use np.allclose-style for NaN-safe element compare
    a = direct.values
    b = via_adapter.values
    # NaN-equal & value-equal
    nan_match = np.isnan(a) == np.isnan(b)
    val_match = np.where(np.isnan(a), True, a == b)
    assert nan_match.all(), f"{strategy_name}: NaN mask mismatch"
    assert val_match.all(), f"{strategy_name}: value mismatch"


class TestM11ParityMatrix:
    def test_dual_momentum_bit_identical(self, synth):
        price_df, _, regime = synth
        strat = DualMomentumStrategy()
        direct = strat.generate(price_df, regime)
        adapter = GenerateStrategyAdapter(strat, mode="off")
        via = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime})
        _assert_panels_equal(direct, via, "DualMomentum")

    def test_trend_following_bit_identical(self, synth):
        price_df, _, regime = synth
        strat = TrendFollowingStrategy()
        direct = strat.generate(price_df, regime)
        adapter = GenerateStrategyAdapter(strat, mode="off")
        via = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime})
        _assert_panels_equal(direct, via, "TrendFollowing")

    def test_cross_asset_rotation_bit_identical(self, synth):
        price_df, _, regime = synth
        strat = CrossAssetRotationStrategy()
        direct = strat.generate(price_df, regime)
        adapter = GenerateStrategyAdapter(strat, mode="off")
        via = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime})
        _assert_panels_equal(direct, via, "CrossAssetRotation")

    def test_simple_baseline_bit_identical(self):
        # SimpleBaselineStrategy requires {MTUM, TQQQ, BIL, QQQ, VIX}
        # in price_df.columns; build a fitting synthetic panel.
        rng = np.random.default_rng(7)
        dates = pd.date_range("2020-01-01", periods=500, freq="B")
        syms = ["MTUM", "TQQQ", "BIL", "QQQ", "VIX"]
        rets = rng.normal(0.0003, 0.015, size=(500, 5))
        rets[0] = 0
        prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
        price_df = pd.DataFrame(prices, index=dates, columns=syms)
        volume = pd.DataFrame(
            rng.uniform(1e5, 1e7, size=(500, 5)),
            index=dates, columns=syms)
        regime = pd.Series("NEUTRAL", index=dates, dtype=str)
        strat = SimpleBaselineStrategy()
        direct = strat.generate(price_df, regime, volume)
        adapter = GenerateStrategyAdapter(strat, mode="off")
        via = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime,
                 "volume_df": volume})
        _assert_panels_equal(direct, via, "SimpleBaseline")

    def test_multi_factor_bit_identical(self, synth):
        price_df, volume, regime = synth
        strat = MultiFactorStrategy()
        direct = strat.generate(price_df, regime, volume)
        adapter = GenerateStrategyAdapter(strat, mode="off")
        via = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime,
                 "volume_df": volume})
        _assert_panels_equal(direct, via, "MultiFactor")

    def test_confirmation_pattern_bit_identical(self, synth):
        # 6th strategy — closes auditor F2-extension + post-R11 M11
        # backlog (the "grep-introspection bug" was a script-level
        # subprocess invocation issue in initial R12, not a
        # strategy-level bug; module imports cleanly when loaded
        # by the test runner directly).
        # ConfirmationPatternStrategy signature: generate(price_df,
        # volume_df=None) — no regime_series. Adapter inspect-based
        # kwarg filter handles this asymmetric signature.
        price_df, volume, _ = synth
        strat = ConfirmationPatternStrategy()
        direct = strat.generate(price_df, volume)
        adapter = GenerateStrategyAdapter(strat, mode="off")
        via = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "volume_df": volume})
        _assert_panels_equal(direct, via, "ConfirmationPattern")


# ── 7th strategy: intraday_reversal direct Protocol satisfaction ───
class TestIntradayReversalNativeProtocol:
    def test_has_4_method_state_machine(self):
        # PRD §F.2 blueprint: intraday_reversal IS the 4-method
        # DecisionPolicy Protocol natively (the 1/7 model the X1
        # design followed).
        from core.signals.strategies.intraday_reversal import (
            IntradayReversalStrategy,
        )
        for m in ("detect_setups", "confirm_signals",
                  "build_target_weights", "step_day"):
            assert hasattr(IntradayReversalStrategy, m), (
                f"intraday_reversal missing 4-method protocol member {m}")


# ── adapter mock backward-compat (X1 test legacy) ──────────────────
class TestAdapterMockBackwardCompat:
    """X4 adapter rewrite must preserve X1 mock test paths."""

    def test_legacy_mock_signature_still_works(self):
        # X1 mock returns dict from generate(date, ctx) — must
        # still work via the inspect-fallback path.
        weights = {"AAA": 0.5, "BBB": 0.5}

        class _LegacyMock:
            def generate(self, date, ctx=None):
                return weights

        adapter = GenerateStrategyAdapter(_LegacyMock(), mode="off")
        out = adapter.build_target_weights(
            state=None, ctx={"date": pd.Timestamp("2025-01-01")})
        assert out == weights


# ── PYTHONHASHSEED determinism ─────────────────────────────────────
class TestDeterminism:
    def test_parity_stable_across_repeated_calls(self, synth):
        price_df, _, regime = synth
        strat = DualMomentumStrategy()
        adapter = GenerateStrategyAdapter(strat, mode="off")
        out1 = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime})
        out2 = adapter.build_target_weights(
            state=None,
            ctx={"price_df": price_df, "regime_series": regime})
        _assert_panels_equal(out1, out2, "DualMomentum-determinism")
