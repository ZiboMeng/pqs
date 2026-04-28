"""Revalidate + materiality policy tests (PRD v2.1 §4.4 + §4.6).

Builds minimal v2-style TD entries in memory, mutates synthetic
panels, and verifies the right E1-E5 escalation fires for each
revision class.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from core.research.forward import (
    CHECKPOINT_DRIFT_BPS_THRESHOLD,
    NAV_IMPACT_BPS_THRESHOLD,
    RAW_DRIFT_PCT_THRESHOLD,
    BarHashInputs,
    CheckpointCadence,
    CostAssumptions,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
    PerScopeHashInputs,
    SourceLayerBreakdown,
    SourceLayerView,
    compute_benchmark_hash,
    compute_execution_nav_hash,
    compute_signal_input_hash,
    revalidate_manifest,
)
from core.research.frozen_spec import FrozenStrategySpec
from core.research.robustness.window_spec import (
    DataIntegritySnapshot,
    EvidenceClass,
)


CAND_DIR = "data/research_candidates"


# ── helpers ───────────────────────────────────────────────────────


def _bday_index(start: str, end: str) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _panel(symbols: list[str], start: str, end: str, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    idx = _bday_index(start, end)
    out: dict = {}
    for col, base in [("close", 100.0), ("open", 99.5), ("high", 101.0),
                       ("low", 99.0), ("volume", 1_000_000.0)]:
        df = pd.DataFrame(
            base + rng.standard_normal((len(idx), len(symbols))).cumsum(axis=0) * 0.1,
            index=idx, columns=symbols,
        )
        out[col] = df
    return out


def _spec() -> FrozenStrategySpec:
    return FrozenStrategySpec.from_yaml_file(
        f"{CAND_DIR}/rcm_v1_defensive_composite_01.yaml",
    )


def _build_v2_td_entry(
    *,
    panel: dict,
    spec: FrozenStrategySpec,
    universe: list[str],
    held: list[str],
    weights: dict,
    benchmark_symbols: list[str],
    start_date: date,
    as_of_date: date,
    cum_ret: float = 0.001,
    track_signal_per_cell: bool = True,
) -> ForwardRun:
    """Build a v2-style TD entry with all three input-scope hashes
    + bar_hash_inputs + held_today_weights captured.

    ``track_signal_per_cell`` defaults to ``True`` so per-cell
    attribution drives the E1-E5 path in tests asserting specific
    materiality outcomes (matches the explicit opt-in contract from
    Blocker-2: deterministic NAV-impact attribution requires populated
    signal_input.per_cell_digest). Tests covering the production
    default (empty signal-scope per_cell_digest → fail-closed) pass
    ``track_signal_per_cell=False`` explicitly.
    """
    sig_h, sig_in = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel, as_of_date=as_of_date,
        track_per_cell=track_signal_per_cell,
    )
    exec_h, exec_in = compute_execution_nav_hash(
        held_or_traded_symbols=held, panel=panel,
        start_date=start_date, as_of_date=as_of_date,
    )
    bench_h, bench_in = compute_benchmark_hash(
        benchmark_symbols=benchmark_symbols, panel=panel,
        start_date=start_date, as_of_date=as_of_date,
    )
    return ForwardRun(
        checkpoint_label="TD002",
        as_of_date=as_of_date,
        n_observed_trading_days=2,
        cum_ret=cum_ret,
        signal_input_hash=sig_h,
        execution_nav_hash=exec_h,
        benchmark_hash=bench_h,
        bar_hash=sig_h[:8] + exec_h[:8] + bench_h[:8],   # 24 chars
        bar_hash_inputs=BarHashInputs(
            signal_input=sig_in, execution_nav=exec_in, benchmark=bench_in,
        ),
        source_layer_breakdown=SourceLayerBreakdown(
            as_of_held_source=SourceLayerView(),
            window_input_source=SourceLayerView(),
        ),
        held_today_weights=weights,
    )


def _wrap_manifest(entry: ForwardRun, *, start_date: date) -> ForwardRunManifest:
    return ForwardRunManifest(
        candidate_id="rcm_v1_defensive_composite_01",
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef012345",
        start_date=start_date,
        cost_assumptions=CostAssumptions(
            source="config/cost_model.yaml",
            config_hash="cafebabe1234deadbeef",
        ),
        checkpoint_cadence=CheckpointCadence(),
        current_status=ForwardRunStatus.in_progress,
        data_integrity_snapshot=DataIntegritySnapshot(
            daily_store_rebuild_commit="abcdef012345",
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime(2026, 4, 28, tzinfo=timezone.utc),
        ),
        runs=[entry],
    )


def _common_setup(seed: int = 0):
    spec = _spec()
    universe = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"]
    held = ["AAPL", "MSFT"]
    weights = {"AAPL": 0.5, "MSFT": 0.5}   # so close drift × weight is meaningful
    benchmarks = ["SPY", "QQQ"]
    panel_a = _panel(universe + ["QQQ"], "2026-01-02", "2026-04-30", seed=seed)
    start_date = date(2026, 4, 24)
    as_of = date(2026, 4, 27)
    entry = _build_v2_td_entry(
        panel=panel_a, spec=spec, universe=universe, held=held,
        weights=weights, benchmark_symbols=benchmarks,
        start_date=start_date, as_of_date=as_of,
    )
    manifest = _wrap_manifest(entry, start_date=start_date)
    return spec, universe, held, weights, benchmarks, panel_a, manifest


# ── E0: clean revalidation produces no events ─────────────────────


def test_revalidate_clean_panel_no_events():
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003 / 2026-04-28",
    )
    assert summary.events == []
    assert summary.n_runs_checked == 1
    assert summary.requires_data_review is False


# ── E1: held set + close drift → NAV impact bps → invalidate ──────


def test_revalidate_e1_nav_impact_invalidates():
    """0.50% close drift on AAPL (50% weight) → NAV impact = 25 bps,
    well above E1's 10 bps threshold → invalidated."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] *= 1.005   # +0.5%

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert ev.policy_decision == "invalidated"
    # 0.50 weight × 0.5% drift = 0.0025 = 25 bps
    assert ev.estimated_nav_impact_bps is not None
    assert ev.estimated_nav_impact_bps >= NAV_IMPACT_BPS_THRESHOLD
    assert "execution_nav" in ev.affected_scopes
    assert summary.requires_data_review is True


# ── E5: small NAV but raw drift ≥0.50% on tiny weight → invalidate ─


def test_revalidate_e5_raw_drift_secondary_guard():
    """Tiny weight (0%) but 0.55% raw close drift → E5 guard fires."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    # Add a tiny-weight position that's revised
    manifest.runs[0].held_today_weights = {"AAPL": 0.99, "TSLA": 0.001, "MSFT": 0.0}
    # Re-rebuild the entry's exec hash with TSLA in the held set so the
    # diff actually surfaces a TSLA cell revision.
    panel_b = {k: v.copy() for k, v in panel.items()}
    held_with_tsla = ["AAPL", "MSFT", "TSLA"]
    new_entry = _build_v2_td_entry(
        panel=panel, spec=spec, universe=universe, held=held_with_tsla,
        weights=manifest.runs[0].held_today_weights,
        benchmark_symbols=benchmarks,
        start_date=manifest.start_date, as_of_date=manifest.runs[0].as_of_date,
    )
    manifest.runs[0] = new_entry

    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "TSLA"] *= 1.0055   # +0.55%

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    # NAV impact ≈ 0.001 × 0.55% × 10000 = 0.055 bps — below E1 (10 bps)
    assert ev.estimated_nav_impact_bps is not None
    assert ev.estimated_nav_impact_bps < NAV_IMPACT_BPS_THRESHOLD
    # But raw drift ≥ 0.50% → E5 → invalidate
    assert ev.raw_max_close_drift_pct >= RAW_DRIFT_PCT_THRESHOLD
    assert ev.policy_decision == "invalidated"


# ── flagged_only: small NAV impact + small drift → no invalidate ──


def test_revalidate_small_revision_flagged_only():
    """0.05% close drift on a 50% weight: NAV impact ≈ 2.5 bps, below
    all thresholds → flagged_only, no requires_data_review."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] *= 1.0005  # +0.05%

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert ev.policy_decision == "flagged_only"
    assert summary.requires_data_review is False


# ── bound_only: signal-scope-only revision (non-held name) → invalidate ──


def test_revalidate_signal_scope_revision_fail_closed():
    """A non-held universe name's volume revises (affects amihud_20d
    signal). Held set unaffected. Per §4.4 fail-closed rule, we cannot
    map this to deterministic NAV impact → bound_only → invalidated."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    # NVDA not in held set — only affects signal_input scope
    panel_b["volume"].loc[pd.Timestamp("2026-04-22"), "NVDA"] *= 1.5

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert "signal_input" in ev.affected_scopes
    # bound_only → estimated_nav_impact_bps None
    assert ev.estimated_nav_impact_bps is None
    assert ev.policy_decision == "invalidated"


# ── bound_only: out-of-ring revision → invalidate ─────────────────


def test_revalidate_out_of_ring_revision_fail_closed():
    """A revision lands 15 trading days back, outside the 10-day
    anchor ring. We can detect it via per_cell_digest but cannot
    compute deterministic NAV impact → bound_only → invalidated."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    # 2026-04-06 is 15+ trading days before 2026-04-27 as_of
    panel_b["close"].loc[pd.Timestamp("2026-04-06"), "AAPL"] *= 1.01

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert ev.policy_decision == "invalidated"
    assert "out-of-ring" in ev.delta_summary or "bound_only" in ev.delta_summary


# ── E4: decision sign flip ──────────────────────────────────────


def test_revalidate_e4_decision_sign_flip_either_direction():
    """E4 fires when |drift| could plausibly cross zero, regardless
    of which direction the revision pushes NAV. Bug-fix regression
    test (post-audit): pre-fix code only checked drift in the
    positive direction."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    # Stored cum_ret is small (0.001); a NAV impact of 5 bps (≥0.05%
    # = 0.0005) is large enough relative to |0.001|=0.001 to potentially
    # flip the sign in one direction. With weights 0.5/0.5 and a 0.01%
    # close drift on AAPL: NAV impact = 0.5 × 0.0001 × 10000 = 0.5 bps;
    # too small. Need larger drift.
    panel_b = {k: v.copy() for k, v in panel.items()}
    # Drift of 0.5% on 50% weight → NAV impact 25 bps = 0.0025 cum_ret
    # drift, dwarfing the stored 0.001 cum_ret.
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] *= 1.005

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    # |drift_magnitude| (0.0025) >= |stored_cum| (0.001) → E4 fires
    assert ev.decision_sign_flip is True
    assert "E4" in ev.delta_summary
    assert ev.policy_decision == "invalidated"


# ── E2/E3: benchmark drift ──────────────────────────────────────


def test_revalidate_benchmark_drift_invalidates():
    """SPY revision flips vs_spy materially → E3 trigger."""
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    # Revise SPY end-of-window close by +0.5% — drives vs_spy by ≥25 bps
    panel_b["close"].loc[pd.Timestamp("2026-04-27"), "SPY"] *= 1.005

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert "benchmark" in ev.affected_scopes
    # vs_spy drift should be substantial
    assert ev.estimated_vs_spy_drift_bps is not None
    assert abs(ev.estimated_vs_spy_drift_bps) >= CHECKPOINT_DRIFT_BPS_THRESHOLD
    assert ev.policy_decision == "invalidated"


# ── legacy TD001 entries skipped ──────────────────────────────────


def test_revalidate_skips_legacy_td001():
    """A TD001 entry with legacy_unhashed_inputs=True must be skipped
    (no event), counted in n_legacy_skipped."""
    spec, universe, held, weights, benchmarks, panel, manifest = _common_setup()
    legacy_td1 = ForwardRun(
        checkpoint_label="TD001",
        as_of_date=manifest.start_date,
        n_observed_trading_days=1,
        cum_ret=0.0,
        legacy_unhashed_inputs=True,
    )
    manifest.runs.insert(0, legacy_td1)

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert summary.n_legacy_skipped == 1
    assert summary.n_runs_checked == 1   # only the v2 entry was checked
    assert summary.events == []


# ── codex Round-10 Blocker 2: empty signal_input.per_cell_digest ──


def test_revalidate_signal_diff_empty_digest_fails_closed_even_with_exec_nav_diff():
    """Codex Round-10 Blocker 2 regression. Production default:
    ``track_per_cell=False`` on signal_input → empty per_cell_digest.
    A revision that flips BOTH signal_input AND execution_nav scope
    hashes must still fail-close to ``invalidated`` (bound_only) — we
    cannot prove the signal-scope diff is a strict subset of the
    execution_nav-anchored cells without per-cell attribution. Pre-fix
    code optimistically delegated materiality to execution_nav E1/E5
    when both scopes differed, missing parallel out-of-ring revisions.
    """
    spec, universe, held, _w, benchmarks, panel, _ = _common_setup()
    # Build the entry with track_signal_per_cell=False — the
    # production default.
    start_date = date(2026, 4, 24)
    as_of = date(2026, 4, 27)
    entry = _build_v2_td_entry(
        panel=panel, spec=spec, universe=universe, held=held,
        weights={"AAPL": 0.5, "MSFT": 0.5},
        benchmark_symbols=benchmarks,
        start_date=start_date, as_of_date=as_of,
        track_signal_per_cell=False,
    )
    assert entry.bar_hash_inputs.signal_input.per_cell_digest == {}, (
        "test setup: signal_input.per_cell_digest must be empty under "
        "production default"
    )
    manifest = _wrap_manifest(entry, start_date=start_date)

    # Mutate AAPL close on a held / in-ring date — flips both
    # signal_input AND execution_nav hashes. With empty signal-scope
    # digest we cannot prove the signal diff is exclusively this one
    # cell; conservative fail-close to bound_only / invalidated.
    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] *= 1.0005

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert "signal_input" in ev.affected_scopes
    assert "execution_nav" in ev.affected_scopes
    # The bound_only fail-close MUST fire regardless of E1 NAV bps
    # being below 10 bps threshold.
    assert ev.estimated_nav_impact_bps is None, (
        "bound_only must suppress deterministic NAV-impact reporting"
    )
    assert ev.policy_decision == "invalidated"
    assert "bound_only" in ev.delta_summary
    assert "empty per_cell_digest" in ev.delta_summary
    assert summary.requires_data_review is True


def test_revalidate_signal_diff_with_populated_digest_keeps_in_ring_path():
    """Sibling test: when ``track_per_cell=True`` (test/diagnostic
    opt-in), small in-ring revisions on held names' close/open take
    the per-cell coverage path and stay flagged_only — proving the
    Blocker-2 fail-close is gated on the empty-digest condition, not
    on signal_input scope diffs in general.
    """
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] *= 1.0005

    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="TD003",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    assert ev.policy_decision == "flagged_only"
    assert summary.requires_data_review is False


# ── R2 / A2 adversarial regression suite (codex did NOT cover) ────


def test_revalidate_thread_safe_concurrent_calls():
    """A2 adversarial S11: revalidate_manifest is pure-functional and
    must be safe to call from concurrent threads against independent
    manifests (or even the same manifest, since it does not mutate).
    """
    import threading
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    out_a, out_b = [], []
    def _t1():
        out_a.append(revalidate_manifest(
            manifest, spec=spec, universe=universe, panel=panel,
            benchmark_symbols=benchmarks, detected_by_run_label="A",
        ))
    def _t2():
        out_b.append(revalidate_manifest(
            manifest, spec=spec, universe=universe, panel=panel,
            benchmark_symbols=benchmarks, detected_by_run_label="B",
        ))
    t1, t2 = threading.Thread(target=_t1), threading.Thread(target=_t2)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert len(out_a[0].events) == 0
    assert len(out_b[0].events) == 0


def test_revalidate_does_not_mutate_input_manifest():
    """A2 adversarial S08: revalidate_manifest is non-mutating. Caller
    is responsible for persisting events on entries. Verifies the
    contract by checking object identity + data_revision_event field
    on the input manifest before vs after.
    """
    spec, universe, held, _w, benchmarks, panel, manifest = _common_setup()
    panel_b = {k: v.copy() for k, v in panel.items()}
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] *= 1.0005
    pre_runs = list(manifest.runs)
    pre_event = manifest.runs[0].data_revision_event
    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="S08",
    )
    assert manifest.runs[0].data_revision_event == pre_event   # untouched
    assert manifest.runs == pre_runs                            # identity preserved
    assert len(summary.events) == 1                             # event in summary, not on manifest


def test_revalidate_zero_weight_held_revision_invalidates():
    """A2 adversarial S07: a held symbol with weight=0 is still in the
    execution_nav scope (must be tracked because it could be sized up
    later), but its NAV impact is 0 by construction. A 0.6% close
    revision on a 0-weight position must still fire E5 (raw drift
    >= 0.50%) → invalidated. Without E5 the revision would silently
    pass since E1 NAV impact = 0.
    """
    spec = _spec()
    universe = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"]
    held = ["AAPL", "MSFT", "TSLA"]
    weights = {"AAPL": 0.5, "MSFT": 0.5, "TSLA": 0.0}
    benchmarks = ["SPY", "QQQ"]
    panel_a = _panel(universe + ["QQQ"], "2026-01-02", "2026-04-30", seed=0)
    start_date = date(2026, 4, 24)
    as_of = date(2026, 4, 27)
    entry = _build_v2_td_entry(
        panel=panel_a, spec=spec, universe=universe, held=held,
        weights=weights, benchmark_symbols=benchmarks,
        start_date=start_date, as_of_date=as_of,
        track_signal_per_cell=True,   # exercise the cell-level path
    )
    manifest = _wrap_manifest(entry, start_date=start_date)
    panel_b = {k: v.copy() for k, v in panel_a.items()}
    panel_b["close"].loc[pd.Timestamp("2026-04-24"), "TSLA"] *= 1.006
    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel_b,
        benchmark_symbols=benchmarks, detected_by_run_label="S07",
    )
    assert len(summary.events) == 1
    _entry, ev = summary.events[0]
    # NAV impact = 0 because TSLA weight = 0
    assert ev.estimated_nav_impact_bps == 0.0
    # raw drift 0.6% >= 0.5% threshold → E5 fires → invalidated
    assert ev.raw_max_close_drift_pct >= RAW_DRIFT_PCT_THRESHOLD
    assert ev.policy_decision == "invalidated"


def test_revalidate_backward_window_deterministic():
    """A2 adversarial S15: as_of < start_date should not crash. The
    panel slice is empty → '|empty|' sentinel → deterministic hash.
    Robustness guarantee.
    """
    panel = _panel(["AAPL", "MSFT"], "2026-04-20", "2026-04-30")
    backward_start = date(2026, 4, 27)
    backward_end = date(2026, 4, 24)
    h1, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL", "MSFT"], panel=panel,
        start_date=backward_start, as_of_date=backward_end,
    )
    h2, _ = compute_execution_nav_hash(
        held_or_traded_symbols=["AAPL", "MSFT"], panel=panel,
        start_date=backward_start, as_of_date=backward_end,
    )
    assert h1 == h2
    assert len(h1) == 24
