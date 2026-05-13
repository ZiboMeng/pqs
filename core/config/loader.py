"""
Config loader: reads all YAML files, merges overrides, validates via pydantic v2.

Usage:
    from core.config.loader import load_config
    cfg = load_config()               # loads from default config/ directory
    cfg = load_config(overrides={...}) # apply runtime overrides

CLI validation:
    python -m core.config.loader --validate
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

from core.config.schemas import (
    AcceptanceThresholds,
    BacktestConfig,
    CostModelConfig,
    RegimeConfig,
    ReportingConfig,
    RiskConfig,
    SystemConfig,
    UniverseConfig,
)

# ── Project root detection ────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback: use current working directory
    return Path.cwd()


PROJECT_ROOT: Path = _find_project_root()


# ── YAML helpers ─────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file; return empty dict if file does not exist."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Recursively merge `override` into `base`.
    - Dicts are merged recursively.
    - All other types: override wins.
    Returns a new dict (does not mutate inputs).
    """
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


# ── Per-section loaders ───────────────────────────────────────────────────────

def _load_section(config_dir: Path, filename: str) -> Dict[str, Any]:
    return _load_yaml(config_dir / filename)


# ── PQSConfig: the unified validated config object ───────────────────────────

class PQSConfig:
    """
    Single object that holds all validated configuration sections.

    Attributes are pydantic models; access like:
        cfg.system.account.initial_capital_usd
        cfg.risk.budget.core
        cfg.cost_model.get_total_cost_bps("SPY", "interday", 18.0)
    """

    def __init__(
        self,
        system: SystemConfig,
        universe: UniverseConfig,
        cost_model: CostModelConfig,
        risk: RiskConfig,
        regime: RegimeConfig,
        backtest: BacktestConfig,
        reporting: ReportingConfig,
        acceptance: AcceptanceThresholds,
        _raw: Dict[str, Any],
    ):
        self.system = system
        self.universe = universe
        self.cost_model = cost_model
        self.risk = risk
        self.regime = regime
        self.backtest = backtest
        self.reporting = reporting
        self.acceptance = acceptance
        self._raw = _raw  # unvalidated merged dict, useful for debugging

    def __repr__(self) -> str:
        return (
            f"PQSConfig(env={self.system.env!r}, "
            f"capital={self.system.account.initial_capital_usd:,.0f} USD, "
            f"universe_size={len(self.universe.seed_pool)})"
        )


# ── Multi-universe helper (C10-2-B per research multi-universe architecture) ─


def load_alternate_universe(path: Path) -> Dict[str, Any]:
    """Load a non-default universe yaml file as a dict (for use with
    ``load_config(overrides={"universe": ...})`` or
    ``forward.runner.init(universe_yaml_override=...)``).

    Per memory `feedback_multi_universe_research_default`, research-stage
    multi-universe coexistence is the default architecture: each candidate
    spec / mining cycle can lock its own universe via path. The main
    ``config/universe.yaml`` is preserved as the "default / legacy"
    universe that Trial 9 v2 + RCMv1 + Cand-2 forward manifests lock.

    Args:
        path: Path to alternate universe yaml file. Must exist.

    Returns:
        Parsed universe dict (untyped).

    Raises:
        FileNotFoundError: if path does not exist.
    """
    import yaml

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Alternate universe yaml not found: {path}")
    return yaml.safe_load(path.read_text())


# ── Main loader ───────────────────────────────────────────────────────────────

def load_config(
    config_dir: Optional[Path] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> PQSConfig:
    """
    Load, merge, and validate all configuration.

    Args:
        config_dir: path to config/ directory. Defaults to PROJECT_ROOT/config.
        overrides:  dict of overrides to deep-merge on top of file-based config.
                    Keys are section names: 'system', 'universe', 'risk', etc.

    Returns:
        PQSConfig with all sections validated.

    Raises:
        pydantic.ValidationError: if any section fails schema validation.
        FileNotFoundError: if config_dir does not exist.
    """
    if config_dir is None:
        config_dir = PROJECT_ROOT / "config"

    config_dir = Path(config_dir)
    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")

    # Load each section YAML
    raw: Dict[str, Any] = {}
    section_files = {
        "system":     "system.yaml",
        "universe":   "universe.yaml",
        "cost_model": "cost_model.yaml",
        "risk":       "risk.yaml",
        "regime":     "regime.yaml",
        "backtest":   "backtest.yaml",
        "reporting":  "reporting.yaml",
        "acceptance": "acceptance.yaml",
    }
    for section, filename in section_files.items():
        raw[section] = _load_section(config_dir, filename)

    # Apply runtime overrides
    if overrides:
        for section, override_val in overrides.items():
            if section in raw and isinstance(override_val, dict):
                raw[section] = _deep_merge(raw[section], override_val)
            else:
                raw[section] = override_val

    # Apply environment variable overrides
    _apply_env_overrides(raw)

    # Validate each section via pydantic
    errors: Dict[str, str] = {}

    def _validate(section: str, model_cls, data: Dict):
        try:
            return model_cls(**data)
        except ValidationError as exc:
            errors[section] = str(exc)
            return None

    system    = _validate("system",     SystemConfig,    raw.get("system", {}))
    universe  = _validate("universe",   UniverseConfig,  raw.get("universe", {}))
    cost_model= _validate("cost_model", CostModelConfig, raw.get("cost_model", {}))
    risk      = _validate("risk",       RiskConfig,      raw.get("risk", {}))
    regime    = _validate("regime",     RegimeConfig,    raw.get("regime", {}))
    backtest  = _validate("backtest",   BacktestConfig,  raw.get("backtest", {}))
    reporting = _validate("reporting",  ReportingConfig, raw.get("reporting", {}))
    acceptance = _validate("acceptance", AcceptanceThresholds, raw.get("acceptance", {}))

    if errors:
        msg = "\n".join(f"  [{section}] {err}" for section, err in errors.items())
        raise ValueError(f"Configuration validation failed:\n{msg}")

    return PQSConfig(
        system=system,
        universe=universe,
        cost_model=cost_model,
        risk=risk,
        regime=regime,
        backtest=backtest,
        reporting=reporting,
        acceptance=acceptance,
        _raw=raw,
    )


def _apply_env_overrides(raw: Dict[str, Any]) -> None:
    """Apply PQS_* environment variable overrides."""
    env_map = {
        "PQS_ENV":       ("system", "env"),
        "PQS_LOG_LEVEL": ("system", "logging", "level"),
        "PQS_DATA_DIR":  ("system", "paths", "data_dir"),
    }
    for env_var, path in env_map.items():
        val = os.environ.get(env_var)
        if val is not None:
            _set_nested(raw, path, val)


def _set_nested(d: Dict, path: tuple, value: Any) -> None:
    """Set a value in a nested dict using a tuple path."""
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    parser = argparse.ArgumentParser(description="PQS config loader")
    parser.add_argument("--validate", action="store_true", help="Validate all config files")
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--show", type=str, default=None,
                        help="Show a specific section: system|universe|cost_model|risk|regime|backtest|reporting")
    args = parser.parse_args()

    try:
        cfg = load_config(config_dir=args.config_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)

    if args.show:
        section = getattr(cfg, args.show, None)
        if section is None:
            print(f"[FAIL] Unknown section: {args.show}", file=sys.stderr)
            sys.exit(1)
        import json
        print(json.dumps(section.model_dump(), indent=2, default=str))
        return

    print(f"[OK] Config loaded and validated: {cfg}")
    print(f"     Seed pool : {cfg.universe.seed_pool}")
    print(f"     Blacklist : {cfg.universe.blacklist}")
    print(f"     Capital   : ${cfg.system.account.initial_capital_usd:,.0f}")
    print(f"     Env       : {cfg.system.env}")
    print(f"     Budget    : core={cfg.risk.budget.core:.0%} "
          f"tactical={cfg.risk.budget.tactical:.0%} "
          f"enhancer={cfg.risk.budget.enhancer:.0%} "
          f"min_cash={cfg.risk.budget.min_cash:.0%}")


if __name__ == "__main__":
    _cli()
