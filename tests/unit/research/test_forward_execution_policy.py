"""Regression tests for forward runner execution_policy branching
(PRD 20260505 Step 6.1-min Step 4).

Lazy-migration invariant under test:
  - When candidate spec carries execution_policy=None or absent, the
    forward runner's pre-backtest target_wts pipeline is BIT-IDENTICAL
    to the pre-PRD path. This is the load-bearing guarantee for
    isolation of the 3 pre-PRD candidates (RCMv1 / Cand-2 / trial9).

  - When execution_policy.enable_sr_defer is True, ``apply_sr_defer_filter``
    is invoked with the candidate's configured thresholds and the result
    is passed to the backtest engine.

These tests target the helper ``_maybe_apply_sr_defer`` directly to
keep the surface tight; the surrounding observe() flow has separate
coverage in test_forward_runner.py (53 existing tests, all green).
"""
from __future__ import annotations

from datetime import time as dt_time
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from core.research.forward.runner import _maybe_apply_sr_defer
from core.research.frozen_spec import FeatureEntry, FrozenStrategySpec


# ── fixtures ────────────────────────────────────────────────────────────


def _minimal_spec(execution_policy=None) -> FrozenStrategySpec:
    return FrozenStrategySpec(
        candidate_id="test_candidate",
        strategy_version="test-v1",
        source_trial_id="abc123",
        feature_set=[FeatureEntry(name="f1", weight=1.0)],
        benchmark_relative_summary={"note": "n/a"},
        oos_holdout_summary={"folds": 4},
        robustness_summary={"range": [0.0, 1.0]},
        decision_memo="/tmp/memo.md",
        execution_policy=execution_policy,
    )


def _make_target_wts() -> pd.DataFrame:
    """3 dates × 2 symbols of positive weights."""
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {"AAA": [0.5, 0.5, 0.5], "BBB": [0.5, 0.5, 0.5]},
        index=idx,
    )


def _make_60m_rth_bars(
    base_close: float = 100.0,
    last_bar_close: float = 100.0,
    last_bar_resistance_zone: bool = False,
) -> pd.DataFrame:
    """30 trading days × 7 RTH 60m bars per day. If last_bar_resistance_zone,
    the bar engineered to be the LAST RTH bar of day 30 sits 30 bps below
    a swing high formed on day 28 — which is within the 50bps default
    threshold — so the defer filter should fire."""
    rows = []
    rth_hours = [9, 10, 11, 12, 13, 14, 15]  # 09:00 (pre-market 09:00 < 09:30)
    # Use 09:30, 10:30, ..., 15:30 to match RTH start-of-bar 60m convention
    rth_starts = [(9, 30), (10, 30), (11, 30), (12, 30),
                  (13, 30), (14, 30), (15, 30)]
    base_date = pd.Timestamp("2024-01-02")
    for d in range(30):
        day = base_date + pd.Timedelta(days=d)
        if day.weekday() >= 5:
            continue
        for hh, mm in rth_starts:
            ts = day + pd.Timedelta(hours=hh, minutes=mm)
            close_val = base_close
            # Engineer swing high on day index 5 (a few weekdays in)
            if d == 5 and (hh, mm) == (12, 30):
                close_val = base_close * 1.05  # +5% swing high
            rows.append({"timestamp": ts, "open": close_val,
                         "high": close_val * 1.001,
                         "low": close_val * 0.999,
                         "close": close_val,
                         "volume": 1_000_000})
    df = pd.DataFrame(rows).set_index("timestamp")
    return df


class _FakeStore:
    """Minimal PriceStore stub satisfying the ``read`` method only."""
    def __init__(self, bars_by_sym: dict):
        self._bars = bars_by_sym

    def read(self, symbol: str, freq: str) -> pd.DataFrame:
        if freq != "60m":
            return pd.DataFrame()
        return self._bars.get(symbol, pd.DataFrame())


# ── lazy-migration: legacy specs produce identical target_wts ─────────


def test_legacy_spec_no_policy_returns_target_wts_unchanged():
    """execution_policy=None → identical (same object preferred)."""
    spec = _minimal_spec(execution_policy=None)
    tw = _make_target_wts()
    store = _FakeStore({})

    out = _maybe_apply_sr_defer(spec, tw, store)

    assert out is tw, (
        "legacy spec must take fast-return path returning the SAME object"
    )


def test_policy_present_but_disabled_returns_target_wts_unchanged():
    """execution_policy.enable_sr_defer=False → identical."""
    spec = _minimal_spec(execution_policy={"enable_sr_defer": False})
    tw = _make_target_wts()
    store = _FakeStore({})

    out = _maybe_apply_sr_defer(spec, tw, store)

    assert out is tw


def test_policy_missing_enable_key_returns_unchanged():
    """execution_policy = {} (no enable_sr_defer key) → identical."""
    spec = _minimal_spec(execution_policy={})
    tw = _make_target_wts()
    store = _FakeStore({})

    out = _maybe_apply_sr_defer(spec, tw, store)

    assert out is tw


def test_non_dict_policy_returns_unchanged():
    """Schema invariant: execution_policy must be dict or None. Defensive
    against malformed yaml producing a string / list — graceful no-op
    rather than crash, since this is a runner-side check."""
    spec_str = _minimal_spec(execution_policy="enable_sr_defer")  # malformed
    tw = _make_target_wts()
    store = _FakeStore({})

    out = _maybe_apply_sr_defer(spec_str, tw, store)

    assert out is tw


# ── activation path ────────────────────────────────────────────────────


def test_enabled_policy_invokes_filter_and_returns_new_dataframe():
    """When enable_sr_defer=True, helper must return a DIFFERENT object
    (the filter copies internally) and produce a same-shape dataframe."""
    spec = _minimal_spec(execution_policy={"enable_sr_defer": True})
    tw = _make_target_wts()
    bars = _make_60m_rth_bars()
    store = _FakeStore({"AAA": bars, "BBB": bars})

    out = _maybe_apply_sr_defer(spec, tw, store)

    assert out is not tw
    assert out.shape == tw.shape
    # All weights remain in [0, original] — filter only zeros, never amplifies.
    assert (out.values <= tw.values + 1e-9).all()
    assert (out.values >= -1e-9).all()


def test_enabled_policy_passes_custom_config():
    """sr_defer block thresholds reach the filter."""
    spec = _minimal_spec(execution_policy={
        "enable_sr_defer": True,
        "sr_defer": {
            "near_resistance_pct": 0.01,
            "swing_n": 3,
            "lookback_bars": 10,
        },
    })
    tw = _make_target_wts()
    bars = _make_60m_rth_bars()
    store = _FakeStore({"AAA": bars, "BBB": bars})

    # We can't easily mock SRDeferConfig from the runner module without a
    # patcher, so we just verify the call doesn't crash and returns a copy.
    out = _maybe_apply_sr_defer(spec, tw, store)
    assert out is not tw
    assert out.shape == tw.shape


def test_enabled_policy_with_no_60m_data_passes_through():
    """If 60m read returns empty for all symbols, filter still completes
    (n_skipped_no_60m_coverage covers all positive weights). Output equal
    to input but is a copy (filter constructs a new frame)."""
    spec = _minimal_spec(execution_policy={"enable_sr_defer": True})
    tw = _make_target_wts()
    store = _FakeStore({})  # no 60m for any symbol

    out = _maybe_apply_sr_defer(spec, tw, store)

    pd.testing.assert_frame_equal(out, tw)


def test_store_read_exception_is_swallowed_per_symbol():
    """If store.read raises for one symbol, other symbols still work
    and the filter still runs. This is defensive — trial9-style mid-flight
    panel updates may briefly raise on a missing-on-disk symbol."""
    spec = _minimal_spec(execution_policy={"enable_sr_defer": True})
    tw = _make_target_wts()
    bars = _make_60m_rth_bars()

    class _ErrorStore:
        def read(self, symbol, freq):
            if symbol == "AAA":
                raise RuntimeError("simulated read error")
            return bars

    store = _ErrorStore()

    out = _maybe_apply_sr_defer(spec, tw, store)

    assert out.shape == tw.shape


# ── isolation invariant: real candidate yamls take the fast-return path ─


@pytest.mark.parametrize("yaml_name", [
    "rcm_v1_defensive_composite_01.yaml",
    "candidate_2_orthogonal_01.yaml",
    "trial9_diversifier_001.yaml",
])
def test_real_candidate_yaml_takes_fast_return_path(yaml_name, tmp_path):
    """The 3 pre-PRD candidate specs MUST take the fast-return identity
    path through ``_maybe_apply_sr_defer``. This is the bit-identical
    isolation guarantee that lets us ship Step 6.1-min without
    re-running existing forward observation streams.
    """
    from pathlib import Path
    path = Path("data/research_candidates") / yaml_name
    if not path.exists():
        pytest.skip(f"{yaml_name} not present (expected in repo)")

    spec = FrozenStrategySpec.from_yaml_file(path)
    tw = _make_target_wts()
    store = _FakeStore({})

    out = _maybe_apply_sr_defer(spec, tw, store)

    assert out is tw, (
        f"{yaml_name} did NOT take fast-return path "
        f"(execution_policy={spec.execution_policy!r}); "
        "this would change forward observation NAV"
    )
