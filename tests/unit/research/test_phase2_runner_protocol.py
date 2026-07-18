from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

import scripts.run_strategy_phase2 as runner
from core.research.phase2.registry import ExperimentRegistry, ExperimentSpec
from scripts.run_strategy_phase2 import (
    _development_qualified_families,
    _grids,
    _locked_or_current_commit,
    _neighbor_cells,
    _repair_grids,
)


def test_preregistered_grid_sizes_are_frozen() -> None:
    grids = _grids()
    assert {family: len(cells) for family, cells in grids.items()} == {
        "adaptive_core": 9,
        "controlled_growth": 12,
        "sector_rotation": 12,
        "etf_reversion": 8,
    }
    assert sum(map(len, grids.values())) == 41
    repair = _repair_grids()
    assert repair["sector_rotation_v2"] == [
        {"momentum_weights": [0.2, 0.3, 0.5], "top_n": 3, "slow_trend": 168}
    ]
    assert len(repair["risk_balanced_core"]) == 6
    assert len(repair["defensive_growth"]) == 6
    assert len(repair["multi_asset_trend"]) == 4
    assert len(repair["dual_index_growth"]) == 4
    assert len(repair["crash_buffer_core"]) == 4


def test_parameter_neighbors_change_exactly_one_axis() -> None:
    for family, cells in _grids().items():
        selected = cells[len(cells) // 2]
        neighbors = _neighbor_cells(family, selected)
        assert neighbors
        for neighbor in neighbors:
            assert sum(neighbor[key] != selected[key] for key in selected) == 1


def test_d2_manifest_validation_fail_closes_on_reference_drift(tmp_path, monkeypatch) -> None:
    root = tmp_path
    daily = root / "data/daily"
    ref = root / "data/ref"
    daily.mkdir(parents=True)
    ref.mkdir(parents=True)
    bar_path = daily / "SPY.parquet"
    pd.DataFrame({"close": [1.0]}).to_parquet(bar_path)
    reference_path = ref / "splits.parquet"
    pd.DataFrame({"value": [1]}).to_parquet(reference_path)
    manifest = {
        "schema_version": 1,
        "symbols": {
            "SPY": {"raw_parquet_sha256": hashlib.sha256(bar_path.read_bytes()).hexdigest()}
        },
        "reference_artifacts": {
            "splits.parquet": {
                "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                "rows": 1,
            }
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "DATA_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(runner, "_all_symbols", lambda: ["SPY"])
    runner._validate_data_manifest("d2")
    pd.DataFrame({"value": [2]}).to_parquet(reference_path)
    with pytest.raises(RuntimeError, match="reference data hash drift"):
        runner._validate_data_manifest("d2")


def test_execution_reuses_commit_locked_by_plan_only(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.json")
    spec = ExperimentSpec(
        experiment_id="P2-D2R2-DEV-ADAPTIVE-CORE-01",
        strategy_family="adaptive_core",
        strategy_version="v1",
        hypothesis="test",
        parameters={},
        data_range={"start": "2007-01-03", "end": "2016-12-30"},
        cost_model="test",
        benchmark="SPY",
        code_commit="a" * 40,
    )
    registry.preregister([spec])
    assert _locked_or_current_commit(registry, spec.experiment_id) == "a" * 40


def test_validation_excludes_development_failed_families() -> None:
    policy = runner.PromotionPolicy.load(runner.POLICY_PATH)
    passing = {
        "cagr": 0.08,
        "sharpe": 0.50,
        "sortino": 0.70,
        "max_drawdown": -0.10,
    }
    failing = {**passing, "sharpe": -0.10}
    selection = {
        "families": {
            "adaptive_core": {"metrics": passing},
            "controlled_growth": {"metrics": failing},
        }
    }
    assert set(_development_qualified_families(selection, policy)) == {"adaptive_core"}
