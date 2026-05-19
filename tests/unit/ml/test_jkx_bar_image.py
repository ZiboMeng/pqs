"""PRD-3 RA5 — JKX OHLC+vol bar-image builder (TDD).

build round. AC (PRD-3 ralph-loop RA5): bar-image builder unit
GREEN + the close-only existing path (gaf_image / build_gaf_panel)
bit-identical regression GREEN (additive, default unchanged).

Grounded scope (honest, R4/R6/R7): gaf_image / build_gaf_panel /
to_gasf_gadf (close-only) ALREADY exist + are tested
(test_window_embedding). RA5 ADDS jkx_bar_image / build_jkx_bar_panel
(multi-channel OHLC+vol) WITHOUT touching the close-only path — the
frozen-vs-from-scratch EXPERIMENT is RA6, RA5 is builder + the
bit-identical close-only regression only.
"""
import numpy as np
import pandas as pd
import pytest

from core.ml.chart_cnn import (
    build_gaf_panel,
    build_jkx_bar_panel,
    gaf_image,
    jkx_bar_image,
)
from core.ml.window_embedding import WINDOW_LEN, to_gasf_gadf


def _ohlcv(W=WINDOW_LEN, seed=0):
    rng = np.random.default_rng(seed)
    c = np.cumsum(rng.standard_normal(W)) + 100.0
    o = c + rng.standard_normal(W) * 0.2
    h = np.maximum(o, c) + np.abs(rng.standard_normal(W)) * 0.3
    low = np.minimum(o, c) - np.abs(rng.standard_normal(W)) * 0.3
    v = np.abs(rng.standard_normal(W)) * 1e6 + 1e6
    return np.column_stack([o, h, low, c, v])


class TestJkxBarImageBuilder:
    def test_shape_is_6_channel(self):
        img = jkx_bar_image(_ohlcv())
        assert img.shape == (6, WINDOW_LEN, WINDOW_LEN)
        assert img.dtype == np.float32

    def test_entries_bounded_minus1_1(self):
        # GAF entries ∈ [-1,1] per channel.
        img = jkx_bar_image(_ohlcv(seed=3))
        assert np.nanmin(img) >= -1.0 - 1e-6
        assert np.nanmax(img) <= 1.0 + 1e-6

    def test_first_two_channels_equal_close_only_gaf(self):
        # channel block 0 = GASF+GADF of close → must equal the
        # canonical close-only gaf_image of the same close series.
        w = _ohlcv(seed=1)
        img = jkx_bar_image(w)
        close_gaf = gaf_image(w[:, 3])              # (2,W,W)
        np.testing.assert_allclose(img[:2], close_gaf, atol=1e-6)

    def test_causal_no_look_ahead(self):
        # truncating the future tail must not change earlier
        # builder output for an earlier window (pure window function).
        full = _ohlcv(seed=2)
        a = jkx_bar_image(full[:WINDOW_LEN])
        b = jkx_bar_image(full[:WINDOW_LEN].copy())
        np.testing.assert_array_equal(a, b)         # deterministic

    def test_bad_shape_raises(self):
        with pytest.raises(ValueError):
            jkx_bar_image(np.zeros((WINDOW_LEN, 3)))   # not (W,5)

    def test_constant_series_no_nan_blowup(self):
        # flat O=H=L=C, zero vol → rescale_to_unit maps to zeros;
        # image must be finite (no div-by-zero).
        w = np.column_stack([np.full(WINDOW_LEN, 50.0)] * 4
                            + [np.zeros(WINDOW_LEN)])
        img = jkx_bar_image(w)
        assert np.isfinite(img).all()


class TestBuildJkxBarPanel:
    def _panel(self, syms=("AAA", "BBB"), n=120, seed=5):
        out = {}
        for k, s in enumerate(syms):
            w = _ohlcv(W=n, seed=seed + k)
            out[s] = pd.DataFrame(
                w, columns=["open", "high", "low", "close", "volume"])
        return out

    def test_panel_shape_and_keys(self):
        pnl = self._panel()
        idxs = {"AAA": [80, 100], "BBB": [90]}
        imgs, keys = build_jkx_bar_panel(pnl, idxs)
        assert imgs.shape == (3, 6, WINDOW_LEN, WINDOW_LEN)
        assert keys == [("AAA", 80), ("AAA", 100), ("BBB", 90)]

    def test_causal_warmup_skip(self):
        pnl = self._panel()
        # t < window_len-1 → skipped (insufficient trailing bars)
        imgs, keys = build_jkx_bar_panel(pnl, {"AAA": [10]})
        assert imgs.shape[0] == 0 and keys == []

    def test_empty_returns_well_shaped(self):
        imgs, keys = build_jkx_bar_panel({}, {})
        assert imgs.shape == (0, 6, WINDOW_LEN, WINDOW_LEN)
        assert keys == []


class TestCloseOnlyPathBitIdentical:
    """RA5 AC: the existing close-only path must be byte-unchanged
    (additive change — gaf_image / build_gaf_panel untouched)."""

    def test_gaf_image_still_equals_to_gasf_gadf(self):
        w = _ohlcv(seed=7)[:, 3]            # close series
        np.testing.assert_array_equal(
            gaf_image(w), to_gasf_gadf(w).astype(np.float32))

    def test_build_gaf_panel_unchanged_2channel(self):
        cp = pd.DataFrame({"AAA": np.cumsum(
            np.random.default_rng(8).standard_normal(120)) + 100})
        imgs, keys = build_gaf_panel(cp, {"AAA": [80, 110]})
        assert imgs.shape == (2, 2, WINDOW_LEN, WINDOW_LEN)
        assert keys == [("AAA", 80), ("AAA", 110)]
        # value bit-identical to the canonical encoder
        s = cp["AAA"].to_numpy(float)
        np.testing.assert_array_equal(
            imgs[0], to_gasf_gadf(s[80 - WINDOW_LEN + 1:81]
                                  ).astype(np.float32))
