"""Round 1 (A1) — forward evidence module audit live e2e scenarios.

Runs the 4 scenarios PRD §4 R1 prescribes against REAL data/daily/*
panel + non-mutating synthetic v2.1 manifest:

  S1: clean revalidate (no revisions expected -> 0 events)
  S2: sub-threshold revision with populated per_cell_digest -> flagged_only
  S3: true 252nd prior trading-day revision (Blocker-1 verification)
  S4: empty-digest + dual-scope diff -> invalidated (Blocker-2 verification)

Plus reverse-validation of v2.1.3 fixes:

  RV1: revert Blocker-1 fix -> verify true 252nd revision misses hash
  RV2: revert Blocker-2 fix -> verify dual-scope diff under-classifies
       as flagged_only

Output: verbatim stdout for the round memo.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

import pandas as pd

# Real-data panel from BarStore (PRD §3.3 — no bdate_range)
from core.data.bar_store import BarStore
from core.research.forward.bar_hash import (
    DEFAULT_BAR_REVISION,
    _resolve_lookback_window_start,
    compute_benchmark_hash,
    compute_execution_nav_hash,
    compute_signal_input_hash,
)
from core.research.forward.manifest_schema import (
    BarHashInputs,
    CheckpointCadence,
    CostAssumptions,
    DataIntegritySnapshot,
    EvidenceClass,
    ForwardRun,
    ForwardRunManifest,
    ForwardRunStatus,
    SourceLayerBreakdown,
    SourceLayerView,
)
from core.research.forward.revalidate import (
    NAV_IMPACT_BPS_THRESHOLD,
    revalidate_manifest,
)
from core.research.frozen_spec import FrozenStrategySpec


def _line(msg: str) -> None:
    print(msg, flush=True)


def _build_panel(symbols: list[str], end: str = "2026-04-27") -> dict:
    """Real BarStore panel — production semantics."""
    store = BarStore()
    end_ts = pd.Timestamp(end)
    panels: dict = {}
    for attr in ("close", "open", "high", "low", "volume"):
        cols = {}
        for sym in symbols:
            try:
                df = store.load(sym, freq="daily", adjusted=True).sort_index()
            except Exception as e:
                _line(f"  [warn] BarStore.load({sym}) failed: {e}")
                continue
            df = df[df.index <= end_ts]
            if attr in df.columns:
                cols[sym] = df[attr]
        if cols:
            panels[attr] = pd.concat(cols, axis=1)
    return panels


def _build_v2_entry(
    *,
    spec: FrozenStrategySpec,
    universe: list[str],
    held: list[str],
    weights: dict,
    benchmark_symbols: list[str],
    panel: dict,
    start_date: date,
    as_of_date: date,
    track_signal_per_cell: bool = False,
    cum_ret: float = 0.001,
) -> ForwardRun:
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
        bar_hash=sig_h[:8] + exec_h[:8] + bench_h[:8],
        bar_hash_inputs=BarHashInputs(
            signal_input=sig_in,
            execution_nav=exec_in,
            benchmark=bench_in,
        ),
        source_layer_breakdown=SourceLayerBreakdown(
            as_of_held_source=SourceLayerView(),
            window_input_source=SourceLayerView(),
        ),
        held_today_weights=weights,
    )


def _wrap_manifest(entry: ForwardRun, start_date: date) -> ForwardRunManifest:
    return ForwardRunManifest(
        candidate_id="rcm_v1_audit_synth",
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


def main():
    _line("=" * 78)
    _line("R1 / A1 — forward evidence module audit (live e2e)")
    _line("=" * 78)

    # ── shared setup ──
    spec = FrozenStrategySpec.from_yaml_file(
        "data/research_candidates/rcm_v1_defensive_composite_01.yaml"
    )
    universe = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"]
    held = ["AAPL", "MSFT"]
    weights = {"AAPL": 0.5, "MSFT": 0.5}
    benchmarks = ["SPY", "QQQ"]
    start_date = date(2026, 4, 24)
    as_of = date(2026, 4, 27)

    panel = _build_panel(universe + ["QQQ"], end="2026-04-27")
    if not panel or "close" not in panel:
        _line("ABORT: real panel unavailable")
        sys.exit(1)

    n_close_rows = len(panel["close"].index[panel["close"].index <= pd.Timestamp(as_of)])
    _line(f"panel: {len(panel)} attrs, {n_close_rows} close rows ≤ {as_of}")

    # ── S1: clean revalidate ──
    _line("")
    _line("─" * 60)
    _line("S1 — clean revalidate: no revisions, expect 0 events")
    _line("─" * 60)
    entry = _build_v2_entry(
        spec=spec, universe=universe, held=held, weights=weights,
        benchmark_symbols=benchmarks, panel=panel,
        start_date=start_date, as_of_date=as_of,
    )
    manifest = _wrap_manifest(entry, start_date)
    summary = revalidate_manifest(
        manifest, spec=spec, universe=universe, panel=panel,
        benchmark_symbols=benchmarks, detected_by_run_label="audit-S1",
    )
    _line(f"  events: {len(summary.events)}")
    _line(f"  n_runs_checked: {summary.n_runs_checked}")
    _line(f"  requires_data_review: {summary.requires_data_review}")
    s1_pass = (len(summary.events) == 0
               and summary.n_runs_checked == 1
               and not summary.requires_data_review)
    _line(f"  PASS: {s1_pass}")

    # ── S2: sub-threshold revision with populated digest -> flagged_only ──
    _line("")
    _line("─" * 60)
    _line("S2 — sub-threshold held in-ring revision (track_per_cell=True)")
    _line("     expect flagged_only (NAV impact < 10 bps via populated digest)")
    _line("─" * 60)
    entry_tracked = _build_v2_entry(
        spec=spec, universe=universe, held=held, weights=weights,
        benchmark_symbols=benchmarks, panel=panel,
        start_date=start_date, as_of_date=as_of,
        track_signal_per_cell=True,
    )
    manifest_tracked = _wrap_manifest(entry_tracked, start_date)
    panel_s2 = {k: v.copy() for k, v in panel.items()}
    # 0.05% AAPL close revision on start_date — held, in-ring, anchored
    pre = float(panel["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"])
    panel_s2["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] = pre * 1.0005
    summary_s2 = revalidate_manifest(
        manifest_tracked, spec=spec, universe=universe, panel=panel_s2,
        benchmark_symbols=benchmarks, detected_by_run_label="audit-S2",
    )
    if summary_s2.events:
        _, ev_s2 = summary_s2.events[0]
        _line(f"  policy_decision: {ev_s2.policy_decision}")
        _line(f"  estimated_nav_impact_bps: {ev_s2.estimated_nav_impact_bps}")
        _line(f"  affected_scopes: {ev_s2.affected_scopes}")
        _line(f"  delta_summary: {ev_s2.delta_summary[:120]}")
    s2_pass = (len(summary_s2.events) == 1
               and summary_s2.events[0][1].policy_decision == "flagged_only"
               and not summary_s2.requires_data_review)
    _line(f"  PASS: {s2_pass}")

    # ── S3: true 252nd prior trading-day revision (Blocker-1) ──
    _line("")
    _line("─" * 60)
    _line("S3 — Blocker-1: revise TRUE 252nd prior trading day")
    _line("     pre-v2.1.3 BDay window misses this row by ~9 trading days")
    _line("     expect: signal_input_hash flips, summary detects diff")
    _line("─" * 60)
    valid = panel["close"].index[panel["close"].index <= pd.Timestamp(as_of)]
    if len(valid) >= 252:
        true_252nd = valid[-252].date()
        bday_252 = (pd.Timestamp(as_of) - pd.tseries.offsets.BDay(252)).date()
        _line(f"  true 252nd prior: {true_252nd}")
        _line(f"  BDay(252) start:  {bday_252}  (gap = {(pd.Timestamp(bday_252) - pd.Timestamp(true_252nd)).days} days)")
        # Use a v2 entry (default empty digest) so this validates the
        # production hashing path, not just the test path.
        entry_s3 = _build_v2_entry(
            spec=spec, universe=universe, held=held, weights=weights,
            benchmark_symbols=benchmarks, panel=panel,
            start_date=start_date, as_of_date=as_of,
        )
        manifest_s3 = _wrap_manifest(entry_s3, start_date)
        # Mutate AAPL close on the true 252nd prior trading day — this
        # cell is OUTSIDE BDay(252) but INSIDE the v2.1.3 trading-day
        # window (post-Blocker-1).
        panel_s3 = {k: v.copy() for k, v in panel.items()}
        ts = pd.Timestamp(true_252nd)
        pre_s3 = float(panel["close"].loc[ts, "AAPL"])
        panel_s3["close"].loc[ts, "AAPL"] = pre_s3 + 1.0
        summary_s3 = revalidate_manifest(
            manifest_s3, spec=spec, universe=universe, panel=panel_s3,
            benchmark_symbols=benchmarks, detected_by_run_label="audit-S3",
        )
        _line(f"  events: {len(summary_s3.events)}")
        if summary_s3.events:
            _, ev_s3 = summary_s3.events[0]
            _line(f"  affected_scopes: {ev_s3.affected_scopes}")
            _line(f"  policy_decision: {ev_s3.policy_decision}")
        s3_pass = (len(summary_s3.events) == 1
                   and "signal_input" in summary_s3.events[0][1].affected_scopes)
        _line(f"  PASS: {s3_pass}")
    else:
        _line(f"  SKIP: only {len(valid)} trading rows ≤ as_of (need ≥252)")
        s3_pass = None

    # ── S4: empty-digest + dual-scope diff (Blocker-2) ──
    _line("")
    _line("─" * 60)
    _line("S4 — Blocker-2: empty signal_input.per_cell_digest +")
    _line("     dual-scope (signal+exec_nav) diff -> invalidated (bound_only)")
    _line("─" * 60)
    entry_s4 = _build_v2_entry(
        spec=spec, universe=universe, held=held, weights=weights,
        benchmark_symbols=benchmarks, panel=panel,
        start_date=start_date, as_of_date=as_of,
        track_signal_per_cell=False,
    )
    assert entry_s4.bar_hash_inputs.signal_input.per_cell_digest == {}, "setup invariant"
    manifest_s4 = _wrap_manifest(entry_s4, start_date)
    panel_s4 = {k: v.copy() for k, v in panel.items()}
    # Same 0.05% AAPL revision as S2, but production-default empty digest
    pre_s4 = float(panel["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"])
    panel_s4["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] = pre_s4 * 1.0005
    summary_s4 = revalidate_manifest(
        manifest_s4, spec=spec, universe=universe, panel=panel_s4,
        benchmark_symbols=benchmarks, detected_by_run_label="audit-S4",
    )
    if summary_s4.events:
        _, ev_s4 = summary_s4.events[0]
        _line(f"  policy_decision: {ev_s4.policy_decision}")
        _line(f"  estimated_nav_impact_bps: {ev_s4.estimated_nav_impact_bps}")
        _line(f"  affected_scopes: {ev_s4.affected_scopes}")
        _line(f"  bound_only triggered: {'bound_only' in ev_s4.delta_summary}")
        _line(f"  empty per_cell_digest mention: {'empty per_cell_digest' in ev_s4.delta_summary}")
    s4_pass = (
        len(summary_s4.events) == 1
        and summary_s4.events[0][1].policy_decision == "invalidated"
        and summary_s4.events[0][1].estimated_nav_impact_bps is None
        and "bound_only" in summary_s4.events[0][1].delta_summary
        and "empty per_cell_digest" in summary_s4.events[0][1].delta_summary
        and summary_s4.requires_data_review is True
    )
    _line(f"  PASS: {s4_pass}")

    # ── reverse-validation RV1: revert Blocker-1 fix ──
    _line("")
    _line("=" * 78)
    _line("RV1 — Blocker-1 reverse-validation: monkey-patch BDay back")
    _line("=" * 78)
    import core.research.forward.bar_hash as bh
    orig_resolver = bh._resolve_lookback_window_start
    def buggy_resolver(panel_, as_of_, lookback):
        return (pd.Timestamp(as_of_) - pd.tseries.offsets.BDay(lookback)).date()
    bh._resolve_lookback_window_start = buggy_resolver
    try:
        if len(valid) >= 252:
            true_252nd = valid[-252].date()
            ts = pd.Timestamp(true_252nd)
            pre_rv1 = float(panel["close"].loc[ts, "AAPL"])
            h_pre, _ = compute_signal_input_hash(
                spec=spec, universe=universe, panel=panel, as_of_date=as_of,
            )
            panel_rv1 = {k: v.copy() for k, v in panel.items()}
            panel_rv1["close"].loc[ts, "AAPL"] = pre_rv1 + 1.0
            h_post, _ = compute_signal_input_hash(
                spec=spec, universe=universe, panel=panel_rv1, as_of_date=as_of,
            )
            collision = (h_pre == h_post)
            _line(f"  buggy BDay logic, mutate AAPL/{true_252nd}/close:")
            _line(f"    h_pre  = {h_pre}")
            _line(f"    h_post = {h_post}")
            _line(f"  hash collision (bug present): {collision}")
            rv1_pass = collision  # bug must reproduce under buggy logic
            _line(f"  RV1 PASS: {rv1_pass}")
        else:
            rv1_pass = None
    finally:
        bh._resolve_lookback_window_start = orig_resolver

    # confirm fix re-applied: hash now flips
    if len(valid) >= 252 and rv1_pass:
        h_pre_fix, _ = compute_signal_input_hash(
            spec=spec, universe=universe, panel=panel, as_of_date=as_of,
        )
        panel_rv1 = {k: v.copy() for k, v in panel.items()}
        ts = pd.Timestamp(valid[-252].date())
        panel_rv1["close"].loc[ts, "AAPL"] = float(panel["close"].loc[ts, "AAPL"]) + 1.0
        h_post_fix, _ = compute_signal_input_hash(
            spec=spec, universe=universe, panel=panel_rv1, as_of_date=as_of,
        )
        flips = (h_pre_fix != h_post_fix)
        _line(f"  fix re-applied, hash flips on revision: {flips}")
        rv1_close = flips
        _line(f"  RV1 close: {rv1_close}")

    # ── reverse-validation RV2: revert Blocker-2 fix ──
    _line("")
    _line("=" * 78)
    _line("RV2 — Blocker-2 reverse-validation: monkey-patch revalidate's")
    _line("       empty-digest path back to optimistic gating on exec_nav")
    _line("=" * 78)
    import core.research.forward.revalidate as rev
    orig_revalidate_entry = rev._revalidate_entry

    # Build a buggy version: when sig_diffs is empty AND exec_nav also
    # differs, do NOT set bound_only_reason. This is the pre-Blocker-2
    # behavior.
    def buggy_revalidate_entry(*, entry, spec, universe, panel, start_date,
                                benchmark_symbols, detected_by_run_label,
                                bar_revision):
        # Inline the original logic but substitute the empty-digest path
        # with the pre-fix optimistic gating.
        from datetime import datetime, timezone
        from core.research.forward.bar_hash import (
            compute_signal_input_hash as csi,
            compute_execution_nav_hash as cen,
            compute_benchmark_hash as cbh,
        )
        from core.research.forward.manifest_schema import DataRevisionEvent
        from core.research.forward.revalidate import (
            _diff_cells, _drift_pct, _bench_old_new_path,
            NAV_IMPACT_BPS_THRESHOLD, CHECKPOINT_DRIFT_BPS_THRESHOLD,
            RAW_DRIFT_PCT_THRESHOLD, _BPS_EPS, _PCT_EPS,
        )
        if entry.legacy_unhashed_inputs:
            return None
        if (entry.signal_input_hash is None or entry.execution_nav_hash is None
                or entry.benchmark_hash is None or entry.bar_hash_inputs is None):
            return None

        affected_scopes_set = set()
        revised_cells = []

        stored_sig_digest = entry.bar_hash_inputs.signal_input.per_cell_digest
        track_signal_per_cell = bool(stored_sig_digest)
        sig_hash, sig_inputs = csi(
            spec=spec, universe=universe, panel=panel,
            as_of_date=entry.as_of_date, bar_revision=bar_revision,
            track_per_cell=track_signal_per_cell,
        )
        if sig_hash != entry.signal_input_hash:
            affected_scopes_set.add("signal_input")
            diffs = _diff_cells(stored_sig_digest, sig_inputs.per_cell_digest)
            revised_cells.extend(("signal_input/" + s, d, a) for (s, d, a) in diffs)

        held_or_traded = list(entry.bar_hash_inputs.execution_nav.symbols)
        exec_hash, exec_inputs = cen(
            held_or_traded_symbols=held_or_traded, panel=panel,
            start_date=start_date, as_of_date=entry.as_of_date,
            bar_revision=bar_revision,
        )
        if exec_hash != entry.execution_nav_hash:
            affected_scopes_set.add("execution_nav")
            diffs = _diff_cells(
                entry.bar_hash_inputs.execution_nav.per_cell_digest,
                exec_inputs.per_cell_digest,
            )
            revised_cells.extend(("execution_nav/" + s, d, a) for (s, d, a) in diffs)

        bench_hash, bench_inputs = cbh(
            benchmark_symbols=benchmark_symbols, panel=panel,
            start_date=start_date, as_of_date=entry.as_of_date,
            bar_revision=bar_revision,
        )
        if bench_hash != entry.benchmark_hash:
            affected_scopes_set.add("benchmark")

        if not affected_scopes_set:
            return None

        nav_impact_bps = 0.0
        raw_max_drift = 0.0
        bound_only_reason = None
        held_today_weights = entry.held_today_weights or {}
        exec_anchors = entry.bar_hash_inputs.execution_nav.materiality_anchor_values or {}

        if "execution_nav" in affected_scopes_set:
            exec_diffs = _diff_cells(
                entry.bar_hash_inputs.execution_nav.per_cell_digest,
                exec_inputs.per_cell_digest,
            )
            for sym, iso, attr in exec_diffs:
                if attr not in ("close", "open"):
                    bound_only_reason = f"non-anchored attribute {attr!r}"
                    continue
                sym_anchor = exec_anchors.get(sym, {})
                old_val = sym_anchor.get(iso, {}).get(attr)
                new_panel = panel.get(attr)
                new_val = None
                if new_panel is not None and sym in new_panel.columns:
                    ts2 = pd.Timestamp(iso)
                    if ts2 in new_panel.index:
                        v = new_panel.loc[ts2, sym]
                        if not pd.isna(v):
                            new_val = float(v)
                if old_val is None:
                    bound_only_reason = "out-of-ring"
                    continue
                d_pct = _drift_pct(old_val, new_val)
                if d_pct is None:
                    bound_only_reason = "undefined drift"
                    continue
                raw_max_drift = max(raw_max_drift, d_pct)
                w = float(held_today_weights.get(sym, 0.0))
                nav_impact_bps += abs(w) * d_pct * 10000.0

        # ── BUGGY pre-Blocker-2 logic: empty-digest only fail-closes ──
        # ── when execution_nav scope did NOT also differ.            ──
        if "signal_input" in affected_scopes_set:
            sig_diffs = _diff_cells(
                entry.bar_hash_inputs.signal_input.per_cell_digest,
                sig_inputs.per_cell_digest,
            )
            if not sig_diffs:
                # PRE-FIX: only fail-close when exec_nav not affected
                if "execution_nav" not in affected_scopes_set:
                    bound_only_reason = bound_only_reason or "signal-only"

        invalidate = False
        triggers = []
        if bound_only_reason is not None:
            invalidate = True
            triggers.append(f"bound_only ({bound_only_reason})")
        if nav_impact_bps >= NAV_IMPACT_BPS_THRESHOLD - _BPS_EPS:
            invalidate = True
        if raw_max_drift >= RAW_DRIFT_PCT_THRESHOLD - _PCT_EPS:
            invalidate = True

        revised_symbols = sorted({s.split("/", 1)[1] for (s, _, _) in revised_cells})
        affected_scopes = sorted(affected_scopes_set)
        return DataRevisionEvent(
            detected_at_utc=datetime.now(timezone.utc),
            revised_symbols=revised_symbols,
            detected_by_run_label=detected_by_run_label,
            delta_summary=f"BUGGY scopes={affected_scopes} bound_only={bound_only_reason} triggers={triggers}",
            estimated_nav_impact_bps=(None if bound_only_reason else round(nav_impact_bps, 4)),
            decision_sign_flip=False,
            raw_max_close_drift_pct=(None if raw_max_drift == 0 else round(raw_max_drift, 6)),
            affected_scopes=affected_scopes,
            policy_decision=("invalidated" if invalidate else "flagged_only"),
        )

    rev._revalidate_entry = buggy_revalidate_entry
    try:
        # Reproduce S4 with the buggy logic
        entry_rv2 = _build_v2_entry(
            spec=spec, universe=universe, held=held, weights=weights,
            benchmark_symbols=benchmarks, panel=panel,
            start_date=start_date, as_of_date=as_of,
            track_signal_per_cell=False,
        )
        manifest_rv2 = _wrap_manifest(entry_rv2, start_date)
        panel_rv2 = {k: v.copy() for k, v in panel.items()}
        pre_rv2 = float(panel["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"])
        panel_rv2["close"].loc[pd.Timestamp("2026-04-24"), "AAPL"] = pre_rv2 * 1.0005
        summary_rv2 = revalidate_manifest(
            manifest_rv2, spec=spec, universe=universe, panel=panel_rv2,
            benchmark_symbols=benchmarks, detected_by_run_label="audit-RV2",
        )
        if summary_rv2.events:
            _, ev_rv2 = summary_rv2.events[0]
            _line(f"  buggy logic policy_decision: {ev_rv2.policy_decision}")
            _line(f"  buggy logic NAV impact bps: {ev_rv2.estimated_nav_impact_bps}")
            # Pre-fix: 0.05% AAPL × 0.5 weight = 2.5 bps NAV impact, below
            # 10 bps threshold AND no bound_only fires (because exec_nav
            # also differs and empty-digest gate skipped) -> flagged_only.
            rv2_pass = (
                ev_rv2.policy_decision == "flagged_only"
                and not summary_rv2.requires_data_review
            )
            _line(f"  pre-fix UNDER-classified as flagged_only: {rv2_pass}")
        else:
            rv2_pass = False
        _line(f"  RV2 PASS: {rv2_pass}")
    finally:
        rev._revalidate_entry = orig_revalidate_entry

    # confirm fix re-applied: same revision → invalidated
    summary_rv2_post = revalidate_manifest(
        manifest_rv2, spec=spec, universe=universe, panel=panel_rv2,
        benchmark_symbols=benchmarks, detected_by_run_label="audit-RV2-post",
    )
    if summary_rv2_post.events:
        post_decision = summary_rv2_post.events[0][1].policy_decision
        rv2_close = (post_decision == "invalidated")
        _line(f"  fix re-applied, same revision -> {post_decision}")
        _line(f"  RV2 close: {rv2_close}")

    # ── final summary ──
    _line("")
    _line("=" * 78)
    _line("R1 / A1 final summary")
    _line("=" * 78)
    results = {
        "S1 clean": s1_pass,
        "S2 sub-threshold flagged_only": s2_pass,
        "S3 Blocker-1 252nd-prior detect": s3_pass,
        "S4 Blocker-2 dual-scope invalidated": s4_pass,
        "RV1 Blocker-1 reverse-validate": rv1_pass,
        "RV2 Blocker-2 reverse-validate": rv2_pass,
    }
    for k, v in results.items():
        sym = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
        _line(f"  {sym}: {k}")
    all_passed = all(v is True for v in results.values() if v is not None)
    _line("")
    _line(f"OVERALL: {'PASS' if all_passed else 'FAIL'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
