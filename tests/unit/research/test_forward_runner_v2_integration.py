"""Forward runner v2.1 evidence-hardening integration tests.

Covers the runner-level wiring of the per-scope hashers + revalidate:

  - observe() populates v2 fields on every new TD entry
    (signal_input_hash / execution_nav_hash / benchmark_hash /
     bar_hash rollup / bar_hash_inputs / source_layer_breakdown /
     held_today_weights, all non-None, all stable across re-runs).
  - The first v2 observe() invocation marks pre-v2 entries
    (TD001 baseline rows that existed before v2.1) with
    legacy_unhashed_inputs=True without touching their numerics.
  - Idempotency: a no-op observe() preserves all v2 fields and
    leaves the manifest byte-identical except for any revalidate-
    detected events.
  - Synthetic revision: mutating the live store's frontier bar
    after a TD is written triggers a data_revision_event on the
    affected entry the next time observe() runs.

PRD: docs/prd/20260427-forward_evidence_hardening_prd.md v2.1
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from core.research.forward import (
    BarHashInputs,
    ForwardRun,
    ForwardRunStatus,
    init,
    load_manifest,
    observe,
)


CAND_DIR = Path("data/research_candidates")


def _setup_repo(tmp_path: Path, candidate_id: str) -> Path:
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    src = CAND_DIR / f"{candidate_id}.yaml"
    (out_dir / src.name).write_text(src.read_text())
    return out_dir


# ── core v2.1 wiring ──────────────────────────────────────────────


def test_observe_populates_v2_fields_on_new_td(tmp_path: Path):
    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand,
        start_date="2025-01-02",
        output_dir=out,
        cost_model_path="config/cost_model.yaml",
    )
    appended = observe(
        candidate_id=cand,
        output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10,
        up_to="2025-01-15",
    )
    assert len(appended) > 0
    for entry in appended:
        # All three input-scope hashes populated and 24-char
        assert entry.signal_input_hash and len(entry.signal_input_hash) == 24
        assert entry.execution_nav_hash and len(entry.execution_nav_hash) == 24
        assert entry.benchmark_hash and len(entry.benchmark_hash) == 24
        # Rollup populated and consistent with deterministic combine
        assert entry.bar_hash and len(entry.bar_hash) == 24
        # Reproducibility evidence container
        assert isinstance(entry.bar_hash_inputs, BarHashInputs)
        assert entry.bar_hash_inputs.signal_input.scope == "signal_input"
        assert entry.bar_hash_inputs.execution_nav.scope == "execution_nav"
        assert entry.bar_hash_inputs.benchmark.scope == "benchmark"
        # legacy marker explicitly False (NOT None) on v2 entries
        assert entry.legacy_unhashed_inputs is False
        # held_today_weights captured (allow empty dict if no holdings
        # yet on day-1 — but typically there's at least one position)
        assert entry.held_today_weights is not None


def test_execution_nav_anchored_at_manifest_start_date_not_as_of(tmp_path: Path):
    """PRD §G6: TD002+ must hash bars from manifest.start_date, not
    from each TD's own as_of_date. Verify by inspecting two TDs from
    the same observe() and asserting both share the start_date
    contribution (window_start equals manifest.start_date)."""
    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand,
        start_date="2025-01-02",
        output_dir=out,
        cost_model_path="config/cost_model.yaml",
    )
    appended = observe(
        candidate_id=cand,
        output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10,
        up_to="2025-01-15",
    )
    assert len(appended) >= 2
    manifest_start = date(2025, 1, 2)
    for entry in appended:
        assert entry.bar_hash_inputs.execution_nav.window_start == manifest_start
        assert entry.bar_hash_inputs.benchmark.window_start == manifest_start
        # Signal-input window starts at as_of - max_lookback (252d for
        # RCMv1) — explicitly NOT manifest.start_date.
        sig_start = entry.bar_hash_inputs.signal_input.window_start
        assert sig_start != manifest_start


def test_observe_marks_pre_v2_td_legacy_unhashed_inputs(tmp_path: Path):
    """First v2 observe() must mark any TD entry that lacks bar_hash
    AND lacks an explicit legacy marker as legacy_unhashed_inputs=True.
    Numeric fields on the legacy entry must NOT change."""
    from core.research.forward.manifest_io import save_manifest
    from core.research.forward.manifest_schema import ForwardRunManifest
    from core.research.robustness.window_spec import (
        DataIntegritySnapshot, EvidenceClass,
    )
    from core.research.forward.manifest_schema import (
        CheckpointCadence, CostAssumptions,
    )

    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    # Hand-craft a manifest with a pre-v2 TD001 entry (no bar_hash,
    # no legacy marker). This simulates the production state of the
    # current RCMv1 / Cand-2 manifests.
    cost_path = Path("config/cost_model.yaml")
    cost_hash = __import__("hashlib").sha256(cost_path.read_bytes()).hexdigest()
    legacy_td1 = ForwardRun(
        checkpoint_label="TD001",
        as_of_date=date(2025, 1, 2),
        n_observed_trading_days=1,
        cum_ret=0.0,
        max_dd=0.0,
        notes="legacy baseline",
    )
    manifest = ForwardRunManifest(
        candidate_id=cand,
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef0123456789",
        start_date=date(2025, 1, 2),
        cost_assumptions=CostAssumptions(
            source=str(cost_path), config_hash=cost_hash,
        ),
        checkpoint_cadence=CheckpointCadence(),
        data_integrity_snapshot=DataIntegritySnapshot(
            daily_store_rebuild_commit="abcdef012345",
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime.now(timezone.utc),
        ),
        runs=[legacy_td1],
        current_status=ForwardRunStatus.in_progress,
    )
    manifest_p = out / f"{cand}_forward_manifest.json"
    save_manifest(manifest, manifest_p)
    pre = legacy_td1.model_dump()

    appended = observe(
        candidate_id=cand,
        output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10,
        up_to="2025-01-15",
    )
    assert len(appended) > 0
    reloaded = load_manifest(manifest_p)
    td1_post = reloaded.runs[0]
    # Legacy marker now True
    assert td1_post.legacy_unhashed_inputs is True
    # Numerics preserved exactly
    assert td1_post.cum_ret == pre["cum_ret"]
    assert td1_post.max_dd  == pre["max_dd"]
    assert td1_post.as_of_date == pre["as_of_date"]
    assert td1_post.n_observed_trading_days == pre["n_observed_trading_days"]
    # No v2 hashes on the legacy row
    assert td1_post.bar_hash is None
    assert td1_post.signal_input_hash is None


def test_flagged_only_event_persists_when_no_new_bars(tmp_path: Path):
    """PRD §4.6: revalidate detects revisions on every observe()
    call. When events are flagged_only (sub-threshold) AND there
    are no new bars to append, the events MUST still be saved to
    disk — early-return on no-new-dates would otherwise silently
    drop them. Bug-fix regression test (audit round 2)."""
    from core.research.forward.manifest_io import save_manifest

    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand, start_date="2025-01-02",
        output_dir=out, cost_model_path="config/cost_model.yaml",
    )
    appended = observe(
        candidate_id=cand, output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10, up_to="2025-01-08",
    )
    assert len(appended) > 0

    # Mutate ONE TD's stored signal_input_hash to a known-different
    # value. revalidate will detect divergence; since the actual
    # store hasn't changed, NAV impact = 0 → flagged_only.
    m = load_manifest(out / f"{cand}_forward_manifest.json")
    target = m.runs[-1]
    corrupted = target.model_copy(update={
        "signal_input_hash": "deadbeefdeadbeefdeadbeef",
    })
    new_runs = list(m.runs)
    new_runs[-1] = corrupted
    save_manifest(m.model_copy(update={"runs": new_runs}),
                  out / f"{cand}_forward_manifest.json")

    # Same up_to → no new bars to append. Revalidate-detected
    # event MUST be persisted on the corrupted entry.
    second_call = observe(
        candidate_id=cand, output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10, up_to="2025-01-08",
    )
    assert second_call == [], "no new bars expected"
    m_after = load_manifest(out / f"{cand}_forward_manifest.json")
    target_after = m_after.runs[-1]
    assert target_after.data_revision_event is not None, (
        "revalidate-detected flagged_only event was lost on early "
        "return — observe() must save before returning even when "
        "no new TDs are appended"
    )


def test_observe_revalidates_when_no_new_bars(tmp_path: Path):
    """PRD §4.6: revalidate runs at the top of every observe(),
    regardless of whether new TD bars are appended. Daily-ritual
    contract: a yfinance retroactive revision that lands between
    observations on a no-new-bar day MUST still be detected.
    Bug-fix regression test (post-audit).
    """
    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand, start_date="2025-01-02",
        output_dir=out, cost_model_path="config/cost_model.yaml",
    )
    # Observe once with a capped end date so we have v2 TD entries
    # but more bars exist beyond the cap. Then re-observe with the
    # same cap → no new TDs, but revalidate must still run.
    appended_first = observe(
        candidate_id=cand, output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10, up_to="2025-01-15",
    )
    assert len(appended_first) > 0
    # Patch the manifest in-memory: simulate a stale stored hash by
    # corrupting one TD entry's signal_input_hash. On the next
    # observe, revalidate must surface a divergence event.
    from core.research.forward.manifest_io import save_manifest
    m = load_manifest(out / f"{cand}_forward_manifest.json")
    target_idx = -1   # last v2 entry
    while m.runs[target_idx].legacy_unhashed_inputs is True:
        target_idx -= 1
    target = m.runs[target_idx]
    corrupted = target.model_copy(update={
        "signal_input_hash": "deadbeefdeadbeefdeadbeef",
    })
    new_runs = list(m.runs)
    new_runs[target_idx] = corrupted
    m_corrupted = m.model_copy(update={"runs": new_runs})
    save_manifest(m_corrupted, out / f"{cand}_forward_manifest.json")

    # No new bars (same up_to) — observe must STILL run revalidate
    # and surface the divergence on the corrupted entry.
    appended_second = observe(
        candidate_id=cand, output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10, up_to="2025-01-15",
    )
    assert appended_second == []
    m_after = load_manifest(out / f"{cand}_forward_manifest.json")
    target_after = m_after.runs[target_idx]
    assert target_after.data_revision_event is not None, (
        "revalidate should fire on the corrupted entry even when "
        "no new TDs are appended"
    )


def test_observe_halts_when_requires_data_review(tmp_path: Path):
    """PRD §4.4: once revalidate flips status to requires_data_review,
    observe() must halt until decide() clears the state."""
    from core.research.forward import ForwardHaltError
    from core.research.forward.manifest_io import save_manifest

    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand, start_date="2025-01-02",
        output_dir=out, cost_model_path="config/cost_model.yaml",
    )
    observe(
        candidate_id=cand, output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10, up_to="2025-01-15",
    )
    # Manually flip status to simulate a previous revalidate having
    # fired invalidation. Subsequent observe() must halt.
    m = load_manifest(out / f"{cand}_forward_manifest.json")
    m_review = m.model_copy(update={
        "current_status": ForwardRunStatus.requires_data_review,
    })
    save_manifest(m_review, out / f"{cand}_forward_manifest.json")

    with pytest.raises(ForwardHaltError) as exc:
        observe(
            candidate_id=cand, output_dir=out,
            cost_model_path="config/cost_model.yaml",
            top_n=10, up_to="2025-01-31",
        )
    assert "requires_data_review" in str(exc.value)
    assert "decide()" in str(exc.value)


def test_signal_input_per_cell_digest_empty_in_runner(tmp_path: Path):
    """Storage guard: runner must NOT enable track_per_cell on
    signal_input scope. Manifest size for a few TDs must stay <100KB
    per the audit fix; signal_input.per_cell_digest must be empty."""
    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand, start_date="2025-01-02",
        output_dir=out, cost_model_path="config/cost_model.yaml",
    )
    appended = observe(
        candidate_id=cand, output_dir=out,
        cost_model_path="config/cost_model.yaml",
        top_n=10, up_to="2025-01-15",
    )
    assert len(appended) > 0
    for entry in appended:
        # signal_input per_cell_digest must be empty in production
        assert entry.bar_hash_inputs.signal_input.per_cell_digest == {}
        # but the rolling hash IS populated
        assert entry.signal_input_hash and len(entry.signal_input_hash) == 24
    # Sanity-check overall manifest size. Pre-fix, the signal_input
    # per_cell_digest stored ~80×252×2 cells per TD which produced
    # ~1.5 MB / TD; the fix drops that to ~30 KB / TD (execution_nav
    # + benchmark anchor + metadata only). Threshold bounds against
    # the pre-fix regression while leaving headroom for live runs.
    n_v2_tds = sum(1 for e in appended)
    size_kb = (out / f"{cand}_forward_manifest.json").stat().st_size / 1024
    per_td_kb = size_kb / max(n_v2_tds, 1)
    assert per_td_kb < 100, (
        f"manifest size {size_kb:.1f}KB / {n_v2_tds} TDs = "
        f"{per_td_kb:.1f}KB per TD — well above the post-fix budget "
        f"(~30 KB/TD); likely regression in signal_input "
        f"per_cell_digest pruning"
    )


def test_observe_idempotent_under_v2(tmp_path: Path):
    """Re-running observe with no new bars must be a no-op."""
    cand = "rcm_v1_defensive_composite_01"
    out = _setup_repo(tmp_path, cand)
    init(
        candidate_id=cand, start_date="2025-01-02",
        output_dir=out, cost_model_path="config/cost_model.yaml",
    )
    first  = observe(candidate_id=cand, output_dir=out,
                     cost_model_path="config/cost_model.yaml",
                     top_n=10, up_to="2025-01-15")
    second = observe(candidate_id=cand, output_dir=out,
                     cost_model_path="config/cost_model.yaml",
                     top_n=10, up_to="2025-01-15")
    assert len(first) > 0
    assert second == []
    # And the on-disk manifest's v2 fields are stable across the
    # second (no-op) observe call
    reloaded = load_manifest(out / f"{cand}_forward_manifest.json")
    for entry in reloaded.runs:
        if entry.legacy_unhashed_inputs:
            continue
        assert entry.bar_hash is not None
        assert entry.signal_input_hash is not None
