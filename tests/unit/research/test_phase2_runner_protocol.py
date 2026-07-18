from __future__ import annotations

from scripts.run_strategy_phase2 import _grids, _neighbor_cells


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
