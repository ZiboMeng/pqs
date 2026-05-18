"""P0-A F2 — price-semantics regression test (loader layer).

PRD docs/prd/20260518-p0a_loader_barstore_fix_prd.md §2 F2.

CLAUDE.md long required a "price semantics regression test before any
vendor swap" but it NEVER covered the price-CONSUMER loader layer —
that gap is exactly how P0-A (mining/factor-screen reading raw via
MarketDataStore) survived. This test closes it.

Rigor (per user "don't go through the motions"): includes a
NEGATIVE CONTROL — it asserts the RAW path (MarketDataStore) DOES
exhibit the spurious split-day jump. If that control ever fails, the
test is not actually exercising the bug and must be treated as
broken, not green.

Anchored on REAL split dates from data/ref/splits.parquet:
  NVDA 2021-07-20 1:4, AAPL 2020-08-31 1:4, AAPL 2014-06-09 1:7,
  TSLA 2022-08-25 1:3, AMZN 2022-06-06 1:20.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.data.market_data_store import MarketDataStore
from core.data.price_access import load_adjusted, load_adjusted_panel

_ROOT = Path("data")

# (symbol, split_date, from, to) — real, from splits.parquet
_SPLITS = [
    ("NVDA", "2021-07-20", 1, 4),
    ("AAPL", "2020-08-31", 1, 4),
    ("AAPL", "2014-06-09", 1, 7),
    ("TSLA", "2022-08-25", 1, 3),
    ("AMZN", "2022-06-06", 1, 20),
]


def _ret_at(close: pd.Series, day: pd.Timestamp) -> float | None:
    """Single-day return spanning the split boundary (prev valid →
    first bar on/after split date)."""
    close = close.dropna().sort_index()
    after = close[close.index >= day]
    before = close[close.index < day]
    if after.empty or before.empty:
        return None
    return float(after.iloc[0] / before.iloc[-1] - 1.0)


def _available():
    """Include a split anchor ONLY if the split date is within the
    symbol's loaded data range on BOTH paths (i.e. _ret_at resolvable).
    A pre-data-window split (e.g. AAPL 2014 — daily store starts
    ~2015) is honestly EXCLUDED as out-of-range, NOT failed and NOT
    silently masking a regression (the >=2-anchor guard + per-case
    negative control still bind on every included case)."""
    out = []
    ms = MarketDataStore(data_dir=_ROOT)
    for sym, d, fr, to in _SPLITS:
        raw = ms.read(sym, "1d")
        adj = load_adjusted(sym, _ROOT, "1d")
        if raw is None or raw.empty or adj is None or adj.empty:
            continue
        day = pd.Timestamp(d)
        if _ret_at(raw["close"], day) is None or \
                _ret_at(adj["close"], day) is None:
            continue  # split outside data window — out of scope
        out.append((sym, day, fr, to, raw["close"], adj["close"]))
    return out


_CASES = _available()


def test_at_least_two_split_anchors_present():
    # guards against vacuous green if data goes missing
    assert len(_CASES) >= 2, f"only {len(_CASES)} split anchors loadable"


@pytest.mark.parametrize("case", _CASES, ids=[c[0] + str(c[1].date()) for c in _CASES])
def test_adjusted_has_no_spurious_split_jump(case):
    sym, day, fr, to, raw_c, adj_c = case
    adj_ret = _ret_at(adj_c, day)
    assert adj_ret is not None
    # a real one-day move is rarely beyond ±30%; a split artifact is
    # ~ (fr/to - 1) (e.g. 1:4 → -75%, 1:20 → -95%). Adjusted must NOT
    # show it.
    assert abs(adj_ret) < 0.30, (
        f"{sym} {day.date()} adjusted shows {adj_ret:.2%} at split "
        f"boundary — split cascade NOT applied")


@pytest.mark.parametrize("case", _CASES, ids=[c[0] + str(c[1].date()) for c in _CASES])
def test_NEGATIVE_CONTROL_raw_does_show_split_jump(case):
    # If this fails the regression test is not exercising the bug.
    sym, day, fr, to, raw_c, adj_c = case
    raw_ret = _ret_at(raw_c, day)
    assert raw_ret is not None
    expected = fr / to - 1.0  # e.g. 1:4 → -0.75
    assert raw_ret < -0.40, (
        f"NEGATIVE CONTROL BROKEN: {sym} {day.date()} raw ret "
        f"{raw_ret:.2%} (expected ≈ {expected:.0%}); the raw path no "
        f"longer shows the split artifact → test cannot prove it "
        f"catches P0-A. Treat as BROKEN, not green.")


@pytest.mark.parametrize("case", _CASES, ids=[c[0] + str(c[1].date()) for c in _CASES])
def test_price_access_bit_aligned_with_barstore_adjusted(case):
    from core.data.bar_store import BarStore
    sym = case[0]
    bs = BarStore(root=_ROOT).load(sym, freq="1d", adjusted=True,
                                   fallback="local")
    pa = load_adjusted(sym, _ROOT, "1d")
    j = pa["close"].dropna().align(bs["close"].dropna(), join="inner")
    assert len(j[0]) > 100
    np.testing.assert_allclose(j[0].values, j[1].values, rtol=1e-9)


def test_rewired_loader_returns_adjusted_concrete_signature():
    # Concrete P0-A signature: NVDA 2015-01-02 ≈ 0.50 adjusted, was
    # 20.125 raw. This is what the rewired run_research_miner /
    # run_factor_screen now return.
    panel = load_adjusted_panel(["NVDA"], _ROOT, "1d")
    v = panel["close"]["NVDA"].asof(pd.Timestamp("2015-01-02"))
    assert v < 5.0, f"NVDA 2015 adjusted={v} (raw≈20.1 → loader still raw)"
