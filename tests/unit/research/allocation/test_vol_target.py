"""P4 — vol-target exposure overlay TDD (PRD 20260521 §4.8)."""
import numpy as np
import pandas as pd
import pytest

from core.research.allocation.vol_target import apply_vol_target_overlay


def _close(n=260, k=3, daily_vol=0.012, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-04", periods=n)
    syms = [f"S{i}" for i in range(k)]
    px = 100.0 * np.cumprod(1 + rng.normal(0.0003, daily_vol, (n, k)), axis=0)
    return pd.DataFrame(px, index=idx, columns=syms), idx, syms


class TestVolTargetOverlay:
    def test_empty(self):
        out = apply_vol_target_overlay(pd.DataFrame(), pd.DataFrame())
        assert out.empty

    def test_long_only_preserved(self):
        close, idx, syms = _close()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        out = apply_vol_target_overlay(w, close, target_vol=0.15)
        assert (out >= 0.0).to_numpy().all()

    def test_never_levers_above_max(self):
        """Even a very calm book is never scaled above max_leverage."""
        close, idx, syms = _close(daily_vol=0.002)   # very low vol
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        out = apply_vol_target_overlay(w, close, target_vol=0.15,
                                       max_leverage=1.0)
        assert out.sum(axis=1).max() <= 1.0 + 1e-9   # no margin

    def test_high_vol_book_is_derisked(self):
        """A book whose realized vol exceeds the target gets scaled down
        — post-overlay gross is below the original fully-invested 1.0."""
        close, idx, syms = _close(daily_vol=0.035)   # ~55% annualized
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        out = apply_vol_target_overlay(w, close, target_vol=0.15)
        tail = out.iloc[80:]                          # past the warmup
        assert tail.sum(axis=1).max() < 0.99          # de-risked

    def test_warmup_unscaled(self):
        """Before the lookback fills, scale defaults to max_leverage."""
        close, idx, syms = _close()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        out = apply_vol_target_overlay(w, close, vol_lookback=60)
        pd.testing.assert_series_equal(
            out.iloc[0], w.iloc[0], check_names=False)

    def test_deterministic(self):
        close, idx, syms = _close()
        w = pd.DataFrame(1.0 / 3, index=idx, columns=syms)
        a = apply_vol_target_overlay(w, close)
        b = apply_vol_target_overlay(w, close)
        pd.testing.assert_frame_equal(a, b)
