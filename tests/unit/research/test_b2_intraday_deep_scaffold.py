"""PRD-3 RB4 — B2 intraday deep scaffold + MANDATORY DLinear (TDD)."""
import numpy as np
import pandas as pd
import pytest

from core.ml.transformer_encoder import is_torch_available
from core.research.b2_intraday_deep_scaffold import (
    B2Config,
    b2_ssl_frozen_probe,
    build_multitf_channels,
    dlinear_baseline_fit_predict,
)


class TestDLinearBaselineMandatory:
    """The RB4 AC: DLinear baseline 强制接入,无之结果不可信."""

    def test_fits_and_predicts_shape(self):
        rng = np.random.default_rng(0)
        Xtr = pd.DataFrame(rng.standard_normal((80, 4)),
                           columns=list("abcd"))
        ytr = pd.Series(0.5 * Xtr["a"] + 0.1 * rng.standard_normal(80))
        Xva = pd.DataFrame(rng.standard_normal((30, 4)),
                           columns=list("abcd"))
        p = dlinear_baseline_fit_predict(Xtr, ytr, Xva)
        assert p.shape == (30,) and np.isfinite(p).all()

    def test_recovers_linear_signal(self):
        # y is purely linear in feature 'a' → DLinear must
        # outperform a zero-prediction baseline (RMSE-wise).
        rng = np.random.default_rng(1)
        Xtr = pd.DataFrame(rng.standard_normal((200, 3)),
                           columns=list("abc"))
        ytr = pd.Series(1.5 * Xtr["a"] + 0.05 * rng.standard_normal(200))
        Xva = pd.DataFrame(rng.standard_normal((60, 3)),
                           columns=list("abc"))
        yva = 1.5 * Xva["a"] + 0.05 * rng.standard_normal(60)
        p = dlinear_baseline_fit_predict(Xtr, ytr, Xva)
        rmse_dlin = float(np.sqrt(((p - yva) ** 2).mean()))
        rmse_zero = float(np.sqrt((yva ** 2).mean()))
        assert rmse_dlin < rmse_zero    # baseline does something

    def test_reproducible_fixed_seed(self):
        rng = np.random.default_rng(2)
        Xtr = pd.DataFrame(rng.standard_normal((50, 3)),
                           columns=list("xyz"))
        ytr = pd.Series(rng.standard_normal(50))
        Xva = pd.DataFrame(rng.standard_normal((10, 3)),
                           columns=list("xyz"))
        a = dlinear_baseline_fit_predict(Xtr, ytr, Xva, seed=7)
        b = dlinear_baseline_fit_predict(Xtr, ytr, Xva, seed=7)
        np.testing.assert_allclose(a, b)


class TestMultiTFChannelStack:
    def _bars(self, n, freq_minutes):
        idx = pd.date_range("2025-01-02 09:30", periods=n,
                            freq=f"{freq_minutes}min")
        c = np.cumsum(np.random.default_rng(0).standard_normal(n)) + 100
        return pd.DataFrame({"close": c}, index=idx)

    def _multi(self):
        return {
            "15m": {"X": self._bars(80, 15)},
            "30m": {"X": self._bars(40, 30)},
            "60m": {"X": self._bars(20, 60)},
        }

    def test_shape_K_freq_x_lookback(self):
        # 60m bars 09:30 → 14:30 inclusive = 6 closed bars at
        # decision 14:30, so the lookback ≤ 6 is the constraint
        # (the impl honestly returns None on insufficient warmup —
        # tested separately). Use lookback=4 for the shape check.
        m = self._multi()
        dt = pd.Timestamp("2025-01-02 14:30")
        out = build_multitf_channels(m, "X", dt, lookback_bars=4)
        assert out is not None and out.shape == (3, 4)

    def test_leakage_safe_only_closed_bars(self):
        # any bar with index > decision_time must NOT appear in the
        # output (R10 / CLAUDE.md Multi-TF Leakage Rules).
        m = self._multi()
        dt = pd.Timestamp("2025-01-02 12:00")
        out = build_multitf_channels(m, "X", dt, lookback_bars=4)
        if out is not None:
            for f in ("15m", "30m", "60m"):
                df = m[f]["X"]
                usable = df[df.index <= dt]["close"].iloc[-4:].to_numpy()
                # the stacked row for that freq must match the
                # last-4-closed-bars from the leakage-safe filter.
                channel_idx = {"15m": 0, "30m": 1, "60m": 2}[f]
                np.testing.assert_allclose(out[channel_idx], usable)

    def test_insufficient_warmup_returns_none(self):
        m = self._multi()
        dt = pd.Timestamp("2025-01-02 09:45")  # only ~1 bar in
        assert build_multitf_channels(m, "X", dt, lookback_bars=8) is None

    def test_missing_freq_returns_none(self):
        m = {"15m": {"X": self._bars(80, 15)}}     # 30m / 60m absent
        dt = pd.Timestamp("2025-01-02 14:30")
        assert build_multitf_channels(m, "X", dt) is None


class TestB2SslEntryRoutesRb1Gate:
    def test_naive_archetype_refused_BEFORE_pretrain(self):
        with pytest.raises(ValueError, match=r"NAIVE|naive|老路子"):
            b2_ssl_frozen_probe(
                np.zeros((4, 16), np.float32),
                cfg=B2Config(archetype="bar_direction_voting"))

    def test_unknown_archetype_refused(self):
        with pytest.raises(ValueError, match=r"unknown"):
            b2_ssl_frozen_probe(
                np.zeros((4, 16), np.float32),
                cfg=B2Config(archetype="magic_alpha"))

    def test_bulk_universe_refused_by_default(self):
        with pytest.raises(RuntimeError, match=r"HARD precondition"):
            b2_ssl_frozen_probe(
                np.zeros((4, 16), np.float32),
                universe_name="expanded_v2",
                cfg=B2Config(archetype="intraday_reversal"))


@pytest.mark.skipif(not is_torch_available(), reason="torch needed")
class TestB2SslScaffoldRuns:
    def test_curated_differentiated_pretrains(self):
        W = np.cumsum(np.random.default_rng(3).standard_normal((48, 32)),
                      axis=1).astype(np.float32)
        m, embed = b2_ssl_frozen_probe(
            W, universe_name="executable",
            cfg=B2Config(archetype="intraday_reversal",
                         pretrain_steps=5, seed=11))
        assert all(not p.requires_grad for p in m.parameters())
        assert embed(W[:6]).shape[0] == 6
