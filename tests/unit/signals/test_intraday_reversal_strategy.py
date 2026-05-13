"""Tests for IntradayReversalStrategy Phase 1 skeleton (alt-archetype A).

PRD: docs/prd/20260512-alt_archetype_intraday_reversal_prd.md
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.signals.strategies.intraday_reversal import (
    IntradayReversalConfig, IntradayReversalStrategy,
)
from core.signals.signal_state import SignalStatus


@pytest.fixture
def sample_panels():
    """Build small price + factor panels for 5 symbols × 10 days."""
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    syms = ["A", "B", "C", "D", "E"]
    # weekly_reversal_signal_5d: bottom quantile = setup armed
    # Set A=-2.0 (very negative reversal signal = strong setup), others milder
    wr = pd.DataFrame(
        {
            "A": np.linspace(-2.0, 0.5, 10),
            "B": np.linspace(-1.5, 0.3, 10),
            "C": np.linspace(0.0, 0.5, 10),
            "D": np.linspace(0.5, 1.0, 10),
            "E": np.linspace(0.8, 1.2, 10),
        },
        index=dates,
    )
    # vol_21d: all above filter
    vol = pd.DataFrame(
        {sym: np.full(10, 0.2 + 0.05 * i) for i, sym in enumerate(syms)},
        index=dates,
    )
    return wr, vol, dates, syms


class TestDetectSetups:
    def test_bottom_quantile_armed(self, sample_panels):
        wr, vol, dates, syms = sample_panels
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.20,
                vol_filter_min_pct=0.0,  # disable vol filter for this test
            )
        )
        # On day 0, A=-2.0 (lowest); 20% of 5 = 1 → A should arm
        setups = strat.detect_setups(wr, vol, dates[0])
        assert "A" in setups
        # E (highest) should not be armed
        assert "E" not in setups

    def test_empty_when_no_data(self, sample_panels):
        wr, vol, dates, syms = sample_panels
        strat = IntradayReversalStrategy()
        # Date outside index
        setups = strat.detect_setups(
            wr, vol, pd.Timestamp("1990-01-01"),
        )
        assert setups == []

    def test_vol_filter_removes_low_vol(self):
        """If a candidate is below vol_filter_min_pct, exclude it."""
        dates = pd.date_range("2024-01-02", periods=5, freq="B")
        wr = pd.DataFrame(
            {"A": [-2.0, -2.0, -2.0, -2.0, -2.0], "B": [-1.5] * 5},
            index=dates,
        )
        # A has very low vol, B has high vol
        vol = pd.DataFrame(
            {"A": [0.01, 0.01, 0.01, 0.01, 0.01],
             "B": [0.30, 0.30, 0.30, 0.30, 0.30]},
            index=dates,
        )
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=1.0,  # include all
                vol_filter_min_pct=0.5,  # require ≥50th percentile vol
            )
        )
        setups = strat.detect_setups(wr, vol, dates[0])
        # B (high vol) should be in; A (low vol) should be filtered out
        assert "B" in setups
        assert "A" not in setups


class TestConfirmSignals:
    def test_volume_surge_required(self):
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(volume_surge_at_open_60m_min=1.5)
        )
        armed = ["A", "B"]
        vol_z = pd.Series({"A": 2.0, "B": 0.5})  # A surges, B doesn't
        ret = pd.Series({"A": 0.01, "B": 0.01})  # both positive return
        confirmed = strat.confirm_signals(armed, vol_z, ret)
        assert "A" in confirmed
        assert "B" not in confirmed

    def test_negative_return_rejected(self):
        strat = IntradayReversalStrategy()
        armed = ["A"]
        vol_z = pd.Series({"A": 3.0})
        ret = pd.Series({"A": -0.005})  # negative = NOT reversal direction
        assert strat.confirm_signals(armed, vol_z, ret) == []

    def test_nan_inputs_skipped(self):
        strat = IntradayReversalStrategy()
        armed = ["A", "B"]
        vol_z = pd.Series({"A": np.nan, "B": 2.0})
        ret = pd.Series({"A": 0.01, "B": 0.01})
        confirmed = strat.confirm_signals(armed, vol_z, ret)
        assert "A" not in confirmed  # NaN volume_z → skip
        assert "B" in confirmed


class TestBuildTargetWeights:
    def test_equal_weight_top_n(self):
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(top_n=3, equal_weight=True)
        )
        confirmed = ["E", "A", "C", "B", "D"]
        weights = strat.build_target_weights(confirmed)
        # Top-3 alphabetical-sorted (M11a determinism): A, B, C
        assert set(weights.keys()) == {"A", "B", "C"}
        assert all(w == pytest.approx(1.0 / 3.0) for w in weights.values())

    def test_empty_when_no_confirmed(self):
        strat = IntradayReversalStrategy()
        assert strat.build_target_weights([]) == {}

    def test_top_n_smaller_than_confirmed(self):
        strat = IntradayReversalStrategy(IntradayReversalConfig(top_n=2))
        weights = strat.build_target_weights(["AAA", "BBB", "CCC"])
        assert len(weights) == 2


class TestStepDayEndToEnd:
    """End-to-end one-bar step exercising state machine + scheduler."""

    def test_arm_confirm_schedule(self, sample_panels):
        wr, vol, dates, syms = sample_panels
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(
                setup_quantile_threshold=0.20,
                vol_filter_min_pct=0.0,  # disable vol filter
                volume_surge_at_open_60m_min=1.5,
                execution_delay_bars=1,
                top_n=5,
            )
        )
        # Setup phase: A has lowest wr → should arm
        intraday_vol_z = pd.Series({"A": 2.5})  # confirms volume surge
        early_ret = pd.Series({"A": 0.008})  # positive
        weights = strat.step_day(
            bar_idx=0,
            weekly_reversal_signal_5d=wr,
            vol_21d=vol,
            intraday_volume_60m_zscore=intraday_vol_z,
            early_session_return_pct=early_ret,
            as_of_date=dates[0],
        )
        # A should be in weights (confirmed)
        assert "A" in weights
        # Scheduler should have a pending fill for A at bar 0+1=1
        assert strat.schedule.stats()["pending"] == 1

    def test_no_confirmation_no_fill(self, sample_panels):
        wr, vol, dates, syms = sample_panels
        strat = IntradayReversalStrategy(
            IntradayReversalConfig(setup_quantile_threshold=0.20)
        )
        # Setup A but DON'T confirm (volume z below threshold)
        weights = strat.step_day(
            bar_idx=0,
            weekly_reversal_signal_5d=wr,
            vol_21d=vol,
            intraday_volume_60m_zscore=pd.Series({"A": 0.5}),
            early_session_return_pct=pd.Series({"A": 0.005}),
            as_of_date=dates[0],
        )
        assert weights == {}
        assert strat.schedule.stats()["pending"] == 0


class TestPhase2DependencyImportable:
    """Sanity: Phase 1 imports work (BaseStrategy / SignalStateMachine /
    DeferredExecutionSchedule). Phase 2 integration will use these."""

    def test_deferred_execution_kernel_present(self):
        strat = IntradayReversalStrategy()
        # schedule kernel present + correct execution_delay
        assert strat.schedule.execution_delay_bars == 1

    def test_state_machine_present(self):
        strat = IntradayReversalStrategy()
        assert strat.machine is not None
