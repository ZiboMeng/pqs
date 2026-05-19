"""PRD-3 RA1 — A1 engineered stationary features module (TDD).

build round. AC (PRD-3 ralph-loop RA1): per-feature hand-computed
sample unit tests (no look-ahead / stationary / cross-sectional rank
correct) GREEN; sample-uniqueness + purge wired into eval via
``core/research/label_leakage`` (delegation regression GREEN).

Grounded scope (honest, same R4/R6/R7 pattern): frac-diff price
(``core.ml.feature_prep.frac_diff_ffd``), Family T swing-structure
(``core.factors.swing_structure``), S/R proxy (``dist_from_new_high_252``
/ ``dist_to_swing_*``) and the leakage helpers
(``core.research.label_leakage``) ALREADY exist and are delegated to —
NOT reimplemented. The genuinely-NEW RA1 surface tested here is the
JKX ``close_pos_in_range`` multi-window normalized geometry, the
stationary K-line body/wick/gap ratios, the volume z, and the
assembly module that cross-sectionally ranks monthly + delegates the
leakage helper.
"""
import numpy as np
import pandas as pd
import pytest

from core.research import engineered_features as ef
from core.research.label_leakage import average_uniqueness_weights


# ── close_pos_in_range (JKX normalized geometry) ──────────────────────
class TestClosePosInRange:
    def test_hand_computed_single_window(self):
        # window=3: pos_t = (c_t - min(c[t-2..t])) / (max - min).
        c = pd.Series([10.0, 12.0, 11.0, 9.0, 13.0],
                      index=pd.bdate_range("2020-01-01", periods=5))
        out = ef.close_pos_in_range(c.to_frame("X"), windows=(3,))["w3"]
        # t=0,1 -> NaN (window not full)
        assert out["X"].iloc[0:2].isna().all()
        # t=2: win [10,12,11] min10 max12 -> (11-10)/2 = 0.5
        assert out["X"].iloc[2] == pytest.approx(0.5)
        # t=3: win [12,11,9] min9 max12 -> (9-9)/3 = 0.0
        assert out["X"].iloc[3] == pytest.approx(0.0)
        # t=4: win [11,9,13] min9 max13 -> (13-9)/4 = 1.0
        assert out["X"].iloc[4] == pytest.approx(1.0)

    def test_bounded_0_1_stationary(self):
        rng = np.random.default_rng(0)
        c = pd.DataFrame(
            np.cumsum(rng.standard_normal((300, 4)), axis=0) + 100,
            index=pd.bdate_range("2015-01-01", periods=300),
            columns=list("ABCD"))
        out = ef.close_pos_in_range(c, windows=(20, 63))
        for k, df in out.items():
            v = df.to_numpy()
            v = v[~np.isnan(v)]
            assert (v >= -1e-9).all() and (v <= 1 + 1e-9).all(), k

    def test_no_look_ahead(self):
        # truncating the future must not change any past value.
        rng = np.random.default_rng(1)
        c = pd.DataFrame(
            np.cumsum(rng.standard_normal((120, 3)), axis=0) + 50,
            index=pd.bdate_range("2018-01-01", periods=120),
            columns=list("XYZ"))
        full = ef.close_pos_in_range(c, windows=(20,))["w20"]
        trunc = ef.close_pos_in_range(c.iloc[:80], windows=(20,))["w20"]
        pd.testing.assert_frame_equal(
            full.iloc[:80], trunc, check_freq=False)

    def test_degenerate_flat_window_is_nan(self):
        c = pd.Series([7.0] * 6,
                      index=pd.bdate_range("2020-01-01", periods=6))
        out = ef.close_pos_in_range(c.to_frame("F"), windows=(3,))["w3"]
        # max == min -> 0/0 -> NaN (no information, never a fake 0.5)
        assert out["F"].iloc[2:].isna().all()


# ── K-line body / wick / gap (stationary ratios) ──────────────────────
class TestKlineShape:
    def _ohlc(self):
        idx = pd.bdate_range("2020-01-01", periods=3)
        o = pd.DataFrame({"X": [10.0, 11.0, 9.0]}, index=idx)
        h = pd.DataFrame({"X": [12.0, 11.5, 10.0]}, index=idx)
        low = pd.DataFrame({"X": [9.0, 10.0, 8.0]}, index=idx)
        c = pd.DataFrame({"X": [11.0, 10.5, 9.5]}, index=idx)
        return o, h, low, c

    def test_hand_computed_body_wick_gap(self):
        o, h, low, c = self._ohlc()
        out = ef.kline_shape(o, h, low, c)
        # t0: range=12-9=3 body=(11-10)/3=0.3333
        assert out["body"]["X"].iloc[0] == pytest.approx(1 / 3)
        # upper_wick=(12-max(11,10))/3=(12-11)/3=0.3333
        assert out["upper_wick"]["X"].iloc[0] == pytest.approx(1 / 3)
        # lower_wick=(min(11,10)-9)/3=(10-9)/3=0.3333
        assert out["lower_wick"]["X"].iloc[0] == pytest.approx(1 / 3)
        # gap t0 -> NaN (no prev close)
        assert np.isnan(out["gap"]["X"].iloc[0])
        # gap t1 = (open1 - close0)/close0 = (11-11)/11 = 0.0
        assert out["gap"]["X"].iloc[1] == pytest.approx(0.0)
        # gap t2 = (9 - 10.5)/10.5
        assert out["gap"]["X"].iloc[2] == pytest.approx((9 - 10.5) / 10.5)

    def test_body_bounded_pm1_wick_0_1(self):
        rng = np.random.default_rng(2)
        n = 200
        idx = pd.bdate_range("2016-01-01", periods=n)
        base = np.cumsum(rng.standard_normal((n, 3)), axis=0) + 100
        o = pd.DataFrame(base, index=idx, columns=list("ABC"))
        c = o + rng.standard_normal((n, 3))
        h = np.maximum(o, c) + np.abs(rng.standard_normal((n, 3)))
        low = np.minimum(o, c) - np.abs(rng.standard_normal((n, 3)))
        out = ef.kline_shape(o, pd.DataFrame(h, index=idx, columns=list("ABC")),
                             pd.DataFrame(low, index=idx, columns=list("ABC")), c)
        b = out["body"].to_numpy(); b = b[~np.isnan(b)]
        assert (b >= -1 - 1e-9).all() and (b <= 1 + 1e-9).all()
        for w in ("upper_wick", "lower_wick"):
            v = out[w].to_numpy(); v = v[~np.isnan(v)]
            assert (v >= -1e-9).all() and (v <= 1 + 1e-9).all(), w

    def test_gap_no_look_ahead(self):
        o, h, low, c = self._ohlc()
        full = ef.kline_shape(o, h, low, c)["gap"]
        trunc = ef.kline_shape(o.iloc[:2], h.iloc[:2],
                               low.iloc[:2], c.iloc[:2])["gap"]
        pd.testing.assert_frame_equal(
            full.iloc[:2], trunc, check_freq=False)


# ── volume z (trailing, no look-ahead) ────────────────────────────────
class TestVolumeZ:
    def test_hand_computed(self):
        v = pd.Series([100.0, 100.0, 100.0, 200.0],
                      index=pd.bdate_range("2020-01-01", periods=4))
        out = ef.volume_z(v.to_frame("X"), window=3)
        # t=3: trailing 3 = [100,100,200] mean=133.33 std(ddof=1) of
        # [100,100,200] = 57.735; z = (200-133.33)/57.735
        m = np.mean([100, 100, 200]); s = np.std([100, 100, 200], ddof=1)
        assert out["X"].iloc[3] == pytest.approx((200 - m) / s)
        assert out["X"].iloc[0:2].isna().all()

    def test_no_look_ahead(self):
        rng = np.random.default_rng(3)
        v = pd.DataFrame(np.abs(rng.standard_normal((100, 3))) * 1e6 + 1e6,
                         index=pd.bdate_range("2019-01-01", periods=100),
                         columns=list("XYZ"))
        full = ef.volume_z(v, window=20)
        trunc = ef.volume_z(v.iloc[:60], window=20)
        pd.testing.assert_frame_equal(
            full.iloc[:60], trunc, check_freq=False)


# ── frac-diff price: honest delegation (NOT reimplemented) ────────────
class TestFracDiffDelegation:
    def test_delegates_to_feature_prep(self):
        from core.ml.feature_prep import frac_diff_ffd
        c = pd.Series(
            np.cumsum(np.random.default_rng(4).standard_normal(200)) + 100,
            index=pd.bdate_range("2017-01-01", periods=200))
        got = ef.frac_diff_price(c.to_frame("X"), d=0.4)["X"]
        exp = frac_diff_ffd(c, 0.4)
        pd.testing.assert_series_equal(
            got.dropna(), exp.reindex(got.index).dropna(),
            check_names=False, check_freq=False)


# ── cross-sectional monthly rank ──────────────────────────────────────
class TestCrossSectionalMonthlyRank:
    def test_cross_sectional_rank_is_per_date_across_symbols(self):
        idx = pd.bdate_range("2020-01-01", periods=2)
        df = pd.DataFrame({"A": [1.0, 4.0], "B": [3.0, 2.0],
                           "C": [2.0, 9.0]}, index=idx)
        r = ef.cross_sectional_rank(df)
        # row0: A=1<C=2<B=3 -> pct ranks 1/3,3/3,2/3
        assert r.iloc[0]["A"] == pytest.approx(1 / 3)
        assert r.iloc[0]["C"] == pytest.approx(2 / 3)
        assert r.iloc[0]["B"] == pytest.approx(3 / 3)
        # each row independent (cross-sectional, not time)
        assert r.iloc[1]["B"] == pytest.approx(1 / 3)

    def test_monthly_rank_only_on_month_end_rows(self):
        idx = pd.bdate_range("2020-01-01", periods=60)  # Jan + Feb + Mar
        df = pd.DataFrame(
            np.random.default_rng(5).standard_normal((60, 4)),
            index=idx, columns=list("ABCD"))
        mr = ef.monthly_cross_sectional_rank(df)
        non_nan_dates = mr.dropna(how="all").index
        # only month-end business days carry a rank
        me = pd.bdate_range("2020-01-01", periods=60).to_series().groupby(
            [idx.year, idx.month]).last().values
        assert set(non_nan_dates) <= set(pd.DatetimeIndex(me))
        assert len(non_nan_dates) >= 2  # at least Jan + Feb ends


# ── assembly + leakage delegation (the RA1 module contract) ───────────
class TestBuildPanelAndLeakageWiring:
    def _panel(self, n=180, syms=("AAA", "BBB", "CCC")):
        idx = pd.bdate_range("2018-01-01", periods=n)
        rng = np.random.default_rng(6)
        base = np.cumsum(rng.standard_normal((n, len(syms))), axis=0) + 100
        o = pd.DataFrame(base, index=idx, columns=list(syms))
        c = o + rng.standard_normal((n, len(syms)))
        h = np.maximum(o, c) + np.abs(rng.standard_normal((n, len(syms))))
        low = np.minimum(o, c) - np.abs(rng.standard_normal((n, len(syms))))
        vol = pd.DataFrame(np.abs(rng.standard_normal((n, len(syms)))) * 1e6
                           + 1e6, index=idx, columns=list(syms))
        return dict(open=o,
                    high=pd.DataFrame(h, index=idx, columns=list(syms)),
                    low=pd.DataFrame(low, index=idx, columns=list(syms)),
                    close=c, volume=vol)

    def test_build_engineered_panel_returns_named_feature_map(self):
        p = self._panel()
        feats = ef.build_engineered_panel(
            p["open"], p["high"], p["low"], p["close"], p["volume"],
            close_windows=(20, 63))
        # must expose the NEW primitives + frac-diff delegation key
        for key in ("close_pos_w20", "close_pos_w63", "kline_body",
                    "kline_upper_wick", "kline_lower_wick", "kline_gap",
                    "volume_z20", "frac_diff_close"):
            assert key in feats, key
            assert list(feats[key].columns) == list(p["close"].columns)

    def test_panel_monthly_rank_option_is_bounded(self):
        p = self._panel()
        feats = ef.build_engineered_panel(
            p["open"], p["high"], p["low"], p["close"], p["volume"],
            close_windows=(20,), monthly_rank=True)
        v = feats["close_pos_w20"].to_numpy()
        v = v[~np.isnan(v)]
        # pct rank in (0, 1]
        assert (v > 0).all() and (v <= 1 + 1e-9).all()

    def test_sample_weights_delegates_to_label_leakage_canonical(self):
        # RA1 AC: sample-uniqueness wired via core/research/label_leakage
        # — NOT a duplicate implementation. Byte-identical to calling
        # the canonical helper directly.
        start = np.array([0, 0, 5, 10, 10, 20])
        groups = np.array([0, 0, 0, 1, 1, 1])
        got = ef.engineered_sample_weights(start, horizon=21, groups=groups)
        exp = average_uniqueness_weights(start, 21, groups=groups)
        np.testing.assert_array_equal(got, exp)

    def test_purge_mask_delegates_to_label_leakage_canonical(self):
        from core.research.label_leakage import purge_embargo_mask
        t = np.array([0, 10, 50, 100, 200])
        yrs = [2015, 2016, 2017, 2018, 2019]
        got = ef.engineered_purge_mask(t, yrs, horizon=21,
                                       holdout_years={2018, 2019})
        exp = purge_embargo_mask(t, yrs, 21, {2018, 2019})
        np.testing.assert_array_equal(got, exp)
