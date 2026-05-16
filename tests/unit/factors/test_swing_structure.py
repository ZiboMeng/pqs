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
    SwingPoint,
    SwingStructureConfig,
    _collapse_alternating,
    confirmed_swings_asof,
    detect_raw_swings,
)


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
