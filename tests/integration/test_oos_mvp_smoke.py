"""OOS MVP integration smoke test (R6).

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R6
Acceptance:
  - smoke passes both candidates
  - negative simulation correctly rejected
  - pytest no regression
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml

from dev.scripts.oos_mvp.smoke import (
    DEFAULT_CANDIDATES,
    _negative_simulation,
    run_smoke,
)


_DAILY_STORE = Path("data/daily/SPY.parquet")
_REGISTRY = Path("data/research_candidates/registry.db")


def test_negative_simulation_rejects_pseudo_and_replay():
    """Standalone: negative simulation does not depend on real data."""
    res = _negative_simulation()
    assert res.historical_replay_rejected
    assert res.pseudo_oos_rejected
    assert res.errors == []
    assert res.all_ok


@pytest.mark.skipif(
    not (
        _DAILY_STORE.exists()
        and _REGISTRY.exists()
        and all(
            Path(f"data/research_candidates/{cid}_robustness_window.yaml").exists()
            for cid in DEFAULT_CANDIDATES
        )
    ),
    reason="real R1-R5 artifacts missing — run dev/scripts/oos_mvp/run_robustness_eval.py first",
)
def test_smoke_real_artifacts_passes():
    """End-to-end smoke against the real artifacts produced by R2 + R3 + R4."""
    result = run_smoke()
    assert result.negative_sim.all_ok, (
        f"negative simulation failed: {result.negative_sim.errors}"
    )
    for c in result.candidates:
        assert c.all_ok, (
            f"candidate {c.candidate_id} smoke failed: {c.errors}"
        )
    assert result.all_ok


def test_smoke_synthetic_artifacts_pass(tmp_path: Path):
    """Build a minimal valid artifact set in tmp_path and assert smoke passes.

    This guards the smoke against drift in artifact field expectations
    independent of the real candidates.
    """
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    cid = "synthetic_test"

    window_payload = {
        "candidate_id": cid,
        "evidence_class": "pseudo_oos_robustness",
        "start_date": "2025-04-16",
        "end_date": "2026-04-16",
        "actual_trading_days": 252,
        "target_trading_days": 252,
        "shrink_reason": None,
        "data_integrity_snapshot": {
            "daily_store_rebuild_commit": "abcdef012345",
            "baseline_snapshot_path": "data/baseline/latest.json",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
    (cand_dir / f"{cid}_robustness_window.yaml").write_text(yaml.safe_dump(window_payload))
    (cand_dir / f"{cid}_robustness_eval.json").write_text("{}")
    (cand_dir / f"{cid}_robustness_eval.md").write_text("# eval")
    (cand_dir / f"{cid}_concentration_report.json").write_text(
        '{"per_symbol_watch_shares": {"AAA": 0.05}, '
        '"concentration_gate_status": "warning", '
        '"narrative_permission": "allowed", '
        '"watchlist_total_share": 0.10, '
        '"thin_data_weighted_share": 0.04, '
        '"thin_data_binary_share": 0.10, "n_dates": 252}'
    )
    (cand_dir / f"{cid}_concentration_report.md").write_text("# conc")

    sidecar = tmp_path / "watch.parquet"
    pd.DataFrame(
        [{"symbol": "AAA", "watch_reasons": "x", "thin_data_count": 1, "quarantine_count": 1}]
    ).to_parquet(sidecar)

    result = run_smoke(
        candidate_ids=[cid],
        candidates_dir=cand_dir,
        watch_parquet=sidecar,
    )
    assert result.all_ok, (
        f"synthetic smoke failed: candidates={result.candidates} "
        f"negative={result.negative_sim}"
    )


def test_smoke_detects_wrong_evidence_class(tmp_path: Path):
    """If a window yaml has evidence_class=forward_oos (which would be
    wrong for pseudo-OOS robustness eval), smoke must FAIL the
    candidate but the smoke runner itself must not crash.
    """
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    cid = "wrong_class_cand"

    window_payload = {
        "candidate_id": cid,
        "evidence_class": "forward_oos",  # WRONG for robustness eval
        "start_date": "2025-04-16",
        "end_date": "2026-04-16",
        "actual_trading_days": 252,
        "target_trading_days": 252,
        "data_integrity_snapshot": {
            "daily_store_rebuild_commit": "abcdef012345",
            "baseline_snapshot_path": "data/baseline/latest.json",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }
    (cand_dir / f"{cid}_robustness_window.yaml").write_text(yaml.safe_dump(window_payload))
    (cand_dir / f"{cid}_robustness_eval.json").write_text("{}")
    (cand_dir / f"{cid}_robustness_eval.md").write_text("# eval")
    (cand_dir / f"{cid}_concentration_report.json").write_text(
        '{"per_symbol_watch_shares": {}, "concentration_gate_status": "pass", '
        '"narrative_permission": "allowed", "watchlist_total_share": 0, '
        '"thin_data_weighted_share": 0, "thin_data_binary_share": 0, '
        '"n_dates": 252}'
    )
    (cand_dir / f"{cid}_concentration_report.md").write_text("# conc")

    sidecar = tmp_path / "watch.parquet"
    pd.DataFrame(
        [{"symbol": "AAA", "watch_reasons": "x", "thin_data_count": 0, "quarantine_count": 0}]
    ).to_parquet(sidecar)

    result = run_smoke(
        candidate_ids=[cid],
        candidates_dir=cand_dir,
        watch_parquet=sidecar,
    )
    cand = result.candidates[0]
    assert cand.window_yaml_ok       # it parses
    assert not cand.evidence_class_ok  # but evidence_class fails
    assert not cand.all_ok
    assert any("evidence_class" in e for e in cand.errors)


def test_smoke_handles_missing_artifacts(tmp_path: Path):
    """Smoke runner must not crash when artifacts are missing — it
    records errors and reports failed for that candidate."""
    cand_dir = tmp_path / "empty"
    cand_dir.mkdir()
    sidecar = tmp_path / "missing.parquet"

    result = run_smoke(
        candidate_ids=["nothing_here"],
        candidates_dir=cand_dir,
        watch_parquet=sidecar,
    )
    cand = result.candidates[0]
    assert not cand.all_ok
    assert cand.errors  # at least one error recorded
    # Negative simulation should still pass (independent of candidate state)
    assert result.negative_sim.all_ok
