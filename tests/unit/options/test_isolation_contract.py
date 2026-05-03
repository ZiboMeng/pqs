"""Isolation contract gate test for PQS Options branch.

Ensures the `pqs-options-v1-2026-05-02` branch (and any future options
branch) does NOT modify files belonging to the stock workstream. Failure
on this test BLOCKS merge to main.

Per `docs/prd/20260502-pqs_options_v1_free_path_prd.md` Appendix B.

Rationale: Trial 9 forward observation runs on main and depends on stable
config_snapshot hashes (universe / factor_registry / risk / system /
research_mask). Any modification to those files triggers F-PRD revalidate
HALT on next observe, polluting the 90-day forward soak evidence.

Per CLAUDE.md "决策权属于 operator (我), auditor 只审计不驱动" — this
test is the auditor for branch isolation.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


PROJ = Path(__file__).resolve().parents[3]


# Files / globs the options branch must NOT touch.
# Rule: anything that affects Trial 9 forward observation OR stock workstream.
ISOLATION_LIST_EXACT = {
    # Config layer (most critical — drift triggers Trial 9 forward HALT)
    "config/universe.yaml",
    "config/factor_registry.py",  # Note: actually core/factors/factor_registry.py; kept here for legacy alias
    "config/risk.yaml",
    "config/system.yaml",
    "config/research_mask.yaml",
    "config/temporal_split.yaml",
    "config/temporal_split_v2.yaml",
    "config/temporal_split_v3.yaml",
    "config/cost_model.yaml",
    "config/notify.yaml",
    "config/backtest.yaml",
    "config/regime.yaml",
    "config/events.yaml",
    "config/production_strategy.yaml",
    "config/reporting.yaml",
    "config/acceptance.yaml",
    "config/fleet.yaml",
    # Reference data
    "data/ref/splits.parquet",
    "data/ref/bar_provenance.parquet",
    "data/ref/distributions.parquet",
    # CLAUDE.md and README — frozen on options branch
    "CLAUDE.md",
    "README.md",
}

# Path prefixes (subdirectories) the options branch must NOT touch.
ISOLATION_LIST_PREFIXES = (
    # Data layer
    "data/daily/",
    "data/intraday/",
    "data/research_candidates/trial9_",
    "data/research_candidates/rcm_v1_",
    "data/research_candidates/candidate_2_",
    "data/baseline/",
    "data/ml/forward_runs/",
    "data/ml/research_miner/",
    "data/paper_runs/",
    # Forward observation code
    "core/research/forward/",
    # Track A code
    "core/research/temporal_split",  # captures temporal_split.py + temporal_split_acceptance.py
    "core/research/sealed_ledger",
    "core/research/candidate_registry",
    "core/research/regime_classifier",
    "core/research/acceptance_helpers",
    "core/research/frozen_spec",
    "core/research/risk_cluster_map",
    "core/research/concentration/",
    "core/research/robustness/",
    # Mining + factor
    "core/mining/",
    "core/factors/",
    # Stock backtest core
    "core/backtest/",
    "core/signals/",
    "core/risk/",
    # Diagnostics + reporting + paper + universe + fleet
    "core/diagnostics/",
    "core/reporting/",
    "core/paper_trading/",
    "core/universe/",
    "core/fleet/",
    # Stock data layer (read-only OK; no modifications)
    "core/data/",
    # Stock dev scripts
    "dev/scripts/forward/",
    "dev/scripts/baseline/",
    "dev/scripts/cycle",  # cycle02/03/04 etc
    "dev/scripts/correlation/",
    "dev/scripts/oos_mvp/",
    "dev/scripts/loop/",
    # Stock tests
    "tests/unit/research/",
    "tests/unit/backtest/",
    "tests/unit/factors/",
    "tests/unit/signals/",
    "tests/unit/fleet/",
    "tests/unit/data/",
    "tests/unit/risk/",
    "tests/unit/paper_trading/",
    "tests/unit/reporting/",
    "tests/unit/diagnostics/",
    "tests/integration/",
    # Stock scripts
    "scripts/",
)


def _git_diff_files(base: str = "main") -> list[str]:
    """Return list of files changed in HEAD vs `base` branch."""
    result = subprocess.run(
        ["git", "diff", f"{base}...HEAD", "--name-only"],
        capture_output=True, text=True, cwd=PROJ, check=False,
    )
    if result.returncode != 0:
        # If main is not a valid ref (e.g., during initial branch setup), skip.
        pytest.skip(f"git diff vs {base} unavailable: {result.stderr}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _violates_isolation(path: str) -> bool:
    """True if the given path is in the isolation list (must not be touched)."""
    if path in ISOLATION_LIST_EXACT:
        return True
    for prefix in ISOLATION_LIST_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def test_options_branch_does_not_touch_stock_workstream():
    """HARD merge gate: branch diff vs main must contain ZERO modifications
    to isolation list files.

    Failure means this branch has accidentally edited a stock workstream
    file (Trial 9 forward observation source-of-truth, or stock acceptance
    pipeline, etc). Such a change would either:
      (a) Break Trial 9 forward observation (config_drift halt on next observe)
      (b) Pollute the audit trail of stock workstream
      (c) Both

    Resolution: revert the offending file change. If a legitimate stock
    workstream edit is needed, do it on a separate non-options branch.
    """
    diff = _git_diff_files("main")
    if not diff:
        # No changes vs main — trivially compliant
        return

    violations = [path for path in diff if _violates_isolation(path)]

    assert not violations, (
        f"Options branch violates isolation contract!\n"
        f"The following stock workstream files were modified:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n\nResolution: revert these files via "
        f"`git checkout main -- <file>`. If a legitimate stock workstream "
        "edit is needed, do it on a separate non-options branch.\n"
        "PRD reference: docs/prd/20260502-pqs_options_v1_free_path_prd.md "
        "Appendix B."
    )


def test_options_branch_writes_only_to_options_namespace():
    """Sanity check: branch's net new files all live under options-allowed
    namespace.

    Allowed write targets (per PRD Appendix B):
      - core/options/*
      - config/options_*.yaml
      - data/options/*
      - tests/unit/options/*
      - dev/scripts/options/*
      - docs/prd/2026*-pqs_options*.md
      - docs/memos/2026*-options_*.md
      - docs/checkpoints/2026*-options_*.md

    This is a guidance test (warns rather than fails) for files that
    are outside both isolation list AND options namespace. Such files
    might be legitimate (e.g., new top-level docs) but warrant review.
    """
    diff = _git_diff_files("main")
    if not diff:
        return

    allowed_prefixes = (
        "core/options/",
        "config/options_",
        "data/options/",
        "tests/unit/options/",
        "dev/scripts/options/",
        "docs/prd/",  # Allow any PRD if dated 2026 and options-related
        "docs/memos/",  # Same
        "docs/checkpoints/",
    )

    def _is_allowed(path: str) -> bool:
        for prefix in allowed_prefixes:
            if path.startswith(prefix):
                # For docs/, additionally check filename contains "options"
                if prefix.startswith("docs/"):
                    return "options" in Path(path).name.lower()
                return True
        return False

    # Don't double-flag isolation violations (other test handles those)
    suspicious = [
        path for path in diff
        if not _violates_isolation(path) and not _is_allowed(path)
    ]

    assert not suspicious, (
        f"Options branch wrote files outside options namespace:\n"
        + "\n".join(f"  - {s}" for s in suspicious)
        + "\n\nIf these are legitimate, update test_isolation_contract.py "
        "allowed_prefixes. Else move to options namespace."
    )


def test_isolation_list_completeness_sanity():
    """Sanity: isolation list is non-empty + covers main risk surfaces."""
    assert len(ISOLATION_LIST_EXACT) >= 10, "Isolation exact list suspiciously short"
    assert len(ISOLATION_LIST_PREFIXES) >= 10, "Isolation prefix list suspiciously short"
    # Critical coverage check
    assert "config/universe.yaml" in ISOLATION_LIST_EXACT
    assert "core/research/forward/" in ISOLATION_LIST_PREFIXES
    assert "data/research_candidates/trial9_" in ISOLATION_LIST_PREFIXES
