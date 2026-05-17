"""GAP1-4 — end-to-end universe identity propagation (P4-A1, 2026-05-16).

User requirement: a candidate mined on a given universe must carry that
identity so backtest / forward / promote use the SAME universe, while
the executable default stays byte-for-byte unchanged (D6 / P4-A2).

These tests pin the carrier (FrozenStrategySpec.universe) + the
byte-identical legacy default + the GAP3 forward-init derivation rule.
"""
from __future__ import annotations

import inspect

from core.research.frozen_spec import FrozenStrategySpec

_BASE = {
    "candidate_id": "c", "strategy_version": "v-2026", "source_trial_id": "t",
    "feature_set": [{"name": "f", "weight": 1.0}],
    "benchmark_relative_summary": "a", "oos_holdout_summary": "b",
    "robustness_summary": "c", "decision_memo": "m",
}


def test_legacy_spec_universe_is_none_and_byte_identical():
    """Pre-existing candidates (no `universe` key) → None → to_dict omits
    it → serialization byte-identical (RCMv1/Cand-2/trial9/cycle06/08/pead)."""
    s = FrozenStrategySpec.from_dict(dict(_BASE))
    assert s.universe is None
    assert "universe" not in s.to_dict()


def test_expanded_universe_roundtrips():
    s = FrozenStrategySpec.from_dict({**_BASE, "universe": "expanded_v1"})
    assert s.universe == "expanded_v1"
    assert s.to_dict()["universe"] == "expanded_v1"
    assert FrozenStrategySpec.from_dict(s.to_dict()).universe == "expanded_v1"


def test_explicit_executable_roundtrips():
    s = FrozenStrategySpec.from_dict({**_BASE, "universe": "executable"})
    assert s.universe == "executable"
    assert s.to_dict()["universe"] == "executable"


def test_forward_init_derives_universe_override_from_spec():
    """GAP3: init() must contain the rule mapping spec.universe →
    universe_yaml_override (None/executable → legacy path; expanded_v1 →
    universe_expanded_v1.yaml; unknown → ValueError)."""
    from core.research.forward import runner
    src = inspect.getsource(runner.init)
    assert "spec.universe" in src
    assert "universe_expanded_v1.yaml" in src
    assert 'spec.universe != "executable"' in src
    # explicit kwarg must still win (back-compat with C10-2-B callers)
    assert "universe_yaml_override is None" in src


def test_mining_summary_records_universe():
    """GAP1: run_research_miner._write_artifacts writes summary['universe']."""
    import scripts.run_research_miner as rrm
    src = inspect.getsource(rrm._write_artifacts)
    assert '"universe": universe_name' in src


def test_backtest_and_promote_expose_universe_flag():
    """GAP2/GAP4: run_backtest + promote_strategy expose --universe with
    executable default kept byte-identical (original derivation under else
    / universe.yaml default)."""
    import scripts.run_backtest as rb
    import scripts.promote_strategy as ps
    rb_src = inspect.getsource(rb)
    ps_src = inspect.getsource(ps)
    for src in (rb_src, ps_src):
        assert 'add_argument("--universe"' in src
        assert 'choices=["executable", "expanded_v1"]' in src
        assert 'default="executable"' in src
    # GAP2 D6-safe: executable keeps the original cfg.universe derivation
    assert "list(uni.seed_pool)" in rb_src and 'if getattr(args, "universe"' in rb_src
    # GAP4: fingerprint picks the matching universe yaml, default unchanged
    assert "universe_expanded_v1.yaml" in ps_src
    assert '"universe": universe_name' in ps_src
