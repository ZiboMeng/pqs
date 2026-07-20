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
    # expanded_v2 added by supplementary PRD R-P4ext (data-driven ~1k);
    # executable + expanded_v1 contract unchanged (additive, D6/P4-A2).
    assert UNIVERSE_NAMES == ("executable", "expanded_v1", "expanded_v2")


# ── audit 20260708 P0-1: blacklist must NOT be bypassable via expanded_* ──
_INVERSE_BLACKLISTED = {
    "DUST", "JDST", "LABD", "QID", "SCO", "SDOW", "SDS", "SH",
    "SOXS", "SPXS", "SPXU", "SQQQ", "SVXY", "TBT", "TZA",
}

_LEVERAGED_LONGS_IN_V2 = {
    "ERX", "FAS", "GUSH", "JNUG", "LABU", "NUGT", "QLD", "SOXL",
    "SPXL", "SSO", "TECL", "TNA", "TQQQ", "UCO", "UDOW", "UPRO",
}


@pytest.mark.parametrize("name", ["expanded_v1", "expanded_v2"])
def test_expanded_universe_never_leaks_blacklisted(name):
    """Regression: expanded_v1/v2 additions used to bypass the blacklist, so
    SQQQ (−3x inverse, permanently blacklisted) leaked into a tradable set.
    The resolver now filters the expanded additions through the same
    exclusion set as the base."""
    yaml_name = f"universe_{name}.yaml"
    if not (_CONFIG / yaml_name).exists():
        pytest.skip(f"{yaml_name} not built")
    syms = set(resolve_universe(name))
    uni = load_config(_CONFIG).universe
    leaked = (set(uni.blacklist) | _INVERSE_BLACKLISTED) & syms
    assert not leaked, f"{name} leaked blacklisted symbols: {sorted(leaked)}"


def test_expanded_keeps_leveraged_long_not_blacklisted():
    """Sanity: the fix drops INVERSE ETFs (short-equivalent) but must NOT drop
    leveraged-LONG ETFs (TQQQ/SOXL/SPXL/UPRO) — those are allowed under
    stricter risk caps, not blacklisted."""
    if not (_CONFIG / "universe_expanded_v2.yaml").exists():
        pytest.skip("expanded_v2 not built")
    doc = yaml.safe_load((_CONFIG / "universe_expanded_v2.yaml").read_text()) or {}
    listed = set(doc.get("symbols", []))
    syms = set(resolve_universe("expanded_v2"))
    cfg = load_config(_CONFIG)
    risk_doc = yaml.safe_load((_CONFIG / "risk.yaml").read_text())
    symbol_caps = risk_doc["position_limits"]["symbol_caps"]
    for lev in _LEVERAGED_LONGS_IN_V2 & listed:
        assert lev in syms, f"leveraged-long {lev} was wrongly dropped"
        assert lev in cfg.universe.high_risk_symbols.symbols
        assert float(symbol_caps[lev]) <= 0.10
