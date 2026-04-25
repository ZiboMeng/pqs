"""M12 concentration report tests.

PRD: docs/prd/20260425-oos_mvp_ralph_loop_execution.md §3 R3
PRD v3 §C: tier thresholds (lines 281-294)
Acceptance: 8+ tier classification tests; report-only no hard block.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.research.concentration import (
    ConcentrationGateStatus,
    NarrativePermission,
    compute,
    write_artifacts,
)
from core.research.concentration.report import (
    EXTREME_TOP1,
    EXTREME_TOP3,
    EXTREME_THIN_DATA,
    EXTREME_WATCH_SINGLE,
    WARNING_TOP1,
    WARNING_TOP3,
    WARNING_THIN_DATA,
    WARNING_WATCH_SINGLE,
)


def _wts(*rows) -> pd.DataFrame:
    """Helper: build a DataFrame of weights from list[dict]."""
    df = pd.DataFrame(list(rows)).fillna(0.0)
    df.index = pd.date_range("2025-01-01", periods=len(df), freq="D")
    return df


def test_pass_below_all_thresholds():
    df = _wts(
        {"AAA": 0.10, "BBB": 0.10, "CCC": 0.10, "DDD": 0.10, "EEE": 0.10},
        {"AAA": 0.10, "BBB": 0.10, "CCC": 0.10, "DDD": 0.10, "EEE": 0.10},
    )
    r = compute("c", df)
    assert r.concentration_gate_status == ConcentrationGateStatus.pass_
    assert r.narrative_permission == NarrativePermission.allowed
    assert r.triggered_warnings == []
    assert r.triggered_extremes == []


def test_top1_warning_only():
    """top-1 just above warning (0.45) but below extreme (0.50)."""
    df = _wts({"AAA": 0.45, "BBB": 0.05, "CCC": 0.05})
    r = compute("c", df)
    assert r.concentration_gate_status == ConcentrationGateStatus.warning
    assert r.narrative_permission == NarrativePermission.allowed
    assert any("top1_weight" in w for w in r.triggered_warnings)
    assert r.triggered_extremes == []


def test_top1_extreme_freezes_narrative():
    df = _wts({"AAA": 0.55, "BBB": 0.05, "CCC": 0.05})
    r = compute("c", df)
    assert r.concentration_gate_status == ConcentrationGateStatus.manual_review_required
    assert r.narrative_permission == NarrativePermission.frozen
    assert any("top1_weight" in e for e in r.triggered_extremes)


def test_top3_warning():
    """top-3 sum > 0.70 but each individual < 0.40 (so no top-1 warning)."""
    df = _wts({"AAA": 0.30, "BBB": 0.25, "CCC": 0.20, "DDD": 0.05})
    r = compute("c", df)
    assert r.concentration_gate_status == ConcentrationGateStatus.warning
    # top-3 trigger present, top-1 not present
    assert any("top3_weight" in w for w in r.triggered_warnings)
    assert not any("top1_weight" in w for w in r.triggered_warnings)


def test_top3_extreme():
    df = _wts({"AAA": 0.35, "BBB": 0.30, "CCC": 0.20, "DDD": 0.05})
    r = compute("c", df)
    # top-3 = 0.85 > 0.80 extreme
    assert r.concentration_gate_status == ConcentrationGateStatus.manual_review_required
    assert any("top3_weight" in e for e in r.triggered_extremes)


def test_watch_single_warning():
    df = _wts(
        {"WATCH1": 0.10, "BBB": 0.10, "CCC": 0.10, "DDD": 0.10},
        {"WATCH1": 0.10, "BBB": 0.10, "CCC": 0.10, "DDD": 0.10},
    )
    r = compute("c", df, watch_symbols=["WATCH1"])
    # WATCH1 weight-day share = 0.20 / 0.80 = 0.25 → > 0.08 warning, > 0.15 extreme
    assert r.concentration_gate_status == ConcentrationGateStatus.manual_review_required
    assert any("watch_single_share" in e for e in r.triggered_extremes)


def test_watch_single_warning_only():
    """watch single share ∈ [0.08, 0.15] → warning only, not extreme.

    Carefully choose weights so neither top-1 (>0.40), top-3 (>0.70) nor
    watch-extreme (>0.15) trigger. Spread the rest across many names.
    """
    base = {f"S{i:02d}": 0.0915 for i in range(10)}
    base["WATCH1"] = 0.085
    df = _wts(base, base)
    r = compute("c", df, watch_symbols=["WATCH1"])
    # WATCH1 share = 0.085 / 1.0 = 0.085 → > 0.08 warning, < 0.15 extreme
    # top-3 = 0.0915*3 ≈ 0.275 (< 0.70 warning)
    assert r.concentration_gate_status == ConcentrationGateStatus.warning
    assert any("watch_single_share" in w for w in r.triggered_warnings)
    assert not any("watch_single_share" in e for e in r.triggered_extremes)


def test_thin_data_warning():
    """thin-data share ∈ (0.05, 0.10] with no top-N triggers."""
    base = {f"S{i:02d}": 0.092 for i in range(10)}
    base["THIN1"] = 0.06
    df = _wts(base, base)
    r = compute("c", df, thin_data_symbols=["THIN1"])
    # thin total = 0.06 / 0.98 ≈ 0.061 → > 0.05 warning; < 0.08 watch warning;
    # top-3 = 0.276; top-1 = 0.092 → warning only on thin_data
    assert r.concentration_gate_status == ConcentrationGateStatus.warning
    assert any("thin_data_share" in w for w in r.triggered_warnings)
    assert not any("thin_data_share" in e for e in r.triggered_extremes)


def test_thin_data_extreme():
    df = _wts(
        {"THIN1": 0.15, "BBB": 0.20, "CCC": 0.20, "DDD": 0.20},
        {"THIN1": 0.15, "BBB": 0.20, "CCC": 0.20, "DDD": 0.20},
    )
    r = compute("c", df, thin_data_symbols=["THIN1"])
    # thin total = 0.30 / 1.50 = 0.20 → > 0.10 extreme
    assert r.concentration_gate_status == ConcentrationGateStatus.manual_review_required
    assert any("thin_data_share" in e for e in r.triggered_extremes)


def test_multiple_extremes_all_listed():
    df = _wts({"AAA": 0.55, "BBB": 0.30, "CCC": 0.10, "DDD": 0.05})
    r = compute("c", df)
    # top-1 = 0.55 > 0.50 AND top-3 = 0.95 > 0.80 → both extremes listed
    assert len(r.triggered_extremes) >= 2
    assert any("top1" in e for e in r.triggered_extremes)
    assert any("top3" in e for e in r.triggered_extremes)


def test_empty_weights_returns_pass():
    df = pd.DataFrame()
    r = compute("c", df)
    assert r.concentration_gate_status == ConcentrationGateStatus.pass_
    assert r.n_dates == 0


def test_write_artifacts_emits_two_files(tmp_path: Path):
    df = _wts({"AAA": 0.10, "BBB": 0.10, "CCC": 0.10, "DDD": 0.10})
    r = compute("c1", df)
    paths = write_artifacts(r, tmp_path)
    assert (tmp_path / "c1_concentration_report.json").exists()
    assert (tmp_path / "c1_concentration_report.md").exists()
    assert paths["concentration_json"].endswith("c1_concentration_report.json")


def test_thresholds_match_prd_v3():
    """Numeric copies of PRD v3 §C lines 281-294."""
    assert WARNING_TOP1 == 0.40
    assert WARNING_TOP3 == 0.70
    assert WARNING_THIN_DATA == 0.05
    assert WARNING_WATCH_SINGLE == 0.08
    assert EXTREME_TOP1 == 0.50
    assert EXTREME_TOP3 == 0.80
    assert EXTREME_THIN_DATA == 0.10
    assert EXTREME_WATCH_SINGLE == 0.15


def test_md_renders_status_and_caveats():
    df = _wts({"AAA": 0.55, "BBB": 0.20, "CCC": 0.15})
    r = compute("c", df)
    from core.research.concentration.report import _format_md
    md = _format_md(r)
    assert "manual_review_required" in md
    assert "frozen" in md
    assert "read-only" in md
    assert "not_computed" in md  # sector + beta MVP caveat
