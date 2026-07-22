#!/usr/bin/env python3
"""Freeze Evaluation Contract V2 from the canonical SPY artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.research.evaluation_contract_v2 import (  # noqa: E402
    load_evaluation_contract_v2,
)
from core.research.qualification_v2 import canonical_sha256, sha256_file  # noqa: E402
from core.research.qualification_v4 import _month_end_indices  # noqa: E402


def _atomic_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        default="research/protocols/mining_v5/canonical_spy_total_return.json",
    )
    parser.add_argument(
        "--output",
        default="research/protocols/mining_v5/evaluation_contract_v2.yaml",
    )
    args = parser.parse_args()
    benchmark_path = Path(args.benchmark)
    benchmark_path = (
        benchmark_path if benchmark_path.is_absolute() else ROOT / benchmark_path
    ).resolve()
    output = Path(args.output)
    output = output if output.is_absolute() else ROOT / output
    if output.exists():
        print(f"ERROR: evaluation contract is immutable: {output}", file=sys.stderr)
        return 2
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    dates = tuple(date.fromisoformat(value) for value in benchmark["dates"])
    date_values = [value.isoformat() for value in dates]
    month_ends = [
        dates[index].isoformat() for index in _month_end_indices(dates)
    ]
    payload = {
        "schema_version": 2,
        "protocol_id": "pqs-mining-v5-balanced-v1",
        "governance_policy_id": "pqs-governance-reconciliation-v3",
        "evaluation_start": date_values[0],
        "evaluation_end": date_values[-1],
        "return_dates_sha256": canonical_sha256(date_values),
        "month_end_dates_sha256": canonical_sha256(month_ends),
        "calendar_years": sorted({value.year for value in dates}),
        "minimum_history_sessions": 756,
        "float_comparison_tolerance": 1e-12,
        "cost_scenarios": [
            {"name": "base_30bps", "execution_cost_bps": 30.0},
            {"name": "double_60bps", "execution_cost_bps": 60.0},
            {"name": "triple_90bps", "execution_cost_bps": 90.0},
        ],
        "benchmark": {
            "symbol": "SPY",
            "return_basis": "split_and_distribution_adjusted_total_return",
            "cost_policy": "costless_total_return_hurdle",
            "distributions": "reinvested",
            "source_path": str(benchmark_path.relative_to(ROOT)),
            "source_sha256": sha256_file(benchmark_path),
            "returns_sha256": benchmark["returns_sha256"],
        },
        "return_gates": {
            "base_30bps_cagr_strictly_greater_than_spy": True,
            "double_60bps_cagr_not_less_than_spy": True,
            "triple_90bps_cagr_role": "diagnostic",
            "rolling_window_months": 36,
            "rolling_sample_at_month_end": True,
            "min_rolling_excess_positive_fraction": 0.60,
            "rolling_252_session_role": "diagnostic",
        },
        "drawdown_gates": {
            "full_period_strictly_better": True,
            "rolling_window_months": 36,
            "rolling_sample_at_month_end": True,
            "min_rolling_win_fraction": 0.60,
            "effective_count_method": "conservative_non_overlapping_36m",
            "material_episode_trigger": 0.15,
            "every_material_episode_strictly_better": True,
            "monthly_downside_capture_strict_max": 1.0,
            "annual_material_harm_max_pp": 3.0,
            "annual_all_years_strict_dominance": False,
            "apply_to_all_cost_scenarios": True,
            "raw_strategy_absolute_cap_enabled": False,
        },
        "account_risk": {
            "research_candidate_gate": False,
            "paper_status_on_incomplete": "SHADOW_PAPER_OBSERVATION",
            "operating_target_min": 0.15,
            "operating_target_max": 0.20,
            "stress_path_max_drawdown": 0.25,
            "required_path_scenarios": [
                "gfc_2008",
                "covid_2020",
                "rate_hike_2022",
            ],
            "terminal_weighted_shock_can_pass": False,
            "capital_eligible_in_this_phase": False,
        },
        "cpcv": {
            "n_groups": 6,
            "k_test": 2,
            "horizon": 63,
            "embargo_frac": 0.01,
        },
    }
    _atomic_yaml(output, payload)
    load_evaluation_contract_v2(output, governance_path=ROOT / "config/research_governance.yaml")
    print(f"wrote {output}")
    print(f"benchmark_sha256={payload['benchmark']['source_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
