"""Tests for ``core.research.promotion.fingerprints`` (PRD #3 P3.5).

Discipline (per CLAUDE.md /loop protocol + unified PRD #3/#4 script):
- determinism across processes
- byte-for-byte backward-compat with the legacy
  ``scripts/promote_strategy.py::_compute_fingerprints`` (D6/P4-A2)
- drift detection: changing a yaml file changes the hash
- registry selection: production vs research yields distinct hashes
- universe selection: executable vs expanded yields distinct hashes
- extra_files extension: included files affect ``config_hash``
- schema purity: utility takes no panel / yfinance / bar_store deps
"""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest
import yaml

from core.research.promotion import fingerprints as fp


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_universe_hash_deterministic_same_inputs(self):
        h1 = fp.compute_universe_hash("executable")
        h2 = fp.compute_universe_hash("executable")
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_factor_registry_hash_deterministic(self):
        h1 = fp.compute_factor_registry_hash("production")
        h2 = fp.compute_factor_registry_hash("production")
        assert h1 == h2

    def test_config_hash_deterministic(self):
        h1 = fp.compute_config_hash()
        h2 = fp.compute_config_hash()
        assert h1 == h2

    def test_compute_fingerprints_returns_all_three(self):
        out = fp.compute_fingerprints()
        assert set(out.keys()) == {
            "universe", "universe_hash", "factor_registry_hash", "config_hash"
        }
        assert out["universe"] == "executable"
        assert all(len(out[k]) == 64 for k in
                   ("universe_hash", "factor_registry_hash", "config_hash"))


# ---------------------------------------------------------------------------
# Backward compat with legacy script (D6/P4-A2 byte-for-byte)
# ---------------------------------------------------------------------------


class TestBackwardCompatLegacyScript:
    def test_byte_for_byte_matches_legacy_promote_strategy_helper(self):
        """``compute_fingerprints("executable", "production")`` must match
        ``scripts/promote_strategy.py::_compute_fingerprints("executable")``
        byte-for-byte. Pre-existing promoted yamls must remain valid."""
        import importlib.util

        repo_root = Path(__file__).resolve().parents[4]
        legacy_path = repo_root / "scripts" / "promote_strategy.py"
        spec = importlib.util.spec_from_file_location("legacy_promote", legacy_path)
        assert spec is not None and spec.loader is not None
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)

        legacy_out = legacy._compute_fingerprints("executable")
        new_out = fp.compute_fingerprints(
            universe_name="executable", registry="production"
        )

        assert legacy_out["universe"] == new_out["universe"]
        assert legacy_out["universe_hash"] == new_out["universe_hash"]
        assert legacy_out["factor_registry_hash"] == new_out["factor_registry_hash"]
        assert legacy_out["config_hash"] == new_out["config_hash"]


# ---------------------------------------------------------------------------
# Universe selection
# ---------------------------------------------------------------------------


class TestUniverseSelection:
    def test_executable_vs_expanded_v2_distinct(self):
        h_exec = fp.compute_universe_hash("executable")
        h_exp = fp.compute_universe_hash("expanded_v2")
        assert h_exec != h_exp, "different universe yamls must yield different hashes"

    def test_unknown_universe_raises(self):
        with pytest.raises(ValueError, match="Unknown universe_name"):
            fp.compute_universe_hash("does_not_exist")


# ---------------------------------------------------------------------------
# Registry selection
# ---------------------------------------------------------------------------


class TestRegistrySelection:
    def test_production_vs_research_distinct(self):
        h_prod = fp.compute_factor_registry_hash("production")
        h_res = fp.compute_factor_registry_hash("research")
        assert h_prod != h_res, (
            "PRODUCTION_FACTORS and RESEARCH_FACTORS are different sets, "
            "they must yield different hashes"
        )

    def test_unknown_registry_raises(self):
        with pytest.raises(ValueError, match="Unknown registry"):
            fp.compute_factor_registry_hash("nonsense")


# ---------------------------------------------------------------------------
# Drift detection (with tmp repo)
# ---------------------------------------------------------------------------


class TestDriftDetection:
    def test_universe_hash_changes_when_yaml_changes(self, tmp_path: Path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        # baseline
        (cfg_dir / "universe.yaml").write_text(yaml.safe_dump({
            "seed_pool": ["SPY", "QQQ"],
            "sector_etfs": ["XLF"],
        }))
        h_before = fp.compute_universe_hash("executable", repo_root=tmp_path)
        # add a symbol
        (cfg_dir / "universe.yaml").write_text(yaml.safe_dump({
            "seed_pool": ["SPY", "QQQ", "GLD"],  # added GLD
            "sector_etfs": ["XLF"],
        }))
        h_after = fp.compute_universe_hash("executable", repo_root=tmp_path)
        assert h_before != h_after, "adding a symbol must change the hash"

    def test_config_hash_changes_when_yaml_changes(self, tmp_path: Path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        for fn in ("risk.yaml", "backtest.yaml", "cost_model.yaml"):
            (cfg_dir / fn).write_text("placeholder: 1\n")
        h_before = fp.compute_config_hash(repo_root=tmp_path)
        (cfg_dir / "risk.yaml").write_text("placeholder: 2\n")  # change content
        h_after = fp.compute_config_hash(repo_root=tmp_path)
        assert h_before != h_after, "editing risk.yaml must change config_hash"


# ---------------------------------------------------------------------------
# extra_files extension (for trigger-first canonical config in P3.6)
# ---------------------------------------------------------------------------


class TestExtraFilesExtension:
    def test_no_extra_files_equals_base_only(self, tmp_path: Path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        for fn in ("risk.yaml", "backtest.yaml", "cost_model.yaml"):
            (cfg_dir / fn).write_text(f"name: {fn}\n")
        h_none = fp.compute_config_hash(extra_files=None, repo_root=tmp_path)
        h_empty = fp.compute_config_hash(extra_files=[], repo_root=tmp_path)
        assert h_none == h_empty, "None and empty extra_files must produce same hash"

    def test_extra_file_changes_config_hash(self, tmp_path: Path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        for fn in ("risk.yaml", "backtest.yaml", "cost_model.yaml"):
            (cfg_dir / fn).write_text(f"name: {fn}\n")
        canonical_yaml = tmp_path / "canonical.yaml"
        canonical_yaml.write_text("canonical: v1\n")

        h_without = fp.compute_config_hash(repo_root=tmp_path)
        h_with = fp.compute_config_hash(
            extra_files=["canonical.yaml"], repo_root=tmp_path
        )
        assert h_without != h_with, (
            "adding an extra file to config_hash must change the hash"
        )

    def test_extra_file_drift_detected(self, tmp_path: Path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        for fn in ("risk.yaml", "backtest.yaml", "cost_model.yaml"):
            (cfg_dir / fn).write_text(f"name: {fn}\n")
        canonical = tmp_path / "canonical.yaml"

        canonical.write_text("canonical: v1\n")
        h_v1 = fp.compute_config_hash(
            extra_files=["canonical.yaml"], repo_root=tmp_path
        )
        canonical.write_text("canonical: v2\n")
        h_v2 = fp.compute_config_hash(
            extra_files=["canonical.yaml"], repo_root=tmp_path
        )
        assert h_v1 != h_v2, "drift in extra file must change config_hash"

    def test_extra_file_absolute_path_accepted(self, tmp_path: Path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        for fn in ("risk.yaml", "backtest.yaml", "cost_model.yaml"):
            (cfg_dir / fn).write_text(f"name: {fn}\n")
        canonical = tmp_path / "canonical.yaml"
        canonical.write_text("canonical: v1\n")
        h_abs = fp.compute_config_hash(
            extra_files=[str(canonical)], repo_root=tmp_path
        )
        h_rel = fp.compute_config_hash(
            extra_files=["canonical.yaml"], repo_root=tmp_path
        )
        assert h_abs == h_rel, "absolute and relative paths must resolve identically"


# ---------------------------------------------------------------------------
# Schema purity: utility has no panel / yfinance / bar_store deps
# ---------------------------------------------------------------------------


class TestSchemaPurity:
    def test_no_heavy_data_imports(self):
        """Ensure fingerprint utility stays a thin deterministic hasher —
        no data-pipeline imports (matches PRD #3 P3.5 thin-overlay scope)."""
        src = Path(fp.__file__).read_text()
        for bad in ("from core.data", "import yfinance", "from core.factors.bar_store",
                    "pandas", "numpy"):
            assert bad not in src, f"fingerprints.py must not import {bad!r}"
