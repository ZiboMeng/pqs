#!/usr/bin/env python3
"""Build or verify the governance-bound Phase 3 observation artifact."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.research.governance import resolve_strategy_governance  # noqa: E402
from core.runtime.strategy_artifact import (  # noqa: E402
    StrategyArtifactError,
    build_strategy_artifact,
    current_environment,
    verify_strategy_artifact,
    write_strategy_artifact,
)

STRATEGY_ID = "dual_index_growth_v1"
ARTIFACT_PATH = Path(
    "research/registries/strategy_artifacts/dual_index_growth_v1/observation_v1.json"
)
COMPONENT_PATHS = {
    "strategy": ["core/signals/strategies/phase2_etf.py"],
    "configuration": [
        "config/strategies.paper.yaml",
        "config/portfolio.paper.yaml",
    ],
    "feature_regime": [
        "config/regime.paper.yaml",
        "config/regime.yaml",
        "core/regime/phase2_regime.py",
        "core/regime/regime_detector.py",
    ],
    "allocator": ["core/portfolio/strategy_allocator.py"],
    "risk": [
        "config/risk.yaml",
        "core/risk/kill_switch.py",
        "core/trading/controls.py",
        "core/trading/risk.py",
    ],
    "cost_execution": [
        "config/cost_model.yaml",
        "core/execution/cost_model.py",
        "core/execution/execution_simulator.py",
    ],
    "data_contract": [
        "core/data/price_access.py",
        "core/data/price_basis.py",
        "core/data/source_boundaries.py",
        "core/data/vix_loader.py",
    ],
    "runtime": [
        "core/paper_trading/paper_trading_engine.py",
        "core/paper_trading/phase2_runtime.py",
        "core/runtime/strategy_artifact.py",
        "core/trading/order.py",
        "core/trading/reconciliation.py",
        "core/trading/service.py",
        "core/trading/store.py",
        "scripts/run_phase2_paper.py",
    ],
    "governance": [
        "config/research_governance.yaml",
        "core/research/governance.py",
    ],
    "dependency": ["pyproject.toml", "requirements.txt"],
}
EVIDENCE_PATHS = [
    "research/results/phase2/development/selection_d2r5.json",
    "research/results/phase2/validation/summary_d2r5.json",
    "research/results/phase2/holdout/summary_d2r5.json",
    "research/results/phase2/paper/operational_acceptance.json",
    "research/registry/promotion_registry.json",
]
ENVIRONMENT_PACKAGES = ["numpy", "pandas", "pydantic", "PyYAML", "scipy"]


def _yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StrategyArtifactError(f"configuration must be a mapping: {path}")
    return payload


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _inputs() -> tuple[dict[str, Any], dict[str, Any], str]:
    strategy_config = _yaml(ROOT / "config/strategies.paper.yaml")
    registry = json.loads(
        (ROOT / "research/registry/strategy_registry.json").read_text(encoding="utf-8")
    )
    configured = next(
        item for item in strategy_config["strategies"] if item["strategy_id"] == STRATEGY_ID
    )
    registered = next(
        item for item in registry["strategies"] if item["strategy_id"] == STRATEGY_ID
    )
    if not configured.get("enabled") or registered.get("status") != "PAPER_APPROVED":
        raise StrategyArtifactError("strategy is not enabled and PAPER-approved")
    if configured.get("schedule") != registered.get("schedule"):
        raise StrategyArtifactError("strategy schedule drift between config and registry")
    governance = resolve_strategy_governance(
        STRATEGY_ID,
        str(registered["status"]),
        path=ROOT / "config/research_governance.yaml",
    )
    if (
        governance.effective_status != "PAPER_OBSERVATION_ONLY"
        or governance.paper_observation_enabled is not True
        or governance.automatic_promotion_eligible is not False
        or governance.capital_eligible is not False
    ):
        raise StrategyArtifactError("strategy governance is not safe for observation-only PAPER")
    return configured, registered, governance.effective_status


def build() -> dict[str, Any]:
    configured, registered, effective_status = _inputs()
    return build_strategy_artifact(
        repo_root=ROOT,
        strategy_id=STRATEGY_ID,
        strategy_version=str(registered["version"]),
        promotion_status=effective_status,
        allowed_runtime_modes=["PAPER"],
        live_enabled=False,
        component_paths=COMPONENT_PATHS,
        strategy_parameters=configured["parameters"],
        universe=registered["asset_universe"],
        schedule=configured["schedule"],
        data_schema_version="phase2-adjusted-total-return-d2-v1",
        promotion_evidence_paths=EVIDENCE_PATHS,
        code_commit=_git_commit(),
        created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        environment=current_environment(ENVIRONMENT_PACKAGES),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--output", default=str(ARTIFACT_PATH))
    parser.add_argument("--skip-environment", action="store_true")
    args = parser.parse_args()
    target = ROOT / args.output
    try:
        if args.mode == "build":
            if target.exists():
                payload = verify_strategy_artifact(
                    target,
                    repo_root=ROOT,
                    expected_strategy_id=STRATEGY_ID,
                    expected_strategy_version="v1",
                    expected_promotion_status="PAPER_OBSERVATION_ONLY",
                    verify_environment=not args.skip_environment,
                )
                path, reused = target, True
            else:
                payload = build()
                path, reused = write_strategy_artifact(target, payload)
            result = {
                "artifact": str(path.relative_to(ROOT)),
                "artifact_root_sha256": payload["artifact_root_sha256"],
                "reused": reused,
                "status": "PASS",
            }
        else:
            payload = verify_strategy_artifact(
                target,
                repo_root=ROOT,
                expected_strategy_id=STRATEGY_ID,
                expected_strategy_version="v1",
                expected_promotion_status="PAPER_OBSERVATION_ONLY",
                verify_environment=not args.skip_environment,
            )
            result = {
                "artifact": str(target.relative_to(ROOT)),
                "artifact_root_sha256": payload["artifact_root_sha256"],
                "status": "PASS",
            }
    except (OSError, StrategyArtifactError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
