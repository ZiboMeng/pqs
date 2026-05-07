"""Master PRD §4.2 Phase B.2 (R4 ship 2026-05-07) — SR defer mining
integration tests.

Per PRD-AC §1.3 user explicit-go: when ResearchCompositeSpec is sampled
with ``enable_sr_defer=True`` AND ResearchMiner was constructed with
non-None ``intraday_bars_60m``, ``evaluate_composite`` must apply
``apply_sr_defer_filter`` to the harness's baseline weights and re-run
BacktestEngine on the filtered weights when activation ≥ 5% (I6
prefilter).

Phase 3 round 1 stub behavior (intraday_bars_60m=None) MUST remain
bit-for-bit unchanged — see ``test_baseline_unchanged_when_intraday_none``.
"""

from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd
import pytest

from core.mining.research_miner import (
    ObjectiveWeights,
    ResearchCompositeSpec,
    ResearchMiner,
    evaluate_composite,
    zscore_cs,
)


# ── Synthetic panel builder (mirrors test_prd_ac_phase3_search_space) ─────────


def _build_panel(n_days=180, n_syms=8, seed=0):
    """Synthetic price + factor panel for harness eval."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    syms = [f"S{i}" for i in range(n_syms)]
    market = rng.normal(0, 0.01, size=n_days)
    sym_specific = rng.normal(0, 0.005, size=(n_days, n_syms))
    rets = market[:, None] + sym_specific
    prices = 100.0 * np.cumprod(1 + rets, axis=0)
    price_df = pd.DataFrame(prices, index=dates, columns=syms)
    open_df = price_df * (1 + rng.normal(0, 0.001, size=(n_days, n_syms)))
    fwd = price_df.pct_change(21).shift(-21)
    panel_map = {
        "momentum_20d": zscore_cs(price_df.pct_change(20)),
        "momentum_60d": zscore_cs(price_df.pct_change(60)),
    }
    spy = pd.Series(
        400.0 * np.cumprod(1 + market + rng.normal(0, 0.001, size=n_days)),
        index=dates, name="SPY",
    )
    qqq = pd.Series(
        300.0 * np.cumprod(
            1 + market * 1.1 + rng.normal(0, 0.002, size=n_days)
        ),
        index=dates, name="QQQ",
    )
    return panel_map, fwd, price_df, open_df, spy, qqq


def _build_60m_bars_high_activation(price_df: pd.DataFrame) -> dict:
    """Build 60m bars where every RTH bar's close is at-or-above the
    rolling-window swing high — apply_sr_defer_filter should fire on
    nearly every (date, sym) cell.

    Strategy: synthetic monotone-rising 60m bars with each day's last
    RTH bar exactly at the lookback-window max → close = R, distance = 0,
    triggers the near_resistance_pct=0.5% threshold.
    """
    bars = {}
    daily_dates = price_df.index
    for sym in price_df.columns:
        rows = []
        for d in daily_dates:
            # 7 RTH 60m bars per day: 09:30, 10:30, ..., 15:30 (post-market 16:00 excl)
            for hh in (9, 10, 11, 12, 13, 14, 15):
                ts = pd.Timestamp(d.date()) + pd.Timedelta(
                    hours=hh, minutes=30 if hh == 9 else 0,
                )
                rows.append({
                    "ts": ts,
                    "close": float(price_df.loc[d, sym]),
                    "high": float(price_df.loc[d, sym]) * 1.0001,
                    "low": float(price_df.loc[d, sym]) * 0.9999,
                    "open": float(price_df.loc[d, sym]),
                    "volume": 1_000_000,
                })
        df = pd.DataFrame(rows).set_index("ts").sort_index()
        bars[sym] = df
    return bars


def _build_60m_bars_low_activation(price_df: pd.DataFrame) -> dict:
    """60m bars where the daily close is FAR below recent swing high —
    apply_sr_defer_filter should NOT fire (activation < 5%).
    """
    bars = {}
    daily_dates = price_df.index
    for sym in price_df.columns:
        rows = []
        # Synthetic monotone DOWN-trend at intraday level — last RTH bar
        # close is FAR below the 20-bar lookback max.
        for i, d in enumerate(daily_dates):
            base = float(price_df.loc[d, sym])
            for hh in (9, 10, 11, 12, 13, 14, 15):
                ts = pd.Timestamp(d.date()) + pd.Timedelta(
                    hours=hh, minutes=30 if hh == 9 else 0,
                )
                # Down-trending intraday: peak at 09:30, declining
                price = base * (1.0 + 0.05 - 0.01 * (hh - 9))
                rows.append({
                    "ts": ts,
                    "close": price,
                    "high": price * 1.0001,
                    "low": price * 0.9999,
                    "open": price,
                    "volume": 1_000_000,
                })
        df = pd.DataFrame(rows).set_index("ts").sort_index()
        bars[sym] = df
    return bars


# ── Tests ────────────────────────────────────────────────────────────────────


def test_baseline_unchanged_when_intraday_none():
    """Phase 3 round 1 stub: spec.enable_sr_defer=True with
    intraday_bars_60m=None → evaluate_composite produces SAME metrics as
    spec.enable_sr_defer=False (filter is no-op when no 60m data)."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    spec_no_defer = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        enable_sr_defer=False,
    )
    spec_defer_no_bars = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        enable_sr_defer=True,
    )
    metrics_baseline = evaluate_composite(
        spec_no_defer, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        compute_nav=True,
        intraday_bars_60m=None,
    )
    metrics_defer_no_bars = evaluate_composite(
        spec_defer_no_bars, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        compute_nav=True,
        intraday_bars_60m=None,
    )
    # Without intraday_bars_60m, filter is skipped → identical NAV.
    # Use NaN-safe equality (raw == returns False on NaN).
    def _eq(a, b):
        if pd.isna(a) and pd.isna(b):
            return True
        return a == b

    assert _eq(metrics_baseline.nav_sharpe, metrics_defer_no_bars.nav_sharpe)
    assert _eq(metrics_baseline.nav_max_dd, metrics_defer_no_bars.nav_max_dd)
    assert _eq(metrics_baseline.ic_ir, metrics_defer_no_bars.ic_ir)


def test_sr_defer_high_activation_triggers_second_backtest(monkeypatch):
    """When SR defer filter fires materially (stubbed 80% activation),
    the I6 prefilter (≥ 5%) lets the second BacktestEngine run path
    execute. Verified by spying on BacktestEngine.run call count: ONE
    baseline call (from harness's expost_eval) + ONE filtered call
    (from research_miner R4 path) = 2 invocations under
    spec.enable_sr_defer=True; ONE invocation under =False.
    """
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    bars = _build_60m_bars_low_activation(price_df)  # any non-empty dict

    from core.research import sr_signal_filter as srf

    def _stub_filter(target_wts, intraday, config=None, start=None, end=None):
        out = target_wts.copy()
        n_evaluated = max(int((target_wts > 0).sum().sum()), 100)
        n_defers = int(0.8 * n_evaluated)
        stats = srf.SRDeferStats(
            n_defers=n_defers,
            n_evaluated=n_evaluated,
            n_skipped_no_60m_coverage=0,
            n_skipped_short_history=0,
            n_skipped_no_rth_bars_today=0,
        )
        return out, stats

    monkeypatch.setattr(srf, "apply_sr_defer_filter", _stub_filter)

    # Spy on BacktestEngine.run via a counter
    from core.backtest import backtest_engine as bem
    real_run = bem.BacktestEngine.run
    call_counter = {"n": 0}

    def _spy_run(self, *args, **kwargs):
        call_counter["n"] += 1
        return real_run(self, *args, **kwargs)

    monkeypatch.setattr(bem.BacktestEngine, "run", _spy_run)

    spec_no_defer = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        enable_sr_defer=False,
    )
    spec_defer = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        enable_sr_defer=True,
    )

    # Run baseline (no defer) — expect 1 BacktestEngine.run call
    call_counter["n"] = 0
    evaluate_composite(
        spec_no_defer, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        compute_nav=True,
        intraday_bars_60m=bars,
    )
    n_baseline = call_counter["n"]

    # Run defer with stubbed high-activation — expect 2 BacktestEngine.run calls
    call_counter["n"] = 0
    evaluate_composite(
        spec_defer, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        compute_nav=True,
        intraday_bars_60m=bars,
    )
    n_defer = call_counter["n"]

    assert n_baseline == 1, (
        f"baseline (enable_sr_defer=False) should call BacktestEngine.run "
        f"once, got {n_baseline}"
    )
    assert n_defer == 2, (
        f"defer (enable_sr_defer=True + 80% stub activation) should call "
        f"BacktestEngine.run twice (baseline + filtered), got {n_defer}"
    )


def test_sr_defer_low_activation_uses_baseline_nav():
    """I6 prefilter: when activation_rate < 5%, baseline NAV must be
    used (no second BacktestEngine run). Verified by NAV equality
    between spec.enable_sr_defer=True and =False on the same panel."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    bars_low = _build_60m_bars_low_activation(price_df)
    spec_no_defer = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        enable_sr_defer=False,
    )
    spec_defer = ResearchCompositeSpec(
        features=("momentum_20d", "momentum_60d"),
        weights=(0.5, 0.5), family_counts={"A": 2},
        enable_sr_defer=True,
    )
    metrics_baseline = evaluate_composite(
        spec_no_defer, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        compute_nav=True,
        intraday_bars_60m=bars_low,
    )
    metrics_defer = evaluate_composite(
        spec_defer, panel_map, fwd,
        price_df=price_df, open_df=open_df,
        spy_series=spy, qqq_series=qqq,
        compute_nav=True,
        intraday_bars_60m=bars_low,
    )
    # I6 prefilter skips second harness when activation < 5% → identical
    # NAV. Allow tiny floating-point tolerance just in case.
    if metrics_baseline.nav_sharpe == metrics_baseline.nav_sharpe:  # not NaN
        assert (
            abs(metrics_baseline.nav_sharpe - metrics_defer.nav_sharpe) < 1e-9
        ), (
            "I6 prefilter should keep NAV unchanged when activation < 5%; "
            f"baseline={metrics_baseline.nav_sharpe} defer={metrics_defer.nav_sharpe}"
        )


def test_research_miner_rejects_true_choices_without_intraday_bars():
    """Constructor contract: enable_sr_defer_choices contains True →
    intraday_bars_60m MUST be provided (else SR defer is sampled but
    silently no-op, defeating the search dim)."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    with pytest.raises(ValueError, match="intraday_bars_60m"):
        ResearchMiner(
            factor_panel_map=panel_map,
            fwd_returns=fwd,
            objective_weights=ObjectiveWeights(),  # v1_legacy (no NAV path)
            enable_sr_defer_choices=(False, True),
            intraday_bars_60m=None,  # contract violation
        )


def test_research_miner_accepts_true_choices_with_intraday_bars():
    """Constructor accepts (False, True) when intraday_bars_60m supplied."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    bars = _build_60m_bars_low_activation(price_df)
    miner = ResearchMiner(
        factor_panel_map=panel_map,
        fwd_returns=fwd,
        objective_weights=ObjectiveWeights(),
        enable_sr_defer_choices=(False, True),
        intraday_bars_60m=bars,
    )
    assert miner.intraday_bars_60m is bars
    assert tuple(miner.enable_sr_defer_choices) == (False, True)


def test_legacy_caller_unchanged_no_intraday_bars():
    """Backward compat: legacy callers (cycle04/05/06 archive replay)
    construct ResearchMiner without intraday_bars_60m AND without True in
    sr_defer choices — must NOT raise."""
    panel_map, fwd, price_df, open_df, spy, qqq = _build_panel()
    # No intraday_bars_60m; choices stays default (False,)
    miner = ResearchMiner(
        factor_panel_map=panel_map,
        fwd_returns=fwd,
        objective_weights=ObjectiveWeights(),
    )
    assert miner.intraday_bars_60m is None
    assert tuple(miner.enable_sr_defer_choices) == (False,)
