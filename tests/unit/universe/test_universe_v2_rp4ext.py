"""R-P4ext acceptance — expanded_v2 ~1k (supplementary PRD §8.5).

RP4-A1 coverage audit schema · RP4-A2 resolve_v2 + executable/v1
bit-identical · RP4-A5 survivorship linkage.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.universe.universe_resolver import (
    UNIVERSE_NAMES,
    resolve_universe,
)

_PROJ = Path(__file__).resolve().parents[3]


# RP4-A1 --------------------------------------------------------------
def test_coverage_audit_schema():
    p = _PROJ / "data" / "audit" / "ml_redo" / "universe_v2_coverage.json"
    assert p.exists(), "run dev/scripts/ml_redo/universe_v2_coverage_audit.py"
    a = json.loads(p.read_text())
    for k in ("n_scanned", "n_shortlist", "n_passed_filters", "n_selected",
              "target_n", "thresholds", "sealed_discipline", "per_symbol",
              "run1_artifact_note"):
        assert k in a, f"missing {k}"
    # N is data-driven (not a guessed constant): selected <= passed <= scanned
    assert a["n_selected"] <= a["n_passed_filters"] <= a["n_scanned"]
    assert a["n_selected"] > 0
    # per-symbol entries carry coverage provenance + drop reason field
    sample = [r for r in a["per_symbol"] if r.get("drop") is None][:5]
    for r in sample:
        assert "n_train_rows" in r and "completeness" in r
    # sealed discipline recorded
    assert "sealed 2026 never read" in a["sealed_discipline"]


# RP4-A2 --------------------------------------------------------------
def test_resolve_expanded_v2_and_executable_v1_bit_identical():
    assert "expanded_v2" in UNIVERSE_NAMES
    v2 = resolve_universe("expanded_v2")
    assert len(v2) > 200            # data-driven ~1k (+ base, + benchmarks)
    assert "SPY" in v2 and "QQQ" in v2
    # D6/P4-A2: executable + expanded_v1 outputs UNCHANGED by adding v2
    ex = resolve_universe("executable")
    assert len(ex) >= 79
    v1 = resolve_universe("expanded_v1")
    # executable is a strict prefix of v1 and v2 (additive semantics)
    assert v1[:len(ex)] == ex
    assert v2[:len(ex)] == ex
    with pytest.raises(ValueError):
        resolve_universe("expanded_v3")


# RP4-A5 --------------------------------------------------------------
def test_survivorship_audit_links_to_rp4ext():
    p = _PROJ / "data" / "audit" / "ml_redo" / "survivorship_audit.json"
    a = json.loads(p.read_text())
    # R0-A5 flags as_of_rebuild_required; R-P4ext is the consumer that
    # must honor it (v2 either includes delisted names OR records caveat)
    assert a["as_of_rebuild_required"] is True
    cov = json.loads(
        (_PROJ / "data" / "audit" / "ml_redo"
         / "universe_v2_coverage.json").read_text())
    # the coverage audit explicitly records the membership-by-data /
    # no-external-index stance (residual survivorship caveat is honest)
    assert "membership by data" in cov["sealed_discipline"]
