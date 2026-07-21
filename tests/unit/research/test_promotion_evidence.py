from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.research.promotion.evidence import (
    REQUIRED_BOUND_SOURCES,
    sha256_file,
    validate_promotion_evidence,
)


ROOT = Path(__file__).resolve().parents[3]
COMMIT = "a" * 40


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config/research_governance.yaml", tmp_path / "config")
    source_hashes = {}
    for relative in REQUIRED_BOUND_SOURCES:
        source = tmp_path / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            source.write_text(f"fixture for {relative}\n", encoding="utf-8")
        source_hashes[relative] = sha256_file(source)
    source = tmp_path / REQUIRED_BOUND_SOURCES[0]
    qualification = tmp_path / "qualification.json"
    qualification.write_text(json.dumps({"candidate_id": "candidate-1"}))
    alignment = tmp_path / "alignment.json"
    alignment.write_text(
        json.dumps({"passed": True, "max_equity_drift_bps": 0.5}),
        encoding="utf-8",
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({
            "schema_version": 1,
            "candidate_id": "candidate-1",
            "code_commit": COMMIT,
            "benchmark": {
                "symbol": "SPY",
                "comparison_basis": "total_return_after_strategy_costs",
                "strategy_costs_included": True,
            },
            "lookahead": {
                "passed": True,
                "test_exit_code": 0,
                "tests": ["timing"],
                "source_hashes": source_hashes,
            },
            "overfit": {
                "honest_n_trials": 20,
                "deflated_sharpe_probability": 0.97,
                "probability_backtest_overfitting": 0.25,
                "minimum_backtest_length_passed": True,
                "cpcv_passed": True,
                "cpcv_n_folds": 15,
                "artifact_path": "qualification.json",
                "artifact_sha256": sha256_file(qualification),
            },
            "paper_backtest_alignment": {
                "passed": True,
                "max_equity_drift_bps": 0.5,
                "artifact_path": "alignment.json",
                "artifact_sha256": sha256_file(alignment),
            },
        }),
        encoding="utf-8",
    )
    return evidence, source


def test_valid_candidate_bound_evidence_passes(tmp_path: Path) -> None:
    evidence, _ = _fixture(tmp_path)
    result = validate_promotion_evidence(
        evidence,
        expected_candidate_id="candidate-1",
        repo_root=tmp_path,
        expected_code_commit=COMMIT,
    )
    assert result.passed
    assert result.failed_checks == ()
    assert len(result.artifact_sha256) == 64


def test_source_drift_fails_closed(tmp_path: Path) -> None:
    evidence, source = _fixture(tmp_path)
    source.write_text("value = 2\n", encoding="utf-8")
    result = validate_promotion_evidence(
        evidence,
        expected_candidate_id="candidate-1",
        repo_root=tmp_path,
        expected_code_commit=COMMIT,
    )
    assert not result.passed
    assert any(item.startswith("lookahead_source_hash_mismatch") for item in result.failed_checks)


def test_overfit_threshold_failure_routes_to_hold(tmp_path: Path) -> None:
    evidence, _ = _fixture(tmp_path)
    payload = json.loads(evidence.read_text())
    payload["overfit"]["deflated_sharpe_probability"] = 0.50
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_promotion_evidence(
        evidence,
        expected_candidate_id="candidate-1",
        repo_root=tmp_path,
        expected_code_commit=COMMIT,
    )
    assert not result.passed
    assert "overfit_dsr_below_threshold" in result.failed_checks


def test_missing_evidence_is_never_a_pass(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config/research_governance.yaml", tmp_path / "config")
    result = validate_promotion_evidence(
        None,
        expected_candidate_id="candidate-1",
        repo_root=tmp_path,
    )
    assert not result.passed
    assert "promotion_evidence_missing" in result.failed_checks


def test_source_reference_outside_repo_is_rejected(tmp_path: Path) -> None:
    evidence, _ = _fixture(tmp_path)
    outside = tmp_path.parent / "outside-source.py"
    outside.write_text("not repository evidence\n", encoding="utf-8")
    payload = json.loads(evidence.read_text())
    payload["lookahead"]["source_hashes"][str(outside)] = sha256_file(outside)
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    result = validate_promotion_evidence(
        evidence,
        expected_candidate_id="candidate-1",
        repo_root=tmp_path,
        expected_code_commit=COMMIT,
    )
    assert not result.passed
    assert any(
        item.startswith("lookahead_source_hash_mismatch")
        for item in result.failed_checks
    )
