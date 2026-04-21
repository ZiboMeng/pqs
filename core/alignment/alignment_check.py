"""Runtime alignment check between production strategy artifact and
current repo state (PRD M3).

On every `run_backtest.py` / `run_paper.py` / `run_multi_tf_backtest.py`
startup, this module compares `config/production_strategy.yaml::fingerprints`
against hashes recomputed from current repo state.

Lifecycle:
- Phase 1 (current): WARN-only. Mismatch logged + written to artifact, but
  no entrypoint is blocked. Gives the team observability without brittleness.
- Phase 2 (future): FAIL mode. `run_paper.py --mode live` refuses to start
  on mismatch unless `--ignore-alignment-check`. backtest/research unaffected.

Mode switch: `config/system.yaml::alignment::mode = warn | fail` (future).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.logging_setup import get_logger

logger = get_logger(__name__)


class AlignmentMode(str, Enum):
    WARN = "warn"
    FAIL = "fail"


class AlignmentCheckError(RuntimeError):
    """Raised in FAIL mode when fingerprints don't match."""


@dataclass
class AlignmentReport:
    timestamp: str
    mode: AlignmentMode
    production_status: str
    production_strategy_exists: bool
    checks: Dict[str, Dict[str, Any]]  # name -> {match, expected, actual, severity}
    all_match: bool
    ignored: bool = False
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d

    def summary_line(self) -> str:
        if self.all_match:
            return f"Alignment: all OK ({self.mode.value} mode, status={self.production_status})"
        n_mismatch = sum(1 for c in self.checks.values() if not c.get("match"))
        return (
            f"Alignment: {n_mismatch}/{len(self.checks)} mismatches "
            f"({self.mode.value} mode, status={self.production_status})"
        )


# ---------------------------------------------------------------------------
# Hash computation helpers
# ---------------------------------------------------------------------------


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_universe_hash(root: Path) -> str:
    """Hash = sorted concat of tradable symbols across 4 universe sections."""
    uni_yaml = yaml.safe_load((root / "config" / "universe.yaml").read_text())
    tradable: List[str] = []
    for key in ("seed_pool", "sector_etfs", "factor_etfs", "cross_asset"):
        v = uni_yaml.get(key, [])
        if isinstance(v, list):
            tradable.extend(v)
    return _sha256_str("|".join(sorted(set(tradable))))


def compute_factor_registry_hash() -> str:
    from core.factors.factor_registry import PRODUCTION_FACTORS
    return _sha256_str("|".join(sorted(PRODUCTION_FACTORS)))


def compute_config_hash(root: Path) -> str:
    """Hash = concat of risk + backtest + cost_model YAML hashes."""
    parts = []
    for fn in ("risk.yaml", "backtest.yaml", "cost_model.yaml"):
        p = root / "config" / fn
        if p.exists():
            parts.append(_sha256_file(p))
    return _sha256_str("|".join(parts))


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------


def check_alignment(
    root: Path,
    mode: AlignmentMode = AlignmentMode.WARN,
    ignore: bool = False,
) -> AlignmentReport:
    """Compare production_strategy.yaml fingerprints against current state.

    Args:
        root: repo root path
        mode: WARN (log-only) or FAIL (raise AlignmentCheckError on mismatch)
        ignore: if True, short-circuit to a pass report (for --ignore-alignment-check)
    """
    from core.config.production_strategy import (
        DEFAULT_CONFIG_PATH, load_production_strategy, ProductionStrategyError,
    )

    ts = datetime.now(timezone.utc).isoformat()
    warnings_list: List[str] = []
    errors_list: List[str] = []

    if ignore:
        return AlignmentReport(
            timestamp=ts,
            mode=mode,
            production_status="(ignored)",
            production_strategy_exists=False,
            checks={},
            all_match=True,
            ignored=True,
            warnings=["Alignment check explicitly ignored via --ignore-alignment-check"],
        )

    # Load production strategy
    try:
        ps_cfg = load_production_strategy(root / DEFAULT_CONFIG_PATH)
        exists = True
    except ProductionStrategyError as exc:
        warnings_list.append(f"Cannot load production_strategy.yaml: {exc}")
        return AlignmentReport(
            timestamp=ts,
            mode=mode,
            production_status="(missing)",
            production_strategy_exists=False,
            checks={},
            all_match=False,
            warnings=warnings_list,
        )

    # For conservative_default / no_validated_best: fingerprints are expected
    # to be empty. We still compute current hashes for logging, but don't
    # count "empty expected vs filled actual" as a mismatch.
    is_provisional = ps_cfg.status != "active"

    expected = {
        "universe_hash": ps_cfg.fingerprints.universe_hash,
        "factor_registry_hash": ps_cfg.fingerprints.factor_registry_hash,
        "config_hash": ps_cfg.fingerprints.config_hash,
    }
    actual = {
        "universe_hash": compute_universe_hash(root),
        "factor_registry_hash": compute_factor_registry_hash(),
        "config_hash": compute_config_hash(root),
    }

    checks: Dict[str, Dict[str, Any]] = {}
    for name in ("universe_hash", "factor_registry_hash", "config_hash"):
        exp, act = expected[name], actual[name]
        if not exp:
            checks[name] = {
                "match": True,
                "expected": "(empty)",
                "actual": act[:12] + "...",
                "severity": "info",
                "note": f"fingerprint not recorded (status={ps_cfg.status}); tracking-only",
            }
        else:
            match = (exp == act)
            checks[name] = {
                "match": match,
                "expected": exp[:12] + "...",
                "actual": act[:12] + "...",
                "severity": "ok" if match else "mismatch",
            }
            if not match:
                msg = (
                    f"Alignment mismatch: {name} expected={exp[:12]}... "
                    f"actual={act[:12]}..."
                )
                if mode == AlignmentMode.FAIL:
                    errors_list.append(msg)
                else:
                    warnings_list.append(msg)

    all_match = all(c["match"] for c in checks.values())

    report = AlignmentReport(
        timestamp=ts,
        mode=mode,
        production_status=ps_cfg.status,
        production_strategy_exists=exists,
        checks=checks,
        all_match=all_match,
        warnings=warnings_list,
        errors=errors_list,
    )

    # Log outcome
    if all_match:
        if is_provisional:
            logger.info(
                "Alignment: status=%s — fingerprints not recorded (expected); "
                "current hashes logged to artifact",
                ps_cfg.status,
            )
        else:
            logger.info("Alignment: all fingerprints match (status=active)")
    else:
        for w in warnings_list:
            logger.warning(w)
        for e in errors_list:
            logger.error(e)
        if mode == AlignmentMode.FAIL and errors_list:
            raise AlignmentCheckError(
                f"Alignment check failed ({len(errors_list)} error(s)); "
                f"use --ignore-alignment-check to override."
            )

    return report


def write_alignment_report(
    report: AlignmentReport,
    out_dir: str | Path = "data/paper_trading",
) -> Path:
    """Write alignment report to JSON (timestamped)."""
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    ts_safe = report.timestamp.replace(":", "-").replace("+", "Z")
    out = p / f"alignment_{ts_safe}.json"
    out.write_text(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return out
