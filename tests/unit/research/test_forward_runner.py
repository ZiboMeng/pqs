"""Forward OOS runner R-fwd-1 tests.

Covers:
  - manifest IO (load/save round-trip + schema bypass guard)
  - init (idempotent file-exists guard, frozen spec hash, cost hash)
  - status (read-only summary)
  - observe (append-only, idempotent multi-day catch-up, cost-hash HALT)
  - decide (narrow allow-list, audit-trail entry)

PRD: docs/prd/20260426-forward_oos_runner_prd.md §6 R-fwd-1
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.research.forward import (
    ForwardHaltError,
    ForwardRunManifest,
    ForwardRunStatus,
    decide,
    init,
    load_manifest,
    manifest_path,
    observe,
    save_manifest,
    status,
)
from core.research.forward.runner import (
    _file_sha256_hex,
    _resolve_dates_to_observe,
    _verify_cost_hash_or_halt,
)


# ── manifest IO ─────────────────────────────────────────────────────────


def _build_manifest(**overrides) -> ForwardRunManifest:
    from core.research.robustness.window_spec import (
        DataIntegritySnapshot,
        EvidenceClass,
    )
    from core.research.forward.manifest_schema import (
        CheckpointCadence,
        CostAssumptions,
    )

    base = dict(
        candidate_id="test_cand",
        evidence_class=EvidenceClass.forward_oos,
        spec_hash="abcdef0123456789",
        start_date=date(2026, 4, 25),
        cost_assumptions=CostAssumptions(
            source="config/cost_model.yaml",
            config_hash="cafebabe1234deadbeef",
        ),
        checkpoint_cadence=CheckpointCadence(),
        data_integrity_snapshot=DataIntegritySnapshot(
            daily_store_rebuild_commit="abcdef012345",
            baseline_snapshot_path="data/baseline/latest.json",
            generated_at_utc=datetime.now(timezone.utc),
        ),
    )
    base.update(overrides)
    return ForwardRunManifest(**base)


def test_save_load_round_trip(tmp_path: Path):
    m = _build_manifest()
    p = tmp_path / "m.json"
    save_manifest(m, p)
    loaded = load_manifest(p)
    assert loaded.candidate_id == m.candidate_id
    assert loaded.spec_hash == m.spec_hash
    assert loaded.evidence_class is m.evidence_class


def test_load_rejects_evidence_class_drift(tmp_path: Path):
    """Schema bypass guard: if someone hand-edits the JSON to flip
    evidence_class, load_manifest must reject."""
    m = _build_manifest()
    p = tmp_path / "m.json"
    save_manifest(m, p)
    payload = json.loads(p.read_text())
    payload["evidence_class"] = "historical_replay"
    p.write_text(json.dumps(payload))
    with pytest.raises(Exception):  # ValidationError
        load_manifest(p)


# ── init ────────────────────────────────────────────────────────────────


def _setup_fake_repo(tmp_path: Path, candidate_id: str = "fake_cand") -> tuple:
    """Create a minimal candidate yaml + cost yaml + registry stub."""
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    spec_path = out_dir / f"{candidate_id}.yaml"
    spec_path.write_text(_minimal_spec_yaml(candidate_id))
    cost_path = tmp_path / "cost_model.yaml"
    cost_path.write_text("commission_per_trade: 0.005\nslippage_bps: 5\n")
    return out_dir, cost_path, spec_path


def _minimal_spec_yaml(cid: str) -> str:
    return f"""
candidate_id: {cid}
strategy_version: test-v1-2026-04-26
source_trial_id: test_trial_001
feature_set:
  - name: ret_5d
    weight: 1.0
    family: B
    source: core/factors/factor_generator.py
benchmark_relative_summary: 'test'
oos_holdout_summary: 'test'
robustness_summary: 'test'
decision_memo: 'test'
"""


def test_init_creates_manifest_with_pinned_hashes(tmp_path: Path, monkeypatch):
    out_dir, cost_path, spec_path = _setup_fake_repo(tmp_path)
    # init() pulls promoted_at via registry by default; pass start_date
    # explicitly to avoid registry dependency in the unit test.
    m = init(
        candidate_id="fake_cand",
        start_date="2026-04-25",
        output_dir=out_dir,
        cost_model_path=cost_path,
    )
    p = manifest_path("fake_cand", out_dir)
    assert p.exists()
    assert m.spec_hash == _file_sha256_hex(spec_path)
    assert m.cost_assumptions.config_hash == _file_sha256_hex(cost_path)
    assert m.evidence_class.value == "forward_oos"
    assert m.runs == []
    assert m.current_status.value == "not_started"


def test_init_refuses_to_clobber_existing(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    with pytest.raises(FileExistsError):
        init(candidate_id="fake_cand", start_date="2026-04-25",
             output_dir=out_dir, cost_model_path=cost_path)


# ── PRD F step 2: init populates config_snapshot ─────────────────────


def _make_fake_config_dir(tmp_path: Path) -> Path:
    """Synthetic config tree for hermetic Step 2 tests."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "universe.yaml").write_text(
        "seed_pool: [SPY, QQQ, AAPL]\nblacklist: [SQQQ]\n"
    )
    (cfg_dir / "research_mask.yaml").write_text(
        "min_price: 5.0\nmin_usd_volume: 1000000\nrolling_window_days: 60\n"
    )
    (cfg_dir / "risk.yaml").write_text(
        "long_only: true\nallow_margin: false\nallow_short: false\n"
    )
    (cfg_dir / "system.yaml").write_text(
        "env: test\naccount:\n  initial_capital_usd: 100000\n"
    )
    return cfg_dir


def test_init_populates_config_snapshot(tmp_path: Path):
    """Step 2 acceptance: init() must build a ConfigSnapshot with all 5
    hashes + sources map populated.

    Reverse-validation: stash runner.py's _build_config_snapshot call
    in init() and the manifest's config_snapshot would be None — this
    test fails on len(...) attribute access.
    """
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    cfg_dir = _make_fake_config_dir(tmp_path)
    m = init(
        candidate_id="fake_cand",
        start_date="2026-04-25",
        output_dir=out_dir,
        cost_model_path=cost_path,
        config_dir=cfg_dir,
    )
    snap = m.config_snapshot
    assert snap is not None, "init() must populate config_snapshot"
    # All 5 hashes are non-empty SHA-256 digests (64 hex chars).
    assert len(snap.universe_hash) == 64
    assert len(snap.factor_registry_hash) == 64
    assert len(snap.research_mask_hash) == 64
    assert len(snap.risk_config_hash) == 64
    assert len(snap.system_config_hash) == 64
    # sources map round-trip carries the 5 source paths.
    assert set(snap.sources.keys()) == {
        "universe_hash", "factor_registry_hash",
        "research_mask_hash", "risk_config_hash", "system_config_hash",
    }
    # snapshot_at_utc is a real timezone-aware UTC datetime.
    assert snap.snapshot_at_utc.tzinfo is not None
    # Migration note untouched at init.
    assert snap.migration_note is None


def test_init_config_snapshot_persists_through_save_load(tmp_path: Path):
    """JSON round-trip through save_manifest + load_manifest preserves all 5 hashes."""
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    cfg_dir = _make_fake_config_dir(tmp_path)
    m = init(
        candidate_id="fake_cand",
        start_date="2026-04-25",
        output_dir=out_dir,
        cost_model_path=cost_path,
        config_dir=cfg_dir,
    )
    # Re-load from disk
    from core.research.forward.manifest_io import load_manifest
    p = manifest_path("fake_cand", out_dir)
    m2 = load_manifest(p)
    assert m2.config_snapshot is not None
    assert m2.config_snapshot.universe_hash == m.config_snapshot.universe_hash
    assert m2.config_snapshot.factor_registry_hash == m.config_snapshot.factor_registry_hash
    assert m2.config_snapshot.research_mask_hash == m.config_snapshot.research_mask_hash
    assert m2.config_snapshot.risk_config_hash == m.config_snapshot.risk_config_hash
    assert m2.config_snapshot.system_config_hash == m.config_snapshot.system_config_hash


def test_canonical_yaml_sha_ignores_key_reordering(tmp_path: Path):
    """A reorder of the same keys must NOT change the hash — defense
    against false-positive drift on benign yaml edits."""
    from core.research.forward.runner import _canonical_yaml_sha

    f = tmp_path / "u1.yaml"
    f.write_text("blacklist: [SQQQ, SOXS]\nseed_pool: [SPY, QQQ]\n")
    h1 = _canonical_yaml_sha(f)

    # Reorder top-level keys
    f.write_text("seed_pool: [SPY, QQQ]\nblacklist: [SQQQ, SOXS]\n")
    h2 = _canonical_yaml_sha(f)
    assert h1 == h2, "key reordering must not change the canonical hash"


def test_canonical_yaml_sha_detects_real_content_change(tmp_path: Path):
    """Adding a real new symbol DOES change the hash."""
    from core.research.forward.runner import _canonical_yaml_sha

    f = tmp_path / "u2.yaml"
    f.write_text("seed_pool: [SPY, QQQ]\n")
    h1 = _canonical_yaml_sha(f)

    f.write_text("seed_pool: [SPY, QQQ, META]\n")
    h2 = _canonical_yaml_sha(f)
    assert h1 != h2, "adding META to seed_pool must change the canonical hash"


def test_factor_registry_contract_sha_is_deterministic():
    """Same registry state → same hash (no dict-ordering / set-iteration drift)."""
    from core.research.forward.runner import _factor_registry_contract_sha
    h1 = _factor_registry_contract_sha()
    h2 = _factor_registry_contract_sha()
    assert h1 == h2
    assert len(h1) == 64


def test_first_post_freeze_trading_day_pre_close_freeze():
    """Freeze at 15:28 UTC (before 20:00 UTC market close) → that day's
    close IS post-freeze → start on that day.

    This is Cand-2's exact case: frozen_at_utc=2026-04-24T15:28 → 4-24
    close at 20:00 UTC is post-freeze. Pre-fix bug pushed start_date
    to 4-27 (Mon), losing 4-24 as a legitimate forward observation.
    """
    from core.research.forward.runner import _first_post_freeze_trading_day
    frozen = datetime(2026, 4, 24, 15, 28, 35, tzinfo=timezone.utc)
    # If SPY parquet is unavailable, falls back to BDay; should still
    # land on 4-24 because 4-24 was a Friday.
    result = _first_post_freeze_trading_day(frozen)
    assert result == date(2026, 4, 24), (
        f"freeze before market close should observe same-day's close; "
        f"got {result}"
    )


def test_first_post_freeze_trading_day_post_close_freeze():
    """Freeze at 23:39 UTC (after 20:00 UTC market close) → that day's
    close is pre-freeze → start on next trading day.

    This is RCMv1's case: frozen_at_utc=2026-04-23T23:39 → 4-23 close
    at 20:00 UTC is pre-freeze → start_date = 4-24.
    """
    from core.research.forward.runner import _first_post_freeze_trading_day
    frozen = datetime(2026, 4, 23, 23, 39, 14, tzinfo=timezone.utc)
    result = _first_post_freeze_trading_day(frozen)
    assert result == date(2026, 4, 24)


def test_first_post_freeze_trading_day_freeze_on_weekend():
    """Freeze on a weekend (any time) → start at next trading day."""
    from core.research.forward.runner import _first_post_freeze_trading_day
    # Saturday afternoon
    frozen = datetime(2026, 4, 25, 14, 0, tzinfo=timezone.utc)
    result = _first_post_freeze_trading_day(frozen)
    # 4-25 is Saturday, so candidate = 4-25 (since 14 < 20), and the
    # next trading day on-or-after 4-25 is Monday 4-27.
    assert result == date(2026, 4, 27)


def test_first_post_freeze_trading_day_dst_winter_pre_close():
    """R8 (B5) DST regression: freeze at 20:30 UTC during EST/winter.

    EST = UTC-5, so 20:30 UTC = 15:30 ET, which is BEFORE the 16:00 ET
    market close. The pre-R8 code used a fixed ``_NYSE_CLOSE_UTC_HOUR
    = 20`` heuristic that would treat hour=20 as past-close and
    incorrectly advance start_date to the next day. The post-R8 fix
    converts to America/New_York and compares to 16:00 ET, which
    correctly identifies this as pre-close → today's close is
    post-freeze → start on this day.
    """
    from core.research.forward.runner import _first_post_freeze_trading_day
    # Wednesday 2026-01-14 at 20:30 UTC = 15:30 EST (winter)
    frozen = datetime(2026, 1, 14, 20, 30, 0, tzinfo=timezone.utc)
    result = _first_post_freeze_trading_day(frozen)
    assert result == date(2026, 1, 14), (
        f"EST 15:30 (UTC 20:30) is pre-close; should start same day, got {result}"
    )


def test_first_post_freeze_trading_day_dst_winter_post_close():
    """R8 (B5) DST regression: freeze at 21:30 UTC during EST/winter.

    EST = UTC-5, so 21:30 UTC = 16:30 ET, which is AFTER the 16:00 ET
    market close. Today's close is pre-freeze → start on next trading
    day.
    """
    from core.research.forward.runner import _first_post_freeze_trading_day
    # Wednesday 2026-01-14 at 21:30 UTC = 16:30 EST
    frozen = datetime(2026, 1, 14, 21, 30, 0, tzinfo=timezone.utc)
    result = _first_post_freeze_trading_day(frozen)
    assert result == date(2026, 1, 15), (
        f"EST 16:30 (UTC 21:30) is post-close; should start next day, got {result}"
    )


def test_init_advances_weekend_start_date_to_next_trading_day(tmp_path: Path):
    """Post-MVP audit fix (2026-04-26): start_date must be a trading day.

    Previously ``init`` used ``frozen + 1 calendar day`` which could
    land on a weekend (e.g. Cand-2 promoted_at=2026-04-24 → start_date=
    2026-04-25 Saturday). This test pins the corrected behavior:
    explicit weekend start_date is advanced to the next trading day.
    """
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    # 2026-04-25 is a Saturday. Real SPY index has 2026-04-24 (Fri)
    # and 2026-04-27 (Mon next), so next-trading-day after Sat is Mon.
    # If the test runs without a SPY parquet at the test path, BDay
    # fallback should still advance past the weekend.
    m = init(
        candidate_id="fake_cand",
        start_date="2026-04-25",  # Saturday
        output_dir=out_dir,
        cost_model_path=cost_path,
    )
    # Saturday → at minimum next Monday (or whatever SPY says).
    assert m.start_date.weekday() < 5, (
        f"start_date {m.start_date} is still a non-trading day "
        f"(weekday={m.start_date.weekday()})"
    )


def test_init_overwrite_resets(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    # Override should succeed and produce a fresh empty runs[].
    m = init(candidate_id="fake_cand", start_date="2026-05-01",
             output_dir=out_dir, cost_model_path=cost_path,
             overwrite=True)
    assert m.start_date == date(2026, 5, 1)
    assert m.runs == []


# ── status ──────────────────────────────────────────────────────────────


def test_status_returns_summary(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    s = status("fake_cand", output_dir=out_dir)
    assert s["candidate_id"] == "fake_cand"
    assert s["current_status"] == "not_started"
    assert s["evidence_class"] == "forward_oos"
    assert s["n_runs"] == 0


# ── observe (HALT paths — no real data needed) ──────────────────────────


def test_observe_halts_on_cost_hash_mismatch(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    # Mutate the cost yaml — its sha256 now differs from the manifest pin.
    cost_path.write_text("commission_per_trade: 0.999\nslippage_bps: 999\n")
    with pytest.raises(ForwardHaltError) as exc:
        observe("fake_cand", output_dir=out_dir, cost_model_path=cost_path)
    assert "cost-yaml hash mismatch" in str(exc.value)


def test_observe_halts_on_missing_cost_file(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    cost_path.unlink()
    with pytest.raises(ForwardHaltError):
        observe("fake_cand", output_dir=out_dir, cost_model_path=cost_path)


def test_verify_cost_hash_passes_on_unchanged_file(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    m = init(candidate_id="fake_cand", start_date="2026-04-25",
             output_dir=out_dir, cost_model_path=cost_path)
    # Direct verify call — should not raise.
    _verify_cost_hash_or_halt(m, cost_path)


# ── _resolve_dates_to_observe (idempotent + append-only) ────────────────


def test_resolve_dates_excludes_already_observed(tmp_path: Path):
    """Idempotent multi-day catch-up: dates already in runs[] are skipped."""
    from core.research.forward.manifest_schema import ForwardRun

    m = _build_manifest(
        runs=[
            ForwardRun(
                checkpoint_label="TD001",
                as_of_date=date(2026, 4, 28),
                n_observed_trading_days=1,
            ),
            ForwardRun(
                checkpoint_label="TD002",
                as_of_date=date(2026, 4, 29),
                n_observed_trading_days=2,
            ),
        ],
    )
    # Available index includes already-observed dates AND new dates.
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-04-28"),
        pd.Timestamp("2026-04-29"),
        pd.Timestamp("2026-04-30"),
        pd.Timestamp("2026-05-01"),
    ])
    new_dates = _resolve_dates_to_observe(m, idx)
    assert new_dates == [date(2026, 4, 30), date(2026, 5, 1)]


def test_resolve_dates_no_new_bars_returns_empty():
    from core.research.forward.manifest_schema import ForwardRun

    m = _build_manifest(
        runs=[
            ForwardRun(
                checkpoint_label="TD001",
                as_of_date=date(2026, 4, 28),
                n_observed_trading_days=1,
            ),
        ],
    )
    idx = pd.DatetimeIndex([pd.Timestamp("2026-04-28")])
    assert _resolve_dates_to_observe(m, idx) == []


def test_resolve_dates_respects_up_to_cap():
    m = _build_manifest()
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-04-26"),
        pd.Timestamp("2026-04-27"),
        pd.Timestamp("2026-04-28"),
        pd.Timestamp("2026-04-29"),
    ])
    new = _resolve_dates_to_observe(m, idx, up_to=date(2026, 4, 27))
    assert date(2026, 4, 26) in new
    assert date(2026, 4, 27) in new
    assert date(2026, 4, 28) not in new
    assert date(2026, 4, 29) not in new


def test_decide_entry_does_not_collide_with_td_lookups():
    """Append-only contract: a 'DECIDE' audit entry must not be
    treated as an observed TD by _resolve_dates_to_observe.
    """
    from core.research.forward.manifest_schema import ForwardRun

    m = _build_manifest(
        runs=[
            ForwardRun(
                checkpoint_label="TD001",
                as_of_date=date(2026, 4, 28),
                n_observed_trading_days=1,
            ),
            ForwardRun(
                checkpoint_label="DECIDE",
                as_of_date=date(2026, 4, 28),
                n_observed_trading_days=1,
                notes="aborted by user",
            ),
        ],
    )
    idx = pd.DatetimeIndex([
        pd.Timestamp("2026-04-28"),
        pd.Timestamp("2026-04-29"),
    ])
    # 04-28 is observed (TD001); 04-29 is new despite the DECIDE entry
    # also being on 04-28.
    assert _resolve_dates_to_observe(m, idx) == [date(2026, 4, 29)]


# ── decide ──────────────────────────────────────────────────────────────


def test_decide_rejects_disallowed_status(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    with pytest.raises(ValueError):
        decide(
            "fake_cand",
            ForwardRunStatus.in_progress,  # not in allow-list
            output_dir=out_dir,
        )


def test_decide_accepts_allowed_status(tmp_path: Path):
    out_dir, cost_path, _ = _setup_fake_repo(tmp_path)
    init(candidate_id="fake_cand", start_date="2026-04-25",
         output_dir=out_dir, cost_model_path=cost_path)
    m = decide(
        "fake_cand", ForwardRunStatus.completed_fail,
        notes="forward window failed at 30 TD",
        output_dir=out_dir,
    )
    assert m.current_status is ForwardRunStatus.completed_fail
    # Audit trail entry
    decide_entries = [r for r in m.runs if r.checkpoint_label == "DECIDE"]
    assert len(decide_entries) == 1
    assert "forward window failed" in (decide_entries[0].notes or "")


# ── real-data smoke (skipped when artifacts missing) ────────────────────


@pytest.mark.skipif(
    not (
        Path("data/daily/SPY.parquet").exists()
        and Path(
            "data/research_candidates/rcm_v1_defensive_composite_01.yaml"
        ).exists()
        and Path("data/research_candidates/registry.db").exists()
    ),
    reason="real data store / registry / candidate spec missing — skip smoke",
)
def test_observe_smoke_real_data_appends_runs(tmp_path: Path):
    """End-to-end smoke against real artifacts. Forward window is
    candidate's promoted_at + 1 day → today's data; we expect AT LEAST
    one TD entry to be appended (RCMv1 promoted 2026-04-23, data ends
    around 2026-04-17 — actually NEGATIVE forward window: should be
    a no-op that returns empty list, and that IS the correct
    contract).
    """
    out_dir = tmp_path / "candidates"
    out_dir.mkdir()
    cand_yaml = Path(
        "data/research_candidates/rcm_v1_defensive_composite_01.yaml"
    )
    (out_dir / cand_yaml.name).write_text(cand_yaml.read_text())
    # Use a DEFINITELY-PAST start_date so we get TD entries.
    init(
        candidate_id="rcm_v1_defensive_composite_01",
        start_date="2025-01-02",
        output_dir=out_dir,
        cost_model_path="config/cost_model.yaml",
    )
    appended = observe(
        candidate_id="rcm_v1_defensive_composite_01",
        output_dir=out_dir,
        cost_model_path="config/cost_model.yaml",
        top_n=10,
        up_to="2025-02-01",  # short window for fast smoke
    )
    assert len(appended) > 0, "expected at least one TD entry over Jan 2025"
    # Idempotent: re-running should produce no new entries.
    second_call = observe(
        candidate_id="rcm_v1_defensive_composite_01",
        output_dir=out_dir,
        cost_model_path="config/cost_model.yaml",
        top_n=10,
        up_to="2025-02-01",
    )
    assert second_call == [], "re-running observe must be idempotent"


# ── schema-bypass static guard (replaces R5 no-runner test) ─────────────


def test_runner_module_imports_schema():
    """Stronger structural invariant: every forward-package module that
    touches manifests must reference ``ForwardRunManifest`` so any
    write path goes through schema validation.
    """
    runner_src = Path(
        "core/research/forward/runner.py"
    ).read_text()
    assert "ForwardRunManifest" in runner_src
    io_src = Path(
        "core/research/forward/manifest_io.py"
    ).read_text()
    assert "ForwardRunManifest" in io_src


# ── decision_pending status-machine transition (codex Round-4) ──────────
#
# The PRD says ``observe()`` should move the manifest to
# ``decision_pending`` once the largest observed TD count reaches the
# largest configured ``decision_days`` checkpoint. The pre-fix code only
# ever transitioned ``not_started → in_progress``, leaving the manifest
# stuck at ``in_progress`` after the terminal day. The fix lives in
# ``_next_status_after_observe`` and is exercised by ``observe`` end-to-
# end, but the helper is unit-tested here directly so we don't need 60
# synthetic trading days per case.


def _make_td_run(n_td: int, *, label: str = None) -> "ForwardRun":  # type: ignore[name-defined]
    from core.research.forward.manifest_schema import ForwardRun
    return ForwardRun(
        checkpoint_label=label or f"TD{n_td:03d}",
        as_of_date=date(2026, 4, 24) + pd.Timedelta(days=n_td).to_pytimedelta(),
        n_observed_trading_days=n_td,
        cum_ret=0.0,
        max_dd=0.0,
        notes="synthetic",
    )


def test_observe_status_below_terminal_day_stays_in_progress():
    from core.research.forward.runner import _next_status_after_observe
    runs = [_make_td_run(1)]  # only TD001, terminal_day = 2
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.in_progress,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.in_progress


def test_observe_status_at_terminal_day_transitions_to_decision_pending():
    from core.research.forward.runner import _next_status_after_observe
    runs = [_make_td_run(1), _make_td_run(2)]   # last TD == terminal_day
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.in_progress,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.decision_pending


def test_observe_status_multi_day_catchup_crosses_terminal_day():
    """A multi-day catch-up that goes from below to past the terminal
    day in one observe() call must still land at decision_pending."""
    from core.research.forward.runner import _next_status_after_observe
    runs = [_make_td_run(1), _make_td_run(3)]  # crossed terminal_day=2
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.in_progress,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.decision_pending


def test_observe_status_ignores_non_TD_entries_for_terminal_check():
    """Non-TD audit / checkpoint / weekly entries do not contribute to
    the terminal-day check. A manifest with 3 DECIDE entries must NOT
    reach decision_pending unless the TD count itself qualifies.
    """
    from core.research.forward.manifest_schema import ForwardRun
    from core.research.forward.runner import _next_status_after_observe

    decide_entry = ForwardRun(
        checkpoint_label="DECIDE",
        as_of_date=date(2026, 4, 30),
        n_observed_trading_days=10,   # decoy: high count on a non-TD row
        cum_ret=0.0,
        max_dd=0.0,
        notes="user decision audit",
    )
    runs = [decide_entry, decide_entry, decide_entry, _make_td_run(1)]
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.in_progress,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.in_progress, (
        "non-TD entries' n_observed_trading_days must NOT count toward "
        "the terminal-day check; only TD-prefixed rows do"
    )


def test_observe_status_never_overwrites_terminal_status():
    """completed_success / completed_fail / aborted are user-driven
    terminal states. observe() must never push them back to
    in_progress or decision_pending.
    """
    from core.research.forward.runner import _next_status_after_observe
    # Build runs that WOULD trip decision_pending if status were not terminal.
    runs = [_make_td_run(2), _make_td_run(3)]
    for terminal in (
        ForwardRunStatus.completed_success,
        ForwardRunStatus.completed_fail,
        ForwardRunStatus.aborted,
    ):
        result = _next_status_after_observe(
            current_status=terminal,
            new_runs=runs,
            decision_days=[2],
        )
        assert result is terminal, (
            f"terminal status {terminal!r} must not be overwritten by observe()"
        )


def test_observe_status_decision_pending_is_sticky():
    """Once a manifest reaches decision_pending, subsequent observe()
    calls must keep it there — only decide() should move it forward.
    """
    from core.research.forward.runner import _next_status_after_observe
    runs = [_make_td_run(2), _make_td_run(3), _make_td_run(4)]
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.decision_pending,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.decision_pending


def test_observe_status_first_successful_observation_promotes_not_started():
    """Pre-existing contract: first successful observation moves
    not_started → in_progress (when terminal day not yet crossed)."""
    from core.research.forward.runner import _next_status_after_observe
    runs = [_make_td_run(1)]
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.not_started,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.in_progress


def test_observe_status_not_started_can_jump_directly_to_decision_pending():
    """Edge case: a manifest that goes from not_started straight past
    terminal day in one catch-up must land at decision_pending, not
    in_progress."""
    from core.research.forward.runner import _next_status_after_observe
    runs = [_make_td_run(1), _make_td_run(2)]
    result = _next_status_after_observe(
        current_status=ForwardRunStatus.not_started,
        new_runs=runs,
        decision_days=[2],
    )
    assert result is ForwardRunStatus.decision_pending
