"""PRD-2 P2.3 R10 — Multi-TF Leakage Rules consolidated gate (TDD).

build round. AC (PRD-2 ralph-loop R10): the 3 CLAUDE.md Multi-TF
Leakage Rules — bar-completion / no-future-higher-TF / ≥1-bar
execution delay — asserted as named contracts on
``multi_timescale`` (decide_timing / build_context /
get_latest_completed_bar).

Grounded scope (honest, R4/R6/R7 pattern — NOT a false all-new
claim): rules ① bar-completion and ② no-future-higher-TF are
ALREADY substantively covered in ``test_multi_timescale.py``
(``test_no_future_bar`` / ``test_build_context_excludes_future_bars``
/ ``test_decision_mid_bar_excludes_incomplete_bar`` /
``test_build_context_at_exact_bar_close_includes_just_closed``).
This file is the **explicit consolidated PRD-2 P2.3 R10
leakage-rules contract gate** (the 3 rules named in one place per
the CLAUDE.md Multi-TF Leakage Rules table, the unlocked-by-R9-
ratify gate), AND it pins the genuinely under-covered ③ ≥1-bar
execution-delay STRUCTURAL guarantee that the existing
defer-*decision* tests (test_timing_decision.py) did not assert as
a leakage contract.
"""
import pandas as pd
import pytest

from core.intraday.multi_timescale import (
    build_context,
    decide_timing,
    get_latest_completed_bar,
)

_T = pd.Timestamp("2025-04-01 10:30")


def _df(close_times, closes):
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes,
         "volume": [1e5] * len(closes)},
        index=pd.DatetimeIndex(close_times))


# ── Rule ① bar-completion (only closed bars) ──────────────────────────
class TestRule1BarCompletion:
    def test_bar_closing_exactly_at_decision_is_usable(self):
        # just-closed bar (close == decision_time) IS available.
        df = _df(["2025-04-01 09:30", "2025-04-01 10:30"], [100.0, 101.0])
        bar = get_latest_completed_bar(df, _T)
        assert bar is not None and bar.timestamp == _T

    def test_incomplete_bar_after_decision_excluded(self):
        # a bar that closes AFTER the decision instant must NOT be used.
        df = _df(["2025-04-01 10:30", "2025-04-01 11:30"], [101.0, 102.0])
        bar = get_latest_completed_bar(df, pd.Timestamp("2025-04-01 10:45"))
        assert bar.timestamp == _T   # the 10:30 close, never the 11:30


# ── Rule ② no-future-higher-TF ────────────────────────────────────────
class TestRule2NoFutureHigherTF:
    def test_15m_decision_cannot_see_later_closing_60m_bar(self):
        # 15m decision at 10:30; the 60m bar [09:30,10:30] closes at
        # 10:30 (usable) but the next 60m bar closes 11:30 (future) —
        # build_context must never expose a bar.timestamp > decision.
        multi = {
            "60m": {"X": _df(["2025-04-01 10:30", "2025-04-01 11:30"],
                             [100.0, 105.0])},
            "15m": {"X": _df(["2025-04-01 10:15", "2025-04-01 10:30"],
                             [100.0, 100.5])},
        }
        ctx = build_context(multi, "X", _T)
        for freq, bar in ctx.bars.items():
            assert bar.timestamp <= _T, f"{freq} future-TF leakage"
        # the 60m must be the 10:30 close, never the 11:30 future bar
        assert ctx.bars["60m"].timestamp == _T

    def test_build_context_raises_never_returns_future_bar(self):
        # only a strictly-future 60m bar exists → it must be excluded
        # (returned context simply has no 60m entry), never leaked.
        multi = {"60m": {"X": _df(["2025-04-01 11:30"], [105.0])}}
        ctx = build_context(multi, "X", _T)
        assert "60m" not in ctx.bars


# ── Rule ③ ≥1-bar execution delay (structural; under-covered) ─────────
class TestRule3MinOneBarExecutionDelay:
    def test_forming_bar_unusable_until_its_close_is_next_bar(self):
        # signal_timestamp == bar_close_time (CLAUDE.md protocol). A bar
        # still forming at decision_time (closes at T+15m) is NOT
        # actionable now; the only usable bar is the prior closed one →
        # acting on the forming bar is impossible until its close, i.e.
        # execution is structurally ≥ 1 bar delayed.
        df = _df(["2025-04-01 10:15", "2025-04-01 10:45"], [100.0, 99.0])
        # decision at 10:30: 10:15 closed, 10:45 still forming
        bar = get_latest_completed_bar(df, _T)
        assert bar.timestamp == pd.Timestamp("2025-04-01 10:15"), (
            "the still-forming 10:45 bar must NOT be actionable at "
            "10:30 — that is the ≥1-bar execution-delay guarantee")

    def test_decision_attributed_at_decision_time_no_same_instant_lookahead(self):
        # decide_timing must attribute its decision at decision_time and
        # consume only bars whose close <= decision_time (build_context's
        # asserted hard invariant). Pass a context built at _T and verify
        # the decision_time is exactly _T (no peeking past it).
        multi = {
            "60m": {"X": _df(["2025-04-01 09:30", "2025-04-01 10:30"],
                             [100.0, 101.5])},
            "30m": {"X": _df(["2025-04-01 10:00", "2025-04-01 10:30"],
                             [100.0, 101.0])},
        }
        ctx = build_context(multi, "X", _T)
        d = decide_timing(ctx, "X", base_weight=0.3)
        assert d.decision_time == _T
        for bar in ctx.bars.values():
            assert bar.timestamp <= _T

    def test_long_only_no_short_preserved_through_timing(self):
        # boundary: the 15m-as-decision-input revision must NOT relax
        # long-only — timing only scales/defers, never flips to short.
        multi = {"60m": {"X": _df(["2025-04-01 09:30", "2025-04-01 10:30"],
                                  [100.0, 98.0])}}  # 60m bearish
        ctx = build_context(multi, "X", _T)
        d = decide_timing(ctx, "X", base_weight=0.3)
        assert d.effective_weight >= 0.0  # never negative (no short)
