"""G5-A4 — strategy-decay early-warning detector tests.

PRD docs/prd/20260517-backtest_robustness_completion_prd.md §4 G5.
"""
import numpy as np

from core.research.decay_detector import (
    backward_cusum,
    detect_decay,
    page_hinkley,
    rolling_ic_decay,
    rolling_psr_degraded,
)


def _stable(n, seed=0):
    return 0.001 + 0.01 * np.random.default_rng(seed).standard_normal(n)


def _decaying(n, seed=0):
    rng = np.random.default_rng(seed)
    good = 0.004 + 0.01 * rng.standard_normal(n // 2)
    bad = -0.004 + 0.01 * rng.standard_normal(n - n // 2)
    return np.concatenate([good, bad])


def test_page_hinkley_detects_mean_drop():
    assert page_hinkley(_decaying(400, 1), lam=2.0)["alarm"] is True
    assert page_hinkley(_stable(400, 1), lam=5.0)["alarm"] is False


def test_backward_cusum_detects_recent_shift():
    assert backward_cusum(_decaying(400, 2))["alarm"] is True
    assert backward_cusum(_stable(400, 2))["alarm"] is False


def test_rolling_psr_degraded():
    r = rolling_psr_degraded(_decaying(400, 3), window=60)
    assert r["alarm"] is True
    assert r["psr_recent"] < r["psr_early"]
    assert rolling_psr_degraded(_stable(400, 3), window=60)["alarm"] is False


def test_rolling_ic_decay():
    ic = np.concatenate([np.full(40, 0.05), np.full(40, -0.02)])
    assert rolling_ic_decay(ic, window=20)["alarm"] is True
    assert rolling_ic_decay(np.full(80, 0.03), window=20)["alarm"] is False


def test_detect_decay_red_on_decaying():
    r = detect_decay(_decaying(500, 4))
    assert r["verdict"] == "RED"
    assert len(r["fired"]) >= 2
    assert r["additive"] is True


def test_detect_decay_green_on_stable():
    r = detect_decay(_stable(500, 5))
    assert r["verdict"] == "GREEN"
    assert r["fired"] == []


def test_detect_decay_pure_no_mutation():
    arr = _stable(300, 6)
    snapshot = arr.copy()
    detect_decay(arr)
    assert np.array_equal(arr, snapshot)   # input untouched (pure)


def test_short_series_graceful_no_false_alarm():
    for fn in (page_hinkley, backward_cusum):
        assert fn([0.01, 0.02, 0.0])["alarm"] is False
    r = detect_decay([0.01, -0.01, 0.0, 0.02])
    assert r["verdict"] == "GREEN"          # insufficient ⇒ no alarm
    assert "NEW-TD-only" in r["note"]


def test_ic_series_optional():
    r = detect_decay(_stable(400, 7))       # no ic_series
    assert r["rolling_ic"].get("skipped") is True
