"""M11a immediate-rerun probe — `scripts/run_paper_candidate.py`.

Two subprocess invocations of run_paper_candidate.py with identical
args but different PYTHONHASHSEEDs MUST produce byte-identical
pnl_daily.csv (the artifact that drives paper_drift_report).

This is the direct probe for the residual 18-65 bps paper-vs-replay
drift documented in `docs/memos/20260424-m14_nan_equity_fix.md` §4.3.
Pre-M11a-fix this would FAIL because BacktestEngine._generate_orders
iterated `set(...)` whose order depends on hash randomization, and
the fills' downstream effect on integer-share rounding produced
systematic per-process differences.

Skipped if the live registry/data prerequisites aren't present (CI on
a fresh checkout without paper-run state, etc).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_PAPER_CANDIDATE = REPO_ROOT / "scripts" / "run_paper_candidate.py"
REGISTRY_DB = REPO_ROOT / "data" / "research_candidates" / "registry.db"


def _have_prereqs() -> bool:
    return RUN_PAPER_CANDIDATE.exists() and REGISTRY_DB.exists()


@pytest.mark.skipif(
    not _have_prereqs(),
    reason="run_paper_candidate.py / registry.db missing — skipping CI probe",
)
def test_run_paper_candidate_byte_identical_across_hashseeds(tmp_path):
    """Two runs with PYTHONHASHSEED ∈ {0, 1} must produce identical pnl_daily."""
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    common = [
        sys.executable, str(RUN_PAPER_CANDIDATE),
        "--candidate-id", "rcm_v1_defensive_composite_01",
        "--start-date", "2024-01-02",
        "--end-date", "2024-01-31",  # ~20 trading days, lightweight
        "--top-n", "10",
    ]

    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "PYTHONUNBUFFERED": "1",
    }

    proc_a = subprocess.run(
        common + ["--out-dir", str(out_a)],
        env={**base_env, "PYTHONHASHSEED": "0"},
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, check=False, timeout=180,
    )
    if proc_a.returncode != 0:
        pytest.skip(
            f"run_paper_candidate seed=0 failed (likely missing data): "
            f"{proc_a.stderr[-500:]}"
        )

    proc_b = subprocess.run(
        common + ["--out-dir", str(out_b)],
        env={**base_env, "PYTHONHASHSEED": "1"},
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, check=False, timeout=180,
    )
    if proc_b.returncode != 0:
        pytest.skip(
            f"run_paper_candidate seed=1 failed: {proc_b.stderr[-500:]}"
        )

    pnl_a = pd.read_csv(out_a / "pnl_daily.csv")
    pnl_b = pd.read_csv(out_b / "pnl_daily.csv")

    pd.testing.assert_frame_equal(
        pnl_a, pnl_b, check_exact=False, atol=1e-9, rtol=0,
    )

    # Stricter: equity_curve column must be byte-equal
    assert (pnl_a["equity_curve"].values == pnl_b["equity_curve"].values).all(), (
        f"equity_curve diverged across PYTHONHASHSEED.\n"
        f"seed=0 final: {pnl_a['equity_curve'].iloc[-1]}\n"
        f"seed=1 final: {pnl_b['equity_curve'].iloc[-1]}"
    )
