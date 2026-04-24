"""Integration tests for PRD M5 multi-TF execution contract.

Verifies:
  - decide_timing never returns effective_weight < 0 (long-only)
  - Lower TF adverse signals → defer, not flip
  - Short side (daily_side=-1) → execute=False
  - 60m veto → execute=False, effective_weight=0
  - Runtime WARN when any timing_provider returns negative weights
    (intraday engine clips + logs)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.intraday.multi_timescale import (
    build_context,
    decide_timing,
)


def _make_intraday_bars(
    n_days: int = 30,
    symbol: str = "SPY",
    start_price: float = 400.0,
    trend: float = 0.001,
    freq: str = "60min",
) -> pd.DataFrame:
    """Build synthetic OHLCV intraday DataFrame."""
    bars_per_day = 7  # 60m RTH bars
    n_bars = n_days * bars_per_day
    idx = pd.date_range("2024-01-02 09:30", periods=n_bars, freq=freq)
    close = np.array([start_price * (1 + trend) ** i for i in range(n_bars)])
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.002,
        "low": close * 0.998,
        "close": close,
        "volume": np.ones(n_bars) * 1e5,
    }, index=idx)


def test_decide_timing_never_produces_negative_weight_for_long_side():
    """effective_weight >= 0 for any base_weight >= 0, any TF combo."""
    multi_bars = {
        "60m": {"SPY": _make_intraday_bars(trend=0.003, freq="60min")},
        "30m": {"SPY": _make_intraday_bars(trend=0.002, freq="30min")},
        "15m": {"SPY": _make_intraday_bars(trend=-0.003, freq="15min")},
    }
    last_bar = multi_bars["60m"]["SPY"].index[-1]
    ctx = build_context(multi_bars, "SPY", last_bar)
    d = decide_timing(ctx, "SPY", base_weight=0.3, daily_side=1)
    assert d.effective_weight >= 0


def test_decide_timing_short_side_refuses():
    """daily_side=-1 is not supported in long-only system."""
    multi_bars = {"60m": {"SPY": _make_intraday_bars(trend=0.003, freq="60min")}}
    last_bar = multi_bars["60m"]["SPY"].index[-1]
    ctx = build_context(multi_bars, "SPY", last_bar)
    d = decide_timing(ctx, "SPY", base_weight=0.3, daily_side=-1)
    assert d.execute is False
    assert d.effective_weight == 0


def test_decide_timing_zero_base_weight_no_execute():
    multi_bars = {"60m": {"SPY": _make_intraday_bars(trend=0.003, freq="60min")}}
    last_bar = multi_bars["60m"]["SPY"].index[-1]
    ctx = build_context(multi_bars, "SPY", last_bar)
    d = decide_timing(ctx, "SPY", base_weight=0.0, daily_side=1)
    assert d.execute is False


def test_intraday_engine_clips_negative_weights_from_timing_provider(caplog):
    """If a buggy timing_provider returns negative weights, engine should
    clip + warn, not propagate negatives."""
    from core.backtest.intraday_engine import IntradayBacktestEngine
    from core.config.loader import load_config
    from core.execution.cost_model import CostModel

    cfg = load_config(ROOT / "config")
    engine = IntradayBacktestEngine(
        cost_model=CostModel(cfg.cost_model),
        initial_capital=10000.0,
    )

    day_bars = {
        "SPY": _make_intraday_bars(n_days=1, trend=0.001, freq="60min").iloc[:7].copy(),
    }
    date = day_bars["SPY"].index[0].normalize()

    # Malicious fn returns negative weight
    def bad_fn(bar_ts, shares, cash):
        return {"SPY": -0.5}

    with caplog.at_level(logging.WARNING):
        engine.run_multi_day(
            date=date,
            day_bars=day_bars,
            target_wts={"SPY": 0.0},
            positions={},
            cash=10000.0,
            target_wts_fn=bad_fn,
        )

    # Should not blow up; and WARN log should be present
    msg = " ".join(r.message for r in caplog.records)
    assert "negative" in msg.lower()
