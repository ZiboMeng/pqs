"""P0-B / audit P1-2 — HAC (Newey-West) IC t-stat tests.

PRD: grand-audit §4 P1-2 + P0-B. The fix: factor IC t-stat must be
HAC-adjusted (overlapping horizon-day labels → autocorrelated IC →
iid t overstates significance). Rigor (no 走过场): a NEGATIVE-style
control — on iid input HAC ≈ iid (no spurious deflation); on
autocorrelated input HAC MUST deflate |t|.
"""
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from core.factors.factor_engine import FactorEngine, _hac_ttest_mean0


def test_iid_input_hac_matches_plain_t():
    rng = np.random.default_rng(0)
    x = 0.02 + 0.1 * rng.standard_normal(800)   # iid, small +mean
    t_plain, p_plain = scipy_stats.ttest_1samp(x, 0.0)
    t_hac, p_hac = _hac_ttest_mean0(x, lag=20)
    # no autocorrelation ⇒ HAC ≈ iid (within ~15%)
    assert abs(t_hac - t_plain) / abs(t_plain) < 0.15
    assert p_hac > 0  # finite, defined


def test_autocorr_flips_false_positive_to_insignificant():
    # The decision-relevant property: a WEAK mean on a STRONGLY
    # autocorrelated series is a classic false positive — iid t says
    # "significant" (p<0.05); HAC must correctly say "NOT significant"
    # (p>0.05). Robust assertion = the FLIP + deflation ordering, not
    # a brittle absolute p threshold (which depends on signal
    # strength — over-specifying it was the prior test's mistake).
    rng = np.random.default_rng(1)
    n = 1500
    e = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = 0.9 * x[i - 1] + e[i]            # strong autocorr
    x = 0.18 + x                                 # weak mean vs σ_x
    t_plain, p_plain = scipy_stats.ttest_1samp(x, 0.0)
    t_hac, p_hac = _hac_ttest_mean0(x, lag=30)
    assert abs(t_hac) < abs(t_plain)             # deflated
    assert p_plain < 0.05                        # iid: false positive
    assert p_hac > 0.05                          # HAC: correctly NOT sig
    assert p_hac / max(p_plain, 1e-300) > 10.0   # orders less significant


def test_degenerate_short_input():
    t, p = _hac_ttest_mean0(np.array([0.1]), lag=5)
    assert np.isnan(t) and np.isnan(p)


def test_horizon_widens_lag_in_factor_stats():
    # An autocorrelated IC series: larger horizon ⇒ wider Bartlett lag
    # ⇒ for positively-autocorrelated IC, |t| should not increase
    # (more autocorr accounted for ⇒ ≤).
    rng = np.random.default_rng(2)
    n = 600
    e = rng.standard_normal(n)
    ic = np.empty(n)
    ic[0] = e[0]
    for i in range(1, n):
        ic[i] = 0.6 * ic[i - 1] + e[i]
    ic = pd.Series(0.04 + 0.02 * ic,
                   index=pd.bdate_range("2010-01-01", periods=n))
    s_h1 = FactorEngine.compute_factor_stats(ic, "f", horizon=1)
    s_h21 = FactorEngine.compute_factor_stats(ic, "f", horizon=21)
    assert abs(s_h21.t_stat) <= abs(s_h1.t_stat) + 1e-9
    # field contract intact (downstream is_significant depends on these)
    for s in (s_h1, s_h21):
        assert np.isfinite(s.mean_ic) and np.isfinite(s.t_stat)
        assert np.isfinite(s.p_value) and 0.0 <= s.p_value <= 2.0
