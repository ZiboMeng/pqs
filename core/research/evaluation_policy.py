"""Runtime evaluation policy override layer.

Authority: CLAUDE.md "Benchmark Outperformance Rule" +
docs/memos/20260502-qqq_benchmark_deprecation.md
Shipped 2026-05-14 (P0.a) per comprehensive audit finding —
Codex caught governance drift between docs (QQQ deprecated) and
code (v1/v2 yaml + MiningEvaluator + backtest.yaml still HARD).

Design: This module reads `config/evaluation_policy.yaml` at import
time and exposes flags that acceptance evaluators + mining evaluators
consult. The yaml files (temporal_split v1/v2/v3, backtest.yaml) are
left UNCHANGED to preserve `locked_after_first_use` invariant; this
runtime layer is what unifies behavior.

API:
    from core.research.evaluation_policy import (
        get_policy, is_qqq_field, should_demote_qqq_gate,
        is_mining_qqq_disabled,
    )

    pol = get_policy()
    if is_qqq_field(gate.field) and should_demote_qqq_gate():
        # treat as diagnostic_only regardless of yaml action
        ...
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


_POLICY_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "evaluation_policy.yaml"


@dataclass(frozen=True)
class EvaluationPolicy:
    """Runtime overrides for acceptance + mining evaluators."""

    schema_version: str = "1.0"
    effective_date: str = "2026-05-02"

    # QQQ governance
    qqq_demote_kill_to_diagnostic: bool = False
    qqq_mining_evaluator_disabled: bool = False
    qqq_field_patterns: tuple = ()

    @property
    def qqq_governance_active(self) -> bool:
        """True if ANY qqq override is active."""
        return self.qqq_demote_kill_to_diagnostic or self.qqq_mining_evaluator_disabled


def _load_policy_yaml(path: Path) -> dict:
    if not path.exists():
        logger.info(
            "evaluation_policy.yaml not found at %s — using defaults (no overrides)",
            path,
        )
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def get_policy(path: Optional[Path] = None) -> EvaluationPolicy:
    """Load and cache evaluation policy. Pass `path` for test injection."""
    p = path if path is not None else _POLICY_PATH
    data = _load_policy_yaml(p)
    qqq = data.get("qqq_governance", {}) or {}
    return EvaluationPolicy(
        schema_version=str(data.get("schema_version", "1.0")),
        effective_date=str(data.get("effective_date", "2026-05-02")),
        qqq_demote_kill_to_diagnostic=bool(qqq.get("demote_kill_to_diagnostic", False)),
        qqq_mining_evaluator_disabled=bool(qqq.get("mining_evaluator_qqq_disabled", False)),
        qqq_field_patterns=tuple(qqq.get("qqq_field_patterns", []) or []),
    )


def reload_policy(path: Optional[Path] = None) -> EvaluationPolicy:
    """Bust the cache and reload — for tests + late binding."""
    get_policy.cache_clear()
    return get_policy(path)


def is_qqq_field(field_name: str, policy: Optional[EvaluationPolicy] = None) -> bool:
    """Check if a gate field is QQQ-related per policy patterns.

    Uses fnmatch-style glob patterns: e.g. `*.excess_vs_qqq` matches
    `validation.2025.excess_vs_qqq`. Case-sensitive.
    """
    pol = policy if policy is not None else get_policy()
    if not pol.qqq_field_patterns:
        # Fallback: substring match for safety when patterns not configured
        return "qqq" in field_name.lower()
    for pattern in pol.qqq_field_patterns:
        if fnmatch.fnmatchcase(field_name, pattern):
            return True
    return False


def should_demote_qqq_gate(field_name: str = "",
                            policy: Optional[EvaluationPolicy] = None) -> bool:
    """True if QQQ gate on `field_name` should be demoted to diagnostic_only.

    If `field_name` is empty, returns True iff policy says demote unconditionally.
    """
    pol = policy if policy is not None else get_policy()
    if not pol.qqq_demote_kill_to_diagnostic:
        return False
    if not field_name:
        return True
    return is_qqq_field(field_name, policy=pol)


def is_mining_qqq_disabled(policy: Optional[EvaluationPolicy] = None) -> bool:
    """True if MiningEvaluator (core/mining/evaluator.py) QQQ gate disabled."""
    pol = policy if policy is not None else get_policy()
    return pol.qqq_mining_evaluator_disabled


__all__ = [
    "EvaluationPolicy",
    "get_policy",
    "reload_policy",
    "is_qqq_field",
    "should_demote_qqq_gate",
    "is_mining_qqq_disabled",
]
