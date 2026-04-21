"""Unit tests for core/alignment/alignment_check.py (PRD M3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from core.alignment import (
    AlignmentCheckError,
    AlignmentMode,
    AlignmentReport,
    check_alignment,
    write_alignment_report,
)


ROOT = Path(__file__).resolve().parents[3]


def test_check_alignment_repo_runs():
    """On the real repo, alignment check must not raise in WARN mode."""
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    assert isinstance(report, AlignmentReport)
    assert report.timestamp
    assert report.mode == AlignmentMode.WARN
    # status is either conservative_default / active / no_validated_best
    assert report.production_status in (
        "conservative_default", "active", "no_validated_best",
    )


def test_conservative_default_has_empty_fingerprints():
    """conservative_default status → fingerprints empty → all checks tracking-only match."""
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    if report.production_status == "conservative_default":
        for name, chk in report.checks.items():
            # Empty expected means "not recorded, tracking only"
            assert chk["match"] is True or chk.get("note"), (
                f"{name}: expected match or tracking-only, got {chk}"
            )


def test_ignore_flag_short_circuits():
    report = check_alignment(ROOT, mode=AlignmentMode.WARN, ignore=True)
    assert report.ignored
    assert report.all_match is True
    assert report.production_status == "(ignored)"


def test_fail_mode_does_not_raise_on_empty_fingerprints():
    """conservative_default has empty fingerprints — should not raise even in FAIL mode."""
    report = check_alignment(ROOT, mode=AlignmentMode.FAIL)
    if report.production_status == "conservative_default":
        assert report.all_match or not report.errors


def test_fail_mode_raises_on_mismatch(tmp_path):
    """Simulate mismatch: build a fake repo with mismatching fingerprints."""
    # Copy minimum needed structure
    (tmp_path / "config").mkdir()
    # universe.yaml
    (tmp_path / "config" / "universe.yaml").write_text("""
seed_pool: [SPY, QQQ]
sector_etfs: []
factor_etfs: []
cross_asset: []
""")
    # risk/backtest/cost_model yaml (minimal)
    (tmp_path / "config" / "risk.yaml").write_text("long_only: true\n")
    (tmp_path / "config" / "backtest.yaml").write_text("start_date: '2020-01-01'\n")
    (tmp_path / "config" / "cost_model.yaml").write_text("mode: bps_based\n")
    # production_strategy.yaml with FAKE fingerprints that won't match
    (tmp_path / "config" / "production_strategy.yaml").write_text("""
schema_version: "1.0"
status: "active"
strategy_type: "multi_factor"
source:
  mode: "promoted_from_archive"
  spec_id: "fake_spec"
  lineage_tag: "fake"
  promoted_at: "2026-04-21T00:00:00Z"
  rationale: "test"
params:
  top_n: 4
factor_weights:
  low_vol: 0.5
  momentum: 0.5
validation:
  post_fix_validated: true
  passed_oos_gate: true
  passed_qqq_gate: true
  passed_paper_backtest_alignment: true
fingerprints:
  universe_hash: "deadbeef" * 8
  factor_registry_hash: "cafebabe" * 8
  config_hash: "abcdef01" * 8
""")
    # The above yaml has python-like concat — sanitize:
    import re
    ps_path = tmp_path / "config" / "production_strategy.yaml"
    text = ps_path.read_text()
    text = re.sub(r'"([a-f0-9]+)" \* 8', lambda m: f'"{m.group(1)*8}"', text)
    ps_path.write_text(text)

    with pytest.raises(AlignmentCheckError):
        check_alignment(tmp_path, mode=AlignmentMode.FAIL)


def test_write_alignment_report_roundtrip(tmp_path):
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    out = write_alignment_report(report, tmp_path)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["production_status"] == report.production_status
    assert loaded["mode"] == "warn"


def test_missing_production_strategy_returns_warning(tmp_path):
    """If production_strategy.yaml is missing, report warns but does not raise in WARN mode."""
    (tmp_path / "config").mkdir()
    # Write the 3 config files but NOT production_strategy.yaml
    (tmp_path / "config" / "universe.yaml").write_text("seed_pool: [SPY]\n")
    (tmp_path / "config" / "risk.yaml").write_text("long_only: true\n")
    (tmp_path / "config" / "backtest.yaml").write_text("start_date: '2020-01-01'\n")
    (tmp_path / "config" / "cost_model.yaml").write_text("mode: bps_based\n")

    report = check_alignment(tmp_path, mode=AlignmentMode.WARN)
    assert not report.production_strategy_exists
    assert report.production_status == "(missing)"
    assert any("Cannot load" in w for w in report.warnings)


def test_all_match_semantics():
    """all_match is True iff every check's .match is True."""
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    computed = all(c["match"] for c in report.checks.values())
    assert report.all_match == computed


def test_summary_line_format():
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    line = report.summary_line()
    assert "Alignment" in line
    assert report.production_status in line


def test_mode_enum_values():
    assert AlignmentMode.WARN.value == "warn"
    assert AlignmentMode.FAIL.value == "fail"


def test_checks_contain_expected_keys():
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    if report.production_strategy_exists:
        assert set(report.checks.keys()) == {"universe_hash", "factor_registry_hash", "config_hash"}


def test_report_as_dict_is_json_serializable():
    report = check_alignment(ROOT, mode=AlignmentMode.WARN)
    d = report.as_dict()
    json.dumps(d)  # should not raise
