"""Unit tests for core/factors/swing_structure.py — P1·R1 (causal swing core).

Per ralph-loop execution PRD §4 round P1·R1. Gate:
  - P1-A2 causal hard test (`test_swing_structure_causal`)
  - §B-B2 alternating-collapse rule (`test_collapse_alternating_b2`)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.factors.swing_structure import (
    HIGH,
    LOW,
    SWING_STRUCTURE_FEATURES,
    SwingPoint,
    SwingStructureConfig,
    _collapse_alternating,
    compute_swing_structure_factors,
    confirmed_swings_asof,
    detect_raw_swings,
    load_swing_structure_config,
)

# domain of each of the 12 family-T features for the P1-A1 ranges test
_UNIT_INTERVAL = {
    "swing_fib_retrace_fit_382", "swing_fib_retrace_fit_618",
    "swing_impulse_score", "swing_corrective_score",
    "swing_trend_maturity", "swing_high_low_overlap_pct",
}
_NON_NEGATIVE = {
    "swing_last_up_seg_len_pct", "swing_last_seg_len_ratio",
    "swing_last_seg_slope_ratio", "swing_seg_len_dispersion",
    "swing_since_last_swing_bars",
}
_SIGNED_FINITE = {"swing_net_drift_k"}


def _zigzag_bars(n_cycles: int = 6, seg: int = 14,
                  lo: float = 100.0, hi: float = 130.0) -> pd.DataFrame:
    """Deterministic triangular-wave OHLC bars with clean alternating swings.

    Each cycle = an up-seg then a down-seg of ``seg`` bars (``endpoint=False``
    so the peak / trough bar is a strict local extremum)."""
    prices: list[float] = []
    for _ in range(n_cycles):
        prices += list(np.linspace(lo, hi, seg, endpoint=False))
        prices += list(np.linspace(hi, lo, seg, endpoint=False))
    close = np.asarray(prices, dtype=float)
    idx = pd.date_range("2020-01-01", periods=len(close), freq="D")
    return pd.DataFrame(
        {"high": close + 0.5, "low": close - 0.5, "close": close},
        index=idx,
    )


def test_swing_structure_causal():
    """P1-A2: confirmed_swings_asof on the FULL panel must equal the result
    on a panel truncated to t, for every t — proves the day-t swing read
    uses no future bars (filter-then-collapse causality, PRD §3.4)."""
    cfg = SwingStructureConfig(swing_n=5)
    bars = _zigzag_bars()
    raw_full = detect_raw_swings(bars, cfg)

    for t in range(20, len(bars), 7):
        asof_full = confirmed_swings_asof(raw_full, t)
        raw_trunc = detect_raw_swings(bars.iloc[: t + 1], cfg)
        asof_trunc = confirmed_swings_asof(raw_trunc, t)
        key_full = [(s.idx, s.kind, round(s.price, 6)) for s in asof_full]
        key_trunc = [(s.idx, s.kind, round(s.price, 6)) for s in asof_trunc]
        assert key_full == key_trunc, f"causality violated at t={t}"

    # non-vacuous: the panel must actually produce swings to compare
    assert len(confirmed_swings_asof(raw_full, len(bars) - 1)) >= 4


def test_collapse_alternating_b2():
    """§B-B2: consecutive same-kind extrema collapse to the more extreme;
    the output strictly alternates HIGH / LOW."""
    raw = [
        SwingPoint(0, 110.0, HIGH, 5),
        SwingPoint(3, 118.0, HIGH, 8),    # consecutive HIGH — 118 > 110 wins
        SwingPoint(9, 95.0, LOW, 14),
        SwingPoint(12, 92.0, LOW, 17),    # consecutive LOW — 92 < 95 wins
        SwingPoint(20, 125.0, HIGH, 25),
    ]
    out = _collapse_alternating(raw)

    kinds = [s.kind for s in out]
    assert all(kinds[i] != kinds[i + 1] for i in range(len(kinds) - 1)), \
        "output not strictly alternating"
    assert (out[0].idx, out[0].price) == (3, 118.0), "consecutive HIGH kept wrong one"
    assert (out[1].idx, out[1].price) == (12, 92.0), "consecutive LOW kept wrong one"
    assert out[2].idx == 20
    assert len(out) == 3


def test_collapse_alternating_already_alternating():
    """Already-alternating input is returned unchanged."""
    raw = [
        SwingPoint(0, 110.0, HIGH, 5),
        SwingPoint(5, 95.0, LOW, 10),
        SwingPoint(10, 120.0, HIGH, 15),
    ]
    assert _collapse_alternating(raw) == raw


def test_collapse_alternating_tie_keeps_earlier():
    """Equal-price consecutive same-kind: the earlier point is kept."""
    raw = [SwingPoint(0, 110.0, HIGH, 5), SwingPoint(3, 110.0, HIGH, 8)]
    out = _collapse_alternating(raw)
    assert len(out) == 1 and out[0].idx == 0


def test_detect_raw_swings_zigzag_nonempty():
    """detect_raw_swings finds alternating-ish raw extrema on the zigzag."""
    cfg = SwingStructureConfig(swing_n=5)
    raw = detect_raw_swings(_zigzag_bars(), cfg)
    assert len(raw) >= 6
    assert {s.kind for s in raw} == {HIGH, LOW}
    # confirmation lag is exactly swing_n
    assert all(s.confirmation_idx == s.idx + cfg.swing_n for s in raw)


def _drift_zigzag(n_cycles: int = 12, seg: int = 13, base: float = 100.0,
                  amp: float = 18.0, drift: float = 1.5,
                  amp_jitter: float = 2.0) -> np.ndarray:
    """Upward-drifting triangular wave with per-cycle amplitude variation —
    produces non-degenerate swings (same-kind swings differ in price; segment
    lengths vary), unlike a perfectly periodic zigzag."""
    close: list[float] = []
    for c in range(n_cycles):
        lo = base + drift * c
        hi = lo + amp + amp_jitter * (c % 3)
        close += list(np.linspace(lo, hi, seg, endpoint=False))
        lo2 = base + drift * (c + 1)
        close += list(np.linspace(hi, lo2, seg, endpoint=False))
    return np.asarray(close, dtype=float)


def _zigzag_panel(n_symbols: int = 3) -> pd.DataFrame:
    cols = {}
    for s in range(n_symbols):
        cols[f"SYM{s}"] = _drift_zigzag(base=100.0 + 5.0 * s,
                                        drift=1.5 + 0.3 * s)
    n = len(next(iter(cols.values())))
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(cols, index=idx)


def test_swing_structure_ranges():
    """P1-A1: all 12 family-T features are produced, each non-NaN value is
    inside its declared domain, and the feature set is non-vacuous."""
    panel = _zigzag_panel()
    cfg = SwingStructureConfig(swing_n=5, K=8)
    factors = compute_swing_structure_factors(panel, cfg=cfg)

    assert set(factors.keys()) == set(SWING_STRUCTURE_FEATURES)
    assert len(SWING_STRUCTURE_FEATURES) == 12

    for name, df in factors.items():
        assert list(df.index) == list(panel.index)
        assert list(df.columns) == list(panel.columns)
        vals = df.to_numpy(dtype=float).ravel()
        finite = vals[np.isfinite(vals)]
        assert finite.size > 0, f"{name} produced only NaN — vacuous"
        if name in _UNIT_INTERVAL:
            assert (finite >= 0.0).all() and (finite <= 1.0).all(), \
                f"{name} out of [0,1]"
        elif name in _NON_NEGATIVE:
            assert (finite >= 0.0).all(), f"{name} negative"
        elif name in _SIGNED_FINITE:
            assert np.isfinite(finite).all(), f"{name} non-finite"
        else:
            raise AssertionError(f"{name} not classified in a domain set")


def test_swing_structure_config_sourced():
    """P1-A6: thresholds come from config/swing_structure.yaml (not
    hardcoded). The yaml loads; and K demonstrably drives behaviour —
    different K => different feature output."""
    cfg = load_swing_structure_config()
    assert (cfg.swing_n, cfg.K, cfg.tol, cfg.maturity_cap) == (5, 8, 0.15, 5)

    panel = _zigzag_panel()
    f_k8 = compute_swing_structure_factors(
        panel, cfg=SwingStructureConfig(swing_n=5, K=8))
    f_k4 = compute_swing_structure_factors(
        panel, cfg=SwingStructureConfig(swing_n=5, K=4))
    # at least one feature must differ somewhere — proves K flows from cfg
    differs = False
    for name in SWING_STRUCTURE_FEATURES:
        a = f_k8[name].to_numpy(dtype=float)
        b = f_k4[name].to_numpy(dtype=float)
        both = np.isfinite(a) & np.isfinite(b)
        if both.any() and not np.allclose(a[both], b[both]):
            differs = True
            break
    assert differs, "feature output identical for K=8 vs K=4 — K not config-sourced"
