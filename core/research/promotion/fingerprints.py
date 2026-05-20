"""Deterministic repo-state fingerprints for production promotion (PRD #3 P3.5).

Three hashes capture the structural state of the repo at promotion time:

- ``universe_hash``  — sha256 of the sorted-unique tradable symbol list from
  the chosen universe yaml (``config/universe*.yaml``). Detects drift if
  symbols are added/removed/renamed.
- ``factor_registry_hash`` — sha256 of the sorted factor-name list from
  ``core.factors.factor_registry`` (``PRODUCTION_FACTORS`` for the MFS
  path; ``RESEARCH_FACTORS`` for the trigger-first canonical path that
  consumes the wider research panel).
- ``config_hash`` — sha256 of the concatenated file hashes of
  ``risk.yaml`` / ``backtest.yaml`` / ``cost_model.yaml`` (plus any
  ``extra_files`` such as the trigger-first canonical config).

Properties:
- Pure function of inputs (universe yaml content + registry frozenset +
  config files on disk). No side effects.
- Deterministic across processes — re-running with identical repo state
  yields byte-identical hashes.
- Backward-compatible with ``scripts/promote_strategy.py::_compute_fingerprints``
  when called as ``compute_fingerprints(universe_name="executable",
  registry="production")``; the MFS promote path is byte-for-byte preserved.

Drift detection: ``M3`` alignment-check at runtime hashes the live repo
state and compares against the ``fingerprints`` section of the active
``config/production_strategy.yaml``. Mismatch → WARN (or hard-fail in
``strict_match`` mode).

PRD: docs/prd/20260520-prd_trigger_first_canonical_promotion.md §P3.5
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Literal

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[3]

# Universe yaml names by symbolic id (kept aligned with
# scripts/promote_strategy.py --universe choices for byte-for-byte parity).
_UNIVERSE_YAML_BY_NAME = {
    "executable": "universe.yaml",
    "expanded_v1": "universe_expanded_v1.yaml",
    "expanded_v2": "universe_expanded_v2.yaml",
}

# Universe yaml sections aggregated into the tradable-symbol set
# (matches the convention in scripts/promote_strategy.py).
_UNIVERSE_TRADABLE_SECTIONS = ("seed_pool", "sector_etfs", "factor_etfs", "cross_asset")

# Config files baked into config_hash (legacy MFS-promote contract).
_BASE_CONFIG_FILES = ("risk.yaml", "backtest.yaml", "cost_model.yaml")

RegistryName = Literal["production", "research"]


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_root(repo_root: Path | None = None) -> Path:
    return Path(repo_root) if repo_root is not None else _REPO_ROOT


def compute_universe_hash(
    universe_name: str = "executable",
    *,
    repo_root: Path | None = None,
) -> str:
    """Hash the sorted-unique tradable symbol list for ``universe_name``.

    Byte-for-byte compatible with the legacy ``_compute_fingerprints``
    helper in ``scripts/promote_strategy.py`` when called with
    ``universe_name="executable"`` (D6/P4-A2 invariant).
    """
    if universe_name not in _UNIVERSE_YAML_BY_NAME:
        raise ValueError(
            f"Unknown universe_name={universe_name!r}; "
            f"valid: {sorted(_UNIVERSE_YAML_BY_NAME)}"
        )
    yaml_path = _repo_root(repo_root) / "config" / _UNIVERSE_YAML_BY_NAME[universe_name]
    uni_yaml = yaml.safe_load(yaml_path.read_text())
    tradable: list[str] = []
    for key in _UNIVERSE_TRADABLE_SECTIONS:
        v = uni_yaml.get(key, [])
        if isinstance(v, list):
            tradable.extend(v)
    return _sha256_str("|".join(sorted(set(tradable))))


def compute_factor_registry_hash(registry: RegistryName = "production") -> str:
    """Hash the sorted factor-name list from ``core.factors.factor_registry``.

    Args:
        registry: ``"production"`` → ``PRODUCTION_FACTORS`` (MFS / legacy
            promote); ``"research"`` → ``RESEARCH_FACTORS`` (trigger-first
            canonical consuming the wider research panel).
    """
    from core.factors.factor_registry import PRODUCTION_FACTORS, RESEARCH_FACTORS
    if registry == "production":
        names = sorted(PRODUCTION_FACTORS)
    elif registry == "research":
        names = sorted(RESEARCH_FACTORS)
    else:
        raise ValueError(
            f"Unknown registry={registry!r}; valid: 'production' | 'research'"
        )
    return _sha256_str("|".join(names))


def compute_config_hash(
    extra_files: Iterable[str | Path] | None = None,
    *,
    repo_root: Path | None = None,
) -> str:
    """Hash the concatenation of ``risk.yaml`` / ``backtest.yaml`` /
    ``cost_model.yaml`` file hashes (plus optional ``extra_files``).

    ``extra_files`` lets the trigger-first canonical promote path bake
    the canonical config yaml into the fingerprint without disturbing
    the MFS legacy path (empty extra → byte-for-byte identical to
    legacy ``_compute_fingerprints`` config_hash).
    """
    root = _repo_root(repo_root)
    parts: list[str] = []
    for fn in _BASE_CONFIG_FILES:
        parts.append(_sha256_file(root / "config" / fn))
    if extra_files:
        for ef in extra_files:
            ef_path = Path(ef)
            if not ef_path.is_absolute():
                ef_path = root / ef_path
            parts.append(_sha256_file(ef_path))
    return _sha256_str("|".join(parts))


def compute_fingerprints(
    universe_name: str = "executable",
    registry: RegistryName = "production",
    extra_files: Iterable[str | Path] | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Compute all three fingerprints in one call.

    Output schema matches ``scripts/promote_strategy.py::_compute_fingerprints``:

        {
          "universe": universe_name,
          "universe_hash": str,
          "factor_registry_hash": str,
          "config_hash": str,
        }

    With defaults (``universe_name="executable"``, ``registry="production"``,
    ``extra_files=None``), all three hashes are byte-for-byte identical to
    the legacy helper (D6/P4-A2 invariant — every pre-existing MFS promote
    produces the same fingerprints).
    """
    return {
        "universe": universe_name,
        "universe_hash": compute_universe_hash(universe_name, repo_root=repo_root),
        "factor_registry_hash": compute_factor_registry_hash(registry),
        "config_hash": compute_config_hash(extra_files, repo_root=repo_root),
    }
