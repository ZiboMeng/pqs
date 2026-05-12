"""Regression tests for forward runner ``evidence_config`` opt-in
(PRD 20260512 Step 3).

Lazy-migration invariant under test:
  - Pre-PRD spec without ``evidence_config`` (None) → forward runner
    passes ``track_per_cell=False`` to ``compute_signal_input_hash``
    → ``per_cell_digest`` stays empty (matches RCMv1 / Cand-2 /
    trial9_diversifier_001 behavior bit-for-bit).
  - Spec with ``evidence_config.track_signal_input_per_cell=True``
    → ``compute_signal_input_hash`` called with ``track_per_cell=True``
    → ``per_cell_digest`` is populated.

These tests target ``compute_signal_input_hash`` directly via the
opt-in flag value the runner would resolve, plus a schema round-trip
on ``FrozenStrategySpec`` to ensure yaml ⇄ dataclass works.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from core.research.forward.bar_hash import compute_signal_input_hash
from core.research.frozen_spec import FeatureEntry, FrozenStrategySpec


# ── fixtures ────────────────────────────────────────────────────────────


def _minimal_spec(evidence_config=None) -> FrozenStrategySpec:
    return FrozenStrategySpec(
        candidate_id="test_candidate",
        strategy_version="test-v1",
        source_trial_id="abc123",
        feature_set=[FeatureEntry(name="ret_1d", weight=1.0)],
        benchmark_relative_summary={"note": "n/a"},
        oos_holdout_summary={"folds": 4},
        robustness_summary={"range": [0.0, 1.0]},
        decision_memo="/tmp/memo.md",
        evidence_config=evidence_config,
    )


def _make_panel():
    """Small panel: 30 trading days × 4 syms × close + open."""
    idx = pd.bdate_range("2026-04-01", periods=30)
    close = pd.DataFrame(
        {s: 100.0 + np.arange(len(idx)) * 0.1 for s in ["AAA", "BBB", "CCC", "DDD"]},
        index=idx,
    )
    open_df = close.shift(1).fillna(100.0)
    return {"close": close, "open": open_df}


# ── §7.1 legacy preservation: evidence_config=None ─────────────────────


def test_legacy_spec_no_evidence_config_keeps_empty_per_cell_digest():
    """A spec without evidence_config (None) → runner's resolved
    track_per_cell is False → compute_signal_input_hash returns empty
    per_cell_digest. Mirrors pre-PRD RCMv1 / Cand-2 / trial9_001 behavior."""
    spec = _minimal_spec(evidence_config=None)
    panel = _make_panel()
    # Mirror runner.py:1041 resolution
    track = bool((spec.evidence_config or {}).get("track_signal_input_per_cell", False))
    assert track is False

    h, inputs = compute_signal_input_hash(
        spec=spec, universe=["AAA", "BBB", "CCC", "DDD"], panel=panel,
        as_of_date=date(2026, 4, 30), track_per_cell=track,
    )
    assert inputs.per_cell_digest == {}
    # Sanity: rolling hash is deterministic
    h2, _ = compute_signal_input_hash(
        spec=spec, universe=["AAA", "BBB", "CCC", "DDD"], panel=panel,
        as_of_date=date(2026, 4, 30), track_per_cell=track,
    )
    assert h == h2


# ── §7.2 opt-in: track_signal_input_per_cell=True ─────────────────────


def test_opt_in_evidence_config_populates_per_cell_digest():
    spec = _minimal_spec(
        evidence_config={"track_signal_input_per_cell": True}
    )
    panel = _make_panel()
    track = bool((spec.evidence_config or {}).get("track_signal_input_per_cell", False))
    assert track is True

    h, inputs = compute_signal_input_hash(
        spec=spec, universe=["AAA", "BBB", "CCC", "DDD"], panel=panel,
        as_of_date=date(2026, 4, 30), track_per_cell=track,
    )
    # 4 syms in universe with non-empty per-cell digests
    assert len(inputs.per_cell_digest) == 4
    assert set(inputs.per_cell_digest.keys()) == {"AAA", "BBB", "CCC", "DDD"}


def test_opt_in_false_explicit_keeps_empty_digest():
    """evidence_config={track_signal_input_per_cell: False} explicit
    → same behavior as omitting."""
    spec = _minimal_spec(
        evidence_config={"track_signal_input_per_cell": False}
    )
    track = bool((spec.evidence_config or {}).get("track_signal_input_per_cell", False))
    assert track is False
    panel = _make_panel()
    _, inputs = compute_signal_input_hash(
        spec=spec, universe=["AAA", "BBB", "CCC", "DDD"], panel=panel,
        as_of_date=date(2026, 4, 30), track_per_cell=track,
    )
    assert inputs.per_cell_digest == {}


# ── §7.3 hash stability: rolling hash same regardless of per_cell flag ─


def test_rolling_hash_invariant_to_track_per_cell():
    """The rolling hash (the returned hex digest) is identical whether
    track_per_cell=True or False. Only per_cell_digest differs. This
    invariant is what lets revalidate at revalidate.py:277 recompute
    with bool(stored_digest) and still get a comparable hash."""
    spec = _minimal_spec()
    panel = _make_panel()
    h_false, _ = compute_signal_input_hash(
        spec=spec, universe=["AAA", "BBB"], panel=panel,
        as_of_date=date(2026, 4, 30), track_per_cell=False,
    )
    h_true, _ = compute_signal_input_hash(
        spec=spec, universe=["AAA", "BBB"], panel=panel,
        as_of_date=date(2026, 4, 30), track_per_cell=True,
    )
    assert h_false == h_true, (
        "rolling hash must be invariant to track_per_cell so revalidate "
        "can recompute under the entry's own setting without spurious "
        "diffs (revalidate.py:277 contract)"
    )


# ── §7.4 schema round-trip ─────────────────────────────────────────────


def test_yaml_round_trip_preserves_evidence_config():
    spec = _minimal_spec(
        evidence_config={"track_signal_input_per_cell": True}
    )
    y = spec.to_yaml()
    assert "evidence_config" in y
    assert "track_signal_input_per_cell" in y
    spec2 = FrozenStrategySpec.from_yaml(y)
    assert spec2.evidence_config == {"track_signal_input_per_cell": True}


def test_yaml_round_trip_omits_none_evidence_config():
    """When evidence_config is None, to_dict / to_yaml omit the key
    entirely (preserves backward-compatible yaml shape)."""
    spec = _minimal_spec(evidence_config=None)
    d = spec.to_dict()
    assert "evidence_config" not in d
    y = spec.to_yaml()
    assert "evidence_config" not in y


def test_from_dict_handles_missing_evidence_config():
    """Pre-PRD yaml without evidence_config loads with None (default)."""
    d = {
        "candidate_id": "legacy",
        "strategy_version": "legacy-v1",
        "source_trial_id": "abc",
        "feature_set": [{"name": "ret_1d", "weight": 1.0}],
        "benchmark_relative_summary": {"note": "n/a"},
        "oos_holdout_summary": {"n": 1},
        "robustness_summary": {"r": [0, 1]},
        "decision_memo": "/tmp/memo.md",
    }
    spec = FrozenStrategySpec.from_dict(d)
    assert spec.evidence_config is None


def test_from_dict_passes_through_explicit_evidence_config():
    d = {
        "candidate_id": "opt_in",
        "strategy_version": "opt-in-v1",
        "source_trial_id": "abc",
        "feature_set": [{"name": "ret_1d", "weight": 1.0}],
        "benchmark_relative_summary": {"note": "n/a"},
        "oos_holdout_summary": {"n": 1},
        "robustness_summary": {"r": [0, 1]},
        "decision_memo": "/tmp/memo.md",
        "evidence_config": {"track_signal_input_per_cell": True},
    }
    spec = FrozenStrategySpec.from_dict(d)
    assert spec.evidence_config == {"track_signal_input_per_cell": True}


# ── §7.5 unknown keys still flow into extras (not into evidence_config) ─


def test_evidence_config_does_not_capture_extras():
    """A yaml field NOT in the PRD's documented evidence_config shape
    should not be silently absorbed — it should be either in extras or
    inside the explicit evidence_config dict if the user put it there."""
    d = {
        "candidate_id": "weird",
        "strategy_version": "weird-v1",
        "source_trial_id": "abc",
        "feature_set": [{"name": "ret_1d", "weight": 1.0}],
        "benchmark_relative_summary": {"note": "n/a"},
        "oos_holdout_summary": {"n": 1},
        "robustness_summary": {"r": [0, 1]},
        "decision_memo": "/tmp/memo.md",
        "evidence_config": {
            "track_signal_input_per_cell": True,
            "future_flag_v2": "reserved",
        },
        "unknown_top_level": "should_go_to_extras",
    }
    spec = FrozenStrategySpec.from_dict(d)
    assert spec.evidence_config["track_signal_input_per_cell"] is True
    assert spec.evidence_config["future_flag_v2"] == "reserved"
    assert spec.extras.get("unknown_top_level") == "should_go_to_extras"
