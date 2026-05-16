"""Schema validation for the Phase 2A incremental-IC report (AC P2-A1).

Per ralph-loop execution PRD §5 round P2A·R2. Machine-checkable acceptance:
the report JSON exists, carries the required paired-test fields, the B3
col-diff audit (exactly the 12 family-T columns differ), and the
config-scoped verdict marker (P2-A2 machine proxy).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPORT = (Path(__file__).resolve().parents[3]
           / "data" / "audit" / "chart_structure" / "phase2a_incremental_ic.json")


def test_phase2a_report_schema():
    if not _REPORT.exists():
        pytest.skip("phase2a report not generated yet")
    rep = json.loads(_REPORT.read_text())

    assert rep["evaluation"] == "phase2a_incremental_ic"
    # P2-A2 machine proxy: verdict must be declared config-scoped
    assert rep["verdict_scope"] == "config_scoped"
    assert isinstance(rep["k_grid"], list) and rep["k_grid"]
    assert "verdict" in rep and rep["verdict"]

    for key, r in rep["results"].items():
        # B3 audit: treatment differs from baseline by EXACTLY the 12
        # family-T columns
        assert r["col_diff_count"] == 12, f"{key}: col_diff_count != 12"
        assert r["col_diff_is_family_t"] is True, f"{key}: col diff not family T"
        pt = r["paired_t"]
        for fld in ("n_years", "mean_delta_ic", "std_delta_ic",
                    "t_stat", "p_value", "ci95"):
            assert fld in pt, f"{key}: paired_t missing {fld}"
        assert len(pt["ci95"]) == 2
        assert isinstance(rep["significant_positive_ks"], list)
