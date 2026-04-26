"""Watch-list exposure section tests (R4).

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R4
Acceptance:
  - section appears in both report types for both candidates
  - watch sidecar missing → graceful degrade ("data quality unknown"), not crash
  - top-table + at least 1 prose paragraph
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from core.research.concentration.watch_exposure import (
    render_watch_exposure_section,
)


def _write_concentration(dir_: Path, candidate_id: str, payload: dict) -> Path:
    p = dir_ / f"{candidate_id}_concentration_report.json"
    p.write_text(json.dumps(payload))
    return p


def _write_sidecar(path: Path, rows: list[dict]) -> Path:
    df = pd.DataFrame(rows)
    df.to_parquet(path)
    return path


def _full_payload(**overrides) -> dict:
    base = {
        "candidate_id": "cand_x",
        "n_dates": 252,
        "watchlist_total_share": 0.30,
        "thin_data_total_share": 0.20,
        "watchlist_single_max_share": 0.10,
        "concentration_gate_status": "manual_review_required",
        "narrative_permission": "frozen",
        "per_symbol_watch_shares": {"BKNG": 0.10, "TKO": 0.05, "CMG": 0.03},
    }
    base.update(overrides)
    return base


def test_section_renders_table_and_prose(tmp_path: Path):
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _write_concentration(cand_dir, "cand_x", _full_payload())
    sidecar = _write_sidecar(
        tmp_path / "watch.parquet",
        [
            {
                "symbol": "BKNG",
                "watch_reasons": "thin_pct=58.3%",
                "thin_data_count": 278,
                "quarantine_count": 1569,
            },
            {
                "symbol": "TKO",
                "watch_reasons": "hardcoded_watch",
                "thin_data_count": 0,
                "quarantine_count": 30,
            },
            {
                "symbol": "CMG",
                "watch_reasons": "thin_pct=12%",
                "thin_data_count": 50,
                "quarantine_count": 5,
            },
        ],
    )
    lines = render_watch_exposure_section(
        "cand_x",
        watch_parquet=sidecar,
        candidates_dir=cand_dir,
    )
    body = "\n".join(lines)
    # Section header
    assert lines[0].startswith("## Watch-list exposure")
    # Top table
    assert "| symbol | weight-day share |" in body
    assert "| BKNG |" in body
    assert "278" in body  # thin_data_days for BKNG
    # Prose
    assert "weight-day-share on watch-list names" in body
    # narrative_permission echo
    assert "manual_review_required" in body
    assert "frozen" in body


def test_section_graceful_degrade_no_sidecar(tmp_path: Path):
    """Sidecar missing → no crash; aggregates from concentration JSON still shown."""
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _write_concentration(cand_dir, "cand_x", _full_payload())
    bad_sidecar = tmp_path / "missing.parquet"
    lines = render_watch_exposure_section(
        "cand_x",
        watch_parquet=bad_sidecar,
        candidates_dir=cand_dir,
    )
    body = "\n".join(lines)
    assert "no watch sidecar" in body
    # The concentration aggregates should still render (prose body)
    assert "weight-day-share" in body


def test_section_graceful_degrade_no_concentration(tmp_path: Path):
    """No concentration JSON → table omitted, explanatory note + no crash."""
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    sidecar = _write_sidecar(
        tmp_path / "watch.parquet",
        [{"symbol": "AAA", "watch_reasons": "x",
          "thin_data_count": 1, "quarantine_count": 1}],
    )
    lines = render_watch_exposure_section(
        "missing_candidate",
        watch_parquet=sidecar,
        candidates_dir=cand_dir,
    )
    body = "\n".join(lines)
    assert "no concentration report" in body


def test_section_graceful_degrade_neither(tmp_path: Path):
    """Both missing → single 'data quality unknown' note, no crash."""
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    lines = render_watch_exposure_section(
        "ghost",
        watch_parquet=tmp_path / "missing.parquet",
        candidates_dir=cand_dir,
    )
    body = "\n".join(lines)
    assert "data quality unknown" in body


def test_section_no_watch_overlap(tmp_path: Path):
    """Concentration shows zero watch-list overlap → table omitted, prose still emits."""
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _write_concentration(
        cand_dir, "cand_x",
        _full_payload(per_symbol_watch_shares={}, watchlist_total_share=0.0),
    )
    sidecar = _write_sidecar(
        tmp_path / "watch.parquet",
        [{"symbol": "AAA", "watch_reasons": "x",
          "thin_data_count": 0, "quarantine_count": 0}],
    )
    lines = render_watch_exposure_section(
        "cand_x",
        watch_parquet=sidecar,
        candidates_dir=cand_dir,
    )
    body = "\n".join(lines)
    assert "no overlap with watch-list" in body
    # prose still present
    assert "weight-day-share" in body


def test_master_report_includes_section_when_watch_exposure_set(tmp_path: Path):
    """MasterReport.to_markdown() must render the section when watch_exposure is set."""
    from core.reporting.master_report import MasterReport

    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _write_concentration(cand_dir, "cand_x", _full_payload())
    sidecar = _write_sidecar(
        tmp_path / "watch.parquet",
        [{"symbol": "BKNG", "watch_reasons": "thin_pct=58%",
          "thin_data_count": 100, "quarantine_count": 200}],
    )
    mr = MasterReport(
        generated_at=pd.Timestamp("2026-04-25"),
        watch_exposure={
            "candidate_id": "cand_x",
            "watch_parquet": sidecar,
            "candidates_dir": cand_dir,
        },
    )
    md = mr.to_markdown()
    assert "Watch-list exposure" in md
    assert "BKNG" in md
    assert "manual_review_required" in md


def test_master_report_omits_section_when_watch_exposure_none():
    """MasterReport.to_markdown() must NOT render the section if watch_exposure is None."""
    from core.reporting.master_report import MasterReport

    mr = MasterReport(generated_at=pd.Timestamp("2026-04-25"))
    md = mr.to_markdown()
    assert "Watch-list exposure" not in md


def test_pipe_in_watch_reasons_is_escaped(tmp_path: Path):
    """`watch_reasons` from the sidecar can contain raw `|` (e.g.,
    'thin_pct=58% | quar_pct=77%'). Those must be escaped so the markdown
    table column count stays correct.
    """
    cand_dir = tmp_path / "candidates"
    cand_dir.mkdir()
    _write_concentration(cand_dir, "cand_x", _full_payload(
        per_symbol_watch_shares={"AAA": 0.10},
    ))
    sidecar = _write_sidecar(
        tmp_path / "watch.parquet",
        [{"symbol": "AAA", "watch_reasons": "thin_pct=58% | quar_pct=77%",
          "thin_data_count": 100, "quarantine_count": 200}],
    )
    lines = render_watch_exposure_section(
        "cand_x",
        watch_parquet=sidecar,
        candidates_dir=cand_dir,
    )
    body = "\n".join(lines)
    # Raw pipe must not appear in the watch_reasons column body
    assert "thin_pct=58% \\| quar_pct=77%" in body
    # Find the AAA row and verify it has exactly 5 inner cells (6 column
    # boundary pipes). Escaped pipes inside cell content (`\|`) don't count.
    aaa_row = next(line for line in lines if line.startswith("| AAA "))
    boundary_count = aaa_row.replace("\\|", "").count("|")
    assert boundary_count == 6, (
        f"AAA row column count broken: boundary_count={boundary_count} row={aaa_row!r}"
    )


def test_section_default_paths_run_without_crash():
    """Default paths point at real repo state — must not crash even if files missing."""
    lines = render_watch_exposure_section("nonexistent_candidate_id_xyz")
    # We don't care about the exact body — just that it returned a list of strings.
    assert isinstance(lines, list)
    assert all(isinstance(s, str) for s in lines)
