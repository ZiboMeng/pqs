"""S4 (supplement PRD 2026-05-22) — exit-policy enforcement TDD."""
import pandas as pd
import pytest

from core.research.allocation.exit_policy import (
    apply_signal_decay_exit,
    apply_turnover_band,
)


def _panel(rows, cols=("A", "B", "C")):
    idx = pd.bdate_range("2022-01-03", periods=len(rows))
    return pd.DataFrame(rows, index=idx, columns=list(cols))


class TestSignalDecayExit:
    def test_empty_passthrough(self):
        assert apply_signal_decay_exit(
            pd.DataFrame(), pd.DataFrame()).empty

    def test_decayed_name_is_exited(self):
        w = _panel([[0.5, 0.5, 0.0], [0.5, 0.5, 0.0]])
        # B's rank decays below 0.50 on bar 1 → B exited
        rank = _panel([[0.9, 0.8, 0.1], [0.9, 0.30, 0.1]])
        out = apply_signal_decay_exit(w, rank, exit_threshold=0.50)
        assert out.iloc[0]["B"] == 0.5         # bar 0 — B still ranked
        assert out.iloc[1]["B"] == 0.0         # bar 1 — B decayed → cash
        assert out.iloc[1]["A"] == 0.5         # A survives

    def test_above_threshold_unchanged(self):
        w = _panel([[0.5, 0.5, 0.0]])
        rank = _panel([[0.9, 0.8, 0.1]])
        pd.testing.assert_frame_equal(
            apply_signal_decay_exit(w, rank, 0.50), w)

    def test_nan_rank_keeps_position(self):
        w = _panel([[0.5, 0.5, 0.0]])
        rank = _panel([[float("nan"), 0.8, 0.1]])
        out = apply_signal_decay_exit(w, rank, 0.50)
        assert out.iloc[0]["A"] == 0.5         # NaN rank → kept

    def test_long_only_preserved(self):
        w = _panel([[0.6, 0.4, 0.0], [0.6, 0.4, 0.0]])
        rank = _panel([[0.9, 0.2, 0.1], [0.9, 0.2, 0.1]])
        out = apply_signal_decay_exit(w, rank, 0.50)
        assert (out.to_numpy() >= -1e-12).all()


class TestTurnoverBand:
    def test_empty_passthrough(self):
        assert apply_turnover_band(pd.DataFrame(), 0.02).empty

    def test_tiny_delta_skipped(self):
        # bar1 wants a 0.01 move on A — below the 0.02 band → skipped
        w = _panel([[0.5, 0.5, 0.0], [0.51, 0.49, 0.0]])
        out = apply_turnover_band(w, band=0.02)
        assert out.iloc[1]["A"] == 0.5         # 0.01 < band → not traded

    def test_large_delta_traded(self):
        w = _panel([[0.5, 0.5, 0.0], [0.9, 0.1, 0.0]])
        out = apply_turnover_band(w, band=0.02)
        assert out.iloc[1]["A"] == 0.9         # 0.40 >= band → traded

    def test_band_zero_passthrough(self):
        w = _panel([[0.5, 0.5, 0.0], [0.51, 0.49, 0.0]])
        pd.testing.assert_frame_equal(apply_turnover_band(w, 0.0), w)

    def test_deterministic(self):
        w = _panel([[0.5, 0.5, 0.0], [0.7, 0.3, 0.0]])
        pd.testing.assert_frame_equal(
            apply_turnover_band(w, 0.02), apply_turnover_band(w, 0.02))
