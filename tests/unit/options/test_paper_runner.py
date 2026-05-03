"""Unit tests for options forward paper-trading runner.

Covers: spec hash determinism, init/observe state machine, idempotency,
overlay close logic, expiry handling.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from core.options.paper.spec import (
    StrategySpec, OverlayParams, VolRegimeFilterParams, PricingParams,
    load_spec, write_spec,
)
from core.options.paper.runner import init_run, observe, _is_last_bday_of_month


@pytest.fixture
def spec_factory():
    def _make(**overrides):
        # Note: risk_per_trade_pct=0.12 because $10K NAV @ 2pct = $200
        # which is too small for one SPY 8pct OTM bull put (~$1000 max loss
        # per contract). Real production needs $30K+ NAV for 2pct risk on
        # SPY-direct, OR XSP (mini-SPX, 1/10 size), OR widen risk to ~12pct.
        defaults = dict(
            candidate_id="test_run",
            strategy_type="bull_put_spread",
            underlying="SPY", short_otm_pct=0.08, long_otm_pct=0.10,
            dte_open_days=30, risk_per_trade_pct=0.12,
            initial_nav=10000.0, created_at="2026-05-02",
            overlay=OverlayParams(),
            vol_regime_filter=VolRegimeFilterParams(enabled=False),
            pricing=PricingParams(),
        )
        defaults.update(overrides)
        return StrategySpec(**defaults)
    return _make


def test_spec_hash_deterministic(spec_factory):
    s1 = spec_factory()
    s2 = spec_factory()
    assert s1.spec_hash() == s2.spec_hash()


def test_spec_hash_changes_when_param_changes(spec_factory):
    s1 = spec_factory(short_otm_pct=0.08)
    s2 = spec_factory(short_otm_pct=0.05)
    assert s1.spec_hash() != s2.spec_hash()


def test_spec_yaml_roundtrip(tmp_path, spec_factory):
    spec = spec_factory()
    yaml_path = tmp_path / "spec.yaml"
    h1 = write_spec(spec, yaml_path)
    spec2 = load_spec(yaml_path)
    h2 = spec2.spec_hash()
    assert h1 == h2


def test_init_creates_run_dir_and_manifest(tmp_path, spec_factory):
    spec = spec_factory()
    state = init_run(spec, base_dir=tmp_path, start_date="2026-05-04")
    assert state.spec_hash == spec.spec_hash()
    assert state.start_date == "2026-05-04"
    assert state.nav_initial == 10000.0
    assert state.cash == 10000.0
    assert (tmp_path / "test_run" / "spec.yaml").exists()
    assert (tmp_path / "test_run" / "manifest.json").exists()


def test_init_idempotent(tmp_path, spec_factory):
    spec = spec_factory()
    state1 = init_run(spec, base_dir=tmp_path, start_date="2026-05-04")
    state2 = init_run(spec, base_dir=tmp_path, start_date="2026-05-04")
    assert state1.spec_hash == state2.spec_hash
    assert state1.start_date == state2.start_date


def test_init_rejects_spec_hash_mismatch(tmp_path, spec_factory):
    s1 = spec_factory(short_otm_pct=0.08)
    init_run(s1, base_dir=tmp_path, start_date="2026-05-04")
    s2 = spec_factory(short_otm_pct=0.05)
    with pytest.raises(RuntimeError, match="DIFFERENT spec_hash"):
        init_run(s2, base_dir=tmp_path)


def _synthetic_spy_history(end_date: datetime, n_days: int = 60,
                            base: float = 580.0, drift: float = 0.3) -> pd.Series:
    idx = pd.bdate_range(end=end_date, periods=n_days)
    return pd.Series([base + i * drift for i in range(n_days)], index=idx)


def test_observe_first_call_writes_td001(tmp_path, spec_factory):
    spec = spec_factory()
    init_run(spec, base_dir=tmp_path, start_date="2026-05-04")
    today = datetime(2026, 5, 4)
    hist = _synthetic_spy_history(today)
    res = observe(spec, today, spot=600.0, vix=18.0,
                  spy_history_close=hist, base_dir=tmp_path)
    assert res["status"] == "observed"
    assert res["n_observe_days"] == 1
    assert res["nav"] == 10000.0
    assert (tmp_path / "test_run" / "daily_nav.csv").exists()


def test_observe_idempotent_same_day(tmp_path, spec_factory):
    spec = spec_factory()
    init_run(spec, base_dir=tmp_path, start_date="2026-05-04")
    today = datetime(2026, 5, 4)
    hist = _synthetic_spy_history(today)
    observe(spec, today, 600.0, 18.0, hist, base_dir=tmp_path)
    res = observe(spec, today, 600.0, 18.0, hist, base_dir=tmp_path)
    assert res["status"] == "skipped_already_today"


def test_observe_opens_position_on_last_bday_of_month(tmp_path, spec_factory):
    """Last bday of month + vol_regime_filter disabled = should open position."""
    spec = spec_factory()
    init_run(spec, base_dir=tmp_path, start_date="2026-05-29")
    today = datetime(2026, 5, 29)  # Last Friday of May 2026
    assert _is_last_bday_of_month(today), "test setup error: 2026-05-29 should be last bday"
    hist = _synthetic_spy_history(today)
    res = observe(spec, today, 600.0, 18.0, hist, base_dir=tmp_path)
    assert res["open_positions"] == 1
    assert any("opened" in e for e in res["events"])


def test_observe_no_open_when_vix_above_halt(tmp_path, spec_factory):
    spec = spec_factory()
    init_run(spec, base_dir=tmp_path, start_date="2026-05-29")
    today = datetime(2026, 5, 29)  # last bday
    hist = _synthetic_spy_history(today)
    res = observe(spec, today, 600.0, 50.0, hist, base_dir=tmp_path)
    assert res["open_positions"] == 0


def test_observe_no_open_when_not_last_bday(tmp_path, spec_factory):
    spec = spec_factory()
    init_run(spec, base_dir=tmp_path, start_date="2026-05-04")
    today = datetime(2026, 5, 4)  # Mon, not last bday
    assert not _is_last_bday_of_month(today)
    hist = _synthetic_spy_history(today)
    res = observe(spec, today, 600.0, 18.0, hist, base_dir=tmp_path)
    assert res["open_positions"] == 0


def test_observe_full_cycle_open_then_expire_worthless(tmp_path, spec_factory):
    """Open a position, advance to expiry with spot well above strikes,
    confirm expire_worthless + cash credited."""
    spec = spec_factory(dte_open_days=21)
    init_run(spec, base_dir=tmp_path, start_date="2026-05-29")
    today = datetime(2026, 5, 29)
    hist = _synthetic_spy_history(today)
    # Open at SPY=600
    observe(spec, today, 600.0, 18.0, hist, base_dir=tmp_path)
    # Advance day-by-day to expiry; spot rises to 620 (well above 8% OTM put)
    for d in range(1, 25):
        next_day = today + timedelta(days=d)
        if next_day.weekday() >= 5: continue  # skip weekends
        spot_now = 600.0 + d * 0.5
        observe(spec, next_day, spot_now, 18.0, hist, base_dir=tmp_path)

    manifest = json.loads((tmp_path / "test_run" / "manifest.json").read_text())
    # Position should have closed by now (either expiry_worthless or early_tp)
    assert manifest["closed_positions_count"] >= 1
    assert manifest["realized_pnl_cumulative"] != 0


def test_vol_regime_filter_blocks_when_outside_band(tmp_path, spec_factory):
    spec = spec_factory(vol_regime_filter=VolRegimeFilterParams(
        enabled=True, vix_min=12.0, vix_max=25.0, require_positive_vrp=False,
    ))
    init_run(spec, base_dir=tmp_path, start_date="2026-05-29")
    today = datetime(2026, 5, 29)
    hist = _synthetic_spy_history(today)
    # VIX=10 < vix_min=12 → should NOT open
    res = observe(spec, today, 600.0, 10.0, hist, base_dir=tmp_path)
    assert res["open_positions"] == 0


def test_is_last_bday_of_month():
    # 2026-05-29 is Friday, last weekday of May 2026
    assert _is_last_bday_of_month(datetime(2026, 5, 29))
    # 2026-05-04 is Monday, plenty of more weekdays in May
    assert not _is_last_bday_of_month(datetime(2026, 5, 4))
    # 2026-04-30 is Thursday, last weekday of April 2026 (May 1 = Friday is in May)
    assert _is_last_bday_of_month(datetime(2026, 4, 30))
