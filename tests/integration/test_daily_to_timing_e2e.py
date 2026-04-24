"""End-to-end integration test for the P1 closure (2026-04-20).

Covers the full daily → timing → intraday-runtime → persistence flow
in a single test, verifying that the three constraint refactors
actually work together when wired through production code paths:

  daily MFS signals
    → target weights (PortfolioConstructor)
      → paper live/replay (PaperTradingEngine.run_day_intraday)
        → multi-TF timing provider (make_timing_target_provider)
          → bar-by-bar IntradayBacktestEngine.run_multi_day
            → per-bar persistence (intraday_fills, bar_checkpoints)

Assertions (must all hold for the closure to be complete):
  1. Every RTH bar drives a timing decision via decide_timing
  2. Per-bar persistence rows are written
  3. Idempotent re-run produces zero new fills
  4. When timing veto is active, effective_weight = 0 on vetoed bars
  5. Without timing (baseline), runtime still works unchanged
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from core.config.loader import load_config
from core.execution.cost_model import CostModel
from core.intraday.multi_timescale import (
    TimingThresholds, make_timing_target_provider,
)
from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.paper_trading.pnl_tracker import PnLTracker
from core.risk.kill_switch import KillSwitch, KillSwitchConfig


def _rth_bars(n_bars: int, symbol: str, base_price: float,
              trend: float, freq_min: int = 60) -> pd.DataFrame:
    """Right-labeled RTH bars for one symbol with a controlled trend.

    trend > 0 → bullish bars (close > open); trend < 0 → bearish.
    """
    idx = pd.date_range("2025-04-01 10:30", periods=n_bars,
                        freq=f"{freq_min}min")
    base = base_price + np.cumsum(np.full(n_bars, trend))
    rows = []
    for i, p in enumerate(base):
        if trend > 0:
            o = p - 0.3
            c = p + 0.3
        else:
            o = p + 0.3
            c = p - 0.3
        rows.append({"open": o, "high": max(o, c) + 0.2,
                     "low": min(o, c) - 0.2, "close": c,
                     "volume": 1e5})
    return pd.DataFrame(rows, index=idx)


def _multi_tf_bars(symbol: str, bullish: bool) -> dict:
    """Build a full multi-TF bar set (60m/30m/15m) for a single symbol
    on one day. All TFs agree in direction."""
    trend = 0.5 if bullish else -0.5
    return {
        "60m": {symbol: _rth_bars(6, symbol, 100, trend, 60)},
        "30m": {symbol: _rth_bars(12, symbol, 100, trend, 30)},
        "15m": {symbol: _rth_bars(24, symbol, 100, trend, 15)},
    }


def _make_engine(db_path=None):
    cfg = load_config(Path("config"))
    cost = CostModel(cfg.cost_model)
    tracker = PnLTracker(initial_capital=10_000)
    ks = KillSwitch(KillSwitchConfig(max_drawdown=-0.99))
    if db_path is None:
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = f.name
        f.close()
    engine = PaperTradingEngine(
        cost_model=cost, pnl_tracker=tracker, db_path=db_path,
        initial_capital=10_000, kill_switch=ks,
    )
    return engine, db_path, cfg


# ──────────────────────────────────────────────────────────────────────────
# E2E: daily signals → timing → paper runtime → persistence
# ──────────────────────────────────────────────────────────────────────────

class TestDailyToTimingE2E:

    def test_bullish_day_every_bar_executes_with_timing(self):
        """All TFs bullish → decide_timing returns execute=True on every
        bar → paper engine fires trades + persists per-bar rows."""
        engine, db, cfg = _make_engine()
        date_ts = pd.Timestamp("2025-04-01")
        multi = _multi_tf_bars("AAPL", bullish=True)
        day_bars = {"AAPL": multi["60m"]["AAPL"]}

        # Daily MFS target (just a fake base weight for this test)
        daily_target = {"AAPL": 0.5}

        th = TimingThresholds.from_config(cfg.risk.intraday_timing)
        tp = make_timing_target_provider(multi, daily_target, thresholds=th)

        engine.run_day_intraday(
            run_id="e2e-bull", date=date_ts,
            day_bars=day_bars, target_wts={},
            timing_provider=tp,
        )

        conn = sqlite3.connect(db)
        n_fills = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='e2e-bull'"
        ).fetchone()[0]
        n_equity = conn.execute(
            "SELECT COUNT(*) FROM intraday_equity WHERE run_id='e2e-bull'"
        ).fetchone()[0]
        n_cp = conn.execute(
            "SELECT COUNT(*) FROM bar_checkpoints WHERE run_id='e2e-bull'"
        ).fetchone()[0]
        conn.close()

        # 6 bars → loop runs 5 iterations; at least one BUY fires on
        # bar 0 since cur_w is empty and target is 0.5
        assert n_fills > 0, "timing+runtime produced no fills"
        assert n_equity > 0, "per-bar equity rows not written"
        assert n_cp == 1, "no checkpoint written"

    def test_bearish_15m_defers_vs_bullish_60m(self):
        """60m bull + 30m bull + 15m BEAR → lower TF defers every bar
        → execute=False every bar → no fills, no position."""
        engine, db, cfg = _make_engine()
        date_ts = pd.Timestamp("2025-04-01")
        bull_60 = _rth_bars(6, "AAPL", 100, +0.5, 60)
        bull_30 = _rth_bars(12, "AAPL", 100, +0.5, 30)
        bear_15 = _rth_bars(24, "AAPL", 100, -0.5, 15)
        multi = {"60m": {"AAPL": bull_60}, "30m": {"AAPL": bull_30},
                 "15m": {"AAPL": bear_15}}
        day_bars = {"AAPL": bull_60}

        daily_target = {"AAPL": 0.5}
        th = TimingThresholds.from_config(cfg.risk.intraday_timing)
        tp = make_timing_target_provider(multi, daily_target, thresholds=th)

        engine.run_day_intraday(
            run_id="e2e-defer", date=date_ts,
            day_bars=day_bars, target_wts={},
            timing_provider=tp,
        )

        conn = sqlite3.connect(db)
        n_fills = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='e2e-defer'"
        ).fetchone()[0]
        conn.close()
        # EOD force-close still writes 0 fills (no position to close)
        assert n_fills == 0, (
            "15m bearish should defer every bar but fills were written"
        )

    def test_every_bar_drives_timing_decision(self):
        """Count decide_timing calls via the provider instrumentation
        and confirm one per processed bar."""
        engine, db, cfg = _make_engine()
        date_ts = pd.Timestamp("2025-04-01")
        multi = _multi_tf_bars("AAPL", bullish=True)
        day_bars = {"AAPL": multi["60m"]["AAPL"]}

        daily_target = {"AAPL": 0.5}
        th = TimingThresholds.from_config(cfg.risk.intraday_timing)

        # Wrap provider to count calls
        base_tp = make_timing_target_provider(multi, daily_target, thresholds=th)
        call_bars = []

        def _counting_tp(bar_ts, positions, cash):
            call_bars.append(bar_ts)
            return base_tp(bar_ts, positions, cash)

        engine.run_day_intraday(
            run_id="e2e-count", date=date_ts,
            day_bars=day_bars, target_wts={},
            timing_provider=_counting_tp,
        )

        # 6 bars → loop processes 5 (range(n_bars-1)); each should call
        # the provider exactly once before order generation.
        assert len(call_bars) == 5
        # Each call must use a distinct right-labeled bar close time
        assert len(set(call_bars)) == 5

    def test_idempotent_rerun_with_timing(self):
        """约束 1 invariant (idempotent re-run) must hold when
        timing_provider is in use."""
        engine, db, cfg = _make_engine()
        date_ts = pd.Timestamp("2025-04-01")
        multi = _multi_tf_bars("AAPL", bullish=True)
        day_bars = {"AAPL": multi["60m"]["AAPL"]}
        daily_target = {"AAPL": 0.5}
        th = TimingThresholds.from_config(cfg.risk.intraday_timing)
        tp = make_timing_target_provider(multi, daily_target, thresholds=th)

        engine.run_day_intraday(
            run_id="e2e-idemp", date=date_ts,
            day_bars=day_bars, target_wts={},
            timing_provider=tp,
        )
        conn = sqlite3.connect(db)
        n1 = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='e2e-idemp'"
        ).fetchone()[0]
        conn.close()

        # Fresh engine → same DB → same run_id should short-circuit
        engine2, _, _ = _make_engine(db_path=db)
        engine2.run_day_intraday(
            run_id="e2e-idemp", date=date_ts,
            day_bars=day_bars, target_wts={},
            timing_provider=tp,
        )
        conn = sqlite3.connect(db)
        n2 = conn.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='e2e-idemp'"
        ).fetchone()[0]
        conn.close()
        assert n1 > 0, "first run produced no fills"
        assert n2 == n1, "timing re-run produced duplicate fills"

    def test_provider_and_plain_target_produce_identical_counts_when_bullish(self):
        """Sanity: when timing never defers (all TFs bullish),
        provider path should produce the same NUMBER of fills as the
        static target path — i.e. timing is not spuriously introducing
        extra trades when it agrees with daily target."""
        engine_a, db_a, cfg = _make_engine()
        engine_b, db_b, _ = _make_engine()
        date_ts = pd.Timestamp("2025-04-01")
        multi = _multi_tf_bars("AAPL", bullish=True)
        day_bars = {"AAPL": multi["60m"]["AAPL"]}
        daily_target = {"AAPL": 0.5}

        # (a) plain target
        engine_a.run_day_intraday(
            run_id="e2e-plain", date=date_ts,
            day_bars=day_bars, target_wts=daily_target,
        )

        # (b) timing provider — all bullish → should be equivalent
        th = TimingThresholds.from_config(cfg.risk.intraday_timing)
        tp = make_timing_target_provider(multi, daily_target, thresholds=th)
        engine_b.run_day_intraday(
            run_id="e2e-timed", date=date_ts,
            day_bars=day_bars, target_wts={},
            timing_provider=tp,
        )

        conn_a = sqlite3.connect(db_a)
        conn_b = sqlite3.connect(db_b)
        n_a = conn_a.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='e2e-plain'"
        ).fetchone()[0]
        n_b = conn_b.execute(
            "SELECT COUNT(*) FROM intraday_fills WHERE run_id='e2e-timed'"
        ).fetchone()[0]
        conn_a.close()
        conn_b.close()
        assert n_a == n_b, (
            f"bullish timing path wrote {n_b} fills vs plain {n_a} — "
            "indicates provider side-effect on agreeing signal"
        )


# ──────────────────────────────────────────────────────────────────────────
# R6: short-circuit robust to bar growth / ref_sym changes
# ──────────────────────────────────────────────────────────────────────────

class TestShortCircuitRobustness:

    def test_rerun_with_extra_bar_continues(self):
        """If day_bars grows between calls (e.g. more bars arrive live),
        the engine must NOT short-circuit — it must process the new
        bars."""
        engine, db, _ = _make_engine()
        date_ts = pd.Timestamp("2025-04-01")

        short_bars = {"AAPL": _rth_bars(3, "AAPL", 100, +0.5, 60)}
        engine.run_day_intraday(
            run_id="e2e-grow", date=date_ts,
            day_bars=short_bars, target_wts={"AAPL": 0.5},
        )
        conn = sqlite3.connect(db)
        n_eq_1 = conn.execute(
            "SELECT COUNT(*) FROM intraday_equity WHERE run_id='e2e-grow'"
        ).fetchone()[0]
        conn.close()
        assert n_eq_1 >= 1

        # Now "more bars arrive": extend day_bars. Re-run on the same
        # (run_id, date). Engine should resume past the checkpoint.
        longer_bars = {"AAPL": _rth_bars(6, "AAPL", 100, +0.5, 60)}
        engine2, _, _ = _make_engine(db_path=db)
        engine2.run_day_intraday(
            run_id="e2e-grow", date=date_ts,
            day_bars=longer_bars, target_wts={"AAPL": 0.5},
        )
        conn = sqlite3.connect(db)
        n_eq_2 = conn.execute(
            "SELECT COUNT(*) FROM intraday_equity WHERE run_id='e2e-grow'"
        ).fetchone()[0]
        conn.close()
        assert n_eq_2 > n_eq_1, (
            f"extended bar set produced no new equity rows ({n_eq_1} → "
            f"{n_eq_2}) — short-circuit fired spuriously"
        )
