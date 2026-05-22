"""S4 (supplement PRD 2026-05-22) — turnover-cap enforcement TDD."""
import numpy as np
import pandas as pd
import pytest

from core.research.allocation.constraints import apply_turnover_cap


def _panel(rows):
    idx = pd.bdate_range("2022-01-03", periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=["A", "B", "C"])


class TestApplyTurnoverCap:
    def test_empty_passthrough(self):
        assert apply_turnover_cap(pd.DataFrame(), 0.4).empty

    def test_under_cap_unchanged(self):
        """Moves below the cap pass through exactly."""
        w = _panel([[0.4, 0.3, 0.3], [0.4, 0.3, 0.3], [0.45, 0.30, 0.25]])
        out = apply_turnover_cap(w, turnover_cap=0.40)
        pd.testing.assert_frame_equal(out, w)

    def test_over_cap_is_throttled(self):
        """A full reshuffle (turnover 2.0) is throttled to the cap."""
        w = _panel([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        out = apply_turnover_cap(w, turnover_cap=0.40)
        # bar 0 = full initial entry; bar 1 throttled
        realized_turnover = float((out.iloc[1] - out.iloc[0]).abs().sum())
        assert realized_turnover == pytest.approx(0.40, abs=1e-9)

    def test_throttled_book_converges_toward_target(self):
        """Holding a fixed target, the throttled book drifts toward it."""
        w = _panel([[1.0, 0.0, 0.0]] + [[0.0, 1.0, 0.0]] * 20)
        out = apply_turnover_cap(w, turnover_cap=0.40)
        # after many bars at a fixed target, converges
        assert out.iloc[-1]["B"] > 0.95
        # every per-bar turnover <= cap (bar 0 = initial entry, skip)
        to = out.diff().abs().sum(axis=1).iloc[1:]
        assert (to <= 0.40 + 1e-9).all()

    def test_initial_entry_throttled_when_requested(self):
        w = _panel([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        out = apply_turnover_cap(w, turnover_cap=0.40,
                                 throttle_initial_entry=True)
        assert float(out.iloc[0].abs().sum()) == pytest.approx(0.40)

    def test_long_only_preserved(self):
        w = _panel([[0.5, 0.5, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0]])
        out = apply_turnover_cap(w, turnover_cap=0.30)
        assert (out.to_numpy() >= -1e-12).all()

    def test_deterministic(self):
        w = _panel([[0.5, 0.5, 0.0], [0.0, 0.0, 1.0]])
        a = apply_turnover_cap(w, 0.3)
        b = apply_turnover_cap(w, 0.3)
        pd.testing.assert_frame_equal(a, b)
