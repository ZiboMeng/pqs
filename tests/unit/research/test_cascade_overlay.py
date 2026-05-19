"""PRD-2 P2.3 R12 — multi-TF cascade construction overlay (TDD).

build round. AC (PRD-2 ralph-loop R12): cascade-wiring unit GREEN +
60m-only baseline reproducible regression GREEN. Boundary pinned:
timing/sizing/veto on existing daily weights, NOT intraday alpha
mining; long-only preserved; never amplifies above base.
"""
import inspect

import pandas as pd
import pytest

from core.intraday.multi_timescale import (
    MultiTimescaleContext,
    TimescaleBar,
)
from core.research import cascade_overlay as co
from core.research.cascade_overlay import apply_cascade_overlay

_T = pd.Timestamp("2025-04-01 10:30")


def _bar(direction: int, freq: str) -> TimescaleBar:
    c = 101.5 if direction == 1 else (98.5 if direction == -1 else 100.0)
    return TimescaleBar(timestamp=_T, freq=freq, open=100.0, high=102.0,
                        low=98.0, close=c, volume=1e5)


def _ctx(**dirs) -> MultiTimescaleContext:
    return MultiTimescaleContext(
        decision_time=_T,
        bars={f: _bar(d, f) for f, d in dirs.items() if d is not None})


_W = pd.Series({"AAA": 0.4, "BBB": 0.35, "CCC": 0.25})


class TestBaseline60mOnly:
    def test_mode_off_is_identity_bit_identical(self):
        out = apply_cascade_overlay(_W, mode="off")
        pd.testing.assert_series_equal(out, _W)
        assert out is not _W  # a copy, not the same object

    def test_cascade_no_ctx_map_is_identity(self):
        pd.testing.assert_series_equal(
            apply_cascade_overlay(_W, None, mode="cascade"), _W)

    def test_cascade_symbol_without_ctx_passes_through(self):
        # only AAA has a context; BBB/CCC = 60m-only pass-through
        out = apply_cascade_overlay(
            _W, {"AAA": _ctx(**{"60m": 1})}, mode="cascade")
        assert out["BBB"] == _W["BBB"] and out["CCC"] == _W["CCC"]

    def test_baseline_reproducible(self):
        a = apply_cascade_overlay(_W, None, mode="off")
        b = apply_cascade_overlay(_W, None, mode="off")
        pd.testing.assert_series_equal(a, b)


class TestCascadeTimingSizingVeto:
    def test_confirming_60m_keeps_full_weight(self):
        out = apply_cascade_overlay(
            _W, {"AAA": _ctx(**{"60m": 1})}, mode="cascade")
        # 60m confirms long → full target (timing_scale = 1.0)
        assert out["AAA"] == pytest.approx(_W["AAA"])

    def test_contradicting_60m_reduces_or_vetoes(self):
        out = apply_cascade_overlay(
            _W, {"AAA": _ctx(**{"60m": -1})}, mode="cascade")
        # 60m opposes the long target → scaled down / vetoed
        assert 0.0 <= out["AAA"] < _W["AAA"]

    def test_long_only_preserved_never_negative_never_amplified(self):
        ctxs = {"AAA": _ctx(**{"60m": -1}), "BBB": _ctx(**{"60m": 1}),
                "CCC": _ctx(**{"60m": 0})}
        out = apply_cascade_overlay(_W, ctxs, mode="cascade")
        for s in _W.index:
            assert out[s] >= 0.0, f"{s} went negative (no-short broken)"
            assert out[s] <= _W[s] + 1e-12, f"{s} amplified above base"

    def test_nonpositive_base_weight_untouched(self):
        w0 = pd.Series({"AAA": 0.0, "BBB": 0.5})
        out = apply_cascade_overlay(
            w0, {"AAA": _ctx(**{"60m": 1}), "BBB": _ctx(**{"60m": 1})},
            mode="cascade")
        assert out["AAA"] == 0.0

    def test_deterministic(self):
        ctxs = {"AAA": _ctx(**{"60m": -1, "30m": -1})}
        a = apply_cascade_overlay(_W, ctxs, mode="cascade")
        b = apply_cascade_overlay(_W, ctxs, mode="cascade")
        pd.testing.assert_series_equal(a, b)

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            apply_cascade_overlay(_W, None, mode="alpha")


class TestNotIntradayAlphaMining:
    def test_overlay_only_uses_decide_timing_no_alpha_generation(self):
        # structural boundary (CLAUDE.md 15m-revision pin): the
        # overlay must consume the timing primitive ONLY — never any
        # factor/alpha/mining signal generator.
        src = inspect.getsource(co.apply_cascade_overlay)
        assert "decide_timing(" in src
        for forbidden in ("factor", "alpha", "mining", "generate_signal",
                          "FactorEngine", "research_miner"):
            assert forbidden not in src, (
                f"cascade overlay references {forbidden!r} — it must be "
                f"timing/sizing/veto on EXISTING weights, not alpha mining")
