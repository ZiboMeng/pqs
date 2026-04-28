"""Forward-evidence revalidation pass (PRD v2.1 §4.6 + §4.4).

Recomputes the three v2.1 input-scope hashes for every prior TD entry
(except those marked ``legacy_unhashed_inputs=True``) and compares
each to the stored value. Mismatches:

  1. Identify revised cells via per_cell_digest diff.
  2. Reconstruct old close + open numerics from
     ``materiality_anchor_values`` for the recent ring; for revisions
     landing outside the ring, fall back to ``bound_only`` materiality
     per §4.4.
  3. Compute ``estimated_nav_impact_bps`` /
     ``estimated_cum_ret_drift_bps`` / ``estimated_vs_spy_drift_bps`` /
     ``estimated_vs_qqq_drift_bps`` and the ``decision_sign_flip`` flag.
  4. Apply the §4.4 E1-E5 escalation rule table to choose
     ``policy_decision`` (``flagged_only`` vs ``invalidated``).

Mismatches return as ``DataRevisionEvent`` instances; the caller
persists them on the corresponding TD entries (mutating only the
``data_revision_event`` slot, never the historical numeric fields).

This module is import-light so it can be invoked from ``observe()``
at the end of each successful append without dragging in heavy
optional dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from .bar_hash import (
    DEFAULT_BAR_REVISION,
    _capture_anchor_values,
    _hash_panel,
    _merge_cell_digests,
    compute_benchmark_hash,
    compute_execution_nav_hash,
    compute_signal_input_hash,
)
from .manifest_schema import (
    DataRevisionEvent,
    ForwardRun,
    ForwardRunManifest,
    PerScopeHashInputs,
)


# ── materiality thresholds (PRD §4.4 E1-E5) ────────────────────────


# E1: per-TD NAV impact threshold (bps).
NAV_IMPACT_BPS_THRESHOLD = 10.0
# E2/E3: checkpoint metric drift threshold (bps).
CHECKPOINT_DRIFT_BPS_THRESHOLD = 25.0
# E5: raw close/open drift secondary guard (fraction).
RAW_DRIFT_PCT_THRESHOLD = 0.005   # = 0.50%

# Float-precision tolerance for boundary comparisons. yfinance-style
# revisions are typically expressed as multiplicative scalars (e.g.
# ``*= 1.005`` for +0.5%) which yield drift values like
# 0.004999999... after binary float arithmetic. Using strict ``>=``
# would silently miss boundary cases that the user clearly intended
# to fire. Tolerances below are absolute, conservative, and several
# orders of magnitude smaller than any decision-relevant precision.
_BPS_EPS = 1e-6     # 1e-6 bps is far below any decision-relevant bps
_PCT_EPS = 1e-9     # 1 ulp at the 0.5% scale


# ── public dataclass for revalidation summary ──────────────────────


@dataclass(frozen=True)
class RevalidationSummary:
    """Aggregate outcome of a revalidate pass over one manifest."""

    candidate_id: str
    n_runs_checked: int
    n_legacy_skipped: int
    n_no_hash_skipped: int   # entries that lack v2.1 hashes (shouldn't happen post-step-5)
    events: list  # list[DataRevisionEvent]
    requires_data_review: bool


# ── revision detection helpers ─────────────────────────────────────


def _diff_cells(stored: dict, current: dict) -> list[tuple[str, str, str]]:
    """Return list of (sym, iso_date, attr) cells whose digest differs.

    A cell present in one side and absent in the other counts as
    revised — that's a structural revision (sym/date/attr appeared or
    disappeared) which is also material.
    """
    out: list[tuple[str, str, str]] = []
    syms = set(stored.keys()) | set(current.keys())
    for sym in syms:
        s_dates = stored.get(sym, {})
        c_dates = current.get(sym, {})
        all_dates = set(s_dates.keys()) | set(c_dates.keys())
        for iso in all_dates:
            s_attrs = s_dates.get(iso, {})
            c_attrs = c_dates.get(iso, {})
            attrs = set(s_attrs.keys()) | set(c_attrs.keys())
            for attr in attrs:
                if s_attrs.get(attr) != c_attrs.get(attr):
                    out.append((sym, iso, attr))
    return out


def _drift_pct(old: Optional[float], new: Optional[float]) -> Optional[float]:
    """Return |new - old| / |old| as a fraction; None if either side
    is None or old is zero."""
    if old is None or new is None:
        return None
    if old == 0:
        return None
    return abs(new - old) / abs(old)


def _signed_drift(old: Optional[float], new: Optional[float]) -> Optional[float]:
    """Signed drift (new - old) / old; None on zero/None."""
    if old is None or new is None:
        return None
    if old == 0:
        return None
    return (new - old) / old


def _bench_old_new_path(
    *,
    bench_anchors: dict,
    panel_close: pd.DataFrame,
    sym: str,
    start_date: date,
    as_of_date: date,
) -> tuple[Optional[float], Optional[float]]:
    """Reconstruct the old vs new cumulative-return path for one
    benchmark symbol over [start_date..as_of_date].

    Returns (old_cum_ret, new_cum_ret); either may be None if data is
    missing (insufficient anchor depth or sym absent from panel).
    """
    # New cum_ret from current panel
    if sym not in panel_close.columns:
        return None, None
    series = panel_close[sym]
    series = series[(series.index >= pd.Timestamp(start_date))
                    & (series.index <= pd.Timestamp(as_of_date))].dropna()
    if len(series) < 2:
        return None, None
    new_cum = float(series.iloc[-1] / series.iloc[0] - 1.0)

    # Old cum_ret using anchor close at start_date and at as_of_date.
    sym_anchor = bench_anchors.get(sym, {})
    s_iso = start_date.isoformat()
    e_iso = as_of_date.isoformat()
    old_start = sym_anchor.get(s_iso, {}).get("close")
    old_end   = sym_anchor.get(e_iso, {}).get("close")
    if old_start is None or old_end is None or old_start == 0:
        return None, new_cum
    old_cum = float(old_end / old_start - 1.0)
    return old_cum, new_cum


# ── per-entry revalidation ─────────────────────────────────────────


def _revalidate_entry(
    *,
    entry: ForwardRun,
    spec,                   # FrozenStrategySpec
    universe: list[str],
    panel: dict,            # current store: {close, open, high, low, volume} → DataFrame
    start_date: date,
    benchmark_symbols: list[str],
    detected_by_run_label: str,
    bar_revision: str,
) -> Optional[DataRevisionEvent]:
    """Recompute the three input-scope hashes for ``entry`` against
    the current panel and return a DataRevisionEvent if any differ.

    Returns None on no-divergence or when the entry is legacy /
    lacks stored hashes (callers handle skip accounting separately).
    """
    if entry.legacy_unhashed_inputs:
        return None
    if (entry.signal_input_hash is None
            or entry.execution_nav_hash is None
            or entry.benchmark_hash is None
            or entry.bar_hash_inputs is None):
        return None

    affected: list[str] = []
    revised_cells: list[tuple[str, str, str]] = []
    affected_scopes_set: set[str] = set()

    # ── recompute signal_input ──────────────────────────────────
    # Recompute with the SAME track_per_cell setting the entry was
    # hashed under: if the stored per_cell_digest is non-empty, the
    # entry was built with track_per_cell=True and the cell-level diff
    # path is meaningful; otherwise the empty-digest fail-closed path
    # in the materiality block runs. Mismatching this would produce
    # spurious "all stored cells differ" diffs.
    stored_sig_digest = entry.bar_hash_inputs.signal_input.per_cell_digest
    track_signal_per_cell = bool(stored_sig_digest)
    sig_hash, sig_inputs = compute_signal_input_hash(
        spec=spec, universe=universe, panel=panel,
        as_of_date=entry.as_of_date, bar_revision=bar_revision,
        track_per_cell=track_signal_per_cell,
    )
    if sig_hash != entry.signal_input_hash:
        affected_scopes_set.add("signal_input")
        diffs = _diff_cells(
            stored_sig_digest,
            sig_inputs.per_cell_digest,
        )
        revised_cells.extend(("signal_input/" + s, d, a) for (s, d, a) in diffs)

    # ── recompute execution_nav ─────────────────────────────────
    held_or_traded = list(entry.bar_hash_inputs.execution_nav.symbols)
    exec_hash, exec_inputs = compute_execution_nav_hash(
        held_or_traded_symbols=held_or_traded,
        panel=panel,
        start_date=start_date,
        as_of_date=entry.as_of_date,
        bar_revision=bar_revision,
    )
    if exec_hash != entry.execution_nav_hash:
        affected_scopes_set.add("execution_nav")
        diffs = _diff_cells(
            entry.bar_hash_inputs.execution_nav.per_cell_digest,
            exec_inputs.per_cell_digest,
        )
        revised_cells.extend(("execution_nav/" + s, d, a) for (s, d, a) in diffs)

    # ── recompute benchmark ─────────────────────────────────────
    bench_hash, bench_inputs = compute_benchmark_hash(
        benchmark_symbols=benchmark_symbols,
        panel=panel,
        start_date=start_date,
        as_of_date=entry.as_of_date,
        bar_revision=bar_revision,
    )
    if bench_hash != entry.benchmark_hash:
        affected_scopes_set.add("benchmark")
        diffs = _diff_cells(
            entry.bar_hash_inputs.benchmark.per_cell_digest,
            bench_inputs.per_cell_digest,
        )
        revised_cells.extend(("benchmark/" + s, d, a) for (s, d, a) in diffs)

    if not affected_scopes_set:
        return None  # all three hashes match — clean

    # ── compute materiality (PRD §4.4) ──────────────────────────
    nav_impact_bps = 0.0
    raw_max_drift = 0.0
    bound_only_reason: Optional[str] = None
    materiality_estimate_class = "in_ring"   # informational

    held_today_weights: dict = entry.held_today_weights or {}
    exec_anchors: dict = entry.bar_hash_inputs.execution_nav.materiality_anchor_values or {}

    # E1 / E2: weighted NAV impact from execution_nav cell revisions
    # in the held set inside the 10-day ring (only close + open
    # attributes are anchored; high/low/volume are not — fail-closed).
    if "execution_nav" in affected_scopes_set:
        exec_diffs = _diff_cells(
            entry.bar_hash_inputs.execution_nav.per_cell_digest,
            exec_inputs.per_cell_digest,
        )
        for sym, iso, attr in exec_diffs:
            if attr not in ("close", "open"):
                bound_only_reason = (
                    f"non-anchored attribute {attr!r} revised on {sym}/{iso}"
                )
                continue
            sym_anchor = exec_anchors.get(sym, {})
            old_val = sym_anchor.get(iso, {}).get(attr)
            new_panel = panel.get(attr)
            new_val = None
            if new_panel is not None and sym in new_panel.columns:
                ts = pd.Timestamp(iso)
                if ts in new_panel.index:
                    v = new_panel.loc[ts, sym]
                    if not pd.isna(v):
                        new_val = float(v)
            if old_val is None:
                bound_only_reason = (
                    f"out-of-ring revision on {sym}/{iso}/{attr} (no anchor)"
                )
                continue
            d_pct = _drift_pct(old_val, new_val)
            if d_pct is None:
                bound_only_reason = (
                    f"undefined drift on {sym}/{iso}/{attr}"
                )
                continue
            raw_max_drift = max(raw_max_drift, d_pct)
            # Use as-of held weight as proxy for that-date weight (PRD
            # accepts close-recent-window approximation).
            w = float(held_today_weights.get(sym, 0.0))
            nav_impact_bps += abs(w) * d_pct * 10000.0

    # signal_input scope revisions (PRD §4.4 coverage matrix):
    #
    # Default config (track_per_cell=False on signal_input) produces an
    # empty per_cell_digest because storing the full 79×252×2 grid
    # would balloon the manifest. **codex Round-10 Blocker 2 fix**:
    # without per-cell attribution we cannot prove the signal-scope
    # diff is a strict subset of execution_nav-anchored cells, so the
    # only safe default is `bound_only` whenever the rolling
    # signal_input hash differs.
    #
    # Concrete failure mode the pre-fix logic missed: a single re-fetch
    # could carry BOTH a held-name close revision (which flips both
    # signal_input and execution_nav hashes; exec_nav E1 captures NAV
    # impact) AND a parallel revision on a non-held name's volume, or
    # on a held name's high/low, or on a held name's close OUTSIDE
    # the [start_date..as_of] execution_nav window. Those parallel
    # revisions also flip signal_input but are invisible to exec_nav
    # E1/E5 — yet they can change cross-sectional ranking and
    # therefore the realized top_n / cum_ret. With empty signal-scope
    # per_cell_digest there is no way to distinguish "1 revision both
    # hashes saw" from "1 in-ring revision + 1 hidden out-of-ring
    # revision". Fail-closed.
    #
    # Tests / diagnostics that need finer attribution opt in via
    # ``track_per_cell=True``; the populated cell diff then runs
    # through the per-attribute coverage check below and small in-ring
    # revisions can stay flagged_only.
    if "signal_input" in affected_scopes_set:
        sig_diffs = _diff_cells(
            entry.bar_hash_inputs.signal_input.per_cell_digest,
            sig_inputs.per_cell_digest,
        )
        # Compute the set of (sym, iso) cells anchored by execution_nav
        # (i.e., within the 10-day materiality_anchor_values ring on
        # close/open attributes). Used by the per-cell coverage check
        # below when track_per_cell=True populates per_cell_digest.
        held_set = set(entry.bar_hash_inputs.execution_nav.symbols)
        anchored_cells: set[tuple[str, str]] = set()
        for sym, by_date in (exec_anchors or {}).items():
            for iso in by_date.keys():
                anchored_cells.add((sym, iso))

        if not sig_diffs:
            # Empty per_cell_digest path (production default): cannot
            # attribute the signal-scope diff cell-by-cell. Fail-closed
            # regardless of execution_nav state per Blocker-2 contract.
            bound_only_reason = bound_only_reason or (
                "signal_input scope diff with empty per_cell_digest "
                "(track_per_cell=False) — cannot prove diff is subset "
                "of execution_nav-anchored cells; conservative bound_only "
                "per PRD §4.4 (codex Round-10 Blocker 2)"
            )
        else:
            for sym, iso, attr in sig_diffs:
                covered_by_anchor = (
                    sym in held_set
                    and attr in ("close", "open")
                    and (sym, iso) in anchored_cells
                )
                if not covered_by_anchor:
                    bound_only_reason = bound_only_reason or (
                        f"signal_input revision on {sym}/{iso}/{attr} "
                        f"(outside execution_nav anchor ring or non-"
                        f"anchored attribute) — NAV impact cannot be "
                        f"computed deterministically without re-running "
                        f"cross-sectional ranking"
                    )
                    break

    # E2/E3: checkpoint metric drift via benchmark anchor reconstruction
    cum_ret_drift_bps = None
    vs_spy_drift_bps  = None
    vs_qqq_drift_bps  = None
    decision_sign_flip = False

    if "benchmark" in affected_scopes_set:
        bench_anchors = entry.bar_hash_inputs.benchmark.materiality_anchor_values or {}
        close_panel = panel.get("close")
        if close_panel is not None:
            for bsym in benchmark_symbols:
                old_cum, new_cum = _bench_old_new_path(
                    bench_anchors=bench_anchors,
                    panel_close=close_panel,
                    sym=bsym,
                    start_date=start_date,
                    as_of_date=entry.as_of_date,
                )
                if old_cum is None or new_cum is None:
                    bound_only_reason = bound_only_reason or (
                        f"benchmark {bsym} cum_ret unreconstructable"
                    )
                    continue
                drift_bps = (new_cum - old_cum) * 10000.0
                if bsym == "SPY":
                    vs_spy_drift_bps = drift_bps
                elif bsym == "QQQ":
                    vs_qqq_drift_bps = drift_bps

    # cum_ret drift proxy: use as_of-date held weight × close drift
    # contribution from execution_nav. (Coarse but honest — PRD §4.4
    # accepts proxy estimates for materiality gates.)
    if "execution_nav" in affected_scopes_set and held_today_weights:
        cum_ret_drift_bps = nav_impact_bps  # proxy

    # cum_ret sign flip: |drift| could plausibly cross zero in either
    # direction. nav_impact_bps is unsigned (a magnitude — we don't
    # know the sign of the revision a priori), so the worst-case
    # check is symmetric: if |drift| >= |stored_cum|, sign COULD flip
    # depending on which direction the revision pushes NAV.
    stored_cum = entry.cum_ret
    if (stored_cum is not None and cum_ret_drift_bps is not None
            and abs(cum_ret_drift_bps) > 0):
        drift_magnitude = abs(cum_ret_drift_bps) / 10000.0
        if drift_magnitude >= abs(stored_cum):
            # Magnitude is large enough that at least one revision
            # direction would flip the sign — fire E4 conservatively.
            decision_sign_flip = True

    # ── apply E1-E5 escalation table ────────────────────────────
    invalidate = False
    triggers: list[str] = []
    if bound_only_reason is not None:
        invalidate = True
        triggers.append(f"bound_only ({bound_only_reason})")
    if nav_impact_bps >= NAV_IMPACT_BPS_THRESHOLD - _BPS_EPS:
        invalidate = True
        triggers.append(f"E1 NAV {nav_impact_bps:.2f} bps")
    for label, val in (
        ("cum_ret", cum_ret_drift_bps),
        ("vs_spy", vs_spy_drift_bps),
        ("vs_qqq", vs_qqq_drift_bps),
    ):
        if val is not None and abs(val) >= CHECKPOINT_DRIFT_BPS_THRESHOLD - _BPS_EPS:
            invalidate = True
            triggers.append(f"E2/E3 {label} {val:.2f} bps")
    if decision_sign_flip:
        invalidate = True
        triggers.append("E4 cum_ret sign flip")
    if raw_max_drift >= RAW_DRIFT_PCT_THRESHOLD - _PCT_EPS:
        invalidate = True
        triggers.append(f"E5 raw drift {raw_max_drift * 100:.3f}%")

    revised_symbols = sorted({s.split("/", 1)[1] for (s, _, _) in revised_cells})
    affected_scopes = sorted(affected_scopes_set)

    delta_summary = (
        f"scopes={affected_scopes}; n_revised_cells={len(revised_cells)}; "
        f"materiality_class={('bound_only' if bound_only_reason else 'in_ring')}; "
        f"triggers={triggers}"
    )

    return DataRevisionEvent(
        detected_at_utc=datetime.now(timezone.utc),
        revised_symbols=revised_symbols,
        detected_by_run_label=detected_by_run_label,
        delta_summary=delta_summary,
        estimated_nav_impact_bps=(
            None if bound_only_reason else round(nav_impact_bps, 4)
        ),
        estimated_cum_ret_drift_bps=(
            None if cum_ret_drift_bps is None else round(cum_ret_drift_bps, 4)
        ),
        estimated_vs_spy_drift_bps=(
            None if vs_spy_drift_bps is None else round(vs_spy_drift_bps, 4)
        ),
        estimated_vs_qqq_drift_bps=(
            None if vs_qqq_drift_bps is None else round(vs_qqq_drift_bps, 4)
        ),
        decision_sign_flip=decision_sign_flip,
        raw_max_close_drift_pct=(
            None if raw_max_drift == 0 else round(raw_max_drift, 6)
        ),
        affected_scopes=affected_scopes,
        policy_decision=("invalidated" if invalidate else "flagged_only"),
    )


# ── public entry point ─────────────────────────────────────────────


def revalidate_manifest(
    manifest: ForwardRunManifest,
    *,
    spec,
    universe: list[str],
    panel: dict,
    benchmark_symbols: list[str],
    detected_by_run_label: str,
    bar_revision: str = DEFAULT_BAR_REVISION,
) -> RevalidationSummary:
    """Pure functional revalidate over a loaded manifest + current panel.

    Caller (typically observe()) is responsible for persisting the
    returned events on the corresponding TD entries and gating
    further observe() calls on the requires_data_review flag.

    Does NOT mutate the manifest. Returns a summary listing the events
    detected; the caller decides whether to persist + which to persist.
    """
    events: list = []
    n_legacy = 0
    n_no_hash = 0
    n_checked = 0
    requires_review = False

    for entry in manifest.runs:
        if not entry.checkpoint_label.startswith("TD"):
            continue
        if entry.legacy_unhashed_inputs:
            n_legacy += 1
            continue
        if (entry.signal_input_hash is None
                or entry.execution_nav_hash is None
                or entry.benchmark_hash is None
                or entry.bar_hash_inputs is None):
            n_no_hash += 1
            continue
        n_checked += 1
        ev = _revalidate_entry(
            entry=entry,
            spec=spec,
            universe=universe,
            panel=panel,
            start_date=manifest.start_date,
            benchmark_symbols=benchmark_symbols,
            detected_by_run_label=detected_by_run_label,
            bar_revision=bar_revision,
        )
        if ev is not None:
            events.append((entry, ev))
            if ev.policy_decision == "invalidated":
                requires_review = True

    return RevalidationSummary(
        candidate_id=manifest.candidate_id,
        n_runs_checked=n_checked,
        n_legacy_skipped=n_legacy,
        n_no_hash_skipped=n_no_hash,
        events=events,
        requires_data_review=requires_review,
    )
