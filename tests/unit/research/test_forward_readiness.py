"""Forward readiness guard tests (post-MVP P1)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from core.research.forward import check_readiness, init


def _setup_min_repo(tmp_path: Path, candidate_id: str) -> tuple:
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    spec = out_dir / f"{candidate_id}.yaml"
    spec.write_text(_minimal_spec_yaml(candidate_id))
    cost = tmp_path / "cost.yaml"
    cost.write_text("commission_per_trade: 0.005\nslippage_bps: 5\n")
    return out_dir, cost


def _minimal_spec_yaml(cid: str) -> str:
    return f"""
candidate_id: {cid}
strategy_version: test-v1-2026-04-26
source_trial_id: test_trial
feature_set:
  - name: ret_5d
    weight: 1.0
    family: B
    source: core/factors/factor_generator.py
benchmark_relative_summary: 'test'
oos_holdout_summary: 'test'
robustness_summary: 'test'
decision_memo: 'test'
"""


def test_readiness_data_behind_start_date(tmp_path: Path, monkeypatch):
    out_dir, cost = _setup_min_repo(tmp_path, "rcand")
    init(candidate_id="rcand", start_date="2026-05-01",
         output_dir=out_dir, cost_model_path=cost)
    daily = tmp_path / "daily"
    daily.mkdir()
    # SPY ends 2026-04-25 — BEHIND the candidate's start_date (5-01)
    spy_idx = pd.DatetimeIndex(["2026-04-23", "2026-04-24", "2026-04-25"])
    pd.DataFrame(
        {"open": 1, "close": 1, "volume": 1}, index=spy_idx,
    ).to_parquet(daily / "SPY.parquet")
    rep = check_readiness(
        "rcand", output_dir=out_dir, daily_dir=daily,
        boundaries_path=tmp_path / "no_sidecar.parquet",
    )
    assert rep.can_append_now is False
    assert rep.latest_data_date == date(2026, 4, 25)
    assert rep.start_date == date(2026, 5, 1)
    assert any("wait for ingest to catch up" in n for n in rep.notes)


def test_readiness_data_ahead_can_append(tmp_path: Path):
    out_dir, cost = _setup_min_repo(tmp_path, "rcand")
    init(candidate_id="rcand", start_date="2026-04-21",
         output_dir=out_dir, cost_model_path=cost)
    daily = tmp_path / "daily"
    daily.mkdir()
    spy_idx = pd.DatetimeIndex(
        ["2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24"]
    )
    pd.DataFrame(
        {"open": 1, "close": 1, "volume": 1}, index=spy_idx,
    ).to_parquet(daily / "SPY.parquet")
    rep = check_readiness(
        "rcand", output_dir=out_dir, daily_dir=daily,
        boundaries_path=tmp_path / "no_sidecar.parquet",
    )
    assert rep.can_append_now is True
    assert rep.n_potential_new_tds == 4
    assert rep.next_expected_td == date(2026, 4, 21)


def test_readiness_data_caught_up_no_new_bars(tmp_path: Path):
    """Last observed = latest data → idempotent no-op state."""
    from core.research.forward.manifest_io import (
        load_manifest, manifest_path, save_manifest,
    )
    from core.research.forward.manifest_schema import ForwardRun

    out_dir, cost = _setup_min_repo(tmp_path, "rcand")
    init(candidate_id="rcand", start_date="2026-04-21",
         output_dir=out_dir, cost_model_path=cost)
    # Add a fake TD entry at 2026-04-24
    p = manifest_path("rcand", out_dir)
    m = load_manifest(p)
    new_runs = list(m.runs) + [ForwardRun(
        checkpoint_label="TD002", as_of_date=date(2026, 4, 24),
        n_observed_trading_days=2,
    )]
    m2 = m.model_copy(update={"runs": new_runs})
    save_manifest(m2, p)

    daily = tmp_path / "daily"
    daily.mkdir()
    spy_idx = pd.DatetimeIndex(["2026-04-23", "2026-04-24"])
    pd.DataFrame(
        {"open": 1, "close": 1, "volume": 1}, index=spy_idx,
    ).to_parquet(daily / "SPY.parquet")
    rep = check_readiness(
        "rcand", output_dir=out_dir, daily_dir=daily,
        boundaries_path=tmp_path / "no_sidecar.parquet",
    )
    assert rep.last_observed_date == date(2026, 4, 24)
    assert rep.can_append_now is False
    assert rep.n_potential_new_tds == 0


def test_readiness_handles_missing_spy_parquet(tmp_path: Path):
    out_dir, cost = _setup_min_repo(tmp_path, "rcand")
    init(candidate_id="rcand", start_date="2026-04-21",
         output_dir=out_dir, cost_model_path=cost)
    daily = tmp_path / "daily"
    daily.mkdir()
    # No SPY parquet at all
    rep = check_readiness(
        "rcand", output_dir=out_dir, daily_dir=daily,
        boundaries_path=tmp_path / "no_sidecar.parquet",
    )
    assert rep.can_append_now is False
    assert rep.latest_data_date is None
    assert any("uninitialized" in n for n in rep.notes)
