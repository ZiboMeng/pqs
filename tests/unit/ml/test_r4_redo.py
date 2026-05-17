"""R4 acceptance — chart-native redo on literature pipeline (PRD §7).

R4-A1 attempt schema · R4-A2 CPCV+DSR fields · R4-A3 vs_tabular block ·
R4-A4 root_cause + config_scoped (no blanket) · R4-A5 old Phase3
superseded markers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parents[3]
_R4 = _PROJ / "data" / "audit" / "ml_redo" / "attempt_r4_litpath.json"


def _load():
    if not _R4.exists():
        pytest.skip("R4 redo not run (run run_r4_chart_native_redo.py)")
    return json.loads(_R4.read_text())


def test_r4_attempt_schema():
    d = _load()
    for k in ("schema_version", "attempt_id", "lineage", "pipeline",
              "arms", "best_arm", "vs_tabular_baseline", "verdict",
              "verdict_scope", "root_cause", "sealed_2026_read"):
        assert k in d, f"missing {k}"
    assert d["lineage"] == "ml-method-redo-2026-05-16"
    assert d["sealed_2026_read"] is False          # G4


def test_r4_cpcv_dsr_and_vs_tabular_block():
    d = _load()
    for arm, v in d["arms"].items():
        assert "oos_rank_ic" in v and "baseline_mom_ic" in v
        assert "vs_tabular_baseline" in v and "n_cpcv_folds" in v
        assert "deflated_sharpe" in v               # R2/R4-A2
    assert d["vs_tabular_baseline"] is not None     # R4-A3 numeric block
    assert "pbo" in d


def test_r4_config_scoped_no_blanket():
    d = _load()
    assert d["verdict_scope"] == "config_scoped"
    rc = d["root_cause"].lower()
    assert "config-scoped" in rc
    assert "not a blanket" in rc or "not 'chart-native fails'" in rc \
        or "deferred-compute" in rc                 # R4-A4 (no blanket; D2)


def test_r4_old_phase3_superseded():
    base = _PROJ / "data" / "audit" / "chart_structure"
    for aid in ("3a_001", "3b_001", "3c_001"):
        p = base / f"phase3_attempt_{aid}.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        assert d.get("superseded_by", "").startswith(
            "ml-method-redo-2026-05-16"), f"{aid} not superseded"
