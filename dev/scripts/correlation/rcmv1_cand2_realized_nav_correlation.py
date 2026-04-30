"""
RCMv1 vs Cand-2 — historical NAV correlation diagnostic (pair-specific wrapper).

This is the LEGACY wrapper preserved for reproducibility of the
2026-04-30 NAV correlation finding. As of 2026-04-30 R39 cleanup,
the actual diagnostic logic lives in
`dev/scripts/correlation/run_pair_nav_correlation.py` which is
generic across any pair. This file is a thin wrapper that fixes
the candidate IDs and run-dirs to RCMv1 × Cand-2 and writes the
canonical output JSON path that the existing memo references.

External-reviewer-prompted experiment (2026-04-30): Cand-2 was
nominated under a "factor-IC orthogonal" claim that has never
been verified at the NAV / portfolio-return level. With Step 5 C2
correlation budget shipped (warn 0.70 / reject 0.85; pairwise on
realized candidate daily returns), this script closes that loop.

Inputs:
  data/paper_runs/rcm_v1_defensive_composite_01/20260425T041403Z/   (2022-08-26 -> 2022-12-15)
  data/paper_runs/rcm_v1_defensive_composite_01/20260425T041358Z/   (2024-01-02 -> 2024-04-19)
  data/paper_runs/candidate_2_orthogonal_01/20260425T041405Z/        (2022-08-26 -> 2022-12-15)
  data/paper_runs/candidate_2_orthogonal_01/20260425T041400Z/        (2024-01-02 -> 2024-04-19)

These are the latest post-step3b ("honest" data round-3) re-runs of
the two paper cells the candidates were nominated on.

Outputs:
  - prints to stdout
  - dumps machine-readable JSON to:
      data/memos/20260430_rcmv1_cand2_realized_correlation.json
    (same path as before refactor; existing memo references intact)

==============================================================================
KEY-NAME COMPATIBILITY NOTE — 2026-04-30 R39 refactor.
==============================================================================
Pre-refactor JSON had a small inconsistency: cell `max_dd` /
`beta_to_qqq` / `beta_to_spy` used full column names (`rcm_v1` /
`cand_2`) but the residual block used short names (`beta_rcm` /
`beta_cnd` / `residual_ann_sharpe_rcm` / `residual_ann_sharpe_cnd`).

Post-refactor, the residual block uses full names (`beta_rcm_v1` /
`beta_cand_2` / `residual_ann_sharpe_rcm_v1` /
`residual_ann_sharpe_cand_2`) for internal consistency.

Headline numbers (pooled Pearson, residual Pearson vs SPY/QQQ,
betas to SPY/QQQ, residual Sharpes) are NUMERICALLY IDENTICAL
to the pre-refactor output. Only key labels changed.

Existing memo references all describe these by NUMBER not by JSON
key, so no documentation update needed.
==============================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add this script's directory to sys.path so we can import the
# co-located generic runner module (dev/ is not a Python package).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Re-export classify / classify_residual / compute_residual_correlation /
# run_pair_correlation for any caller that imports from this module
# (preserves test surface for self_audit_methodology checks).
from run_pair_nav_correlation import (  # type: ignore[import-not-found]  # noqa: F401, E402
    classify,
    classify_residual,
    compute_residual_correlation,
    run_pair_correlation,
)


REPO = Path(__file__).resolve().parents[3]


# Legacy pair-specific configuration. Frozen for the 2026-04-30
# RCMv1 × Cand-2 finding; Track C nominees use generic runner.
RCMV1_RUN_DIRS = [
    REPO / "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041403Z",
    REPO / "data/paper_runs/rcm_v1_defensive_composite_01/20260425T041358Z",
]
CAND2_RUN_DIRS = [
    REPO / "data/paper_runs/candidate_2_orthogonal_01/20260425T041405Z",
    REPO / "data/paper_runs/candidate_2_orthogonal_01/20260425T041400Z",
]
CELL_LABELS = ["2022_h2", "2024_q1"]


def main() -> None:
    result = run_pair_correlation(
        cand_a_id="rcm_v1_defensive_composite_01",
        cand_a_run_dirs=RCMV1_RUN_DIRS,
        cand_b_id="candidate_2_orthogonal_01",
        cand_b_run_dirs=CAND2_RUN_DIRS,
        cell_labels=CELL_LABELS,
        min_overlap=60,
        # Pass legacy column names so cell-level keys stay identical
        # to pre-refactor output (max_dd.rcm_v1 / beta_to_spy.cand_2 etc).
        cand_a_col="rcm_v1",
        cand_b_col="cand_2",
    )

    # Override experiment field to match pre-refactor canonical name + as_of date.
    result["experiment"] = "rcmv1_vs_cand2_historical_nav_correlation"
    result["as_of"] = "2026-04-30"
    # Pre-refactor output didn't have these two fields (they were
    # added by the generic runner) — drop for byte-cleaner diff vs
    # legacy snapshot. They're informational; the tier table below
    # already covers them.
    result.pop("candidate_a_id", None)
    result.pop("candidate_b_id", None)
    result.pop("min_overlap_days", None)
    result.pop("overlap_warning", None)

    out_dir = REPO / "data" / "memos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "20260430_rcmv1_cand2_realized_correlation.json"
    out_path.write_text(json.dumps(result, indent=2, allow_nan=False))

    print(json.dumps(result, indent=2, allow_nan=False))
    print()
    print(f"Wrote machine-readable result to: {out_path}")


if __name__ == "__main__":
    main()
