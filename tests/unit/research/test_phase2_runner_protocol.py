from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

import scripts.run_strategy_phase2 as runner
from core.research.phase2.registry import ExperimentRegistry, ExperimentSpec
from scripts.run_strategy_phase2 import _grids, _locked_or_current_commit, _neighbor_cells


def test_preregistered_grid_sizes_are_frozen() -> None:
    grids = _grids()
    assert {family: len(cells) for family, cells in grids.items()} == {
        "adaptive_core": 9,
        "controlled_growth": 12,
        "sector_rotation": 12,
        "etf_reversion": 8,
    }
    assert sum(map(len, grids.values())) == 41


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
