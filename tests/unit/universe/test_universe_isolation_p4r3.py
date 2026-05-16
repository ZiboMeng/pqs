"""P4·R3 — universe isolation regression test (Gate P4-A3).

Per chart-structure ralph-loop execution PRD §8. D6 isolation contract:
introducing the resolver + the opt-in ``expanded_v1`` universe must
change NOTHING for the default ``executable`` path or for any existing
forward candidate. "P4-A3: forward manifest diff == empty" — proven
structurally below: the forward ``ConfigSnapshot.universe_hash`` is a
pure function of ``config/universe.yaml`` (hashed by exact filename),
so adding ``config/universe_expanded_v1.yaml`` cannot drift it.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.config.loader import load_config
from core.universe.universe_resolver import resolve_universe

_PROJ = Path(__file__).resolve().parents[3]
_CONFIG = _PROJ / "config"


def test_executable_resolution_bit_for_bit_pre_phase4():
    """The load-bearing D6 claim — re-asserted in the isolation suite."""
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
    assert len(resolve_universe("executable")) == 79


def test_expanded_v1_is_strictly_additive():
    """expanded_v1 ADDS symbols; it never removes one from executable."""
    exe = resolve_universe("executable")
    exp = resolve_universe("expanded_v1")
    assert set(exe).issubset(set(exp))           # nothing dropped
    assert len(exp) > len(exe)                   # something added
    assert len(exp) == len(set(exp))             # no dupes
    # the executable members keep their exact order at the front
    assert exp[:len(exe)] == exe


def test_forward_universe_hash_excludes_expanded_yaml():
    """P4-A3: the forward ConfigSnapshot.universe_hash is computed from
    config/universe.yaml ONLY. Adding universe_expanded_v1.yaml cannot
    produce a config-drift event on any forward candidate."""
    from core.research.forward.runner import (
        _build_config_snapshot,
        _canonical_yaml_sha,
    )
    snap = _build_config_snapshot(config_dir=_CONFIG)
    assert snap.universe_hash == _canonical_yaml_sha(_CONFIG / "universe.yaml")
    # the snapshot's universe source is universe.yaml, not the expanded yaml
    assert snap.sources["universe_hash"].endswith("universe.yaml")
    assert "expanded" not in snap.sources["universe_hash"]


def test_expanded_yaml_well_formed():
    """expanded_v1 yaml carries an `expanded_symbols` list, all of which
    are absent from the executable 79 (genuinely additive)."""
    doc = yaml.safe_load((_CONFIG / "universe_expanded_v1.yaml").read_text())
    extra = doc["expanded_symbols"]
    assert len(extra) == len(set(extra)) >= 200
    exe = set(resolve_universe("executable"))
    assert not (set(extra) & exe)  # expanded symbols are all new


def test_resolver_has_zero_forward_path_coupling():
    """The resolver is not imported anywhere under core/research/forward —
    it cannot affect the forward observation pipeline."""
    fwd = _PROJ / "core" / "research" / "forward"
    offenders = [
        p.name for p in fwd.glob("*.py")
        if "universe_resolver" in p.read_text()
    ]
    assert offenders == [], f"resolver leaked into forward path: {offenders}"
