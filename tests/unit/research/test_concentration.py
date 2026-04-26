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
    """thin-data WEIGHTED share ∈ (0.05, 0.10] with no top-N triggers.

    Post-audit-fix (2026-04-25): gate uses weighted = Σ share[s] *
    thin_pct[s], not binary. Fixture: 5 equal positions × 0.20 weight,
    THIN1 with thin_pct=0.30 → weighted = 0.20 * 0.30 = 0.06 → warning.
    """
    base = {f"S{i:02d}": 0.20 for i in range(5)}
    base.pop("S00")
    base["THIN1"] = 0.20
    df = _wts(base, base)
    r = compute(
        "c", df,
        thin_data_symbols=["THIN1"],
        thin_data_pct_map={"THIN1": 0.30},
    )
    assert r.concentration_gate_status == ConcentrationGateStatus.warning
    assert any("thin_data_weighted_share" in w for w in r.triggered_warnings)
    assert not any("thin_data_weighted_share" in e for e in r.triggered_extremes)
    # Binary share is HIGHER than weighted (full 0.20 instead of 0.06):
    # diagnostic only, doesn't drive tier.
    assert r.thin_data_binary_share > r.thin_data_weighted_share


def test_thin_data_extreme():
    """thin-data WEIGHTED share > 0.10 with no top-N triggers."""
    base = {f"S{i:02d}": 0.20 for i in range(5)}
    base.pop("S00")
    base["THIN1"] = 0.20
    df = _wts(base, base)
    r = compute(
        "c", df,
        thin_data_symbols=["THIN1"],
        thin_data_pct_map={"THIN1": 0.55},  # weighted = 0.20 * 0.55 = 0.11
    )
    assert r.concentration_gate_status == ConcentrationGateStatus.manual_review_required
    assert any("thin_data_weighted_share" in e for e in r.triggered_extremes)


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
    # Post-audit fix: md must show both metrics with explicit gate vs
    # diagnostic labels (so future readers can't conflate them).
    assert "WEIGHTED share (gate metric)" in md
    assert "binary share (diagnostic" in md


# ── post-MVP audit (2026-04-25) regression tests for weighted gate ────


def test_weighted_thin_metric_correctly_dilutes_low_thin_pct_symbols():
    """Audit fix regression A: large weight on a SLIGHTLY-thin symbol
    must not be over-counted by the gate.

    Pre-fix bug: binary gate counted the symbol's FULL weight share
    even if its thin_data_pct was tiny (e.g. 5%). Post-fix: weighted
    share scales linearly with thin_data_pct, so a 5% thin symbol
    contributes only 0.05× of its weight.
    """
    df = _wts({"BIG": 0.30, "AAA": 0.20, "BBB": 0.15, "CCC": 0.10, "DDD": 0.10, "EEE": 0.10})
    # BIG has 5% thin history — barely thin.
    r = compute(
        "c", df,
        thin_data_symbols=["BIG"],
        thin_data_pct_map={"BIG": 0.05},
    )
    # Binary: BIG full weight share = 0.30 / 0.95 ≈ 0.316 — would have
    # extreme-tripped pre-fix.
    assert r.thin_data_binary_share > 0.30
    # Weighted: 0.316 × 0.05 = 0.0158 — far below 0.05 warning threshold.
    assert r.thin_data_weighted_share < 0.05
    # Gate: pass on thin axis (no thin-data trigger in either tier).
    assert not any(
        "thin_data" in w for w in r.triggered_warnings
    )
    assert not any(
        "thin_data" in e for e in r.triggered_extremes
    )


def test_weighted_gate_demotes_cand2_style_from_extreme_to_warning():
    """Audit fix regression B: Cand-2-style fixture.

    Pre-fix: binary gate ~50% → extreme + frozen.
    Post-fix: weighted gate ~6% → warning + allowed.

    Demonstrates the "implementation false-positive" the audit found
    and fixed — Cand-2-shaped exposure unfreezes once the gate metric
    is honest. Fixture is a uniform 6 watch + 6 non-watch panel so
    no top-1 / top-3 confound triggers; watch thin_pct = 0.12 (real
    Cand-2 average is in this band).
    """
    base = {f"NW{i:02d}": 0.10 for i in range(6)}
    base.update({f"W{i:02d}": 0.10 for i in range(6)})
    df = _wts(base)
    watch_syms = [f"W{i:02d}" for i in range(6)]
    r = compute(
        "c", df,
        watch_symbols=watch_syms,
        thin_data_symbols=watch_syms,
        thin_data_pct_map={s: 0.12 for s in watch_syms},
    )
    # Binary share = 6 × 0.0833 = 0.50 (would extreme-trip pre-fix).
    assert r.thin_data_binary_share > 0.40
    # Weighted = 0.50 × 0.12 = 0.06 → warning (between 0.05 and 0.10).
    assert 0.05 < r.thin_data_weighted_share < 0.10
    # Gate: warning, NOT manual_review_required.
    assert r.concentration_gate_status == ConcentrationGateStatus.warning
    assert r.narrative_permission == NarrativePermission.allowed


def test_weighted_gate_keeps_rcm_v1_style_in_extreme():
    """Audit fix regression C: RCMv1-style fixture.

    Pre-fix binary gate ~57% → extreme + frozen.
    Post-fix weighted gate ~15% → STILL extreme. The candidate's
    extreme status is real, not implementation false-positive — heavy
    exposure to symbols that are themselves substantially thin.

    Same uniform 6+6 panel as the Cand-2 test, but watch thin_pct = 0.30
    (RCMv1 real top contributors average ~25-30%).
    """
    base = {f"NW{i:02d}": 0.10 for i in range(6)}
    base.update({f"W{i:02d}": 0.10 for i in range(6)})
    df = _wts(base)
    watch_syms = [f"W{i:02d}" for i in range(6)]
    r = compute(
        "c", df,
        watch_symbols=watch_syms,
        thin_data_symbols=watch_syms,
        thin_data_pct_map={s: 0.30 for s in watch_syms},
    )
    # Weighted = 0.50 × 0.30 = 0.15 → extreme (> 0.10).
    assert r.thin_data_weighted_share > 0.10
    assert r.concentration_gate_status == ConcentrationGateStatus.manual_review_required
    assert r.narrative_permission == NarrativePermission.frozen


def test_weighted_share_handles_percent_scale():
    """If sidecar passes thin_data_pct as percent (>1, e.g. 23.3 instead
    of 0.233), the gate must still behave correctly — divide-by-100
    normalization applies."""
    df = _wts({"AAA": 0.50, "BBB": 0.50})
    r = compute(
        "c", df,
        thin_data_symbols=["AAA"],
        thin_data_pct_map={"AAA": 30.0},  # raw percent, not fraction
    )
    # Should be normalized to 0.30 fraction → weighted = 0.50 × 0.30 = 0.15
    assert 0.10 < r.thin_data_weighted_share < 0.20
