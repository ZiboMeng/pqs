"""Unit tests for core/research/evaluation_policy.py.

P0.a Codex audit fix: verify QQQ governance unification.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from core.research.evaluation_policy import (
    EvaluationPolicy,
    get_policy,
    reload_policy,
    is_qqq_field,
    should_demote_qqq_gate,
    is_mining_qqq_disabled,
)


def _write_policy(tmp_path: Path, content: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "evaluation_policy.yaml"
    p.write_text(content)
    return p


def test_default_when_no_yaml_file(tmp_path):
    """Missing yaml → default (all overrides off)."""
    p = tmp_path / "nonexistent.yaml"
    pol = reload_policy(p)
    assert not pol.qqq_demote_kill_to_diagnostic
    assert not pol.qqq_mining_evaluator_disabled
    assert pol.qqq_field_patterns == ()
    assert not pol.qqq_governance_active


def test_yaml_loaded_correctly(tmp_path):
    content = dedent("""\
        schema_version: "1.0"
        effective_date: "2026-05-02"
        qqq_governance:
          demote_kill_to_diagnostic: true
          mining_evaluator_qqq_disabled: true
          qqq_field_patterns:
            - "*.excess_vs_qqq"
            - "*_vs_qqq"
    """)
    p = _write_policy(tmp_path, content)
    pol = reload_policy(p)
    assert pol.qqq_demote_kill_to_diagnostic
    assert pol.qqq_mining_evaluator_disabled
    assert pol.qqq_field_patterns == ("*.excess_vs_qqq", "*_vs_qqq")
    assert pol.qqq_governance_active


def test_is_qqq_field_pattern_match(tmp_path):
    content = dedent("""\
        qqq_governance:
          qqq_field_patterns:
            - "*.excess_vs_qqq"
            - "*_vs_qqq"
            - "*.beta_to_qqq"
    """)
    p = _write_policy(tmp_path, content)
    pol = reload_policy(p)
    assert is_qqq_field("validation.2025.excess_vs_qqq", policy=pol)
    assert is_qqq_field("beta.beta_to_qqq", policy=pol)
    assert is_qqq_field("year_2025_vs_qqq", policy=pol)
    assert not is_qqq_field("validation.2025.excess_vs_spy", policy=pol)
    assert not is_qqq_field("concentration.top1_max", policy=pol)


def test_is_qqq_field_substring_fallback_no_patterns(tmp_path):
    """No patterns configured → fall back to substring match on 'qqq'."""
    p = _write_policy(tmp_path, "qqq_governance: {}")
    pol = reload_policy(p)
    assert is_qqq_field("validation.2025.excess_vs_qqq", policy=pol)
    assert is_qqq_field("foo_QQQ_bar", policy=pol)
    assert not is_qqq_field("validation.spy", policy=pol)


def test_should_demote_when_policy_off(tmp_path):
    p = _write_policy(tmp_path, "qqq_governance:\n  demote_kill_to_diagnostic: false\n")
    pol = reload_policy(p)
    assert not should_demote_qqq_gate("validation.2025.excess_vs_qqq", policy=pol)


def test_should_demote_when_policy_on(tmp_path):
    content = dedent("""\
        qqq_governance:
          demote_kill_to_diagnostic: true
          qqq_field_patterns: ["*.excess_vs_qqq"]
    """)
    p = _write_policy(tmp_path, content)
    pol = reload_policy(p)
    assert should_demote_qqq_gate("validation.2025.excess_vs_qqq", policy=pol)
    # Non-QQQ field: NOT demoted even with policy on
    assert not should_demote_qqq_gate("validation.2025.excess_vs_spy", policy=pol)


def test_should_demote_unconditional_when_no_field(tmp_path):
    """should_demote_qqq_gate('') returns True if policy says demote."""
    content = "qqq_governance:\n  demote_kill_to_diagnostic: true\n"
    p = _write_policy(tmp_path, content)
    pol = reload_policy(p)
    assert should_demote_qqq_gate("", policy=pol)


def test_is_mining_qqq_disabled_flag(tmp_path):
    p = _write_policy(tmp_path, "qqq_governance:\n  mining_evaluator_qqq_disabled: true\n")
    pol = reload_policy(p)
    assert is_mining_qqq_disabled(policy=pol)

    p2 = _write_policy(tmp_path / "subdir", "qqq_governance:\n  mining_evaluator_qqq_disabled: false\n")
    pol2 = reload_policy(p2)
    assert not is_mining_qqq_disabled(policy=pol2)


def test_cache_busted_by_reload(tmp_path):
    """reload_policy must bust the lru_cache."""
    p = _write_policy(tmp_path, "qqq_governance:\n  demote_kill_to_diagnostic: false\n")
    pol1 = reload_policy(p)
    assert not pol1.qqq_demote_kill_to_diagnostic

    p.write_text("qqq_governance:\n  demote_kill_to_diagnostic: true\n")
    pol2 = reload_policy(p)
    assert pol2.qqq_demote_kill_to_diagnostic


def test_production_policy_yaml_loads():
    """Verify production config/evaluation_policy.yaml is well-formed
    AND enables QQQ governance unification per Codex P0.a fix."""
    proj = Path(__file__).resolve().parents[3]
    prod = proj / "config" / "evaluation_policy.yaml"
    assert prod.exists(), "P0.a should ship config/evaluation_policy.yaml"
    pol = reload_policy(prod)
    assert pol.qqq_demote_kill_to_diagnostic, \
        "Production policy must demote QQQ kill_candidate to diagnostic"
    assert pol.qqq_mining_evaluator_disabled, \
        "Production policy must disable old MiningEvaluator QQQ gate"
    assert pol.qqq_governance_active
    # Restore default policy for downstream tests
    reload_policy(None)


def test_policy_dataclass_frozen():
    """EvaluationPolicy is immutable to prevent runtime mutation drift."""
    pol = EvaluationPolicy()
    with pytest.raises(Exception):
        pol.qqq_demote_kill_to_diagnostic = True  # type: ignore
