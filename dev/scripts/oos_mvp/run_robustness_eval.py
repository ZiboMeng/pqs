#!/usr/bin/env python
"""CLI for the OOS MVP robustness eval (PRD §3 R2).

Runs ``core.research.robustness.runner.evaluate`` against one or more
candidate ids. Default is both currently frozen S2_paper_candidate
candidates (RCMv1 + Cand-2). Artifacts land in
``data/research_candidates/<id>_robustness_window.yaml`` /
``<id>_robustness_eval.{json,md}``.

evidence_class is always ``pseudo_oos_robustness`` — never deployable
OOS evidence.

Usage:
    python dev/scripts/oos_mvp/run_robustness_eval.py
    python dev/scripts/oos_mvp/run_robustness_eval.py --candidate-id rcm_v1_defensive_composite_01
    python dev/scripts/oos_mvp/run_robustness_eval.py --target-trading-days 252 --top-n 10
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from core.research.robustness.runner import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TARGET_TRADING_DAYS,
    DEFAULT_TOP_N,
    evaluate,
)

DEFAULT_CANDIDATES = [
    "rcm_v1_defensive_composite_01",
    "candidate_2_orthogonal_01",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run robustness eval for frozen candidates")
    parser.add_argument(
        "--candidate-id",
        action="append",
        default=None,
        help="Candidate id (repeatable). Default: both S2_paper_candidate ids.",
    )
    parser.add_argument(
        "--target-trading-days",
        type=int,
        default=DEFAULT_TARGET_TRADING_DAYS,
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    args = parser.parse_args()

    candidate_ids = args.candidate_id or DEFAULT_CANDIDATES
    summary = []
    for cid in candidate_ids:
        print(f"[oos-mvp] running robustness eval for {cid} ...", flush=True)
        result = evaluate(
            candidate_id=cid,
            target_trading_days=args.target_trading_days,
            top_n=args.top_n,
            output_dir=args.output_dir,
        )
        summary.append(
            {
                "candidate_id": cid,
                "evidence_class": result.window.evidence_class.value,
                "actual_trading_days": result.window.actual_trading_days,
                "target_trading_days": result.window.target_trading_days,
                "metrics": result.metrics,
                "artifacts": result.artifact_paths,
            }
        )

    print("\n[oos-mvp] done. summary:")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
