"""Robustness eval runner tests (R2).

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R2

Mix of unit tests (no data dependency) + a real-data smoke test that
skips if the rebuilt daily store or registry are not available.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from core.research.robustness.runner import (
    DEFAULT_BASELINE_PATH,
    _carve_window,
    _data_integrity_snapshot,
    _format_eval_md,
    _write_artifacts,
    evaluate,
)
from core.research.robustness.window_spec import (
    CandidateRobustnessWindow,
    EvidenceClass,
    ShrinkReasonCode,
)


def _idx(*dates: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(d) for d in dates])


def test_carve_window_exact_target():
    idx = _idx(*[f"2025-01-{d:02d}" for d in range(1, 21)])
    carve = _carve_window(idx, frozen_date=date(2025, 1, 20), target=10)
    assert carve.actual_trading_days == 10
    assert carve.start == date(2025, 1, 11)
    assert carve.end == date(2025, 1, 20)
    assert carve.shrink_reason is None


def test_carve_window_shrunk_with_reason():
    idx = _idx("2025-01-01", "2025-01-02", "2025-01-03")
    carve = _carve_window(idx, frozen_date=date(2025, 1, 3), target=10)
    assert carve.actual_trading_days == 3
    assert carve.shrink_reason is not None
    assert carve.shrink_reason.code == ShrinkReasonCode.data_coverage_short


def test_carve_window_no_data_raises():
    idx = _idx("2026-01-01")
    with pytest.raises(RuntimeError):
        _carve_window(idx, frozen_date=date(2025, 1, 1), target=5)


def test_data_integrity_snapshot_uses_explicit_commit():
    snap = _data_integrity_snapshot(
        daily_store_rebuild_commit="abcdef012345",
        baseline_snapshot_path="data/baseline/latest.json",
    )
    assert snap.daily_store_rebuild_commit == "abcdef012345"
    assert snap.baseline_snapshot_path == "data/baseline/latest.json"


def test_data_integrity_snapshot_default_is_pinned_to_data_rebuild_commit():
    """`daily_store_rebuild_commit` must default to the module pin
    (round-3 step-3b commit), NOT the repo HEAD at eval time.

    Pre-audit bug: runner used ``subprocess git rev-parse HEAD`` so the
    field captured the eval-time HEAD, conflating "data state" with
    "repo state". Fixed in audit pass; this test pins the contract.
    """
    from core.research.robustness.runner import DAILY_STORE_REBUILD_COMMIT
    snap = _data_integrity_snapshot(
        daily_store_rebuild_commit=None,  # default path
        baseline_snapshot_path="data/baseline/latest.json",
    )
    assert snap.daily_store_rebuild_commit.startswith(DAILY_STORE_REBUILD_COMMIT)


def test_write_artifacts_emits_three_files(tmp_path: Path):
    snap = _data_integrity_snapshot(
        daily_store_rebuild_commit="cafebabe1234",
        baseline_snapshot_path=DEFAULT_BASELINE_PATH,
    )
    window = CandidateRobustnessWindow(
        candidate_id="dummy_cand",
        evidence_class=EvidenceClass.pseudo_oos_robustness,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        actual_trading_days=252,
        target_trading_days=252,
        data_integrity_snapshot=snap,
    )
    metrics = {
        "cum_ret": 0.10,
        "sharpe": 1.20,
        "max_dd": -0.05,
        "vs_spy": 0.02,
        "vs_qqq": -0.01,
        "turnover_daily_mean": 0.04,
        "fill_count": 50,
        "n_dates": 252,
    }
    paths = _write_artifacts("dummy_cand", window, metrics, tmp_path)
    assert (tmp_path / "dummy_cand_robustness_window.yaml").exists()
    assert (tmp_path / "dummy_cand_robustness_eval.json").exists()
    assert (tmp_path / "dummy_cand_robustness_eval.md").exists()
    assert paths["window_yaml"].endswith("dummy_cand_robustness_window.yaml")


def test_format_eval_md_marks_pseudo_oos():
    snap = _data_integrity_snapshot(
        daily_store_rebuild_commit="cafebabe1234",
        baseline_snapshot_path=DEFAULT_BASELINE_PATH,
    )
    window = CandidateRobustnessWindow(
        candidate_id="dummy",
        evidence_class=EvidenceClass.pseudo_oos_robustness,
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        actual_trading_days=252,
        target_trading_days=252,
        data_integrity_snapshot=snap,
    )
    metrics = {
        "cum_ret": 0.0,
        "sharpe": 0.0,
        "max_dd": 0.0,
        "vs_spy": None,
        "vs_qqq": None,
        "turnover_daily_mean": 0.0,
        "fill_count": 0,
        "n_dates": 0,
    }
    md = _format_eval_md("dummy", window, metrics)
    assert "pseudo_oos_robustness" in md
    assert "NOT deployable OOS" in md
    assert "PRD v3" in md


@pytest.mark.skipif(
    not (
        Path("data/research_candidates/registry.db").exists()
        and Path("data/daily/SPY.parquet").exists()
        and Path("data/research_candidates/rcm_v1_defensive_composite_01.yaml").exists()
    ),
    reason="real data store / registry / candidate spec missing — skip smoke",
)
def test_smoke_evaluate_rcm_v1_short_window(tmp_path: Path):
    """Real-data smoke: tiny 20-day window for fast turnaround.

    Verifies that evaluate() runs end-to-end against the actual rebuilt
    store + registry + frozen spec, produces three artifacts, and
    explicitly stamps evidence_class = pseudo_oos_robustness.
    """
    out_dir = tmp_path / "research_candidates"
    out_dir.mkdir()
    spec_src = Path("data/research_candidates/rcm_v1_defensive_composite_01.yaml")
    (out_dir / "rcm_v1_defensive_composite_01.yaml").write_text(spec_src.read_text())

    result = evaluate(
        candidate_id="rcm_v1_defensive_composite_01",
        target_trading_days=20,
        output_dir=out_dir,
        top_n=3,
    )
    assert result.window.evidence_class == EvidenceClass.pseudo_oos_robustness
    assert result.window.actual_trading_days <= 20
    for key in (
        "cum_ret", "sharpe", "max_dd", "turnover_daily_mean", "fill_count", "n_dates"
    ):
        assert key in result.metrics
    for key in ("window_yaml", "eval_json", "eval_md"):
        assert Path(result.artifact_paths[key]).exists()
