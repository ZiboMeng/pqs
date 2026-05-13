"""Unit tests for C10-2-B multi-universe loader support.

Per `docs/memos/20260513-cycle10_construction_axis_design.md` extension to
support multi-universe coexistence per memory
`feedback_multi_universe_research_default`.

Tests:
1. load_alternate_universe loads a valid yaml file as dict
2. load_alternate_universe raises FileNotFoundError on missing path
3. load_config + overrides={universe: alt_dict} produces config with alt universe
4. forward._build_config_snapshot with universe_yaml_override produces snapshot
   pointing at override path and hashing it
5. _build_config_snapshot default (no override) preserves legacy behavior
6. observe() / recover() read manifest's recorded universe path
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytest.importorskip("xgboost")  # transitive deps

from core.config.loader import load_alternate_universe, load_config


def test_load_alternate_universe_returns_dict(tmp_path: Path):
    alt_yaml = tmp_path / "universe_alt.yaml"
    alt_yaml.write_text("seed_pool:\n  - AAPL\n  - MSFT\n")
    out = load_alternate_universe(alt_yaml)
    assert isinstance(out, dict)
    assert out["seed_pool"] == ["AAPL", "MSFT"]


def test_load_alternate_universe_raises_on_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Alternate universe yaml not found"):
        load_alternate_universe(tmp_path / "does_not_exist.yaml")


def test_load_config_with_universe_override_via_overrides(tmp_path: Path):
    """Use load_alternate_universe + load_config(overrides=...) to swap universe."""
    # Create minimal alt universe
    alt_yaml = tmp_path / "universe_v2_test.yaml"
    alt_yaml.write_text(
        "seed_pool:\n"
        "  - AAPL\n"
        "  - MSFT\n"
        "blacklist: []\n"
        "macro_reference: []\n"
        "sector_etfs: []\n"
        "factor_etfs: []\n"
        "cross_asset: []\n"
    )
    alt_universe = load_alternate_universe(alt_yaml)
    # Load real PQS config with override (uses real config tree for other sections)
    cfg = load_config(overrides={"universe": alt_universe})
    assert "AAPL" in cfg.universe.seed_pool
    assert "MSFT" in cfg.universe.seed_pool
    # Should NOT contain other names that are in main universe.yaml
    assert "NVDA" not in cfg.universe.seed_pool


# ── _build_config_snapshot universe override ─────────────────────────────


def test_build_config_snapshot_with_override(tmp_path: Path):
    """When universe_yaml_override is provided, snapshot hashes that file
    + records the path in sources."""
    from core.research.forward.runner import _build_config_snapshot

    # Use real config tree for other yamls
    real_config = Path("config")
    # Create alt universe yaml
    alt_yaml = tmp_path / "universe_v2_for_test.yaml"
    alt_yaml.write_text("seed_pool:\n  - AAPL\nblacklist: []\nmacro_reference: []\n"
                        "sector_etfs: []\nfactor_etfs: []\ncross_asset: []\n")

    # With override
    snapshot_with = _build_config_snapshot(real_config, universe_yaml_override=alt_yaml)
    assert snapshot_with.sources["universe_hash"] == str(alt_yaml)

    # Without override (legacy)
    snapshot_default = _build_config_snapshot(real_config)
    assert snapshot_default.sources["universe_hash"] == "config/universe.yaml"

    # Hashes differ (different file contents)
    assert snapshot_with.universe_hash != snapshot_default.universe_hash


def test_build_config_snapshot_override_missing_raises(tmp_path: Path):
    """If override path doesn't exist, raises FileNotFoundError."""
    from core.research.forward.runner import _build_config_snapshot

    with pytest.raises(FileNotFoundError, match="universe_yaml_override path does not exist"):
        _build_config_snapshot(
            Path("config"),
            universe_yaml_override=tmp_path / "missing.yaml",
        )


def test_build_config_snapshot_default_unchanged(tmp_path: Path):
    """Default behavior (no override) produces same snapshot as before C10-2-B —
    Trial 9 v2 / RCMv1 / Cand-2 manifests unaffected."""
    from core.research.forward.runner import _build_config_snapshot

    snapshot = _build_config_snapshot(Path("config"))
    # sources should be exactly _F_CONFIG_SOURCES
    from core.research.forward.runner import _F_CONFIG_SOURCES
    assert snapshot.sources == dict(_F_CONFIG_SOURCES)
    # universe_hash should match config/universe.yaml hash
    from core.research.forward.runner import _canonical_yaml_sha
    expected_hash = _canonical_yaml_sha(Path("config/universe.yaml"))
    assert snapshot.universe_hash == expected_hash
