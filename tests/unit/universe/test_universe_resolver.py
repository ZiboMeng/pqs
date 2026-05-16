"""Unit tests for core/universe/universe_resolver.py — P4·R1.

Per ralph-loop execution PRD §8. Gate P4-A1 (resolver) + P4-A2
(bit-for-bit: `executable` reproduces the pre-Phase-4 79-symbol set).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.config.loader import load_config
from core.universe.universe_resolver import UNIVERSE_NAMES, resolve_universe

_PROJ = Path(__file__).resolve().parents[3]
_CONFIG = _PROJ / "config"


def test_resolve_executable_is_79():
    syms = resolve_universe("executable")
    assert len(syms) == 79
    assert "SPY" in syms and "QQQ" in syms
    assert len(set(syms)) == 79  # no dupes


def test_resolve_executable_matches_canonical_yaml():
    """`executable` set == the canonical config/executable_universe.yaml list."""
    syms = set(resolve_universe("executable"))
    doc = yaml.safe_load((_CONFIG / "executable_universe.yaml").read_text())
    assert syms == set(doc["executable_universe"])


def test_resolve_executable_bit_for_bit_pre_phase4_construction():
    """D6 / P4-A2: `executable` reproduces the pre-Phase-4 inline universe
    construction EXACTLY (same symbols, same order) — so routing existing
    chart-structure code through the resolver is a no-op for the default."""
    cfg = load_config(_CONFIG)
    uni = cfg.universe
    base = list(dict.fromkeys(
        list(uni.seed_pool) + list(uni.sector_etfs)
        + list(uni.factor_etfs) + list(uni.cross_asset)
    ))
    drop = {"BRK-B", "USO", "SLV"}
    expected = [s for s in base if s not in uni.blacklist
                and s not in uni.macro_reference and s not in drop]
    for b in ("SPY", "QQQ"):
        if b not in expected:
            expected.append(b)
    assert resolve_universe("executable") == expected  # order-exact


def test_resolve_expanded_v1_raises_before_built():
    """expanded_v1 raises a clean FileNotFoundError until P4·R2 builds the yaml."""
    if (_CONFIG / "universe_expanded_v1.yaml").exists():
        pytest.skip("expanded_v1 yaml already built")
    with pytest.raises(FileNotFoundError, match="expanded_v1"):
        resolve_universe("expanded_v1")


def test_resolve_unknown_name_raises():
    with pytest.raises(ValueError, match="unknown universe"):
        resolve_universe("nonsense")


def test_universe_names_constant():
    assert UNIVERSE_NAMES == ("executable", "expanded_v1")
