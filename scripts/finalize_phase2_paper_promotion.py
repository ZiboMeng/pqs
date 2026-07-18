#!/usr/bin/env python3
"""Promote the phase-two candidate only after every frozen PAPER gate passes."""

from __future__ import annotations

import json
from pathlib import Path

from core.research.phase2.paper_promotion import current_commit, promote

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    record = promote(
        policy_path=ROOT / "config/strategy_promotion.yaml",
        validation_path=ROOT / "research/results/phase2/validation/summary_d2r5.json",
        holdout_path=ROOT / "research/results/phase2/holdout/summary_d2r5.json",
        operational_path=ROOT / "research/results/phase2/paper/operational_acceptance.json",
        strategy_registry_path=ROOT / "research/registry/strategy_registry.json",
        promotion_registry_path=ROOT / "research/registry/promotion_registry.json",
        config_paths=(
            ROOT / "config/strategies.paper.yaml",
            ROOT / "config/portfolio.paper.yaml",
            ROOT / "config/regime.paper.yaml",
        ),
        code_commit=current_commit(ROOT),
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
